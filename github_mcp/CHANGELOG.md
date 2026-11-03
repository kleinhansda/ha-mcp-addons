# Änderungen

Neue Versionen trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.1.0 (2026-11-04)

- Neu: interner Zugriff ohne Login (`internal_access`), z. B. für Open WebUI auf demselben Home
  Assistant, unter `http://<repo-hash>-github-mcp:9080/mcp`. Nur im internen Docker-Netz
- OIDC-Optionen und `external_url` sind nur noch Pflicht für den öffentlichen Zugang
- Image enthält jetzt `python3` (Standardbibliothek, für die Brücke)

## 1.0.2 (2026-11-03)

- github-mcp-server 2.0.3 → 2.1.0

## 1.0.1 (2026-10-22)

- github-mcp-server 2.0.2 → 2.0.3

## 1.0.0 (2026-10-18)

- Erste Version: github-mcp-server 2.0.2, mcp-auth-proxy 2.10.2
- Server-Token und OIDC-Daten als Add-on-Optionen statt Portainer-Variablen
- Das OIDC-Secret wird nur an den Proxy übergeben, nicht an den MCP-Server
- Einmalige Übernahme von Proxy-Daten aus einem früheren Docker-Stack (`legacy_auth_dir`)
