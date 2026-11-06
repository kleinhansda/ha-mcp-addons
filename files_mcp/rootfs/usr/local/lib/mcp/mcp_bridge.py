#!/usr/bin/env python3
"""Brücke stdio → MCP Streamable HTTP, ohne Anmeldung. Nur für das interne Docker-Netz.

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
- Anfragen mit Origin-Header (Browser) werden abgelehnt, Schutz gegen DNS-Rebinding.
- Beendet sich die App, beendet sich auch die Brücke, run.sh startet beide neu.
"""
from __future__ import annotations

import itertools
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


def log(msg: str) -> None:
    print(f"[bridge] {msg}", file=sys.stderr, flush=True)


def fehler(rid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


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
            # Anfrage der App an den Client (sampling, roots, elicitation): nicht unterstützt.
            if "id" in msg:
                self._senden(fehler(msg["id"], -32601, "Vom Client nicht unterstützt"))
            return  # Benachrichtigungen (Fortschritt, Logs) verwerfen
        with self.pending_lock:
            q = self.pending.pop(msg.get("id"), None)
        if q is not None:
            q.put(msg)

    def anfrage(self, msg: dict) -> dict:
        """Schickt einen Request an die App und wartet auf die Antwort."""
        self.ensure()
        intern = next(self.ids)
        q: queue.Queue = queue.Queue(maxsize=1)
        with self.pending_lock:
            self.pending[intern] = q
        self._senden({**msg, "id": intern})
        try:
            antwort = q.get(timeout=TIMEOUT)
        except queue.Empty:
            with self.pending_lock:
                self.pending.pop(intern, None)
            return fehler(msg["id"], -32603, f"Keine Antwort der App nach {TIMEOUT:.0f} s")
        return {**antwort, "id": msg["id"]}

    def initialisieren(self, msg: dict) -> dict:
        with self.init_lock:
            if self.init_result is None:
                antwort = self.anfrage(msg)
                if "result" not in antwort:
                    return antwort
                self.init_result = antwort["result"]
                self._senden({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return {"jsonrpc": "2.0", "id": msg["id"], "result": self.init_result}

    def verarbeiten(self, msg) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return fehler(None, -32600, "Ungültiger JSON-RPC-Request")
        methode = msg.get("method")
        if methode is None or "id" not in msg:
            return None  # Antworten und Benachrichtigungen des Clients: nichts weiterzugeben
        if methode == "initialize":
            return self.initialisieren(msg)
        if self.init_result is None:
            # Client ohne eigenes initialize (z. B. nach Neustart der Brücke): nachholen.
            init = self.initialisieren({
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "artcraft-bridge", "version": "1"}},
            })
            if "result" not in init:
                return fehler(msg["id"], -32603, "App ließ sich nicht initialisieren")
        return self.anfrage(msg)


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
        antworten = [a for a in (self.app.verarbeiten(m) for m in (daten if batch else [daten]))
                     if a is not None]
        if not antworten:
            self._antwort(202)
            return
        extra = {}
        if not batch and isinstance(daten, dict) and daten.get("method") == "initialize":
            extra["Mcp-Session-Id"] = uuid.uuid4().hex
        body = json.dumps(antworten if batch else antworten[0], ensure_ascii=False).encode()
        self._antwort(200, body, "application/json", extra)


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
    log(f"lauscht auf :{port}{PATH}, App startet beim ersten Request")
    server.serve_forever()


if __name__ == "__main__":
    main()
