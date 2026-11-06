# Files MCP

Dateien unter `/share` für LLM-Clients, die kein eigenes Terminal haben: auflisten, lesen,
gezielt bearbeiten, suchen, verschieben, ablegen, Metadaten lesen und Bilder oder PDF-Seiten
als Vorschau ansehen. Öffentlich hinter [mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy)
mit Login über deinen OIDC-Anbieter (z. B. Pocket ID), intern optional ohne Login.

Der Server (`common/files_mcp.py`) ist ein eigenes kleines Python-Programm. Er war bis ArtCraft
1.4.8 als App `files` dort enthalten.

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `files_list` | Dateien und Ordner, mit Muster (`*.pdf`), rekursiv, nach Datum sortiert |
| `file_info` | Größe, Datum, MIME-Typ, SHA-256; mit `details: true` Metadaten aus dem Inhalt (siehe unten) |
| `file_read_text` | Textdatei lesen, zeilenweise mit `offset`/`limit` |
| `file_write_text` | Text schreiben: `create` (nur neue Datei), `overwrite`, `append` |
| `file_edit` | eine eindeutige Textstelle ersetzen, Rest bleibt unverändert |
| `file_search` | Inhaltssuche (Begriff oder regulärer Ausdruck), Treffer als `Datei:Zeile` |
| `file_move` | verschieben, umbenennen, kopieren (`copy: true`) |
| `file_trash` | statt Löschen: nach `.trash/<Zeitstempel>/` unter der Wurzel |
| `file_get` | Binärdatei holen, große Dateien in Teilen (`offset`/`length`) |
| `file_put` | Binärdatei ablegen (base64), große in Teilen (`append: true`) |
| `file_preview` | Bild oder PDF-Seite verkleinert als Bild, zum Ansehen durch Vision-Modelle |

Mit **Nur lesen** bietet der Server die schreibenden Werkzeuge gar nicht erst an.

### Metadaten (`file_info` mit `details: true`)

| Typ | Inhalt |
|---|---|
| Fotos | Aufnahmedatum, Kamera, Objektiv, Blende, Belichtung, ISO, Ausrichtung, GPS |
| PDF | Seiten, Titel, Autor, Datum, Seitengröße, verschlüsselt, Text vorhanden oder Scan |
| Office (docx, xlsx, pptx) | Titel, Autor, Datum, Seiten, Folien, Tabellenblätter |
| CSV, Markdown, Text | Kodierung, Zeilen, Zeilenende; CSV-Trennzeichen und Spalten; Frontmatter |
| Audio, Video | Dauer, Bitrate, Abtastrate, Kanäle (über mutagen, ohne Videoauflösung) |

**GPS** wird standardmäßig auf zwei Nachkommastellen gerundet (etwa 1 km). Genau nur mit
`gps: exact`, ganz ausgeblendet mit `gps: none`. HEIC-Fotos werden nicht gelesen.

## Sicherheit

- **Wurzel:** Alles ist relativ zu `root`. `..` und Symlinks nach draußen werden abgewiesen.
- **Geschützte Namen** (Standard `.obsidian,.stfolder,.stversions,.git`): In solchen Ordnern
  wird auf keiner Ebene geschrieben, verschoben oder gelöscht, und sie werden nicht durchsucht.
- **Kein endgültiges Löschen.** `file_trash` verschiebt nach `.trash/`. Leeren von Hand, oder
  über die Aufräum-Automation, wenn `.trash/` in deren Ordner liegt.
- **Atomar:** Geschrieben wird erst in eine temporäre Datei, dann umbenannt. Bei geänderten
  Dateien bleiben Besitzer und Rechte erhalten, neue Dateien bekommen den Besitzer des Ordners.
- **Überschreiben** nur ausdrücklich (`overwrite: true` bzw. `mode: overwrite`).

> **Achtung bei `root: /share`:** Der Server sieht dann die Daten aller Apps unter `/share`
> (Obsidian-Vault, Paperless, Nextcloud, Frigate). Mit `internal_access` gilt das ohne Login für
> jede App im internen Netz. Vault-Dateien werden per Syncthing sofort auf alle Geräte verteilt.
> Für solche Wurzeln **Nur lesen** erwägen oder die geschützten Namen erweitern.

## Voraussetzungen

- Für den öffentlichen Zugang: ein OIDC-Client beim Anbieter, Callback
  `https://<hostname>/.auth/oidc/callback`, Public client aus, und ein HTTPS-Hostname, z. B. über
  das Cloudflared-Add-on.
- Für Open WebUI auf demselben Gerät reicht `internal_access`.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-addons`
2. **Files MCP** installieren, Wurzelordner prüfen, starten.
3. Im Log prüfen: `Wurzel: …`, `files: intern ohne Login unter http://<hostname>:9080/mcp` bzw.
   `files: öffentlich auf Port 8080 für …`.
4. **Open WebUI:** Admin → Einstellungen → Externe Tools → Typ **MCP (Streamable HTTP)**, URL
   `http://<repo-hash>-files-mcp:9080/mcp`, Authentifizierung **Keine**.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `internal_access` | Zusätzlich intern ohne Login unter Port 9080 |
| `root` | Wurzelordner unter `/share` (Standard `/share/artcraft/work`) |
| `read_only` | Nur lesende Werkzeuge |
| `protected` | Geschützte Ordner-/Dateinamen, kommagetrennt |
| `max_mb` | Grenze je `file_get`/`file_put`-Aufruf (1–50 MB) |
| `public` | Öffentliche URL und OIDC-Felder, wie bei den anderen MCP-Apps |

## Umzug von ArtCraft (`files`)

Ab ArtCraft 1.4.9 gibt es dort keine App `files` mehr. **Vor dem ArtCraft-Update** umsteigen,
sonst ist der Datei-Connector in der Zwischenzeit weg:

1. Files MCP installieren, `root` auf denselben Ordner wie ArtCraft (`work_dir`) setzen, starten.
2. Cloudflared: den bisherigen Files-Hostnamen auf `http://<repo-hash>-files-mcp:8080` umstellen,
   OIDC-Client unverändert lassen (gleicher Callback).
3. Im LLM-Client den Connector einmal neu verbinden (die Proxy-Daten lagen in ArtCraft).
   Open WebUI: URL auf `http://<repo-hash>-files-mcp:9080/mcp` ändern.
4. In ArtCraft `files_url` leeren und `files` aus `internal_apps` nehmen.
