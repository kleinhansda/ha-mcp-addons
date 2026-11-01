#!/usr/bin/env bash
# Test der Apps Open WebUI und Open Terminal im CI:
#   1. Open Terminal: Schlüssel erzeugen, Health, API mit/ohne Schlüssel, Arbeitsordner
#      unter /share mit Rechten für user, kein Supervisor-Token, Neustart
#   2. Open WebUI frisch: SearXNG antwortet, Web-Suche und Terminal über Umgebung
#      eingetragen, Terminal über den Proxy von Open WebUI erreichbar
#   3. Übernahme der Datenbank in eine zweite, leere App; dabei schreibt provision.py
#      die Einträge in die bestehende Datenbank (Engine zurück auf searxng, Terminal raus)
#   bash .github/scripts/test_open_webui.sh <open-webui-image> <open-terminal-image>
set -euo pipefail
IMG=${1:?Open-WebUI-Image fehlt}
OT_IMG=${2:?Open-Terminal-Image fehlt}
W=$(mktemp -d)
NET=owui-test-net
cleanup() { docker rm -f owui-test ot-test >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null

opts() { # $1 data, $2 terminal key
  cat > "$1/options.json" <<JSON
{"webui_url":"http://localhost:8080","webui_secret_key":"","oidc_configuration_url":"","oidc_provider_name":"Test",
 "oidc_client_id":"","oidc_client_secret":"","oidc_signup":false,"oidc_merge_by_email":false,"login_form":true,
 "searxng":true,"open_terminal_api_key":"$2","open_terminal_url":"http://ot-test:8000",
 "extra_env":["ENABLE_SIGNUP=true"]}
JSON
}

wait_for() { # $1 container, $2 url, $3 Muster, $4 Versuche (5 s)
  for i in $(seq 1 "$4"); do
    if curl -fsS "$2" 2>/dev/null | grep -q "$3"; then echo "$1 gesund nach $((i * 5)) s"; return 0; fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" != "true" ]; then break; fi
    sleep 5
  done
  docker logs "$1" 2>&1 | tail -n 80
  echo "FEHLER: $1 wurde nicht gesund"; exit 1
}

start() { # $1 data, $2 config
  docker rm -f owui-test >/dev/null 2>&1 || true
  docker run -d --name owui-test --network "$NET" -p 18080:8080 -v "$1:/data" -v "$2:/config" "$IMG" >/dev/null
  wait_for owui-test http://127.0.0.1:18080/health '"status":true' 90
}

token() {
  curl -fsS -X POST http://127.0.0.1:18080/api/v1/auths/signin -H 'Content-Type: application/json' \
    -d '{"email":"test@example.org","password":"Test-1234-abcd"}' | jq -r .token
}

searxng_ok() {
  for i in $(seq 1 24); do
    if out=$(docker exec owui-test curl -fsS 'http://127.0.0.1:8888/search?q=home+assistant&format=json' 2>/dev/null) \
       && jq -e '.query == "home assistant"' <<<"$out" >/dev/null; then
      echo "SearXNG antwortet ($(jq '.results | length' <<<"$out") Treffer)"; return 0
    fi
    sleep 5
  done
  docker logs owui-test 2>&1 | grep -i searxng | tail -n 40
  echo "FEHLER: SearXNG antwortet nicht"; exit 1
}

web_engine() { # $1 token
  curl -fsS http://127.0.0.1:18080/api/v1/retrieval/config -H "Authorization: Bearer $1" | jq -r '.web.WEB_SEARCH_ENGINE + " " + (.web.ENABLE_WEB_SEARCH|tostring)'
}

echo "== 1. Open Terminal"
mkdir -p "$W/ot" "$W/share/artcraft/work"; echo '{"api_key":"","work_dir":"/share/artcraft/work"}' > "$W/ot/options.json"
# Datei einer anderen App (root, 644) vor dem Start
sudo sh -c 'echo alt > "$1/share/artcraft/work/von-root.txt"; chown root:root "$1/share/artcraft/work/von-root.txt"; chmod 644 "$1/share/artcraft/work/von-root.txt"' _ "$W"
docker run -d --name ot-test --network "$NET" -p 18000:8000 -e SUPERVISOR_TOKEN=test-token -v "$W/ot:/data" -v "$W/share:/share" "$OT_IMG" >/dev/null
wait_for ot-test http://127.0.0.1:18000/health '"ok"' 36
OT_KEY=$(sudo cat "$W/ot/api_key")
[ ${#OT_KEY} -ge 32 ] || { echo "FEHLER: kein Schlüssel erzeugt"; exit 1; }
logs=$(docker logs ot-test 2>&1); grep '^\[open-terminal-app\]' <<<"$logs" | sed "s/$OT_KEY/<schlüssel>/" || true
grep -q "$OT_KEY" <<<"$logs" || { echo "FEHLER: Schlüssel nicht im Protokoll"; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/files/cwd)
[ "$code" = "401" ] || [ "$code" = "403" ] || { echo "FEHLER: ohne Schlüssel HTTP $code"; exit 1; }
home=$(curl -fsS http://127.0.0.1:18000/files/cwd -H "Authorization: Bearer $OT_KEY" | jq -r .home)
echo "Home im Terminal: $home"
docker exec -u user ot-test sh -c 'echo hallo > ~/probe.txt'
sudo test -f "$W/ot/home/probe.txt" || { echo "FEHLER: Home liegt nicht in /data/home"; exit 1; }
# Arbeitsordner: Link, Unterordner, Rechte für user (auch für neue root-Dateien), kein Token
docker exec -u user ot-test sh -c 'test -L ~/work && test -d ~/work/inbox && test -d ~/work/out' \
  || { echo "FEHLER: ~/work, inbox/ oder out/ fehlen"; exit 1; }
docker exec -u user ot-test sh -c 'echo neu > ~/work/inbox/von-user.txt && cat ~/work/von-root.txt >/dev/null && echo x >> ~/work/von-root.txt' \
  || { echo "FEHLER: user kann im Arbeitsordner nicht schreiben"; exit 1; }
docker exec ot-test sh -c 'echo spaeter > /share/artcraft/work/out/spaeter.txt'
docker exec -u user ot-test sh -c 'echo y >> ~/work/out/spaeter.txt && rm ~/work/out/spaeter.txt' \
  || { echo "FEHLER: user kann neue root-Datei nicht ändern"; exit 1; }
sudo test -f "$W/share/artcraft/work/inbox/von-user.txt" || { echo "FEHLER: Datei nicht unter /share"; exit 1; }
grep -q "Arbeitsordner: /share/artcraft/work als ~/work" <<<"$(docker logs ot-test 2>&1)" || { echo "FEHLER: Arbeitsordner nicht im Protokoll"; exit 1; }
envs=$(docker exec ot-test sh -c 'for p in /proc/[0-9]*; do [ "$(stat -c %U "$p" 2>/dev/null)" = user ] && { echo "--- $p"; tr "\000" "\n" < "$p/environ" 2>/dev/null; }; done; true')
grep -q '^--- ' <<<"$envs" || { echo "FEHLER: kein Prozess als user gefunden"; exit 1; }
if grep -q '^SUPERVISOR_TOKEN=' <<<"$envs"; then echo "FEHLER: Terminal sieht SUPERVISOR_TOKEN"; exit 1; fi
echo "Arbeitsordner ok"
docker restart ot-test >/dev/null
wait_for ot-test http://127.0.0.1:18000/health '"ok"' 36
[ "$(sudo cat "$W/ot/api_key")" = "$OT_KEY" ] || { echo "FEHLER: Schlüssel nach Neustart anders"; exit 1; }
curl -fsS http://127.0.0.1:18000/files/cwd -H "Authorization: Bearer $OT_KEY" >/dev/null

echo "== 2. Open WebUI frisch"
mkdir -p "$W/d1" "$W/c1"; opts "$W/d1" "$OT_KEY"
start "$W/d1" "$W/c1"
logs=$(docker logs owui-test 2>&1); grep '^\[open-webui-app\]' <<<"$logs" || true
grep -q "\[open-webui-app\] Starte Open WebUI" <<<"$logs" || { echo "FEHLER: run.sh lief nicht"; exit 1; }
curl -fsS -X POST http://127.0.0.1:18080/api/v1/auths/signup -H 'Content-Type: application/json' \
  -d '{"name":"Test","email":"test@example.org","password":"Test-1234-abcd"}' >/dev/null
T=$(token)
searxng_ok
[ "$(web_engine "$T")" = "searxng true" ] || { echo "FEHLER: Web-Suche: $(web_engine "$T")"; exit 1; }
list=$(curl -fsS http://127.0.0.1:18080/api/v1/terminals/ -H "Authorization: Bearer $T")
jq -e 'map(.id) | index("ha-open-terminal")' <<<"$list" >/dev/null || { echo "FEHLER: Terminal nicht gelistet: $list"; exit 1; }
via=$(curl -fsS http://127.0.0.1:18080/api/v1/terminals/ha-open-terminal/files/cwd -H "Authorization: Bearer $T" | jq -r .home)
[ "$via" = "$home" ] || { echo "FEHLER: Terminal über Open WebUI: '$via'"; exit 1; }
echo "Terminal über Open WebUI erreichbar"
docker stop owui-test >/dev/null
test -s "$W/d1/webui.db" || { echo "FEHLER: /data/webui.db fehlt"; exit 1; }
test -s "$W/d1/.webui_secret_key" || { echo "FEHLER: Schlüssel nicht in /data"; exit 1; }

echo "== 3. Übernahme in leere App, Einträge in bestehender Datenbank"
mkdir -p "$W/d2" "$W/c2/import"; opts "$W/d2" ""
sudo cp -a "$W/d1"/webui.db* "$W/d1/.webui_secret_key" "$W/c2/import/"
# Engine in der Kopie verstellen: provision.py muss sie zurücksetzen
sudo python3 - "$W/c2/import/webui.db" <<'PY'
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("update config set value = ? where key = 'web.search.engine'", (json.dumps("duckduckgo"),))
c.commit()
print("Engine in der Kopie:", c.execute("select value from config where key = 'web.search.engine'").fetchone()[0])
PY
start "$W/d2" "$W/c2"
logs=$(docker logs owui-test 2>&1); grep '^\[open-webui-app\]' <<<"$logs" || true
grep -q "Übernahme fertig" <<<"$logs" || { echo "FEHLER: keine Übernahme"; exit 1; }
grep -q "Web-Suche: SearXNG eingetragen" <<<"$logs" || { echo "FEHLER: provision.py lief nicht"; exit 1; }
grep -q "Open Terminal ausgetragen" <<<"$logs" || { echo "FEHLER: Terminal nicht ausgetragen"; exit 1; }
sudo cmp "$W/d1/.webui_secret_key" "$W/d2/.webui_secret_key" || { echo "FEHLER: Schlüssel nicht übernommen"; exit 1; }
T=$(token)
[ -n "$T" ] && [ "$T" != "null" ] || { echo "FEHLER: Anmeldung mit übernommenem Nutzer"; exit 1; }
[ "$(web_engine "$T")" = "searxng true" ] || { echo "FEHLER: Web-Suche nach Übernahme: $(web_engine "$T")"; exit 1; }
[ "$(curl -fsS http://127.0.0.1:18080/api/v1/terminals/ -H "Authorization: Bearer $T" | jq length)" = "0" ] || { echo "FEHLER: Terminal noch eingetragen"; exit 1; }
compgen -G "$W/c2/import.erledigt-*" >/dev/null || { echo "FEHLER: Import-Ordner nicht umbenannt"; exit 1; }
echo "Alles ok"
