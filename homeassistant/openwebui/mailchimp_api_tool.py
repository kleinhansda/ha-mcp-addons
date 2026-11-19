"""
title: Mailchimp-API
author: David
version: 1.0.0
description: Mailchimp ohne MCP: Marketing-API (Zielgruppen, Kampagnen, Vorlagen, Berichte), viele Aufrufe in einem Schritt, Kampagnen-HTML auf dem Server durchsuchen und ersetzen, Vorlagen-Bereiche füllen, Bilder und Vorlagen direkt aus /share hochladen. Versand gesperrt, Planen schaltbar.
requirements:
"""

# Ersetzt den Mailchimp-MCP für Open WebUI. Kampagnen-HTML ist schnell 100 KB groß und wird deshalb
# nie ganz an das Modell gegeben: suchen, ersetzen und Vorlagen füllen laufen auf dem Server.

import asyncio
import base64
import html as htmllib
import json
import os
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, Field

# {{n:pfad.im.json}} = Wert aus der Antwort von Aufruf n (ab 0), z. B. {{0:id}}
VERWEIS_RE = re.compile(r"\{\{(\d+):([\w.\-]*)\}\}")
# Versand und Auslöser: nie über dieses Werkzeug
VERSAND_RE = re.compile(r"/actions/(send|resend|start|start-all-emails|trigger)$")
PLANEN_RE = re.compile(r"^/campaigns/[^/]+/actions/(schedule|unschedule)$")
BILDTYPEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
MAX_BILD = 10 * 1024 * 1024
MAX_HTML = 1024 * 1024


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


def _schlank(x: Any) -> Any:
    """_links (oft die Hälfte jeder Antwort) und leere Felder entfernen."""
    if isinstance(x, dict):
        return {k: _schlank(v) for k, v in x.items() if k != "_links" and v not in (None, "", [], {})}
    if isinstance(x, list):
        return [_schlank(e) for e in x]
    return x


def _ersetzen(text: str, ersetzungen: list) -> tuple:
    """Alle oder keine: jede Ersetzung muss genau einmal passen (außer alle=true)."""
    probleme, protokoll = [], []
    for i, e in enumerate(ersetzungen, 1):
        if not isinstance(e, dict):
            probleme.append(f"#{i}: kein Objekt")
            continue
        alt, neu = e.get("alt", e.get("old", "")), e.get("neu", e.get("new", ""))
        alle, rx = bool(e.get("alle", e.get("all", False))), bool(e.get("regex", False))
        if not alt:
            probleme.append(f"#{i}: 'alt' ist leer")
            continue
        if rx:
            try:
                muster = re.compile(alt, re.S)
            except re.error as x:
                probleme.append(f"#{i}: ungültiger regulärer Ausdruck ({x})")
                continue
            treffer = [m.group(0) for m in muster.finditer(text)]
            n = len(treffer)
        else:
            treffer, n = [], text.count(alt)
        if n == 0:
            probleme.append(f"#{i}: nicht gefunden: {alt[:80]!r}")
            continue
        if n > 1 and not alle:
            bsp = f", z. B. {[t[:60] for t in treffer[:3]]}" if rx else ""
            probleme.append(f"#{i}: {n} Treffer, genauer fassen oder alle=true: {alt[:80]!r}{bsp}")
            continue
        text = muster.sub(lambda m: neu, text) if rx else text.replace(alt, neu)
        protokoll.append({"nr": i, "treffer": n, "neu": neu})
    if probleme:
        raise ValueError("; ".join(probleme))
    return text, protokoll


class Tools:
    class Valves(BaseModel):
        api_schluessel: str = Field(default="", description="Mailchimp-API-Schlüssel (endet auf -usNN). Nur für dieses Werkzeug anlegen, jederzeit widerrufbar.")
        rechenzentrum: str = Field(default="", description="Optional, z. B. us21. Leer = aus dem Schlüssel")
        schreiben_erlaubt: bool = Field(default=True, description="Entwürfe, Vorlagen, Dateien anlegen und ändern (POST, PUT, PATCH)")
        planen_erlaubt: bool = Field(default=True, description="Kampagnen planen und Planung aufheben (schedule, unschedule). Sofort-Versand ist immer gesperrt.")
        loeschen_erlaubt: bool = Field(default=False, description="DELETE zulassen (Kampagnen, Vorlagen, Dateien, Kontakte)")
        share_wurzel: str = Field(default="/share/", description="Hochladen nur von Dateien unter diesem Ordner")
        max_zeichen: int = Field(default=12000, description="Antwort an das Modell kürzen")
        pruef_pause_s: int = Field(default=6, description="Wartezeit vor dem Zurücklesen nach Inhaltsänderungen")
        timeout: int = Field(default=60, description="Zeitlimit je Aufruf in Sekunden")

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()

    # ---------- Hilfen ----------

    def _basis(self) -> str:
        dc = (self.valves.rechenzentrum or self.valves.api_schluessel.rsplit("-", 1)[-1]).strip()
        return f"https://{dc}.api.mailchimp.com/3.0"

    def _konfig(self) -> Optional[str]:
        k = self.valves.api_schluessel
        if not k:
            return "Kein Schlüssel im Ventil api_schluessel. David muss ihn in den Ventilen des Werkzeugs „Mailchimp-API“ eintragen."
        if "-" not in k and not self.valves.rechenzentrum:
            return "Schlüssel ohne Rechenzentrum (-usNN): Ventil rechenzentrum setzen."
        return None

    def _pruefen(self, methode: str, pfad: str) -> Optional[str]:
        v = self.valves
        f = self._konfig()
        if f:
            return f
        if methode not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return f"Methode {methode} nicht erlaubt."
        teile = urlsplit(pfad or "")
        p = teile.path.rstrip("/") or "/"
        if teile.scheme or teile.netloc or not p.startswith("/") or ".." in p or any(c.isspace() for c in p):
            return "pfad muss mit / beginnen, ohne Adresse, ohne Leerzeichen und ohne '..', z. B. /campaigns?count=5."
        if methode == "GET":
            return None
        if VERSAND_RE.search(p):
            return "Versand ist über dieses Werkzeug gesperrt. Testmail: /actions/test; Versand nur geplant (/actions/schedule) nach Davids Freigabe."
        if PLANEN_RE.match(p):
            return None if v.planen_erlaubt else "Planen ist abgeschaltet (Ventil planen_erlaubt)."
        if methode == "DELETE" or p.endswith("/actions/delete-permanent"):
            return None if v.loeschen_erlaubt else "Löschen ist abgeschaltet (Ventil loeschen_erlaubt). Den Nutzer fragen."
        if not v.schreiben_erlaubt:
            return "Schreiben ist abgeschaltet (Ventil schreiben_erlaubt)."
        return None

    async def _senden(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten: Any = None) -> tuple:
        """Gibt (status, json_oder_text) zurück; der Schlüssel wird aus Antworten entfernt."""
        body = daten if methode != "GET" and daten not in (None, "") else None
        async with s.request(methode, self._basis() + pfad, json=body,
                             auth=aiohttp.BasicAuth("owui", self.valves.api_schluessel)) as r:
            text = (await r.text()).replace(self.valves.api_schluessel, "***")
            try:
                return r.status, json.loads(text) if text.strip() else None
            except ValueError:
                return r.status, text

    def _sitzung(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout))

    def _text(self, status: int, inhalt: Any, n: int) -> str:
        text = json.dumps(_schlank(inhalt), ensure_ascii=False, separators=(",", ":")) if not isinstance(inhalt, str) else inhalt
        if inhalt is None:
            text = "OK" if status < 400 else ""
        if len(text) > n:
            text = text[:n] + f" […gekürzt, {len(text)} Zeichen. Mit count=, offset= oder fields= eingrenzen; Kampagnen-HTML mit mailchimp_inhalt_suchen]"
        return f"HTTP {status}\n{text}"

    @staticmethod
    def _json(daten: Any) -> Any:
        return json.loads(daten) if isinstance(daten, str) and daten.strip() else daten

    async def _status(self, emitter, text: str, fertig: bool = False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": fertig}})

    async def _html(self, s, kampagne_id: str) -> tuple:
        st, d = await self._senden(s, "GET", f"/campaigns/{kampagne_id}/content")
        if st >= 400 or not isinstance(d, dict):
            return None, f"Fehler: Inhalt nicht lesbar (HTTP {st}): {str(d)[:300]}"
        return d.get("html") or "", None

    async def _entwurf(self, s, kampagne_id: str) -> tuple:
        st, d = await self._senden(s, "GET", f"/campaigns/{kampagne_id}?fields=status,content_type,settings.title")
        if st >= 400 or not isinstance(d, dict):
            return None, f"Fehler: Kampagne {kampagne_id} nicht gefunden (HTTP {st})."
        if d.get("status") != "save":
            return d, f"Fehler: Kampagne hat Status „{d.get('status')}“. Geändert werden nur Entwürfe; eine geplante erst mit /actions/unschedule zurücknehmen."
        return d, None

    def _share_datei(self, pfad: str) -> tuple:
        w = os.path.realpath(self.valves.share_wurzel).rstrip("/") + "/"
        p = os.path.realpath(pfad if os.path.isabs(pfad or "") else os.path.join(w, pfad or ""))
        if not (p + "/").startswith(w) or not os.path.isfile(p):
            return None, f"Fehler: keine Datei unter {self.valves.share_wurzel}: {pfad}"
        return p, None

    # ---------- Funktionen ----------

    async def mailchimp_api(self, methode: str, pfad: str, daten: Optional[Any] = None, __event_emitter__=None) -> str:
        """
        Mailchimp-Marketing-API einmal aufrufen. Beispiele: GET /campaigns?sort_field=send_time&sort_dir=DESC&count=5&fields=campaigns.id,campaigns.settings.title,campaigns.send_time; GET /lists; GET /templates?type=user; POST /campaigns {"type":"regular","recipients":{"list_id":…},"settings":{…}}; POST /campaigns/<id>/actions/test {"test_emails":[…],"send_type":"html"}; GET /campaigns/<id>/send-checklist; POST /campaigns/<id>/actions/schedule {"schedule_time":"2026-12-01T09:00:00+00:00"}.
        :param methode: GET, POST, PUT, PATCH oder DELETE
        :param pfad: Pfad ab /3.0, beginnt mit /, Query direkt anhängen
        :param daten: JSON-Objekt für POST, PUT, PATCH
        :return: HTTP-Status und gekürzte Antwort
        """
        methode = (methode or "GET").upper()
        fehler = self._pruefen(methode, pfad)
        if fehler:
            return "Fehler: " + fehler
        try:
            daten = self._json(daten)
        except ValueError:
            return "Fehler: daten ist kein gültiges JSON."
        await self._status(__event_emitter__, f"Mailchimp: {methode} {pfad}")
        try:
            async with self._sitzung() as s:
                status, inhalt = await self._senden(s, methode, pfad, daten)
        except Exception as e:
            return f"Fehler beim Aufruf: {type(e).__name__}: {e}"
        finally:
            await self._status(__event_emitter__, f"Mailchimp: {methode} {pfad}", True)
        return self._text(status, inhalt, self.valves.max_zeichen)

    async def mailchimp_api_mehrere(self, aufrufe: list[dict], bei_fehler_weiter: bool = False, __event_emitter__=None) -> str:
        """
        Viele Mailchimp-Aufrufe in einem Schritt. Jeder Aufruf: {"methode": "GET", "pfad": "/…", "daten": {…}}. Werte aus früheren Antworten mit {{n:feld}} einsetzen (n ab 0), z. B. "/campaigns/{{0:id}}/send-checklist". Bricht beim ersten Fehler ab, außer bei_fehler_weiter.
        :param aufrufe: Liste der Aufrufe (als Liste, nicht als Text)
        :param bei_fehler_weiter: nach einem Fehler weitermachen
        :return: je Aufruf Nummer, HTTP-Status und gekürzte Antwort
        """
        try:
            aufrufe = self._json(aufrufe) or []
        except ValueError:
            return "Fehler: aufrufe ist kein gültiges JSON."
        if not isinstance(aufrufe, list) or not all(isinstance(a, dict) for a in aufrufe):
            return 'Fehler: aufrufe muss eine Liste von Objekten sein: [{"methode": "GET", "pfad": "/lists"}].'
        if len(aufrufe) > 30:
            return "Fehler: höchstens 30 Aufrufe je Schritt."
        je = max(400, self.valves.max_zeichen // max(1, len(aufrufe)))
        ergebnisse, zeilen = [], []
        async with self._sitzung() as s:
            for i, a in enumerate(aufrufe):
                methode = str(a.get("methode") or "GET").upper()
                status, inhalt = 0, None
                try:
                    pfad = _einsetzen(str(a.get("pfad") or ""), ergebnisse)
                    daten = _einsetzen(self._json(a.get("daten")), ergebnisse)
                    fehler = self._pruefen(methode, pfad)
                except (KeyError, IndexError, ValueError) as e:
                    pfad, fehler = a.get("pfad"), f"Verweis oder JSON ungültig: {e}"
                if not fehler:
                    await self._status(__event_emitter__, f"Mailchimp {i + 1}/{len(aufrufe)}: {methode} {pfad}")
                    try:
                        status, inhalt = await self._senden(s, methode, pfad, daten)
                    except Exception as e:
                        fehler = f"{type(e).__name__}: {e}"
                ergebnisse.append(inhalt if isinstance(inhalt, (dict, list)) else None)
                zeilen.append(f"[{i}] {methode} {pfad}: " + (f"Fehler: {fehler}" if fehler else self._text(status, inhalt, je).replace("\n", " ", 1)))
                if (fehler or status >= 400) and not bei_fehler_weiter:
                    if i < len(aufrufe) - 1:
                        zeilen.append(f"Abgebrochen; Aufrufe {i + 1} bis {len(aufrufe) - 1} nicht ausgeführt.")
                    break
        await self._status(__event_emitter__, "Mailchimp: fertig", True)
        return "\n".join(zeilen)

    async def mailchimp_inhalt_suchen(self, kampagne_id: str, text: str, umgebung: int = 150) -> str:
        """
        Sucht Text im vollständigen HTML einer Kampagne und zeigt jede Fundstelle mit Umgebung (höchstens 20), z. B. Datum, Bandname, Bild-URL („mcusercontent.com“), Links („instagram.com“). Vor mailchimp_inhalt_ersetzen nutzen, um exakte Textstücke zu kennen.
        :param kampagne_id: Kampagnen-ID (10 Zeichen hex)
        :param text: gesuchter Text, Groß-/Kleinschreibung zählt
        :param umgebung: Zeichen HTML vor und nach jeder Fundstelle (bis 1000)
        :return: JSON mit Länge, Anzahl und Fundstellen
        """
        f = self._konfig()
        if f:
            return "Fehler: " + f
        if not text:
            return "Fehler: text fehlt."
        umgebung = max(0, min(int(umgebung or 0), 1000))
        async with self._sitzung() as s:
            html, f = await self._html(s, kampagne_id)
        if f:
            return f
        treffer, start = [], 0
        while len(treffer) < 20:
            p = html.find(text, start)
            if p < 0:
                break
            treffer.append({"position": p, "ausschnitt": html[max(0, p - umgebung):p + len(text) + umgebung]})
            start = p + len(text)
        return json.dumps({"kampagne_id": kampagne_id, "html_laenge": len(html), "anzahl": html.count(text), "fundstellen": treffer}, ensure_ascii=False)

    async def mailchimp_inhalt_ersetzen(self, kampagne_id: str, ersetzungen: list[dict], __event_emitter__=None) -> str:
        """
        Ersetzt Textstücke im HTML eines Kampagnen-Entwurfs auf dem Server, alles oder nichts, und prüft danach, ob Mailchimp die Änderung behalten hat. Jede Ersetzung: {"alt": "…", "neu": "…", "alle": false, "regex": false}; "alt" muss genau einmal vorkommen (außer alle=true). Exakte Stücke vorher mit mailchimp_inhalt_suchen holen.
        :param kampagne_id: Kampagnen-ID des Entwurfs
        :param ersetzungen: Liste der Ersetzungen (als Liste, nicht als Text)
        :return: JSON mit status content_updated oder not_applied
        """
        f = self._pruefen("PUT", f"/campaigns/{kampagne_id}/content")
        if f:
            return "Fehler: " + f
        try:
            ersetzungen = self._json(ersetzungen)
        except ValueError:
            return "Fehler: ersetzungen ist kein gültiges JSON."
        if not isinstance(ersetzungen, list) or not ersetzungen:
            return "Fehler: ersetzungen muss eine nicht leere Liste sein."
        async with self._sitzung() as s:
            _, f = await self._entwurf(s, kampagne_id)
            if f:
                return f
            html, f = await self._html(s, kampagne_id)
            if f:
                return f
            try:
                neu, protokoll = _ersetzen(html, ersetzungen)
            except ValueError as e:
                return f"Fehler: Nichts gespeichert: {e}"
            await self._status(__event_emitter__, "Mailchimp: speichere Inhalt …")
            st, d = await self._senden(s, "PUT", f"/campaigns/{kampagne_id}/content", {"html": neu})
            if st >= 400:
                return self._text(st, d, 1500)
            # Kampagnen aus dem neuen E-Mail-Builder zeigen das HTML kurz und stellen dann den Builder-Inhalt wieder her
            await asyncio.sleep(max(0, self.valves.pruef_pause_s))
            spaeter, f = await self._html(s, kampagne_id)
        await self._status(__event_emitter__, "Mailchimp: fertig", True)
        if f:
            return json.dumps({"status": "saved_unverified", "fehler": f}, ensure_ascii=False)
        fehlt = [p["nr"] for p in protokoll if p["neu"] and p["neu"] not in spaeter]
        erg = {"status": "not_applied" if fehlt else "content_updated", "kampagne_id": kampagne_id,
               "ersetzungen": [{"nr": p["nr"], "treffer": p["treffer"]} for p in protokoll],
               "fehlen_nach_speichern": fehlt, "html_laenge": len(spaeter)}
        if fehlt:
            erg["hinweis"] = "Mailchimp hat die Änderung nicht behalten (typisch für Kampagnen aus dem neuen E-Mail-Builder). Nicht wiederholen, keine Testmail; David die Änderungen als Liste alt → neu für den Editor geben."
        return json.dumps(erg, ensure_ascii=False)

    async def mailchimp_vorlage_fuellen(self, kampagne_id: str, vorlage_id: str, bereiche: dict, __event_emitter__=None) -> str:
        """
        Setzt den Inhalt eines Kampagnen-Entwurfs aus einer eigenen Vorlage plus HTML je Bereich (mc:edit), z. B. {"titel": "<h1>27.11. Band</h1>", "bild": "<img src='https://…' width='600' style='display:block;width:100%'>"}. Nicht genannte Bereiche behalten den Vorlageninhalt. Danach wird zurückgelesen und geprüft.
        :param kampagne_id: Kampagnen-ID des Entwurfs
        :param vorlage_id: ID der Vorlage (Zahl)
        :param bereiche: Objekt Bereichsname -> HTML
        :return: JSON mit status content_updated oder not_applied
        """
        f = self._pruefen("PUT", f"/campaigns/{kampagne_id}/content")
        if f:
            return "Fehler: " + f
        try:
            bereiche = self._json(bereiche)
            vid = int(str(vorlage_id).strip())
        except ValueError:
            return "Fehler: bereiche ist kein gültiges JSON oder vorlage_id keine Zahl."
        if not isinstance(bereiche, dict) or not bereiche:
            return "Fehler: bereiche muss ein nicht leeres Objekt sein."
        async with self._sitzung() as s:
            _, f = await self._entwurf(s, kampagne_id)
            if f:
                return f
            await self._status(__event_emitter__, "Mailchimp: fülle Vorlage …")
            st, d = await self._senden(s, "PUT", f"/campaigns/{kampagne_id}/content", {"template": {"id": vid, "sections": bereiche}})
            if st >= 400:
                return self._text(st, d, 1500)
            await asyncio.sleep(max(0, self.valves.pruef_pause_s))
            html, f = await self._html(s, kampagne_id)
        await self._status(__event_emitter__, "Mailchimp: fertig", True)
        if f:
            return json.dumps({"status": "saved_unverified", "fehler": f}, ensure_ascii=False)
        klar, fehlt = htmllib.unescape(html), []
        for k, wert in bereiche.items():
            probe = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(wert)))
            probe = max((w for w in re.split(r"\s{2,}|\n", probe) if w.strip()), key=len, default="").strip()[:60]
            if probe and probe not in klar:
                fehlt.append(k)
        return json.dumps({"status": "not_applied" if fehlt else "content_updated", "kampagne_id": kampagne_id,
                           "vorlage_id": vid, "bereiche": list(bereiche), "fehlen_nach_speichern": fehlt,
                           "html_laenge": len(html)}, ensure_ascii=False)

    async def mailchimp_datei_hochladen(self, pfad: str, name: str = "", vorlage_id: str = "", ordner_id: str = "") -> str:
        """
        Lädt eine Datei aus /share zu Mailchimp: Bild oder PDF (png, jpg, gif, webp, pdf, bis 10 MB) in den File Manager, Rückgabe full_size_url; HTML-Datei als eigene Vorlage (neu oder mit vorlage_id aktualisiert), Rückgabe Vorlagen-ID und mc:edit-Bereiche. Kein Base64 im Chat nötig.
        :param pfad: absoluter Pfad unter /share
        :param name: Name in Mailchimp (leer = Dateiname; bei Vorlagen Pflicht für neue)
        :param vorlage_id: nur HTML: bestehende Vorlage aktualisieren statt neu anlegen
        :param ordner_id: optionaler Ordner im File Manager bzw. Vorlagenordner
        :return: JSON mit id, name und URL bzw. Bereichen
        """
        f = self._pruefen("POST", "/file-manager/files")
        if f:
            return "Fehler: " + f
        p, f = self._share_datei(pfad)
        if f:
            return f
        endung = os.path.splitext(p)[1].lower()
        name = (name or "").strip() or os.path.basename(p)
        async with self._sitzung() as s:
            if endung in (".html", ".htm"):
                if os.path.getsize(p) > MAX_HTML:
                    return "Fehler: HTML größer als 1 MB."
                with open(p, encoding="utf-8") as fh:
                    html = fh.read()
                bereiche = sorted(set(re.findall(r'mc:edit=["\']([^"\']+)["\']', html)))
                body = {"name": name, "html": html}
                if ordner_id and not vorlage_id:
                    body["folder_id"] = str(ordner_id)
                if vorlage_id:
                    st, d = await self._senden(s, "PATCH", f"/templates/{str(vorlage_id).strip()}", body)
                else:
                    st, d = await self._senden(s, "POST", "/templates", body)
                if st >= 400 or not isinstance(d, dict):
                    return self._text(st, d, 1500)
                return json.dumps({"status": "vorlage_aktualisiert" if vorlage_id else "vorlage_angelegt", "id": d.get("id"),
                                   "name": d.get("name"), "bereiche": bereiche, "html_laenge": len(html)}, ensure_ascii=False)
            if endung not in BILDTYPEN:
                return f"Fehler: Dateityp {endung} nicht erlaubt ({', '.join(sorted(BILDTYPEN | {'.html'}))})."
            if os.path.getsize(p) > MAX_BILD:
                return "Fehler: Datei größer als 10 MB."
            with open(p, "rb") as fh:
                body = {"name": name, "file_data": base64.b64encode(fh.read()).decode("ascii")}
            if ordner_id:
                body["folder_id"] = int(ordner_id)
            st, d = await self._senden(s, "POST", "/file-manager/files", body)
        if st >= 400 or not isinstance(d, dict):
            return self._text(st, d, 1500)
        return json.dumps({k: d.get(k) for k in ("id", "name", "full_size_url", "width", "height", "size")}, ensure_ascii=False)
