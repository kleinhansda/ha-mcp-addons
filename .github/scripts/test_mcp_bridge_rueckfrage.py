#!/usr/bin/env python3
"""Tests für Rückfragen (elicitation) durch common/mcp_bridge.py.

  python3 .github/scripts/test_mcp_bridge_rueckfrage.py common/mcp_bridge.py

Ein Test-Server fragt bei tools/call "frage" über elicitation/create nach und antwortet erst,
wenn die Antwort des Clients da ist. Geprüft wird: Weitergabe über den SSE-Stream, Antwort per
POST zurück an die App, Fähigkeit gegenüber der App, Clients ohne Fähigkeit, fremde Sitzung,
getrennter Client, mehrere gleichzeitige Aufrufe.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BRIDGE = Path(sys.argv[1]).resolve()

PROBE = r'''
import json, sys
init = {}
offen = {}   # Rückfrage-ID der App -> ursprüngliche Request-ID
n = 0
def out(m):
    print(json.dumps(m), flush=True)
for line in sys.stdin:
    m = json.loads(line)
    if "method" not in m:          # Antwort des Clients auf eine Rückfrage
        rid = offen.pop(m.get("id"), None)
        if rid is not None:
            out({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(
                {"antwort": m.get("result"), "fehler": m.get("error")})}]}})
        continue
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        init = m["params"]
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": "2025-06-18",
             "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1"}}})
    elif m["method"] == "tools/list":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [
            {"name": "frage", "inputSchema": {"type": "object"}},
            {"name": "caps", "inputSchema": {"type": "object"}}]}})
    elif m["params"]["name"] == "caps":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"content": [{"type": "text", "text": json.dumps(init.get("capabilities"))}]}})
    else:
        n += 1
        eid = f"e{n}"
        offen[eid] = m["id"]
        out({"jsonrpc": "2.0", "id": eid, "method": "elicitation/create",
             "params": {"message": "Mail senden?", "requestedSchema": {"type": "object", "properties": {}}}})
'''

ok = 0


def check(bed, was):
    global ok
    if not bed:
        raise AssertionError(was)
    ok += 1
    print("ok   ", was)


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, port: int, elicitation: bool):
        self.port = port
        r, h = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"},
            "capabilities": {"elicitation": {}} if elicitation else {}}}, sitzung=None)
        self.sitzung = h.get("Mcp-Session-Id")

    def post(self, msg, sitzung="__self__", accept="application/json, text/event-stream"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        kopf = {"Content-Type": "application/json", "Accept": accept, "Authorization": "Bearer geheim"}
        s = self.sitzung if sitzung == "__self__" else sitzung
        if s:
            kopf["Mcp-Session-Id"] = s
        c.request("POST", "/mcp", json.dumps(msg), kopf)
        r = c.getresponse()
        return r, dict(r.getheaders())

    def aufruf(self, name="frage", rid=7):
        return self.post({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": {}}})


def ereignisse(r):
    """Liest SSE-Ereignisse (data-Zeilen) einzeln aus einer offenen Antwort."""
    daten = []
    while True:
        z = r.fp.readline()
        if not z:
            return
        z = z.decode().rstrip("\n")
        if z.startswith("data: "):
            daten.append(z[6:])
        elif z == "" and daten:
            yield json.loads("\n".join(daten))
            daten = []


def text(msg):
    return json.loads(msg["result"]["content"][0]["text"])


def main():
    port = freier_port()
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "probe.py"
        probe.write_text(PROBE)
        env = {**os.environ, "BRIDGE_TOKEN": "geheim"}
        proc = subprocess.Popen([sys.executable, str(BRIDGE), str(port), "--", sys.executable, str(probe)],
                                env=env, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)

            # Erster Client meldet KEINE Rückfragen an: die App bekommt die Fähigkeit trotzdem.
            ohne = Client(port, elicitation=False)
            r, h = ohne.aufruf("caps", 2)
            check("application/json" in h.get("Content-Type", ""), "ohne Fähigkeit: normale JSON-Antwort")
            check(text(json.loads(r.read())) == {"elicitation": {}}, "App sieht elicitation, obwohl der erste Client sie nicht meldet")

            r, h = ohne.aufruf("frage", 3)
            erg = text(json.loads(r.read()))
            check(erg["fehler"] and erg["fehler"]["code"] == -32601, "ohne Fähigkeit: Rückfrage abgelehnt, App bekommt Fehler")

            # Client mit Fähigkeit: Rückfrage kommt über den Stream, Antwort geht zurück.
            mit = Client(port, elicitation=True)
            check(bool(mit.sitzung), "initialize liefert Mcp-Session-Id")
            r, h = mit.aufruf("frage", 4)
            check("text/event-stream" in h.get("Content-Type", ""), "mit Fähigkeit: tools/call als SSE-Stream")
            ev = ereignisse(r)
            frage = next(ev)
            check(frage.get("method") == "elicitation/create" and str(frage["id"]).startswith("rueckfrage-"),
                  "Rückfrage kommt mit eigener ID über den Stream")
            check(frage["params"]["message"] == "Mail senden?", "Inhalt der Rückfrage unverändert")

            # Antwort aus fremder Sitzung wird verworfen
            fremd = Client(port, elicitation=True)
            r2, _ = fremd.post({"jsonrpc": "2.0", "id": frage["id"], "result": {"action": "accept", "content": {}}})
            check(r2.status == 202, "fremde Sitzung: 202, aber ...")
            # richtige Sitzung
            r3, _ = mit.post({"jsonrpc": "2.0", "id": frage["id"], "result": {"action": "accept", "content": {"ok": True}}})
            check(r3.status == 202, "Antwort per POST: 202")
            ende = next(ev)
            check(ende.get("id") == 4, "Ende des Streams trägt die ursprüngliche Request-ID")
            check(text(ende)["antwort"] == {"action": "accept", "content": {"ok": True}},
                  "... nur die Antwort aus der eigenen Sitzung kommt bei der App an")

            # Client trennt während offener Rückfrage: App bekommt Fehler statt ewig zu warten
            r, _ = mit.aufruf("frage", 5)
            ev = ereignisse(r)
            next(ev)
            r.close()
            time.sleep(0.5)
            r, _ = ohne.aufruf("caps", 6)   # Brücke lebt weiter
            check(r.status == 200, "nach getrenntem Client arbeitet die Brücke weiter")
            r.read()

            # Zwei gleichzeitige Stream-Aufrufe: Rückfrage nicht eindeutig -> abgelehnt
            a, b = Client(port, True), Client(port, True)
            ergebnisse = {}

            def lauf(c, rid):
                rr, _ = c.aufruf("frage", rid)
                for m in ereignisse(rr):
                    if "method" in m:
                        c.post({"jsonrpc": "2.0", "id": m["id"], "result": {"action": "decline"}})
                    else:
                        ergebnisse[rid] = text(m)
                        break
            t1 = threading.Thread(target=lauf, args=(a, 11))
            t2 = threading.Thread(target=lauf, args=(b, 12))
            # Erst beide Aufrufe offen halten: Rückfragen der App kommen nacheinander, die erste
            # trifft auf einen Kanal, wenn der zweite noch nicht da ist. Deshalb nur prüfen,
            # dass beide Aufrufe sauber enden und keine Antwort beim falschen Client landet.
            t1.start(); t2.start(); t1.join(20); t2.join(20)
            check(set(ergebnisse) == {11, 12}, "zwei gleichzeitige Aufrufe enden beide")
            check(all((e["antwort"] or {}).get("action") == "decline" or (e["fehler"] or {}).get("code") == -32601
                      for e in ergebnisse.values()), "jeder bekommt eigene Antwort oder eine Ablehnung")
        finally:
            proc.terminate()
            log = proc.communicate(timeout=5)[1]
    check("Rückfrage an den Client weitergereicht" in log, "Log nennt die Weitergabe")
    print(f"\n{ok} Prüfungen bestanden")


if __name__ == "__main__":
    main()
