# Änderungen

Neue Versionen trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.0.1 (2026-10-21)

- @netlify/mcp 1.19.0 → 1.20.0

## 1.0.0 (2026-10-18)

- Erste Version: @netlify/mcp 1.19.0 (Node 22), mcp-auth-proxy 2.10.2
- Server-Token und OIDC-Daten als Add-on-Optionen statt Portainer-Variablen
- Das OIDC-Secret wird nur an den Proxy übergeben, nicht an den MCP-Server
- Einmalige Übernahme von Proxy-Daten aus einem früheren Docker-Stack (`legacy_auth_dir`)
