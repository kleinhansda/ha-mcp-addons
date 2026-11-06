# Änderungen

Neue Versionen trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist.

## 1.2.3 (2026-11-06)

- Alte „(alt)“-Felder auf oberster Ebene entfernt. Öffentliche URL und OIDC stehen nur noch im
  optionalen Abschnitt „Öffentlicher Zugang (LLM-Client)“.

## 1.2.2 (2026-11-06)

- Texte im Abschnitt „Öffentlicher Zugang“ neutral (LLM-Client), Optionen und Übersetzungen
  aus dem gemeinsamen Gerüst (`options.yaml`, `common/options/blocks.yaml`).

## 1.2.1 (2026-11-06)

- Behoben: Speichern der Konfiguration schlug mit „does not match regular expression“
  fehl, wenn ein optionales Pfad- oder URL-Feld leer war. Die Felder sind jetzt optional.

## 1.2.0 (2026-11-05)

- **Konfiguration neu gegliedert:** Öffentliche URL und alle OIDC-Felder stehen im aufklappbaren
  Abschnitt „Öffentlicher Zugang (Claude-App)“. Oben bleiben interner Zugriff, Token und
  Server-Optionen. Wer nur intern arbeitet, lässt den Abschnitt zu.
- Werte aus 1.1.x auf oberster Ebene gelten weiter (als „(alt)“ angezeigt) und gehen beim Update
  nicht verloren. Das Protokoll weist darauf hin; bitte in den Abschnitt übertragen und die
  alten Felder leeren.

## 1.1.1 (2026-11-04)

- Behoben: Speichern ohne OIDC (nur interner Zugriff) schlug fehl mit „Missing required option
  'oidc_configuration_url'“. Die OIDC-Felder haben keinen leeren Standardwert mehr und stehen
  bei leerer Konfiguration unter „Ungenutzte optionale Konfigurationsoptionen anzeigen“
- Öffentliche URL ist im Formular nicht mehr als Pflichtfeld markiert

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
