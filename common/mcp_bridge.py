#!/usr/bin/env python3
"""Brücke stdio → MCP Streamable HTTP für das interne Docker-Netz, optional mit Token.

Quelle: common/mcp_bridge.py, Kopien in <add-on>/rootfs/usr/local/lib/mcp/ (sync_common.py).
Ursprung: kleinhansda/artcraft-mcp-ha, dort gleich aufgebaut.

mcp-auth-proxy kennt keinen Modus ohne Login. Für Clients im selben Netz (z. B. Open WebUI
als App auf demselben Home Assistant) stellt diese Brücke den stdio-MCP-Server einer App
unter http://<host>:<port>/mcp bereit. Nur Standardbibliothek.

Aufruf: mcp_bridge.py <port> -- <befehl> [argumente ...]

Verhalten:
- Die App startet erst beim ersten Request (spart RAM für ungenutzte Apps).
- Ein App-Prozess für alle Clients, wie beim Proxy. "initialize" geht nur einmal an die App,
  weitere Clients bekommen die gespeicherte Antwort.
- Request-IDs werden umgeschrieben, damit sich gleichzeitige Clients nicht in die Quere kommen.
- Antworten kommen als application/json. GET /mcp öffnet einen leeren SSE-Kanal (nur Keepalive),
  ohne Accept: text/event-stream gibt es 405.
- Rückfragen (elicitation): Meldet ein Client beim initialize die Fähigkeit "elicitation" an, bekommt
  er bei tools/call (mit Accept: text/event-stream und Mcp-Session-Id) die Antwort als SSE-Stream.
  Fragt die App während des Aufrufs nach (elicitation/create, z. B. "Diese Mail senden?"), geht die
  Frage über diesen Stream an genau diesen Client; seine Antwort (POST) geht an die App zurück.
  Gibt es nicht genau einen solchen laufenden Aufruf, lehnt die Brücke die Rückfrage ab (die App
  sendet dann nichts). Die App sieht die Fähigkeit immer, auch wenn der erste Client sie nicht
  meldet; sampling und roots werden weiterhin nicht unterstützt.
- Anfragen mit Origin-Header (Browser) werden abgelehnt, Schutz gegen DNS-Rebinding.
- Nachsicht bei Werkzeug-Argumenten: Schickt ein Modell einen Wert im falschen Grundtyp
  (Text statt Liste, "3" statt 3, "true" statt true, JSON als Text), passt die Brücke ihn an
  das Eingabeschema des Werkzeugs an, statt die App mit einem Validierungsfehler antworten zu
  lassen. Nur oberste Ebene, nur eindeutige Fälle; das Protokoll nennt das Feld, nie den Wert.
- Falsch benannte Argumente: Fehlt ein Pflichtfeld und steht genau ein unbekanntes Feld da
  (z. B. "command" statt "id", "commands" statt "steps"), benennt die Brücke es um. Gilt auch
  für Objekte in Listen (Schritte eines Batches).
- BRIDGE_ALIASES="alias=original,…": doppelte Werkzeuge ausblenden. Ein Alias verschwindet aus
  tools/list, wenn sein Original da ist; Aufrufe darauf funktionieren weiter. Spart Kontext und
  verhindert, dass ein Modell die Argumente der beiden Varianten verwechselt.
- Ist BRIDGE_TOKEN gesetzt, braucht jede Anfrage an /mcp "Authorization: Bearer <token>",
  sonst 401. Die App selbst bekommt BRIDGE_TOKEN nicht. /health bleibt ohne Token.
- Beendet sich die App, beendet sich auch die Brücke, run.sh startet beide neu.
"""
from __future__ import annotations

import hmac
import itertools
from collections import OrderedDict
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TIMEOUT = float(os.environ.get("BRIDGE_TIMEOUT", "900"))   # Sekunden je Request
MAX_BODY = int(os.environ.get("BRIDGE_MAX_BODY", str(64 * 1024 * 1024)))
PATH = "/mcp"
ALIASE = dict(p.split("=", 1) for p in os.environ.pop("BRIDGE_ALIASES", "").replace(" ", "").split(",") if "=" in p)
TOKEN = os.environ.pop("BRIDGE_TOKEN", "").strip()   # pop: nicht an die App vererben


def log(msg: str) -> None:
    print(f"[bridge] {msg}", file=sys.stderr, flush=True)


def fehler(rid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def _typen(schema: dict) -> set[str]:
    t = schema.get("type")
    typen = set(t if isinstance(t, list) else [t] if t else [])
    for alt in schema.get("anyOf", []) + schema.get("oneOf", []):
        if isinstance(alt, dict):
            typen |= _typen(alt)
    return typen


def _anpassen(wert, schema: dict):
    """Gibt (neuer Wert, Beschreibung) zurück oder (wert, None), wenn nichts zu tun ist."""
    typen = _typen(schema)
    if not typen or wert is None:
        return wert, None
    ist = {str: "string", bool: "boolean", int: "integer", float: "number", list: "array", dict: "object"}.get(type(wert))
    if ist in typen or (ist == "integer" and "number" in typen):
        return wert, None
    if isinstance(wert, str):
        w = wert.strip()
        if "array" in typen:
            if w.startswith("["):
                try:
                    v = json.loads(w)
                    if isinstance(v, list):
                        return v, "Text → Liste (JSON)"
                except json.JSONDecodeError:
                    pass
            teile = [x.strip() for x in w.replace(";", ",").split(",") if x.strip()]
            items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
            if _typen(items) & {"integer", "number"}:
                try:
                    teile = [int(x) if x.lstrip("-").isdigit() else float(x) for x in teile]
                except ValueError:
                    return wert, None
            return teile, "Text → Liste"
        if "object" in typen and w.startswith("{"):
            try:
                v = json.loads(w)
                if isinstance(v, dict):
                    return v, "Text → Objekt (JSON)"
            except json.JSONDecodeError:
                pass
        if "integer" in typen and w.lstrip("-").isdigit():
            return int(w), "Text → Zahl"
        if "number" in typen:
            try:
                return float(w.replace(",", ".")), "Text → Zahl"
            except ValueError:
                pass
        if "boolean" in typen and w.lower() in ("true", "false"):
            return w.lower() == "true", "Text → Wahrheitswert"
        return wert, None
    if "array" in typen and not isinstance(wert, (list, dict)):
        return [wert], "Einzelwert → Liste"
    if "string" in typen and isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return str(wert), "Zahl → Text"
    if "integer" in typen and isinstance(wert, float) and wert.is_integer():
        return int(wert), "Kommazahl → Ganzzahl"
    return wert, None


def _umbenennen(args: dict, schema: dict) -> tuple[dict, list[str]]:
    """Ein unbekanntes Feld auf das einzige fehlende Pflichtfeld umbenennen, wenn eindeutig."""
    props = schema.get("properties") or {}
    if not props:
        return args, []
    fehlend = [k for k in schema.get("required") or [] if k not in args]
    fremd = [k for k in args if k not in props]
    if len(fehlend) == 1 and len(fremd) == 1:
        neu = {k: v for k, v in args.items() if k != fremd[0]}
        neu[fehlend[0]] = args[fremd[0]]
        return neu, [f"{fremd[0]} → {fehlend[0]}"]
    return args, []


class App:
    """Der stdio-MCP-Server der App mit Zuordnung von Antworten zu Requests."""

    def __init__(self, cmd: list[str]):
        self.cmd = cmd
        self.proc: subprocess.Popen | None = None
        self.start_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.init_lock = threading.Lock()
        self.pending: dict[int, queue.Queue] = {}
        self.pending_lock = threading.Lock()
        self.ids = itertools.count(1)
        self.init_result: dict | None = None
        self.schemas: dict[str, dict] = {}
        # Rückfragen: Sitzung -> kann Rückfragen; laufende Stream-Aufrufe; weitergereichte Rückfragen
        self.sitzungen: OrderedDict[str, bool] = OrderedDict()
        self.kanaele: dict[int, dict] = {}
        self.weiter: dict[str, tuple] = {}

    def ensure(self) -> None:
        with self.start_lock:
            if self.proc is not None:
                return
            log(f"starte {' '.join(self.cmd)}")
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0
            )
            threading.Thread(target=self._lesen, daemon=True).start()

    def _senden(self, msg: dict) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode()
        with self.write_lock:
            assert self.proc and self.proc.stdin
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def _lesen(self) -> None:
        assert self.proc and self.proc.stdout
        for zeile in self.proc.stdout:
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                daten = json.loads(zeile)
            except json.JSONDecodeError:
                log(f"keine JSON-Zeile von der App: {zeile[:200]!r}")
                continue
            for msg in daten if isinstance(daten, list) else [daten]:
                self._verteilen(msg)
        code = self.proc.wait()
        log(f"App beendet (Code {code}), Brücke beendet sich")
        os._exit(1)

    def _verteilen(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        if "method" in msg:
            # Anfrage der App an den Client: nur elicitation wird an einen Client weitergereicht.
            if "id" in msg:
                self._rueckfrage(msg)
            return  # Benachrichtigungen (Fortschritt, Logs) verwerfen
        with self.pending_lock:
            q = self.pending.pop(msg.get("id"), None)
        if q is not None:
            q.put(("antwort", msg))

    def _rueckfrage(self, msg: dict) -> None:
        """elicitation/create der App an den einen laufenden Stream-Aufruf weitergeben."""
        if msg.get("method") != "elicitation/create":
            self._senden(fehler(msg["id"], -32601, "Vom Client nicht unterstützt"))
            return
        with self.pending_lock:
            kanaele = list(self.kanaele.values())
            if len(kanaele) != 1:
                grund = ("kein Client mit Rückfrage-Unterstützung verbunden" if not kanaele
                         else "mehrere laufende Aufrufe, Rückfrage nicht eindeutig zuzuordnen")
                self._senden(fehler(msg["id"], -32601, f"Rückfrage nicht möglich: {grund}"))
                log(f"Rückfrage abgelehnt: {grund}")
                return
            kanal = kanaele[0]
            bid = "rueckfrage-" + uuid.uuid4().hex
            self.weiter[bid] = (msg["id"], kanal)
        log("Rückfrage an den Client weitergereicht")
        kanal["q"].put(("anfrage", {**msg, "id": bid}))

    def rueckfrage_antwort(self, msg: dict, sitzung: str | None) -> None:
        """Antwort eines Clients (POST) auf eine weitergereichte Rückfrage an die App zurückgeben."""
        with self.pending_lock:
            eintrag = self.weiter.get(msg.get("id"))
            if eintrag is None:
                return
            app_id, kanal = eintrag
            if kanal["sitzung"] != sitzung:
                log("Antwort auf Rückfrage aus anderer Sitzung verworfen")
                return
            del self.weiter[msg["id"]]
        self._senden({"jsonrpc": "2.0", "id": app_id,
                      **{k: msg[k] for k in ("result", "error") if k in msg}})

    def sitzung_merken(self, sitzung: str, msg: dict) -> None:
        caps = ((msg.get("params") or {}).get("capabilities") or {}) if isinstance(msg, dict) else {}
        with self.pending_lock:
            self.sitzungen[sitzung] = isinstance(caps, dict) and "elicitation" in caps
            while len(self.sitzungen) > 500:
                self.sitzungen.popitem(last=False)

    def kann_rueckfragen(self, sitzung: str | None) -> bool:
        with self.pending_lock:
            return bool(sitzung) and self.sitzungen.get(sitzung, False)

    def anfrage(self, msg: dict) -> dict:
        """Schickt einen Request an die App und wartet auf die Antwort."""
        self.ensure()
        intern = next(self.ids)
        q: queue.Queue = queue.Queue()
        with self.pending_lock:
            self.pending[intern] = q
        self._senden({**msg, "id": intern})
        try:
            _, antwort = q.get(timeout=TIMEOUT)
        except queue.Empty:
            with self.pending_lock:
                self.pending.pop(intern, None)
            return fehler(msg["id"], -32603, f"Keine Antwort der App nach {TIMEOUT:.0f} s")
        return {**antwort, "id": msg["id"]}

    def anfrage_strom(self, msg: dict, sitzung: str):
        """Wie anfrage, liefert aber auch Rückfragen der App: ("anfrage"|"antwort"|"keepalive", msg)."""
        self.ensure()
        intern = next(self.ids)
        q: queue.Queue = queue.Queue()
        kanal = {"q": q, "sitzung": sitzung}
        with self.pending_lock:
            self.pending[intern] = q
            self.kanaele[intern] = kanal
        self._senden({**msg, "id": intern})
        frist = time.monotonic() + TIMEOUT
        try:
            while True:
                rest = frist - time.monotonic()
                if rest <= 0:
                    yield "antwort", fehler(msg["id"], -32603, f"Keine Antwort der App nach {TIMEOUT:.0f} s")
                    return
                try:
                    art, m = q.get(timeout=min(15.0, rest))
                except queue.Empty:
                    yield "keepalive", None
                    continue
                if art == "antwort":
                    yield "antwort", {**m, "id": msg["id"]}
                    return
                frist = time.monotonic() + TIMEOUT   # eine Person entscheidet: Frist neu
                yield "anfrage", m
        finally:
            with self.pending_lock:
                self.pending.pop(intern, None)
                self.kanaele.pop(intern, None)
                offen = [(b, e[0]) for b, e in self.weiter.items() if e[1] is kanal]
                for b, _ in offen:
                    del self.weiter[b]
            for _, app_id in offen:   # Client weg, Rückfrage offen: App nicht ewig warten lassen
                self._senden(fehler(app_id, -32603, "Client getrennt, Rückfrage nicht beantwortet"))

    def initialisieren(self, msg: dict) -> dict:
        with self.init_lock:
            if self.init_result is None:
                # Die Brücke kann Rückfragen weiterreichen: der App immer "elicitation" melden.
                params = dict(msg.get("params") or {})
                caps = dict(params.get("capabilities") or {})
                caps.setdefault("elicitation", {})
                antwort = self.anfrage({**msg, "params": {**params, "capabilities": caps}})
                if "result" not in antwort:
                    return antwort
                self.init_result = antwort["result"]
                self._senden({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return {"jsonrpc": "2.0", "id": msg["id"], "result": self.init_result}

    def vorbereiten(self, msg: dict) -> tuple[dict, dict | None]:
        """Initialisierung nachholen und Argumente anpassen: (msg, fehler oder None)."""
        if self.init_result is None:
            # Client ohne eigenes initialize (z. B. nach Neustart der Brücke): nachholen.
            init = self.initialisieren({
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "artcraft-bridge", "version": "1"}},
            })
            if "result" not in init:
                return msg, fehler(msg["id"], -32603, "App ließ sich nicht initialisieren")
        if msg.get("method") == "tools/call":
            msg = self._argumente_anpassen(msg)
        return msg, None

    def verarbeiten(self, msg, sitzung: str | None = None) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return fehler(None, -32600, "Ungültiger JSON-RPC-Request")
        methode = msg.get("method")
        if methode is None:
            if "id" in msg and ("result" in msg or "error" in msg):
                self.rueckfrage_antwort(msg, sitzung)
            return None  # Antworten und Benachrichtigungen des Clients: nichts weiterzugeben
        if "id" not in msg:
            return None
        if methode == "initialize":
            if sitzung:
                self.sitzung_merken(sitzung, msg)
            return self.initialisieren(msg)
        msg, f = self.vorbereiten(msg)
        if f:
            return f
        antwort = self.anfrage(msg)
        if methode == "tools/list":
            self._schemas_merken(antwort)
            antwort = self._aliase_ausblenden(antwort)
        return antwort

    def _aliase_ausblenden(self, antwort: dict) -> dict:
        tools = (antwort.get("result") or {}).get("tools")
        if not ALIASE or not isinstance(tools, list):
            return antwort
        namen = {t.get("name") for t in tools if isinstance(t, dict)}
        weg = {a for a, o in ALIASE.items() if a in namen and o in namen}
        if not weg:
            return antwort
        return {**antwort, "result": {**antwort["result"], "tools": [t for t in tools if t.get("name") not in weg]}}

    def _schemas_merken(self, antwort: dict) -> None:
        for t in (antwort.get("result") or {}).get("tools") or []:
            if isinstance(t, dict) and isinstance(t.get("inputSchema"), dict):
                self.schemas[t.get("name")] = t["inputSchema"]

    def _argumente_anpassen(self, msg: dict) -> dict:
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        name, args = params.get("name"), params.get("arguments")
        if not isinstance(args, dict) or not args:
            return msg
        if name not in self.schemas:
            self._schemas_merken(self.anfrage({"jsonrpc": "2.0", "id": "schemas", "method": "tools/list"}))
        schema = self.schemas.get(name) or {}
        props = schema.get("properties") or {}
        neu, geaendert = _umbenennen(dict(args), schema)
        for k, v in list(neu.items()):
            if isinstance(props.get(k), dict):
                neu[k], was = _anpassen(v, props[k])
                if was:
                    geaendert.append(f"{k} ({was})")
                # Objekte in Listen (z. B. Schritte eines Batches): Namen und Typen je Eintrag
                items = props[k].get("items") if isinstance(props[k].get("items"), dict) else {}
                if isinstance(neu[k], list) and items.get("properties"):
                    liste, umb = [], set()
                    for e in neu[k]:
                        if isinstance(e, dict):
                            e, u = _umbenennen(e, items)
                            umb.update(u)
                            for kk, vv in list(e.items()):
                                if isinstance(items["properties"].get(kk), dict):
                                    e[kk], w = _anpassen(vv, items["properties"][kk])
                                    if w:
                                        umb.add(f"{kk} ({w})")
                        liste.append(e)
                    neu[k] = liste
                    geaendert += [f"{k}[].{x}" for x in sorted(umb)]
        if not geaendert:
            return msg
        log(f"Argumente angepasst für {name}: {', '.join(geaendert)}")
        return {**msg, "params": {**params, "arguments": neu}}


class Handler(BaseHTTPRequestHandler):
    app: App
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keine Zeile je Request
        pass

    def _antwort(self, code: int, body: bytes = b"", typ: str | None = None, extra=None):
        self.send_response(code)
        if typ:
            self.send_header("Content-Type", typ)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _pruefen(self) -> bool:
        # Body immer lesen, sonst bricht die Verbindung bei abgelehnten Requests ab.
        # Pro Request neu: bei Keep-alive bedient dieselbe Handler-Instanz mehrere Requests.
        self._body, self._laenge = None, 0
        if self.command == "POST":
            self._laenge = int(self.headers.get("Content-Length") or 0)
            if 0 < self._laenge <= MAX_BODY:
                self._body = self.rfile.read(self._laenge)
            elif self._laenge > MAX_BODY:
                self.close_connection = True  # Body nicht gelesen, Verbindung nicht weiterverwenden
        if self.headers.get("Origin"):
            self._antwort(403, b"Origin nicht erlaubt\n", "text/plain; charset=utf-8")
            return False
        if TOKEN:
            gesendet = self.headers.get("Authorization", "")
            erwartet = f"Bearer {TOKEN}"
            if not hmac.compare_digest(gesendet.encode(), erwartet.encode()):
                self._antwort(401, b"Token fehlt oder falsch\n", "text/plain; charset=utf-8",
                              {"WWW-Authenticate": 'Bearer realm="mcp"'})
                return False
        if self.path.split("?", 1)[0] != PATH:
            self._antwort(404, b"Nicht gefunden, Pfad ist /mcp\n", "text/plain; charset=utf-8")
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            self._antwort(200, b"ok\n", "text/plain")
            return
        if not self._pruefen():
            return
        # Leerer SSE-Kanal für Nachrichten vom Server: hält nur offen (Keepalive alle 15 s).
        # Mit 405 versuchen manche Clients (MCP-SDK 2.x) jede Sekunde neu zu verbinden.
        if "text/event-stream" not in self.headers.get("Accept", ""):
            self._antwort(405, extra={"Allow": "POST, DELETE"})
            return
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                time.sleep(15)
        except OSError:
            pass  # Client hat getrennt

    def do_DELETE(self):
        if self._pruefen():
            self._antwort(200)

    def do_POST(self):
        if not self._pruefen():
            return
        if self._body is None:
            self.close_connection = True
            self._antwort(413 if self._laenge > MAX_BODY else 400)
            return
        try:
            daten = json.loads(self._body)
        except json.JSONDecodeError:
            self._antwort(400, json.dumps(fehler(None, -32700, "Parse error")).encode(),
                          "application/json")
            return

        batch = isinstance(daten, list)
        sitzung = (self.headers.get("Mcp-Session-Id") or "").strip() or None
        extra = {}
        if not batch and isinstance(daten, dict) and daten.get("method") == "initialize":
            sitzung = uuid.uuid4().hex
            extra["Mcp-Session-Id"] = sitzung
        elif (not batch and isinstance(daten, dict) and daten.get("method") == "tools/call" and "id" in daten
              and daten.get("jsonrpc") == "2.0" and "text/event-stream" in self.headers.get("Accept", "")
              and self.app.kann_rueckfragen(sitzung)):
            self._strom(daten, sitzung)
            return
        antworten = [a for a in (self.app.verarbeiten(m, sitzung) for m in (daten if batch else [daten]))
                     if a is not None]
        if not antworten:
            self._antwort(202)
            return
        body = json.dumps(antworten if batch else antworten[0], ensure_ascii=False).encode()
        self._antwort(200, body, "application/json", extra)

    def _strom(self, msg: dict, sitzung: str) -> None:
        """tools/call als SSE-Stream: Rückfragen der App und am Ende die Antwort."""
        msg, f = self.app.vorbereiten(msg)
        if f:
            self._antwort(200, json.dumps(f, ensure_ascii=False).encode(), "application/json")
            return
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        strom = self.app.anfrage_strom(msg, sitzung)
        try:
            for art, m in strom:
                if art == "keepalive":
                    self.wfile.write(b": keepalive\n\n")
                else:
                    self.wfile.write(b"event: message\ndata: " + json.dumps(m, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()
                if art == "antwort":
                    break
        except OSError:
            pass  # Client hat getrennt; offene Rückfragen schließt anfrage_strom
        finally:
            strom.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return  # Client hat die Verbindung geschlossen
        log(f"Fehler bei Request von {client_address[0]}: {sys.exc_info()[1]!r}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 3 or args[1] != "--":
        sys.exit("Aufruf: mcp_bridge.py <port> -- <befehl> [argumente ...]")
    port, cmd = int(args[0]), args[2:]
    Handler.app = App(cmd)
    server = Server(("0.0.0.0", port), Handler)
    log(f"lauscht auf :{port}{PATH} ({'mit Token' if TOKEN else 'ohne Token'}), App startet beim ersten Request")
    server.serve_forever()


if __name__ == "__main__":
    main()
