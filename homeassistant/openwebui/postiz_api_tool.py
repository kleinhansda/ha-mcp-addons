"""
title: Postiz API
author: David
version: 1.1.0
description: Selbst gehostetes Postiz per Public API: Kanäle listen, Posts lesen, als Entwurf anlegen, planen oder sofort veröffentlichen (nur nach Davids Freigabe im Chat), Medien aus freigegebenen Ordnern hochladen, Posts löschen (nur auf Davids Wort). API-Schlüssel nur im Ventil.
"""

# Postiz Public API (https://docs.postiz.com/public-api): Basis <domain>/api/public/v1, Header
# „Authorization: <API-Schlüssel>“ ohne Bearer. Entwürfe (typ draft) legt das Modell frei an;
# planen und sofort veröffentlichen nur, wenn Davids letzte Chatnachricht eine Freigabe ist und der
# Text genau so in der Antwort davor stand (wie beim Werkzeug „Mail senden approval“).

import datetime as dt
import json
import mimetypes
import os
import re
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel, Field

ZUSTIMMUNG = {"ja", "jap", "jo", "ok", "okay", "passt", "posten", "poste", "veröffentlichen", "veröffentliche",
              "planen", "plane", "einplanen", "raus", "yes", "yep", "yeah", "sure", "post", "publish", "schedule", "go"}
FUELLWOERTER = {"bitte", "gerne", "gern", "so", "jetzt", "los", "sie", "es", "ihn", "den", "die", "das", "post",
                "beitrag", "damit", "danke", "gut", "genau", "please", "it", "now", "the", "ahead", "thanks", "you"}
LOESCHEN_RE = re.compile(r"lösch|loesch|entfern|weg damit|delete|remove", re.I)
MAX_FREIGABE = 60
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MEDIEN_ENDUNGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"}
VERBRAUCHT: set = set()


def _text(inhalt: Any) -> str:
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        return "\n".join(t.get("text", "") for t in inhalt if isinstance(t, dict) and t.get("type") == "text")
    return ""


def _norm(s: str) -> str:
    s = s.replace(" ", " ").replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"').replace("„", '"')
    s = re.sub(r"[*_`#>|\\]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def originalnachricht(metadata: Optional[dict], messages: list) -> str:
    """Davids letzte Nachricht wie getippt (__metadata__.user_message), sonst Text nach </context>."""
    um = (metadata or {}).get("user_message")
    if isinstance(um, dict) and isinstance(um.get("content"), (str, list)):
        return _text(um.get("content"))
    users = [m for m in messages or [] if isinstance(m, dict) and m.get("role") == "user"]
    return (_text(users[-1].get("content")) if users else "").rsplit("</context>", 1)[-1]


def ist_freigabe(nachricht: str) -> bool:
    n = nachricht.strip()
    if not n or len(n) > MAX_FREIGABE:
        return False
    woerter = re.findall(r"[a-zäöüß]+", n.lower())
    return bool(woerter) and set(woerter) <= (ZUSTIMMUNG | FUELLWOERTER) and bool(set(woerter) & ZUSTIMMUNG)


def gezeigte_fassung(messages: list) -> str:
    """Alle Antworten des Modells zwischen Davids vorletzter und letzter Nachricht."""
    idx = [i for i, m in enumerate(messages or []) if isinstance(m, dict) and m.get("role") == "user"]
    if not idx:
        return ""
    vorher = idx[-2] if len(idx) > 1 else -1
    return _norm("\n".join(_text(m.get("content")) for m in messages[vorher + 1:idx[-1]]
                           if isinstance(m, dict) and m.get("role") == "assistant"))


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(default="http://192.168.10.40:4007/api/public/v1",
                              description="Public API von Postiz: <Adresse>/api/public/v1 (intern oder https://postiz.ddsk.cloud/api/public/v1)")
        api_key: str = Field(default="", description="API-Schlüssel aus Postiz (Einstellungen → Public API)",
                             json_schema_extra={"input": {"type": "password"}})
        medien_ordner: str = Field(default="/share/hannesbraeu,/share/openwebui/inbox",
                                   description="Kommagetrennt: nur Dateien darunter darf medien_hochladen senden")
        max_mb: int = Field(default=50, description="Größte Mediendatei in MB")
        max_zeichen: int = Field(default=6000, description="Antwort an das Modell kürzen")

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------ HTTP

    async def _api(self, methode: str, pfad: str, json_daten: Any = None, form: Any = None,
                   params: Optional[dict] = None) -> tuple[int, Any]:
        if not self.valves.api_key.strip():
            raise ValueError("Ventil api_key ist leer (Postiz: Einstellungen → Public API). David muss ihn eintragen.")
        url = self.valves.base_url.rstrip("/") + pfad
        kopf = {"Authorization": self.valves.api_key.strip()}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
            async with s.request(methode, url, json=json_daten, data=form, params=params, headers=kopf) as r:
                text = await r.text()
                try:
                    return r.status, json.loads(text) if text.strip() else None
                except ValueError:
                    return r.status, text

    def _kurz(self, obj: Any) -> str:
        t = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
        n = self.valves.max_zeichen
        return t if len(t) <= n else t[:n] + f" […{len(t)} Zeichen, gekürzt]"

    async def _kanaele(self) -> list:
        status, daten = await self._api("GET", "/integrations")
        if status != 200 or not isinstance(daten, list):
            raise ValueError(f"Kanäle nicht lesbar: HTTP {status}: {self._kurz(daten)}")
        return daten

    # ------------------------------------------------------------ Werkzeuge

    async def kanaele_listen(self) -> str:
        """
        Verbundene Kanäle in Postiz (Instagram, Facebook …) mit ID, Plattform und Name. Die ID braucht post_anlegen.
        :return: eine Zeile je Kanal
        """
        try:
            kanaele = await self._kanaele()
        except Exception as e:
            return f"Fehler: {e}"
        if not kanaele:
            return "Keine Kanäle verbunden. David verbindet sie in Postiz unter „Kanal hinzufügen“."
        return "\n".join(f"{k.get('id')} | {k.get('identifier')} | {k.get('name')}"
                         + (" | deaktiviert" if k.get("disabled") else "") for k in kanaele)

    async def posts_lesen(self, start: str = "", ende: str = "") -> str:
        """
        Posts in einem Zeitraum (UTC, ISO 8601, z. B. 2026-11-24T00:00:00.000Z). Ohne Angaben: heute bis in 30 Tagen.
        :param start: Beginn (UTC ISO)
        :param ende: Ende (UTC ISO)
        :return: Posts als JSON (gekürzt)
        """
        jetzt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        start = start or jetzt.replace(hour=0, minute=0, second=0).isoformat().replace("+00:00", ".000Z")
        ende = ende or (jetzt + dt.timedelta(days=30)).isoformat().replace("+00:00", ".000Z")
        try:
            status, daten = await self._api("GET", "/posts", params={"startDate": start, "endDate": ende})
        except Exception as e:
            return f"Fehler: {e}"
        return f"HTTP {status}: {self._kurz(daten)}"

    async def medien_hochladen(self, dateipfad: str) -> str:
        """
        Bild oder Video aus einem freigegebenen Ordner (z. B. /share/hannesbraeu/…) zu Postiz hochladen.
        Erlaubt: jpg, jpeg, png, webp, gif, mp4, mov. Für Instagram am besten JPEG.
        :param dateipfad: absoluter Pfad der Datei
        :return: id und path für post_anlegen (bilder)
        """
        echt = os.path.realpath(dateipfad or "")
        erlaubt = [os.path.realpath(o.strip()) for o in self.valves.medien_ordner.split(",") if o.strip()]
        if not any(echt.startswith(o + os.sep) for o in erlaubt):
            return f"Fehler: nur Dateien unter {', '.join(erlaubt)} (Ventil medien_ordner)."
        if os.path.splitext(echt)[1].lower() not in MEDIEN_ENDUNGEN:
            return f"Fehler: nur {', '.join(sorted(MEDIEN_ENDUNGEN))}."
        if not os.path.isfile(echt):
            return f"Fehler: Datei nicht gefunden: {dateipfad}"
        if os.path.getsize(echt) > self.valves.max_mb * 1024 * 1024:
            return f"Fehler: größer als {self.valves.max_mb} MB."
        try:
            with open(echt, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("file", f.read(), filename=os.path.basename(echt),
                               content_type=mimetypes.guess_type(echt)[0] or "application/octet-stream")
            status, daten = await self._api("POST", "/upload", form=form)
        except Exception as e:
            return f"Fehler: {e}"
        if status not in (200, 201) or not isinstance(daten, dict) or not daten.get("path"):
            return f"Fehler beim Hochladen: HTTP {status}: {self._kurz(daten)}"
        return json.dumps({"id": daten.get("id"), "path": daten.get("path")}, ensure_ascii=False)

    async def post_anlegen(
        self,
        typ: str,
        kanal_ids: list[str],
        text: str,
        datum: str = "",
        bilder: Optional[list[dict]] = None,
        post_art: str = "post",
        __messages__: Optional[list] = None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Post in Postiz anlegen, gleicher Text für alle Kanäle. typ „draft“ (Entwurf, Standard) legt nur an.
        „schedule“ (zum datum) und „now“ (sofort) veröffentlichen und gehen nur, wenn der Post zuvor vollständig im
        Chat gezeigt wurde (Kanäle, Zeitpunkt, Text, Bilder) und Davids letzte Nachricht die Freigabe ist („ja“, „posten“).
        :param typ: draft, schedule oder now
        :param kanal_ids: IDs aus kanaele_listen, z. B. ["abc123"]
        :param text: Text des Posts, bei schedule/now genau wie im Chat gezeigt
        :param datum: Zeitpunkt in UTC, ISO 8601 (z. B. 2026-11-27T17:00:00.000Z); bei now leer
        :param bilder: Liste aus medien_hochladen, z. B. [{"id": "…", "path": "…"}]
        :param post_art: Instagram: post oder story
        :return: Ergebnis mit Post-ID(s)
        """
        typ = (typ or "draft").strip().lower()
        if typ not in ("draft", "schedule", "now"):
            return "Fehler: typ ist draft, schedule oder now."
        if not kanal_ids or not all(ID_RE.match(str(k)) for k in kanal_ids):
            return "Fehler: kanal_ids als Liste von IDs aus kanaele_listen."
        if not (text or "").strip():
            return "Fehler: text ist leer."
        if typ != "now":
            try:
                zeit = dt.datetime.fromisoformat((datum or "").replace("Z", "+00:00"))
            except ValueError:
                return "Fehler: datum als UTC ISO 8601, z. B. 2026-11-27T17:00:00.000Z."
            if zeit.tzinfo is None:
                return "Fehler: datum mit Zeitzone (Z für UTC)."
        else:
            datum = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        bilder = [{"id": str(b.get("id")), "path": str(b.get("path"))} for b in (bilder or []) if isinstance(b, dict)]

        if typ in ("schedule", "now"):
            freigabe = originalnachricht(__metadata__, __messages__ or [])
            if not ist_freigabe(freigabe):
                return ("Nicht veröffentlicht: Davids letzte Nachricht ist keine Freigabe. Post vollständig im Chat zeigen "
                        "(Kanäle, Zeitpunkt, Text, Bild) und fragen; erst nach „ja“ oder „posten“ erneut aufrufen. "
                        "Ohne Freigabe nur typ draft.")
            if _norm(text) not in gezeigte_fassung(__messages__ or []):
                return "Nicht veröffentlicht: der Text weicht von der gezeigten Fassung ab. Fassung zeigen und erneut fragen."
            schluessel = json.dumps([str((__metadata__ or {}).get("chat_id")), freigabe, _norm(text)])
            if schluessel in VERBRAUCHT:
                return "Nicht veröffentlicht: diese Freigabe wurde schon verwendet. Für einen weiteren Post erneut fragen."

        try:
            kanaele = {k.get("id"): k for k in await self._kanaele()}
        except Exception as e:
            return f"Fehler: {e}"
        posts = []
        for kid in kanal_ids:
            k = kanaele.get(kid)
            if not k:
                return f"Fehler: Kanal {kid} gibt es nicht (kanaele_listen)."
            art = k.get("identifier") or ""
            settings: dict = {"__type": art}
            if art.startswith("instagram"):
                settings.update({"post_type": "story" if post_art == "story" else "post", "collaborators": []})
            posts.append({"integration": {"id": kid}, "value": [{"content": text, "image": bilder}], "settings": settings})
        body = {"type": typ, "date": datum, "shortLink": False, "tags": [], "posts": posts}
        try:
            status, daten = await self._api("POST", "/posts", json_daten=body)
        except Exception as e:
            return f"Fehler: {e}"
        if status not in (200, 201):
            return f"Fehler: HTTP {status}: {self._kurz(daten)}"
        if typ in ("schedule", "now"):
            VERBRAUCHT.add(schluessel)
        was = {"draft": "Als Entwurf angelegt", "schedule": f"Geplant für {datum}", "now": "Veröffentlicht"}[typ]
        return f"{was}: {self._kurz(daten)}"

    async def post_loeschen(self, post_id: str, __messages__: Optional[list] = None,
                            __metadata__: Optional[dict] = None) -> str:
        """
        Post löschen (mit allen Posts derselben Gruppe). Nur wenn Davids letzte Nachricht das Löschen verlangt.
        :param post_id: ID des Posts aus posts_lesen oder post_anlegen
        :return: Ergebnis
        """
        if not ID_RE.match(post_id or ""):
            return "Fehler: ungültige Post-ID."
        if not LOESCHEN_RE.search(originalnachricht(__metadata__, __messages__ or [])):
            return "Nicht gelöscht: David hat in seiner letzten Nachricht nicht gesagt, dass der Post gelöscht werden soll."
        try:
            status, daten = await self._api("DELETE", f"/posts/{post_id}")
        except Exception as e:
            return f"Fehler: {e}"
        return ("Gelöscht." if status in (200, 204) else f"Fehler: HTTP {status}: {self._kurz(daten)}")
