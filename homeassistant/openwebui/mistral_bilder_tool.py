"""
title: Mistral Bilder
author: David
version: 0.2.0
description: Erzeugt Bilder über die Mistral-Conversations-API (eingebautes Werkzeug image_generation) und zeigt sie im Chat.
requirements:
"""

import json
from typing import Optional

import aiohttp
from pydantic import BaseModel, Field

API = "https://api.mistral.ai/v1"


class Tools:
    class Valves(BaseModel):
        api_key: str = Field(default="", description="Mistral-API-Schlüssel (console.mistral.ai)")
        model: str = Field(default="mistral-medium-latest", description="Textmodell, das das Bildwerkzeug aufruft")
        timeout: int = Field(default=120, description="Sekunden")

    def __init__(self):
        self.valves = self.Valves()

    async def bild_erzeugen(
        self,
        beschreibung: str,
        __request__=None,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __chat_id__: Optional[str] = None,
        __message_id__: Optional[str] = None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Erzeugt ein Bild mit Mistral und zeigt es im Chat an.

        :param beschreibung: Ausführliche Bildbeschreibung (Motiv, Stil, Farben, Format), am besten auf Englisch.
        :return: Status und URL des Bildes
        """
        if not self.valves.api_key:
            return "Fehler: Im Werkzeug „Mistral Bilder“ ist kein API-Schlüssel hinterlegt (Valves)."

        async def status(text: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        await status("Mistral erzeugt das Bild …")
        headers = {"Authorization": f"Bearer {self.valves.api_key}"}
        body = {
            "model": self.valves.model,
            "instructions": "Erzeuge genau ein Bild mit dem Werkzeug image_generation nach der Beschreibung. Keine Rückfragen.",
            "tools": [{"type": "image_generation"}],
            "inputs": beschreibung,
            "store": False,
        }
        t = aiohttp.ClientTimeout(total=self.valves.timeout)
        try:
            async with aiohttp.ClientSession(timeout=t, headers=headers) as s:
                async with s.post(f"{API}/conversations", json=body) as r:
                    if r.status >= 400:
                        await status("Mistral-Fehler", True)
                        return f"Fehler von Mistral ({r.status}): {(await r.text())[:500]}"
                    data = await r.json()

                # Mistral liefert das Bild je nach Konto als Datei (tool_file) oder als
                # signierte, kurzlebige URL im Ergebnis der Werkzeugausführung.
                file_ids, urls, texte = [], [], []
                for out in data.get("outputs") or []:
                    if out.get("type") == "tool.execution":
                        try:
                            res = json.loads((out.get("info") or {}).get("result") or "{}")
                            if isinstance(res, dict) and res.get("url"):
                                urls.append(res["url"])
                        except (ValueError, TypeError):
                            pass
                    content = out.get("content")
                    if isinstance(content, str):
                        texte.append(content)
                        continue
                    for c in content or []:
                        if c.get("type") == "tool_file" and c.get("file_id"):
                            file_ids.append((c["file_id"], c.get("file_type") or "png"))
                        elif c.get("type") == "text":
                            texte.append(c.get("text", ""))
                if not file_ids and not urls:
                    await status("Kein Bild erhalten", True)
                    return "Mistral hat kein Bild geliefert. Antwort: " + " ".join(texte)[:300]

                bilder = []
                for fid, ftyp in file_ids:
                    async with s.get(f"{API}/files/{fid}/content") as r:
                        if r.status >= 400:
                            return f"Fehler beim Herunterladen ({r.status}): {(await r.text())[:300]}"
                        bilder.append((await r.read(), f"image/{ftyp}"))
            # Signierte URLs ohne Mistral-Schlüssel laden (eigene Sitzung)
            async with aiohttp.ClientSession(timeout=t) as s2:
                for u in urls:
                    async with s2.get(u) as r:
                        if r.status >= 400:
                            return f"Fehler beim Herunterladen des Bildes ({r.status})"
                        ctype = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]
                        if not ctype.startswith("image/"):
                            ctype = "image/jpeg"
                        bilder.append((await r.read(), ctype))
        except Exception as e:
            await status("Fehler", True)
            return f"Fehler: {e}"

        from open_webui.models.chats import Chats
        from open_webui.models.users import UserModel
        from open_webui.routers.images import upload_image
        from open_webui.utils.chat_id import is_saved_chat_id

        user = UserModel(**__user__) if __user__ else None
        meta = {}  # wie das eingebaute generate_image: Verknüpfung mit der Nachricht erst unten
        images = []
        for daten, ctype in bilder:
            _, img = await upload_image(__request__, daten, ctype, meta, user)
            images.append(img)

        files = [{"type": "image", **img} for img in images]
        if is_saved_chat_id(__chat_id__) and __message_id__:
            db = await Chats.add_message_files_by_id_and_message_id(__chat_id__, __message_id__, files)
            if db is not None:
                files = db
        if __event_emitter__:
            await __event_emitter__({"type": "chat:message:files", "data": {"files": files}})
        await status("Bild erzeugt", True)
        return json.dumps(
            {"status": "ok", "hinweis": "Das Bild ist im Chat bereits sichtbar. Nicht erneut einbetten und keine Links ausgeben.",
             "images": [i["url"] for i in images]},
            ensure_ascii=False,
        )
