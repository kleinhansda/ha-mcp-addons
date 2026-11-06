#!/usr/bin/env python3
"""Tests für common/files_mcp.py über das MCP-Protokoll (stdio).

Aufruf: python3 files_mcp/tests/test_files_mcp.py [pfad/zu/files_mcp.py]
Optionale Teile (Pillow, pypdf, mutagen, pdftoppm) werden übersprungen, wenn sie fehlen.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SERVER = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "common" / "files_mcp.py")


def hat(modul: str) -> bool:
    try:
        __import__(modul)
        return True
    except ImportError:
        return False


class Server:
    def __init__(self, root: Path, **env):
        e = dict(os.environ, **{k: str(v) for k, v in env.items()})
        self.p = subprocess.Popen([sys.executable, str(SERVER), str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=e)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def call(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            return r["error"]["message"], True, []
        res = r["result"]
        texte = [c["text"] for c in res["content"] if c["type"] == "text"]
        return "\n".join(texte), res.get("isError", False), res["content"]

    def ok(self, name, **args):
        text, err, content = self.call(name, **args)
        assert not err, f"{name} fehlgeschlagen: {text}"
        return text, content

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        self.p.stdout.close()


class Basis(unittest.TestCase):
    env: dict = {}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        self.root.mkdir()
        (self.root / "notiz.md").write_text("---\ntags: [a]\n---\n## Titel\nZeile eins\nZeile zwei\n", encoding="utf-8")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "daten.csv").write_text("name;wert\nx;1\ny;2\n", encoding="utf-8")
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian" / "app.json").write_text("{}")
        (self.tmp / "draussen.txt").write_text("geheim")
        self.s = Server(self.root, **self.env)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp)


class Lesen(Basis):
    def test_tools_vollstaendig(self):
        namen = [t["name"] for t in self.s.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(len(namen), 11)

    def test_list_pattern_und_mtime(self):
        text, _ = self.s.ok("files_list", recursive=True, pattern="*.csv")
        self.assertIn("sub/daten.csv", text)
        self.assertNotIn("notiz.md", text)
        text, _ = self.s.ok("files_list", sort="mtime")
        self.assertIn("notiz.md", text)

    def test_ausbruch_blockiert(self):
        for pfad in ("../draussen.txt", "/../draussen.txt", "sub/../../draussen.txt"):
            text, err, _ = self.s.call("file_read_text", path=pfad)
            self.assertTrue(err, pfad)
        (self.root / "link").symlink_to(self.tmp / "draussen.txt")
        _, err, _ = self.s.call("file_read_text", path="link")
        self.assertTrue(err)
        text, _ = self.s.ok("files_list")
        self.assertNotIn("link", text)

    def test_absoluter_pfad_innerhalb(self):
        text, _ = self.s.ok("file_read_text", path=str(self.root / "notiz.md"))
        self.assertIn("Zeile eins", text)

    def test_read_text_bereich(self):
        text, _ = self.s.ok("file_read_text", path="notiz.md", offset=5, limit=1, line_numbers=True)
        self.assertIn("5│Zeile eins", text)
        self.assertIn("weiter mit offset=6", text)

    def test_info_und_details(self):
        text, _ = self.s.ok("file_info", path="sub/daten.csv", details=True)
        d = json.loads(text)
        self.assertEqual(len(d["sha256"]), 64)
        self.assertEqual(d["details"]["trennzeichen"], ";")
        self.assertEqual(d["details"]["spalten"], ["name", "wert"])
        text, _ = self.s.ok("file_info", path="notiz.md", details=True)
        self.assertIn("tags: [a]", json.loads(text)["details"]["frontmatter"])

    def test_office(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                       'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Bericht</dc:title><dc:creator>David</dc:creator></cp:coreProperties>')
            z.writestr("docProps/app.xml", '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>3</Pages></Properties>')
        (self.root / "b.docx").write_bytes(buf.getvalue())
        d = json.loads(self.s.ok("file_info", path="b.docx", details=True)[0])["details"]
        self.assertEqual((d["titel"], d["autor"], d["seiten"]), ("Bericht", "David", "3"))

    def test_search(self):
        text, _ = self.s.ok("file_search", query="zeile zwei")
        self.assertIn("notiz.md:6:", text)
        text, _ = self.s.ok("file_search", query="^y;", regex=True)
        self.assertIn("sub/daten.csv:3", text)
        text, _ = self.s.ok("file_search", query="{}")
        self.assertIn("0 Treffer", text)  # .obsidian wird nicht durchsucht

    def test_get_in_teilen(self):
        (self.root / "bin").write_bytes(bytes(range(256)) * 4)
        _, c = self.s.ok("file_get", path="bin", offset=1000, length=100)
        self.assertEqual(len(base64.b64decode(c[1]["resource"]["blob"])), 24)


class Schreiben(Basis):
    def test_write_create_overwrite_append(self):
        self.s.ok("file_write_text", path="neu/a.txt", content="eins")
        _, err, _ = self.s.call("file_write_text", path="neu/a.txt", content="x")
        self.assertTrue(err)
        self.s.ok("file_write_text", path="neu/a.txt", content="zwei", mode="append")
        self.assertEqual((self.root / "neu/a.txt").read_text(), "eins\nzwei")
        self.s.ok("file_write_text", path="neu/a.txt", content="drei", mode="overwrite")
        self.assertEqual((self.root / "neu/a.txt").read_text(), "drei")
        self.assertFalse(list((self.root / "neu").glob("*.part")))

    def test_edit(self):
        self.s.ok("file_edit", path="notiz.md", old_text="Zeile eins", new_text="Zeile 1")
        self.assertIn("Zeile 1\nZeile zwei", (self.root / "notiz.md").read_text())
        _, err, _ = self.s.call("file_edit", path="notiz.md", old_text="Zeile", new_text="X")
        self.assertTrue(err)  # mehrdeutig
        _, err, _ = self.s.call("file_edit", path="notiz.md", old_text="gibtsnicht", new_text="X")
        self.assertTrue(err)
        self.s.ok("file_edit", path="notiz.md", old_text="Zeile", new_text="Z", replace_all=True)
        self.assertNotIn("Zeile", (self.root / "notiz.md").read_text())

    def test_edit_crlf_und_rechte(self):
        p = self.root / "win.txt"
        p.write_bytes(b"a\r\nb\r\nc\r\n")
        os.chmod(p, 0o640)
        self.s.ok("file_edit", path="win.txt", old_text="b\nc", new_text="B\nC")
        self.assertEqual(p.read_bytes(), b"a\r\nB\r\nC\r\n")
        self.assertEqual(p.stat().st_mode & 0o777, 0o640)

    def test_geschuetzt(self):
        for name, args in (("file_write_text", {"path": ".obsidian/x.json", "content": "x"}),
                           ("file_edit", {"path": ".obsidian/app.json", "old_text": "{}", "new_text": "[]"}),
                           ("file_trash", {"path": ".obsidian"}),
                           ("file_move", {"source": "notiz.md", "destination": ".obsidian/"})):
            text, err, _ = self.s.call(name, **args)
            self.assertTrue(err, name)
            self.assertIn("Geschützt", text)
        self.assertEqual((self.root / ".obsidian/app.json").read_text(), "{}")

    def test_move_copy(self):
        self.s.ok("file_move", source="notiz.md", destination="archiv/notiz.md", copy=True)
        self.assertTrue((self.root / "notiz.md").exists() and (self.root / "archiv/notiz.md").exists())
        _, err, _ = self.s.call("file_move", source="notiz.md", destination="archiv/notiz.md")
        self.assertTrue(err)
        self.s.ok("file_move", source="notiz.md", destination="sub")
        self.assertTrue((self.root / "sub/notiz.md").exists())
        _, err, _ = self.s.call("file_move", source="sub", destination="sub/innen")
        self.assertTrue(err)

    def test_trash(self):
        self.s.ok("file_trash", path="sub/daten.csv")
        self.assertFalse((self.root / "sub/daten.csv").exists())
        self.assertEqual(len(list((self.root / ".trash").rglob("daten.csv"))), 1)
        text, _ = self.s.ok("files_list")
        self.assertNotIn(".trash", text)

    def test_put_teile(self):
        daten = os.urandom(3000)
        self.s.ok("file_put", path="x.bin", content_base64=base64.b64encode(daten[:1000]).decode())
        self.s.ok("file_put", path="x.bin", content_base64=base64.b64encode(daten[1000:]).decode(), append=True)
        self.assertEqual((self.root / "x.bin").read_bytes(), daten)
        _, err, _ = self.s.call("file_put", path="x.bin", content_base64="AA==")
        self.assertTrue(err)


class NurLesen(Basis):
    env = {"FILES_READ_ONLY": "true"}

    def test_nur_lesende_tools(self):
        namen = {t["name"] for t in self.s.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(namen, {"files_list", "file_info", "file_read_text", "file_search", "file_get", "file_preview"})
        text, err, _ = self.s.call("file_write_text", path="a.txt", content="x")
        self.assertTrue(err)
        self.assertFalse((self.root / "a.txt").exists())


@unittest.skipUnless(hat("mutagen"), "mutagen fehlt")
class Audio(Basis):
    def test_wav_dauer(self):
        import wave

        with wave.open(str(self.root / "ton.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 8000 * 65)
        d = json.loads(self.s.ok("file_info", path="ton.wav", details=True)[0])["details"]
        self.assertEqual(d["dauer"], "0:01:05")
        self.assertEqual(d["abtastrate_hz"], 8000)


@unittest.skipUnless(hat("PIL"), "Pillow fehlt")
class Bilder(Basis):
    def _foto(self):
        from PIL import Image

        img = Image.new("RGB", (4000, 3000), (200, 100, 50))
        exif = Image.Exif()
        exif[0x010F], exif[0x0110] = "Testkamera", "Modell X"
        exif.get_ifd(0x8769)[0x9003] = "2026:11:03 14:22:01"
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2], gps[3], gps[4] = "N", (50.0, 6.0, 13.0), "E", (8.0, 38.0, 37.0)
        img.save(self.root / "foto.jpg", exif=exif)

    def test_exif_gps_gerundet(self):
        self._foto()
        d = json.loads(self.s.ok("file_info", path="foto.jpg", details=True)[0])["details"]
        self.assertEqual(d["aufnahme"], "2026:11:03 14:22:01")
        self.assertEqual(d["kamera_modell"], "Modell X")
        self.assertEqual((d["gps"]["breite"], d["gps"]["laenge"]), (50.1, 8.64))
        d = json.loads(self.s.ok("file_info", path="foto.jpg", details=True, gps="exact")[0])["details"]
        self.assertAlmostEqual(d["gps"]["breite"], 50.103611, places=5)
        d = json.loads(self.s.ok("file_info", path="foto.jpg", details=True, gps="none")[0])["details"]
        self.assertEqual(d["gps"], "vorhanden (ausgeblendet)")

    def test_preview(self):
        self._foto()
        text, c = self.s.ok("file_preview", path="foto.jpg", max_size=512)
        self.assertIn("512×384", text)
        self.assertEqual(c[1]["type"], "image")

    @unittest.skipUnless(hat("pypdf") and shutil.which("pdftoppm"), "pypdf/pdftoppm fehlt")
    def test_pdf(self):
        from PIL import Image

        Image.new("RGB", (595, 842), "white").save(self.root / "scan.pdf")
        d = json.loads(self.s.ok("file_info", path="scan.pdf", details=True)[0])["details"]
        self.assertEqual(d["seiten"], 1)
        self.assertIn("OCR", d["text"])
        _, c = self.s.ok("file_preview", path="scan.pdf")
        self.assertEqual(c[1]["type"], "image")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"])
