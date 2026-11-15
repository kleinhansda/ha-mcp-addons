#!/usr/bin/env bash
# Test der App Dawarich: echter Start mit eingebautem PostgreSQL, Redis und nginx.
#
#  1. Start mit eingeschaltetem, aber nicht erreichbarem Geocoder (darf den Start nicht verhindern)
#  2. Grunddaten: Länder eingespielt, Admin-Konto mit API-Schlüssel
#  3. Punkt über die OwnTracks-API anlegen
#  4. Ingress: Karte über nginx mit Präfix, alle Skripte/Styles/Importmap-Einträge erreichbar
#  5. Sicherung (backup_pre.sh) und Umzug in eine frische App über /share/dawarich_umzug.tar.gz
#  6. Neustart auf denselben Daten ohne erneutes Einspielen
#
# Aufruf: test_dawarich.sh <image>
set -euo pipefail

IMG=${1:?Image fehlt}
W=$(mktemp -d)
PREFIX=/api/hassio_ingress/citest
FEHLER=0
soll() { if eval "$1"; then echo "ok    $2"; else echo "FEHLER $2"; FEHLER=1; fi; }

optionen() {
  mkdir -p "$1"
  cat > "$1/options.json" <<'EOF'
{"admin_email":"ci@example.org","admin_password":"ci-passwort-123456","time_zone":"Europe/Berlin",
 "application_hosts":"localhost,127.0.0.1","external_url":"","background_processing_concurrency":2,
 "reverse_geocoding":true,"photon_api_host":"http://127.0.0.1:9","photon_language":"de",
 "ha_tracked_entities":"","ha_min_distance":10,"smtp_server":"","smtp_port":587,"smtp_from":"",
 "smtp_username":"","smtp_authentication":"plain","smtp_starttls":true,"database_password":"dawarich"}
EOF
}

starten() {   # $1 Name, $2 Datenordner
  docker run -d --name "$1" -p 3000:3000 -p 8099:8099 -p 8100:8100 \
    -v "$2":/data -v "$W/share":/share "$IMG" >/dev/null
  for i in $(seq 1 450); do
    if curl -fsS -m 5 http://127.0.0.1:3000/api/v1/health 2>/dev/null | grep -q '"ok"'; then
      echo "Dawarich antwortet nach $((i * 2)) s"; return 0
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" != true ]; then break; fi
    sleep 2
  done
  docker logs "$1" 2>&1 | tail -150
  echo "FEHLER: Dawarich startet nicht"; exit 1
}

rails() { docker exec "$1" /command/with-contenv dawarich-rails runner "$2" 2>/dev/null | tail -n 1; }

mkdir -p "$W/share"
optionen "$W/d1"

echo "::group::Erster Start"
starten dw "$W/d1"
docker logs dw > "$W/log1.txt" 2>&1
echo "::endgroup::"
soll 'grep -q "Testabfrage fehlgeschlagen" "$W/log1.txt"' "Start trotz nicht erreichbarem Photon (nur Warnung)"
soll '! grep -q "unable to start service" "$W/log1.txt"' "Alle Dienste gestartet"
LAENDER=$(rails dw 'puts Country.count')
soll '[ "${LAENDER:-0}" -gt 200 ]' "Länder eingespielt ($LAENDER)"
soll 'grep -q "Länder in der Datenbank" "$W/log1.txt"' "db:seed beim Start gelaufen"
soll '[ "$(rails dw "puts User.pluck(:email).sort.join(%q(,))")" = ci@example.org ]' "Nur das eigene Admin-Konto, kein Demo-Konto"
KEY=$(docker exec dw cat /data/dawarich/api_key)
soll '[ -n "$KEY" ]' "API-Schlüssel des Admins in /data/dawarich/api_key"

# Punkt über OwnTracks
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"_type\":\"location\",\"lat\":50.1109,\"lon\":8.6821,\"tst\":$(date +%s),\"tid\":\"ci\",\"acc\":5}" \
  "http://127.0.0.1:3000/api/v1/owntracks/points?api_key=$KEY")
soll '[ "$code" = 200 ]' "OwnTracks-Punkt angenommen (HTTP $code)"
for i in $(seq 1 30); do
  PUNKTE=$(rails dw 'puts Point.count'); [ "${PUNKTE:-0}" -ge 1 ] && break; sleep 2
done
soll '[ "${PUNKTE:-0}" -ge 1 ]' "Punkt gespeichert ($PUNKTE)"

# Ingress: zweite nginx-Instanz mit Präfix, wie sie init-dawarich.sh für Home Assistant erzeugt
docker exec dw sh -c "sed -e 's|INGRESS_PATH|$PREFIX|g' -e 's|listen 8099|listen 8100|' -e 's|^pid .*|pid /tmp/nginx-ci.pid;|' \
  /etc/nginx/nginx.conf.template > /tmp/nginx-ci.conf"
docker exec -d dw nginx -c /tmp/nginx-ci.conf
sleep 2
echo "::group::Ingress"
if python3 - "$PREFIX" <<'PY'
import http.cookiejar, json, re, sys, urllib.parse, urllib.request

prefix = sys.argv[1]
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
direkt, ingress = "http://127.0.0.1:3000", "http://127.0.0.1:8100"

html = op.open(direkt + "/users/sign_in").read().decode()
token = re.search(r'name="authenticity_token" value="([^"]+)"', html).group(1)
daten = urllib.parse.urlencode({"authenticity_token": token, "user[email]": "ci@example.org",
                                "user[password]": "ci-passwort-123456", "user[remember_me]": "0"}).encode()
op.open(direkt + "/users/sign_in", daten).read()

fehler = 0
r = op.open(ingress + "/map")
seite = r.read().decode()
if "sign_in" in r.geturl() or "maplibre" not in seite.lower():
    print("FEHLER Karte nicht geladen:", r.geturl()); sys.exit(1)
# Absolute Pfade ohne Präfix in Attributen = Ingress kaputt
roh = re.findall(r'(?:src|href)="(/(?!/)[^"]*)"', seite)
ohne = [u for u in roh if not u.startswith(prefix + "/")]
if ohne:
    print("FEHLER Pfade ohne Ingress-Präfix:", ohne[:10]); fehler = 1
# Skripte, Styles, Importmap-Einträge, MapLibre
urls = set(u for u in roh if re.search(r"\.(js|css|mjs)(\?|$)|/assets/|/maplibre/", u))
for m in re.finditer(r'<script type="importmap"[^>]*>(.*?)</script>', seite, re.S):
    urls.update(v for v in json.loads(m.group(1)).get("imports", {}).values() if v.startswith(prefix + "/"))
if len(urls) < 3:
    print("FEHLER zu wenige Assets gefunden:", urls); fehler = 1
for u in sorted(urls):
    pfad = u[len(prefix):]   # Supervisor entfernt das Präfix, bevor die Anfrage nginx erreicht
    try:
        r = op.open(ingress + pfad); r.read(); code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    if code != 200:
        print(f"FEHLER {code} {pfad}"); fehler = 1
print(f"Ingress: {len(urls)} Assets der Karte geprüft")
sys.exit(fehler)
PY
then echo "ok    Ingress: Karte und Assets über Präfix erreichbar"; else echo "FEHLER Ingress"; FEHLER=1; fi
echo "::endgroup::"

# Sicherung und Umzug
docker exec dw /usr/share/dawarich/backup_pre.sh
docker exec dw sh -c 'tar -C /data -czf /share/dawarich_umzug.tar.gz dawarich'
docker exec dw /usr/share/dawarich/backup_post.sh
SECRET1=$(docker exec dw cat /data/dawarich/secret_key_base)
docker stop -t 90 dw >/dev/null
docker logs dw > "$W/log1.txt" 2>&1
docker rm dw >/dev/null

optionen "$W/d2"
echo "::group::Umzug in frische App"
starten dw2 "$W/d2"
docker logs dw2 > "$W/log2.txt" 2>&1
echo "::endgroup::"
soll 'grep -q "Umzug: Schlüssel und Dateien übernommen" "$W/log2.txt"' "Umzug-Archiv erkannt"
soll 'grep -q "Database restored" "$W/log2.txt"' "Datenbank eingespielt"
soll '[ "$(docker exec dw2 cat /data/dawarich/secret_key_base)" = "$SECRET1" ]' "secret_key_base übernommen"
soll '[ "$(docker exec dw2 cat /data/dawarich/api_key)" = "$KEY" ]' "API-Schlüssel unverändert"
soll '[ "$(rails dw2 "puts Point.count")" = "$PUNKTE" ]' "Punkte übernommen"
soll '[ -f "$W/share/dawarich_umzug.tar.gz.importiert" ] && [ ! -f "$W/share/dawarich_umzug.tar.gz" ]' "Archiv als importiert markiert"

echo "::group::Neustart"
docker restart -t 90 dw2 >/dev/null
for i in $(seq 1 300); do
  curl -fsS -m 5 http://127.0.0.1:3000/api/v1/health 2>/dev/null | grep -q '"ok"' && break; sleep 2
done
docker logs dw2 > "$W/log3.txt" 2>&1
echo "::endgroup::"
soll 'curl -fsS -m 5 http://127.0.0.1:3000/api/v1/health | grep -q "\"ok\""' "Neustart auf denselben Daten"
soll '[ "$(grep -c "Database restored" "$W/log3.txt")" = 1 ]' "Kein zweites Einspielen"
soll '[ "$(rails dw2 "puts Point.count")" = "$PUNKTE" ]' "Punkte nach Neustart vorhanden"

if [ "$FEHLER" != 0 ]; then
  echo "::group::Protokoll"; docker logs dw2 2>&1 | tail -200; echo "::endgroup::"
fi
docker rm -f dw2 >/dev/null 2>&1 || true
exit "$FEHLER"
