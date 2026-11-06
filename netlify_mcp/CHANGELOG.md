# Änderungen

Neue Versionen trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.3.1 (2026-11-06)

- **Nachsicht bei Werkzeug-Argumenten (interner Zugriff):** Schickt ein Modell einen Wert im
  falschen Grundtyp (Text statt Liste, "5" statt 5, "true" statt true), passt die Brücke ihn an das
  Schema an, statt mit einem Validierungsfehler abzubrechen. Das Protokoll nennt das Feld.

## 1.3.0 (2026-11-06)

- **Token für den internen Zugriff (`internal_token`, empfohlen):** Gesetzt, verlangt der interne
  Endpunkt `Authorization: Bearer <Token>`. In Open WebUI bei der Verbindung Authentifizierung
  „Bearer“ wählen und das Token eintragen. Schützt vor anderen Apps und Werkzeugen im internen
  Netz, z. B. den Proxy-Funktionen von ha-mcp. Die Dienste selbst sehen das Token nicht.
  Leer = wie bisher ohne Login; das Protokoll weist dann darauf hin.

## 1.2.1 (2026-11-06)

- Alte „(alt)“-Felder auf oberster Ebene entfernt. Öffentliche URL und OIDC stehen nur noch im
  optionalen Abschnitt „Öffentlicher Zugang (LLM-Client)“.

## 1.2.0 (2026-11-06)

- **Konfiguration neu gegliedert:** Öffentliche URL und OIDC-Felder stehen im aufklappbaren
  Abschnitt „Öffentlicher Zugang (LLM-Client)“, oben bleiben die eigenen Optionen. Werte von
  vorher auf oberster Ebene gelten weiter (als „(alt)“ angezeigt) und gehen beim Update nicht
  verloren; das Protokoll weist darauf hin. Bitte in den Abschnitt übertragen und die alten
  Felder leeren.
- Optionen und Übersetzungen kommen jetzt aus dem gemeinsamen Gerüst (`options.yaml`,
  `common/options/blocks.yaml`).

## 1.1.3 (2026-11-06)

- Behoben: Speichern der Konfiguration schlug mit „does not match regular expression“
  fehl, wenn ein optionales Pfad- oder URL-Feld leer war. Die Felder sind jetzt optional.

## 1.1.2 (2026-11-05)

- Die OIDC-Felder (Konfigurations-URL, Client-ID, Client-Secret) stehen jetzt immer in der
  Konfiguration. Vorher waren sie ohne Wert unter „Unbenutzte optionale Konfigurationsoptionen
  anzeigen“ versteckt. Leer bleiben darf weiterhin, solange keine öffentliche URL gesetzt ist.

## 1.1.1 (2026-11-04)

- Behoben: Speichern ohne OIDC (nur interner Zugriff) schlug fehl mit „Missing required option
  'oidc_configuration_url'“. Die OIDC-Felder haben keinen leeren Standardwert mehr und stehen
  bei leerer Konfiguration unter „Ungenutzte optionale Konfigurationsoptionen anzeigen“
- Öffentliche URL ist im Formular nicht mehr als Pflichtfeld markiert

## 1.1.0 (2026-11-04)

- Neu: interner Zugriff ohne Login (`internal_access`), z. B. für Open WebUI auf demselben Home
  Assistant, unter `http://<repo-hash>-netlify-mcp:9080/mcp`. Nur im internen Docker-Netz
- OIDC-Optionen und `external_url` sind nur noch Pflicht für den öffentlichen Zugang
- Image enthält jetzt `python3` (Standardbibliothek, für die Brücke)

## 1.0.2 (2026-10-27)

- @netlify/mcp 1.20.0 → 1.21.0

## 1.0.1 (2026-10-21)

- @netlify/mcp 1.19.0 → 1.20.0

## 1.0.0 (2026-10-18)

- Erste Version: @netlify/mcp 1.19.0 (Node 22), mcp-auth-proxy 2.10.2
- Server-Token und OIDC-Daten als Add-on-Optionen statt Portainer-Variablen
- Das OIDC-Secret wird nur an den Proxy übergeben, nicht an den MCP-Server
- Einmalige Übernahme von Proxy-Daten aus einem früheren Docker-Stack (`legacy_auth_dir`)
