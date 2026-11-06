#!/usr/bin/env python3
"""MCP-Server (stdio) für Dateien unter einem Wurzelordner.

Quelle: common/files_mcp.py. Kopien liegen in files_mcp und artcraft_mcp, der Build prüft,
dass sie identisch sind (.github/scripts/sync_common.py).

Aufruf: files_mcp.py <wurzelordner>

Umgebung:
  FILES_READ_ONLY=true      nur lesende Werkzeuge anbieten
  FILES_PROTECTED=a,b       Ordner-/Dateinamen, in denen nicht geschrieben wird
                            (Standard: .obsidian,.stfolder,.stversions,.git)
  FILES_MAX_BYTES=n         Grenze je Übertragung (Standard 10 MB)

Der Kern nutzt nur die Standardbibliothek. Optional, wenn installiert:
Pillow (Bild-Metadaten, Vorschau), pypdf (PDF-Metadaten), mutagen (Audio/Video),
pdftoppm aus poppler-utils (PDF-Vorschau). Fehlt etwas, sagt das Werkzeug das.

Sicherheit:
- Pfade relativ zur Wurzel, nach realpath geprüft (kein "..", keine Symlinks nach draußen).
- Geschrieben wird atomar (temporäre Datei, dann Umbenennen); Besitzer und Rechte einer
  geänderten Datei bleiben erhalten, neue Dateien bekommen den Besitzer des Ordners.
- Kein endgültiges Löschen: file_trash verschiebt nach .trash/ unter der Wurzel.
"""
from __future__ import annotations

import base64
import csv
import fnmatch
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

PROTOCOL = "2025-06-18"
VERSION = "2.0"
MAX_BYTES = int(os.environ.get("FILES_MAX_BYTES", 10 * 1024 * 1024))
MAX_LIST = 500
MAX_TEXT_CHARS = 200_000
MAX_SEARCH_FILE = 5 * 1024 * 1024
READ_ONLY = os.environ.get("FILES_READ_ONLY", "false").lower() == "true"
PROTECTED = {
    s.strip()
    for s in os.environ.get("FILES_PROTECTED", ".obsidian,.stfolder,.stversions,.git").split(",")
    if s.strip()
}
TRASH = ".trash"

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("text/markdown", ".md")

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


class Fehler(Exception):
    pass


# --------------------------------------------------------------------------- Pfade


def rel(p: Path) -> str:
    r = p.relative_to(ROOT).as_posix()
    return r if r != "." else ""


def aufloesen(pfad: str, muss_existieren: bool = True) -> Path:
    pfad = (pfad or "").strip()
    if pfad.startswith(str(ROOT) + "/"):
        pfad = pfad[len(str(ROOT)) + 1 :]  # absolute Angabe innerhalb der Wurzel zulassen
    pfad = pfad.lstrip("/")
    p = (ROOT / pfad).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise Fehler(f"Pfad liegt außerhalb von {ROOT}")
    if muss_existieren and not p.exists():
        raise Fehler(f"Nicht gefunden: {pfad}")
    return p


def schreibbar(p: Path) -> None:
    if READ_ONLY:
        raise Fehler("Nur-Lese-Modus")
    teile = set(p.relative_to(ROOT).parts)
    gesperrt = teile & PROTECTED
    if gesperrt:
        raise Fehler(f"Geschützter Pfad ({', '.join(sorted(gesperrt))}), hier wird nicht geschrieben")
    if p == ROOT:
        raise Fehler("Die Wurzel selbst kann nicht geändert werden")


def zeit(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def groesse(n: int) -> str:
    for einheit in ("B", "KB", "MB", "GB"):
        if n < 1024 or einheit == "GB":
            return f"{n:.0f} {einheit}" if einheit == "B" else f"{n:.1f} {einheit}"
        n /= 1024
    return str(n)


def besitz_uebernehmen(ziel: Path, vorbild: Path) -> None:
    """Besitzer (und bei Dateien die Rechte) vom Vorbild übernehmen; ohne root still."""
    try:
        st = vorbild.stat()
        if os.geteuid() == 0:
            os.chown(ziel, st.st_uid, st.st_gid)
        if vorbild.is_file():
            os.chmod(ziel, st.st_mode & 0o7777)
    except OSError:
        pass


def atomar_schreiben(p: Path, daten: bytes) -> None:
    vorhanden = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".part", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(daten)
        besitz_uebernehmen(Path(tmp), p if vorhanden else p.parent)
        if not vorhanden:
            os.chmod(tmp, 0o664)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def text_lesen(p: Path) -> tuple[str, str]:
    roh = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return roh.decode(enc), "utf-8"
        except UnicodeDecodeError:
            pass
    if b"\x00" in roh[:4096]:
        raise Fehler("Binärdatei, file_get verwenden")
    return roh.decode("cp1252", errors="replace"), "cp1252"


def ist_binaer(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            return b"\x00" in fh.read(4096)
    except OSError:
        return True


# --------------------------------------------------------------------------- Werkzeuge


def files_list(a: dict) -> list:
    base = aufloesen(a.get("path", ""))
    if not base.is_dir():
        raise Fehler("Kein Ordner")
    muster = a.get("pattern") or ""
    limit = min(int(a.get("limit") or MAX_LIST), MAX_LIST)
    eintraege = []
    it = base.rglob("*") if a.get("recursive") else base.iterdir()
    for p in it:
        if p.name == TRASH and p.parent == ROOT and not a.get("show_trash"):
            continue
        try:
            rp = p.resolve()
            if rp != ROOT and ROOT not in rp.parents:
                continue
            st = p.stat()
        except OSError:
            continue
        if muster and not fnmatch.fnmatch(p.name, muster):
            continue
        eintraege.append((p, st))
        if len(eintraege) >= 20 * MAX_LIST:
            break
    if a.get("sort") == "mtime":
        eintraege.sort(key=lambda e: e[1].st_mtime, reverse=True)
    else:
        eintraege.sort(key=lambda e: (not e[0].is_dir(), str(e[0]).lower()))
    zeilen = []
    for p, st in eintraege[:limit]:
        d = p.is_dir()
        zeilen.append(f"{'d' if d else '-'} {'' if d else groesse(st.st_size):>9}  {zeit(st.st_mtime)}  {rel(p)}{'/' if d else ''}")
    if len(eintraege) > limit:
        zeilen.append(f"… {len(eintraege) - limit} weitere, mit pattern oder path eingrenzen")
    return [{"type": "text", "text": "\n".join(zeilen) or "(leer)"}]


def file_info(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    st = p.stat()
    info: dict = {
        "pfad": rel(p),
        "typ": "ordner" if p.is_dir() else "datei",
        "geaendert": zeit(st.st_mtime),
    }
    if p.is_dir():
        kinder = list(p.iterdir())
        info["eintraege"] = len(kinder)
    else:
        info["groesse"] = st.st_size
        info["groesse_lesbar"] = groesse(st.st_size)
        info["mime"] = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if st.st_size <= 500 * 1024 * 1024:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            info["sha256"] = h.hexdigest()
        if a.get("details"):
            info["details"] = metadaten(p, info["mime"], a.get("gps") or "rough")
    return [{"type": "text", "text": json.dumps(info, ensure_ascii=False, indent=2, default=str)}]


def file_read_text(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    if not p.is_file():
        raise Fehler("Keine Datei")
    if p.stat().st_size > 50 * MAX_BYTES:
        raise Fehler("Datei zu groß zum Lesen als Text")
    text, enc = text_lesen(p)
    zeilen = text.splitlines()
    start = max(int(a.get("offset") or 1), 1)
    anzahl = max(int(a.get("limit") or 400), 1)
    teil = zeilen[start - 1 : start - 1 + anzahl]
    if a.get("line_numbers"):
        breite = len(str(start + len(teil)))
        inhalt = "\n".join(f"{start + i:>{breite}}│{z}" for i, z in enumerate(teil))
    else:
        inhalt = "\n".join(teil)
    if len(inhalt) > MAX_TEXT_CHARS:
        inhalt = inhalt[:MAX_TEXT_CHARS] + "\n… gekürzt, kleineres limit wählen"
    ende = start + len(teil) - 1
    kopf = f"{rel(p)} ({enc}), Zeilen {start}–{ende} von {len(zeilen)}"
    if ende < len(zeilen):
        kopf += f"; weiter mit offset={ende + 1}"
    return [{"type": "text", "text": kopf + "\n\n" + inhalt}]


def file_write_text(a: dict) -> list:
    p = aufloesen(a.get("path", ""), muss_existieren=False)
    schreibbar(p)
    if p.is_dir():
        raise Fehler("Zielpfad ist ein Ordner")
    modus = a.get("mode") or "create"
    inhalt = a.get("content")
    if not isinstance(inhalt, str):
        raise Fehler("content fehlt")
    if modus == "create" and p.exists():
        raise Fehler("Datei existiert. mode=overwrite (ersetzen) oder append (anhängen) wählen, oder file_edit")
    if modus == "append" and p.exists():
        alt, _ = text_lesen(p)
        if alt and not alt.endswith("\n") and not inhalt.startswith("\n"):
            inhalt = "\n" + inhalt
        inhalt = alt + inhalt
    elif modus not in ("create", "overwrite", "append"):
        raise Fehler("mode muss create, overwrite oder append sein")
    daten = inhalt.encode("utf-8")
    if len(daten) > MAX_BYTES:
        raise Fehler(f"Inhalt zu groß ({groesse(len(daten))})")
    atomar_schreiben(p, daten)
    return [{"type": "text", "text": f"Geschrieben ({modus}): {rel(p)}, {groesse(len(daten))}"}]


def file_edit(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    schreibbar(p)
    if not p.is_file():
        raise Fehler("Keine Datei")
    alt_s, neu_s = a.get("old_text"), a.get("new_text")
    if not isinstance(alt_s, str) or not alt_s or not isinstance(neu_s, str):
        raise Fehler("old_text (nicht leer) und new_text angeben")
    text, enc = text_lesen(p)
    crlf = "\r\n" in text
    such = alt_s.replace("\r\n", "\n")
    basis = text.replace("\r\n", "\n") if crlf else text
    n = basis.count(such)
    if n == 0:
        raise Fehler("old_text nicht gefunden (Leerzeichen und Zeilenumbrüche müssen genau stimmen). Vorher mit file_read_text lesen")
    if n > 1 and not a.get("replace_all"):
        raise Fehler(f"old_text kommt {n}-mal vor; mehr Kontext angeben oder replace_all=true")
    zeile = basis[: basis.find(such)].count("\n") + 1
    neu = basis.replace(such, neu_s.replace("\r\n", "\n"), -1 if a.get("replace_all") else 1)
    if crlf:
        neu = neu.replace("\n", "\r\n")
    atomar_schreiben(p, neu.encode("utf-8" if enc == "utf-8" else "cp1252", errors="replace"))
    return [{"type": "text", "text": f"Geändert: {rel(p)}, {n if a.get('replace_all') else 1} Stelle(n), ab Zeile {zeile}"}]


def file_search(a: dict) -> list:
    query = a.get("query") or ""
    if not query:
        raise Fehler("query fehlt")
    base = aufloesen(a.get("path", ""))
    muster = a.get("pattern") or "*"
    maxi = min(int(a.get("max_results") or 100), 500)
    flags = 0 if a.get("case_sensitive") else re.IGNORECASE
    try:
        rx = re.compile(query if a.get("regex") else re.escape(query), flags)
    except re.error as e:
        raise Fehler(f"Ungültiger regulärer Ausdruck: {e}")
    treffer, dateien = [], set()
    kandidaten = [base] if base.is_file() else base.rglob(muster)
    for p in kandidaten:
        if len(treffer) >= maxi:
            break
        try:
            if not p.is_file() or TRASH in p.relative_to(ROOT).parts[:1] or set(p.relative_to(ROOT).parts) & PROTECTED:
                continue
            rp = p.resolve()
            if ROOT not in rp.parents or p.stat().st_size > MAX_SEARCH_FILE or ist_binaer(p):
                continue
            text, _ = text_lesen(p)
        except (OSError, Fehler):
            continue
        for nr, zeile in enumerate(text.splitlines(), 1):
            if rx.search(zeile):
                treffer.append(f"{rel(p)}:{nr}: {zeile.strip()[:200]}")
                dateien.add(p)
                if len(treffer) >= maxi:
                    break
    kopf = f"{len(treffer)} Treffer in {len(dateien)} Datei(en)" + (" (Grenze erreicht)" if len(treffer) >= maxi else "")
    return [{"type": "text", "text": kopf + ("\n" + "\n".join(treffer) if treffer else "")}]


def file_move(a: dict) -> list:
    src = aufloesen(a.get("source", ""))
    dst = aufloesen(a.get("destination", ""), muss_existieren=False)
    kopie = bool(a.get("copy"))
    if not kopie:
        schreibbar(src)
    schreibbar(dst)
    if dst.is_dir():
        dst = dst / src.name
    if dst == src:
        raise Fehler("Quelle und Ziel sind gleich")
    if src.is_dir() and (dst == src or src in dst.parents):
        raise Fehler("Ordner kann nicht in sich selbst verschoben werden")
    if dst.exists():
        if not a.get("overwrite"):
            raise Fehler(f"Ziel existiert: {rel(dst)} (overwrite=true zum Ersetzen)")
        if dst.is_dir():
            raise Fehler("Ziel ist ein vorhandener Ordner, wird nicht ersetzt")
    neu_ordner = not dst.parent.exists()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if neu_ordner:
        besitz_uebernehmen(dst.parent, dst.parent.parent)
    if kopie:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
    else:
        shutil.move(str(src), str(dst))
    return [{"type": "text", "text": f"{'Kopiert' if kopie else 'Verschoben'}: {rel(src)} → {rel(dst)}"}]


def file_trash(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    schreibbar(p)
    if p.relative_to(ROOT).parts[0] == TRASH:
        raise Fehler("Liegt schon im Papierkorb; endgültig löschen nur von Hand")
    stempel = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ziel = ROOT / TRASH / stempel / p.relative_to(ROOT)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(ziel))
    return [{"type": "text", "text": f"In den Papierkorb verschoben: {rel(p)} → {rel(ziel)}"}]


def file_get(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    if not p.is_file():
        raise Fehler("Keine Datei")
    size = p.stat().st_size
    offset = max(int(a.get("offset") or 0), 0)
    laenge = int(a.get("length") or 0) or (size - offset)
    if laenge > MAX_BYTES:
        if offset == 0 and not a.get("length"):
            raise Fehler(f"Datei hat {groesse(size)}, Grenze {groesse(MAX_BYTES)}: in Teilen mit offset/length holen")
        raise Fehler(f"length höchstens {MAX_BYTES}")
    with p.open("rb") as fh:
        fh.seek(offset)
        daten = fh.read(laenge)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    teil = offset > 0 or offset + len(daten) < size
    text = f"{rel(p)}: {groesse(size)}, {mime}"
    if teil:
        text += f"; Bytes {offset}–{offset + len(daten) - 1} von {size}"
        if offset + len(daten) < size:
            text += f", weiter mit offset={offset + len(daten)}"
    return [
        {"type": "text", "text": text},
        {"type": "resource", "resource": {"uri": f"file:///{rel(p)}", "mimeType": mime, "blob": base64.b64encode(daten).decode()}},
    ]


def file_put(a: dict) -> list:
    p = aufloesen(a.get("path", ""), muss_existieren=False)
    schreibbar(p)
    if p.is_dir():
        raise Fehler("Zielpfad ist ein Ordner")
    try:
        daten = base64.b64decode(a.get("content_base64", ""), validate=True)
    except ValueError:
        raise Fehler("content_base64 ist kein gültiges base64")
    if len(daten) > MAX_BYTES:
        raise Fehler(f"Teil zu groß ({groesse(len(daten))}), höchstens {groesse(MAX_BYTES)} je Aufruf; mit append=true in Teilen senden")
    if a.get("append"):
        if not p.exists():
            raise Fehler("append=true braucht eine vorhandene Datei; ersten Teil ohne append senden")
        with p.open("ab") as fh:
            fh.write(daten)
        return [{"type": "text", "text": f"Angehängt: {rel(p)}, jetzt {groesse(p.stat().st_size)}"}]
    if p.exists() and not a.get("overwrite"):
        raise Fehler("Datei existiert, overwrite=true setzen, um sie zu ersetzen")
    atomar_schreiben(p, daten)
    return [{"type": "text", "text": f"Geschrieben: {rel(p)} ({groesse(len(daten))})"}]


def file_preview(a: dict) -> list:
    p = aufloesen(a.get("path", ""))
    if not p.is_file():
        raise Fehler("Keine Datei")
    kante = min(max(int(a.get("max_size") or 1024), 64), 2048)
    mime = mimetypes.guess_type(p.name)[0] or ""
    try:
        from PIL import Image
    except ImportError:
        raise Fehler("Vorschau nicht verfügbar (Pillow fehlt in diesem Image)")
    if mime == "application/pdf":
        if not shutil.which("pdftoppm"):
            raise Fehler("PDF-Vorschau nicht verfügbar (pdftoppm fehlt)")
        seite = max(int(a.get("page") or 1), 1)
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(
                ["pdftoppm", "-f", str(seite), "-l", str(seite), "-png", "-scale-to", str(kante), "-singlefile", str(p), f"{td}/s"],
                capture_output=True, timeout=60,
            )
            if r.returncode != 0 or not Path(f"{td}/s.png").exists():
                raise Fehler(f"PDF-Seite {seite} nicht darstellbar")
            img = Image.open(f"{td}/s.png")
            img.load()
    else:
        try:
            _heif_laden()
            img = Image.open(p)
            img.load()
        except Exception:
            raise Fehler("Kein darstellbares Bild")
    try:
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    breite, hoehe = img.size
    img.thumbnail((kante, kante))
    if img.mode not in ("RGB", "L"):
        hg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            hg.paste(img, mask=img.split()[-1])
        else:
            hg.paste(img.convert("RGB"))
        img = hg
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return [
        {"type": "text", "text": f"Vorschau {rel(p)}: Original {breite}×{hoehe} px, Vorschau {img.size[0]}×{img.size[1]} px"},
        {"type": "image", "data": base64.b64encode(buf.getvalue()).decode(), "mimeType": "image/jpeg"},
    ]


# --------------------------------------------------------------------------- Metadaten


def _heif_laden() -> bool:
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
        return True
    except Exception:
        return False


def _gps_dezimal(werte, ref) -> float | None:
    try:
        g, m, s = (float(x) for x in werte)
        d = g + m / 60 + s / 3600
        return -d if ref in ("S", "W") else d
    except Exception:
        return None


def meta_bild(p: Path, gps_modus: str) -> dict:
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return {"hinweis": "Pillow fehlt, keine Bild-Metadaten"}
    _heif_laden()
    out: dict = {}
    with Image.open(p) as img:
        out.update({"format": img.format, "breite": img.size[0], "hoehe": img.size[1], "farbmodus": img.mode})
        exif = img.getexif()
        if not exif:
            out["exif"] = "keine"
            return out
        tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        try:
            tags.update({ExifTags.TAGS.get(k, k): v for k, v in exif.get_ifd(0x8769).items()})
        except Exception:
            pass
        if "DateTimeOriginal" not in tags:  # ältere Pillow-Versionen: flache Legacy-Sicht
            try:
                tags.update({ExifTags.TAGS.get(k, k): v for k, v in (img._getexif() or {}).items() if k != 0x8825})
            except Exception:
                pass
        felder = {
            "aufnahme": "DateTimeOriginal", "geaendert_exif": "DateTime", "kamera_hersteller": "Make",
            "kamera_modell": "Model", "objektiv": "LensModel", "blende": "FNumber", "belichtung_s": "ExposureTime",
            "iso": "ISOSpeedRatings", "brennweite_mm": "FocalLength", "ausrichtung": "Orientation", "software": "Software",
        }
        for name, tag in felder.items():
            v = tags.get(tag)
            if v is not None and v != "":
                out[name] = float(v) if hasattr(v, "numerator") else (v.strip("\x00 ") if isinstance(v, str) else v)
        try:
            gps = {ExifTags.GPSTAGS.get(k, k): v for k, v in exif.get_ifd(0x8825).items()}
        except Exception:
            gps = {}
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = _gps_dezimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef"))
            lon = _gps_dezimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef"))
            if lat is not None and lon is not None:
                if gps_modus == "none":
                    out["gps"] = "vorhanden (ausgeblendet)"
                elif gps_modus == "exact":
                    out["gps"] = {"breite": round(lat, 6), "laenge": round(lon, 6)}
                else:
                    out["gps"] = {"breite": round(lat, 2), "laenge": round(lon, 2), "genauigkeit": "ca. 1 km (gps=exact für genau)"}
    return out


def meta_pdf(p: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"hinweis": "pypdf fehlt, keine PDF-Metadaten"}
    r = PdfReader(str(p))
    out: dict = {"verschluesselt": r.is_encrypted}
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            return out
    out["seiten"] = len(r.pages)
    m = r.metadata or {}
    for name, key in (("titel", "/Title"), ("autor", "/Author"), ("ersteller", "/Creator"), ("erzeugt_mit", "/Producer"),
                      ("erstellt", "/CreationDate"), ("geaendert", "/ModDate")):
        if m.get(key):
            out[name] = str(m.get(key))
    if r.pages:
        box = r.pages[0].mediabox
        b, h = float(box.width) / 72 * 25.4, float(box.height) / 72 * 25.4
        out["seitengroesse_mm"] = f"{b:.0f} × {h:.0f}"
        try:
            zeichen = sum(len((r.pages[i].extract_text() or "").strip()) for i in range(min(3, len(r.pages))))
            out["text"] = "vorhanden" if zeichen > 20 else "kaum oder keiner (Scan? OCR nötig)"
        except Exception:
            pass
    return out


def meta_office(p: Path) -> dict:
    out: dict = {}
    ns = {
        "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
        "dc": "http://purl.org/dc/elements/1.1/",
        "dcterms": "http://purl.org/dc/terms/",
        "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
        "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    }
    try:
        z = zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        return {"hinweis": "kein gültiges Office-Dokument"}
    with z:
        namen = set(z.namelist())
        if "docProps/core.xml" in namen:
            core = ET.fromstring(z.read("docProps/core.xml"))
            for name, pfad in (("titel", "dc:title"), ("autor", "dc:creator"), ("zuletzt_von", "cp:lastModifiedBy"),
                               ("erstellt", "dcterms:created"), ("geaendert", "dcterms:modified")):
                el = core.find(pfad, ns)
                if el is not None and (el.text or "").strip():
                    out[name] = el.text.strip()
        if "docProps/app.xml" in namen:
            app = ET.fromstring(z.read("docProps/app.xml"))
            for name, tag in (("seiten", "Pages"), ("woerter", "Words"), ("folien", "Slides"), ("anwendung", "Application")):
                el = app.find(f"ep:{tag}", ns)
                if el is not None and (el.text or "").strip():
                    out[name] = el.text.strip()
        if "xl/workbook.xml" in namen:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            out["tabellenblaetter"] = [s.get("name") for s in wb.iter(f"{{{ns['s']}}}sheet")]
    return out


def meta_text(p: Path) -> dict:
    if p.stat().st_size > 50 * MAX_BYTES:
        return {"hinweis": "zu groß für Textanalyse"}
    text, enc = text_lesen(p)
    out: dict = {"kodierung": enc, "zeilen": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
                 "zeilenende": "CRLF" if "\r\n" in text else "LF"}
    endung = p.suffix.lower()
    if endung in (".csv", ".tsv"):
        probe = text[:20000]
        try:
            dialekt = csv.Sniffer().sniff(probe, delimiters=",;\t|")
            trenn = dialekt.delimiter
        except csv.Error:
            trenn = "\t" if endung == ".tsv" else ","
        kopf = next(csv.reader(io.StringIO(probe), delimiter=trenn), [])
        out.update({"trennzeichen": {"\t": "Tab"}.get(trenn, trenn), "spalten": kopf[:100], "datenzeilen": max(out["zeilen"] - 1, 0)})
    elif endung == ".md" and text.startswith("---"):
        ende = text.find("\n---", 3)
        if ende > 0:
            fm = text[3:ende].strip()
            out["frontmatter"] = fm[:2000]
    return out


def meta_audio(p: Path) -> dict:
    try:
        import mutagen
    except ImportError:
        return {"hinweis": "mutagen fehlt, keine Audio-/Video-Metadaten"}
    try:
        f = mutagen.File(str(p))
    except Exception:
        f = None
    if f is None or not getattr(f, "info", None):
        return {"hinweis": "Format nicht erkannt"}
    i = f.info
    out: dict = {}
    if getattr(i, "length", None):
        s = int(i.length)
        out["dauer"] = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    for name, attr in (("bitrate_kbit", "bitrate"), ("abtastrate_hz", "sample_rate"), ("kanaele", "channels"), ("codec", "codec")):
        v = getattr(i, attr, None)
        if v:
            out[name] = round(v / 1000) if attr == "bitrate" else v
    out["typ"] = type(f).__name__
    return out


def metadaten(p: Path, mime: str, gps_modus: str) -> dict:
    endung = p.suffix.lower()
    try:
        if mime.startswith("image/") and endung != ".svg":
            return meta_bild(p, gps_modus)
        if mime == "application/pdf":
            return meta_pdf(p)
        if endung in (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"):
            return meta_office(p)
        if mime.startswith(("audio/", "video/")) or endung in (".m4a", ".flac", ".opus", ".ogg", ".mp4", ".mov", ".m4v"):
            return meta_audio(p)
        if not ist_binaer(p):
            return meta_text(p)
    except Fehler as e:
        return {"hinweis": str(e)}
    except Exception as e:  # beschädigte Dateien sollen nicht den Aufruf abbrechen
        return {"hinweis": f"Metadaten nicht lesbar: {type(e).__name__}"}
    return {"hinweis": "keine Metadaten für diesen Typ"}


# --------------------------------------------------------------------------- Beschreibung


def _p(beschreibung: str, typ: str = "string", **extra) -> dict:
    return {"type": typ, "description": beschreibung, **extra}


PFAD = _p("Pfad relativ zur Wurzel")
TOOLS = [
    ("files_list", False, "Listet Dateien und Ordner (Größe, Änderungszeit). Mit pattern filtern, mit sort=mtime die neuesten zuerst.",
     {"path": _p("Ordner, leer = Wurzel"), "recursive": _p("Unterordner einbeziehen", "boolean"),
      "pattern": _p("Dateinamen-Muster, z. B. *.pdf"), "sort": _p("name (Standard) oder mtime", enum=["name", "mtime"]),
      "limit": _p(f"Höchstens so viele Einträge (max {MAX_LIST})", "integer")}, []),
    ("file_info", False, "Größe, Datum, MIME-Typ und SHA-256 einer Datei, ohne sie zu laden. Mit details=true zusätzlich Metadaten "
     "aus dem Inhalt: Fotos (Aufnahmedatum, Kamera, Belichtung, GPS), PDF (Seiten, Titel, Text vorhanden), Office, CSV-Spalten, "
     "Markdown-Frontmatter, Audio/Video-Dauer.",
     {"path": PFAD, "details": _p("Metadaten aus dem Inhalt lesen", "boolean"),
      "gps": _p("rough (Standard, ca. 1 km), exact oder none", enum=["rough", "exact", "none"])}, ["path"]),
    ("file_read_text", False, "Liest eine Textdatei (Markdown, CSV, Code, Logs) direkt als Text, zeilenweise mit offset/limit.",
     {"path": PFAD, "offset": _p("Erste Zeile, ab 1", "integer"), "limit": _p("Anzahl Zeilen (Standard 400)", "integer"),
      "line_numbers": _p("Zeilennummern voranstellen", "boolean")}, ["path"]),
    ("file_write_text", True, "Schreibt Text in eine Datei. mode=create (Standard, nur neue Datei), overwrite (ersetzt alles) "
     "oder append (anhängen). Für Änderungen an bestehenden Dateien file_edit verwenden.",
     {"path": PFAD, "content": _p("Textinhalt (UTF-8)"), "mode": _p("create, overwrite oder append", enum=["create", "overwrite", "append"])},
     ["path", "content"]),
    ("file_edit", True, "Ersetzt eine Textstelle in einer bestehenden Datei, der Rest bleibt unverändert. old_text muss genau "
     "einmal vorkommen (sonst mehr Kontext angeben). Vorher mit file_read_text lesen.",
     {"path": PFAD, "old_text": _p("Genau zu ersetzender Text, inkl. Leerzeichen und Umbrüche"), "new_text": _p("Neuer Text"),
      "replace_all": _p("Alle Vorkommen ersetzen", "boolean")}, ["path", "old_text", "new_text"]),
    ("file_search", False, "Durchsucht Textdateien nach einem Begriff oder regulären Ausdruck, liefert Datei:Zeile: Inhalt.",
     {"query": _p("Suchbegriff"), "path": _p("Ordner oder Datei, leer = Wurzel"), "pattern": _p("Dateinamen-Muster, z. B. *.md"),
      "regex": _p("query als regulären Ausdruck", "boolean"), "case_sensitive": _p("Groß-/Kleinschreibung beachten", "boolean"),
      "max_results": _p("Höchstens so viele Treffer (Standard 100)", "integer")}, ["query"]),
    ("file_move", True, "Verschiebt, benennt um oder kopiert (copy=true) eine Datei oder einen Ordner. Zielordner werden angelegt. "
     "Überschreibt nur mit overwrite=true.",
     {"source": PFAD, "destination": _p("Zielpfad oder vorhandener Zielordner"), "copy": _p("Kopieren statt verschieben", "boolean"),
      "overwrite": _p("Vorhandene Zieldatei ersetzen", "boolean")}, ["source", "destination"]),
    ("file_trash", True, f"Löscht eine Datei oder einen Ordner nicht endgültig, sondern verschiebt ihn nach {TRASH}/ (mit Zeitstempel).",
     {"path": PFAD}, ["path"]),
    ("file_get", False, f"Holt eine Datei als Binärinhalt (Resource mit Blob), höchstens {MAX_BYTES // (1024 * 1024)} MB je Aufruf; "
     "größere in Teilen mit offset/length. Für Text file_read_text, für Bilder zum Ansehen file_preview.",
     {"path": PFAD, "offset": _p("Startbyte", "integer"), "length": _p("Anzahl Bytes", "integer")}, ["path"]),
    ("file_put", True, f"Legt eine Datei ab (Inhalt base64, höchstens {MAX_BYTES // (1024 * 1024)} MB je Aufruf). Überschreibt nur mit "
     "overwrite=true; größere Dateien in Teilen: erster Teil normal, weitere mit append=true.",
     {"path": PFAD, "content_base64": _p("Inhalt base64"), "overwrite": _p("Vorhandene Datei ersetzen", "boolean"),
      "append": _p("An vorhandene Datei anhängen", "boolean")}, ["path", "content_base64"]),
    ("file_preview", False, "Zeigt ein Bild oder eine PDF-Seite verkleinert als Bild an, zum Ansehen und Prüfen von Ergebnissen.",
     {"path": PFAD, "page": _p("PDF-Seite, ab 1", "integer"), "max_size": _p("Längste Kante in Pixeln (Standard 1024)", "integer")},
     ["path"]),
]
HANDLER = {
    "files_list": files_list, "file_info": file_info, "file_read_text": file_read_text, "file_write_text": file_write_text,
    "file_edit": file_edit, "file_search": file_search, "file_move": file_move, "file_trash": file_trash,
    "file_get": file_get, "file_put": file_put, "file_preview": file_preview,
}


def tool_liste() -> list[dict]:
    hinweis = f" Wurzel: {ROOT}." + (" Nur-Lese-Modus." if READ_ONLY else "")
    out = []
    for name, schreibt, beschr, props, req in TOOLS:
        if schreibt and READ_ONLY:
            continue
        schema = {"type": "object", "properties": props}
        if req:
            schema["required"] = req
        out.append({"name": name, "description": beschr + (hinweis if name == "files_list" else ""), "inputSchema": schema,
                    "annotations": {"readOnlyHint": not schreibt, "destructiveHint": name in ("file_write_text", "file_put"),
                                    "idempotentHint": not schreibt}})
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
                      "serverInfo": {"name": "files", "title": "Dateien", "version": VERSION}})
    elif methode == "ping":
        antwort(id_, {})
    elif methode == "tools/list":
        antwort(id_, {"tools": tool_liste()})
    elif methode == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        fn = HANDLER.get(name)
        if fn is None or (READ_ONLY and any(t[0] == name and t[1] for t in TOOLS)):
            antwort(id_, error={"code": -32602, "message": f"Unbekanntes Tool: {name}"})
            return
        try:
            antwort(id_, {"content": fn(params.get("arguments") or {})})
        except Fehler as e:
            antwort(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except (ValueError, TypeError) as e:
            antwort(id_, {"content": [{"type": "text", "text": f"Ungültige Angabe: {e}"}], "isError": True})
        except OSError as e:
            antwort(id_, {"content": [{"type": "text", "text": f"Dateifehler: {e.strerror or e}"}], "isError": True})
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
