#!/usr/bin/env python3
"""Tests für paperless_mcp.py gegen eine kleine nachgebaute Paperless-API.

  python3 paperless_mcp/tests/test_paperless_mcp.py paperless_mcp/rootfs/usr/local/lib/mcp/paperless_mcp.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SERVER = Path(sys.argv[1]).resolve()
TOKEN = "geheim"

TAGS = [{"id": 1, "name": "Rechnung", "document_count": 2, "is_inbox_tag": False},
        {"id": 2, "name": "Inbox", "document_count": 1, "is_inbox_tag": True},
        {"id": 3, "name": "Steuer 2024", "document_count": 1}]
CORR = [{"id": 10, "name": "Vodafone", "document_count": 1}, {"id": 11, "name": "Stadtwerke", "document_count": 1}]
TYPES = [{"id": 20, "name": "Rechnung", "document_count": 2}]
FIELDS = [{"id": 30, "name": "Betrag", "data_type": "monetary"}]
DOCS = {
    5: {"id": 5, "title": "Vodafone Rechnung März", "created": "2024-03-02", "added": "2024-03-05T10:00:00Z",
        "correspondent": 10, "document_type": 20, "tags": [1, 3], "archive_serial_number": 42,
        "original_file_name": "scan.pdf", "page_count": 2, "content": "Rechnungsbetrag 39,99 EUR " + "x" * 3000,
        "custom_fields": [{"field": 30, "value": "EUR39.99"}], "notes": [{"created": "2024-03-06T09:00", "note": "bezahlt"}]},
    6: {"id": 6, "title": "Stadtwerke Abschlag", "created": "2025-01-10", "correspondent": 11, "document_type": 20,
        "tags": [1, 2], "content": ""},
}
LOG: list[tuple[str, str, dict, bytes]] = []
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")


class Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def senden(self, code, obj=None, roh=None, typ="application/json"):
        body = roh if roh is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def auth(self):
        if self.headers.get("Authorization") != f"Token {TOKEN}":
            self.senden(401, {"detail": "Invalid token."})
            return False
        return True

    def liste(self, items):
        return {"count": len(items), "next": None, "results": items}

    def do_GET(self):
        if not self.auth():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        LOG.append(("GET", u.path, q, b""))
        p = u.path
        if p == "/api/tags/":
            return self.senden(200, self.liste(TAGS))
        if p == "/api/correspondents/":
            return self.senden(200, self.liste(CORR))
        if p == "/api/document_types/":
            return self.senden(200, self.liste(TYPES))
        if p in ("/api/storage_paths/",):
            return self.senden(200, self.liste([]))
        if p == "/api/custom_fields/":
            return self.senden(200, self.liste(FIELDS))
        if p == "/api/documents/":
            docs = list(DOCS.values())
            if "query" in q:
                docs = [dict(d, __search_hit__={"score": 0.9, "highlights": "<span>Rechnung</span>sbetrag"})
                        for d in docs if q["query"].lower().rstrip("*") in (d["title"] + d["content"]).lower()]
            if "tags__id__all" in q:
                need = {int(x) for x in q["tags__id__all"].split(",")}
                docs = [d for d in docs if need <= set(d["tags"])]
            if "more_like_id" in q:
                docs = list(DOCS.values())
            return self.senden(200, self.liste(docs))
        if p.startswith("/api/documents/") and p.endswith("/thumb/"):
            return self.senden(200, roh=PNG, typ="image/png")
        if p.startswith("/api/documents/"):
            d = DOCS.get(int(p.split("/")[3]))
            return self.senden(200, d) if d else self.senden(404, {"detail": "Not found."})
        self.senden(404, {})

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_PATCH(self):
        if not self.auth():
            return
        b = self.body()
        LOG.append(("PATCH", self.path, {}, b))
        d = DOCS[int(self.path.split("/")[3])]
        d.update(json.loads(b))
        self.senden(200, d)

    def do_POST(self):
        if not self.auth():
            return
        b = self.body()
        LOG.append(("POST", self.path, {}, b))
        if self.path == "/api/tags/":
            t = {"id": 99, "name": json.loads(b)["name"], "document_count": 0}
            TAGS.append(t)
            return self.senden(201, t)
        if self.path.endswith("/notes/"):
            return self.senden(200, [])
        if self.path == "/api/documents/post_document/":
            return self.senden(200, "task-123")
        self.senden(404, {})


class Client:
    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, "-I", str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env={**os.environ, **env})
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def call(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return r

    def daten(self, name, **args):
        r = self.call(name, **args)
        assert not r.get("isError"), r
        return json.loads(r["content"][0]["text"]), r

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


ok = 0


def check(bedingung, was):
    global ok
    if not bedingung:
        raise AssertionError(was)
    ok += 1
    print("ok   ", was)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    tmp = Path(tempfile.mkdtemp())
    (tmp / "neu.pdf").write_bytes(b"%PDF-1.4 test")
    env = {"PAPERLESS_URL": base, "PAPERLESS_TOKEN": TOKEN, "PAPERLESS_PUBLIC_URL": "https://paper.example",
           "PAPERLESS_UPLOAD_ROOT": str(tmp)}

    # Nur lesen (Standard)
    c = Client(env)
    init = c.rpc("initialize")["result"]
    check(init["serverInfo"]["name"] == "paperless", "initialize")
    namen = [t["name"] for t in c.rpc("tools/list")["result"]["tools"]]
    check(namen == ["paperless_search", "paperless_get_document", "paperless_preview", "paperless_similar", "paperless_list"],
          "Nur lesen: nur lesende Werkzeuge")
    r = c.rpc("tools/call", {"name": "paperless_update_document", "arguments": {"id": 5, "title": "x"}})
    check("error" in r and DOCS[5]["title"] != "x", "Nur lesen: schreibendes Werkzeug abgewiesen")

    d, _ = c.daten("paperless_search", query="rechnung")
    erster = d["results"][0]
    check(d["count"] == 1 and erster["id"] == 5, "Volltextsuche findet Dokument")
    check(erster["correspondent"] == "Vodafone" and erster["tags"] == ["Rechnung", "Steuer 2024"], "IDs werden zu Namen")
    check(erster["url"] == "https://paper.example/documents/5/details" and "highlights" in erster, "Link und Auszug")

    d, _ = c.daten("paperless_search", tags="inbox", created_from="2025", created_to="2025")
    q = [e for e in LOG if e[1] == "/api/documents/"][-1][2]
    check(q.get("tags__id__all") == "2" and q.get("created__date__gte") == "2025-01-01"
          and q.get("created__date__lte") == "2025-12-31" and q.get("ordering") == "-created",
          "Filter: Tag-Name, Jahr als Zeitraum, Sortierung ohne query")
    check([x["id"] for x in d["results"]] == [6], "Filter nach Tag")

    r = c.call("paperless_search", tags="Gibtsnicht")
    check(r.get("isError") and "gibt es nicht" in r["content"][0]["text"], "Unbekannter Tag: klare Meldung")
    r = c.call("paperless_search", tags="e")
    check(r.get("isError") and "mehrdeutig" in r["content"][0]["text"], "Mehrdeutiger Name: klare Meldung")

    d, r = c.daten("paperless_get_document", id=5, max_chars=500)
    check(d["custom_fields"] == [{"name": "Betrag", "value": "EUR39.99"}] and d["notes"][0]["note"] == "bezahlt",
          "Dokument: Felder und Notizen")
    check(d["content_next_offset"] == 500 and len(r["content"][1]["text"]) == 500, "Dokument: Text in Teilen")
    d, r = c.daten("paperless_get_document", id=6)
    check("content_hint" in d and len(r["content"]) == 1, "Dokument ohne OCR-Text: Hinweis auf Vorschau")
    r = c.call("paperless_get_document", id=77)
    check(r.get("isError") and "Nicht gefunden" in r["content"][0]["text"], "Unbekannte ID")

    r = c.call("paperless_preview", id=5)
    check(r["content"][0]["type"] == "image" and r["content"][0]["mimeType"] == "image/png", "Vorschau als Bild")
    d, _ = c.daten("paperless_similar", id=5)
    check([x["id"] for x in d["results"]] == [6], "Ähnliche ohne das Dokument selbst")
    d, _ = c.daten("paperless_list", kind="tags", contains="in")
    check(d["items"] == [{"id": 2, "name": "Inbox", "documents": 1, "inbox": True}], "Liste mit Filter")
    c.close()

    # Falsches Token
    c = Client({**env, "PAPERLESS_TOKEN": "falsch"})
    c.rpc("initialize")
    r = c.call("paperless_list", kind="tags")
    check(r.get("isError") and "Token" in r["content"][0]["text"], "Falsches Token: klare Meldung")
    c.close()

    # Schreiben
    c = Client({**env, "PAPERLESS_READ_ONLY": "false"})
    c.rpc("initialize")
    check(len(c.rpc("tools/list")["result"]["tools"]) == 8, "Schreibmodus: 8 Werkzeuge")
    d, _ = c.daten("paperless_update_document", id=6, title="Abschlag Januar", add_tags=["Steuer 2024", "Neu"],
                   remove_tags="Inbox", create_missing_tags=True, correspondent="Stadtwerke")
    patch = json.loads([e for e in LOG if e[0] == "PATCH"][-1][3])
    check(patch["tags"] == [1, 3, 99] and patch["title"] == "Abschlag Januar" and patch["correspondent"] == 11,
          "Tags hinzufügen/entfernen/anlegen, Titel, Korrespondent")
    d, _ = c.daten("paperless_add_note", id=5, note="Frist 30.4.")
    check(json.loads([e for e in LOG if e[1].endswith("/notes/")][-1][3]) == {"note": "Frist 30.4."}, "Notiz")
    d, _ = c.daten("paperless_upload", path=str(tmp / "neu.pdf"), title="Neu", tags="Rechnung")
    body = [e for e in LOG if e[1] == "/api/documents/post_document/"][-1][3]
    check(d["task_id"] == "task-123" and b'filename="neu.pdf"' in body and b"%PDF-1.4 test" in body
          and b'name="tags"\r\n\r\n1' in body, "Upload aus Ordner als multipart")
    r = c.call("paperless_upload", path="/etc/passwd")
    check(r.get("isError") and "unter" in r["content"][0]["text"], "Upload außerhalb des erlaubten Ordners abgewiesen")
    c.close()
    srv.shutdown()
    print(f"\n{ok} Prüfungen bestanden")


if __name__ == "__main__":
    main()
