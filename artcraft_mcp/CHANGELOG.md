# Änderungen

Neue Versionen der Apps trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.0.8 (2026-10-31)

- Offene Schriften im Image: DejaVu, Liberation (Arial-, Times- und Courier-kompatibel),
  Open Sans, Lato und Inter, je Familie Regular, Italic, Bold und BoldItalic (#1)
- Kopie der Schriften nach `<work_dir>/fonts/standard`, damit PdfCraft sie findet und einbettet
  (neue Option `fonts_to_work`, Standard an)
- Eigene Schriften unter `<work_dir>/fonts` gelten für alle drei Apps
- Selbsttest prüft, dass PdfCraft Schriften findet und eine davon in eine PDF einbettet

## 1.0.7 (2026-10-31)

- VectorCraft 0.18.0 → 0.19.0
- PhotoCraft 0.17.0 → 0.18.0
- PdfCraft 0.15.0 → 0.16.1

## 1.0.6 (2026-10-29)

- VectorCraft 0.17.0 → 0.18.0
- PhotoCraft 0.16.0 → 0.17.0
- PdfCraft 0.14.0 → 0.15.0

## 1.0.5 (2026-10-26)

- VectorCraft 0.16.0 → 0.17.0
- PhotoCraft 0.15.1 → 0.16.0
- PdfCraft 0.13.0 → 0.14.0

## 1.0.4 (2026-10-24)

- PhotoCraft 0.14.0 → 0.15.1

## 1.0.3 (2026-10-23)

- VectorCraft 0.14.0 → 0.16.0
- PhotoCraft 0.12.0 → 0.14.0
- PdfCraft 0.11.0 → 0.13.0

## 1.0.2 (2026-10-22)

- PhotoCraft 0.11.1 → 0.12.0
- PdfCraft 0.10.1 → 0.11.0

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
