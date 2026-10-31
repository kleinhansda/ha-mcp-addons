#!/usr/bin/env bash
# Test der Open-WebUI-App im CI: frischer Start, danach Übernahme der dabei
# entstandenen Datenbank in eine zweite, leere App (Import-Pfad).
#   bash .github/scripts/test_open_webui.sh <image>
set -euo pipefail
IMG=${1:?Image fehlt}
W=$(mktemp -d)
trap 'docker rm -f owui-test >/dev/null 2>&1 || true' EXIT

opts() {
  cat > "$1/options.json" <<JSON
{"webui_url":"http://localhost:8080","webui_secret_key":"","oidc_configuration_url":"","oidc_provider_name":"Test",
 "oidc_client_id":"","oidc_client_secret":"","oidc_signup":false,"oidc_merge_by_email":false,"login_form":true,
 "extra_env":["ENABLE_SIGNUP=true"]}
JSON
}

start() { # $1 data, $2 config
  docker rm -f owui-test >/dev/null 2>&1 || true
  docker run -d --name owui-test -p 18080:8080 -v "$1:/data" -v "$2:/config" "$IMG" >/dev/null
  for i in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:18080/health 2>/dev/null | grep -q '"status":true'; then
      echo "gesund nach $((i * 5)) s"; return 0
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' owui-test)" != "true" ]; then break; fi
    sleep 5
  done
  docker logs owui-test | tail -n 80
  echo "FEHLER: Open WebUI wurde nicht gesund"; exit 1
}

echo "== 1. Frischer Start"
mkdir -p "$W/d1" "$W/c1"; opts "$W/d1"
start "$W/d1" "$W/c1"
docker logs owui-test 2>&1 | grep -q "\[open-webui-app\] Starte Open WebUI" || { echo "FEHLER: run.sh lief nicht"; exit 1; }
# Nutzer anlegen, damit die Datenbank Inhalt hat
curl -fsS -X POST http://127.0.0.1:18080/api/v1/auths/signup -H 'Content-Type: application/json' \
  -d '{"name":"Test","email":"test@example.org","password":"Test-1234-abcd"}' >/dev/null
docker stop owui-test >/dev/null
test -s "$W/d1/webui.db" || { echo "FEHLER: /data/webui.db fehlt"; exit 1; }
test -s "$W/d1/.webui_secret_key" || { echo "FEHLER: Schlüssel nicht in /data"; exit 1; }

echo "== 2. Übernahme in leere App"
mkdir -p "$W/d2" "$W/c2/import"; opts "$W/d2"
sudo cp -a "$W/d1/webui.db" "$W/d1/.webui_secret_key" "$W/c2/import/"
start "$W/d2" "$W/c2"
docker logs owui-test 2>&1 | grep -q "Übernahme fertig" || { docker logs owui-test | tail -n 40; echo "FEHLER: keine Übernahme"; exit 1; }
sudo cmp "$W/d1/.webui_secret_key" "$W/d2/.webui_secret_key" || { echo "FEHLER: Schlüssel nicht übernommen"; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:18080/api/v1/auths/signin \
  -H 'Content-Type: application/json' -d '{"email":"test@example.org","password":"Test-1234-abcd"}')
[ "$code" = "200" ] || { echo "FEHLER: Anmeldung mit übernommenem Nutzer: HTTP $code"; exit 1; }
ls "$W/c2" | grep -q '^import.erledigt-' || { echo "FEHLER: Import-Ordner nicht umbenannt"; exit 1; }
echo "Alles ok"
