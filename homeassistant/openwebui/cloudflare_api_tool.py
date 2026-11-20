"""
title: Cloudflare-API
author: David
version: 1.0.0
description: Cloudflare-API (client/v4) mit API-Token: Zonen, DNS-Einträge, Tunnel, Zugriffsregeln, Workers lesen und nach Freigabe ändern; ein Aufruf oder viele in einem Schritt. Löschen per Ventil.
"""

# Nachfolger von cloudflare_api2 (lud seine Ventile nie, blockierende Aufrufe, falscher Import).
# Aus der Vorlage owui-werkzeug/rest_api.py; Cloudflare meldet Fehler im Feld errors (success=false).

import json
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, Field

# {{n:pfad.im.json}} = Wert aus der Antwort von Aufruf n (ab 0), z. B. {{0:data.id}}
VERWEIS_RE = re.compile(r"\{\{(\d+):([\w.\-]*)\}\}")


def _wert(daten: Any, pfad: str) -> Any:
    for teil in [t for t in pfad.split(".") if t]:
        if isinstance(daten, list) and teil.lstrip("-").isdigit():
            daten = daten[int(teil)]
        elif isinstance(daten, dict) and teil in daten:
            daten = daten[teil]
        else:
            raise KeyError(pfad)
    return daten


def _einsetzen(x: Any, ergebnisse: list) -> Any:
    if isinstance(x, str):
        def holen(m):
            i = int(m.group(1))
            if i >= len(ergebnisse) or ergebnisse[i] is None:
                raise KeyError(m.group(0))
            return _wert(ergebnisse[i], m.group(2))
        ganz = VERWEIS_RE.fullmatch(x)
        return holen(ganz) if ganz else VERWEIS_RE.sub(lambda m: str(holen(m)), x)
    if isinstance(x, list):
        return [_einsetzen(e, ergebnisse) for e in x]
    if isinstance(x, dict):
        return {k: _einsetzen(e, ergebnisse) for k, e in x.items()}
    return x


class Tools:
    class Valves(BaseModel):
        basis_url: str = Field(default="https://api.cloudflare.com/client/v4", description="Adresse ohne / am Ende")
        api_schluessel: str = Field(default="", description="Cloudflare-API-Token (My Profile → API Tokens), nur mit den nötigen Rechten, z. B. Zone:DNS Edit")
        erlaubte_pfade: str = Field(default="/zones,/accounts,/user/tokens/verify,/memberships", description="Kommagetrennte Pfad-Anfänge, die aufgerufen werden dürfen")
        schreiben_erlaubt: bool = Field(default=True, description="POST, PUT und PATCH zulassen")
        loeschen_erlaubt: bool = Field(default=False, description="DELETE zulassen")
        max_zeichen: int = Field(default=12000, description="Antwort an das Modell kürzen")
        timeout: int = Field(default=30)

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()

    # Hilfsmethoden beginnen mit _, sonst werden sie zu Werkzeugen für das Modell.
    def _pruefen(self, methode: str, pfad: str) -> Optional[str]:
        v = self.valves
        if not v.api_schluessel:
            return "Kein Token im Ventil api_schluessel. David muss es in den Ventilen des Werkzeugs „Cloudflare-API“ eintragen."
        if methode not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return f"Methode {methode} nicht erlaubt."
        if methode in ("POST", "PUT", "PATCH") and not v.schreiben_erlaubt:
            return "Schreiben ist abgeschaltet (Ventil schreiben_erlaubt)."
        if methode == "DELETE" and not v.loeschen_erlaubt:
            return "Löschen ist abgeschaltet (Ventil loeschen_erlaubt)."
        teile = urlsplit(pfad or "")
        if teile.scheme or teile.netloc or not teile.path.startswith("/") or ".." in teile.path:
            return "pfad muss mit / beginnen, ohne Adresse und ohne '..'."
        erlaubt = [p.strip() for p in v.erlaubte_pfade.split(",") if p.strip()]
        if not any(teile.path.startswith(p) for p in erlaubt):
            return "Pfad nicht freigegeben. Erlaubt: " + ", ".join(erlaubt)
        return None

    async def _senden(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten: Any) -> tuple[int, str]:
        v = self.valves
        kopf = {"Authorization": "Bearer " + v.api_schluessel, "Accept": "application/json"}
        async with s.request(methode, v.basis_url.rstrip("/") + pfad, headers=kopf,
                             json=daten if daten not in (None, "") and methode != "GET" else None) as r:
            text = (await r.text()).replace(v.api_schluessel, "***")
            status = r.status
            try:
                d = json.loads(text)
                if isinstance(d, dict) and d.get("success") is False and status < 400:
                    status = 400  # Cloudflare meldet manche Fehler mit HTTP 200
                if isinstance(d, dict):
                    # Nur das Nötige: Ergebnis, Fehler, Seiteninfo
                    d = {k: d[k] for k in ("result", "errors", "messages", "result_info") if d.get(k) not in (None, [], {})}
                    text = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            except ValueError:
                pass
            return status, text

    @staticmethod
    def _json(daten: Any) -> Any:
        return json.loads(daten) if isinstance(daten, str) and daten.strip() else daten

    async def cloudflare_api(self, methode: str, pfad: str, daten: Optional[Any] = None, __event_emitter__=None) -> str:
        """
        Ruft die Cloudflare-API einmal auf. Beispiele: GET /user/tokens/verify, GET /zones?name=ddsk.cloud, GET /zones/<zone_id>/dns_records?per_page=100, POST /zones/<zone_id>/dns_records {"type":"CNAME","name":"x.ddsk.cloud","content":"…","proxied":true}, GET /accounts/<id>/cfd_tunnel. Mehrere Aufrufe: cloudflare_api_mehrere.
        :param methode: GET, POST, PUT, PATCH oder DELETE
        :param pfad: Pfad ab der Server-Wurzel, beginnend mit /, Query-Parameter direkt anhängen
        :param daten: optionaler JSON-Inhalt (Objekt) für POST, PUT, PATCH
        :return: HTTP-Status und Antwort (gekürzt)
        """
        methode = (methode or "GET").upper()
        fehler = self._pruefen(methode, pfad)
        if fehler:
            return "Fehler: " + fehler
        try:
            daten = self._json(daten)
        except ValueError:
            return "Fehler: daten ist kein gültiges JSON."
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Cloudflare: {methode} {pfad}", "done": False}})
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout)) as s:
                status, text = await self._senden(s, methode, pfad, daten)
        except Exception as e:
            return f"Fehler beim Aufruf: {type(e).__name__}: {e}"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Cloudflare: {methode} {pfad}", "done": True}})
        n = self.valves.max_zeichen
        return f"HTTP {status}\n" + (text if len(text) <= n else text[:n] + " […gekürzt]")

    async def cloudflare_api_mehrere(self, aufrufe: list[dict], bei_fehler_weiter: bool = False, __event_emitter__=None) -> str:
        """
        Viele Cloudflare-Aufrufe in einem Schritt. Jeder Aufruf: {"methode": "GET", "pfad": "/zones?name=…", "daten": {…}}.
        Werte aus früheren Antworten mit {{n:pfad.im.json}} einsetzen (n ab 0), z. B. "/zones/{{0:result.0.id}}/dns_records".
        Bricht beim ersten Fehler (HTTP ab 400 oder success=false) ab, außer bei_fehler_weiter.
        :param aufrufe: Liste der Aufrufe (als Liste übergeben, nicht als Text)
        :param bei_fehler_weiter: nach einem Fehler mit den übrigen Aufrufen weitermachen
        :return: je Aufruf eine Zeile mit Nummer, HTTP-Status und gekürzter Antwort
        """
        try:
            aufrufe = self._json(aufrufe) or []
        except ValueError:
            return "Fehler: aufrufe ist kein gültiges JSON."
        if not isinstance(aufrufe, list) or not all(isinstance(a, dict) for a in aufrufe):
            return 'Fehler: aufrufe muss eine Liste von Objekten sein: [{"methode": "GET", "pfad": "/zones"}].'
        je = max(300, self.valves.max_zeichen // max(1, len(aufrufe)))
        ergebnisse, zeilen = [], []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout)) as s:
            for i, a in enumerate(aufrufe):
                methode = str(a.get("methode") or "GET").upper()
                status, text = 0, ""
                try:
                    pfad = _einsetzen(str(a.get("pfad") or ""), ergebnisse)
                    daten = _einsetzen(self._json(a.get("daten")), ergebnisse)
                    fehler = self._pruefen(methode, pfad)
                except (KeyError, IndexError, ValueError) as e:
                    pfad, fehler = a.get("pfad"), f"Verweis oder JSON ungültig: {e}"
                if not fehler:
                    if __event_emitter__:
                        await __event_emitter__({"type": "status", "data": {"description": f"API {i + 1}/{len(aufrufe)}: {methode} {pfad}", "done": False}})
                    try:
                        status, text = await self._senden(s, methode, pfad, daten)
                    except Exception as e:
                        fehler = f"{type(e).__name__}: {e}"
                try:
                    ergebnisse.append(json.loads(text) if text else None)
                except ValueError:
                    ergebnisse.append(None)
                kurz = " ".join(text.split())
                kurz = kurz if len(kurz) <= je else kurz[:je] + " […gekürzt]"
                zeilen.append(f"[{i}] {methode} {pfad}: " + (f"Fehler: {fehler}" if fehler else f"HTTP {status} {kurz}"))
                if (fehler or status >= 400) and not bei_fehler_weiter:
                    if i < len(aufrufe) - 1:
                        zeilen.append(f"Abgebrochen; Aufrufe {i + 1} bis {len(aufrufe) - 1} nicht ausgeführt.")
                    break
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "API: fertig", "done": True}})
        return "\n".join(zeilen)
