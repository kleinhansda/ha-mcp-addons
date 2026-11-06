# Changelog

## 0.5.4 (2026-11-06)

- „Arbeitsordner“ darf jetzt auch `/share` selbst sein. Unterordner regeln dann Skills bzw.
  Anweisungen an das Modell. Mail-Anhänge landen in `/share/inbox`, Anhänge zum Senden kommen
  aus `/share/out`. Rechte per ACL setzt die App dann nur auf diese beiden Ordner.

## 0.5.3

- Entfernt: „Übernahme aus altem Add-on“ (`legacy_data_dir`). Ein leeres Feld ließ das
  Speichern mit „does not match regular expression“ scheitern. Nach dem Umzug Clients einmal
  neu verbinden.
- „Arbeitsordner“ darf leer bleiben (Arbeitsordner aus), ohne dass das Speichern scheitert.

## 0.5.2

- Mit „Mail bearbeiten“ steht jetzt auch `save_draft` bereit: Entwürfe landen im
  Entwürfe-Ordner des Postfachs. Vorher fehlte das Werkzeug in der Kernauswahl.

## 0.5.1

- Behoben: Speichern schlug fehl („Unknown error“), wenn `internal_access` in einer
  übernommenen Konfiguration fehlte. Die Option ist jetzt optional.

## 0.5.0

- Umgezogen nach `kleinhansda/ha-mcp-addons` (didi's Apps). Neuer Slug, Umzug
  siehe DOCS.md, Abschnitt „Umzug aus ha-mailbox-org-mcp“.
- Neu: **Interner Zugriff ohne Login** (`internal_access`, Standard aus). Je
  aktivem Dienst eine Brücke (`mcp_bridge.py` aus `common/`) unter
  `http://<hostname>:9081–9085/mcp`, nur im internen Netz, z. B. für Open WebUI.
  Stürzt eine Brücke ab, startet nur sie neu.
- Das Image enthält dafür python3.

## 0.4.0

- Neu: **Arbeitsordner** (`work_dir`, Standard `/share/artcraft/work`), gemeinsam
  mit ArtCraft, Foto MCP und Open Terminal. Mail-Anhänge werden mit
  `get_attachments` nach `inbox/` gespeichert, Anhänge zum Senden kommen aus
  `out/`. Drive: `work_list`, `drive_to_work` (Dateien beliebigen Typs aus dem
  Drive in den Arbeitsordner) und mit `drive_write` `work_to_drive`.
- Das Add-on bindet `/share` ein und setzt im Arbeitsordner Schreibrechte für
  uid 1000 (ACL).

## 0.3.1

- Behoben: Die Gesundheitsprüfung des Basis-Images fragte Port 80 ab, nicht
  den Port 8099 des Add-ons. Home Assistant blieb dadurch bei „Wird gestartet“,
  und der Watchdog startete die App alle paar Minuten neu.

## 0.3.0

- Neu: **mailbox.org Drive** über WebDAV (`drive_enabled`, aus per Standard).
  Eigener kleiner Server: Ordner auflisten, Dateien suchen, Textdateien lesen.
  Mit `drive_write` zusätzlich Textdateien und Ordner anlegen; Löschen und
  Verschieben gibt es nicht. `drive_root` beschränkt den Zugriff auf einen
  Ordner. Braucht ein eigenes Anwendungspasswort „WebDAV-Client“
  (`webdav_password`).

## 0.2.1

- Neu: `dav_password` für Kalender und Adressbuch. mailbox.org vergibt
  Passwörter je Anwendungstyp; ein E-Mail-App-Passwort führte bei CalDAV/CardDAV
  zu HTTP 401. Ohne Angabe gilt weiterhin `app_password`.

## 0.2.0

- Neu: optionales **Passkey-Gate** (`passkey_enabled`). Freigaben laufen über
  einen OIDC-Anbieter wie Pocket ID; das Hub-Passwort wird serverseitig
  eingesetzt und ist von außen nicht mehr verwendbar.
- mcp-hub 0.11.7 (behebt einen Absturz durch präparierte komprimierte
  Request-Bodies, CVE-2026-111181).
- Port 8099 wird standardmäßig nicht mehr auf dem Host veröffentlicht; ein
  Tunnel/Proxy als HA-App nutzt den internen Hostnamen. Bestehende
  Installationen behalten ihre Einstellung.

## 0.1.0

- Erste Version: mcp-hub 0.11.6 mit imap-mcp 0.5.3, smtp-mcp 0.2.0,
  caldav-mcp 0.1.5, carddav-mcp 0.1.3.
- Standard: nur lesen, Senden aus, kuratierte Werkzeugauswahl.
