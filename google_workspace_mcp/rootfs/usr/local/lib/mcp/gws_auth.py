#!/usr/bin/env python3
"""Einmalige Google-Anmeldung für Google Workspace MCP ohne Rückruf-Server.

workspace-mcp meldet sich normalerweise über einen Rückruf auf http://localhost:8000 an. Das
geht vom Handy oder von einem anderen Rechner aus nicht. Dieses Skript macht die Anmeldung in
zwei Schritten über die App-Optionen:

  1. Start ohne gültige Anmeldung: Es erzeugt einen Anmelde-Link (OAuth mit PKCE, Desktop-Client,
     Rücksprung http://localhost) und schreibt ihn ins Log.
  2. Nach der Zustimmung zeigt der Browser eine nicht erreichbare Seite http://localhost/?...code=...
     Diese Adresse in die Option auth_response kopieren und die App neu starten. Das Skript tauscht
     den Code gegen Tokens und legt sie im Format von workspace-mcp ab (<email>.json).

Aufruf: python gws_auth.py   (liest alles aus der Umgebung, siehe services.sh)
Rückgabe 0 = Anmeldung gültig, 2 = Anmeldung nötig (Link im Log). Gibt nie Tokens aus.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = os.environ.get("GWS_TOKEN_URL", "https://oauth2.googleapis.com/token")  # für Tests überschreibbar
REDIRECT = "http://localhost"


def log(msg: str) -> None:
    print(f"[auth] {msg}", flush=True)


def benoetigte_scopes() -> list[str]:
    """Scopes so, wie workspace-mcp sie für WORKSPACE_MCP_PERMISSIONS verlangt."""
    from auth.permissions import get_all_permission_scopes, parse_permissions_arg, set_permissions
    from auth.scopes import BASE_SCOPES
    perms = parse_permissions_arg(os.environ["WORKSPACE_MCP_PERMISSIONS"].split())
    set_permissions(perms)
    return sorted(set(BASE_SCOPES) | set(get_all_permission_scopes()))


def deckt(vorhanden: set[str], noetig: list[str]) -> bool:
    """Wie workspace-mcp prüfen: breite Rechte (z. B. drive) decken engere (drive.readonly) ab."""
    from auth.scopes import has_required_scopes
    return bool(has_required_scopes(list(vorhanden), list(noetig)))


def dateiname(email: str) -> str:
    return urllib.parse.quote(email, safe="@._-") + ".json"


def gespeicherte_scopes(pfad: Path) -> set[str] | None:
    try:
        daten = json.loads(pfad.read_text())
    except (OSError, ValueError):
        return None
    if not daten.get("refresh_token"):
        return None
    return set(daten.get("scopes") or [])


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def link_erzeugen(scopes: list[str], email: str, offen: Path) -> None:
    verifier = b64url(secrets.token_bytes(48))
    state = b64url(secrets.token_bytes(18))
    offen.write_text(json.dumps({"state": state, "verifier": verifier, "scopes": scopes,
                                 "erstellt": dt.datetime.now(dt.timezone.utc).isoformat()}))
    offen.chmod(0o600)
    q = {"client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"], "redirect_uri": REDIRECT, "response_type": "code",
         "scope": " ".join(scopes), "access_type": "offline", "prompt": "consent", "state": state,
         "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
         "login_hint": email, "include_granted_scopes": "true"}
    log("Anmeldung bei Google nötig. Diesen Link im Browser öffnen, mit " + email + " anmelden und zustimmen:")
    print(AUTH_URL + "?" + urllib.parse.urlencode(q), flush=True)
    log("Danach zeigt der Browser eine nicht erreichbare Seite http://localhost/?state=…&code=…")
    log("Diese komplette Adresse in die Option „Anmelde-Antwort“ kopieren und die App neu starten.")


def tauschen(antwort: str, offen: Path, ziel_dir: Path, email: str) -> bool:
    try:
        pending = json.loads(offen.read_text())
    except (OSError, ValueError):
        log("Anmelde-Antwort eingetragen, aber kein offener Anmeldevorgang. Antwort leeren, App neu starten, neuen Link nutzen.")
        return False
    q = urllib.parse.parse_qs(urllib.parse.urlparse(antwort.strip()).query)
    if "error" in q:
        log(f"Google meldet: {q['error'][0]}. Anmeldung neu starten.")
        offen.unlink(missing_ok=True)
        return False
    if q.get("state", [""])[0] != pending["state"] or not q.get("code"):
        log("Anmelde-Antwort passt nicht zum aktuellen Link (alter Link oder unvollständig kopiert).")
        return False
    daten = urllib.parse.urlencode({"code": q["code"][0], "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
                                    "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
                                    "redirect_uri": REDIRECT, "grant_type": "authorization_code",
                                    "code_verifier": pending["verifier"]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=daten), timeout=20) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            fehler = json.load(e).get("error_description") or str(e.code)
        except ValueError:
            fehler = str(e.code)
        log(f"Google lehnt den Code ab: {fehler}. Codes gelten nur wenige Minuten und einmal; neuen Link nutzen.")
        offen.unlink(missing_ok=True)
        return False
    if not tok.get("refresh_token"):
        log("Google hat kein Refresh-Token geliefert. Unter myaccount.google.com/permissions den Zugriff entfernen und neu anmelden.")
        return False
    tatsaechlich = email
    try:
        nutz = tok["id_token"].split(".")[1]
        tatsaechlich = json.loads(base64.urlsafe_b64decode(nutz + "=" * (-len(nutz) % 4))).get("email") or email
    except (KeyError, IndexError, ValueError):
        pass
    if tatsaechlich.lower() != email.lower():
        log(f"Angemeldet als {tatsaechlich}, eingetragen ist {email}. Option „Google-Konto“ anpassen.")
        return False
    ablauf = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(seconds=int(tok.get("expires_in", 3600)))
    creds = {"token": tok["access_token"], "refresh_token": tok["refresh_token"], "token_uri": "https://oauth2.googleapis.com/token",
             "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"], "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
             "scopes": tok.get("scope", " ".join(pending["scopes"])).split(), "expiry": ablauf.isoformat()}
    ziel_dir.mkdir(parents=True, exist_ok=True)
    pfad = ziel_dir / dateiname(email)
    fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f, indent=2)
    offen.unlink(missing_ok=True)
    log(f"Anmeldung gespeichert für {email}. Die Option „Anmelde-Antwort“ kann wieder geleert werden.")
    return True


def main() -> int:
    email = os.environ.get("USER_GOOGLE_EMAIL", "").strip()
    ziel_dir = Path(os.environ["WORKSPACE_MCP_CREDENTIALS_DIR"])
    offen = Path(os.environ.get("GWS_PENDING", ziel_dir.parent / "anmeldung_offen.json"))
    if not email or not os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or not os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"):
        log("Google-Konto, OAuth-Client-ID und Client-Secret eintragen (siehe Dokumentation).")
        return 2
    scopes = benoetigte_scopes()
    pfad = ziel_dir / dateiname(email)
    vorhanden = gespeicherte_scopes(pfad)
    if vorhanden is not None and deckt(vorhanden, scopes):
        log(f"Anmeldung für {email} vorhanden, Rechte passen.")
        return 0
    antwort = os.environ.get("GWS_AUTH_RESPONSE", "").strip()
    if antwort and offen.exists():
        if tauschen(antwort, offen, ziel_dir, email):
            neu = gespeicherte_scopes(pfad) or set()
            if deckt(neu, scopes):
                return 0
            log("Google hat nicht alle Rechte erteilt: " + ", ".join(sorted(set(scopes) - neu)))
    elif vorhanden is not None:
        log("Die Rechte haben sich geändert (Optionen Gmail/Kalender/Drive), neue Zustimmung nötig.")
    ziel_dir.parent.mkdir(parents=True, exist_ok=True)
    link_erzeugen(scopes, email, offen)
    return 2


if __name__ == "__main__":
    sys.exit(main())
