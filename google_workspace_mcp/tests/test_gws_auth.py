#!/usr/bin/env python3
"""Test der Anmeldung (gws_auth.py) gegen einen nachgebauten Google-Token-Endpunkt.

  <venv>/bin/python tests/test_gws_auth.py <pfad/zu/gws_auth.py>

Braucht die Pakete von workspace-mcp (für die Scopes), aber kein Netz.
"""
import base64, hashlib, json, os, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKRIPT = sys.argv[1]
EMAIL = "info@hannesbraeu.example"
ok = 0
LETZTE = {}


def check(c, was):
    global ok
    if not c:
        raise AssertionError(was)
    ok += 1
    print("ok   ", was)


class Token(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        q = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        LETZTE.clear(); LETZTE.update({k: v[0] for k, v in q.items()})
        if q["code"][0] == "falsch":
            body, code = {"error": "invalid_grant", "error_description": "Bad Request"}, 400
        else:
            nutz = base64.urlsafe_b64encode(json.dumps({"email": EMAIL}).encode()).decode().rstrip("=")
            body, code = {"access_token": "AT", "refresh_token": "RT", "expires_in": 3599, "id_token": f"x.{nutz}.y",
                          "scope": "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile "
                                   "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar "
                                   "https://www.googleapis.com/auth/drive"}, 200
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Token)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp())
env = {**os.environ, "WORKSPACE_MCP_PERMISSIONS": "gmail:readonly calendar:full drive:full",
       "WORKSPACE_MCP_CREDENTIALS_DIR": str(tmp / "creds"), "USER_GOOGLE_EMAIL": EMAIL,
       "GOOGLE_OAUTH_CLIENT_ID": "cid", "GOOGLE_OAUTH_CLIENT_SECRET": "geheim",
       "GWS_TOKEN_URL": f"http://127.0.0.1:{srv.server_port}/token"}


def lauf(antwort=""):
    p = subprocess.run([sys.executable, SKRIPT], env={**env, "GWS_AUTH_RESPONSE": antwort}, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


rc, out = lauf()
link = next(z for z in out.splitlines() if z.startswith("https://accounts.google.com/"))
q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
check(rc == 2 and q["access_type"] == ["offline"] and q["code_challenge_method"] == ["S256"], "ohne Anmeldung: Link mit PKCE, offline")
check("geheim" not in out, "Client-Secret steht nicht im Log")
state = q["state"][0]

rc, out = lauf(f"http://localhost/?state=anders&code=abc")
check(rc == 2 and "passt nicht" in out, "falscher state abgewiesen")
neu_state = urllib.parse.parse_qs(urllib.parse.urlparse(next(z for z in out.splitlines() if z.startswith("https://"))).query)["state"][0]

rc, out = lauf(f"http://localhost/?state={neu_state}&code=falsch")
check(rc == 2 and "lehnt den Code ab" in out, "abgelehnter Code: Meldung, neuer Link")
neu_state = urllib.parse.parse_qs(urllib.parse.urlparse(next(z for z in out.splitlines() if z.startswith("https://"))).query)["state"][0]
verifier = json.loads((tmp / "anmeldung_offen.json").read_text())["verifier"]

rc, out = lauf(f"http://localhost/?state={neu_state}&code=gut&scope=x")
check(rc == 0 and "gespeichert" in out, "gültige Antwort: Anmeldung gespeichert")
check(LETZTE.get("code_verifier") == verifier and LETZTE.get("redirect_uri") == "http://localhost", "Tausch mit Verifier und Rücksprung")
creds = json.loads((tmp / "creds" / f"{EMAIL}.json").read_text())
check(creds["refresh_token"] == "RT" and creds["client_id"] == "cid" and "https://www.googleapis.com/auth/drive" in creds["scopes"], "Format wie workspace-mcp")
check(oct((tmp / "creds" / f"{EMAIL}.json").stat().st_mode & 0o777) == "0o600", "Datei nur für den Besitzer lesbar")
check("AT" not in out.replace("AUTH", "") and "RT" not in out, "Tokens stehen nicht im Log")

rc, out = lauf(f"http://localhost/?state={neu_state}&code=gut")
check(rc == 0 and "Rechte passen" in out, "Neustart mit alter Antwort: nichts zu tun")

env["WORKSPACE_MCP_PERMISSIONS"] = "gmail:drafts calendar:full drive:full"
rc, out = lauf()
check(rc == 2 and "geändert" in out, "mehr Rechte: neue Zustimmung")
print(f"\n{ok} Prüfungen bestanden")
srv.shutdown()
