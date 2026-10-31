# Foto MCP

Ein eigener MCP-Server für Urlaubs- und Alltagsfotos, als Remote-Connector für Claude, auch für
die Smartphone-App. Er arbeitet direkt auf dem Home-Assistant-Gerät, die Fotos verlassen es
nicht. Claude bekommt nur verkleinerte Vorschauen zur Kontrolle. Davor sitzt
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy) als OAuth-Server mit Login über deinen
OIDC-Anbieter (z. B. Pocket ID).

Hintergrund und Entscheidungen:
[docs/FOTO.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/FOTO.md).
Gemeinsames Muster aller Add-ons:
[docs/ARCHITEKTUR.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/ARCHITEKTUR.md).

## Werkzeuge

| Tool | Wofür |
|---|---|
| `ordner_sichten` | EXIF (Kamera, Brennweite, Blende, Zeit, ISO, Aufnahmezeit), Schärfe, Helligkeit, byte-gleiche Kopien, Serien, Kontaktbogen (24 Bilder je Seite) |
| `vorschau` | Bis zu 6 Bilder nebeneinander mit Hilfslinien, wahlweise gedreht und ausgeschnitten. Zum Prüfen der Schräglage |
| `neigung_messen` | Vorschlag für die Schräglage (Senkrechte mit Korrektur stürzender Linien, sonst Horizont; Linien von Personen zählen nicht) und Anzahl Gesichter |
| `aussortieren` | Verschiebt Bilder nach `_aussortiert/`. Löscht nie, überschreibt nie |
| `optimieren` | Job: Tonwert, Entrauschen ab ISO 400, Schärfen, Begradigen, motivgerechter Zuschnitt, Effekte (`bw`, `film`, `glow`, `clarity`), optional Retusche. Schreibt `final/<name>_final.jpg` |
| `retusche` | Job: dezente Hautretusche (Flecken, Rötung, minimal glätten). Augen, Brauen, Lippen, Bart und Haare bleiben unberührt. Schreibt `<name>_retusche.jpg` |
| `job_status` | Fortschritt, Ergebnisse je Bild und Vorschauen (Zuschnitt mit Drittel- und Mittellinie, vorher/nachher je Gesicht) |

Originale werden nie verändert. Ergebnisse haben immer ein Suffix (`_final`, `_bw`, `_retusche` …)
und dürfen bei einem neuen Lauf überschrieben werden.

## Voraussetzungen

- Ein OIDC-Client beim Anbieter, Callback `https://<hostname>/.auth/oidc/callback`, Public client
  aus. Den Client von ArtCraft MCP kann man mitbenutzen, dann dort die Callback-URL ergänzen.
- Ein öffentlicher HTTPS-Hostname, z. B. über das Cloudflared-Add-on.
- Fotos im Arbeitsordner, z. B. per Syncthing, Samba oder WebDAV.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-mcp-addons`
2. **Foto MCP** installieren. Home Assistant baut das Image auf dem Gerät (Python-Pakete und
   Gesichtsmodell werden geladen und geprüft, ca. 450 MB). Das dauert auf einem Raspberry Pi
   einige Minuten.
3. Konfiguration ausfüllen, speichern, starten.
4. Im Log prüfen: Versionen (Python, OpenCV, MediaPipe), `Arbeitsordner: …`,
   `foto: Start auf Port 8080 für …` und `Foto MCP … auf stdio`.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration` |
| `oidc_provider_name` | Name auf der Anmeldeseite |
| `oidc_client_id`, `oidc_client_secret` | OIDC-Client |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse) |
| `external_url` | Öffentliche Adresse ohne Pfad, z. B. `https://foto.example.com` |
| `work_dir` | Ordner unter `/share`, Standard `/share/artcraft/work` (derselbe wie bei ArtCraft MCP) |

## Tunnel

Hostname wie in `external_url`, Pfad leer, Dienst-URL `http://<add-on-hostname>:8080`. Den
Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App. Keine Access-App davor, bei
aktiver WAF-Regel „Block AI bots“ eine Ausnahme für den Hostnamen anlegen.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, URL `https://<hostname>/mcp`,
keine Client-ID. Beim Verbinden öffnet sich die Anmeldung des OIDC-Anbieters.

## Ressourcen

Gemessen in einer x86-Testumgebung: 20-MP-Foto optimieren ca. 16 s, Retusche ca. 35 s je Selfie
mit zwei Gesichtern, Sichtung ca. 0,3 s je Bild. Auf einem Raspberry Pi 4 grob 4- bis 6-mal so
lange, also etwa 1 bis 2 Minuten je Foto, Spitze ca. 1,5 GB RAM. Darum laufen `optimieren` und
`retusche` als Job, immer nur einer gleichzeitig. Ein Neustart des Add-ons verwirft laufende
Jobs, fertige Dateien bleiben.

## Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| `außerhalb des Arbeitsordners` | Pfad zeigt aus `work_dir` heraus | Pfad relativ zum Arbeitsordner angeben, z. B. `Salzburg/DSC01234.JPG` |
| `Job … unbekannt` | Add-on wurde neu gestartet | Job neu starten, fertige Dateien liegen schon in `final/` |
| Kein Gesicht erkannt | Gesicht sehr klein, stark verdeckt oder im Profil | `mitte` (waagrechte Motivmitte 0..1) oder `format` vorgeben |
| Installation bricht beim Bauen ab | PyPI oder Google Storage nicht erreichbar, Prüfsumme passt nicht | Später erneut versuchen, sonst Issue im Repo |
| `libEGL.so.1: cannot open shared object file` | Systembibliothek fehlt im Image | Im Dockerfile `libegl1 libgles2` prüfen |
