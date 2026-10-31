# Änderungen

## 0.12.5 (2026-11-01)

- Erste Version: offizielles Image von Open WebUI 0.12.5 (amd64, arm64)
- Optionen für öffentliche URL, Geheimschlüssel und Login über OIDC (z. B. Pocket ID)
- Einmalige Übernahme einer bestehenden Installation aus `/addon_configs/…/import`, mit
  Prüfung der Datenbank
- Healthcheck mit 15 Minuten Anlaufzeit, damit Migrationen beim ersten Start nicht vom
  Watchdog abgebrochen werden
- Heruntergeladene Modelle (`cache/embedding`, `cache/whisper`) sind vom Backup ausgenommen
