# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.1.0 (2026-11-06)

- **Token für den internen Zugriff (`internal_token`, empfohlen):** Gesetzt, verlangt der interne
  Endpunkt `Authorization: Bearer <Token>`. In Open WebUI bei der Verbindung Authentifizierung
  „Bearer“ wählen und das Token eintragen. Schützt vor anderen Apps und Werkzeugen im internen
  Netz, z. B. den Proxy-Funktionen von ha-mcp. Die Dienste selbst sehen das Token nicht.
  Leer = wie bisher ohne Login; das Protokoll weist dann darauf hin.

## 1.0.2 (2026-11-06)

- Startskript: Hinweis auf alte Felder entfernt.

## 1.0.1 (2026-11-06)

- Optionen und Übersetzungen aus dem gemeinsamen Gerüst (`options.yaml`,
  `common/options/blocks.yaml`), Texte vereinheitlicht.

## 1.0.0 (2026-11-06)

- Erste Version. Datei-Server aus ArtCraft ausgelagert und erweitert: 11 Werkzeuge
  (`files_list`, `file_info` mit Metadaten, `file_read_text`, `file_write_text`, `file_edit`,
  `file_search`, `file_move`, `file_trash`, `file_get`/`file_put` in Teilen, `file_preview`).
- Optionen `root`, `read_only`, `protected`, `max_mb`; öffentlicher Zugang mit OIDC und
  interner Zugriff ohne Login wie bei den anderen MCP-Apps.
