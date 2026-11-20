"""
title: Nextcloud-API
author: David
version: 0.2.0
description: OCS-/REST-Aufrufe an die eigene Nextcloud (z. B. Forms, Polls) mit einem App-Passwort, das nur in den Ventilen steht. Das Modell sieht das Passwort nie; erlaubt sind nur freigegebene Pfade. nextcloud_api_mehrere erledigt viele Aufrufe in einem Werkzeugschritt.
"""

import base64
import json
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, Field

# {{n:pfad.im.json}} = Wert aus der Antwort von Aufruf n (ab 0), z. B. {{0:ocs.data.id}}
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
    """Verweise auf frühere Antworten einsetzen; ein Verweis allein behält den Typ (z. B. Zahl)."""
    if isinstance(x, str):
        def holen(m):
            i = int(m.group(1))
            if i >= len(ergebnisse) or ergebnisse[i] is None:
                raise KeyError(m.group(0))
            return _wert(ergebnisse[i], m.group(2))
        ganz = VERWEIS_RE.fullmatch(x)
        if ganz:
            return holen(ganz)
        return VERWEIS_RE.sub(lambda m: str(holen(m)), x)
    if isinstance(x, list):
        return [_einsetzen(e, ergebnisse) for e in x]
    if isinstance(x, dict):
        return {k: _einsetzen(e, ergebnisse) for k, e in x.items()}
    return x


class Tools:
    class Valves(BaseModel):
        basis_url: str = Field(default="https://next.fleki.cloud", description="Nextcloud-Adresse ohne Pfad")
        benutzer: str = Field(default="david", description="Nextcloud-Benutzername")
        app_passwort: str = Field(default="", description="Eigenes App-Passwort nur für dieses Werkzeug (Nextcloud → Einstellungen → Sicherheit), jederzeit widerrufbar")
        erlaubte_pfade: str = Field(
            default="/ocs/v2.php/apps/forms/,/index.php/apps/polls/api/,/ocs/v2.php/apps/files_sharing/api/v1/shares,/ocs/v2.php/cloud/capabilities",
            description="Kommagetrennte Pfad-Anfänge, die aufgerufen werden dürfen",
        )
        loeschen_erlaubt: bool = Field(default=False, description="DELETE-Aufrufe zulassen")
        max_zeichen: int = Field(default=12000, description="Antwort an das Modell kürzen")
        max_aufrufe: int = Field(default=80, description="Höchstzahl Aufrufe je nextcloud_api_mehrere")
        timeout: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    def _pruefen(self, methode: str, pfad: str) -> Optional[str]:
        v = self.valves
        if not v.app_passwort:
            return "Kein App-Passwort in den Ventilen des Werkzeugs hinterlegt. David muss es dort eintragen."
        if methode not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return f"Methode {methode} nicht erlaubt."
        if methode == "DELETE" and not v.loeschen_erlaubt:
            return "Löschen ist für dieses Werkzeug abgeschaltet (Ventil loeschen_erlaubt)."
        teile = urlsplit(pfad or "")
        if teile.scheme or teile.netloc or not teile.path.startswith("/") or ".." in teile.path:
            return "pfad muss ein Pfad ab / auf dieser Nextcloud sein, ohne Adresse und ohne '..'."
        erlaubt = [p.strip() for p in v.erlaubte_pfade.split(",") if p.strip()]
        if not any(teile.path.startswith(p) for p in erlaubt):
            return "Pfad nicht freigegeben. Erlaubt: " + ", ".join(erlaubt)
        return None

    async def _senden(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten: Any) -> tuple[int, str]:
        v = self.valves
        token = base64.b64encode(f"{v.benutzer}:{v.app_passwort}".encode()).decode()
        kopf = {"Authorization": "Basic " + token, "OCS-APIRequest": "true", "Accept": "application/json"}
        async with s.request(methode, v.basis_url.rstrip("/") + pfad, headers=kopf,
                             json=daten if daten not in (None, "") and methode != "GET" else None,
                             params={"format": "json"} if "/ocs/" in urlsplit(pfad).path else None,
                             allow_redirects=False) as r:
            text = await r.text()
            return r.status, text.replace(v.app_passwort, "***")

    @staticmethod
    def _json(daten: Any) -> Any:
        if isinstance(daten, str) and daten.strip():
            return json.loads(daten)
        return daten

    async def nextcloud_api(
        self,
        methode: str,
        pfad: str,
        daten: Optional[Any] = None,
        __event_emitter__=None,
    ) -> str:
        """
        Ruft die Nextcloud-API einmal auf (OCS/REST), z. B. Forms: GET /ocs/v2.php/apps/forms/api/v3/forms, Umfragen (Polls): GET /index.php/apps/polls/api/v1.0/polls.
        Für mehrere Aufrufe (Fragen, Optionen, Freigaben) nextcloud_api_mehrere nehmen: ein Werkzeugschritt statt vieler.
        Anmeldung und OCS-Header ergänzt das Werkzeug selbst.
        :param methode: GET, POST, PUT, PATCH oder DELETE
        :param pfad: Pfad ab der Server-Wurzel, beginnend mit /, z. B. /ocs/v2.php/apps/forms/api/v3/forms
        :param daten: optionaler JSON-Inhalt (Objekt) für POST/PUT/PATCH
        :return: HTTP-Status und Antwort als JSON-Text
        """
        v = self.valves
        methode = (methode or "GET").upper()
        fehler = self._pruefen(methode, pfad)
        if fehler:
            return "Fehler: " + fehler
        try:
            daten = self._json(daten)
        except ValueError:
            return "Fehler: daten ist kein gültiges JSON."
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Nextcloud: {methode} {pfad}", "done": False}})
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=v.timeout)) as s:
                status, text = await self._senden(s, methode, pfad, daten)
        except Exception as e:
            return f"Fehler beim Aufruf: {type(e).__name__}: {e}"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Nextcloud: {methode} {pfad}", "done": True}})
        if len(text) > v.max_zeichen:
            text = text[: v.max_zeichen] + " […gekürzt]"
        return f"HTTP {status}\n{text}"

    async def nextcloud_api_mehrere(
        self,
        aufrufe: list[dict],
        bei_fehler_weiter: bool = False,
        __event_emitter__=None,
    ) -> str:
        """
        Viele Nextcloud-API-Aufrufe nacheinander in einem Werkzeugschritt, z. B. Formular mit allen Fragen und
        Optionen anlegen. Jeder Aufruf: {"methode": "POST", "pfad": "/ocs/...", "daten": {...}}.
        Werte aus früheren Antworten einsetzen mit {{n:pfad.im.json}} (n ab 0), z. B. pfad
        "/ocs/v2.php/apps/forms/api/v3/forms/{{0:ocs.data.id}}/questions" nach dem Anlegen des Formulars in Aufruf 0.
        Bricht beim ersten Fehler (HTTP ab 400) ab, außer bei_fehler_weiter ist true.
        :param aufrufe: Liste der Aufrufe (als Liste übergeben, nicht als Text)
        :param bei_fehler_weiter: nach einem Fehler mit den übrigen Aufrufen weitermachen
        :return: je Aufruf eine Zeile mit Nummer, HTTP-Status und gekürzter Antwort
        """
        v = self.valves
        try:
            aufrufe = self._json(aufrufe) or []
        except ValueError:
            return "Fehler: aufrufe ist kein gültiges JSON."
        if not isinstance(aufrufe, list) or not all(isinstance(a, dict) for a in aufrufe):
            return 'Fehler: aufrufe muss eine Liste von Objekten sein: [{"methode": "GET", "pfad": "/ocs/..."}].'
        if len(aufrufe) > v.max_aufrufe:
            return f"Fehler: höchstens {v.max_aufrufe} Aufrufe je Schritt (Ventil max_aufrufe)."
        je = max(300, v.max_zeichen // max(1, len(aufrufe)))
        ergebnisse: list = []
        zeilen: list[str] = []
        abgebrochen = False
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=v.timeout)) as s:
                for i, a in enumerate(aufrufe):
                    methode = str(a.get("methode") or "GET").upper()
                    try:
                        pfad = _einsetzen(str(a.get("pfad") or ""), ergebnisse)
                        daten = _einsetzen(self._json(a.get("daten")), ergebnisse)
                    except (KeyError, IndexError, ValueError) as e:
                        status, text, fehler = 0, "", f"Verweis oder JSON ungültig: {e}"
                    else:
                        fehler = self._pruefen(methode, pfad)
                        status, text = 0, ""
                        if not fehler:
                            if __event_emitter__:
                                await __event_emitter__({"type": "status", "data": {
                                    "description": f"Nextcloud {i + 1}/{len(aufrufe)}: {methode} {pfad}", "done": False}})
                            try:
                                status, text = await self._senden(s, methode, pfad, daten)
                            except Exception as e:
                                fehler = f"{type(e).__name__}: {e}"
                    try:
                        ergebnisse.append(json.loads(text) if text else None)
                    except ValueError:
                        ergebnisse.append(None)
                    kurz = " ".join(text.split())
                    grenze = je * 3 if (fehler or status >= 400) else je
                    if len(kurz) > grenze:
                        kurz = kurz[:grenze] + " […gekürzt]"
                    if fehler:
                        zeilen.append(f"[{i}] {methode} {a.get('pfad')}: Fehler: {fehler}")
                    else:
                        zeilen.append(f"[{i}] {methode} {pfad}: HTTP {status} {kurz}")
                    if (fehler or status >= 400) and not bei_fehler_weiter:
                        abgebrochen = i < len(aufrufe) - 1
                        break
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Nextcloud: fertig", "done": True}})
        if abgebrochen:
            zeilen.append(f"Abgebrochen nach Aufruf {len(zeilen) - 1}; Aufrufe {len(zeilen)} bis {len(aufrufe) - 1} nicht ausgeführt.")
        return "\n".join(zeilen)
