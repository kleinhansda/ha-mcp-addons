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

`mediapipe` verlangt `opencv-contrib-python` (mit GUI-Bibliotheken). Für die Gesichtserkennung
reicht die Headless-Variante, deshalb wird mit `--no-deps` installiert und die tatsächlich
gebrauchten Pakete stehen einzeln in `requirements.in` (gefunden durch Import-Test). matplotlib
lädt MediaPipe beim Import mit. `libmediapipe.so` ist gegen `libEGL` und `libGLESv2` gelinkt,
auch wenn auf der CPU gerechnet wird. Beides gibt es als manylinux-Wheel für aarch64 und amd64
mit glibc 2.28, passend zu Debian Bookworm.

Das Gesichtsmodell `face_landmarker.task` (float16, 3,7 MB) kommt von Google Storage und wird
gegen seine SHA-256 geprüft.

## Verfahren

- **Schräglage:** Liniensegmente (LSD) auf 2000 px. Senkrechte: Winkel gegen die waagrechte
  Bildposition robust linear angepasst, der Wert in der Bildmitte ist die Schräglage. So stören
  stürzende Linien bei Aufnahmen nach oben nicht. Linien in Personenbereichen (unter jedem
  Gesicht) zählen nicht, Kleidungsfalten hatten sonst −2,7° statt 0° ergeben. Ohne genug
  Senkrechte: Horizont. Immer nur ein Vorschlag, Claude prüft mit `vorschau`.
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
