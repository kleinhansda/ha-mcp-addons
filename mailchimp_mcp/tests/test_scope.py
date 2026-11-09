#!/usr/bin/env python3
"""Prüft die Umfänge von Mailchimp MCP im gebauten Image (ohne Netz zu Mailchimp).

  docker run --rm -v "$PWD/mailchimp_mcp/tests:/t:ro" test:mailchimp_mcp python3 /t/test_scope.py

Je Umfang wird service_setup aus services.sh mit nachgebauten Optionen ausgeführt, dann der
Server per stdio gestartet: Anzahl Werkzeuge, Schreibsperre bei "lesen", Probelauf bei
"entwuerfe" (create_campaign ruft dann Mailchimp nicht auf).
"""
import json, os, subprocess

SERVICES = os.environ.get("MC_SERVICES", "/usr/local/lib/mcp/services.sh")
SERVER = os.environ.get("MC_SERVER", "/opt/venv/bin/mailchimp-mcp")
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
    p = subprocess.Popen([SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
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
check(len(namen) == 20 and "list_campaigns" in namen and "create_campaign" not in namen, f"lesen: 20 Werkzeuge ({len(namen)})")
check(e["MAILCHIMP_READ_ONLY"] == "true", "lesen: Schreiben gesperrt")
check("error" in a[3] or a[3].get("result", {}).get("isError"), "lesen: create_campaign nicht aufrufbar")

e = env_fuer({"api_key": "", "scope": "entwuerfe", "extra_tools": "tag_member", "dry_run": True})
a = sitzung(e, LISTE, {"method": "tools/call", "params": {"name": "create_campaign", "arguments": {
    "list_id": "abc", "subject_line": "Bockbier-Anstich"}}})
namen = {t["name"] for t in a[2]["result"]["tools"]}
check(len(namen) == 26 and {"create_campaign", "send_test_email", "tag_member"} <= namen
      and "send_campaign" not in namen and "delete_member" not in namen, f"entwuerfe + tag_member: 26 Werkzeuge ({len(namen)})")
text = a[3]["result"]["content"][0]["text"]
check('"dry_run": true' in text and "Bockbier-Anstich" in text, "Probelauf: create_campaign ohne Aufruf")

e = env_fuer({"api_key": "", "scope": "alle", "extra_tools": "", "dry_run": False})
a = sitzung(e, LISTE)
namen = {t["name"] for t in a[2]["result"]["tools"]}
check(len(namen) > 200 and "send_campaign" in namen, f"alle: {len(namen)} Werkzeuge")

print(f"\n{ok} Prüfungen bestanden")
