# Spliit

[Spliit](https://github.com/spliit-app/spliit) teilt Ausgaben in Gruppen, ähnlich wie Splitwise:
Gruppen per Link teilen, Ausgaben erfassen, Salden und Ausgleichszahlungen sehen. Diese App
bringt PostgreSQL mit, es braucht keine weitere Datenbank.

## Installation

1. **Spliit** aus „didi's Apps“ installieren und starten. Beim ersten Start legt die App die
   Datenbank an (im Protokoll: `Neue Datenbank`, dann `PostgreSQL … bereit`).
2. Zugang von außen über das Cloudflared-Add-on: neue Route, z. B. `split.example.com` →
   `http://be60cb4b-spliit:3000`.
3. Optional in die Seitenleiste von Home Assistant: Einstellungen → Dashboards → Dashboard
   hinzufügen → Webseite, mit der HTTPS-Adresse aus Schritt 2.

Der Port 3000 ist standardmäßig nicht nach außen freigegeben. Nur eintragen, wenn du Spliit ohne
Cloudflared im Heimnetz direkt aufrufen willst.

> **Kein Login:** Spliit hat keine Benutzerkonten. Wer den Link einer Gruppe kennt, kann sie
> sehen und ändern. Für den Zugang aus dem Internet einen Schutz davorschalten, z. B. Cloudflare
> Access oder einen Worker mit Passwortabfrage.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `backup_days` | Täglicher SQL-Dump nach `/backup/spliit-<Datum>.sql`, so viele Tage aufbewahren. 0 = aus |
| `ha_events` | Neue Aktivitäten alle 30 s als Ereignis `spliit_activity` an Home Assistant melden |

## Ereignisse in Home Assistant

Mit `ha_events` meldet die App jede neue Aktivität als Ereignis `spliit_activity` mit den Feldern
`type` (z. B. `CREATE_EXPENSE`), `group`, `group_id`, `participant` und `details`. Beispiel für
eine Benachrichtigung:

```yaml
triggers:
  - trigger: event
    event_type: spliit_activity
    event_data:
      type: CREATE_EXPENSE
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.participant }}: {{ trigger.event.data.details }} ({{ trigger.event.data.group }})"
```

## Sicherung

- Home-Assistant-Backups enthalten die Datenbank. Die App wird dafür kurz angehalten
  (`backup: cold`), damit das Abbild konsistent ist.
- Zusätzlich, mit `backup_days` > 0, ein täglicher SQL-Dump nach `/backup`. Wiederherstellen in
  eine leere Datenbank, z. B. im Terminal der App:
  `psql -U spliit -h 127.0.0.1 -d spliit < /backup/spliit-2026-11-08.sql`.
  ⚠️ Nur in eine leere Datenbank einspielen, sonst entstehen doppelte oder widersprüchliche
  Einträge.

## Technik

Basis ist das offizielle Image `ghcr.io/spliit-app/spliit` (Version in `Dockerfile`, `SPLIIT_VERSION`)
plus PostgreSQL 16 aus Alpine. Die Datenbank liegt unter `/data/postgres`, nur auf 127.0.0.1
erreichbar. Schema-Änderungen neuer Spliit-Versionen spielt `prisma migrate deploy` beim Start ein.
