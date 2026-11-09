# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist. mailchimp-mcp und seine
Abhängigkeiten sind in `requirements.txt` fest eingetragen und werden von Hand aktualisiert.

## 1.1.0 (2026-11-10)

- Neue Werkzeuge für große Newsletter (HTML um 100 KB, zu groß für `set_campaign_content` aus
  einem Modell): `find_in_campaign_content` (Fundstellen im vollständigen HTML),
  `replace_in_campaign_content` (gezielte Ersetzungen, alles oder nichts) und
  `upload_file_from_share` (Bild aus `/share` statt Base64). Schreibende nur ab Umfang `entwuerfe`.
- `/share` wird nur lesend eingebunden.

## 1.0.0 (2026-11-09)

- Erste Version: [mailchimp-mcp](https://github.com/damientilman/mailchimp-mcp-server) 1.2.0
  (MCP-SDK 1.30) mit drei Umfängen: **lesen** (Standard, ca. 20 Werkzeuge, Schreiben gesperrt),
  **entwuerfe** (zusätzlich Kampagnen-Entwürfe und Testmails, kein Versand) und **alle**.
- Probelauf, weitere Werkzeuge per Name, interner Zugriff mit Token über die Brücke, öffentlicher
  Zugang mit OIDC über mcp-auth-proxy.
