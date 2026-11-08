# Open Terminal

[Open Terminal](https://github.com/open-webui/open-terminal) gibt Modellen in Open WebUI eine
Shell mit Dateien und Werkzeugen: Code ausführen, Dateien erzeugen und umwandeln (PDF, Word,
Excel, Bilder, Audio), Daten auswerten. Die Dateien erscheinen im Chat im Reiter „Dateien“.

Die App nutzt das offizielle Image (volle Variante mit Python-Datenpaketen, Node.js,
LibreOffice, Pandoc, LaTeX und ffmpeg, rund 4 GB), ergänzt um R (siehe [R](#r)), und läuft in
einem eigenen Container.
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

## R

R kommt aus Debian (R 4.5) mit fertigen Binärpaketen, auch auf arm64:

- `r-recommended` (MASS, Matrix, survival …), tidyverse, data.table, renv, rmarkdown, knitr,
  readxl, writexl, openxlsx. Pandoc und LaTeX für rmarkdown bringt das Image mit.
- R-Kernel für Jupyter (`ir`), falls Debian IRkernel führt.
- `Rscript` und `R` im Terminal, CRAN (`cloud.r-project.org`) ist ohne Rückfrage eingestellt.

Weitere Pakete:

| Weg | Ziel | Bei Updates der App |
|---|---|---|
| `install.packages("x")` | `~/R/library` unter `/data/home` | bleibt erhalten, im Backup |
| `sudo apt-get install r-cran-x` | System-Bibliothek im Image | geht verloren |
| renv im Projekt | `renv/library` im Projekt, Cache unter `~/.cache/R/renv` | bleibt erhalten, Cache nicht im Backup |

`install.packages()` baut aus den Quellen; auf einem Raspberry Pi dauert das bei Paketen mit
C/C++-Code (z. B. `arrow`, `sf`) lange und braucht Arbeitsspeicher. Fehlt dafür eine
Systembibliothek, hilft `sudo apt-get install lib…-dev`, die ist nach einem Update aber wieder weg.
Nach dem Zurückspielen eines Backups in renv-Projekten `renv::restore()` ausführen, weil der
Cache nicht gesichert wird.

## Arbeitsordner

`~/work` im Terminal zeigt auf `work_dir` (Standard `/share/artcraft/work`), denselben Ordner,
den ArtCraft und Foto MCP nutzen. So kann das Modell Dateien aus dem Chat dort ablegen,
umwandeln und an die anderen Apps übergeben.

- Austauschordner `mbox/inbox`, `mbox/outbox` (Mail) und `openwebui/inbox` (Anhänge aus dem Chat). Die App legt sie beim Start an.
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

## Python- und R-Pakete

Statt eigener Werkzeuge pro Programm arbeiten Modelle hier mit den Bibliotheken, die sie gut
kennen. Die App installiert sie beim Start im Hintergrund (Protokoll: `[pakete] …`, am Ende
`Pakete bereit`):

| Gruppe | Pakete |
|---|---|
| `bild` | Pillow, pillow-heif, OpenCV (headless), scikit-image, imageio, rawpy |
| `vektor` | drawsvg, svgwrite, svgelements, CairoSVG, ReportLab, fonttools, qrcode, python-barcode |
| `pdf` | pypdf, pikepdf, PyMuPDF, pdfplumber |
| `office` | python-docx, docxtpl, python-pptx, openpyxl, XlsxWriter, Markdown |
| `cad` | ezdxf, shapely, matplotlib |
| `3d` | trimesh, numpy-stl, manifold3d, build123d (CAD auf OpenCascade, Export STEP/STL/3MF; ca. 60 MB) |

Schon im Image: numpy, pandas, matplotlib, plotly, LibreOffice (z. B. `soffice --headless
--convert-to pdf`), Pandoc, ImageMagick, ffmpeg, Poppler, LaTeX, R mit tidyverse.

- Die Pakete liegen in `~/.venv` (uv, mit Zugriff auf die Pakete des Images). `python`, `pip`
  und Jupyter im Terminal nutzen diese Umgebung.
- `update_packages` an: jeder Start holt die neuesten Versionen. Vorher wird der Stand in
  `~/.venv/staende/<Datum>.txt` gesichert (die letzten 10). Bricht ein Update etwas, zurück mit
  `uv pip sync --python ~/.venv/bin/python ~/.venv/staende/<Datum>.txt`.
  ⚠️ `sync` entfernt dabei alle Pakete in `~/.venv`, die nicht in der Datei stehen.
- Einzelne Versionen festhalten: unter `python_packages` mit Version, z. B. `pandas==2.2.3`.
- Von Hand neu installieren oder aktualisieren: `terminal-pakete`.
- R-Pakete aus `r_packages` werden auf dem Raspberry Pi kompiliert. Der erste Start kann dann
  deutlich länger dauern.

## Vorlagen

Unter `~/vorlagen` (im Image `/usr/local/share/vorlagen`, nur lesen) liegen getestete Skripte als
Ausgangspunkt für Modelle, z. B. `3d/teil.py`. In den Projektordner kopieren und dort anpassen.

