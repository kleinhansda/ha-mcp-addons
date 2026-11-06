#!/bin/bash
# Startet je App zwei mögliche Zugänge, die sich nicht ausschließen:
# - öffentlich: App mit eingetragener URL bekommt einen mcp-auth-proxy (OIDC-Login),
#   Port 8081 bis 8090.
# - intern: App in internal_apps bekommt die Brücke mcp_bridge.py ohne Anmeldung,
#   Port 9081 bis 9090, nur im internen Docker-Netz erreichbar (z. B. für Open WebUI).
# Stürzt ein Dienst ab, startet ihn seine Schleife neu, die anderen laufen weiter.
set -euo pipefail

# shellcheck source=rootfs/usr/local/lib/artcraft/apps.sh
source /usr/local/lib/artcraft/apps.sh

OPTS="${ARTCRAFT_OPTIONS:-/data/options.json}"   # für Tests überschreibbar
DATA="${ARTCRAFT_DATA:-/data}"
VERSIONS="${ARTCRAFT_VERSIONS:-/usr/local/share/artcraft-versions}"
BRIDGE="${ARTCRAFT_BRIDGE:-/usr/local/lib/artcraft/mcp_bridge.py}"

log()    { echo "[artcraft] $*"; }
fehler() { echo "[artcraft] FEHLER: $*" >&2; exit 1; }
# URLs und OIDC stehen im optionalen Abschnitt "public" (aufklappbar im UI).
opt()    { jq -r --arg k "$1" '((.public // {})[$k] // "" | tostring) as $n
                               | if $n != "" then $n else (.[$k] // "" | tostring) end' "$OPTS"; }
intern() { jq -e --arg a "$1" '(.internal_apps // []) | index($a) != null' "$OPTS" >/dev/null; }

[ -f "$OPTS" ] || fehler "$OPTS fehlt"

OIDC_CONFIGURATION_URL="$(opt oidc_configuration_url)"
OIDC_CLIENT_ID="$(opt oidc_client_id)"
OIDC_CLIENT_SECRET="$(opt oidc_client_secret)"
OIDC_ALLOWED_USERS="$(opt oidc_allowed_users)"
PROVIDER="$(opt oidc_provider_name)"
WORK="$(opt work_dir)"
LEGACY="$(opt legacy_auth_dir)"
PDFCRAFT_COMPACT="$(opt pdfcraft_compact)"

[ -n "$WORK" ] || fehler "work_dir ist leer"

# Welche App läuft wie? Optionsnamen nutzen "_" (craft_anything_url), App-Namen "-".
declare -A URLS=()
oeffentlich=0
for app in "${APPS[@]}"; do
  url="$(opt "${app//-/_}_url")"
  if [ -n "$url" ]; then URLS[$app]="${url%/}"; oeffentlich=$(( oeffentlich + 1 )); fi
done

# OIDC ist nur für den öffentlichen Zugang Pflicht.
if (( oeffentlich > 0 )); then
  [ -n "$OIDC_CONFIGURATION_URL" ] || fehler "oidc_configuration_url ist leer (nötig für öffentliche URLs)"
  [ -n "$OIDC_CLIENT_ID" ]         || fehler "oidc_client_id ist leer (nötig für öffentliche URLs)"
  [ -n "$OIDC_CLIENT_SECRET" ]     || fehler "oidc_client_secret ist leer (nötig für öffentliche URLs)"
  # Der Proxy liest die OIDC-Werte aus der Umgebung (so taucht das Secret nicht in der
  # Prozessliste auf). Die Apps selbst bekommen die Werte nicht, siehe "env -u" unten.
  export OIDC_CONFIGURATION_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET
  if [ -n "$OIDC_ALLOWED_USERS" ]; then export OIDC_ALLOWED_USERS; fi
fi
export PDFCRAFT_COMPACT
export HOME=/tmp

mkdir -p "$WORK"
# Alle Apps laufen im Arbeitsordner. CADCraft, GridCraft und Craft Anything haben keine
# Root-Option; relative Pfade beim Speichern landeten sonst im Container (/ bzw. /tmp)
# und waren für Open Terminal, Open WebUI und die anderen Apps unsichtbar.
cd "$WORK"
log "Versionen:"
sed 's/^/[artcraft]   /' "$VERSIONS"
log "Arbeitsordner: $WORK"
schriften_einrichten "$WORK" "$(opt fonts_to_work)"
log "Schriften: $(find "$WORK/fonts" -type f \( -name '*.ttf' -o -name '*.otf' \) | wc -l) Dateien in $WORK/fonts"

# neustarten <app> <befehl ...>: führt den Befehl in einer Schleife aus.
# Länger gelaufen: kurz warten. Sofort wieder beendet: Pause verdoppeln, höchstens 60 s.
neustarten() {
  local app=$1 pause=5 start
  shift
  while true; do
    start=$SECONDS
    "$@" 2>&1 | sed -u "s/^/[$app] /" || true
    if (( SECONDS - start > 60 )); then pause=5; elif (( pause < 60 )); then pause=$(( pause * 2 )); fi
    log "$app: beendet, Neustart in ${pause} s"
    sleep "$pause"
  done
}

oeffentlicher_dienst() {
  local app=$1 url=$2 port=${PORTS[$1]} data="$DATA/$1"
  mkdir -p "$data"

  # Einmalige Übernahme der Proxy-Daten (registrierte Clients, Schlüssel) aus einer
  # früheren Installation. Dann muss Claude nicht neu verbunden werden.
  if [ -n "$LEGACY" ] && [ -d "$LEGACY/$app" ] && [ -z "$(ls -A "$data")" ]; then
    cp -a "$LEGACY/$app/." "$data/"
    log "$app: Proxy-Daten aus $LEGACY/$app übernommen"
  fi

  app_cmd "$app" "$WORK"
  log "$app: öffentlich auf Port $port für $url (mit Login)"
  neustarten "$app" mcp-auth-proxy \
    --listen ":$port" \
    --external-url "$url" \
    --no-auto-tls \
    --data-path "$data" \
    --oidc-provider-name "$PROVIDER" \
    -- env -u OIDC_CLIENT_SECRET -u OIDC_CLIENT_ID -u OIDC_CONFIGURATION_URL -u OIDC_ALLOWED_USERS \
    "${CMD[@]}"
}

interner_dienst() {
  local app=$1 port=${INTERNAL_PORTS[$1]}
  app_cmd "$app" "$WORK"
  log "$app: intern ohne Login unter http://$HOST:$port/mcp"
  neustarten "$app:intern" python3 "$BRIDGE" "$port" -- \
    env -u OIDC_CLIENT_SECRET -u OIDC_CLIENT_ID -u OIDC_CONFIGURATION_URL -u OIDC_ALLOWED_USERS \
    "${CMD[@]}"
}

beenden() {
  trap '' TERM INT
  log "Stoppe Dienste"
  kill -TERM 0 2>/dev/null || true
  wait || true
  exit 0
}
trap beenden TERM INT

# Hostname des Add-ons im internen Netz (Form xxxxxxxx-artcraft-mcp), nur für das Log.
HOST="$(hostname)"

# Bis 1.4.8 gab es hier die App "files", jetzt eigene App Files MCP.
if intern files; then
  log "Hinweis: Die App „files“ gibt es in ArtCraft nicht mehr, sie ist jetzt die eigene App Files MCP." \
      "files aus internal_apps nehmen; Umstieg siehe DOCS von Files MCP."
fi

n=0
for app in "${APPS[@]}"; do
  gestartet=0
  if [ -n "${URLS[$app]:-}" ]; then
    oeffentlicher_dienst "$app" "${URLS[$app]}" &
    gestartet=1
  fi
  if intern "$app"; then
    interner_dienst "$app" &
    gestartet=1
  fi
  if (( gestartet )); then
    n=$(( n + 1 ))
  else
    log "$app: weder URL noch interner Zugriff eingetragen, wird nicht gestartet"
  fi
done
(( n > 0 )) || fehler "Keine App aktiviert. Eine URL eintragen oder Apps unter internal_apps wählen."

wait
