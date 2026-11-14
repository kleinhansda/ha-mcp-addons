# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.1.4 (2026-11-14)

- mcp-auth-proxy 2.10.4 → 2.10.6

## 1.1.3 (2026-11-13)

- mcp-auth-proxy 2.10.2 → 2.10.4

## 1.1.2 (2026-11-07)

- **Brücke (interner Zugriff):** Falsch benannte Argumente werden umbenannt, wenn eindeutig (ein
  Pflichtfeld fehlt, genau ein unbekanntes Feld ist da, z. B. `command` statt `id`), auch in den
  Schritten eines Batches. Das Protokoll nennt die Umbenennung.

## 1.1.1 (2026-11-06)

- **Nachsicht bei Werkzeug-Argumenten (interner Zugriff):** Schickt ein Modell einen Wert im
  falschen Grundtyp (Text statt Liste, "5" statt 5, "true" statt true), passt die Brücke ihn an das
  Schema an, statt mit einem Validierungsfehler abzubrechen. Das Protokoll nennt das Feld.

## 1.1.0 (2026-11-06)

- **Token für den internen Zugriff (`internal_token`, empfohlen):** Gesetzt, verlangt der interne
  Endpunkt `Authorization: Bearer <Token>`. In Open WebUI bei der Verbindung Authentifizierung
  „Bearer“ wählen und das Token eintragen. Schützt vor anderen Apps und Werkzeugen im internen
  Netz, z. B. den Proxy-Funktionen von ha-mcp. Die Dienste selbst sehen das Token nicht.
  Leer = wie bisher ohne Login; das Protokoll weist dann darauf hin.

## 1.0.1 (2026-11-06)

- Startskript: Hinweis auf alte Felder entfernt.

## 1.0.0 (2026-11-06)

- Erste Version: eigener MCP-Server für Paperless-ngx (nur Python-Standardbibliothek) mit
  `paperless_search`, `paperless_get_document`, `paperless_preview`, `paperless_similar`,
  `paperless_list` und, ohne „Nur lesen“, `paperless_update_document`, `paperless_add_note`,
  `paperless_upload`.
- Filter nach Namen statt IDs, Treffer mit Textauszug und Link zur Weboberfläche.
- Beim Start prüft das Log, ob Paperless erreichbar und das Token gültig ist.
