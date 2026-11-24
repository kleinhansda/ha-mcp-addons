#!/usr/bin/env python3
"""Tests für postiz_api_tool.py gegen einen nachgebauten Postiz-Server (Public API).

  python3 homeassistant/openwebui/tests/test_postiz_api.py
"""
import asyncio
import importlib.util
import json
import os
import tempfile
from pathlib import Path

from aiohttp import web

spec = importlib.util.spec_from_file_location("p", Path(__file__).resolve().parents[1] / "postiz_api_tool.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

ok = 0
anfragen = []


def check(b, w):
    global ok
    assert b, w
    ok += 1
    print("ok  ", w)


def auth(req):
    return req.headers.get("Authorization") == "geheim"


async def integrations(req):
    if not auth(req):
        return web.json_response({"msg": "unauthorized"}, status=401)
    return web.json_response([{"id": "ig1", "identifier": "instagram", "name": "hannesbraeu"},
                              {"id": "fb1", "identifier": "facebook", "name": "Hannesbräu"}])


async def posts_get(req):
    anfragen.append(("GET", dict(req.query)))
    return web.json_response({"posts": []}) if "startDate" in req.query and "endDate" in req.query else web.json_response({}, status=400)


async def posts_post(req):
    body = await req.json()
    anfragen.append(("POST", body))
    return web.json_response([{"postId": "p1", "integration": x["integration"]["id"]} for x in body["posts"]])


async def upload(req):
    data = await req.post()
    f = data.get("file")
    anfragen.append(("UPLOAD", getattr(f, "filename", None)))
    return web.json_response({"id": "m1", "path": "https://postiz.example/uploads/x.jpg"})


async def delete(req):
    anfragen.append(("DELETE", req.match_info["id"]))
    return web.json_response({"ok": True})


GEZEIGT = "**Kanäle:** Instagram, Facebook\n**Wann:** Fr, 27.11., 18:00\n\n> Kilted Cowboy live im Hannesbräu!\n> Freitag ab 19 Uhr.\n\nPosten?"
TEXT = "Kilted Cowboy live im Hannesbräu!\nFreitag ab 19 Uhr."


def verlauf(freigabe):
    return [{"role": "user", "content": "Mach einen Post"}, {"role": "assistant", "content": GEZEIGT},
            {"role": "user", "content": freigabe}]


async def main():
    app = web.Application()
    app.router.add_get("/api/public/v1/integrations", integrations)
    app.router.add_get("/api/public/v1/posts", posts_get)
    app.router.add_post("/api/public/v1/posts", posts_post)
    app.router.add_post("/api/public/v1/upload", upload)
    app.router.add_delete("/api/public/v1/posts/{id}", delete)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    d = tempfile.mkdtemp()
    os.makedirs(f"{d}/hb")
    Path(f"{d}/hb/poster.jpg").write_bytes(b"\xff\xd8bild")
    Path(f"{d}/geheim.db").write_bytes(b"x")
    Path(f"{d}/hb/skript.py").write_text("x")

    t = p.Tools()
    t.valves.base_url = f"http://127.0.0.1:{port}/api/public/v1"
    t.valves.medien_ordner = f"{d}/hb"
    check((await t.kanaele_listen()).startswith("Fehler") and "api_key" in await t.kanaele_listen(), "ohne Schlüssel: Hinweis aufs Ventil")
    t.valves.api_key = "geheim"
    k = await t.kanaele_listen()
    check("ig1 | instagram" in k and "fb1 | facebook" in k, "Kanäle mit Schlüssel ohne Bearer")
    r = await t.posts_lesen()
    check(r.startswith("HTTP 200") and "startDate" in anfragen[-1][1], "posts_lesen setzt startDate/endDate")

    check((await t.medien_hochladen(f"{d}/geheim.db")).startswith("Fehler: nur Dateien"), "Upload außerhalb des Ordners gesperrt")
    check((await t.medien_hochladen(f"{d}/hb/../geheim.db")).startswith("Fehler: nur Dateien"), "Upload mit .. gesperrt")
    check((await t.medien_hochladen(f"{d}/hb/skript.py")).startswith("Fehler: nur"), "nur Bild-/Videoendungen")
    m = json.loads(await t.medien_hochladen(f"{d}/hb/poster.jpg"))
    check(m["id"] == "m1" and anfragen[-1] == ("UPLOAD", "poster.jpg"), "Upload als Feld file")

    r = await t.post_anlegen("draft", ["ig1", "fb1"], TEXT, "2026-11-27T17:00:00.000Z", [m])
    body = anfragen[-1][1]
    check(r.startswith("Als Entwurf") and body["type"] == "draft" and body["shortLink"] is False and body["tags"] == [],
          "Entwurf ohne Freigabe, Pflichtfelder gesetzt")
    check(body["posts"][0]["value"][0]["content"] == TEXT and body["posts"][0]["value"][0]["image"] == [m],
          "Text und Bild in value[]")
    check(body["posts"][0]["settings"] == {"__type": "instagram", "post_type": "post", "collaborators": []}
          and body["posts"][1]["settings"] == {"__type": "facebook"}, "Einstellungen je Plattform")

    n = len(anfragen)
    r = await t.post_anlegen("now", ["ig1"], TEXT, __messages__=verlauf("Mach noch ein Emoji rein"), __metadata__={})
    check(r.startswith("Nicht veröffentlicht") and len(anfragen) == n, "sofort ohne Freigabe: nichts gesendet")
    r = await t.post_anlegen("schedule", ["ig1"], TEXT + " Eintritt frei!", "2026-11-27T17:00:00.000Z",
                             __messages__=verlauf("ja"), __metadata__={"chat_id": "c1"})
    check(r.startswith("Nicht veröffentlicht") and "weicht" in r, "geänderter Text: nicht geplant")
    r = await t.post_anlegen("schedule", ["ig1", "fb1"], TEXT, "2026-11-27T17:00:00.000Z",
                             __messages__=verlauf("x"), __metadata__={"chat_id": "c1", "user_message": {"content": "Ja, posten"}})
    check(r.startswith("Geplant") and anfragen[-1][1]["type"] == "schedule", "mit Freigabe geplant")
    r = await t.post_anlegen("schedule", ["ig1", "fb1"], TEXT, "2026-11-27T17:00:00.000Z",
                             __messages__=verlauf("x"), __metadata__={"chat_id": "c1", "user_message": {"content": "Ja, posten"}})
    check("schon verwendet" in r, "dieselbe Freigabe nicht zweimal")
    check((await t.post_anlegen("draft", ["zz9"], TEXT, "2026-11-27T17:00:00.000Z")).startswith("Fehler: Kanal"), "unbekannter Kanal")
    check((await t.post_anlegen("draft", ["ig1"], TEXT, "morgen")).startswith("Fehler: datum"), "Datum geprüft")

    check((await t.post_loeschen("../x", __metadata__={"user_message": {"content": "löschen"}})).startswith("Fehler"), "Post-ID geprüft")
    check((await t.post_loeschen("p1", __metadata__={"user_message": {"content": "passt"}})).startswith("Nicht gelöscht"), "löschen nur auf Davids Wort")
    r = await t.post_loeschen("p1", __metadata__={"user_message": {"content": "Bitte den Post löschen"}})
    check(r == "Gelöscht." and anfragen[-1] == ("DELETE", "p1"), "löschen mit Davids Wort")
    await runner.cleanup()


asyncio.run(main())
print(f"\n{ok} Prüfungen bestanden")
