# Open Terminal

[Open Terminal](https://github.com/open-webui/open-terminal) gibt Modellen in Open WebUI eine
Shell mit Dateien und Werkzeugen: Code ausführen, Dateien erzeugen und umwandeln (PDF, Word,
Excel, Bilder, Audio), Daten auswerten. Die Dateien erscheinen im Chat im Reiter „Dateien“.

Die App nutzt das offizielle Image (volle Variante mit Python-Datenpaketen, Node.js,
LibreOffice, Pandoc, LaTeX und ffmpeg, rund 4 GB) und läuft in einem eigenen Container.
Befehle des Modells kommen so nicht an Datenbank und Schlüssel von Open WebUI.

## Einrichtung mit der App Open WebUI

1. **Open Terminal** installieren und starten.
2. Im Protokoll steht `API-Schlüssel (…): <schlüssel>`. Den Wert kopieren.
3. In der App **Open WebUI** unter Konfiguration bei `open_terminal_api_key` einfügen und
   Open WebUI neu starten.

Open WebUI trägt die Verbindung dann selbst ein (Admin-Bereich → Integrationen → Open
Terminal). Sie ist zunächst nur für Admins nutzbar. Andere Nutzer oder Gruppen gibst du dort
frei; die Freigaben bleiben bei Neustarts erhalten.

Im Chat wählst du das Terminal aus einer Auswahlliste; danach erscheint in der Seitenleiste des
Chats der Reiter „Dateien“.

## Arbeitsordner

`~/work` im Terminal zeigt auf `work_dir` (Standard `/share/artcraft/work`), denselben Ordner,
den ArtCraft und Foto MCP nutzen. So kann das Modell Dateien aus dem Chat dort ablegen,
umwandeln und an die anderen Apps übergeben.

- `inbox/` für Eingänge, `out/` für Ergebnisse. Die App legt beide beim Start an.
- `user` bekommt per ACL Schreibrechte, auch auf Dateien, die andere Apps später anlegen.
- Aufgeräumt wird nicht von dieser App, sondern von Home Assistant (Pyscript
  `work_cleanup.py`, siehe Repository-README).

## Was das Modell darf

- Alles, was ein Nutzer mit `sudo` im Container darf: Pakete installieren, Dateien anlegen
  und löschen, ins Internet verbinden.
- **Ganz `/share`**, nicht nur den Arbeitsordner: Home Assistant kann `/share` nur komplett
  einbinden, und mit `sudo` gelten keine Dateirechte. Dazu gehören z. B. Syncthing-Ordner
  oder Paperless-Daten. Deshalb: Terminal nur für Admins freigeben, in Open WebUI
  „Um Bestätigung bitten“ für Werkzeuge nutzen und `/share` sichern. Mit leerem `work_dir`
  bleibt `/share` eingebunden, aber ohne Link.
- **Nicht**: an `/config`, die Datenbank oder Schlüssel von Open WebUI. Das Token des
  Supervisors wird vor dem Start entfernt.
- Erreichbar ist die App nur im internen Netz der Apps (`http://<repo-hash>-open-terminal:8000`),
  nicht von außen, solange der Port leer bleibt.

## Optionen

| Option | Bedeutung |
|---|---|
| `api_key` | Leer = beim ersten Start erzeugt und in `/data/api_key` gespeichert. Eigener Wert möglich; dann in Open WebUI denselben eintragen |
| `work_dir` | Arbeitsordner unter `/share`, im Terminal als `~/work`. Leer = kein Link |

## Daten und Backup

Das Home-Verzeichnis des Terminals liegt in `/data/home`. Dateien und mit `pip install --user`
oder `npm` nachinstallierte Pakete bleiben bei Updates erhalten und sind im Backup der App,
ohne `.cache` und `.npm`. Mit `sudo apt install` installierte Pakete gehen beim Update
verloren.

## Updates

Die Version ist fest (`OPEN_TERMINAL_VERSION` im Dockerfile). Ein täglicher Workflow prüft
neue Releases, baut und testet die App zusammen mit Open WebUI auf amd64 und arm64 und trägt
die Version erst danach ein. Home Assistant zeigt dann das Update an. Die Add-on-Version folgt
der Version von Open Terminal, eigene Änderungen hängen `-1`, `-2` … an. Open WebUI am besten
zusammen aktualisieren.
