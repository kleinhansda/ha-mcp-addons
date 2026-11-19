"""
title: GitHub-API
author: David
version: 2.0.0
description: GitHub ohne MCP: REST-API für Issues, Pull Requests, Kommentare, Branches, Dateien, Actions/CI, Releases und Suche (einzeln oder viele Aufrufe in einem Schritt), dazu Dateien und Ordner von /share in einem Commit pushen und Repos nach /share holen. Dateiinhalte beim Pushen laufen nicht durch das Modell.
requirements:
"""

# Nachfolger von „Push to Repo“ (1.0.0): push_to_repo und pull_from_repo unverändert, neu sind
# github_api und github_api_mehrere. Sperren: Pushen und /contents-Schreiben nie auf gesperrte
# Branches, Mergen und Löschen nur mit Ventil, Repo-Einstellungen (Mitglieder, Webhooks, Secrets,
# Schutzregeln, Umbenennen) nur mit admin_erlaubt.

import base64
import hashlib
import json
import os
import re
import stat
import tarfile
import tempfile
import time
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlsplit

import aiohttp
from pydantic import BaseModel, Field

MARKER = ".push_to_repo.json"

# {{n:pfad.im.json}} = Wert aus der Antwort von Aufruf n (ab 0), z. B. {{0:number}} oder {{1:head.sha}}
VERWEIS_RE = re.compile(r"\{\{(\d+):([\w.\-]*)\}\}")

# Pfade, die github_api überhaupt aufruft
API_PRAEFIXE = ("/repos/", "/search/", "/user", "/users/", "/orgs/", "/rate_limit", "/notifications", "/gists", "/markdown", "/licenses", "/gitignore", "/meta")

# Repo-Einstellungen: schreiben nur mit admin_erlaubt (Rest nach /repos/owner/name)
ADMIN_RE = re.compile(
    r"^/?$|^/(collaborators|hooks|keys|invitations|transfer|rulesets|environments|autolinks|topics|pages|"
    r"vulnerability-alerts|automated-security-fixes|private-vulnerability-reporting|properties|interaction-limits|"
    r"actions/(secrets|variables|permissions|runners|oidc)|dependabot/secrets|codespaces/secrets|"
    r"branches/.+/(protection|rename))(/|$)"
)

# Felder, die nur Tokens kosten
WEG = {"node_id", "_links", "gravatar_id", "performed_via_github_app", "reactions", "author_association",
       "site_admin", "user_view_type", "permissions", "security_and_analysis", "license", "temp_clone_token"}
URL_BEHALTEN = {"html_url", "download_url", "browser_download_url"}


def _wert(daten: Any, pfad: str) -> Any:
    for teil in [t for t in pfad.split(".") if t]:
        if isinstance(daten, list) and teil.lstrip("-").isdigit():
            daten = daten[int(teil)]
        elif isinstance(daten, dict) and teil in daten:
            daten = daten[teil]
        else:
            raise KeyError(pfad)
    return daten


def _einsetzen(x: Any, ergebnisse: list) -> Any:
    if isinstance(x, str):
        def holen(m):
            i = int(m.group(1))
            if i >= len(ergebnisse) or ergebnisse[i] is None:
                raise KeyError(m.group(0))
            return _wert(ergebnisse[i], m.group(2))
        ganz = VERWEIS_RE.fullmatch(x)
        return holen(ganz) if ganz else VERWEIS_RE.sub(lambda m: str(holen(m)), x)
    if isinstance(x, list):
        return [_einsetzen(e, ergebnisse) for e in x]
    if isinstance(x, dict):
        return {k: _einsetzen(e, ergebnisse) for k, e in x.items()}
    return x


def _schlank(x: Any, tiefe: int = 0) -> Any:
    """Antwort kürzen: Personen als Login, eingebettete Repos als full_name, API-Links und leere Felder weg,
    Dateiinhalte (base64) als Text."""
    if isinstance(x, dict):
        if tiefe > 0 and "login" in x and "avatar_url" in x:
            return x["login"]
        if tiefe > 0 and "full_name" in x and "private" in x:
            return x["full_name"]
        x = dict(x)
        if x.get("encoding") == "base64" and isinstance(x.get("content"), str):
            try:
                x["inhalt"] = base64.b64decode(x.pop("content")).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                x["inhalt"] = f"(Binärdatei, {x.get('size', '?')} Bytes, nicht angezeigt)"
            x.pop("encoding", None)
        aus = {}
        for k, v in x.items():
            if v is None or k in WEG:
                continue
            if (k.endswith("_url") and k not in URL_BEHALTEN) or (k == "url" and isinstance(v, str) and ("api.github.com" in v or "/api/v3/" in v)):
                continue
            if k == "app" and isinstance(v, dict):
                aus[k] = v.get("slug") or v.get("name")
                continue
            aus[k] = _schlank(v, tiefe + 1)
        return aus
    if isinstance(x, list):
        return [_schlank(e, tiefe + 1) for e in x]
    return x


class Tools:
    class Valves(BaseModel):
        github_token: str = Field(
            default="",
            description="GitHub-Token (fine-grained). Rechte je nach Bedarf: Contents, Pull requests, Issues (Lesen/Schreiben), Actions, Checks, Metadata (Lesen). Welche Repos erreichbar sind, bestimmt das Token.",
        )
        erlaubte_repos: str = Field(
            default="",
            description="Optional: Komma-getrennte Liste owner/name. Leer = alle Repos, die das Token erlaubt.",
        )
        schreiben_erlaubt: bool = Field(default=True, description="github_api: POST, PUT, PATCH zulassen (Issues, PRs, Kommentare, Branches, Labels)")
        mergen_erlaubt: bool = Field(default=False, description="github_api: Pull Requests mergen und Branches zusammenführen zulassen")
        loeschen_erlaubt: bool = Field(default=False, description="github_api: DELETE zulassen (z. B. Branch nach dem Merge löschen)")
        admin_erlaubt: bool = Field(default=False, description="github_api: Repo-Einstellungen ändern (Umbenennen, Mitglieder, Webhooks, Secrets, Schutzregeln, neue Repos)")
        max_zeichen: int = Field(default=12000, description="github_api: Antwort an das Modell kürzen")
        quelle_wurzel: str = Field(default="/share/", description="Nur unterhalb dieses Ordners wird gelesen und geschrieben")
        gesperrte_branches: str = Field(
            default="main,master",
            description="Branches, auf die nie geschrieben wird (Push, /contents, Refs). Komma-getrennt. Leer = keine Sperre.",
        )
        ignorieren: str = Field(
            default=".git,__pycache__,.DS_Store,Thumbs.db,node_modules,.venv,.pytest_cache," + MARKER,
            description="Datei- und Ordnernamen, die beim Pushen eines Ordners übersprungen werden (Komma-getrennt)",
        )
        max_datei_mb: float = Field(default=50.0, description="Maximale Größe je Datei in MB (GitHub lehnt über 100 MB ab)")
        max_gesamt_mb: float = Field(default=200.0, description="Maximale Gesamtgröße je Push bzw. Download in MB")
        fuer_terminal_beschreibbar: bool = Field(
            default=True,
            description="Geholte Dateien für alle beschreibbar machen, damit das Terminal sie bearbeiten kann",
        )
        api_url: str = Field(default="https://api.github.com", description="GitHub-API (nur für GitHub Enterprise ändern)")
        timeout_s: int = Field(default=300, description="Zeitlimit je Vorgang in Sekunden")

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()

    # ---------- Hilfen ----------

    def _liste(self, text: str) -> list:
        return [t.strip() for t in (text or "").split(",") if t.strip()]

    def _repo_pruefen(self, repo: str):
        repo = (repo or "").strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            return None, "Fehler: repo muss die Form owner/name haben, z. B. kleinhansda/hb_website."
        erlaubt = [r.lower() for r in self._liste(self.valves.erlaubte_repos)]
        if erlaubt and repo.lower() not in erlaubt:
            return None, f"Fehler: Das Repo {repo} ist für dieses Werkzeug nicht freigegeben (erlaubt: {', '.join(erlaubt)})."
        return repo, None

    def _wurzel(self) -> str:
        return os.path.realpath(self.valves.quelle_wurzel).rstrip("/") + "/"

    def _unter_wurzel(self, pfad: str) -> Optional[str]:
        echt = os.path.realpath(pfad or "")
        w = self._wurzel()
        return echt if (echt + "/").startswith(w) else None

    @staticmethod
    def _repo_pfad_ok(p: str) -> bool:
        return bool(p) and not p.startswith("/") and "\\" not in p and not any(t in ("", ".", "..") for t in p.split("/"))

    @staticmethod
    def _blob_sha(daten: bytes) -> str:
        return hashlib.sha1(b"blob %d\x00" % len(daten) + daten).hexdigest()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.valves.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "open-webui-github-api",
        }

    @staticmethod
    async def _fehlertext(r) -> str:
        try:
            return (await r.json()).get("message", "")
        except Exception:
            return (await r.text())[:300]

    @staticmethod
    def _json(daten: Any) -> Any:
        return json.loads(daten) if isinstance(daten, str) and daten.strip() else daten

    # ---------- github_api: Prüfen, Senden, Darstellen ----------

    def _api_pruefen(self, methode: str, pfad: str, daten: Any) -> Optional[str]:
        v = self.valves
        if not v.github_token:
            return "Im Werkzeug „GitHub-API“ ist kein GitHub-Token hinterlegt (Ventile). Das muss ein Admin eintragen."
        if methode not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return f"Methode {methode} nicht erlaubt."
        teile = urlsplit(pfad or "")
        p = teile.path
        if teile.scheme or teile.netloc or not p.startswith("/") or ".." in p or any(c.isspace() for c in p):
            return "pfad muss mit / beginnen, ohne Adresse, ohne Leerzeichen und ohne '..', z. B. /repos/owner/name/pulls."
        if not p.startswith(API_PRAEFIXE):
            return "Pfad nicht freigegeben. Erlaubt: " + ", ".join(API_PRAEFIXE)
        gesperrt = set(self._liste(v.gesperrte_branches))
        rest = ""
        if p.startswith("/repos/"):
            m = re.match(r"^/repos/([^/]+/[^/]+)(.*)$", p)
            if not m:
                return "Pfad unvollständig: /repos/owner/name/…"
            _, f = self._repo_pruefen(m.group(1))
            if f:
                return f.removeprefix("Fehler: ")
            rest = m.group(2)
        if methode == "GET":
            return None
        if methode == "DELETE" and not v.loeschen_erlaubt:
            return "Löschen ist abgeschaltet (Ventil loeschen_erlaubt). Den Nutzer fragen."
        if methode != "DELETE" and not v.schreiben_erlaubt:
            return "Schreiben ist abgeschaltet (Ventil schreiben_erlaubt)."
        if not p.startswith("/repos/"):
            if p == "/markdown" or v.admin_erlaubt:
                return None
            return "Außerhalb von /repos/ wird nur gelesen (Ventil admin_erlaubt)."
        if ADMIN_RE.search(rest) and not v.admin_erlaubt:
            return "Repo-Einstellungen sind gesperrt (Ventil admin_erlaubt). Den Nutzer bitten, das auf GitHub selbst zu ändern."
        if re.match(r"^/pulls/\d+/merge$|^/merges$|^/merge-upstream$", rest) and not v.mergen_erlaubt:
            return "Mergen ist abgeschaltet (Ventil mergen_erlaubt). Link zum PR geben, der Nutzer merged selbst."
        d = daten if isinstance(daten, dict) else {}
        if re.match(r"^/contents(/|$)", rest):
            b = str(d.get("branch") or "")
            if not b:
                return "Schreiben über /contents nur mit branch in daten (eigener Branch, nicht der Standard-Branch). Für mehrere Dateien push_to_repo nehmen."
            if b in gesperrt:
                return f"Auf „{b}“ wird nie geschrieben. Eigenen Branch nehmen und einen PR anlegen."
        m = re.match(r"^/git/refs/heads/(.+)$", rest)
        if m and m.group(1) in gesperrt:
            return f"Der Branch „{m.group(1)}“ ist gesperrt."
        if rest == "/git/refs" and str(d.get("ref", "")).removeprefix("refs/heads/") in gesperrt:
            return "Gesperrte Branches werden nicht angelegt oder verschoben."
        return None

    @staticmethod
    def _naechste(link: str, api: str) -> str:
        for teil in (link or "").split(","):
            if 'rel="next"' in teil:
                url = teil.split(";")[0].strip().strip("<>")
                return url[len(api):] if url.startswith(api) else url
        return ""

    async def _anfrage(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten: Any) -> tuple:
        """Gibt (status, json_oder_text, ist_json, nächste_seite) zurück. Weiterleitungen von Hand:
        signierte Download-Links (Logs, Archive) liegen auf anderen Hosts und bekommen kein Token."""
        api = self.valves.api_url.rstrip("/")
        url, kopf = api + pfad, self._headers()
        for _ in range(5):
            body = daten if methode != "GET" and daten not in (None, "") else None
            async with s.request(methode, url, headers=kopf, json=body, allow_redirects=False) as r:
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                    url = urljoin(str(r.url), r.headers["Location"])
                    if urlsplit(url).netloc != urlsplit(api).netloc:
                        kopf = {"User-Agent": "open-webui-github-api"}
                    if r.status == 303 or (r.status in (301, 302) and methode != "GET"):
                        methode, daten = "GET", None
                    continue
                roh = bytearray()
                async for teil in r.content.iter_chunked(1 << 16):
                    roh += teil
                    if len(roh) > 5 * 1048576:
                        break
                weiter = self._naechste(r.headers.get("Link", ""), api)
                text = roh.decode("utf-8", errors="replace")
                if self.valves.github_token:
                    text = text.replace(self.valves.github_token, "***")
                if "json" in r.headers.get("Content-Type", "") and text.strip():
                    try:
                        return r.status, json.loads(text), True, weiter
                    except ValueError:
                        pass
                return r.status, text, False, weiter
        return 0, "Zu viele Weiterleitungen.", False, ""

    def _darstellen(self, status: int, inhalt: Any, ist_json: bool, weiter: str, pfad: str, n: int) -> str:
        kopf = f"HTTP {status}" + (f" | nächste Seite: {weiter}" if weiter else "")
        if status == 404:
            kopf += " (gibt es nicht oder das Token hat keinen Zugriff)"
        if ist_json:
            text = json.dumps(_schlank(inhalt), ensure_ascii=False, separators=(",", ":"))
        else:
            text = inhalt if isinstance(inhalt, str) else ""
        if not text:
            text = "OK" if status < 400 else ""
        if len(text) > n:
            if not ist_json and "/logs" in pfad:
                text = f"[…Anfang gekürzt, {len(text)} Zeichen]\n" + text[-n:]
            else:
                text = text[:n] + f" […gekürzt, {len(text)} Zeichen. Mit ?per_page=, Filtern oder einzelnen Pfaden eingrenzen]"
        return kopf + "\n" + text

    async def github_api(self, methode: str, pfad: str, daten: Optional[Any] = None, __event_emitter__=None) -> str:
        """
        GitHub-REST-API einmal aufrufen: Issues, Pull Requests, Reviews, Kommentare, Branches, Dateien lesen, Actions/CI, Releases, Suche. Beispiele: GET /repos/o/r/pulls?state=open, GET /repos/o/r/contents/pfad?ref=branch (Text kommt dekodiert), POST /repos/o/r/pulls {"title","head","base","body"}, GET /repos/o/r/commits/<ref>/check-runs. Mehrere Aufrufe: github_api_mehrere. Dateien committen: push_to_repo.
        :param methode: GET, POST, PUT, PATCH oder DELETE
        :param pfad: Pfad ab der API-Wurzel, beginnt mit /, Query direkt anhängen
        :param daten: JSON-Objekt für POST, PUT, PATCH
        :return: HTTP-Status und gekürzte Antwort
        """
        methode = (methode or "GET").upper()
        try:
            daten = self._json(daten)
        except ValueError:
            return "Fehler: daten ist kein gültiges JSON."
        fehler = self._api_pruefen(methode, pfad, daten)
        if fehler:
            return "Fehler: " + fehler
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"GitHub: {methode} {pfad}", "done": False}})
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout_s)) as s:
                status, inhalt, ist_json, weiter = await self._anfrage(s, methode, pfad, daten)
        except Exception as e:
            return f"Fehler beim Aufruf: {type(e).__name__}: {e}"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"GitHub: {methode} {pfad}", "done": True}})
        return self._darstellen(status, inhalt, ist_json, weiter, pfad, self.valves.max_zeichen)

    async def github_api_mehrere(self, aufrufe: list[dict], bei_fehler_weiter: bool = False, __event_emitter__=None) -> str:
        """
        Viele GitHub-API-Aufrufe in einem Schritt, z. B. PR anlegen und danach Label setzen. Jeder Aufruf: {"methode": "POST", "pfad": "/repos/o/r/…", "daten": {…}}. Werte aus früheren Antworten mit {{n:feld}} einsetzen (n ab 0), z. B. "/repos/o/r/issues/{{0:number}}/labels". Bricht beim ersten Fehler ab, außer bei_fehler_weiter.
        :param aufrufe: Liste der Aufrufe (als Liste, nicht als Text)
        :param bei_fehler_weiter: nach einem Fehler weitermachen
        :return: je Aufruf Nummer, HTTP-Status und gekürzte Antwort
        """
        try:
            aufrufe = self._json(aufrufe) or []
        except ValueError:
            return "Fehler: aufrufe ist kein gültiges JSON."
        if not isinstance(aufrufe, list) or not all(isinstance(a, dict) for a in aufrufe):
            return 'Fehler: aufrufe muss eine Liste von Objekten sein: [{"methode": "GET", "pfad": "/repos/…"}].'
        if len(aufrufe) > 30:
            return "Fehler: höchstens 30 Aufrufe je Schritt."
        je = max(400, self.valves.max_zeichen // max(1, len(aufrufe)))
        ergebnisse, zeilen = [], []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout_s)) as s:
            for i, a in enumerate(aufrufe):
                methode = str(a.get("methode") or "GET").upper()
                status, ausgabe, inhalt = 0, "", None
                try:
                    pfad = _einsetzen(str(a.get("pfad") or ""), ergebnisse)
                    daten = _einsetzen(self._json(a.get("daten")), ergebnisse)
                    fehler = self._api_pruefen(methode, pfad, daten)
                except (KeyError, IndexError, ValueError) as e:
                    pfad, fehler = a.get("pfad"), f"Verweis oder JSON ungültig: {e}"
                if not fehler:
                    if __event_emitter__:
                        await __event_emitter__({"type": "status", "data": {"description": f"GitHub {i + 1}/{len(aufrufe)}: {methode} {pfad}", "done": False}})
                    try:
                        status, inhalt, ist_json, weiter = await self._anfrage(s, methode, pfad, daten)
                        ausgabe = self._darstellen(status, inhalt, ist_json, weiter, pfad, je).replace("\n", " ", 1)
                        if not ist_json:
                            inhalt = None
                    except Exception as e:
                        fehler = f"{type(e).__name__}: {e}"
                ergebnisse.append(inhalt)
                zeilen.append(f"[{i}] {methode} {pfad}: " + (f"Fehler: {fehler}" if fehler else ausgabe))
                if (fehler or status >= 400) and not bei_fehler_weiter:
                    if i < len(aufrufe) - 1:
                        zeilen.append(f"Abgebrochen; Aufrufe {i + 1} bis {len(aufrufe) - 1} nicht ausgeführt.")
                    break
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "GitHub: fertig", "done": True}})
        return "\n".join(zeilen)

    # ---------- push_to_repo ----------

    async def push_to_repo(
        self,
        repo: str,
        branch: str,
        commit_nachricht: str,
        quelle: str,
        ziel: str = "",
        dateien: Optional[list[str]] = None,
        loeschen: Optional[list[str]] = None,
        neuer_branch_von: str = "",
        erwarteter_commit: str = "",
        ersetzen: bool = False,
        __event_emitter__=None,
    ) -> str:
        """
        Pusht Dateien von /share in einem einzigen Commit auf einen Branch eines GitHub-Repos. Der Dateiinhalt läuft nicht durch den Chat und wird nach dem Hochladen per Blob-SHA geprüft. Geht für Text- und Binärdateien, behält das Ausführbar-Bit und kann im selben Commit Dateien löschen. Unveränderte Dateien werden übersprungen.

        :param repo: Repo als owner/name, z. B. kleinhansda/ha-addons
        :param branch: Ziel-Branch, z. B. fix-run-sh. Nie main.
        :param commit_nachricht: Commit-Nachricht
        :param quelle: Absoluter Pfad unter /share: eine Datei oder ein Ordner (z. B. ein mit pull_from_repo geholtes Repo)
        :param ziel: Pfad im Repo. Bei einer Datei der Dateipfad (leer = Dateiname im Repo-Wurzelordner), bei einem Ordner der Zielordner (leer = Repo-Wurzel)
        :param dateien: Optional: nur diese Pfade relativ zu quelle pushen (z. B. die geänderten Dateien aus git status). Leer = alles unter quelle
        :param loeschen: Optional: Pfade im Repo, die im selben Commit gelöscht werden (Datei oder Ordner)
        :param neuer_branch_von: Gibt es branch noch nicht, wird er von diesem Branch aus angelegt, z. B. main. Leer = branch muss existieren
        :param erwarteter_commit: Optional: Commit-SHA, auf dem deine Änderungen beruhen (aus pull_from_repo oder git rev-parse HEAD). Steht der Branch woanders, wird abgebrochen
        :param ersetzen: True erlaubt das Überschreiben vorhandener Dateien mit anderem Inhalt. Für bearbeitete Dateien nötig; für neue Dateien False lassen
        :return: Ergebnis als JSON (Commit, geänderte, neue, gelöschte Dateien, Link) oder eine Fehlermeldung
        """
        v = self.valves

        async def status(text: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        if not v.github_token:
            return "Fehler: Im Werkzeug „GitHub-API“ ist kein GitHub-Token hinterlegt (Ventile). Das muss ein Admin eintragen."
        repo, f = self._repo_pruefen(repo)
        if f:
            return f
        branch = (branch or "").strip()
        if not branch:
            return "Fehler: branch fehlt."
        if branch in self._liste(v.gesperrte_branches):
            return f"Fehler: Auf „{branch}“ pusht dieses Werkzeug nie. Eigenen Branch verwenden (neuer_branch_von=\"{branch}\")."
        if not (commit_nachricht or "").strip():
            return "Fehler: commit_nachricht fehlt."

        # Quelle einsammeln
        q = self._unter_wurzel(quelle)
        if not q:
            return f"Fehler: quelle muss unter {v.quelle_wurzel} liegen."
        if not os.path.exists(q):
            return f"Fehler: quelle nicht gefunden: {quelle}"
        ziel = (ziel or "").strip().strip("/")
        if ziel and not self._repo_pfad_ok(ziel):
            return "Fehler: ziel muss ein relativer Pfad im Repo sein, ohne „..“."
        ignor = set(self._liste(v.ignorieren))
        eintraege = []  # (lokaler Pfad, Repo-Pfad)

        if os.path.isfile(q):
            if dateien:
                return "Fehler: dateien nur zusammen mit einem Ordner als quelle angeben."
            eintraege.append((q, ziel or os.path.basename(q)))
        else:
            if dateien:
                for rel in dateien:
                    rel = (rel or "").strip()
                    while rel.startswith("./"):
                        rel = rel[2:]
                    if not self._repo_pfad_ok(rel) or any(t in ignor for t in rel.split("/")):
                        return f"Fehler: Ungültiger oder ausgeschlossener Pfad in dateien: {rel}"
                    lokal = os.path.realpath(os.path.join(q, rel))
                    if not (lokal + "/").startswith(q.rstrip("/") + "/") or not os.path.isfile(lokal):
                        return f"Fehler: {rel} ist keine Datei unter {quelle}."
                    eintraege.append((lokal, f"{ziel}/{rel}" if ziel else rel))
            else:
                uebersprungen_links = []
                for wurzel, ordner, namen in os.walk(q, followlinks=False):
                    ordner[:] = sorted(o for o in ordner if o not in ignor and not os.path.islink(os.path.join(wurzel, o)))
                    for n in sorted(namen):
                        if n in ignor:
                            continue
                        lokal = os.path.join(wurzel, n)
                        if os.path.islink(lokal):
                            uebersprungen_links.append(os.path.relpath(lokal, q))
                            continue
                        rel = os.path.relpath(lokal, q).replace(os.sep, "/")
                        eintraege.append((lokal, f"{ziel}/{rel}" if ziel else rel))
        for _, rp in eintraege:
            if not self._repo_pfad_ok(rp):
                return f"Fehler: Ungültiger Zielpfad im Repo: {rp}"

        loeschen = [p.strip().strip("/") for p in (loeschen or []) if p and p.strip()]
        for p in loeschen:
            if not self._repo_pfad_ok(p):
                return f"Fehler: Ungültiger Pfad in loeschen: {p}"
        if not eintraege and not loeschen:
            return "Fehler: Nichts zu pushen (keine Dateien gefunden, nichts zu löschen)."

        gesamt = 0
        for lokal, rp in eintraege:
            g = os.path.getsize(lokal)
            if g > v.max_datei_mb * 1048576:
                return f"Fehler: {rp} ist {g / 1048576:.1f} MB groß, erlaubt sind {v.max_datei_mb:g} MB je Datei."
            gesamt += g
        if gesamt > v.max_gesamt_mb * 1048576:
            return f"Fehler: Zusammen {gesamt / 1048576:.1f} MB, erlaubt sind {v.max_gesamt_mb:g} MB je Push."

        api = v.api_url.rstrip("/")
        r_url = f"{api}/repos/{repo}"
        await status(f"Prüfe {repo}@{branch} …")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=v.timeout_s), headers=self._headers()) as s:

                async def get_json(url, wobei, params=None, erlaubt404=False):
                    async with s.get(url, params=params) as r:
                        if r.status == 404 and erlaubt404:
                            return None, None
                        if r.status >= 400:
                            return None, f"Fehler von GitHub beim {wobei} ({r.status}): {await self._fehlertext(r)}"
                        return await r.json(), None

                async def post_json(url, body, wobei, methode="post"):
                    async with getattr(s, methode)(url, json=body) as r:
                        if r.status >= 400:
                            return None, r.status, f"Fehler von GitHub beim {wobei} ({r.status}): {await self._fehlertext(r)}"
                        return await r.json(), r.status, None

                ref, f = await get_json(f"{r_url}/git/ref/heads/{quote(branch, safe='/')}", "Lesen des Branches", erlaubt404=True)
                if f:
                    return f
                neu_anlegen = ref is None
                if neu_anlegen:
                    basis = (neuer_branch_von or "").strip()
                    if not basis:
                        return f"Fehler: Branch „{branch}“ gibt es in {repo} nicht (oder das Token darf das Repo nicht lesen). Mit neuer_branch_von anlegen lassen, z. B. neuer_branch_von=\"main\"."
                    ref, f = await get_json(f"{r_url}/git/ref/heads/{quote(basis, safe='/')}", "Lesen des Basis-Branches", erlaubt404=True)
                    if f:
                        return f
                    if ref is None:
                        return f"Fehler: Basis-Branch „{basis}“ gibt es in {repo} nicht."
                kopf = ref["object"]["sha"]
                erwartet = (erwarteter_commit or "").strip().lower()
                if erwartet and not kopf.lower().startswith(erwartet):
                    await status("Branch hat sich geändert", True)
                    return (
                        f"Abgebrochen: {repo}@{branch if not neu_anlegen else neuer_branch_von} steht auf {kopf[:12]}, "
                        f"deine Änderungen beruhen auf {erwartet[:12]}. Inzwischen gibt es andere Commits. "
                        "Den Nutzer fragen; ggf. neu holen (pull_from_repo) und Änderungen erneut anwenden."
                    )

                commit, f = await get_json(f"{r_url}/git/commits/{kopf}", "Lesen des Commits")
                if f:
                    return f
                baum_sha = commit["tree"]["sha"]
                baum, f = await get_json(f"{r_url}/git/trees/{baum_sha}", "Lesen des Dateibaums", params={"recursive": "1"})
                if f:
                    return f
                vorhanden = None
                if not baum.get("truncated"):
                    vorhanden = {e["path"]: e for e in baum.get("tree", [])}

                async def eintrag(pfad):
                    if vorhanden is not None:
                        return vorhanden.get(pfad)
                    d, _ = await get_json(f"{r_url}/contents/{quote(pfad)}", "Prüfen", params={"ref": kopf}, erlaubt404=True)
                    if d is None:
                        return None
                    if isinstance(d, list):
                        return {"type": "tree"}
                    return {"type": "blob", "sha": d.get("sha"), "mode": None}

                await status(f"Vergleiche {len(eintraege)} Datei(en) …")
                aenderungen, neue, geaendert, gleich, konflikte = [], [], [], [], []
                for lokal, rp in eintraege:
                    with open(lokal, "rb") as fh:
                        daten = fh.read()
                    sha = self._blob_sha(daten)
                    modus = "100755" if os.stat(lokal).st_mode & stat.S_IXUSR else "100644"
                    alt = await eintrag(rp)
                    if alt and alt.get("type") == "tree":
                        return f"Fehler: {rp} ist im Repo ein Ordner, keine Datei."
                    if alt and alt.get("sha") == sha and (alt.get("mode") in (None, modus)):
                        gleich.append(rp)
                        continue
                    if alt and alt.get("sha") != sha and not ersetzen:
                        konflikte.append(rp)
                        continue
                    aenderungen.append((lokal, rp, sha, modus, daten))
                    (geaendert if alt else neue).append(rp)
                if konflikte:
                    await status("Vorhandene Dateien", True)
                    liste = ", ".join(konflikte[:20]) + (" …" if len(konflikte) > 20 else "")
                    return (
                        f"Nicht gepusht: {len(konflikte)} Datei(en) gibt es auf {branch} schon mit anderem Inhalt: {liste}. "
                        "Sind es bearbeitete Dateien, mit ersetzen=true wiederholen. Sonst anderen Namen wählen oder den Nutzer fragen."
                    )

                geloescht, fehlt = [], []
                for p in loeschen:
                    if vorhanden is not None:
                        treffer = [k for k, e in vorhanden.items() if e["type"] == "blob" and (k == p or k.startswith(p + "/"))]
                    else:
                        e = await eintrag(p)
                        treffer = [p] if e and e.get("type") == "blob" else []
                    if not treffer:
                        fehlt.append(p)
                    geloescht.extend(treffer)
                lokal_da = sorted(set(geloescht) & {rp for _, rp in eintraege})
                if lokal_da:
                    await status("Löschen widersprüchlich", True)
                    liste = ", ".join(lokal_da[:20]) + (" …" if len(lokal_da) > 20 else "")
                    return (
                        f"Nicht gepusht: Zum Löschen angegeben, liegt aber in quelle noch vor: {liste}. "
                        "Erst lokal löschen (sonst kommt die Datei beim nächsten Push zurück) oder aus loeschen nehmen."
                    )
                geloescht = sorted(set(geloescht))

                if not aenderungen and not geloescht:
                    await status("Keine Änderungen", True)
                    return json.dumps({"ok": True, "repo": repo, "branch": branch, "commit": None, "hinweis": "Keine Änderungen: alle Dateien sind auf dem Branch schon identisch.", "unveraendert": len(gleich), "nicht_gefunden_zum_loeschen": fehlt}, ensure_ascii=False)

                baum_eintraege = []
                for i, (lokal, rp, sha, modus, daten) in enumerate(aenderungen, 1):
                    await status(f"Lade hoch {i}/{len(aenderungen)}: {rp}")
                    blob, _, f = await post_json(f"{r_url}/git/blobs", {"content": base64.b64encode(daten).decode("ascii"), "encoding": "base64"}, f"Hochladen von {rp}")
                    if f:
                        return f
                    if blob.get("sha") != sha:
                        return f"Fehler: Prüfsumme von {rp} stimmt nach dem Hochladen nicht (lokal {sha[:12]}, GitHub {str(blob.get('sha'))[:12]}). Nichts committet."
                    baum_eintraege.append({"path": rp, "mode": modus, "type": "blob", "sha": sha})
                for p in geloescht:
                    baum_eintraege.append({"path": p, "mode": "100644", "type": "blob", "sha": None})

                await status("Erzeuge Commit …")
                neuer_baum, _, f = await post_json(f"{r_url}/git/trees", {"base_tree": baum_sha, "tree": baum_eintraege}, "Anlegen des Dateibaums")
                if f:
                    return f
                neuer_commit, _, f = await post_json(f"{r_url}/git/commits", {"message": commit_nachricht.strip(), "tree": neuer_baum["sha"], "parents": [kopf]}, "Anlegen des Commits")
                if f:
                    return f
                c_sha = neuer_commit["sha"]
                if neu_anlegen:
                    _, st, f = await post_json(f"{r_url}/git/refs", {"ref": f"refs/heads/{branch}", "sha": c_sha}, "Anlegen des Branches")
                else:
                    _, st, f = await post_json(f"{r_url}/git/refs/heads/{quote(branch, safe='/')}", {"sha": c_sha, "force": False}, "Aktualisieren des Branches", methode="patch")
                if f:
                    if st == 422:
                        return f"Abgebrochen: Während des Pushs kam ein anderer Commit auf {branch}. Nichts geändert. Den Nutzer fragen. ({f})"
                    return f
        except aiohttp.ClientError as e:
            await status("Verbindungsfehler", True)
            return f"Fehler: GitHub nicht erreichbar ({type(e).__name__}). Vor einem neuen Versuch den Branch prüfen."
        except TimeoutError:
            await status("Zeitüberschreitung", True)
            return "Fehler: Zeitüberschreitung bei GitHub. Vor einem neuen Versuch den Branch prüfen."

        # Marker im geholten Ordner auf den neuen Stand setzen
        marker = os.path.join(q, MARKER) if os.path.isdir(q) else None
        if marker and os.path.isfile(marker):
            try:
                with open(marker, encoding="utf-8") as fh:
                    m = json.load(fh)
                if m.get("repo", "").lower() == repo.lower():
                    m.update({"ref": branch, "commit": c_sha, "aktualisiert": time.strftime("%Y-%m-%dT%H:%M:%S")})
                    with open(marker, "w", encoding="utf-8") as fh:
                        json.dump(m, fh, ensure_ascii=False, indent=2)
            except Exception:
                pass

        await status("Gepusht", True)

        def kurz(lst):
            return lst[:50] + ([f"… und {len(lst) - 50} weitere"] if len(lst) > 50 else [])

        web = "https://github.com" if "api.github.com" in api else api
        return json.dumps(
            {
                "ok": True,
                "repo": repo,
                "branch": branch,
                "branch_neu_angelegt": neu_anlegen,
                "commit": c_sha,
                "vorher": kopf,
                "neu": kurz(neue),
                "geaendert": kurz(geaendert),
                "geloescht": kurz(geloescht),
                "unveraendert": len(gleich),
                "nicht_gefunden_zum_loeschen": fehlt,
                "link": f"{web}/{repo}/commit/{c_sha}",
                "pr_anlegen": f"{web}/{repo}/compare/{quote(branch, safe='')}?expand=1",
                "pr_per_api": f"github_api POST /repos/{repo}/pulls mit daten {{\"title\": …, \"head\": \"{branch}\", \"base\": …, \"body\": …}}",
            },
            ensure_ascii=False,
        )

    # ---------- pull_from_repo ----------

    async def pull_from_repo(
        self,
        repo: str,
        ziel_ordner: str,
        ref: str = "",
        pfad: str = "",
        __event_emitter__=None,
    ) -> str:
        """
        Holt ein Repo, einen Ordner oder eine Datei aus GitHub in einen neuen Ordner unter /share, auch aus privaten Repos. Die Pfade bleiben wie im Repo, so dass der Ordner danach im Terminal bearbeitet und mit push_to_repo (quelle=ziel_ordner, ziel leer) zurückgepusht werden kann. Kein git und keine Zugangsdaten im Terminal nötig.

        :param repo: Repo als owner/name, z. B. kleinhansda/ha-addons
        :param ziel_ordner: Neuer oder leerer Ordner unter /share, z. B. /share/repos/ha-addons. Vorhandene Dateien werden nie überschrieben
        :param ref: Branch, Tag oder Commit. Leer = Standard-Branch
        :param pfad: Optional: nur diesen Ordner oder diese Datei im Repo holen, z. B. open_webui. Leer = ganzes Repo
        :return: Ergebnis als JSON (Ordner, Commit, Anzahl Dateien) oder eine Fehlermeldung
        """
        v = self.valves

        async def status(text: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        if not v.github_token:
            return "Fehler: Im Werkzeug „GitHub-API“ ist kein GitHub-Token hinterlegt (Ventile). Das muss ein Admin eintragen."
        repo, f = self._repo_pruefen(repo)
        if f:
            return f
        pfad = (pfad or "").strip().strip("/")
        if pfad and not self._repo_pfad_ok(pfad):
            return "Fehler: pfad muss ein relativer Pfad im Repo sein, ohne „..“."

        roh = (ziel_ordner or "").rstrip("/")
        w = self._wurzel()
        eltern = os.path.realpath(os.path.dirname(roh)) if roh else ""
        if not roh or not os.path.isabs(roh) or not (eltern + "/").startswith(w):
            return f"Fehler: ziel_ordner muss ein absoluter Pfad unter {v.quelle_wurzel} sein."
        ziel = os.path.join(eltern, os.path.basename(roh))
        if os.path.islink(ziel):
            return "Fehler: ziel_ordner darf kein Link sein."
        if os.path.exists(ziel) and (not os.path.isdir(ziel) or os.listdir(ziel)):
            return f"Fehler: {ziel_ordner} gibt es schon und ist nicht leer. Einen neuen Ordner angeben; vorhandene Dateien werden nie überschrieben."

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
        tmp.close()
        try:
            return await self._pull(repo, ziel, ref, pfad, tmp.name, status)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    async def _pull(self, repo, ziel, ref, pfad, tmpname, status) -> str:
        v = self.valves
        api = v.api_url.rstrip("/")
        r_url = f"{api}/repos/{repo}"
        await status(f"Hole {repo} …")

        async def speichern(r) -> Optional[str]:
            gelesen = 0
            with open(tmpname, "wb") as out:
                async for teil in r.content.iter_chunked(1 << 16):
                    gelesen += len(teil)
                    if gelesen > v.max_gesamt_mb * 1048576:
                        return f"Fehler: Archiv größer als {v.max_gesamt_mb:g} MB. Mit pfad nur einen Teil holen oder Valve erhöhen."
                    out.write(teil)
            return None

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=v.timeout_s), headers=self._headers()) as s:
                ref = (ref or "").strip()
                if not ref:
                    async with s.get(r_url) as r:
                        if r.status >= 400:
                            return f"Fehler von GitHub beim Lesen des Repos ({r.status}): {await self._fehlertext(r)}"
                        ref = (await r.json()).get("default_branch") or "main"
                async with s.get(f"{r_url}/commits/{quote(ref, safe='')}", headers={"Accept": "application/vnd.github.sha"}) as r:
                    if r.status >= 400:
                        return f"Fehler von GitHub: Stand „{ref}“ in {repo} nicht gefunden ({r.status}): {await self._fehlertext(r)}"
                    c_sha = (await r.text()).strip()
                url = None
                async with s.get(f"{r_url}/tarball/{c_sha}", allow_redirects=False) as r:
                    if r.status in (301, 302, 303, 307, 308):
                        url = urljoin(str(r.url), r.headers.get("Location", ""))
                    elif r.status >= 400:
                        return f"Fehler von GitHub beim Archiv ({r.status}): {await self._fehlertext(r)}"
                    else:
                        f = await speichern(r)
                        if f:
                            return f
            if url:
                # Der Download-Link ist signiert und liegt auf einem anderen Host: ohne Token abrufen
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=v.timeout_s)) as s2:
                    async with s2.get(url) as r:
                        if r.status >= 400:
                            return f"Fehler beim Herunterladen des Archivs ({r.status})."
                        f = await speichern(r)
                        if f:
                            return f
        except aiohttp.ClientError as e:
            await status("Verbindungsfehler", True)
            return f"Fehler: GitHub nicht erreichbar ({type(e).__name__})."
        except TimeoutError:
            await status("Zeitüberschreitung", True)
            return "Fehler: Zeitüberschreitung beim Herunterladen."

        await status("Entpacke …")
        anzahl, groesse, links, angelegt = 0, 0, [], not os.path.exists(ziel)
        try:
            os.makedirs(ziel, exist_ok=True)
            with tarfile.open(tmpname, "r:gz") as tar:
                for m in tar:
                    teile = m.name.split("/", 1)
                    if len(teile) < 2 or not teile[1]:
                        continue
                    rel = teile[1].rstrip("/")
                    if pfad and not (rel == pfad or rel.startswith(pfad + "/")):
                        continue
                    if not self._repo_pfad_ok(rel):
                        continue
                    dest = os.path.join(ziel, rel)
                    if not (os.path.realpath(os.path.dirname(dest)) + "/").startswith(os.path.realpath(ziel) + "/"):
                        continue
                    if m.isdir():
                        os.makedirs(dest, exist_ok=True)
                        continue
                    if not m.isfile():
                        links.append(rel)
                        continue
                    groesse += m.size
                    if groesse > v.max_gesamt_mb * 1048576:
                        return f"Fehler: Mehr als {v.max_gesamt_mb:g} MB entpackt, abgebrochen. Teilweise entpackt in {ziel}."
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    quelle = tar.extractfile(m)
                    with open(dest, "xb") as out:
                        while True:
                            block = quelle.read(1 << 16)
                            if not block:
                                break
                            out.write(block)
                    modus = 0o755 if m.mode & 0o100 else 0o644
                    if v.fuer_terminal_beschreibbar:
                        modus |= 0o666
                    os.chmod(dest, modus)
                    anzahl += 1
        except FileExistsError as e:
            return f"Fehler: Datei existiert schon, nichts überschrieben: {e.filename}"
        except tarfile.TarError as e:
            return f"Fehler: Archiv ungültig ({e})."

        if anzahl == 0:
            if angelegt:
                for wurzel, ordner, namen in os.walk(ziel, topdown=False):
                    if not namen:
                        try:
                            os.rmdir(wurzel)
                        except OSError:
                            pass
            await status("Nichts gefunden", True)
            return f"Fehler: In {repo}@{ref} gibt es unter „{pfad or '/'}“ keine Dateien."

        if v.fuer_terminal_beschreibbar:
            for wurzel, ordner, _ in os.walk(ziel):
                for o in ordner:
                    try:
                        os.chmod(os.path.join(wurzel, o), 0o777)
                    except OSError:
                        pass
            try:
                os.chmod(ziel, 0o777)
            except OSError:
                pass
        with open(os.path.join(ziel, MARKER), "w", encoding="utf-8") as fh:
            json.dump({"repo": repo, "ref": ref, "commit": c_sha, "pfad": pfad, "geholt": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh, ensure_ascii=False, indent=2)

        await status(f"{anzahl} Dateien geholt", True)
        return json.dumps(
            {
                "ok": True,
                "repo": repo,
                "ref": ref,
                "commit": c_sha,
                "ordner": ziel,
                "pfad_im_repo": pfad or "/",
                "dateien": anzahl,
                "groesse_mb": round(groesse / 1048576, 2),
                "links_uebersprungen": links[:20],
                "zurueckpushen": f"push_to_repo(repo=\"{repo}\", branch=<eigener Branch>, neuer_branch_von=\"{ref}\", quelle=\"{ziel}\", ziel=\"\", erwarteter_commit=\"{c_sha}\", ersetzen=true, dateien=[geänderte Pfade])",
            },
            ensure_ascii=False,
        )
