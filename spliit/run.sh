#!/bin/sh
# Start von Spliit mit eingebautem PostgreSQL (Daten in /data/postgres).
# Optionen: backup_days (tägliche SQL-Dumps nach /backup), ha_events (Ereignis spliit_activity).
set -e
OPTIONS=${OPTIONS_PATH:-/data/options.json}
DATA=${SPLIIT_DATA:-/data}
BACKUP=${SPLIIT_BACKUP:-/backup}
PGDATA=$DATA/postgres
log() { echo "[spliit] $*"; }
opt() { [ -f "$OPTIONS" ] && jq -r --arg k "$1" '.[$k] // empty' "$OPTIONS" || true; }

BACKUP_DAYS=$(opt backup_days); BACKUP_DAYS=${BACKUP_DAYS:-7}
HA_EVENTS=$(opt ha_events); HA_EVENTS=${HA_EVENTS:-true}

export POSTGRES_PRISMA_URL="postgresql://spliit@127.0.0.1:5432/spliit"
export POSTGRES_URL_NON_POOLING="$POSTGRES_PRISMA_URL"

# --- PostgreSQL (nur auf 127.0.0.1, Vertrauen ohne Passwort, da nur im Container erreichbar)
mkdir -p /run/postgresql "$PGDATA"
chown -R postgres:postgres /run/postgresql "$PGDATA"
chmod 700 "$PGDATA"
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  log "Neue Datenbank in $PGDATA"
  su-exec postgres initdb -D "$PGDATA" -U spliit --auth=trust >/dev/null
fi
# Nach einem harten Abbruch kann eine alte PID-Datei den Start blockieren
rm -f "$PGDATA/postmaster.pid"
su-exec postgres postgres -D "$PGDATA" -c listen_addresses=127.0.0.1 &
PG_PID=$!
i=0
until pg_isready -h 127.0.0.1 -q; do
  i=$((i + 1)); [ $i -gt 60 ] && { log "FEHLER: PostgreSQL startet nicht"; exit 1; }
  sleep 1
done
psql -U spliit -h 127.0.0.1 -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='spliit'" | grep -q 1 \
  || createdb -U spliit -h 127.0.0.1 spliit
log "PostgreSQL $(psql -U spliit -h 127.0.0.1 -d spliit -Atc 'SHOW server_version') bereit"

# --- Schema anlegen/aktualisieren (vor dem Watcher, der braucht die Tabelle Activity)
npx prisma migrate deploy

# --- Tägliche Sicherung nach /backup
if [ "$BACKUP_DAYS" -gt 0 ] 2>/dev/null && [ -d "$BACKUP" ]; then
  log "Tägliche Sicherung nach $BACKUP/spliit-<Datum>.sql, $BACKUP_DAYS Tage"
  ( while true; do
      f="$BACKUP/spliit-$(date +%F).sql"
      if pg_dump -U spliit -h 127.0.0.1 spliit > "$f.part"; then mv "$f.part" "$f"; else rm -f "$f.part"; fi
      find "$BACKUP" -maxdepth 1 -name 'spliit-*.sql' -mtime +"$BACKUP_DAYS" -delete
      sleep 86400
    done ) &
else
  log "Keine eigene Sicherung (backup_days=0)"
fi

# --- Neue Aktivitäten als Home-Assistant-Ereignis spliit_activity
if [ "$HA_EVENTS" = "true" ] && [ -n "$SUPERVISOR_TOKEN" ]; then
  STATE=$DATA/spliit_last_activity
  cat > /tmp/watch.sql <<'SQL'
SELECT a."time"::text || '|' || json_build_object(
  'type', a."activityType",
  'group', g."name",
  'group_id', a."groupId",
  'participant', p."name",
  'details', a."data"
)::text
FROM "Activity" a
JOIN "Group" g ON g."id" = a."groupId"
LEFT JOIN "Participant" p ON p."id" = a."participantId"
WHERE a."time" > :'last'::timestamp
ORDER BY a."time";
SQL
  [ -s "$STATE" ] || psql -U spliit -h 127.0.0.1 -d spliit -At \
    -c 'SELECT COALESCE(MAX("time"), now()::timestamp)::text FROM "Activity"' > "$STATE"
  log "Ereignisse an Home Assistant: spliit_activity"
  ( while true; do
      sleep 30
      LAST=$(cat "$STATE")
      psql -U spliit -h 127.0.0.1 -d spliit -At -v last="$LAST" -f /tmp/watch.sql 2>/dev/null \
      | while IFS= read -r line; do
          ts="${line%%|*}"
          json="${line#*|}"
          if curl -fsS -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" \
            -d "$json" "http://supervisor/core/api/events/spliit_activity" >/dev/null; then
            echo "$ts" > "$STATE"
          else
            break
          fi
        done
    done ) &
else
  log "Keine Ereignisse an Home Assistant"
fi

# --- Spliit (Arbeitsverzeichnis und Startbefehl aus dem Basis-Image)
log "Starte Spliit auf Port 3000"
npm run start &
APP_PID=$!

stop_all() {
  kill "$APP_PID" 2>/dev/null || true
  su-exec postgres pg_ctl stop -D "$PGDATA" -m fast >/dev/null 2>&1 || kill "$PG_PID" 2>/dev/null || true
}
trap 'log "Stoppe"; stop_all; exit 0' TERM INT

set +e
wait "$APP_PID"
RC=$?
log "Spliit beendet mit Exit-Code $RC"
stop_all
exit $RC
