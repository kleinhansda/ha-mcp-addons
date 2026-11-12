# Änderungen

## 0.13.3.4 (2026-11-12)

- Chat-Schrift: neuer Wert `system-serif` (Serifenschrift des Geräts, ohne Download). Mit sechs
  Werten zeigt Home Assistant die Option als Drop-down statt als Radio-Buttons.
- Design, Chat-Schrift und `custom.css` kommen nach einem Neustart sofort im Browser an: Der Link
  auf `/static/custom.css` trägt jetzt eine Prüfsumme (`?v=…`). Bisher lieferten Browser und
  Cloudflare oft noch die alte Datei aus dem Cache.

## 0.13.3.3 (2026-11-12)

- Neue Option **Chat-Schrift**: `standard`, `redaction`, `source-serif`, `literata`, `newsreader`.
  Setzt nur den Text in Chat-Nachrichten in einer Serifenschrift, für alle Nutzer; Oberfläche und
  Code bleiben unverändert. Die Schriften (Fontsource, SIL OFL 1.1) liegen im Image und werden
  unter `/static/schriften/` ausgeliefert, ohne externe Abrufe. Reihenfolge in `custom.css`:
  Design, Chat-Schrift, eigenes CSS.

## 0.13.3.2 (2026-11-10)

- Versionsschema mit Punkt statt Bindestrich: Home Assistant wertet „0.13.3-2“ als Vorabversion und damit als älter als 0.13.3; die Aktualisieren-Schaltfläche blieb grau.

## 0.13.3-2 (2026-11-10)

- Neue Option **Design**: `standard`, `claude`, `openai`, `zora`, `hannesbraeu`, `nord`. Färbt die
  Grautöne von Open WebUI (hell und dunkel) und setzt eine Akzentfarbe für Senden-Knopf, Links,
  Markierung und Auswahlfelder. `custom.css` wird danach eingebunden und kann alles überschreiben.

## 0.13.3-1 (2026-11-10)

- Eigenes CSS: `custom.css` im App-Konfigurationsordner (`/addon_configs/<repo>_open_webui/`)
  wird beim Start übernommen. Beim ersten Start legt die App eine Vorlage mit einem
  auskommentierten Beispiel an (größeres Modell-Icon auf der Startseite).

## 0.13.3 (2026-11-09)

- Open WebUI 0.13.0 → 0.13.3, [Release-Notes](https://github.com/open-webui/open-webui/releases/tag/v0.13.3)
- Vor dem Update ein Backup anlegen lassen: Datenbank-Migrationen lassen sich nicht rückgängig machen

## 0.13.2 (2026-11-06)

- `/share` ist jetzt eingebunden (lesen und schreiben). Nötig für die Funktion „Anhänge nach /share“:
  Sie legt Dateien und Bilder aus dem Chat unter `/share/openwebui/inbox/<Datum>/` ab, damit
  MCP-Werkzeuge (Files, ArtCraft, Foto, Paperless) und das Terminal sie nutzen können.

## 0.13.1 (2026-11-06)

- Behoben: Speichern der Konfiguration schlug mit „does not match regular expression“
  fehl, wenn ein optionales Pfad- oder URL-Feld leer war. Die Felder sind jetzt optional.

## 0.13.0 (2026-11-04)

- Open WebUI 0.12.5 → 0.13.0, [Release-Notes](https://github.com/open-webui/open-webui/releases/tag/v0.13.0)
- Vor dem Update ein Backup anlegen lassen: Datenbank-Migrationen lassen sich nicht rückgängig machen

## 0.12.5-1 (2026-11-01)

- Web-Suche mit eigener SearXNG-Instanz in der App (Option `searxng`, Standard an). Open
  WebUI wird bei jedem Start darauf eingestellt
- Open Terminal: mit `open_terminal_api_key` trägt die App die Verbindung zur neuen App
  „Open Terminal“ selbst ein (nur für Admins, Freigaben bleiben erhalten)

## 0.12.5 (2026-11-01)

- Erste Version: offizielles Image von Open WebUI 0.12.5 (amd64, arm64)
- Optionen für öffentliche URL, Geheimschlüssel und Login über OIDC (z. B. Pocket ID)
- Einmalige Übernahme einer bestehenden Installation aus `/addon_configs/…/import`, mit
  Prüfung der Datenbank
- Healthcheck mit 15 Minuten Anlaufzeit, damit Migrationen beim ersten Start nicht vom
  Watchdog abgebrochen werden
- Heruntergeladene Modelle (`cache/embedding`, `cache/whisper`) sind vom Backup ausgenommen
