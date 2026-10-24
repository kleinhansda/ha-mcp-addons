# Änderungen

Neue Versionen der Apps trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

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
