# Änderungen

Neue Versionen der Apps trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.4.0 (2026-11-04)

- Umzug: Das Add-on liegt wieder in `kleinhansda/ha-mcp-addons`. Neuer Hostname
  `be60cb4b-artcraft-mcp`, Tunnel und Connectoren umstellen (siehe DOCS, „Umzug aus artcraft-mcp-ha“)
- Schriften zurück: DejaVu, Liberation, Open Sans, Lato, Inter im Image, Option `fonts_to_work`
  kopiert sie für PdfCraft in den Arbeitsordner, eigene Schriften in `<work_dir>/fonts`
- Selbsttest prüft, dass PdfCraft Schriften findet und einbetten kann

## 1.3.0 (2026-11-03)

- Neu: Interner Zugriff ohne Login (`internal_apps`), z. B. für Open WebUI auf demselben
  Home Assistant. Je App unter `http://<add-on-hostname>:9081/mcp` usw. (Port + 1000), nur im
  internen Docker-Netz. Die App startet erst beim ersten Zugriff.
- OIDC-Optionen sind nur noch Pflicht, wenn eine öffentliche URL eingetragen ist.
- Behoben: Craft Anything startete trotz `craft_anything_url` nicht (Optionsname falsch gelesen).

## 1.2.1 (2026-11-03)

- VectorCraft 0.20.0 → 0.21.0
- PhotoCraft 0.19.0 → 0.20.1
- PdfCraft 0.17.0 → 0.18.0
- CADCraft 0.16.0 → 0.17.0
- WordCraft 0.14.0 → 0.15.0
- DeckCraft 0.14.1 → 0.15.0
- GridCraft 0.15.0 → 0.16.0
- FigCraft 0.14.0 → 0.15.0

## 1.2.0 (2026-11-02)

- Neu: CADCraft 0.16.0 - 2D-CAD, Zeichnungen (DXF/DWG), Port 8085
- Neu: WordCraft 0.14.0 - Textverarbeitung (.docx, .doc), Port 8086
- Neu: DeckCraft 0.14.1 - Präsentationen (.pptx), Port 8087
- Neu: GridCraft 0.15.0 - Tabellenkalkulation (.xlsx), Port 8088
- Neu: FigCraft 0.14.0 - Interface-Design, Prototyping, Port 8089
- Neu: Craft Anything 0.3.0 - Reverse Engineering, Rebuild, Port 8090

## 1.1.7 (2026-11-02)

- VectorCraft 0.19.0 → 0.20.0
- PhotoCraft 0.18.0 → 0.19.0
- PdfCraft 0.16.1 → 0.17.0

## 1.1.6 (2026-10-31)

- VectorCraft 0.18.0 → 0.19.0
- PhotoCraft 0.17.0 → 0.18.0
- PdfCraft 0.15.0 → 0.16.1

## 1.1.5 (2026-10-29)

- VectorCraft 0.17.0 → 0.18.0
- PhotoCraft 0.16.0 → 0.17.0
- PdfCraft 0.14.0 → 0.15.0

## 1.1.4 (2026-10-26)

- VectorCraft 0.16.0 → 0.17.0
- PhotoCraft 0.15.1 → 0.16.0
- PdfCraft 0.13.0 → 0.14.0

## 1.1.3 (2026-10-24)

- PhotoCraft 0.14.0 → 0.15.1

## 1.1.2 (2026-10-23)

- VectorCraft 0.14.0 → 0.16.0
- PhotoCraft 0.12.0 → 0.14.0
- PdfCraft 0.11.0 → 0.13.0

## 1.1.1 (2026-10-22)

- PhotoCraft 0.11.1 → 0.12.0
- PdfCraft 0.10.1 → 0.11.0

## 1.1.0 (2026-10-21)

- Neue App „Dateien“ (Port 8084, Option `files_url`): MCP-Server für den Arbeitsordner mit
  `files_list`, `file_get` und `file_put`. Damit erreicht Claude in der Cloud Exporte der Apps und
  kann Dateien ablegen. Ohne `files_url` wird sie nicht gestartet, bestehende Installationen
  ändern sich nicht.
- Image enthält jetzt `python3` (Debian, mit Standardbibliothek).

## 1.0.1 (2026-10-21)

- VectorCraft 0.13.1 → 0.14.0
- PhotoCraft 0.10.0 → 0.11.1
- PdfCraft 0.9.0 → 0.10.1

## 1.0.0 (2026-10-18)

- Erste Version: VectorCraft 0.13.1, PhotoCraft 0.10.0, PdfCraft 0.9.0, mcp-auth-proxy 2.10.2
- Ein Proxy je App auf den Ports 8081 bis 8083, jede App einzeln abschaltbar
- Abgestürzte Dienste starten einzeln neu, die anderen laufen weiter
- Das OIDC-Secret wird nur an den Proxy übergeben, nicht an die Apps
- Einmalige Übernahme von Proxy-Daten aus einem früheren Docker-Stack (`legacy_auth_dir`)
