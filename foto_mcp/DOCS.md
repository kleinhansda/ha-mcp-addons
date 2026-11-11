# Foto MCP

Ein eigener MCP-Server für Urlaubs- und Alltagsfotos, als Remote-Connector für Claude, auch für
die Smartphone-App. Er arbeitet direkt auf dem Home-Assistant-Gerät, die Fotos verlassen es
nicht. Claude bekommt nur verkleinerte Vorschauen zur Kontrolle. Davor sitzt
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy) als OAuth-Server mit Login über deinen
OIDC-Anbieter (z. B. Pocket ID).

Hintergrund und Entscheidungen:
[docs/FOTO.md](https://github.com/kleinhansda/ha-addons/blob/main/docs/FOTO.md).
Gemeinsames Muster aller Add-ons:
[docs/ARCHITEKTUR.md](https://github.com/kleinhansda/ha-addons/blob/main/docs/ARCHITEKTUR.md).

## Werkzeuge

| Tool | Wofür |
|---|---|
| `ordner_sichten` | EXIF (Kamera, Brennweite, Blende, Zeit, ISO, Aufnahmezeit), Schärfe, Helligkeit, Bildtyp, byte-gleiche Kopien, Serien, Kontaktbogen (24 Bilder je Seite) |
| `vorschau` | Bis zu 6 Bilder nebeneinander mit Hilfslinien, wahlweise gedreht und ausgeschnitten. Zum Prüfen der Schräglage |
| `neigung_messen` | Vorschlag für die Schräglage (Horizont, sonst Senkrechte, sonst Waagrechte), Bildtyp mit Begründung, Objekte, Flächenanteile, Gesichter |
| `aussortieren` | Verschiebt Bilder nach `_aussortiert/`. Löscht nie, überschreibt nie |
| `optimieren` | Job: Tonwert, Entrauschen ab ISO 400, Schärfen, Begradigen, Bildtyp und dessen Regel (Zuschnitt, Look, Retusche), Rezept, eigene Regler, Effekte. Schreibt `final/<name>_final.jpg` und ein Protokoll |
| `anpassen` | Job: nur Regler und Effekte, ohne Tonwert, Drehung und Zuschnitt, z. B. auf `_final.jpg`. Schreibt `<name>_angepasst.jpg` |
| `rezept_speichern`, `rezepte` | Looks als Rezept im Arbeitsordner speichern und anzeigen |
| `retusche` | Job: dezente Hautretusche (Flecken, Rötung, minimal glätten). Augen, Brauen, Lippen, Bart und Haare bleiben unberührt. Schreibt `<name>_retusche.jpg` |
| `job_status` | Fortschritt, Ergebnisse je Bild, Protokoll und Vorschauen (Zuschnitt mit Drittel- und Mittellinie, vorher/nachher je Gesicht) |

Originale werden nie verändert. Ergebnisse haben immer ein Suffix (`_final`, `_bw`, `_retusche`,
`_angepasst` …) und dürfen bei einem neuen Lauf überschrieben werden. Protokolle und Rezepte
werden nie überschrieben (Protokolle haben Zeit und Job-ID im Namen, Rezepte nur mit
`ueberschreiben: true`).

## Schräglage

1. **Horizont**: die Grenze zwischen Himmel und Land oder Wasser bzw. die Uferlinie, wenn sie
   über mindestens die halbe Breite gerade verläuft. Masten, Türme und Bäume fallen als Ausreißer
   heraus. Der Winkel wird an der Kante in höherer Auflösung nachgemessen.
2. **Senkrechte Kanten** (Hauskanten, Fenster, Masten), stürzende Linien herausgerechnet. Sie
   gelten auch, wenn ein „Horizont“ ihnen um mehr als 1° widerspricht: Dann war es meist eine
   Dachkante in Perspektive.
3. **Übrige waagrechte Linien**, nur bis ±3°.

Linien in Personenbereichen zählen nicht (Gesichter und Objekterkennung). Unter 0,3° und über 6°
wird nicht gedreht. Das Ergebnis bleibt ein Vorschlag: mit `vorschau` prüfen.

## Bildtypen und Regeln

| Typ | Erkannt an | Zuschnitt | Look (Regler) |
|---|---|---|---|
| `portraet` | 1 Hauptperson (Gesicht, oder große Person ohne Gesicht) | Motiv: Augen auf dem oberen Drittel, Tier daneben bleibt drin | Schatten +10, Wärme +3, Vignette +10, Retusche |
| `gruppe` | ≥ 2 Hauptpersonen | Motiv: alle drin | Schatten +15, Lichter −10 |
| `tier` | Hund, Katze, Pferd … groß genug, keine Person | Motiv | Struktur +10, Schatten +5 |
| `baum` | eine frei stehende Grünfläche mit Himmel daneben | Motiv | Struktur +15, Vignette +15 |
| `landschaft` | viel Grün oder Himmel | Originalformat | Atmosphäre +15, Struktur +10, Sättigung +5 |
| `berge` | Szene Berge, unruhige Himmelsgrenze | Originalformat | Struktur +20, Atmosphäre +10, Himmel: Helligkeit −8 |
| `meer` | Wasser und Himmel, Szene Wasser | Horizont auf ein Drittel (Höhe bis 85 %) | Wärme +5, Lichter −15 |
| `architektur` | Szene Architektur, viele senkrechte Kanten | Originalformat | Struktur +15 |
| `essen` | Essen in den Objekten oder Szene Essen | Originalformat | Wärme +3, Sättigung +5 |
| `sonstiges` | nichts davon | Originalformat | keiner |

Personen zählen nur, wenn sie groß genug sind (keine Passanten). Hund und Katze verwechselt die
Objekterkennung öfter; ist die Szenenerkennung eindeutig, gilt deren Tier. „Baum“ und „Berge“
sind Heuristiken aus Farbe, Struktur und Himmelsgrenze: im Protokoll und in der Vorschau
kontrollieren und bei Bedarf `typ` vorgeben.

Vorrang: `format` und `mitte` vor der Regel, Looks in der Reihenfolge Regel < Rezept <
`anpassen`. `regeln: false` schaltet Regel-Zuschnitt, Regel-Look und Regel-Retusche ab.

## Regler, Bereiche, Effekte, Rezepte

Regler von −100 bis 100, angelehnt an Snapseeds *Feinabstimmung* und *Details*: `helligkeit`,
`kontrast`, `lichter`, `schatten`, `atmosphaere` (lokale Tonwertkompression), `struktur` (nur wo
Struktur ist, glatter Himmel bleibt), `saettigung` (wie Dynamik), `waerme`, `schaerfen`,
`vignette` (negativ hellt die Ecken auf). Je Bereich als Unterobjekt:

```json
{"struktur": 20, "himmel": {"helligkeit": -15, "saettigung": 10}, "hintergrund": {"saettigung": -30}}
```

Bereiche: `himmel` (inklusive Wolken bis zur Himmelsgrenze), `gruen`, `wasser`, `person`
(GrabCut in den Personenboxen), `motiv` (Personen, Tiere, Baum), `hintergrund` (alles außer
Motiv). Statt global geht auch je Bild: `{"DSC01234": {...}}`.

Effekte (jeweils als eigene Datei zusätzlich zur normalen Fassung): `bw`, `film`, `glow`,
`clarity`, `tonal`, `hdr`, `drama`, `vignette`, `lens_blur`.

Rezepte liegen in `rezepte/<name>.json` im Arbeitsordner:

```json
{"anpassen": {"waerme": 15, "struktur": 10, "himmel": {"saettigung": 10}}, "effekte": ["film"], "beschreibung": "Herbst"}
```

## Protokoll

Jeder Job (`optimieren`, `anpassen`, `retusche`) schreibt `protokoll_<zeit>_<job>.md` in den
Ausgabeordner, z. B. `final/protokoll_20261105-094221_9c9b3e3a.md`, und `job_status` liefert
denselben Text. Je Bild: Laden, Tonwert (Schwarz-/Weißpunkt), Entrauschen, Schärfen, Schräglage
mit Bezug (oder warum nicht gedreht wurde), Erkanntes, Bildtyp mit Begründung, Zuschnitt mit
Format und Box, Look mit Herkunft, gespeicherte Dateien, Effekte, Retusche.

## Voraussetzungen

- Ein OIDC-Client beim Anbieter, Callback `https://<hostname>/.auth/oidc/callback`, Public client
  aus. Den Client von ArtCraft MCP kann man mitbenutzen, dann dort die Callback-URL ergänzen.
- Ein öffentlicher HTTPS-Hostname, z. B. über das Cloudflared-Add-on.
- Fotos im Arbeitsordner, z. B. per Syncthing, Samba oder WebDAV.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-addons`
2. **Foto MCP** installieren. Home Assistant baut das Image auf dem Gerät (Python-Pakete und
   Gesichtsmodell werden geladen und geprüft, ca. 450 MB). Das dauert einige Minuten.
3. Konfiguration ausfüllen, speichern, starten.
4. Im Log prüfen: Versionen (Python, OpenCV, MediaPipe), `Arbeitsordner: …`,
   `foto: öffentlich auf Port 8080 für …` bzw. `foto: intern ohne Login unter …` und `Foto MCP … auf stdio`.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration`. OIDC ist nur mit `external_url` nötig |
| `oidc_provider_name` | Name auf der Anmeldeseite |
| `oidc_client_id`, `oidc_client_secret` | OIDC-Client |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse) |
| `external_url` | Öffentliche Adresse ohne Pfad, z. B. `https://foto.example.com`. Leer = kein öffentlicher Zugang |
| `internal_access` | Zusätzlich intern ohne Login erreichbar, siehe [Interner Zugriff](#interner-zugriff-ohne-login-z-b-open-webui) |
| `work_dir` | Ordner unter `/share`, Standard `/share/artcraft/work` (derselbe wie bei ArtCraft MCP) |

## Tunnel

Hostname wie in `external_url`, Pfad leer, Dienst-URL `http://<add-on-hostname>:8080`. Den
Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App. Keine Access-App davor, bei
aktiver WAF-Regel „Block AI bots“ eine Ausnahme für den Hostnamen anlegen.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, URL `https://<hostname>/mcp`,
keine Client-ID. Beim Verbinden öffnet sich die Anmeldung des OIDC-Anbieters.

## Interner Zugriff ohne Login (z. B. Open WebUI)

Mit `internal_access: true` ist der Server zusätzlich **ohne Anmeldung** im internen Docker-Netz
von Home Assistant erreichbar, für Clients auf demselben Gerät wie Open WebUI. Die öffentliche
URL mit Login kann daneben weiterlaufen oder leer bleiben; ohne sie ist kein OIDC nötig.

- Adresse: `http://<repo-hash>-foto-mcp:9080/mcp`, z. B. `http://be60cb4b-foto-mcp:9080/mcp`. Das Log
  zeigt sie beim Start (`… intern ohne Login unter …`).
- Port 9080 (öffentlicher Port + 1000) steht nicht unter **Netzwerk** und wird nie auf den Host
  gelegt, ist also aus dem Heimnetz nicht erreichbar.
- In Open WebUI: Admin-Bereich → Einstellungen → Integrationen → **+**, Typ *MCP Streamable
  HTTP*, URL wie oben, Authentifizierung *Keine*.
- Läuft beides, sind es zwei getrennte Prozesse des Servers.

**Sicherheit:** Jede App im internen Netz (alle Apps, Home Assistant selbst, Apps mit
Host-Netzwerk) kann den Server dann ohne Login nutzen. Wer intern zugreift, kann den ganzen Arbeitsordner lesen und dort schreiben (Ergebnisse, Aussortieren). Originale verändert der Server nie. Anfragen aus dem Browser (mit
`Origin`-Header) werden abgelehnt.

## Jobs

`optimieren` und `retusche` laufen als Job, immer nur einer gleichzeitig. Ein Neustart des Add-ons
verwirft laufende Jobs, fertige Dateien bleiben.

## Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| `außerhalb des Arbeitsordners` | Pfad zeigt aus `work_dir` heraus | Pfad relativ zum Arbeitsordner angeben, z. B. `Salzburg/DSC01234.JPG` |
| `Job … unbekannt` | Add-on wurde neu gestartet | Job neu starten, fertige Dateien liegen schon in `final/` |
| Kein Gesicht erkannt | Gesicht sehr klein, stark verdeckt oder im Profil | `mitte` (waagrechte Motivmitte 0..1) oder `format` vorgeben |
| Falscher Bildtyp | Heuristik (Baum, Berge) oder Szene mehrdeutig | `typ: {"NAME": "landschaft"}` vorgeben, Begründung steht im Protokoll |
| Log: `Objekterkennung AUS` | Modelldatei fehlt (nur bei eigenem Image) | Add-on neu bauen; ohne Modelle stützt sich der Bildtyp nur auf Gesichter und Bereiche |
| Installation bricht beim Bauen ab | PyPI oder Google Storage nicht erreichbar, Prüfsumme passt nicht | Später erneut versuchen, sonst Issue im Repo |
| `libEGL.so.1: cannot open shared object file` | Systembibliothek fehlt im Image | Im Dockerfile `libegl1 libgles2` prüfen |
