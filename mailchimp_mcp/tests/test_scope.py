#!/usr/bin/env python3
"""Prüft die Umfänge von Mailchimp MCP im gebauten Image (ohne Netz zu Mailchimp).

  docker run --rm -v "$PWD/mailchimp_mcp/tests:/t:ro" test:mailchimp_mcp /opt/venv/bin/python3 /t/test_scope.py

Je Umfang wird service_setup aus services.sh mit nachgebauten Optionen ausgeführt, dann der
Server per stdio gestartet: Anzahl Werkzeuge, Schreibsperre bei "lesen", Probelauf bei
"entwuerfe" (create_campaign ruft dann Mailchimp nicht auf).
"""
import json, os, subprocess

SERVICES = os.environ.get("MC_SERVICES", "/usr/local/lib/mcp/services.sh")
SERVER = os.environ.get("MC_SERVER", "/opt/venv/bin/python3 /usr/local/lib/mcp/mailchimp_plus.py").split()
ok = 0


def check(cond, was):
    global ok
    if not cond:
        raise AssertionError(was)
    ok += 1
    print("ok   ", was)


def env_fuer(opts: dict) -> dict:
    """service_setup mit opt() aus opts ausführen und die exportierte Umgebung zurückgeben."""
    skript = ('opt() { python3 -c "import json,sys; v=json.loads(sys.argv[1]).get(sys.argv[2],\'\'); '
              'print(str(v).lower() if isinstance(v,bool) else v)" "$OPTS_JSON" "$1"; }; '
              'log() { echo "$*" >&2; }; fehler() { echo "$*" >&2; exit 1; }; '
              f'source {SERVICES}; service_setup; env -0')
    out = subprocess.run(["bash", "-c", skript], env={**os.environ, "OPTS_JSON": json.dumps(opts)},
                         capture_output=True, check=True).stdout
    return dict(x.split("=", 1) for x in out.decode().split("\0") if "=" in x)


def sitzung(env, *anfragen):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i + 2, **a} for i, a in enumerate(anfragen)]
    p = subprocess.Popen(SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         env=env, text=True)
    p.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
    p.stdin.flush()
    antworten, offen = {}, {1} | {i + 2 for i in range(len(anfragen))}
    while offen:
        zeile = p.stdout.readline()
        if not zeile:
            break
        try:
            m = json.loads(zeile)
        except ValueError:
            continue
        if "id" in m:
            antworten[m["id"]] = m
            offen.discard(m["id"])
    p.stdin.close()
    p.wait(timeout=30)
    return antworten


LISTE = {"method": "tools/list"}

# Ohne Schlüssel: kein Netzaufruf in service_setup.
e = env_fuer({"api_key": "", "scope": "lesen", "extra_tools": "", "dry_run": False})
a = sitzung(e, LISTE, {"method": "tools/call", "params": {"name": "create_campaign", "arguments": {
    "list_id": "x", "subject_line": "y"}}})
namen = {t["name"] for t in a[2]["result"]["tools"]}
check(len(namen) == 21 and "find_in_campaign_content" in namen and "create_campaign" not in namen
      and "replace_in_campaign_content" not in namen, f"lesen: 21 Werkzeuge ({len(namen)})")
check(e["MAILCHIMP_READ_ONLY"] == "true", "lesen: Schreiben gesperrt")
check("error" in a[3] or a[3].get("result", {}).get("isError"), "lesen: create_campaign nicht aufrufbar")

e = env_fuer({"api_key": "", "scope": "entwuerfe", "extra_tools": "tag_member", "dry_run": True})
a = sitzung(e, LISTE, {"method": "tools/call", "params": {"name": "create_campaign", "arguments": {
    "list_id": "abc", "subject_line": "Bockbier-Anstich"}}})
namen = {t["name"] for t in a[2]["result"]["tools"]}
check(len(namen) == 29 and {"create_campaign", "send_test_email", "tag_member", "replace_in_campaign_content",
                             "upload_file_from_share"} <= namen
      and "send_campaign" not in namen and "delete_member" not in namen, f"entwuerfe + tag_member: 29 Werkzeuge ({len(namen)})")
text = a[3]["result"]["content"][0]["text"]
check('"dry_run": true' in text and "Bockbier-Anstich" in text, "Probelauf: create_campaign ohne Aufruf")

e = env_fuer({"api_key": "", "scope": "alle", "extra_tools": "", "dry_run": False})
a = sitzung(e, LISTE)
namen = {t["name"] for t in a[2]["result"]["tools"]}
check(len(namen) > 200 and "send_campaign" in namen, f"alle: {len(namen)} Werkzeuge")

# Ersetzen ohne Netz: reine Funktion aus mailchimp_plus
import sys
sys.path.insert(0, os.environ.get("MC_LIB", "/usr/local/lib/mcp"))
os.environ.update(MAILCHIMP_API_KEY="x-us1", MAILCHIMP_READ_ONLY="false")
import mailchimp_plus as mp
html = '<p>18.09. Live - Rico Bravo</p><img src="https://x/alt.jpg"><p>18.09.</p>'
neu, prot = mp.ersetzen(html, [{"old": "18.09. Live - Rico Bravo", "new": "27.11. Live - Danny Wuenschel"},
                               {"old": "https://x/alt.jpg", "new": "https://x/neu.jpg"}])
check("Danny Wuenschel" in neu and "neu.jpg" in neu and neu.count("18.09.") == 1, "ersetzen: eindeutige Treffer")
try:
    mp.ersetzen(html, [{"old": "<p>", "new": "<div>"}, {"old": "fehlt", "new": "x"}])
    check(False, "ersetzen: mehrdeutig/fehlend muss scheitern")
except ValueError as e:
    check("2 Treffer" in str(e) and "nicht gefunden" in str(e), "ersetzen: alles oder nichts mit allen Problemen")
check(mp.ersetzen(html, [{"old": "<p>", "new": "<div>", "all": True}])[0].count("<div>") == 2, "ersetzen: all=true")
check(len(mp.fundstellen(html, "18.09.", 5)) == 2, "fundstellen: zwei Treffer")
link = '<a href="https://calendar.google.com/calendar/event?action=TEMPLATE&tmeid=NmRqM2VvcHBjcGo2MmJi%3D&tmsrc=x">'
neu, _ = mp.ersetzen(link, [{"old": r"tmeid=[A-Za-z0-9%=_-]+", "new": "tmeid=NEU", "regex": True}])
check("tmeid=NEU&tmsrc=x" in neu, "ersetzen: regex für lange IDs")
try:
    mp.ersetzen(html, [{"old": r"\d\d\.\d\d\.", "new": "x", "regex": True}])
    check(False, "regex mehrdeutig muss scheitern")
except ValueError as e:
    check("2 Treffer" in str(e) and "18.09." in str(e), "ersetzen: regex mehrdeutig mit Beispielen")
check(mp.pruefen("<p>alt</p>", [{"old": "a", "new": "neu"}]) == [{"nr": 1, "new": "neu"}], "pruefen: fehlendes new erkannt")
mp.SHARE = __import__("pathlib").Path("/tmp")
check("Nur Dateien unter" in mp.upload_file_from_share("/etc/passwd"), "upload: nur unter /share")

print(f"\n{ok} Prüfungen bestanden")
