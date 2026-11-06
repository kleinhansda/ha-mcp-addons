# Änderungen

## 0.13.1 (2026-11-06)

- Behoben: Speichern der Konfiguration schlug mit „does not match regular expression“
  fehl, wenn ein optionales Pfad- oder URL-Feld leer war. Die Felder sind jetzt optional.

## 0.13.0 (2026-11-04)

- Open WebUI 0.12.5 → 0.13.0, [Release-Notes](https://github.com/open-webui/open-webui/releases/tag/v0.13.0)
- Vor dem Update ein Backup anlegen lassen: Datenbank-Migrationen lassen sich nicht rückgängig machen

## 0.12.5-1 (2026-11-01)

- Web-Suche mit eigener SearXNG-Instanz in der App (Option `searxng`, Standard an). Open
  WebUI wird bei jedem Start darauf eingestellt
- Open Terminal: mit `open_terminal_api_key` trägt die App die Verbindung zur neuen App
  „Open Terminal“ selbst ein (nur für Admins, Freigaben bleiben erhalten)

## 0.12.5 (2026-11-01)

- Erste Version: offizielles Image von Open WebUI 0.12.5 (amd64, arm64)
- Optionen für öffentliche URL, Geheimschlüssel und Login über OIDC (z. B. Pocket ID)
- Einmalige Übernahme einer bestehenden Installation aus `/addon_configs/…/import`, mit
  Prüfung der Datenbank
- Healthcheck mit 15 Minuten Anlaufzeit, damit Migrationen beim ersten Start nicht vom
  Watchdog abgebrochen werden
- Heruntergeladene Modelle (`cache/embedding`, `cache/whisper`) sind vom Backup ausgenommen
