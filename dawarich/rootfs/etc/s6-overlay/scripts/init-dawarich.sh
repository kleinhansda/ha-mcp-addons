#!/usr/bin/with-contenv bashio

export PATH="/usr/lib/postgresql/17/bin:${PATH}"

# --- Create persistent data directories (HA mounts /data fresh) ---
mkdir -p /data/postgres /data/redis /data/dawarich/storage /data/dawarich/public
mkdir -p /var/app/tmp/imports/watched
mkdir -p /run/postgresql && chown postgres:postgres /run/postgresql

# --- Hardcoded infrastructure env vars ---
for kv in \
  "DATABASE_HOST=localhost" \
  "DATABASE_PORT=5432" \
  "DATABASE_USERNAME=dawarich" \
  "DATABASE_NAME=dawarich_production" \
  "REDIS_URL=redis://localhost:6379/0" \
  "RAILS_ENV=production" \
  "SELF_HOSTED=true" \
  "STORE_GEODATA=true" \
  "APPLICATION_PROTOCOL=http" \
  "RAILS_LOG_TO_STDOUT=true" \
  "SIDEKIQ_EMBEDDED=true" \
  "WEB_CONCURRENCY=0"; do
  key="${kv%%=*}"
  val="${kv#*=}"
  printf '%s' "$val" > "/var/run/s6/container_environment/${key}"
done

# --- User-configurable env vars ---
printf '%s' "$(bashio::config 'database_password')" > /var/run/s6/container_environment/DATABASE_PASSWORD
printf '%s' "$(bashio::config 'time_zone')" > /var/run/s6/container_environment/TIME_ZONE
printf '%s' "$(bashio::config 'application_hosts')" > /var/run/s6/container_environment/APPLICATION_HOSTS
printf '%s' "$(bashio::config 'background_processing_concurrency')" > /var/run/s6/container_environment/BACKGROUND_PROCESSING_CONCURRENCY

# DOMAIN is what Dawarich uses to build absolute URLs in mails (Devise unlock and
# password-reset instructions). Unset, rendering those mails raises "Missing host
# to link to!" and the request 500s — which is what a locked-out account hits on
# its next login attempt, instead of being told the account is locked.
#
# Dawarich hardcodes https:// in those links, so the address only works from
# outside if it is one you actually reach over https through a reverse proxy.
# `external_url` overrides the guess for that case; without it
# we keep using the first application_hosts entry, which is right for LAN use.
# bashio 0.16.2 treats an empty default argument as "null". Check existence
# explicitly so omitted optional strings stay empty during upgrades.
optional_config_string() {
  if bashio::config.exists "$1"; then
    bashio::config "$1"
  fi
}

PRIMARY_HOST="$(optional_config_string 'external_url')"
PRIMARY_HOST="${PRIMARY_HOST#https://}"
PRIMARY_HOST="${PRIMARY_HOST#http://}"
PRIMARY_HOST="${PRIMARY_HOST%%/*}"
if [ -z "$PRIMARY_HOST" ]; then
  PRIMARY_HOST="$(bashio::config 'application_hosts' | cut -d',' -f1 | xargs)"
fi
[ -z "$PRIMARY_HOST" ] && PRIMARY_HOST="homeassistant.local"
printf '%s' "$PRIMARY_HOST" > /var/run/s6/container_environment/DOMAIN

# --- SMTP ---
# Dawarich always sets ActionMailer's delivery method to :smtp in production, so
# with nothing configured Rails still tries to deliver and the job fails with
# "SMTP-AUTH requested but missing user name" — the default authentication is
# `plain` and there is no user name to send. Nothing in the app surfaces that;
# it only shows up as a job retrying in the background. Family invitations,
# password resets and digest mails all go through it.
SMTP_SERVER="$(optional_config_string 'smtp_server')"
if [ -n "$SMTP_SERVER" ]; then
  SMTP_FROM="$(optional_config_string 'smtp_from')"
  [ -z "$SMTP_FROM" ] && SMTP_FROM="$(bashio::config 'admin_email')"
  SMTP_AUTH="$(bashio::config 'smtp_authentication' 'plain')"
  SMTP_USERNAME="$(optional_config_string 'smtp_username')"

  printf '%s' "$SMTP_SERVER"                             > /var/run/s6/container_environment/SMTP_SERVER
  printf '%s' "$(bashio::config 'smtp_port' '587')"      > /var/run/s6/container_environment/SMTP_PORT
  printf '%s' "$SMTP_FROM"                               > /var/run/s6/container_environment/SMTP_FROM
  printf '%s' "$SMTP_AUTH"                               > /var/run/s6/container_environment/SMTP_AUTHENTICATION

  # Only write credentials when there are some. An unauthenticated relay needs
  # smtp_authentication set to none, and Dawarich reads an empty user name as a
  # user name, which is what produces the SMTP-AUTH error above.
  if [ -n "$SMTP_USERNAME" ]; then
    printf '%s' "$SMTP_USERNAME"                          > /var/run/s6/container_environment/SMTP_USERNAME
    printf '%s' "$(optional_config_string 'smtp_password')" > /var/run/s6/container_environment/SMTP_PASSWORD
  elif [ "$SMTP_AUTH" != "none" ]; then
    bashio::log.warning "SMTP: smtp_username is empty but smtp_authentication is '${SMTP_AUTH}'."
    bashio::log.warning "SMTP: set smtp_authentication to 'none' for an unauthenticated relay, or mail will fail to send."
  fi

  # Defaults to on when the option is absent: an unset key should not quietly
  # downgrade the connection to plaintext.
  if [ "$(bashio::config 'smtp_starttls' 'true')" = "false" ]; then
    printf '%s' "false" > /var/run/s6/container_environment/SMTP_STARTTLS
  else
    printf '%s' "true"  > /var/run/s6/container_environment/SMTP_STARTTLS
  fi

  bashio::log.info "SMTP: enabled (${SMTP_SERVER}, from ${SMTP_FROM}, auth ${SMTP_AUTH})"
  bashio::log.info "SMTP: links in mails will point at https://${PRIMARY_HOST}"
else
  bashio::log.info "SMTP: not configured — Dawarich will not send mail"
fi

# Admin user credentials
printf '%s' "$(bashio::config 'admin_email')" > /var/run/s6/container_environment/ADMIN_EMAIL
printf '%s' "$(bashio::config 'admin_password')" > /var/run/s6/container_environment/ADMIN_PASSWORD

# Dawarich rejects passwords shorter than 12 characters. Creating the admin user
# would fail with "Password is too short" and leave the app with no account to
# log in with, so warn about it here rather than at the point of failure.
ADMIN_PW="$(bashio::config 'admin_password')"
if [ -n "$ADMIN_PW" ] && [ ${#ADMIN_PW} -lt 12 ]; then
  bashio::log.warning "admin_password is only ${#ADMIN_PW} characters — Dawarich requires at least 12."
  bashio::log.warning "The admin user cannot be created until you set a longer password in the app configuration."
fi

# HA location tracker settings
printf '%s' "$(optional_config_string 'ha_tracked_entities')" > /var/run/s6/container_environment/HA_TRACKED_ENTITIES
printf '%s' "$(bashio::config 'ha_min_distance')" > /var/run/s6/container_environment/HA_MIN_DISTANCE

# --- Reverse geocoding ---
# Der Test beim Start darf den Start nie verhindern: das Skript läuft mit `set -e` (bashio),
# und ein nicht erreichbarer Geocoder (Server aus, gesperrte IP) hat in der Vorlage die ganze
# App lahmgelegt (curl exit 7, init-dawarich bricht ab, Ingress 502). Jeder Aufruf ist hier
# mit `|| true` abgesichert und auf 10 s begrenzt; ein Fehler ergibt nur eine Warnung.
geocoder_probe() {   # $1 = URL, $2 = jq-Ausdruck für den Ortsnamen
  local antwort code ort
  antwort=$(curl -4 -s -m 10 -w '\n%{http_code}' "$1" 2>/dev/null) || true
  code=$(printf '%s' "$antwort" | tail -n 1)
  ort=$(printf '%s' "$antwort" | sed '$d' | jq -r "$2 // empty" 2>/dev/null) || true
  if [ -n "$ort" ]; then
    bashio::log.info "Reverse geocoding: erreichbar (Test: ${ort})"
  else
    bashio::log.warning "Reverse geocoding: Testabfrage fehlgeschlagen (HTTP ${code:-000}). Dawarich startet trotzdem;"
    bashio::log.warning "Reverse geocoding: Punkte bleiben ohne Ort, bis der Dienst erreichbar ist."
  fi
}

if bashio::config.true 'reverse_geocoding'; then
  PHOTON_URL="$(optional_config_string 'photon_api_host')"
  PHOTON_KEY="$(optional_config_string 'photon_api_key')"
  PHOTON_LANG="$(optional_config_string 'photon_language')"
  GEOAPIFY_KEY="$(optional_config_string 'geoapify_api_key')"
  if [ -n "$PHOTON_URL" ]; then
    # Dawarich erwartet den Host ohne Schema und das Protokoll getrennt in PHOTON_API_USE_HTTPS.
    PHOTON_URL="${PHOTON_URL%/}"
    case "$PHOTON_URL" in http://*|https://*) ;; *) PHOTON_URL="https://${PHOTON_URL}" ;; esac
    PHOTON_HOST="${PHOTON_URL#https://}"
    PHOTON_HOST="${PHOTON_HOST#http://}"
    printf '%s' "$PHOTON_HOST" > /var/run/s6/container_environment/PHOTON_API_HOST
    if [[ "$PHOTON_URL" == https://* ]]; then
      printf '%s' "true" > /var/run/s6/container_environment/PHOTON_API_USE_HTTPS
    else
      printf '%s' "false" > /var/run/s6/container_environment/PHOTON_API_USE_HTTPS
    fi
    [ -n "$PHOTON_LANG" ] && printf '%s' "$PHOTON_LANG" > /var/run/s6/container_environment/PHOTON_API_LANGUAGE
    if [ -n "$PHOTON_KEY" ]; then
      printf '%s' "$PHOTON_KEY" > /var/run/s6/container_environment/PHOTON_API_KEY
      bashio::log.info "Reverse geocoding: Photon (${PHOTON_HOST}, mit API-Schlüssel)"
    else
      bashio::log.info "Reverse geocoding: Photon (${PHOTON_HOST})"
      geocoder_probe "${PHOTON_URL}/reverse?lat=50.1109&lon=8.6821" '.features[0].properties.city'
    fi
    case "$PHOTON_HOST" in
      photon.komoot.io*)
        bashio::log.warning "Reverse geocoding: photon.komoot.io ist der öffentliche Server (1 Abfrage/s, sperrt bei großen Mengen)."
        bashio::log.warning "Reverse geocoding: für viele Punkte einen eigenen Photon-Server eintragen." ;;
    esac
  elif [ -n "$GEOAPIFY_KEY" ]; then
    printf '%s' "$GEOAPIFY_KEY" > /var/run/s6/container_environment/GEOAPIFY_API_KEY
    bashio::log.info "Reverse geocoding: Geoapify"
    geocoder_probe "https://api.geoapify.com/v1/geocode/reverse?lat=50.1109&lon=8.6821&apiKey=${GEOAPIFY_KEY}" '.features[0].properties.city'
  else
    bashio::log.warning "Reverse geocoding: eingeschaltet, aber weder photon_api_host noch geoapify_api_key gesetzt, bleibt aus."
  fi
else
  bashio::log.info "Reverse geocoding: aus"
fi

# --- Umzug aus einer anderen Dawarich-App ---
# /share/dawarich_umzug.tar.gz enthält das Verzeichnis dawarich/ der alten App (mit
# secret_key_base, Dateien und backup.sql als Datenbank-Dump, siehe DOCS.md). Übernommen wird es
# nur in eine frische Installation: ohne Datenbank und ohne eigenen Schlüssel. Den Dump spielt
# svc-dawarich ein (gleicher Weg wie bei der Wiederherstellung eines Backups); danach wird das
# Archiv in dawarich_umzug.tar.gz.importiert umbenannt.
UMZUG=/share/dawarich_umzug.tar.gz
if [ -f "$UMZUG" ]; then
  if [ ! -f /data/postgres/PG_VERSION ] && [ ! -f /data/dawarich/secret_key_base ]; then
    bashio::log.info "Umzug: übernehme ${UMZUG} ($(du -h "$UMZUG" | cut -f1))..."
    tar -xzf "$UMZUG" -C /data dawarich/secret_key_base dawarich/backup.sql || true
    if [ -s /data/dawarich/backup.sql ] && [ -s /data/dawarich/secret_key_base ]; then
      tar -xzf "$UMZUG" -C /data dawarich/storage 2>/dev/null || true
      tar -xzf "$UMZUG" -C /data dawarich/public 2>/dev/null || true
      printf '%s' "$UMZUG" > /data/dawarich/.umzug_quelle
      bashio::log.info "Umzug: Schlüssel und Dateien übernommen, die Datenbank wird beim Start eingespielt."
    else
      bashio::log.error "Umzug: im Archiv fehlen dawarich/backup.sql oder dawarich/secret_key_base, nichts übernommen."
      rm -f /data/dawarich/backup.sql /data/dawarich/secret_key_base
    fi
  else
    bashio::log.warning "Umzug: ${UMZUG} liegt bereit, diese App hat aber schon Daten. Nicht übernommen."
  fi
fi

# --- SECRET_KEY_BASE: auto-generate on first run, persist to /data ---
if [ -f /data/dawarich/secret_key_base ]; then
  cat /data/dawarich/secret_key_base > /var/run/s6/container_environment/SECRET_KEY_BASE
else
  openssl rand -hex 64 | tee /data/dawarich/secret_key_base > /var/run/s6/container_environment/SECRET_KEY_BASE
fi

# --- PostgreSQL init on first run ---
# A missing cluster means either a first install or a restored backup (HA backups
# exclude postgres/**). svc-dawarich needs to tell those apart to decide whether
# it may import a SQL dump, so record it here.
printf '%s' "false" > /var/run/s6/container_environment/PG_FRESH_INIT
if [ ! -f /data/postgres/PG_VERSION ]; then
  bashio::log.info "Initializing PostgreSQL database..."
  printf '%s' "true" > /var/run/s6/container_environment/PG_FRESH_INIT
  chown -R postgres:postgres /data/postgres
  su - postgres -c "PATH=/usr/lib/postgresql/17/bin:\$PATH initdb -D /data/postgres"
  # Trust auth: safe because PG binds to localhost only, port 5432 not exposed
  cat > /data/postgres/pg_hba.conf <<'PGEOF'
# Trust is safe here: PostgreSQL is only accessible via localhost within
# this container. Port 5432 is NOT exposed to the host or other containers.
local   all   all                 trust
host    all   all   127.0.0.1/32  trust
host    all   all   ::1/128       trust
PGEOF
fi

# Ensure ownership is correct on restarts
chown -R postgres:postgres /data/postgres
chown -R postgres:postgres /run/postgresql

# --- Generate nginx ingress proxy config ---
# Fetch the ingress entry path from Supervisor API (e.g. /api/hassio_ingress/<token>)
INGRESS_ENTRY=$(curl -s -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
  http://supervisor/addons/self/info 2>/dev/null | jq -r '.data.ingress_entry // empty')

if [ -n "$INGRESS_ENTRY" ]; then
  # Remove trailing slash
  INGRESS_ENTRY="${INGRESS_ENTRY%/}"
  bashio::log.info "Ingress path: ${INGRESS_ENTRY}"
  sed "s|INGRESS_PATH|${INGRESS_ENTRY}|g" \
    /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
else
  bashio::log.warning "Could not determine ingress path, using passthrough"
  sed "s|INGRESS_PATH||g" \
    /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
fi
