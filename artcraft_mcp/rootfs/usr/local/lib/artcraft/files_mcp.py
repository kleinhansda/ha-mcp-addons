#!/usr/bin/env python3
"""Kleiner MCP-Server (stdio) für den Arbeitsordner: Dateien auflisten, holen, ablegen.

Gedacht für Claude in der Cloud, das die Ergebnisse der ArtCraft-Apps (PhotoCraft usw.)
sonst nur über einen Umweg erreicht. Nur Standardbibliothek.

Aufruf: files_mcp.py <arbeitsordner>

Sicherheit:
- Alle Pfade werden relativ zum Arbeitsordner aufgelöst und nach realpath geprüft
  (kein "..", keine Symlinks nach draußen).
- file_get und file_put sind auf MAX_BYTES begrenzt.
- file_put überschreibt nur mit overwrite=true.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
from pathlib import Path

PROTOCOL = "2025-06-18"
MAX_BYTES = int(os.environ.get("FILES_MAX_BYTES", 10 * 1024 * 1024))
MAX_LIST = 500

mimetypes.add_type("image/webp", ".webp")

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

TOOLS = [
    {
        "name": "files_list",
        "description": (
            "Listet Dateien und Ordner im Arbeitsordner (relativ). "
            f"Höchstens {MAX_LIST} Einträge, mit Größe in Bytes und Änderungszeit (UTC)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Unterordner, leer = Arbeitsordner"},
                "recursive": {"type": "boolean", "description": "Auch Unterordner durchsuchen (Standard false)"},
            },
        },
    },
    {
        "name": "file_get",
        "description": (
            "Holt eine Datei aus dem Arbeitsordner als Binärinhalt (Resource mit Blob). "
            f"Höchstens {MAX_BYTES // (1024 * 1024)} MB."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Dateipfad relativ zum Arbeitsordner"}},
            "required": ["path"],
        },
    },
    {
        "name": "file_put",
        "description": (
            "Legt eine Datei im Arbeitsordner ab (Inhalt base64). Überschreibt nur mit overwrite=true. "
            f"Höchstens {MAX_BYTES // (1024 * 1024)} MB."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Zielpfad relativ zum Arbeitsordner"},
                "content_base64": {"type": "string"},
                "overwrite": {"type": "boolean", "description": "Vorhandene Datei überschreiben (Standard false)"},
            },
            "required": ["path", "content_base64"],
        },
    },
]


class Fehler(Exception):
    pass


def aufloesen(rel: str, muss_existieren: bool = True) -> Path:
    rel = (rel or "").strip().lstrip("/")
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise Fehler("Pfad liegt außerhalb des Arbeitsordners")
    if muss_existieren and not p.exists():
        raise Fehler(f"Nicht gefunden: {rel}")
    return p


def files_list(args: dict) -> list[dict]:
    base = aufloesen(args.get("path", ""))
    if not base.is_dir():
        raise Fehler("Kein Ordner")
    it = base.rglob("*") if args.get("recursive") else base.iterdir()
    zeilen = []
    for p in sorted(it):
        try:
            rp = p.resolve()
            if rp != ROOT and ROOT not in rp.parents:
                continue  # Symlink nach draußen
            st = p.stat()
        except OSError:
            continue
        ordner = p.is_dir()
        from datetime import datetime, timezone
        zeit = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        zeilen.append(f"{'d' if ordner else '-'} {0 if ordner else st.st_size:>10}  {zeit}  {p.relative_to(ROOT)}{'/' if ordner else ''}")
        if len(zeilen) >= MAX_LIST:
            zeilen.append(f"… auf {MAX_LIST} Einträge begrenzt")
            break
    return [{"type": "text", "text": "\n".join(zeilen) or "(leer)"}]


def file_get(args: dict) -> list[dict]:
    p = aufloesen(args.get("path", ""))
    if not p.is_file():
        raise Fehler("Keine Datei")
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise Fehler(f"Datei zu groß: {size} Bytes (Grenze {MAX_BYTES})")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    blob = base64.b64encode(p.read_bytes()).decode()
    return [
        {"type": "text", "text": f"{p.relative_to(ROOT)}: {size} Bytes, {mime}"},
        {"type": "resource", "resource": {"uri": f"file:///{p.relative_to(ROOT)}", "mimeType": mime, "blob": blob}},
    ]


def file_put(args: dict) -> list[dict]:
    p = aufloesen(args.get("path", ""), muss_existieren=False)
    if p == ROOT or p.is_dir():
        raise Fehler("Zielpfad ist ein Ordner")
    if p.exists() and not args.get("overwrite"):
        raise Fehler("Datei existiert, overwrite=true setzen, um sie zu ersetzen")
    try:
        daten = base64.b64decode(args.get("content_base64", ""), validate=True)
    except ValueError:
        raise Fehler("content_base64 ist kein gültiges base64")
    if len(daten) > MAX_BYTES:
        raise Fehler(f"Inhalt zu groß: {len(daten)} Bytes (Grenze {MAX_BYTES})")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_bytes(daten)
    os.replace(tmp, p)
    return [{"type": "text", "text": f"Geschrieben: {p.relative_to(ROOT)} ({len(daten)} Bytes)"}]


HANDLER = {"files_list": files_list, "file_get": file_get, "file_put": file_put}


def antwort(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def verarbeite(msg: dict) -> None:
    methode = msg.get("method")
    id_ = msg.get("id")
    if id_ is None:  # Notification
        return
    if methode == "initialize":
        antwort(id_, {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "artcraft-files", "version": "1.0"},
        })
    elif methode == "ping":
        antwort(id_, {})
    elif methode == "tools/list":
        antwort(id_, {"tools": TOOLS})
    elif methode == "tools/call":
        params = msg.get("params") or {}
        fn = HANDLER.get(params.get("name"))
        if fn is None:
            antwort(id_, error={"code": -32602, "message": "Unbekanntes Tool"})
            return
        try:
            antwort(id_, {"content": fn(params.get("arguments") or {})})
        except Fehler as e:
            antwort(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except OSError as e:
            antwort(id_, {"content": [{"type": "text", "text": f"Dateifehler: {e.strerror}"}], "isError": True})
    else:
        antwort(id_, error={"code": -32601, "message": "Methode nicht unterstützt"})


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for zeile in sys.stdin:
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            verarbeite(json.loads(zeile))
        except json.JSONDecodeError:
            antwort(None, error={"code": -32700, "message": "Ungültiges JSON"})


if __name__ == "__main__":
    main()
