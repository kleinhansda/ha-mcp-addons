# Änderungen

## 0.17.3.4 (2026-11-09)

- **Behoben: Home Assistant hat die Versionen 0.17.3-1 bis 0.17.3-4 nie installiert.** Eine Endung
  `-N` gilt als Vorabversion und damit als älter als 0.17.3. Eigene Änderungen zählen jetzt mit einer
  vierten Stelle (0.17.3.4). Dieses Update bringt alles aus 0.17.3.1 bis 0.17.3.3 mit: Python-Pakete
  per uv, R-Pakete, beschreibbare Ordner, build123d, Vorlagen.

- **Vorlagen** im Image unter `/usr/local/share/vorlagen` (im Terminal `~/vorlagen`, nur lesen):
  `3d/teil.py` (build123d, Export STEP/STL, Prüfansichten, Prüfwerte). Ein CI-Job führt die
  Vorlagen auf amd64 und arm64 aus.

## 0.17.3.3 (2026-11-08)

- Paketgruppe `3d` um **build123d** erweitert: CAD auf OpenCascade (wie FreeCAD), exakte Teile
  mit Maßen, Export als STEP, STL und 3MF, Ansichten als SVG. Auf arm64 ohne Kompilieren
  (ca. 60 MB). Die Gruppe ist nicht standardmäßig aktiv, in der App unter Python-Paketgruppen
  `3d` einschalten.

## 0.17.3.2 (2026-11-08)

- Behoben: Die Python-Pakete wurden nicht installiert (`venv nicht angelegt`). Die Installation
  läuft jetzt unabhängig vom Startordner und ohne fremde uv-Konfiguration; Fehler von uv stehen
  im Protokoll.
- Neue Option `writable_dirs`: Ordner relativ zu `/share`, in die das Terminal zusätzlich schreiben darf
  (ACL, auch für später angelegte Dateien), z. B. `hannesbraeu`. Bisher war bei `/share` als
  Arbeitsordner nur `mbox/` und `openwebui/` beschreibbar.

## 0.17.3.1 (2026-11-08)

- **Python-Pakete per uv:** Paketgruppen `bild`, `vektor`, `pdf`, `office`, `cad` (Standard) und
  `3d` sowie eigene Pakete (`python_packages`) landen in `~/.venv`. Das Python im Terminal nutzt
  sie automatisch und sieht weiter die Pakete des Images. Mit `update_packages` (Standard an)
  holt jeder Start die neuesten Versionen; der vorherige Stand liegt in `~/.venv/staende/`.
- **R-Pakete aus CRAN** (`r_packages`) in `~/R/library`, mit Aktualisierung beim Start.
- Installation im Hintergrund, das Terminal ist sofort da. Von Hand: `terminal-pakete`.
- Neu im Image: uv, `rsvg-convert`, cairo.
- Optionen und Übersetzungen kommen aus dem gemeinsamen Gerüst (`options.yaml`).

## 0.17.3 (2026-11-07)

- Open Terminal 0.17.1 → 0.17.3, [Release-Notes](https://github.com/open-webui/open-terminal/releases/tag/v0.17.3)

## 0.17.2 (2026-11-06)

- Austauschordner jetzt `mbox/inbox`, `mbox/outbox` (mailbox.org MCP) und `openwebui/inbox`
  (Chat-Anhänge) statt `inbox/` und `out/`. Mit `/share` als Arbeitsordner gelten die Rechte
  nur für `mbox/` und `openwebui/`. Bestehende Ordner `inbox/` und `out/` bleiben unangetastet.

## 0.17.1 (2026-11-06)

- Open Terminal 0.16.6 → 0.17.1, [Release-Notes](https://github.com/open-webui/open-terminal/releases/tag/v0.17.1)

## 0.16.8 (2026-11-06)

- „Arbeitsordner“ darf jetzt auch `/share` selbst sein. Unterordner regeln dann Skills bzw.
  Anweisungen an das Modell. `~/work` zeigt dann auf `/share`. Rechte per ACL nur auf `inbox/`
  und `out/`; für andere Ordner unter `/share` arbeitet das Modell mit `sudo`.

## 0.16.7 (2026-11-06)

- Behoben: Speichern der Konfiguration schlug mit „does not match regular expression“
  fehl, wenn ein optionales Pfad- oder URL-Feld leer war. Die Felder sind jetzt optional.

## 0.16.6 (2026-11-05)

- Open Terminal 0.16.1 → 0.16.6, [Release-Notes](https://github.com/open-webui/open-terminal/releases/tag/v0.16.6)

## 0.16.1-1 (2026-11-05)

- Besitz des Home-Verzeichnisses wird bei jedem Start geprüft: Gehört der Inhalt nicht
  "user" (z. B. nach einer Migration per scp als root), wird er rekursiv korrigiert.
  Vorher startete das entrypoint.sh des Basis-Images mit "mkdir: Permission denied"
  durch und die App stürzte ab

## 0.16.1 (2026-11-04)

- Open Terminal 0.14.7 → 0.16.1, [Release-Notes](https://github.com/open-webui/open-terminal/releases/tag/v0.16.1)

## 0.14.7-2 (2026-11-04)

- R aus Debian (trixie, R 4.5) mit `r-recommended`, tidyverse, data.table, renv, rmarkdown,
  knitr, readxl, writexl, openxlsx und R-Kernel für Jupyter (fertige Binärpakete, auch arm64)
- Eigene Pakete aus `install.packages()` landen in `~/R/library` (unter `/data`), bleiben bei
  Updates erhalten und sind im Backup. CRAN ist ohne Rückfrage voreingestellt
- Image wird dadurch rund 0,5 GB größer

## 0.14.7-1 (2026-11-01)

- Arbeitsordner: `/share` eingebunden, `~/work` zeigt auf `work_dir` (Standard
  `/share/artcraft/work`), `inbox/` und `out/` werden angelegt
- Schreibrechte für `user` per ACL, auch für später von anderen Apps angelegte Dateien
- Token des Supervisors wird vor dem Start des Terminals entfernt

## 0.14.7 (2026-11-01)

- Erste Version: offizielles Image von Open Terminal 0.14.7 (amd64, arm64)
- API-Schlüssel wird beim ersten Start erzeugt und im Protokoll angezeigt
- Home-Verzeichnis unter `/data/home`: Dateien und nachinstallierte Pakete bleiben bei
  Updates erhalten und im Backup (ohne `.cache` und `.npm`)
