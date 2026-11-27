"""
title: Mail senden approval
author: David
version: 1.4.0
description: Sendet eine Mail oder Antwort über smtp-mcp (mailbox.org MCP), nur nach Freigabe im Chat: Davids letzte Nachricht muss „ja“, „senden“, „yes“ oder „send“ sein, und Absender, Empfänger, Betreff und Text müssen genau so in der Antwort davor stehen. Kein Dialog. Absender bei Antworten automatisch: die Adresse, an die die Mail ging. Räumt passende Entwürfe danach in den Papierkorb; verworfene Entwürfe mit entwurf_verwerfen.
"""

# Ersetzt für die Modelle das MCP-Werkzeug mboxsend. smtp-mcp fragt vor jedem Versand per
# Rückfrage (elicitation) nach; dieses Werkzeug beantwortet sie selbst, aber erst, nachdem es im
# Chatverlauf (__messages__) geprüft hat, dass David den gezeigten Text freigegeben hat. Eine
# Anweisung in einer Mail oder Datei kann keine Nachricht von David erzeugen, deshalb ersetzt diese
# Prüfung den Dialog. Jede Freigabe gilt für genau einen Versand.
# Absender: bei Antworten fragt das Werkzeug imap-mcp (reply_sender), an welche der eingetragenen
# Absenderadressen die beantwortete Mail ging, und sendet von dort; sonst gilt die erste Adresse. Die
# Adresse muss wie Empfänger und Text in der gezeigten Fassung stehen („Von: …“).
# Entwürfe: nach dem Senden und mit entwurf_verwerfen werden Entwürfe mit genau diesem Betreff und
# diesen Empfängern aus dem Entwürfe-Ordner in den Papierkorb verschoben (wiederherstellbar, nie gelöscht).

import hashlib
import json
import re
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel, Field

# Wörter, aus denen eine Freigabe bestehen darf; mindestens eines aus ZUSTIMMUNG muss vorkommen.
ZUSTIMMUNG = {"ja", "jap", "jo", "ok", "okay", "passt", "senden", "sende", "absenden", "abschicken",
              "verschicken", "schick", "schicke", "schicken", "raus",
              "yes", "yep", "yeah", "sure", "send", "approve", "approved", "go"}
FUELLWOERTER = {"bitte", "gerne", "gern", "so", "jetzt", "los", "sie", "es", "die", "mail", "ab",
                "damit", "danke", "gut", "genau", "nachricht", "antwort", "du", "kannst",
                "please", "it", "now", "the", "email", "message", "reply", "ahead", "out", "thanks", "thank", "you"}
VERWERFEN_RE = re.compile(r"verw[ie]rf|lösch|loesch|wegwerf|weg damit|entsorg|papierkorb|discard|delete|trash|bin it", re.I)
MAX_ENTWUERFE = 5          # höchstens so viele Entwürfe je Aufruf verschieben
MAX_FREIGABE = 60          # Zeichen; längere Nachrichten sind keine reine Freigabe
VERBRAUCHT: dict[str, str] = {}   # Freigabe-Schlüssel -> Message-ID (nur im Speicher)


def _text(inhalt: Any) -> str:
    """Inhalt einer Chat-Nachricht als Text (String oder Liste von Teilen)."""
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        return "\n".join(t.get("text", "") for t in inhalt if isinstance(t, dict) and t.get("type") == "text")
    return ""


def _norm(s: str) -> str:
    """Für den Vergleich: Markdown-Zeichen weg, typografische Zeichen vereinheitlichen, Leerraum zu einem Leerzeichen."""
    s = s.replace(" ", " ").replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"').replace("„", '"')
    s = re.sub(r"[*_`#>|\\]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def ist_freigabe(nachricht: str) -> bool:
    n = nachricht.strip()
    if not n or len(n) > MAX_FREIGABE:
        return False
    woerter = re.findall(r"[a-zäöüß]+", n.lower())
    if not woerter or not set(woerter) <= (ZUSTIMMUNG | FUELLWOERTER):
        return False
    return bool(set(woerter) & ZUSTIMMUNG)


def originalnachricht(metadata: Optional[dict], messages: list) -> str:
    """Davids letzte Nachricht so, wie er sie getippt hat. Open WebUI setzt Wissen (RAG) und
    Filter-Zusätze vor bzw. hinter die Nachricht in __messages__; das Original steht in
    __metadata__["user_message"] (vom Browser, nicht vom Modell). Ohne Metadaten: Text nach dem
    letzten </context>."""
    um = (metadata or {}).get("user_message")
    if isinstance(um, dict) and isinstance(um.get("content"), (str, list)):
        return _text(um.get("content"))
    users = [m for m in messages or [] if isinstance(m, dict) and m.get("role") == "user"]
    t = _text(users[-1].get("content")) if users else ""
    return t.rsplit("</context>", 1)[-1]


def pruefe_chat(messages: list, an: list, cc: list, bcc: list, betreff: str, text: str,
                metadata: Optional[dict] = None, absender: str = "") -> tuple[Optional[str], str]:
    """(Fehler oder None, Schlüssel der Freigabe). Letzte Nachricht von David = Freigabe,
    alle Antworten des Modells seit der Nachricht davor = gezeigte Fassung."""
    idx = [i for i, m in enumerate(messages or []) if isinstance(m, dict) and m.get("role") == "user"]
    if not idx:
        return "Keine Nachricht von David im Verlauf.", ""
    letzte = idx[-1]
    freigabe = originalnachricht(metadata, messages)
    if not ist_freigabe(freigabe):
        return ("Nicht gesendet: Davids letzte Nachricht ist keine Freigabe (erwartet z. B. „ja“, „senden“, "
                "„yes“, „send“). Mail vollständig im Chat zeigen, „Senden?“ fragen und erst danach erneut aufrufen."), ""
    vorher = idx[-2] if len(idx) > 1 else -1
    gezeigt = _norm("\n".join(_text(m.get("content")) for m in messages[vorher + 1:letzte]
                              if isinstance(m, dict) and m.get("role") == "assistant"))
    fehlt = [f"Empfänger {a}" for a in [*an, *cc, *bcc] if a.lower() not in gezeigt]
    if absender and absender.lower() not in gezeigt:
        fehlt.append(f"Absender {absender} (als „Von: {absender}“ zeigen)")
    if _norm(betreff) not in gezeigt:
        fehlt.append("Betreff")
    if _norm(text) not in gezeigt:
        fehlt.append("Text (muss Wort für Wort so in der Antwort davor stehen)")
    if fehlt:
        return ("Nicht gesendet: weicht von der Fassung ab, die David freigegeben hat (" + ", ".join(fehlt) +
                "). Die zu sendende Fassung vollständig zeigen und erneut fragen."), ""
    schluessel = hashlib.sha256(json.dumps([len(idx), freigabe, gezeigt[-2000:]]).encode()).hexdigest()
    return None, schluessel


def _ergebnis(antwort: dict) -> tuple[Optional[dict], str]:
    """(structuredContent oder None, Fehlertext) aus einer tools/call-Antwort."""
    if antwort.get("error"):
        return None, str(antwort["error"].get("message"))
    erg = antwort.get("result") or {}
    sc = erg.get("structuredContent")
    text = " ".join(c.get("text", "") for c in erg.get("content") or [] if isinstance(c, dict))
    if erg.get("isError") or not isinstance(sc, dict):
        return None, text[:600] or "keine Antwort"
    return sc, ""


async def _sse(antwort: aiohttp.ClientResponse):
    """JSON-RPC-Nachrichten aus einem SSE-Stream."""
    daten: list[str] = []
    async for roh in antwort.content:
        zeile = roh.decode("utf-8", "replace").rstrip("\r\n")
        if zeile.startswith("data:"):
            daten.append(zeile[5:].lstrip())
        elif zeile == "" and daten:
            try:
                yield json.loads("\n".join(daten))
            except ValueError:
                pass
            daten = []


async def _antwort(r: aiohttp.ClientResponse, rid: Any) -> Optional[dict]:
    if "text/event-stream" in r.headers.get("Content-Type", ""):
        async for m in _sse(r):
            if m.get("id") == rid:
                return m
        return None
    t = await r.text()
    return json.loads(t) if t.strip() else None


class Tools:
    class Valves(BaseModel):
        brucke_url: str = Field(
            default="http://be60cb4b-mailbox-org-mcp:9082/mcp",
            description="Interne SMTP-Brücke der App mailbox.org MCP (Port 9082 = smtp).",
        )
        imap_url: str = Field(
            default="http://be60cb4b-mailbox-org-mcp:9081/mcp",
            description="Interne Mail-Brücke (Port 9081 = imap), zum Aufräumen von Entwürfen. Leer = aus.",
        )
        token: str = Field(default="", description="Token für internen Zugriff (Option internal_token der App).",
                           json_schema_extra={"input": {"type": "password"}})
        zeitlimit: int = Field(default=90, description="Sekunden bis zum Abbruch.")

    def __init__(self):
        self.valves = self.Valves()

    async def _mcp(self, url: str, werkzeug: str, args: dict, muss_enthalten: list) -> dict:
        """Ein Werkzeug über die Brücke aufrufen. Eine Rückfrage wird nur angenommen, wenn ihr Text
        alle Werte aus muss_enthalten nennt (Empfänger bzw. Quell- und Zielordner)."""
        kopf = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.valves.token:
            kopf["Authorization"] = "Bearer " + self.valves.token
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.zeitlimit)) as s:
            async with s.post(url, headers=kopf, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {"elicitation": {}},
                    "clientInfo": {"name": "owui-mail-senden", "version": "1.0.0"}}}) as r:
                if r.status != 200:
                    raise RuntimeError(f"Brücke: HTTP {r.status} bei initialize")
                sitzung = r.headers.get("Mcp-Session-Id")
                await _antwort(r, 1)
            if sitzung:
                kopf["Mcp-Session-Id"] = sitzung
            async with s.post(url, headers=kopf, json={"jsonrpc": "2.0", "method": "notifications/initialized"}) as r:
                await r.read()
            async with s.post(url, headers=kopf, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": werkzeug, "arguments": args}}) as r:
                if r.status != 200:
                    raise RuntimeError(f"Brücke: HTTP {r.status} bei {werkzeug}")
                if "text/event-stream" not in r.headers.get("Content-Type", ""):
                    return json.loads(await r.text())
                async for m in _sse(r):
                    if m.get("method") == "elicitation/create":
                        p = m.get("params") or {}
                        frage = p.get("message") or ""
                        # Nur die Rückfrage zu genau diesem Auftrag annehmen
                        passt = bool(muss_enthalten) and all(a.lower() in frage.lower() for a in muss_enthalten)
                        props = ((p.get("requestedSchema") or {}).get("properties") or {})
                        inhalt = {k: True for k, v in props.items() if (v or {}).get("type") == "boolean"}
                        ergebnis = {"action": "accept", "content": inhalt} if passt and inhalt else {"action": "decline"}
                        async with s.post(url, headers=kopf, json={"jsonrpc": "2.0", "id": m.get("id"), "result": ergebnis}) as r2:
                            await r2.read()
                    elif m.get("id") == 2:
                        return m
        raise RuntimeError("Brücke hat den Aufruf ohne Ergebnis beendet")

    async def _absender(self, in_reply_to: Optional[str]) -> str:
        """Absender laut imap-mcp (reply_sender): bei Antworten die eingetragene Adresse, an die die Mail
        ging, sonst der Standard. Ohne Mail-Brücke oder ältere App: leer (smtp-mcp nimmt SMTP_FROM)."""
        if not self.valves.imap_url:
            return ""
        try:
            a = await self._mcp(self.valves.imap_url, "reply_sender", {"in_reply_to": in_reply_to} if in_reply_to else {}, [])
        except Exception:
            return ""
        sc, _ = _ergebnis(a)
        return str((sc or {}).get("from") or "").strip().lower()

    async def _ordner(self) -> tuple[str, str]:
        """(Entwürfe, Papierkorb) laut Server (special-use), sonst Drafts/Trash."""
        a = await self._mcp(self.valves.imap_url, "list_mailboxes", {}, [])
        sc, _ = _ergebnis(a)
        entwuerfe, papierkorb = "Drafts", "Trash"
        for b in (sc or {}).get("mailboxes") or []:
            su = (b.get("specialUse") or "").lower()
            if su == "\\drafts":
                entwuerfe = b.get("path") or entwuerfe
            elif su == "\\trash":
                papierkorb = b.get("path") or papierkorb
        return entwuerfe, papierkorb

    async def _entwuerfe_wegraeumen(self, an: list, betreff: str) -> str:
        """Entwürfe mit genau diesem Betreff und allen Empfängern in den Papierkorb. Rückgabe: Satz für das Modell."""
        if not self.valves.imap_url or not an or not betreff.strip():
            return ""
        entwuerfe, papierkorb = await self._ordner()
        a = await self._mcp(self.valves.imap_url, "list_messages",
                            {"mailbox": entwuerfe, "to": an[0], "subject": betreff[:200], "limit": 20}, [])
        sc, fehler = _ergebnis(a)
        if sc is None:
            return f"Entwürfe nicht geprüft: {fehler}"
        uids = [m["uid"] for m in sc.get("messages") or []
                if isinstance(m.get("uid"), int)
                and (m.get("subject") or "").strip().lower() == betreff.strip().lower()
                and all(x.lower() in (m.get("to") or "").lower() for x in an)][:MAX_ENTWUERFE]
        if not uids:
            return "Kein passender Entwurf im Ordner Entwürfe."
        a = await self._mcp(self.valves.imap_url, "move_messages",
                            {"uids": uids, "mailbox": entwuerfe, "destination": papierkorb}, [entwuerfe, papierkorb])
        sc, fehler = _ergebnis(a)
        if sc is None:
            return f"Entwurf nicht verschoben: {fehler}"
        return f"{len(uids)} Entwurf/Entwürfe mit diesem Betreff in den Papierkorb ({papierkorb}) verschoben."

    async def entwurf_verwerfen(
        self,
        an: list[str],
        betreff: str,
        __messages__: Optional[list] = None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Verschiebt einen verworfenen Mail-Entwurf aus dem Ordner Entwürfe in den Papierkorb (wiederherstellbar).
        Nur aufrufen, wenn David den Entwurf verwerfen oder löschen will. Trifft nur Entwürfe mit genau
        diesem Betreff und diesen Empfängern. Nach mail_senden ist das nicht nötig, das räumt selbst auf.
        :param an: Empfänger des Entwurfs, z. B. ["name@example.de"].
        :param betreff: Betreff des Entwurfs, genau wie gespeichert (bei Antworten mit „Re: “).
        """
        nachricht = originalnachricht(__metadata__, __messages__ or [])
        if not VERWERFEN_RE.search(nachricht or ""):
            return "Nicht verschoben: David hat in seiner letzten Nachricht nicht gesagt, dass der Entwurf weg soll (z. B. „verwerfen“, „löschen“)."
        try:
            return await self._entwuerfe_wegraeumen(list(an or []), betreff)
        except Exception as e:
            return f"Nicht verschoben: {e}"

    async def mail_senden(
        self,
        an: list[str],
        betreff: str,
        text: str,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[list[str]] = None,
        absender: Optional[str] = None,
        __messages__: Optional[list] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> str:
        """
        Sendet eine Mail oder Antwort von Davids mailbox.org-Adresse. Nur aufrufen, nachdem die Mail
        vollständig im Chat gezeigt (Von, An, Cc, Betreff, Text) und David mit „ja“/„senden“ (oder „yes“/„send“) geantwortet hat.
        Absender, Empfänger, Betreff und Text müssen genau so in der vorigen Antwort stehen, sonst wird nicht gesendet.
        Den Absender vorher mit reply_sender (mbox, bei Antworten mit in_reply_to) ermitteln und als „Von:“ zeigen.
        :param an: Empfänger, nur E-Mail-Adressen, z. B. ["name@example.de"].
        :param betreff: Betreff, bei Antworten mit „Re: “.
        :param text: Mailtext (reiner Text), genau wie im Chat gezeigt.
        :param cc: Kopie-Empfänger.
        :param bcc: Blindkopie-Empfänger.
        :param in_reply_to: Bei Antworten: Message-ID der beantworteten Mail aus get_message.
        :param references: Bei Antworten: References-Liste der beantworteten Mail aus get_message.
        :param absender: Nur wenn David ausdrücklich eine andere seiner Adressen will; sonst leer lassen (automatisch).
        """
        an, cc, bcc = list(an or []), list(cc or []), list(bcc or [])
        if not an:
            return "Nicht gesendet: kein Empfänger."
        absender = (absender or "").strip().lower() or await self._absender(in_reply_to)
        fehler, schluessel = pruefe_chat(__messages__ or [], an, cc, bcc, betreff, text, __metadata__, absender)
        if fehler:
            return fehler
        chat = str((__metadata__ or {}).get("chat_id") or "")
        schluessel = hashlib.sha256((chat + schluessel).encode()).hexdigest()
        if schluessel in VERBRAUCHT:
            return f"Nicht gesendet: diese Freigabe wurde schon verwendet (Message-ID {VERBRAUCHT[schluessel]}). Für einen weiteren Versand erneut fragen."

        args: dict[str, Any] = {"to": an, "body": text}
        if absender:
            args["from"] = absender
        if cc:
            args["cc"] = cc
        if bcc:
            args["bcc"] = bcc
        if in_reply_to:
            werkzeug = "reply_mail"
            args.update({"original_subject": betreff, "subject": betreff, "in_reply_to": in_reply_to})
            if references:
                args["references"] = references
        else:
            werkzeug = "send_mail"
            args["subject"] = betreff

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Sende an {', '.join(an)}", "done": False}})
        try:
            antwort = await self._mcp(self.valves.brucke_url, werkzeug, args, [*an, *cc, *bcc])
        except Exception as e:
            return f"Nicht gesendet: {e}"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "", "done": True}})

        if antwort.get("error"):
            return f"Nicht gesendet: {antwort['error'].get('message')}"
        erg = antwort.get("result") or {}
        sc = erg.get("structuredContent") or {}
        if erg.get("isError") or not sc:
            t = " ".join(c.get("text", "") for c in erg.get("content") or [] if isinstance(c, dict))
            return f"Nicht gesendet: {t[:600] or 'keine Antwort von smtp-mcp'}"
        VERBRAUCHT[schluessel] = sc.get("message_id", "?")
        if sc.get("already_sent"):
            return f"Nicht erneut gesendet: genau diese Mail ging schon raus (Message-ID {sc.get('message_id')})."
        teile = [f"Gesendet{' von ' + absender if absender else ''} an {', '.join(sc.get('accepted') or an)}",
                 f"Message-ID {sc.get('message_id')}"]
        notiz = str(sc.get("note") or "")
        if "copy was saved to the Sent folder" in notiz:
            teile.append("Kopie in „Gesendet“ abgelegt")
        elif "saving a copy to the Sent folder failed" in notiz:
            teile.append("Kopie in „Gesendet“ fehlgeschlagen: " + notiz.split("failed:", 1)[-1].strip()[:200])
        if sc.get("rejected"):
            teile.append(f"ABGELEHNT vom Server (nicht zugestellt): {', '.join(sc['rejected'])}")
        try:
            aufgeraeumt = await self._entwuerfe_wegraeumen(an, betreff)
        except Exception as e:   # Versand ist erfolgt; Aufräumen darf ihn nie als Fehler melden
            aufgeraeumt = f"Entwürfe nicht geprüft: {e}"
        return "; ".join(teile) + "." + (f" {aufgeraeumt}" if aufgeraeumt else "")
