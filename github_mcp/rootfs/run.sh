#!/bin/bash
# Gemeinsames Startskript aller Add-ons dieses Repos.
# Quelle: common/run.sh. Die Kopien in <add-on>/rootfs/run.sh müssen identisch sein,
# das prüft der Build (.github/scripts/sync_common.py).
#
# Startet je Dienst aus /usr/local/lib/mcp/services.sh einen mcp-auth-proxy, der den
# stdio-MCP-Server des Dienstes anbindet. Stürzt ein Dienst ab, startet seine Schleife
# ihn neu, die anderen Dienste laufen weiter.
set -euo pipefail

OPTS="${MCP_OPTIONS:-/data/options.json}"   # für Tests überschreibbar
DATA="${MCP_DATA:-/data}"

log()    { echo "[addon] $*"; }
fehler() { echo "[addon] FEHLER: $*" >&2; exit 1; }
opt()    { jq -r --arg k "$1" '.[$k] // "" | tostring' "$OPTS"; }

[ -f "$OPTS" ] || fehler "$OPTS fehlt"

# services.sh definiert SERVICES, PORTS, URL_OPTION sowie service_setup und service_cmd.
# shellcheck source=/dev/null
source /usr/local/lib/mcp/services.sh

OIDC_CONFIGURATION_URL="$(opt oidc_configuration_url)"
OIDC_CLIENT_ID="$(opt oidc_client_id)"
OIDC_CLIENT_SECRET="$(opt oidc_client_secret)"
OIDC_ALLOWED_USERS="$(opt oidc_allowed_users)"
PROVIDER="$(opt oidc_provider_name)"
LEGACY="$(opt legacy_auth_dir)"

[ -n "$OIDC_CONFIGURATION_URL" ] || fehler "oidc_configuration_url ist leer"
[ -n "$OIDC_CLIENT_ID" ]         || fehler "oidc_client_id ist leer"
[ -n "$OIDC_CLIENT_SECRET" ]     || fehler "oidc_client_secret ist leer"

# Der Proxy liest die OIDC-Werte aus der Umgebung (so tauchen sie nicht in der
# Prozessliste auf). Die MCP-Server bekommen sie nicht, siehe "env -u" unten.
export OIDC_CONFIGURATION_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET
if [ -n "$OIDC_ALLOWED_USERS" ]; then export OIDC_ALLOWED_USERS; fi
export HOME=/tmp

service_setup

log "Versionen:"
sed 's/^/[addon]   /' /usr/local/share/mcp-versions

dienst() {
  local svc=$1 url=$2 port=${PORTS[$1]} data="$DATA/$1" pause=5 start src
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
  while true; do
    start=$SECONDS
    log "$svc: Start auf Port $port für $url"
    mcp-auth-proxy \
      --listen ":$port" \
      --external-url "$url" \
      --no-auto-tls \
      --data-path "$data" \
      --oidc-provider-name "$PROVIDER" \
      -- env -u OIDC_CLIENT_SECRET -u OIDC_CLIENT_ID -u OIDC_CONFIGURATION_URL -u OIDC_ALLOWED_USERS \
      "${CMD[@]}" 2>&1 | sed -u "s/^/[$svc] /" || true
    # Länger gelaufen: kurz warten. Sofort wieder beendet: Pause verdoppeln, höchstens 60 s.
    if (( SECONDS - start > 60 )); then pause=5; elif (( pause < 60 )); then pause=$(( pause * 2 )); fi
    log "$svc: beendet, Neustart in ${pause} s"
    sleep "$pause"
  done
}

beenden() {
  trap '' TERM INT
  log "Stoppe Dienste"
  kill -TERM 0 2>/dev/null || true
  wait || true
  exit 0
}
trap beenden TERM INT

n=0
for svc in "${SERVICES[@]}"; do
  url="$(opt "${URL_OPTION[$svc]}")"
  if [ -n "$url" ]; then
    dienst "$svc" "${url%/}" &
    n=$(( n + 1 ))
  else
    log "$svc: keine URL eingetragen (${URL_OPTION[$svc]}), wird nicht gestartet"
  fi
done
[ "$n" -gt 0 ] || fehler "Kein Dienst aktiviert. Mindestens eine URL eintragen."

wait
