# Dawarich

[Dawarich](https://github.com/Freika/dawarich) speichert Standortverläufe (Handy-Apps, Home-Assistant-Tracker,
Google-Takeout-Import) und zeigt sie als Karte, Zeitleiste, Reisen und Statistiken. Die App bringt
PostgreSQL mit PostGIS, Redis und einen nginx für die Seitenleiste mit; Hintergrundaufgaben laufen
im Prozess der Weboberfläche.

Grundlage sind die Startskripte von
[thomdev-j/dawarich-home-assistant-addon](https://github.com/thomdev-j/dawarich-home-assistant-addon)
(AGPL-3.0, siehe `LICENSE`). Diese App folgt neuen Dawarich-Versionen selbst: ein täglicher Workflow
trägt sie nach bestandenem Test ein.

## Unterschiede zur Vorlage

- **Start trotz Geocoder-Ausfall:** Ist der Photon- oder Geoapify-Dienst beim Start nicht
  erreichbar, gibt es nur eine Warnung. In der Vorlage blieb die ganze App stehen (Seitenleiste 502).
- **Länder und Grunddaten:** `rails db:seed` läuft nach dem Anlegen des Admin-Kontos. Ohne die
  Ländertabelle bekommen Punkte beim Reverse Geocoding kein Land („no country record“).
- **Datenmigrationen:** `rake data:migrate` läuft wie im offiziellen Image bei jedem Start.
- **Hintergrundaufgaben eingebettet** (seit Dawarich 1.17 Standard), kein eigener Sidekiq-Dienst.
- **Umzug** aus einer anderen Dawarich-App über `/share/dawarich_umzug.tar.gz` (siehe unten).
- Option `photon_language` für Ortsnamen in einer anderen Sprache.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `admin_email`, `admin_password` | Konto, das beim Start angelegt wird. Passwort mindestens 12 Zeichen, gilt nur beim Anlegen. |
| `reverse_geocoding` | Orte, Städte und Länder zu den Punkten ermitteln. |
| `photon_api_host` | Eigener Photon-Server, z. B. `http://192.168.1.10:2322`. Der öffentliche Server `photon.komoot.io` erlaubt 1 Abfrage pro Sekunde und sperrt bei großen Mengen. |
| `photon_language` | Sprache der Ortsnamen, z. B. `de`. |
| `geoapify_api_key` | Alternative zu Photon. |
| `ha_tracked_entities` | `device_tracker`- oder `person`-Entitäten, deren Positionen an Dawarich gehen; mit `:name` ein eigenes Konto. |
| `external_url` | Externe HTTPS-Adresse für Links in Mails. |
| `smtp_*` | Mailversand für Passwort-Zurücksetzen und Einladungen. |

Port 3000 ist die Weboberfläche und API für Handy-Apps (OwnTracks, Overland, Dawarich-App). Der
API-Schlüssel steht in Dawarich unter Einstellungen → Konto.

Rails-Befehle im Container: `docker exec -it <container> dawarich-rails runner "puts Point.count"`.

## Sicherung

Home-Assistant-Backups enthalten die Datenbank als SQL-Dump (`backup_pre.sh`), nicht die
Rohdateien. Beim Wiederherstellen spielt die App den Dump beim nächsten Start selbst ein.

## Umzug aus einer anderen Dawarich-App

Übernimmt Datenbank, Dateien (Importe, Exporte) und den Schlüssel `secret_key_base`. Ohne diesen
Schlüssel wären verschlüsselte Einstellungen (z. B. API-Schlüssel von Integrationen, 2FA) nicht
mehr lesbar; deshalb nicht nur einen Datenbank-Export umziehen.

> **Achtung:** Die neue App übernimmt das Archiv nur, solange sie noch keine eigenen Daten hat.
> Wurde sie schon einmal gestartet, erst deinstallieren (Daten löschen) und neu installieren.
> Die alte App erst entfernen, wenn in der neuen alles da ist.

1. In Home Assistant ein Backup der alten App anlegen.
2. Im Terminal (Schutzmodus der Terminal-App aus) den Namen des alten Containers suchen und die
   Daten nach `/share` packen:

   ```
   docker ps --format '{{.Names}}' | grep -i dawarich
   ALT=app_xxxxxxxx_dawarich      # Name aus der Zeile oben
   docker exec "$ALT" /usr/share/dawarich/backup_pre.sh
   docker exec "$ALT" sh -c 'tar -C /data -czf /share/dawarich_umzug.tar.gz dawarich && rm -f /data/dawarich/backup.sql'
   ls -lh /share/dawarich_umzug.tar.gz
   ```

3. Die alte App **stoppen** (beide nutzen Port 3000, und der Tracker würde Punkte doppelt schicken).
4. Diese App installieren, die Konfiguration übernehmen (in der alten App „Als YAML bearbeiten“,
   kopieren, hier einfügen) und starten.
5. Im Protokoll erscheinen „Umzug: Schlüssel und Dateien übernommen“ und „Database restored“.
   Das Archiv heißt danach `dawarich_umzug.tar.gz.importiert` und kann gelöscht werden.

Nach dem Umzug holt Dawarich Datenmigrationen und Hintergrundaufgaben nach (z. B. Besuche über die
ganze Historie erkennen); das kann eine Weile dauern. Die Fortschritte zeigt Sidekiq unter
Einstellungen → Hintergrundaufgaben.
