# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.0.0 (2026-11-06)

- Erste Version: eigener MCP-Server für Paperless-ngx (nur Python-Standardbibliothek) mit
  `paperless_search`, `paperless_get_document`, `paperless_preview`, `paperless_similar`,
  `paperless_list` und, ohne „Nur lesen“, `paperless_update_document`, `paperless_add_note`,
  `paperless_upload`.
- Filter nach Namen statt IDs, Treffer mit Textauszug und Link zur Weboberfläche.
- Beim Start prüft das Log, ob Paperless erreichbar und das Token gültig ist.
