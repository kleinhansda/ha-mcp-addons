#!/usr/bin/env bash
# Test des Mehrbenutzer-Modus der App Open Terminal:
#   Administrator (aus admin_users) liest /share und schreibt in beschreibbare Ordner,
#   Familienkonto sieht von /share nur den Familienordner, hat ein eigenes Home, kein sudo,
#   kommt nicht ins Home des anderen; nach einem Neustart behalten die Konten ihre UID.
#   WebDAV-Zugang (rclone) nur für den Administrator, weder für die Familie noch über die
#   Datei-API (liest als "user") lesbar, ebenso options.json.
#   bash .github/scripts/test_open_terminal_multi.sh <open-terminal-image>
set -euo pipefail
IMG=${1:?Image fehlt}
W=$(mktemp -d)
KEY=testschluessel-1234
ADMIN=0928ab8c-3c96-4e3c-a2ef-ba1859ed330e
FAM=f00dbabe-1111-2222-3333-444455556666
WDPW=sehr-geheimes-webdav-pw
cleanup() { docker rm -f ot-multi >/dev/null 2>&1 || true; sudo rm -rf "$W" 2>/dev/null || true; }
trap cleanup EXIT
mkdir -p "$W/data" "$W/share/geheim" "$W/share/hannesbraeu"
echo vertraulich > "$W/share/geheim/notiz.txt"
cat > "$W/data/options.json" <<JSON
{"api_key":"$KEY","work_dir":"/share","writable_dirs":["hannesbraeu"],"python_bundles":[],"python_packages":[],
 "update_packages":false,"r_packages":[],"multi_user":true,"admin_users":["$ADMIN"],"family_dir":"familie",
 "webdav":{"name":"wolke","url":"https://dav.example.invalid/remote.php/dav/files/david/","user":"david",
           "password":"$WDPW","vendor":"nextcloud"}}
JSON

start() {
  docker rm -f ot-multi >/dev/null 2>&1 || true
  docker run -d --name ot-multi -p 18001:8000 -v "$W/data:/data" -v "$W/share:/share" "$IMG" >/dev/null
  for i in $(seq 1 40); do
    curl -fsS http://127.0.0.1:18001/health >/dev/null 2>&1 && { echo "gesund nach $((i * 3)) s"; return 0; }
    sleep 3
  done
  docker logs ot-multi 2>&1 | tail -n 60; echo "FEHLER: nicht gesund"; exit 1
}

als() { # $1 Nutzer-ID, $2 Befehl → Ausgabe; Rückgabe = Exit-Code des Befehls
  local r
  r=$(curl -fsS -X POST "http://127.0.0.1:18001/execute?wait=30" -H "Authorization: Bearer $KEY" \
      -H "X-User-Id: $1" -H 'Content-Type: application/json' -d "$(jq -n --arg c "$2" '{command:$c}')")
  jq -r '[.output[]?.data] | join("")' <<<"$r" | tr -d '\r'
  return "$(jq -r '.exit_code // 99' <<<"$r")"
}
datei() { # $1 Nutzer-ID, $2 Pfad → HTTP-Status der Datei-API (Open Terminal liest als "user")
  curl -s -o /dev/null -w '%{http_code}' -G "http://127.0.0.1:18001/files/read" --data-urlencode "path=$2" \
    -H "Authorization: Bearer $KEY" -H "X-User-Id: $1"
}
ok() { echo "ok    $1"; }
fail() { echo "FEHLER: $1"; docker logs ot-multi 2>&1 | tail -n 40; exit 1; }

start
docker logs ot-multi 2>&1 | grep "Mehrbenutzer: an" >/dev/null || fail "Mehrbenutzer nicht eingeschaltet"

out=$(als "$ADMIN" 'whoami; cat /share/geheim/notiz.txt; echo x > /share/hannesbraeu/admin.txt && echo geschrieben; pwd') \
  || fail "Administrator: Befehl fehlgeschlagen: $out"
grep -q '^u0928ab8c$' <<<"$out" && grep -q vertraulich <<<"$out" && grep -q geschrieben <<<"$out" \
  && grep -q '^/data/home$' <<<"$out" && ok "Administrator: eigenes Konto, liest /share, schreibt in hannesbraeu, Home /data/home" \
  || fail "Administrator: $out"

out=$(als "$FAM" 'whoami; pwd') || fail "Familie: $out"
FAMK=$(head -n1 <<<"$out"); FAMH=$(sed -n 2p <<<"$out")
[ "$FAMK" = f00dbabe ] && [ "$FAMH" = /home/f00dbabe ] && ok "Familie: eigenes Konto und Home" || fail "Familie: $out"
sleep 5   # Wächter richtet das neue Konto ein

als "$FAM" 'cat /share/geheim/notiz.txt' >/dev/null 2>&1 && fail "Familie liest /share/geheim"
als "$FAM" 'ls /share' >/dev/null 2>&1 && fail "Familie listet /share"
ok "Familie: /share gesperrt"
out=$(als "$FAM" 'echo hallo > /share/familie/von-fam.txt && cat /share/familie/von-fam.txt && ls ~/familie/') \
  || fail "Familienordner: $out"
grep -q hallo <<<"$out" && ok "Familie: Familienordner les- und schreibbar, als ~/familie" || fail "Familienordner: $out"
als "$ADMIN" 'cat /share/familie/von-fam.txt' | grep hallo >/dev/null && ok "Administrator liest Familienordner" \
  || fail "Administrator liest Familienordner nicht"
als "$FAM" 'sudo -n true' >/dev/null 2>&1 && fail "Familie hat sudo"
ok "Familie: kein sudo"
als "$FAM" 'ls /data/home/ 2>&1; cat /data/options.json' >/dev/null 2>&1 && fail "Familie liest Home des Administrators oder options.json"
ok "Familie: kein Zugriff auf /data/home und options.json"
als "$FAM" 'echo geheim > ~/privat.txt' >/dev/null || fail "Familie schreibt nicht ins eigene Home"
als "$ADMIN" 'cat /home/f00dbabe/privat.txt' >/dev/null 2>&1 && fail "Administrator-Konto liest Home der Familie (über Shell)"
ok "Homes gegenseitig geschützt (Shell)"

# WebDAV
docker logs ot-multi 2>&1 | grep "WebDAV: Ziel wolke: (https://dav.example.invalid)" >/dev/null || fail "WebDAV nicht eingerichtet"
docker logs ot-multi 2>&1 | grep "$WDPW" >/dev/null && fail "WebDAV-Passwort im Protokoll"
out=$(als "$ADMIN" 'rclone listremotes; rclone config show wolke; rclone reveal "$(sed -n "s/^pass = //p" ~/.config/rclone/rclone.conf)"') \
  || fail "Administrator: rclone: $out"
grep -q '^wolke:$' <<<"$out" && grep -q 'vendor = nextcloud' <<<"$out" && grep -q "^$WDPW$" <<<"$out" \
  && ok "WebDAV: Administrator hat das Ziel wolke: mit Passwort" || fail "WebDAV Administrator: $out"
out=$(als "$FAM" 'rclone listremotes; cat /data/webdav/rclone.conf' 2>&1) && fail "Familie liest WebDAV-Zugang: $out"
grep -q wolke <<<"$out" && fail "Familie sieht das WebDAV-Ziel: $out"
ok "WebDAV: Familie sieht das Ziel nicht"
for p in /data/webdav/rclone.conf /data/home/.config/rclone/rclone.conf /data/options.json; do
  for u in "$FAM" "$ADMIN"; do
    c=$(datei "$u" "$p"); [ "$c" = 200 ] && fail "Datei-API liefert $p an $u"
  done
done
ok "Datei-API: WebDAV-Zugang und options.json für niemanden lesbar (Status $c)"

uid1=$(docker exec ot-multi id -u f00dbabe)
start
sleep 2
out=$(als "$FAM" 'id -u; cat ~/privat.txt') || fail "nach Neustart: $out"
[ "$(head -n1 <<<"$out")" = "$uid1" ] && grep -q geheim <<<"$out" \
  && ok "Neustart: gleiche UID ($uid1), Home erhalten" || fail "Neustart: $out (vorher UID $uid1)"
als "$FAM" 'cat /share/geheim/notiz.txt' >/dev/null 2>&1 && fail "nach Neustart: Familie liest /share/geheim"
ok "Neustart: /share bleibt gesperrt"
als "$ADMIN" 'rclone listremotes' | grep -q '^wolke:$' && ok "Neustart: WebDAV-Ziel bleibt" || fail "Neustart: WebDAV fehlt"

# WebDAV ohne Mehrbenutzer: wird nicht eingerichtet, alter Zugang entfernt
sudo jq ".multi_user=false" "$W/data/options.json" > "$W/o.json" && sudo cp "$W/o.json" "$W/data/options.json"
start
docker logs ot-multi 2>&1 | grep "WARNUNG: WebDAV nicht eingerichtet" >/dev/null || fail "keine Warnung ohne Mehrbenutzer"
docker exec ot-multi test -e /data/webdav && fail "WebDAV-Zugang ohne Mehrbenutzer nicht entfernt"
ok "WebDAV: ohne Mehrbenutzer entfernt, mit Warnung"
echo "Mehrbenutzer-Test bestanden"
