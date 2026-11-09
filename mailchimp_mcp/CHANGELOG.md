# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist. mailchimp-mcp und seine
Abhängigkeiten sind in `requirements.txt` fest eingetragen und werden von Hand aktualisiert.

## 1.0.0 (2026-11-09)

- Erste Version: [mailchimp-mcp](https://github.com/damientilman/mailchimp-mcp-server) 1.2.0
  (MCP-SDK 1.30) mit drei Umfängen: **lesen** (Standard, ca. 20 Werkzeuge, Schreiben gesperrt),
  **entwuerfe** (zusätzlich Kampagnen-Entwürfe und Testmails, kein Versand) und **alle**.
- Probelauf, weitere Werkzeuge per Name, interner Zugriff mit Token über die Brücke, öffentlicher
  Zugang mit OIDC über mcp-auth-proxy.
