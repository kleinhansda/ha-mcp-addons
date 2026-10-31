# Änderungen

## 1.0.0 (2026-10-31)

- Erste Version: eigener MCP-Server mit Python 3.11, OpenCV 4.14 und MediaPipe 1.2 (Face Landmarker)
- Werkzeuge: `ordner_sichten`, `vorschau`, `neigung_messen`, `aussortieren`, `optimieren`, `retusche`, `job_status`
- Optimieren und Retusche laufen als Hintergrundjob, einer nach dem anderen
- Arbeitsordner wie bei ArtCraft MCP (`/share/artcraft/work`), Zugriffe außerhalb werden abgelehnt
- Selbsttest prüft auf beiden Architekturen Schräglage, Gesichtsmodell, Job und Pfadgrenze
