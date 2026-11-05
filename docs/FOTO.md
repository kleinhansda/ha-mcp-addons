# Foto MCP: Hintergrund

Hintergrund zum Add-on: was getestet wurde, was entschieden wurde und warum.
Bedienung steht in [foto_mcp/DOCS.md](../foto_mcp/DOCS.md), das gemeinsame Muster in [ARCHITEKTUR.md](ARCHITEKTUR.md).

## Ziel

Fotos aus dem Urlaub sichten, aussortieren, begradigen, motivgerecht zuschneiden und dezent
retuschieren, gesteuert von Claude, ohne dass ein PC laufen muss. Vorher lief das als Skript auf
einem Laptop (über die Geräte-Brücke der Claude-App). Das Add-on bringt denselben Ablauf auf das
Home-Assistant-Gerät.

## Warum ein eigener Server

| Weg | Ergebnis |
|---|---|
| PhotoCraft (ArtCraft MCP) | Kann Tonwert, Drehen, Zuschnitt, Reparaturpinsel, Weichzeichner. `image.detectFaces` liefert nur 5 Punkte je Gesicht. Für Schräglage-Messung, Gesichter mit 478 Punkten, Flecken-Erkennung und eine genaue Hautmaske fehlt die Analyse |
| Dateien über WebDAV in die Cloud-Umgebung von Claude | wd-mcp überträgt höchstens 10 MB je Datei, Kamera-JPEGs haben 10 bis 20 MB, und jedes Bild ginge base64-kodiert durch den Chat |
| Vierter Dienst im ArtCraft-Add-on | Spart einen OIDC-Client, aber ArtCraft bekommt fast täglich App-Updates, und jedes Update baut auf dem Gerät auch die rund 450 MB Python-Pakete neu |
| **Eigenes Add-on** | Eigene Version, eigener Takt, gleicher Arbeitsordner wie ArtCraft |

Der Server spricht MCP über stdio (JSON-RPC 2.0, Protokoll 2025-06-18) ohne SDK: Er braucht nur
`initialize`, `tools/list`, `tools/call` und `ping`. Das hält die Abhängigkeiten klein.

## Bibliotheken

| Paket | Wofür | Lizenz |
|---|---|---|
| OpenCV (opencv-python-headless 4.14) | Liniensegmente (LSD) für die Schräglage, Drehen, Entrauschen, Filter, Inpainting | Apache 2.0 |
| MediaPipe 1.2 Face Landmarker | 478 Punkte je Gesicht: Umriss, Augen, Brauen, Lippen | Apache 2.0 |
| Pillow | JPEG lesen und schreiben samt EXIF und ICC-Profil | MIT-CMU |
| NumPy | Rechnen | BSD |
| NanoDet-Plus (OpenCV Model Zoo, ONNX über cv2.dnn) | Objekte (COCO, 80 Klassen) für Bildtyp, Personen ohne Gesicht, Motivboxen | Apache 2.0 |
| MobileNetV2 (OpenCV Model Zoo, ONNX über cv2.dnn) | Szenenhinweise aus ImageNet (Berge, Wasser, Architektur, Essen, Hunderassen) | Apache 2.0 |

`mediapipe` verlangt `opencv-contrib-python` (mit GUI-Bibliotheken). Für die Gesichtserkennung
reicht die Headless-Variante, deshalb wird mit `--no-deps` installiert und die tatsächlich
gebrauchten Pakete stehen einzeln in `requirements.in` (gefunden durch Import-Test). matplotlib
lädt MediaPipe beim Import mit. `libmediapipe.so` ist gegen `libEGL` und `libGLESv2` gelinkt,
auch wenn auf der CPU gerechnet wird. Beides gibt es als manylinux-Wheel für aarch64 und amd64
mit glibc 2.28, passend zu Debian Bookworm.

Das Gesichtsmodell `face_landmarker.task` (float16, 3,7 MB) kommt von Google Storage und wird
gegen seine SHA-256 geprüft. Objekt- und Szenenmodell kommen aus dem OpenCV Model Zoo von einem
festen Commit (`media.githubusercontent.com`), ebenfalls mit SHA-256. Beide laufen über
`cv2.dnn`, es braucht kein `onnxruntime`.

**Warum keine Segmentierung per Modell (z. B. SegFormer auf ADE20K, mit Himmel, Baum, Berg,
Meer):** Das wäre für Bildtyp und Bereichsmasken genauer. Die üblichen Quellen liegen auf Hugging
Face und ließen sich in der Entwicklungsumgebung weder laden noch testen. Himmel, Grün und Wasser
kommen deshalb aus Farbe, Helligkeit und Struktur; ein Segmentierungsmodell ist als Ausbau
vorgesehen (siehe Offene Punkte).

## Verfahren

- **Schräglage (ab 1.2.0):** zuerst der echte Horizont. Himmel = glatte, helle, blaue oder graue
  Fläche, die oben an den Bildrand stößt, an deutlichen waagrechten Kanten getrennt (sonst wächst
  ruhiges Meer mit dem Himmel zusammen); helle Wolken dürfen Struktur haben. Je Spalte die Zeile
  unter dem tiefsten Himmelspixel, robuste Gerade (Ausreißer wie Masten und Türme fallen heraus),
  mindestens halbe Breite, Rest unter 1 % der Höhe, höchstens 5°. Zweite Kandidatin: die oberste
  Wasserzeile (Uferlinie). Der Winkel wird mit LSD-Segmenten nahe der Grenze auf 2000 px
  nachgemessen. Dann Senkrechte: Winkel gegen die waagrechte Bildposition robust linear
  angepasst, der Wert in der Bildmitte ist die Schräglage, so stören stürzende Linien nicht.
  Widerspricht der Horizont starken Senkrechten um mehr als 1°, gelten die Senkrechten.
  Zuletzt übrige Waagrechte. Linien in Personenbereichen (Gesichter und erkannte Personen)
  zählen nicht, Kleidungsfalten hatten sonst −2,7° statt 0° ergeben. Immer nur ein Vorschlag,
  Claude prüft mit `vorschau`.
- **Bildtyp:** Reihenfolge Gruppe/Porträt (Hauptgesichter oder große Personen), Tier, Essen,
  Architektur (Szene ≥ 40 %), Meer (Wasser ≥ 12 % und Himmel, oder Szene Wasser), Architektur
  (Szene ≥ 20 % oder viele Senkrechte), Berge, Baum (eine frei stehende Grünfläche mit Himmel
  daneben), Landschaft, sonst `sonstiges`. Analysiert wird das unbearbeitete Bild auf 2000 px.
- **Gesichter:** Gesamtbild auf 2000 px plus 3 × 3 überlappende Kacheln, damit auch kleine
  Gesichter (Ganzkörper, Gruppen) gefunden werden. Für den Zuschnitt zählen nur Gesichter mit
  mindestens 45 % der Breite des größten.
- **Zuschnitt:** Kandidaten 3:2, 4:3, 1:1, 4:5, 3:4, 2:3. Bewertet nach Fläche, Motivanteil
  (Nahaufnahme ca. 50 %, Ganzkörper ca. 28 %), Abstand zur Mitte, Kopf drin, bei Ganzkörper
  Füße drin. Augen auf dem oberen Drittel.
- **Retusche:** Hautmaske aus Gesichtsumriss ohne Augen, Brauen, Lippen und Nasenlöcher, nur
  hautfarbene Pixel, ohne Bereiche mit viel Feinstruktur (Bart, Stoppeln, Haarsträhnen). Flecken:
  kleine, runde Stellen, deutlich röter oder dunkler als die Umgebung, per Inpainting entfernt
  und mit Körnung versehen. Rötung über dem Haut-Median um 40 % zurück. Glätten per
  Frequenztrennung, 75 % der feinen Struktur bleiben, Wirkung 35 %.

## Tests

Am 2026-11-05 (1.2.0), x86, Python 3.13 mit opencv-python-headless 4.14.0.94 und numpy 2.2.6,
ohne Gesichtsmodell (Google Storage war in der Testumgebung nicht erreichbar, Gesichter als leer
angenommen):

- `selbsttest.py` komplett grün, darunter neu: synthetisches Meer, um 2° gekippt → −2,0° aus dem
  Horizont; Gitter weiterhin −2,0° aus den Senkrechten; Protokoll, Rezept, `anpassen`.
- Beispielbilder aus den OpenCV-Repos: Hafen mit Spiegelung → `meer`, Uferlinie −0,2°; Hotel
  → `architektur`, −1,4° aus Senkrechten; Hund vor Fahrrad → `tier` (NanoDet sagte Katze,
  ImageNet Malamute), Ausschnitt 3:4 um den Hund; Obst → `essen`; Fußballer → `portraet` über die
  Person ohne Gesicht; Pont du Gard → `architektur`; Straße mit Passant → `architektur`, nicht
  Porträt. Kein Testbild für Baum, Berge, Gruppe: diese Regeln sind ungetestet.
- Szenenanalyse 0,1 bis 0,5 s je Bild.

Am 2026-10-31 in einer x86-Umgebung mit Python 3.11 und genau den Pins aus `requirements.txt`:

- `selbsttest.py` (auch Teil von `mcp-selftest`): Schräglage eines synthetischen, um 2° gekippten
  Gitters −2,0°, Gesichtsmodell lädt, Sichtung, Vorschau, Job mit Ergebnisdateien, Original
  unverändert, Pfad außerhalb abgelehnt.
- Drei Kamera-Fotos (20 MP): Sichtung 1 s, Schräglage Burghof −0,94° (wie von Hand ermittelt),
  Ganzkörperbild 0° und Gesicht gefunden, Selfie mit zwei Gesichtern, Retusche 5 und 9 Flecken,
  Bart unverändert. Optimieren 3 Bilder 48 s, Retusche 37 s.
- Build und Selbsttest auf aarch64 laufen in der CI (`build.yml`, QEMU). Echte Laufzeiten auf
  dem Raspberry Pi 4 stehen noch aus.

## Offene Punkte

- [ ] Laufzeiten und Speicher auf dem Raspberry Pi 4 messen und in DOCS.md eintragen
- [ ] Neue Versionen der Python-Pakete automatisch prüfen (bisher: `requirements.in` von Hand,
      dann `foto_lock.py`). Der Proxy wird wie bei allen Add-ons von `update.yml` aktualisiert
- [ ] Leberflecken besser von Pickeln unterscheiden (Größe, Rand, Farbe)
- [ ] Bildtypen Baum, Berge, Gruppe an echten Fotos prüfen und Schwellen nachziehen
- [ ] Segmentierungsmodell (z. B. SegFormer-B0 auf ADE20K) für Himmel, Baum, Berg, Wasser statt
      Farbheuristik, wenn es sich mit fester Prüfsumme einbinden und testen lässt
- [ ] Perspektivkorrektur (Trapez) für Architektur, aus den Senkrechten, die die Messung schon findet
