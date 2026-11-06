#!/usr/bin/env python3
"""MCP-Server (stdio) für Paperless-ngx: Dokumente suchen, lesen, ansehen und (optional) pflegen.

Spricht die REST-API von Paperless-ngx mit einem API-Token. Nur Standardbibliothek.

Umgebung:
  PAPERLESS_URL         interne Adresse, z. B. http://ca5234a0-paperless-ngx
  PAPERLESS_TOKEN       API-Token (Paperless: Profil → API-Token)
  PAPERLESS_PUBLIC_URL  optional, Adresse der Weboberfläche für Links in Antworten
  PAPERLESS_READ_ONLY   true = nur lesende Werkzeuge anbieten (Standard)
  PAPERLESS_UPLOAD_ROOT Ordner, aus dem paperless_upload Dateien nehmen darf (Standard /share)
  PAPERLESS_MAX_BYTES   Grenze für hochgeladene Dateien (Standard 50 MB)

Paperless wird erst beim ersten Werkzeugaufruf angesprochen, nicht beim Start.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PROTOCOL = "2025-06-18"
VERSION = "1.0"
BASE = os.environ.get("PAPERLESS_URL", "http://ca5234a0-paperless-ngx").rstrip("/")
TOKEN = os.environ.get("PAPERLESS_TOKEN", "")
PUBLIC = os.environ.get("PAPERLESS_PUBLIC_URL", "").rstrip("/")
READ_ONLY = os.environ.get("PAPERLESS_READ_ONLY", "true").lower() != "false"
UPLOAD_ROOT = Path(os.environ.get("PAPERLESS_UPLOAD_ROOT", "/share")).resolve()
MAX_BYTES = int(os.environ.get("PAPERLESS_MAX_BYTES", 50 * 1024 * 1024))
TIMEOUT = 60
CACHE_SEK = 300
ARTEN = {
    "tags": "tags",
    "correspondents": "correspondents",
    "document_types": "document_types",
    "storage_paths": "storage_paths",
    "custom_fields": "custom_fields",
}


class Fehler(Exception):
    pass


# --------------------------------------------------------------------------- HTTP


def anfrage(methode: str, pfad: str, params: dict | None = None, daten: bytes | None = None,
            typ: str | None = None, roh: bool = False):
    if not TOKEN:
        raise Fehler("Kein API-Token eingetragen (Option paperless_token).")
    url = BASE + pfad
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
    kopf = {"Authorization": f"Token {TOKEN}", "Accept": "application/json"}
    if typ:
        kopf["Content-Type"] = typ
    req = urllib.request.Request(url, data=daten, headers=kopf, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            inhalt = r.read()
            if roh:
                return inhalt, r.headers.get("Content-Type", "application/octet-stream")
            return json.loads(inhalt) if inhalt else {}
    except urllib.error.HTTPError as e:
        text = e.read()[:500].decode("utf-8", "replace")
        if e.code in (401, 403):
            raise Fehler(f"Paperless lehnt ab ({e.code}): Token prüfen oder Rechte des Nutzers. {text}")
        if e.code == 404:
            raise Fehler("Nicht gefunden (falsche ID?)")
        raise Fehler(f"Paperless-Fehler {e.code}: {text}")
    except urllib.error.URLError as e:
        raise Fehler(f"Paperless unter {BASE} nicht erreichbar: {e.reason}")


def json_senden(methode: str, pfad: str, obj: dict):
    return anfrage(methode, pfad, daten=json.dumps(obj).encode(), typ="application/json")


# --------------------------------------------------------------------------- Namen ↔ IDs

_cache: dict[str, tuple[float, dict[int, dict]]] = {}


def objekte(art: str, frisch: bool = False) -> dict[int, dict]:
    jetzt = time.time()
    if not frisch and art in _cache and jetzt - _cache[art][0] < CACHE_SEK:
        return _cache[art][1]
    out: dict[int, dict] = {}
    seite = 1
    while True:
        r = anfrage("GET", f"/api/{art}/", {"page": seite, "page_size": 250})
        for o in r.get("results", []):
            out[o["id"]] = o
        if not r.get("next"):
            break
        seite += 1
    _cache[art] = (jetzt, out)
    return out


def name(art: str, id_) -> str | None:
    if id_ is None:
        return None
    o = objekte(art).get(id_)
    return o["name"] if o else f"#{id_}"


def ids(art: str, werte, anlegen: bool = False) -> list[int]:
    """Namen (ohne Groß-/Kleinschreibung) oder IDs in IDs übersetzen."""
    if werte in (None, "", []):
        return []
    if isinstance(werte, (str, int)):
        werte = [w.strip() for w in str(werte).split(",")] if isinstance(werte, str) else [werte]
    alle = objekte(art)
    out = []
    for w in werte:
        if isinstance(w, int) or (isinstance(w, str) and w.isdigit()):
            out.append(int(w))
            continue
        treffer = [o["id"] for o in alle.values() if o["name"].lower() == str(w).lower()]
        if not treffer:
            treffer = [o["id"] for o in alle.values() if str(w).lower() in o["name"].lower()]
        if len(treffer) == 1:
            out.append(treffer[0])
        elif len(treffer) > 1:
            namen = ", ".join(sorted(alle[i]["name"] for i in treffer)[:10])
            raise Fehler(f"„{w}“ ist mehrdeutig ({namen}). Genauen Namen oder ID angeben.")
        elif anlegen:
            neu = json_senden("POST", f"/api/{art}/", {"name": str(w)})
            _cache.pop(art, None)
            out.append(neu["id"])
        else:
            raise Fehler(f"„{w}“ gibt es nicht ({art}). paperless_list zeigt die vorhandenen.")
    return out


def eine_id(art: str, wert) -> int | None:
    r = ids(art, wert)
    return r[0] if r else None


# --------------------------------------------------------------------------- Ausgabe


def link(doc_id: int) -> str | None:
    return f"{PUBLIC}/documents/{doc_id}/details" if PUBLIC else None


def kurz(d: dict) -> dict:
    out = {
        "id": d["id"],
        "title": d.get("title"),
        "created": (d.get("created") or d.get("created_date") or "")[:10] or None,
        "correspondent": name("correspondents", d.get("correspondent")),
        "document_type": name("document_types", d.get("document_type")),
        "tags": [name("tags", t) for t in d.get("tags") or []],
        "asn": d.get("archive_serial_number"),
        "file": d.get("original_file_name"),
    }
    if d.get("page_count"):
        out["pages"] = d["page_count"]
    if link(d["id"]):
        out["url"] = link(d["id"])
    hit = d.get("__search_hit__")
    if hit:
        out["score"] = round(hit.get("score") or 0, 3)
        if hit.get("highlights"):
            out["highlights"] = hit["highlights"]
        if hit.get("note_highlights"):
            out["note_highlights"] = hit["note_highlights"]
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def text(obj) -> list:
    return [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)}]


def datum(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    if len(s) == 4 and s.isdigit():
        return s + "-01-01"
    return s[:10]


# --------------------------------------------------------------------------- Werkzeuge


def paperless_search(a: dict) -> list:
    p: dict = {"page_size": min(int(a.get("limit") or 10), 50), "page": int(a.get("page") or 1),
               "truncate_content": "true"}
    q = (a.get("query") or "").strip()
    if q:
        p["query"] = q
    else:
        p["ordering"] = a.get("ordering") or "-created"
    if a.get("title_contains"):
        p["title__icontains"] = a["title_contains"]
    if a.get("tags"):
        p["tags__id__all"] = ",".join(map(str, ids("tags", a["tags"])))
    if a.get("exclude_tags"):
        p["tags__id__none"] = ",".join(map(str, ids("tags", a["exclude_tags"])))
    if a.get("correspondent"):
        p["correspondent__id__in"] = ",".join(map(str, ids("correspondents", a["correspondent"])))
    if a.get("document_type"):
        p["document_type__id__in"] = ",".join(map(str, ids("document_types", a["document_type"])))
    if a.get("created_from"):
        p["created__date__gte"] = datum(a["created_from"])
    if a.get("created_to"):
        bis = datum(a["created_to"])
        if bis and len(str(a["created_to"]).strip()) == 4:
            bis = f"{a['created_to']}-12-31"
        p["created__date__lte"] = bis
    if a.get("added_from"):
        p["added__date__gte"] = datum(a["added_from"])
    if a.get("asn") not in (None, ""):
        p["archive_serial_number"] = int(a["asn"])
    r = anfrage("GET", "/api/documents/", p)
    treffer = [kurz(d) for d in r.get("results", [])]
    out = {"count": r.get("count", len(treffer)), "page": p["page"], "results": treffer}
    if r.get("next"):
        out["next_page"] = p["page"] + 1
    if not treffer:
        out["hint"] = ("Keine Treffer. Weniger oder andere Begriffe probieren, Filter lockern, "
                       "oder Wortanfänge mit * (rechn*) suchen.")
    return text(out)


def paperless_get_document(a: dict) -> list:
    doc_id = int(a["id"])
    d = anfrage("GET", f"/api/documents/{doc_id}/")
    out = kurz(d)
    out["added"] = (d.get("added") or "")[:10] or None
    if d.get("storage_path"):
        out["storage_path"] = name("storage_paths", d["storage_path"])
    felder = []
    for cf in d.get("custom_fields") or []:
        f = objekte("custom_fields").get(cf.get("field"), {})
        felder.append({"name": f.get("name", f"#{cf.get('field')}"), "value": cf.get("value")})
    if felder:
        out["custom_fields"] = felder
    notizen = d.get("notes") or []
    if notizen:
        out["notes"] = [{"created": (n.get("created") or "")[:16], "note": n.get("note")} for n in notizen]
    inhalt = d.get("content") or ""
    off = max(int(a.get("offset") or 0), 0)
    lim = min(max(int(a.get("max_chars") or 20000), 500), 100000)
    teil = inhalt[off:off + lim]
    out["content_chars"] = len(inhalt)
    if off + lim < len(inhalt):
        out["content_next_offset"] = off + lim
    if not inhalt.strip():
        out["content_hint"] = "Kein OCR-Text vorhanden, paperless_preview zeigt die Seite als Bild."
    return text(out) + ([{"type": "text", "text": teil}] if teil else [])


def paperless_preview(a: dict) -> list:
    doc_id = int(a["id"])
    daten, typ = anfrage("GET", f"/api/documents/{doc_id}/thumb/", roh=True)
    if not typ.startswith("image/"):
        raise Fehler(f"Unerwartete Vorschau ({typ})")
    return [{"type": "image", "data": base64.b64encode(daten).decode(), "mimeType": typ.split(";")[0]},
            {"type": "text", "text": f"Vorschau (erste Seite) von Dokument {doc_id}."
             + (f" Original: {link(doc_id)}" if link(doc_id) else "")}]


def paperless_similar(a: dict) -> list:
    doc_id = int(a["id"])
    r = anfrage("GET", "/api/documents/", {"more_like_id": doc_id, "page_size": min(int(a.get("limit") or 10), 30),
                                           "truncate_content": "true"})
    return text({"similar_to": doc_id, "results": [kurz(d) for d in r.get("results", []) if d["id"] != doc_id]})


def paperless_list(a: dict) -> list:
    art = a.get("kind") or "tags"
    if art not in ARTEN:
        raise Fehler(f"kind muss eines von {', '.join(ARTEN)} sein")
    alle = objekte(ARTEN[art], frisch=True).values()
    filt = (a.get("contains") or "").lower()
    zeilen = []
    for o in sorted(alle, key=lambda o: o["name"].lower()):
        if filt and filt not in o["name"].lower():
            continue
        z = {"id": o["id"], "name": o["name"]}
        if "document_count" in o:
            z["documents"] = o["document_count"]
        if art == "custom_fields":
            z["type"] = o.get("data_type")
        if art == "tags" and o.get("is_inbox_tag"):
            z["inbox"] = True
        if art == "storage_paths":
            z["path"] = o.get("path")
        zeilen.append(z)
    return text({"kind": art, "count": len(zeilen), "items": zeilen})


def paperless_update_document(a: dict) -> list:
    doc_id = int(a["id"])
    d = anfrage("GET", f"/api/documents/{doc_id}/")
    neu: dict = {}
    if a.get("title"):
        neu["title"] = a["title"]
    if a.get("created"):
        neu["created"] = datum(a["created"])
    if "correspondent" in a:
        neu["correspondent"] = eine_id("correspondents", a["correspondent"]) if a["correspondent"] else None
    if "document_type" in a:
        neu["document_type"] = eine_id("document_types", a["document_type"]) if a["document_type"] else None
    if "asn" in a:
        neu["archive_serial_number"] = int(a["asn"]) if a["asn"] not in (None, "") else None
    tags = list(d.get("tags") or [])
    plus = ids("tags", a.get("add_tags"), anlegen=bool(a.get("create_missing_tags")))
    minus = ids("tags", a.get("remove_tags"))
    if plus or minus:
        neu["tags"] = [t for t in tags if t not in minus] + [t for t in plus if t not in tags]
    if not neu:
        raise Fehler("Nichts zu ändern angegeben.")
    r = json_senden("PATCH", f"/api/documents/{doc_id}/", neu)
    return text({"updated": kurz(r), "changed": sorted(neu)})


def paperless_add_note(a: dict) -> list:
    doc_id = int(a["id"])
    notiz = (a.get("note") or "").strip()
    if not notiz:
        raise Fehler("note ist leer")
    json_senden("POST", f"/api/documents/{doc_id}/notes/", {"note": notiz})
    return text({"id": doc_id, "note_added": notiz})


def multipart(felder: list[tuple[str, str]], datei: tuple[str, str, bytes]) -> tuple[bytes, str]:
    grenze = uuid.uuid4().hex
    teile = []
    for k, v in felder:
        teile.append(f'--{grenze}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    fname, typ, inhalt = datei
    fname_sicher = fname.replace('"', "")
    teile.append(f'--{grenze}\r\nContent-Disposition: form-data; name="document"; filename="{fname_sicher}"\r\n'
                 f"Content-Type: {typ}\r\n\r\n".encode() + inhalt + b"\r\n")
    teile.append(f"--{grenze}--\r\n".encode())
    return b"".join(teile), f"multipart/form-data; boundary={grenze}"


def paperless_upload(a: dict) -> list:
    if a.get("path"):
        p = Path(str(a["path"])).resolve()
        if p != UPLOAD_ROOT and UPLOAD_ROOT not in p.parents:
            raise Fehler(f"Pfad muss unter {UPLOAD_ROOT} liegen")
        if not p.is_file():
            raise Fehler(f"Datei nicht gefunden: {p}")
        if p.stat().st_size > MAX_BYTES:
            raise Fehler(f"Datei größer als {MAX_BYTES // (1024 * 1024)} MB")
        inhalt, fname = p.read_bytes(), p.name
    elif a.get("content_base64"):
        inhalt = base64.b64decode(a["content_base64"], validate=False)
        fname = a.get("filename") or "upload.pdf"
        if len(inhalt) > MAX_BYTES:
            raise Fehler(f"Inhalt größer als {MAX_BYTES // (1024 * 1024)} MB")
    else:
        raise Fehler("path oder content_base64 angeben")
    typ = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    felder: list[tuple[str, str]] = []
    if a.get("title"):
        felder.append(("title", a["title"]))
    if a.get("created"):
        felder.append(("created", datum(a["created"]) or ""))
    if a.get("correspondent"):
        felder.append(("correspondent", str(eine_id("correspondents", a["correspondent"]))))
    if a.get("document_type"):
        felder.append(("document_type", str(eine_id("document_types", a["document_type"]))))
    for t in ids("tags", a.get("tags")):
        felder.append(("tags", str(t)))
    body, ctype = multipart(felder, (fname, typ, inhalt))
    r = anfrage("POST", "/api/documents/post_document/", daten=body, typ=ctype)
    return text({"queued": fname, "task_id": r,
                 "hint": "Paperless verarbeitet die Datei im Hintergrund (OCR). In ein bis zwei Minuten mit paperless_search finden."})


# --------------------------------------------------------------------------- Beschreibung


def _p(beschreibung: str, typ: str = "string", **extra) -> dict:
    return {"type": typ, "description": beschreibung, **extra}


ID = _p("Dokument-ID", "integer")
LISTE = {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": ["string", "integer"]}}],
         "description": "Namen oder IDs, als Liste oder kommagetrennt"}
TOOLS = [
    ("paperless_search", False,
     "Sucht Dokumente im Paperless-Archiv (Rechnungen, Verträge, Bescheide, Briefe …). query ist Volltext über OCR-Text, "
     "Titel, Tags und Notizen; unterstützt Wörter, \"Phrasen\", Wortanfang* , AND/OR/NOT und Feldsuche wie "
     "correspondent:vodafone oder created:[2024 to 2025]. Filter (Tags, Korrespondent, Typ, Datum) nehmen Namen. "
     "Ohne query: neueste zuerst. Liefert ID, Titel, Datum, Korrespondent, Tags und Textauszüge (highlights). "
     "Den vollen Text holt paperless_get_document.",
     {"query": _p("Volltext-Suche"), "tags": {**LISTE, "description": "Alle diese Tags (Namen oder IDs)"},
      "exclude_tags": {**LISTE, "description": "Keines dieser Tags"},
      "correspondent": {**LISTE, "description": "Korrespondent(en)"}, "document_type": {**LISTE, "description": "Dokumenttyp(en)"},
      "created_from": _p("Ausstellungsdatum ab (YYYY-MM-DD oder Jahr)"), "created_to": _p("Ausstellungsdatum bis (YYYY-MM-DD oder Jahr)"),
      "added_from": _p("Hinzugefügt ab (YYYY-MM-DD)"), "title_contains": _p("Titel enthält"),
      "asn": _p("Archiv-Seriennummer", "integer"),
      "ordering": _p("Ohne query: Sortierung, z. B. -created (Standard), created, title, -added"),
      "limit": _p("Treffer je Seite (Standard 10, max 50)", "integer"), "page": _p("Seite, ab 1", "integer")}, []),
    ("paperless_get_document", False,
     "Holt ein Dokument mit allen Metadaten, Notizen, benutzerdefinierten Feldern und dem OCR-Text. Lange Texte in Teilen "
     "über offset/max_chars (content_next_offset in der Antwort).",
     {"id": ID, "offset": _p("Startzeichen im Text", "integer"),
      "max_chars": _p("Höchstens so viele Zeichen Text (Standard 20000)", "integer")}, ["id"]),
    ("paperless_preview", False, "Zeigt die erste Seite eines Dokuments als Bild (Vorschau), z. B. wenn der OCR-Text fehlt oder "
     "Layout, Unterschrift oder Logo wichtig sind.", {"id": ID}, ["id"]),
    ("paperless_similar", False, "Findet inhaltlich ähnliche Dokumente zu einem Dokument.",
     {"id": ID, "limit": _p("Höchstens so viele (Standard 10)", "integer")}, ["id"]),
    ("paperless_list", False, "Listet Tags, Korrespondenten, Dokumenttypen, Speicherpfade oder benutzerdefinierte Felder mit "
     "Anzahl Dokumenten. Nützlich, um die richtigen Namen für Filter zu finden.",
     {"kind": _p("Art", enum=list(ARTEN)), "contains": _p("Name enthält")}, ["kind"]),
    ("paperless_update_document", True, "Ändert Metadaten eines Dokuments: Titel, Datum, Korrespondent, Dokumenttyp, ASN, Tags "
     "hinzufügen/entfernen. Der Inhalt und die Datei bleiben unverändert. Vorher mit paperless_get_document prüfen.",
     {"id": ID, "title": _p("Neuer Titel"), "created": _p("Ausstellungsdatum YYYY-MM-DD"),
      "correspondent": _p("Korrespondent (Name oder ID, leer = entfernen)"),
      "document_type": _p("Dokumenttyp (Name oder ID, leer = entfernen)"), "asn": _p("Archiv-Seriennummer", "integer"),
      "add_tags": {**LISTE, "description": "Tags hinzufügen"}, "remove_tags": {**LISTE, "description": "Tags entfernen"},
      "create_missing_tags": _p("Nicht vorhandene Tags aus add_tags anlegen", "boolean")}, ["id"]),
    ("paperless_add_note", True, "Hängt eine Notiz an ein Dokument (z. B. „bezahlt am …“, „Frist …“).",
     {"id": ID, "note": _p("Text der Notiz")}, ["id", "note"]),
    ("paperless_upload", True, "Legt ein neues Dokument in Paperless ab, aus einer Datei unter /share (path) oder als base64. "
     "Paperless macht OCR und Zuordnung im Hintergrund.",
     {"path": _p("Datei unter /share, z. B. /share/artcraft/work/out/scan.pdf"), "content_base64": _p("Inhalt base64"),
      "filename": _p("Dateiname bei base64, z. B. rechnung.pdf"), "title": _p("Titel"), "created": _p("Datum YYYY-MM-DD"),
      "correspondent": _p("Korrespondent (Name oder ID)"), "document_type": _p("Dokumenttyp (Name oder ID)"),
      "tags": {**LISTE, "description": "Tags (müssen existieren)"}}, []),
]
HANDLER = {
    "paperless_search": paperless_search, "paperless_get_document": paperless_get_document,
    "paperless_preview": paperless_preview, "paperless_similar": paperless_similar, "paperless_list": paperless_list,
    "paperless_update_document": paperless_update_document, "paperless_add_note": paperless_add_note,
    "paperless_upload": paperless_upload,
}


def tool_liste() -> list[dict]:
    out = []
    for name_, schreibt, beschr, props, req in TOOLS:
        if schreibt and READ_ONLY:
            continue
        schema = {"type": "object", "properties": props}
        if req:
            schema["required"] = req
        out.append({"name": name_, "description": beschr, "inputSchema": schema,
                    "annotations": {"readOnlyHint": not schreibt, "destructiveHint": False,
                                    "idempotentHint": not schreibt, "openWorldHint": False}})
    return out


# --------------------------------------------------------------------------- Protokoll


def antwort(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def verarbeite(msg: dict) -> None:
    methode = msg.get("method")
    id_ = msg.get("id")
    if id_ is None:
        return
    if methode == "initialize":
        antwort(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "paperless", "title": "Paperless-ngx", "version": VERSION},
                      "instructions": "Dokumentenarchiv (Paperless-ngx). Erst paperless_search, dann paperless_get_document "
                                      "für den vollen Text. Antworten mit Dokument-ID und Titel belegen."})
    elif methode == "ping":
        antwort(id_, {})
    elif methode == "tools/list":
        antwort(id_, {"tools": tool_liste()})
    elif methode == "tools/call":
        params = msg.get("params") or {}
        name_ = params.get("name")
        fn = HANDLER.get(name_)
        if fn is None or (READ_ONLY and any(t[0] == name_ and t[1] for t in TOOLS)):
            antwort(id_, error={"code": -32602, "message": f"Unbekanntes Tool: {name_}"})
            return
        try:
            antwort(id_, {"content": fn(params.get("arguments") or {})})
        except Fehler as e:
            antwort(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except (ValueError, TypeError, KeyError) as e:
            antwort(id_, {"content": [{"type": "text", "text": f"Ungültige Angabe: {e}"}], "isError": True})
        except OSError as e:
            antwort(id_, {"content": [{"type": "text", "text": f"Fehler: {e}"}], "isError": True})
    else:
        antwort(id_, error={"code": -32601, "message": "Methode nicht unterstützt"})


def main() -> None:
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
