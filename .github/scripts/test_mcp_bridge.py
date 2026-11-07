#!/usr/bin/env python3
"""Tests für common/mcp_bridge.py: Token, Weitergabe der Umgebung, Nachsicht bei Argumenten.

  python3 .github/scripts/test_mcp_bridge.py common/mcp_bridge.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BRIDGE = Path(sys.argv[1]).resolve()

# Minimaler stdio-MCP-Server: ein Werkzeug "echo", gibt Argumente und BRIDGE_TOKEN-Sichtbarkeit zurück.
PROBE = r'''
import json, os, sys
SCHEMA = {"type": "object", "properties": {
    "to": {"type": "array", "items": {"type": "string"}},
    "limit": {"type": "integer"}, "flag": {"type": "boolean"}, "text": {"type": "string"}},
    "required": ["to"]}
RUN = {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string"}, "params": {"type": "object"}}, "required": ["id"]}
BATCH = {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "object", "additionalProperties": False,
         "properties": {"id": {"type": "string"}, "params": {"type": "object"}}, "required": ["id"]}}}, "required": ["steps"]}
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1"}}
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": "echo", "description": "", "inputSchema": SCHEMA},
                       {"name": "command_run", "description": "", "inputSchema": RUN},
                       {"name": "run_command", "description": "", "inputSchema": RUN},
                       {"name": "command_batch", "description": "", "inputSchema": BATCH},
                       {"name": "ui_screenshot", "description": "", "inputSchema": {"type": "object"}}]}
    else:
        r = {"content": [{"type": "text", "text": json.dumps({"args": m["params"]["arguments"],
             "token_sichtbar": "BRIDGE_TOKEN" in os.environ})}]}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
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


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "probe.py").write_text(PROBE)
    port = freier_port()
    env = {**os.environ, "BRIDGE_TOKEN": "geheim",
           "BRIDGE_ALIASES": "command_run=run_command,ui_screenshot=screenshot"}
    p = subprocess.Popen([sys.executable, str(BRIDGE), str(port), "--", sys.executable, str(tmp / "probe.py")],
                         env=env, stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)

    def post(msg, auth="Bearer geheim"):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if auth is not None:
            h["Authorization"] = auth
        try:
            with urllib.request.urlopen(urllib.request.Request(url, json.dumps(msg).encode(), h), timeout=10) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    check(post(init, None)[0] == 401, "ohne Token: 401")
    check(post(init, "Bearer falsch")[0] == 401, "falsches Token: 401")
    check(post(init)[0] == 200, "richtiges Token: 200")

    def call(args, name="echo"):
        s, b = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return json.loads(b["result"]["content"][0]["text"])

    # Ohne vorheriges tools/list: Brücke holt das Schema selbst
    r = call({"to": "a@b.de, c@d.de", "limit": "5", "flag": "true", "text": 7})
    check(r["args"] == {"to": ["a@b.de", "c@d.de"], "limit": 5, "flag": True, "text": "7"}, "Text → Liste, Zahl, Wahrheitswert, Zahl → Text")
    check(r["token_sichtbar"] is False, "App sieht BRIDGE_TOKEN nicht")
    r = call({"to": ["x@y.de"], "limit": 3})
    check(r["args"] == {"to": ["x@y.de"], "limit": 3}, "korrekte Argumente unverändert")
    r = call({"to": "x@y.de", "limit": "viele"})
    check(r["args"] == {"to": ["x@y.de"], "limit": "viele"}, "Unklares bleibt, wie es ist")
    r = call({"command": "file.new", "params": '{"width": 800}'}, "command_run")
    check(r["args"] == {"id": "file.new", "params": {"width": 800}}, "Umbenennen: command → id, params als JSON-Text")
    r = call({"commands": [{"command": "file.new", "params": '{"a": 1}'}, {"id": "x"}]}, "command_batch")
    check(r["args"] == {"steps": [{"id": "file.new", "params": {"a": 1}}, {"id": "x"}]}, "Batch: commands → steps, Schritte umbenannt")
    s, b = post({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    namen = [t["name"] for t in b["result"]["tools"]]
    check("command_run" not in namen and "run_command" in namen, "Alias mit Original ausgeblendet")
    check("ui_screenshot" in namen, "Alias ohne Original bleibt")
    r = call({"id": "y"}, "command_run")
    check(r["args"] == {"id": "y"}, "Ausgeblendeter Alias bleibt aufrufbar")
    p.terminate()
    log = p.communicate(timeout=5)[1]
    check("Argumente angepasst für echo: to (Text → Liste)" in log and "a@b.de" not in log, "Protokoll nennt Feld, nicht Wert")
    print(f"\n{ok} Prüfungen bestanden")


if __name__ == "__main__":
    main()
