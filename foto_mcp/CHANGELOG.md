# Änderungen

## 1.0.1 (2026-10-31)

- Keine Stufen mehr in Himmel und Verläufen: Entrauschen nur noch der Farbe (Helligkeit erst ab ISO 1600, halb), Schärfen mit Schwelle, Speichern mit Dithering
- Weißpunkt aus dem hellsten Kanal, dadurch laufen bläuliche Himmel nicht mehr neu aus (vorher bis 10 % ausgefressen)
- Lichter werden über eine kantenerhaltende Basisebene etwas abgesenkt, Struktur in hellen Fassaden bleibt
- `clarity` auf 16-Bit-Helligkeit und nur in strukturierten Bereichen, glatte Flächen bleiben unverändert

## 1.0.0 (2026-10-31)

- Erste Version: eigener MCP-Server mit Python 3.11, OpenCV 4.14 und MediaPipe 1.2 (Face Landmarker)
- Werkzeuge: `ordner_sichten`, `vorschau`, `neigung_messen`, `aussortieren`, `optimieren`, `retusche`, `job_status`
- Optimieren und Retusche laufen als Hintergrundjob, einer nach dem anderen
- Arbeitsordner wie bei ArtCraft MCP (`/share/artcraft/work`), Zugriffe außerhalb werden abgelehnt
- Selbsttest prüft auf beiden Architekturen Schräglage, Gesichtsmodell, Job und Pfadgrenze
