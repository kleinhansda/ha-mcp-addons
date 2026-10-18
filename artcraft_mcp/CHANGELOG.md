# Änderungen

Neue Versionen der Apps trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.0.0 (2026-10-18)

- Erste Version: VectorCraft 0.13.1, PhotoCraft 0.10.0, PdfCraft 0.9.0, mcp-auth-proxy 2.10.2
- Ein Proxy je App auf den Ports 8081 bis 8083, jede App einzeln abschaltbar
- Abgestürzte Dienste starten einzeln neu, die anderen laufen weiter
- Das OIDC-Secret wird nur an den Proxy übergeben, nicht an die Apps
- Einmalige Übernahme von Proxy-Daten aus einem früheren Docker-Stack (`legacy_auth_dir`)
