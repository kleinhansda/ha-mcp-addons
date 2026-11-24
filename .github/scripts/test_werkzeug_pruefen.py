#!/usr/bin/env python3
"""Tests für open_terminal/rootfs/usr/local/bin/werkzeug-pruefen an Beispielwerkzeugen.

  python3 .github/scripts/test_werkzeug_pruefen.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRUEFER = REPO / "open_terminal/rootfs/usr/local/bin/werkzeug-pruefen"

# Von einem Modell erzeugtes Postiz-Werkzeug (Valves außerhalb von Tools, Datei ohne Pfadprüfung)
KAPUTT = '"""\ntitle: Postiz API\nauthor: David\nversion: 1.0.0\ndescription: Postiz-Instanz (eigener, postiz.ddsk.cloud) per REST-API: Kanaele listen, Posts ansehen/anlegen/loeschen, Medien hochladen. API-Key im Ventil.\n"""\n\nimport os\nimport aiohttp\nfrom typing import Optional, List\nfrom pydantic import BaseModel, Field\n\n\nclass Valves(BaseModel):\n    base_url: str = Field(default="https://postiz.ddsk.cloud", description="Postiz-Basis-URL")\n    api_key: str = Field(default="", description="Postiz-API-Key (Settings > API Keys)")\n    max_zeichen: int = Field(default=2000, description="Gekuerzte Antwort-Zeichen")\n\n\nclass Tools:\n    def __init__(self):\n        self.valves = self.Valves()\n\n    async def _senden(self, methode: str, pfad: str, daten: Optional[dict] = None, datei: str = "") -> str:\n        if not self.valves.api_key:\n            return "Fehler: Ventil api_key ist leer (Postiz Settings > API Keys)."\n        url = self.valves.base_url.rstrip("/") + pfad\n        headers = {"Authorization": "Bearer " + self.valves.api_key}\n        try:\n            timeout = aiohttp.ClientTimeout(total=60)\n            async with aiohttp.ClientSession(timeout=timeout) as s:\n                if datei:\n                    form = aiohttp.FormData()\n                    form.add_field("image", open(datei, "rb"), filename=os.path.basename(datei))\n                    async with s.post(url, data=form, headers=headers) as r:\n                        text = await r.text()\n                        return "HTTP %s: %s" % (r.status, text[: self.valves.max_zeichen])\n                else:\n                    async with s.request(methode, url, json=daten, headers=headers) as r:\n                        text = await r.text()\n                        return "HTTP %s: %s" % (r.status, text[: self.valves.max_zeichen])\n        except Exception as e:\n            return "Fehler: %s" % e\n\n    async def kanaele_listen(self) -> str:\n        """Alle verbundenen Kanaele (Instagram, Facebook ...) mit Integration-ID.\n        :return: HTTP-Status und JSON-Liste\n        """\n        return await self._senden("GET", "/integrations")\n\n    async def posts_lesen(self, start: str = "", end: str = "") -> str:\n        """Posts in einem Zeitraum lesen (UTC ISO 8601, z. B. 2026-11-24T00:00:00.000Z).\n        :param start: Von (UTC ISO), leer = alle\n        :param end: Bis (UTC ISO), leer = alle\n        :return: HTTP-Status und JSON\n        """\n        q = ""\n        teile = [(k, v) for k, v in [("start", start), ("end", end)] if v]\n        if teile:\n            q = "?" + "&".join("%s=%s" % t for t in teile)\n        return await self._senden("GET", "/posts" + q)\n\n    async def post_anlegen(self, typ: str, datum: str, integration_id: str, content: str, settings_type: str = "instagram", post_type: str = "post", bilder: Optional[List[dict]] = None) -> str:\n        """Post anlegen. typ: now, schedule oder draft. datum: UTC ISO 8601. bilder: Liste aus medien_hochladen.\n        :param typ: now, schedule oder draft\n        :param datum: UTC ISO 8601 (z. B. 2026-11-25T08:00:00.000Z)\n        :param integration_id: ID aus kanaele_listen\n        :param content: Post-Text\n        :param settings_type: z. B. instagram\n        :param post_type: post, story oder reel\n        :param bilder: [{"id": ..., "path": ...}] aus medien_hochladen\n        :return: HTTP-Status und JSON mit Post-ID\n        """\n        daten = {\n            "type": typ,\n            "date": datum,\n            "posts": [\n                {\n                    "integration": {"id": integration_id},\n                    "content": content,\n                    "settings": {"__type": settings_type, "post_type": post_type},\n                    "images": bilder or []\n                }\n            ]\n        }\n        return await self._senden("POST", "/posts", daten=daten)\n\n    async def post_loeschen(self, post_id: str) -> str:\n        """Post loeschen (nur auf ausdruecklichen Wunsch).\n        :param post_id: ID des Posts\n        :return: HTTP-Status\n        """\n        return await self._senden("DELETE", "/posts/" + post_id)\n\n    async def medien_hochladen(self, dateipfad: str) -> str:\n        """Bild/Video nach Postiz hochladen (z. B. /share/.../poster.png).\n        :param dateipfad: absoluter Pfad zur Mediendatei\n        :return: HTTP-Status und JSON mit id/path fuer post_anlegen(bilder=...)\n        """\n        if not os.path.isfile(dateipfad):\n            return "Fehler: Datei nicht gefunden: " + dateipfad\n        return await self._senden("POST", "/upload", datei=dateipfad)\n'

DATEI_OHNE_PRUEFUNG = """\"\"\"
title: Lesen
version: 1.0.0
description: liest Dateien
\"\"\"
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        x: str = Field(default="", description="x")

    def __init__(self):
        self.valves = self.Valves()

    async def lesen(self, pfad: str) -> str:
        \"\"\"
        Datei lesen.
        :param pfad: Pfad
        \"\"\"
        return open(pfad).read()
"""

ok = 0


def check(b, w):
    global ok
    assert b, w
    ok += 1
    print("ok  ", w)


def lauf(code=None, datei=None, *args):
    with tempfile.TemporaryDirectory() as d:
        if datei is None:
            datei = Path(d) / "probe.py"
            datei.write_text(code)
        r = subprocess.run([sys.executable, str(PRUEFER), str(datei), *args], capture_output=True, text=True, cwd=d)
        json_datei = Path(datei).with_name(Path(datei).stem + ".json")
        inhalt = json.loads(json_datei.read_text()) if "--json" in args and json_datei.is_file() and str(json_datei).startswith(d) else None
        return r.returncode, r.stdout, inhalt


rc, aus, _ = lauf(KAPUTT)
check(rc == 1 and "außerhalb von class Tools" in aus, "Valves außerhalb von Tools wird erkannt")
rc, aus, inhalt = lauf(KAPUTT, None, "--json")
check(rc == 1 and inhalt is None, "kaputtes Werkzeug: keine Import-Datei")
rc, aus, _ = lauf(DATEI_OHNE_PRUEFUNG)
check(rc == 1 and "Dateizugriff ohne Pfadprüfung" in aus, "Dateizugriff ohne realpath ist ein Fehler")
with tempfile.TemporaryDirectory() as d:
    ziel = Path(d) / "mail_senden.py"
    ziel.write_text((REPO / "homeassistant/openwebui/mail_senden_tool.py").read_text())
    r = subprocess.run([sys.executable, str(PRUEFER), str(ziel), "--json"], capture_output=True, text=True)
    check(r.returncode == 0, "geprüftes Werkzeug (mail_senden) ohne Fehler:\n" + r.stdout[-600:])
    imp = json.loads((Path(d) / "mail_senden.json").read_text())
    check(isinstance(imp, list) and imp[0]["id"] == "mail_senden" and "class Tools" in imp[0]["content"],
          "Import-Datei ist eine Liste mit id und content")
    check("prüft aber keine Freigabe" not in r.stdout, "ändernde Funktionen mit Freigabeprüfung ohne Hinweis")
    check("Hinweis: API-Aufrufe ohne Quellenangabe" in r.stdout, "fehlende API-Quelle nur als Hinweis")
print(f"\n{ok} Prüfungen bestanden")
