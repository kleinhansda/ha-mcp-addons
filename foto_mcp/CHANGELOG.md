# Änderungen

## 1.1.1 (2026-11-04)

- Behoben: Speichern ohne OIDC (nur interner Zugriff) schlug fehl mit „Missing required option
  'oidc_configuration_url'“. Die OIDC-Felder haben keinen leeren Standardwert mehr und stehen
  bei leerer Konfiguration unter „Ungenutzte optionale Konfigurationsoptionen anzeigen“
- Öffentliche URL ist im Formular nicht mehr als Pflichtfeld markiert

## 1.1.0 (2026-11-04)

- Neu: interner Zugriff ohne Login (`internal_access`), z. B. für Open WebUI auf demselben Home
  Assistant, unter `http://<repo-hash>-foto-mcp:9080/mcp`. Nur im internen Docker-Netz
- OIDC-Optionen und `external_url` sind nur noch Pflicht für den öffentlichen Zugang

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
