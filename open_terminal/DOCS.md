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

## GitHub-Zugang

Mit der Option `github_token` kann das Modell im Terminal Repos klonen, Branches pushen und
Pull Requests anlegen, ohne Umweg über den GitHub-MCP.

- Token: **Fine-grained PAT** (github.com → Settings → Developer settings → Fine-grained
  tokens), nur für die nötigen Repos, Rechte *Contents* und *Pull requests* (Lesen/Schreiben),
  mit Ablaufdatum. Keine Admin- oder Workflow-Rechte.
- Im Terminal steht er als `GH_TOKEN` bereit. `gh` nutzt ihn direkt; `git` über einen
  Credential-Helper für `https://github.com`, der `GH_TOKEN` erst beim Aufruf liest. Der Token
  landet nicht in `~/.gitconfig` und nicht im Backup.
- Nur HTTPS-Remotes (`https://github.com/…`), keine SSH-Remotes (`git@github.com:…`).
- Mit `sudo` ist `GH_TOKEN` nicht gesetzt; git-Befehle ohne `sudo` ausführen.
- **Jeder Befehl im Terminal kann den Token lesen.** Deshalb Rechte und Repos eng halten.
  Option leeren und App neu starten entfernt den Zugang wieder.

## Was das Modell darf

- Alles, was ein Nutzer mit `sudo` im Container darf: Pakete installieren, Dateien anlegen
  und löschen, ins Internet verbinden.
- **Ganz `/share`**, nicht nur den Arbeitsordner: Home Assistant kann `/share` nur komplett
  einbinden, und mit `sudo` gelten keine Dateirechte. Dazu gehören z. B. Syncthing-Ordner
  oder Paperless-Daten. Deshalb: Terminal nur für Admins freigeben, in Open WebUI
  „Um Bestätigung bitten“ für Werkzeuge nutzen und `/share` sichern. Mit leerem `work_dir`
  bleibt `/share` eingebunden, aber ohne Link.
- Mit gesetztem `github_token`: auf die freigegebenen GitHub-Repos schreiben (siehe oben).
- **Nicht**: an `/config`, die Datenbank oder Schlüssel von Open WebUI. Das Token des
  Supervisors wird vor dem Start entfernt.
- Erreichbar ist die App nur im internen Netz der Apps (`http://<repo-hash>-open-terminal:8000`),
  nicht von außen, solange der Port leer bleibt.

## Optionen

| Option | Bedeutung |
|---|---|
| `api_key` | Leer = beim ersten Start erzeugt und in `/data/api_key` gespeichert. Eigener Wert möglich; dann in Open WebUI denselben eintragen |
| `work_dir` | Arbeitsordner unter `/share`, im Terminal als `~/work`. Leer = kein Link |
| `github_token` | Optional, fine-grained PAT. Im Terminal als `GH_TOKEN` (git über HTTPS, gh). Leer = kein GitHub-Zugang |

## Daten und Backup

Das Home-Verzeichnis des Terminals liegt in `/data/home`. Dateien und mit `pip install --user`
oder `npm` nachinstallierte Pakete bleiben bei Updates erhalten und sind im Backup der App,
ohne `.cache` und `.npm`. Mit `sudo apt install` installierte Pakete gehen beim Update
verloren.

## Updates

Die Version ist fest (`OPEN_TERMINAL_VERSION` im Dockerfile) und wird von Hand erhöht,
zusammen mit `version` in `config.yaml`.
