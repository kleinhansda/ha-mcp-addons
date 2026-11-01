"""Trägt SearXNG und Open Terminal in die Datenbank von Open WebUI ein.

Open WebUI liest Umgebungsvariablen nur als Vorgabe für Schlüssel, die noch nicht in
der Tabelle "config" stehen. Bei einer bestehenden Datenbank (Neustart, Übernahme)
schreibt dieses Skript deshalb vor dem Start genau diese Schlüssel:

- web.search.*: Engine searxng mit der internen URL (nur wenn SEARXNG_QUERY_URL gesetzt)
- terminal_server.connections: ein Eintrag mit der id "ha-open-terminal". Andere
  Einträge bleiben unberührt, Freigaben (config.access_grants) und "enabled" des
  eigenen Eintrags ebenfalls. Ohne Schlüssel wird der eigene Eintrag entfernt.

Aufruf: python3 provision.py <webui.db>; Werte kommen aus der Umgebung.
"""
import json
import os
import sqlite3
import sys
import time

TERMINAL_ID = "ha-open-terminal"


def log(msg):
    print(f"[open-webui-app] {msg}", flush=True)


def main(db_path):
    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("pragma table_info(config)")}
    if not {"key", "value"} <= cols:
        log("Datenbank hat noch das alte Format, Vorgaben wirken über Umgebungsvariablen. Nach dem ersten Start einmal neu starten.")
        return

    def get(key):
        row = con.execute("select value from config where key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row and row[0] is not None else None

    def put(key, value):
        con.execute(
            "insert into config (key, value, updated_at) values (?, ?, ?) "
            "on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), int(time.time())),
        )

    query_url = os.environ.get("SEARXNG_QUERY_URL", "")
    if query_url:
        put("web.search.enable", True)
        put("web.search.engine", "searxng")
        put("web.search.searxng_query_url", query_url)
        log("Web-Suche: SearXNG eingetragen")

    url = os.environ.get("APP_TERMINAL_URL", "")
    key = os.environ.get("APP_TERMINAL_KEY", "")
    conns = get("terminal_server.connections") or []
    if not isinstance(conns, list):
        conns = []
    mine = next((c for c in conns if isinstance(c, dict) and c.get("id") == TERMINAL_ID), None)
    others = [c for c in conns if c is not mine]
    if key and url:
        entry = dict(mine or {"id": TERMINAL_ID, "name": "Open Terminal", "enabled": True, "config": {}})
        entry.update({"url": url, "path": "/openapi.json", "key": key, "auth_type": "bearer"})
        put("terminal_server.connections", others + [entry])
        log(f"Open Terminal eingetragen: {url}")
    elif mine is not None:
        put("terminal_server.connections", others)
        log("Open Terminal ausgetragen (kein Schlüssel gesetzt)")

    con.commit()
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
