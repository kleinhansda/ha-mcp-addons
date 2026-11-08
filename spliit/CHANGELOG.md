# Änderungen

## 1.0.0 (2026-11-08)

- Erste Version im Repo, aus der lokalen App übernommen: Spliit 1.22.0 mit eingebautem
  PostgreSQL 16, täglicher SQL-Dump nach `/backup`, Ereignis `spliit_activity` für Home Assistant.
- Neu gegenüber der lokalen App: Optionen `backup_days` und `ha_events`, Port 3000 standardmäßig
  nicht freigegeben (Zugang über Cloudflared), konsistente HA-Backups (`backup: cold`), Dumps
  erst nach erfolgreichem Abschluss sichtbar, Start bricht nach 60 s ohne PostgreSQL ab.
