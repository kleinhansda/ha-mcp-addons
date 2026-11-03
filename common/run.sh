#!/bin/bash
# Gemeinsames Startskript aller Add-ons dieses Repos.
# Quelle: common/run.sh. Die Kopien in <add-on>/rootfs/run.sh müssen identisch sein,
# das prüft der Build (.github/scripts/sync_common.py).
#
# Startet je Dienst aus /usr/local/lib/mcp/services.sh bis zu zwei Zugänge, die sich nicht
# ausschließen:
# - öffentlich: mit eingetragener URL ein mcp-auth-proxy (OIDC-Login) auf PORTS[dienst]
# - intern: mit internal_access die Brücke mcp_bridge.py ohne Login auf PORTS[dienst] + 1000,
#   nur im internen Docker-Netz (z. B. für Open WebUI auf demselben Home Assistant)
# Stürzt ein Dienst ab, startet seine Schleife ihn neu, die anderen Dienste laufen weiter.
set -euo pipefail

OPTS="${MCP_OPTIONS:-/data/options.json}"   # für Tests überschreibbar
DATA="${MCP_DATA:-/data}"
VERSIONS="${MCP_VERSIONS:-/usr/local/share/mcp-versions}"
BRIDGE="${MCP_BRIDGE:-/usr/local/lib/mcp/mcp_bridge.py}"
SERVICES_SH="${MCP_SERVICES:-/usr/local/lib/mcp/services.sh}"

log()    { echo "[addon] $*"; }
fehler() { echo "[addon] FEHLER: $*" >&2; exit 1; }
opt()    { jq -r --arg k "$1" '.[$k] // "" | tostring' "$OPTS"; }

[ -f "$OPTS" ] || fehler "$OPTS fehlt"

# services.sh definiert SERVICES, PORTS, URL_OPTION sowie service_setup und service_cmd.
# shellcheck source=/dev/null
source "$SERVICES_SH"

OIDC_CONFIGURATION_URL="$(opt oidc_configuration_url)"
OIDC_CLIENT_ID="$(opt oidc_client_id)"
OIDC_CLIENT_SECRET="$(opt oidc_client_secret)"
OIDC_ALLOWED_USERS="$(opt oidc_allowed_users)"
PROVIDER="$(opt oidc_provider_name)"
LEGACY="$(opt legacy_auth_dir)"
INTERN="$(opt internal_access)"

# Öffentliche URLs je Dienst. OIDC ist nur für den öffentlichen Zugang Pflicht.
declare -A URLS=()
oeffentlich=0
for svc in "${SERVICES[@]}"; do
  url="$(opt "${URL_OPTION[$svc]}")"
  if [ -n "$url" ]; then URLS[$svc]="${url%/}"; oeffentlich=$(( oeffentlich + 1 )); fi
done

if (( oeffentlich > 0 )); then
  [ -n "$OIDC_CONFIGURATION_URL" ] || fehler "oidc_configuration_url ist leer (nötig für öffentliche URLs)"
  [ -n "$OIDC_CLIENT_ID" ]         || fehler "oidc_client_id ist leer (nötig für öffentliche URLs)"
  [ -n "$OIDC_CLIENT_SECRET" ]     || fehler "oidc_client_secret ist leer (nötig für öffentliche URLs)"
  # Der Proxy liest die OIDC-Werte aus der Umgebung (so tauchen sie nicht in der
  # Prozessliste auf). Die MCP-Server bekommen sie nicht, siehe "env -u" unten.
  export OIDC_CONFIGURATION_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET
  if [ -n "$OIDC_ALLOWED_USERS" ]; then export OIDC_ALLOWED_USERS; fi
fi
export HOME=/tmp

service_setup

log "Versionen:"
sed 's/^/[addon]   /' "$VERSIONS"

# neustarten <name> <befehl ...>: führt den Befehl in einer Schleife aus.
# Länger gelaufen: kurz warten. Sofort wieder beendet: Pause verdoppeln, höchstens 60 s.
neustarten() {
  local name=$1 pause=5 start
  shift
  while true; do
    start=$SECONDS
    "$@" 2>&1 | sed -u "s/^/[$name] /" || true
    if (( SECONDS - start > 60 )); then pause=5; elif (( pause < 60 )); then pause=$(( pause * 2 )); fi
    log "$name: beendet, Neustart in ${pause} s"
    sleep "$pause"
  done
}

oeffentlicher_dienst() {
  local svc=$1 url=$2 port=${PORTS[$1]} data="$DATA/$1" src
  mkdir -p "$data"

  # Einmalige Übernahme der Proxy-Daten (registrierte Clients, Schlüssel) aus einer
  # früheren Installation, damit Claude nicht neu verbunden werden muss.
  # Mehrere Dienste: Unterordner je Dienst. Ein Dienst: der Ordner selbst.
  if [ -n "$LEGACY" ] && [ -z "$(ls -A "$data")" ]; then
    src="$LEGACY/$svc"
    if [ ! -d "$src" ] && [ "${#SERVICES[@]}" -eq 1 ]; then src="$LEGACY"; fi
    if [ -d "$src" ]; then
      cp -a "$src/." "$data/"
      log "$svc: Proxy-Daten aus $src übernommen"
    fi
  fi

  service_cmd "$svc"
  log "$svc: öffentlich auf Port $port für $url (mit Login)"
  neustarten "$svc" mcp-auth-proxy \
    --listen ":$port" \
    --external-url "$url" \
    --no-auto-tls \
    --data-path "$data" \
    --oidc-provider-name "$PROVIDER" \
    -- env -u OIDC_CLIENT_SECRET -u OIDC_CLIENT_ID -u OIDC_CONFIGURATION_URL -u OIDC_ALLOWED_USERS \
    "${CMD[@]}"
}

interner_dienst() {
  local svc=$1 port=$(( PORTS[$1] + 1000 ))
  service_cmd "$svc"
  log "$svc: intern ohne Login unter http://$HOST:$port/mcp"
  neustarten "$svc:intern" python3 "$BRIDGE" "$port" -- \
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

# Hostname der App im internen Netz (Form xxxxxxxx-<slug>), nur für das Log.
HOST="$(hostname)"

n=0
for svc in "${SERVICES[@]}"; do
  gestartet=0
  if [ -n "${URLS[$svc]:-}" ]; then
    oeffentlicher_dienst "$svc" "${URLS[$svc]}" &
    gestartet=1
  fi
  if [ "$INTERN" = true ]; then
    interner_dienst "$svc" &
    gestartet=1
  fi
  if (( gestartet )); then
    n=$(( n + 1 ))
  else
    log "$svc: weder URL (${URL_OPTION[$svc]}) noch internal_access, wird nicht gestartet"
  fi
done
(( n > 0 )) || fehler "Kein Dienst aktiviert. Eine URL eintragen oder internal_access einschalten."

wait
