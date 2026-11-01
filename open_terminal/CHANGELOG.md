# Änderungen

## 0.14.7-1 (2026-11-01)

- Arbeitsordner: `/share` eingebunden, `~/work` zeigt auf `work_dir` (Standard
  `/share/artcraft/work`), `inbox/` und `out/` werden angelegt
- Schreibrechte für `user` per ACL, auch für später von anderen Apps angelegte Dateien
- Token des Supervisors wird vor dem Start des Terminals entfernt

## 0.14.7 (2026-11-01)

- Erste Version: offizielles Image von Open Terminal 0.14.7 (amd64, arm64)
- API-Schlüssel wird beim ersten Start erzeugt und im Protokoll angezeigt
- Home-Verzeichnis unter `/data/home`: Dateien und nachinstallierte Pakete bleiben bei
  Updates erhalten und sind im Backup (ohne `.cache` und `.npm`)
