"""
title: mailbox.org Kalender & Kontakte
author: David
version: 1.0.0
description: Kalender (CalDAV) und Adressbuch (CardDAV) bei mailbox.org: Termine lesen, eintragen, ändern, Kontakte suchen und pflegen. Direkt per DAV, ohne MCP. Löschen nur mit Ventil.
requirements:
"""

# Schlanker Ersatz für die MCP-Dienste calendar und contacts der App „mailbox.org MCP“ in Open WebUI.
# Zugang: E-Mail-Adresse und ein mailbox.org-Anwendungspasswort vom Typ
# „Kalender- und Adressbuch-Client (CalDAV/CardDAV)“ in den Ventilen.

import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import BaseModel, Field

WOCHENTAG = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "urn:ietf:params:xml:ns:carddav"}
CACHE_S = 600


# --- iCalendar / vCard -------------------------------------------------------------------------

def _entfalten(text: str) -> list:
    """Zeilen entfalten (RFC 5545 3.1): Fortsetzungszeilen beginnen mit Leerzeichen oder Tab."""
    zeilen: list = []
    for z in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if z[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += z[1:]
        elif z:
            zeilen.append(z)
    return zeilen


def _falten(zeile: str) -> str:
    """Auf 75 Oktette falten, ohne UTF-8-Zeichen zu zerschneiden."""
    teile, aktuell, laenge = [], "", 0
    for ch in zeile:
        n = len(ch.encode("utf-8"))
        if laenge + n > (75 if not teile else 74):
            teile.append(aktuell)
            aktuell, laenge = "", 0
        aktuell += ch
        laenge += n
    teile.append(aktuell)
    return "\r\n ".join(teile)


def _zerlegen(zeile: str) -> tuple:
    """'DTSTART;TZID=Europe/Berlin:2026…' -> ('DTSTART', {'TZID': 'Europe/Berlin'}, '2026…')."""
    kopf, _, wert = zeile.partition(":")
    # Doppelpunkte in Parameterwerten in Anführungszeichen
    if kopf.count('"') % 2:
        rest = wert
        while kopf.count('"') % 2 and ":" in rest:
            vor, _, rest = rest.partition(":")
            kopf += ":" + vor
        wert = rest
    teile = kopf.split(";")
    params = {}
    for p in teile[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return teile[0].upper(), params, wert


def _text(wert: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), wert)


def _esc(wert: str) -> str:
    return str(wert).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _bloecke(zeilen: list, name: str) -> list:
    """Alle Komponenten BEGIN:name … END:name als (start, ende) Indizes."""
    out, start = [], None
    for i, z in enumerate(zeilen):
        if z.upper() == "BEGIN:" + name:
            start = i
        elif z.upper() == "END:" + name and start is not None:
            out.append((start, i))
            start = None
    return out


def _eigenschaften(zeilen: list) -> dict:
    d: dict = {}
    tiefe = 0
    for z in zeilen[1:-1]:
        if z.upper().startswith("BEGIN:"):
            tiefe += 1
        elif z.upper().startswith("END:"):
            tiefe -= 1
        elif tiefe == 0:
            n, p, v = _zerlegen(z)
            d.setdefault(n, []).append((p, v))
    return d


def _ical_zeit(wert: str, params: dict, tz: ZoneInfo):
    """-> (date) für ganztägig oder (aware datetime)."""
    w = wert.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", w):
        return date(int(w[:4]), int(w[4:6]), int(w[6:8]))
    dt = datetime.strptime(w[:15], "%Y%m%dT%H%M%S")
    if w.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc).astimezone(tz)
    try:
        zone = ZoneInfo(params["TZID"]) if params.get("TZID") else tz
    except Exception:
        zone = tz
    return dt.replace(tzinfo=zone).astimezone(tz)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _lesbar(x) -> str:
    if isinstance(x, datetime):
        return f"{WOCHENTAG[x.weekday()]}, {x:%d.%m.%Y %H:%M}"
    return f"{WOCHENTAG[x.weekday()]}, {x:%d.%m.%Y}"


def _eingabe_zeit(s: str, tz: ZoneInfo) -> tuple:
    """'2026-11-20' -> ('date', date); '2026-11-20T14:00' / '2026-11-20 14:00' -> ('datetime', aware)."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "date", date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))
    return "datetime", dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _ersetzen(zeilen: list, name: str, neu: Optional[list]) -> list:
    """Alle Zeilen der Eigenschaft name (oberste Ebene der Komponente) durch neu ersetzen (None = entfernen)."""
    out, gesetzt, tiefe = [], False, 0
    for i, z in enumerate(zeilen):
        oben = tiefe == 1
        if z.upper().startswith("BEGIN:"):
            tiefe += 1
        elif z.upper().startswith("END:"):
            if tiefe == 1 and not gesetzt and neu:
                out.extend(neu)
                gesetzt = True
            tiefe -= 1
        elif oben and _zerlegen(z)[0] == name:
            if not gesetzt and neu:
                out.extend(neu)
            gesetzt = True
            continue
        out.append(z)
    return out


# --- Werkzeug ----------------------------------------------------------------------------------

class Tools:
    class Valves(BaseModel):
        dav_url: str = Field(default="https://dav.mailbox.org/", description="DAV-Adresse von mailbox.org")
        benutzer: str = Field(default="", description="mailbox.org-E-Mail-Adresse")
        passwort: str = Field(default="", description="Anwendungspasswort vom Typ „Kalender- und Adressbuch-Client (CalDAV/CardDAV)“")
        zeitzone: str = Field(default="Europe/Berlin", description="Zeitzone für Ein- und Ausgabe")
        erlaubte_kalender: str = Field(default="", description="Kalendernamen, Komma-getrennt; leer = alle")
        standard_kalender: str = Field(default="", description="Kalender für neue Termine; leer = erster erlaubter")
        kalender_schreiben: bool = Field(default=True, description="Termine eintragen und ändern")
        kontakte_schreiben: bool = Field(default=True, description="Kontakte anlegen und ergänzen")
        loeschen_erlaubt: bool = Field(default=False, description="Termine endgültig löschen")
        timeout: int = Field(default=20, description="Zeitlimit je Anfrage in Sekunden")

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()
        self._cache: dict = {}

    # --- Verbindung ---

    def _tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.valves.zeitzone or "Europe/Berlin")
        except Exception:
            return ZoneInfo("Europe/Berlin")

    def _konfig(self) -> Optional[str]:
        if not self.valves.benutzer or not self.valves.passwort:
            return "Fehler: Benutzer oder Passwort fehlt. David muss beides in den Ventilen des Werkzeugs „mailbox.org Kalender & Kontakte“ eintragen."
        return None

    def _sauber(self, text: str) -> str:
        return text.replace(self.valves.passwort, "***") if self.valves.passwort else text

    async def _dav(self, methode: str, url: str, body: str = "", tiefe: Optional[str] = None, kopf: Optional[dict] = None) -> tuple:
        h = {"Content-Type": "application/xml; charset=utf-8"} if body.lstrip().startswith("<") else {}
        if body and not h:
            h["Content-Type"] = "text/calendar; charset=utf-8" if "BEGIN:VCALENDAR" in body else "text/vcard; charset=utf-8"
        if tiefe is not None:
            h["Depth"] = tiefe
        h.update(kopf or {})
        auth = aiohttp.BasicAuth(self.valves.benutzer, self.valves.passwort)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout), auth=auth) as s:
            async with s.request(methode, url, data=body.encode("utf-8") if body else None, headers=h, allow_redirects=True) as r:
                return r.status, await r.text(errors="replace"), dict(r.headers), str(r.url)

    def _fehler(self, st: int, text: str, was: str) -> str:
        if st == 401:
            return "Fehler: Anmeldung abgelehnt (HTTP 401). Ventile prüfen: Benutzer = E-Mail-Adresse, Passwort = Anwendungspasswort für CalDAV/CardDAV."
        if st == 412:
            return f"Fehler: {was} wurde inzwischen woanders geändert (HTTP 412). Neu lesen und noch einmal versuchen."
        return f"Fehler bei {was} (HTTP {st}): {self._sauber(re.sub(r'<[^>]+>', ' ', text))[:200].strip()}"

    @staticmethod
    def _antworten(xml: str) -> list:
        try:
            wurzel = ET.fromstring(xml)
        except ET.ParseError:
            return []
        return wurzel.findall("d:response", NS)

    async def _propfind(self, url: str, props: str, tiefe: str) -> tuple:
        body = f'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="urn:ietf:params:xml:ns:carddav"><d:prop>{props}</d:prop></d:propfind>'
        st, text, _, end_url = await self._dav("PROPFIND", url, body, tiefe)
        return st, text, end_url

    async def _sammlungen(self) -> tuple:
        """-> ({kalendername: url}, {adressbuchname: url}, Fehler). 10 Minuten zwischengespeichert."""
        c = self._cache.get("sammlungen")
        if c and time.time() - c[0] < CACHE_S and c[1] == self.valves.benutzer:
            return c[2], c[3], None
        basis = self.valves.dav_url.rstrip("/") + "/"
        try:
            st, text, end_url = await self._propfind(basis, "<d:current-user-principal/>", "0")
            if st == 404 or (st < 400 and not text.strip()):
                st, text, end_url = await self._propfind(urljoin(basis, "/.well-known/caldav"), "<d:current-user-principal/>", "0")
            if st >= 400:
                return {}, {}, self._fehler(st, text, "der Anmeldung")
            p = ET.fromstring(text).find(".//d:current-user-principal/d:href", NS)
            principal = urljoin(end_url, p.text.strip()) if p is not None and p.text else end_url
            st, text, end_url = await self._propfind(principal, "<c:calendar-home-set/><a:addressbook-home-set/>", "0")
            if st >= 400:
                return {}, {}, self._fehler(st, text, "der Suche nach Kalendern")
            wurzel = ET.fromstring(text)
            homes = {}
            for tag in ("c:calendar-home-set", "a:addressbook-home-set"):
                h = wurzel.find(f".//{tag}/d:href", NS)
                if h is not None and h.text:
                    homes[tag] = urljoin(end_url, h.text.strip())
            kal, adr = {}, {}
            for tag, ziel in (("c:calendar-home-set", kal), ("a:addressbook-home-set", adr)):
                if tag not in homes:
                    continue
                st, text, end_url = await self._propfind(
                    homes[tag], "<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>", "1")
                if st >= 400:
                    continue
                for r in self._antworten(text):
                    href = r.findtext("d:href", "", NS).strip()
                    typ = r.find(".//d:resourcetype", NS)
                    if typ is None:
                        continue
                    ist_kal = typ.find("c:calendar", NS) is not None
                    ist_adr = typ.find("a:addressbook", NS) is not None
                    if (tag.startswith("c") and not ist_kal) or (tag.startswith("a") and not ist_adr):
                        continue
                    comps = [x.get("name") for x in r.findall(".//c:supported-calendar-component-set/c:comp", NS)]
                    if ist_kal and comps and "VEVENT" not in comps:
                        continue
                    name = (r.findtext(".//d:displayname", "", NS) or "").strip() or unquote(href.rstrip("/").rsplit("/", 1)[-1])
                    while name in ziel:
                        name += "*"
                    ziel[name] = urljoin(end_url, href)
        except aiohttp.ClientError as e:
            return {}, {}, f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        except ET.ParseError:
            return {}, {}, "Fehler: unerwartete Antwort des DAV-Servers (kein XML)."
        erlaubt = [k.strip() for k in self.valves.erlaubte_kalender.split(",") if k.strip()]
        if erlaubt:
            kal = {k: v for k, v in kal.items() if k in erlaubt}
        self._cache["sammlungen"] = (time.time(), self.valves.benutzer, kal, adr)
        return kal, adr, None

    def _kalender_wahl(self, kal: dict, name: str) -> tuple:
        name = (name or "").strip() or self.valves.standard_kalender.strip()
        if not name:
            return (next(iter(kal.items())) if kal else (None, None)), None
        if name in kal:
            return (name, kal[name]), None
        treffer = [k for k in kal if k.lower() == name.lower()]
        if len(treffer) == 1:
            return (treffer[0], kal[treffer[0]]), None
        return (None, None), f"Fehler: Kalender „{name}“ gibt es nicht. Vorhanden: {', '.join(kal) or 'keine'}."

    def _id_aufloesen(self, sammlungen: dict, ident: str) -> tuple:
        """'Privat/abc.ics' -> (Sammlungsname, Ressourcen-URL)."""
        name, _, datei = (ident or "").strip().rpartition("/")
        if not name or not datei or datei in (".", ".."):
            return None, None, "Fehler: id im Format „<Name>/<Datei>“ aus der Ausgabe von *_lesen bzw. *_suchen übernehmen."
        if name not in sammlungen:
            return None, None, f"Fehler: „{name}“ gibt es nicht. Vorhanden: {', '.join(sammlungen) or 'keine'}."
        return name, sammlungen[name].rstrip("/") + "/" + datei, None

    async def _report(self, url: str, body: str) -> tuple:
        st, text, _, end_url = await self._dav("REPORT", url, body, "1")
        if st >= 400:
            return None, st, text
        out = []
        for r in self._antworten(text):
            href = r.findtext("d:href", "", NS).strip()
            daten = r.findtext(".//c:calendar-data", None, NS) or r.findtext(".//a:address-data", None, NS)
            if daten:
                out.append((urljoin(end_url, href), r.findtext(".//d:getetag", "", NS), daten))
        return out, st, text

    # --- Termine ---

    def _termine_aus(self, ics: str, von: datetime, bis: datetime) -> list:
        tz = self._tz()
        zeilen = _entfalten(ics)
        out = []
        # Einzeln geänderte Vorkommen (RECURRENCE-ID) nicht zusätzlich aus der Serie erzeugen
        ueberschrieben = set()
        for a, b in _bloecke(zeilen, "VEVENT"):
            rid = _eigenschaften(zeilen[a:b + 1]).get("RECURRENCE-ID")
            if rid:
                try:
                    ueberschrieben.add(_ical_zeit(rid[0][1], rid[0][0], tz))
                except ValueError:
                    pass
        for a, b in _bloecke(zeilen, "VEVENT"):
            e = _eigenschaften(zeilen[a:b + 1])
            if "DTSTART" not in e:
                continue
            try:
                s = _ical_zeit(e["DTSTART"][0][1], e["DTSTART"][0][0], tz)
                if "DTEND" in e:
                    en = _ical_zeit(e["DTEND"][0][1], e["DTEND"][0][0], tz)
                elif "DURATION" in e:
                    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", e["DURATION"][0][1].strip())
                    dauer = timedelta(weeks=int(m.group(1) or 0), days=int(m.group(2) or 0), hours=int(m.group(3) or 0), minutes=int(m.group(4) or 0)) if m else timedelta(0)
                    en = s + dauer
                else:
                    en = s + (timedelta(days=1) if not isinstance(s, datetime) else timedelta(0))
            except (ValueError, KeyError):
                continue
            serie = "RRULE" in e
            starts = [(s, en)]
            if serie and "RECURRENCE-ID" not in e:
                starts = self._serie(e, s, en, von, bis, ueberschrieben) or []
            for s1, en1 in starts:
                a1 = datetime.combine(s1, datetime.min.time(), tz) if not isinstance(s1, datetime) else s1
                b1 = datetime.combine(en1, datetime.min.time(), tz) if not isinstance(en1, datetime) else en1
                if b1 <= von or a1 >= bis:
                    if not (a1 == b1 and von <= a1 < bis):
                        continue
                out.append({
                    "start": s1, "ende": en1, "serie": serie or "RECURRENCE-ID" in e,
                    "titel": _text(e.get("SUMMARY", [({}, "")])[0][1]),
                    "ort": _text(e.get("LOCATION", [({}, "")])[0][1]),
                    "text": _text(e.get("DESCRIPTION", [({}, "")])[0][1]),
                    "status": e.get("STATUS", [({}, "")])[0][1].upper(),
                })
        return out

    def _serie(self, e: dict, s, en, von: datetime, bis: datetime, ueberschrieben: set) -> list:
        """Serientermin selbst aufschlüsseln, falls der Server nicht expandiert (python-dateutil)."""
        try:
            from dateutil.rrule import rrulestr
        except ImportError:
            return [(s, en)]
        dauer = en - s
        start = s if isinstance(s, datetime) else datetime.combine(s, datetime.min.time())
        regel = e["RRULE"][0][1]
        if not isinstance(s, datetime):
            regel = re.sub(r"UNTIL=(\d{8})T\d{6}Z?", r"UNTIL=\1", regel)
        else:
            regel = re.sub(r"UNTIL=(\d{8})(?!T)", r"UNTIL=\1T235959Z", regel)
        try:
            r = rrulestr(regel, dtstart=start)
            ausnahmen = set(ueberschrieben)
            for p, v in e.get("EXDATE", []):
                for w in v.split(","):
                    try:
                        ausnahmen.add(_ical_zeit(w, p, self._tz()))
                    except ValueError:
                        pass
            if isinstance(s, datetime):
                treffer = r.between(von - dauer, bis, inc=True)
                return [(t, t + dauer) for t in treffer if t not in ausnahmen][:200]
            treffer = r.between(von.replace(tzinfo=None) - dauer, bis.replace(tzinfo=None), inc=True)
            return [(t.date(), t.date() + dauer) for t in treffer if t.date() not in ausnahmen][:200]
        except (ValueError, TypeError):
            return [(s, en)]

    async def mailbox_termine_lesen(self, von: str = "", bis: str = "", tage: int = 14, suche: str = "", kalender: str = "") -> str:
        """
        Liest Termine aus den mailbox.org-Kalendern in einem Zeitraum, Serientermine einzeln.
        :param von: Startdatum 2026-11-20 (leer = heute)
        :param bis: Enddatum einschließlich (leer = von + tage)
        :param tage: Länge des Zeitraums, wenn bis leer ist (höchstens 366)
        :param suche: optional nur Termine, deren Titel, Ort oder Beschreibung diesen Text enthält
        :param kalender: Name eines Kalenders; leer = alle
        :return: Kalendernamen, dann je Termin eine Zeile mit Wochentag, Zeit, Titel, Ort, Kalender und id
        """
        f = self._konfig()
        if f:
            return f
        tz = self._tz()
        try:
            start = date.fromisoformat(von) if von else datetime.now(tz).date()
            ende = date.fromisoformat(bis) + timedelta(days=1) if bis else start + timedelta(days=min(366, max(1, int(tage or 14))))
        except ValueError:
            return "Fehler: von und bis als 2026-11-20 angeben."
        if ende <= start:
            return "Fehler: bis liegt vor von."
        kal, _, f = await self._sammlungen()
        if f:
            return f
        if kalender:
            (name, url), f = self._kalender_wahl(kal, kalender)
            if f:
                return f
            auswahl = {name: url}
        else:
            auswahl = kal
        a = datetime.combine(start, datetime.min.time(), tz)
        b = datetime.combine(ende, datetime.min.time(), tz)
        bereich = f'start="{_utc(a)}" end="{_utc(b)}"'
        body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f'<d:prop><d:getetag/><c:calendar-data><c:expand {bereich}/></c:calendar-data></d:prop>'
                f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range {bereich}/>'
                '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
        termine, fehler = [], []
        for name, url in auswahl.items():
            try:
                res, st, text = await self._report(url, body)
            except aiohttp.ClientError as e:
                fehler.append(f"{name}: nicht erreichbar ({type(e).__name__})")
                continue
            if res is None:
                fehler.append(f"{name}: " + self._fehler(st, text, "der Abfrage"))
                continue
            for href, _, ics in res:
                for t in self._termine_aus(ics, a, b):
                    t["kalender"], t["id"] = name, f"{name}/{unquote(href.rstrip('/').rsplit('/', 1)[-1])}"
                    termine.append(t)
        if suche:
            q = suche.lower()
            termine = [t for t in termine if q in (t["titel"] + " " + t["ort"] + " " + t["text"]).lower()]
        schluessel = lambda t: datetime.combine(t["start"], datetime.min.time(), tz) if not isinstance(t["start"], datetime) else t["start"]
        termine.sort(key=schluessel)
        zeilen = [f"Kalender: {', '.join(auswahl) or 'keine'}",
                  f"{len(termine)} Termine {_lesbar(start)} bis {_lesbar(ende - timedelta(days=1))}" + (f" mit „{suche}“" if suche else "") + ":"]
        for t in termine[:300]:
            s, en = t["start"], t["ende"]
            if isinstance(s, datetime):
                z = f"- {_lesbar(s)}–" + (f"{en:%H:%M}" if en.date() == s.date() else _lesbar(en))
            else:
                letzter = en - timedelta(days=1)
                z = f"- {_lesbar(s)}" + (f" bis {_lesbar(letzter)}" if letzter > s else "") + " (ganztägig)"
            z += f": {t['titel'] or '(ohne Titel)'}"
            if t["ort"]:
                z += f" ({t['ort']})"
            if t["status"] == "CANCELLED":
                z += " [abgesagt]"
            if t["serie"]:
                z += " [Serie]"
            z += f" · {t['kalender']} · id {t['id']}"
            if t["text"]:
                z += f"\n  {t['text'][:160].replace(chr(10), ' ')}"
            zeilen.append(z)
        if len(termine) > 300:
            zeilen.append(f"… {len(termine) - 300} weitere, Zeitraum verkleinern")
        zeilen += [f"Fehler {x}" for x in fehler]
        return "\n".join(zeilen)

    async def mailbox_termin_speichern(self, titel: str = "", start: str = "", ende: str = "", ort: str = "", beschreibung: str = "", kalender: str = "", id: str = "") -> str:
        """
        Trägt einen Termin ein (ohne id) oder ändert einen bestehenden (mit id aus mailbox_termine_lesen; nur angegebene Felder ändern sich). Nur nach Davids Bestätigung aufrufen.
        :param titel: Titel des Termins (Pflicht bei neuem Termin)
        :param start: 2026-11-20 (ganztägig) oder 2026-11-20T14:00 (Ortszeit)
        :param ende: wie start; ganztägig = letzter Tag; leer = 1 Stunde bzw. 1 Tag
        :param ort: optionaler Ort
        :param beschreibung: optionale Beschreibung
        :param kalender: Name des Kalenders für neue Termine; leer = Standardkalender
        :param id: id eines bestehenden Termins zum Ändern, z. B. Privat/abc.ics
        :return: Bestätigung mit Wochentag und id oder Fehler
        """
        f = self._konfig()
        if f:
            return f
        if not self.valves.kalender_schreiben:
            return "Fehler: Termine schreiben ist abgeschaltet (Ventil kalender_schreiben)."
        tz = self._tz()
        kal, _, f = await self._sammlungen()
        if f:
            return f
        zeit = None
        if start or ende:
            if not start:
                return "Fehler: zu ende auch start angeben."
            try:
                art, s = _eingabe_zeit(start, tz)
                if ende:
                    art2, en = _eingabe_zeit(ende, tz)
                    if art2 != art:
                        return "Fehler: start und ende beide als Datum oder beide mit Uhrzeit angeben."
                else:
                    en = s + (timedelta(hours=1) if art == "datetime" else timedelta(0))
            except ValueError:
                return "Fehler: start/ende als 2026-11-20 oder 2026-11-20T14:00 angeben."
            if en < s or (art == "datetime" and en == s):
                return "Fehler: ende liegt nicht nach start."
            if art == "date":
                zeit = ([f"DTSTART;VALUE=DATE:{s:%Y%m%d}"], [f"DTEND;VALUE=DATE:{en + timedelta(days=1):%Y%m%d}"])
                wann = _lesbar(s) + (f" bis {_lesbar(en)}" if en > s else "") + " (ganztägig)"
            else:
                zeit = ([f"DTSTART:{_utc(s)}"], [f"DTEND:{_utc(en)}"])
                wann = f"{_lesbar(s)}–" + (f"{en:%H:%M}" if en.date() == s.date() else _lesbar(en))
        jetzt = _utc(datetime.now(timezone.utc))

        if not id:
            if not (titel or "").strip() or not zeit:
                return "Fehler: Für einen neuen Termin titel und start angeben."
            (name, url), f = self._kalender_wahl(kal, kalender)
            if f:
                return f
            if not url:
                return "Fehler: Kein Kalender gefunden."
            uid = str(uuid.uuid4())
            ev = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{jetzt}", f"CREATED:{jetzt}", f"LAST-MODIFIED:{jetzt}",
                  f"SUMMARY:{_esc(titel.strip())}", zeit[0][0], zeit[1][0]]
            if ort:
                ev.append(f"LOCATION:{_esc(ort)}")
            if beschreibung:
                ev.append(f"DESCRIPTION:{_esc(beschreibung)}")
            ev.append("END:VEVENT")
            ics = "\r\n".join(_falten(z) for z in ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Open WebUI//mailbox_dav//DE", "CALSCALE:GREGORIAN", *ev, "END:VCALENDAR"]) + "\r\n"
            ziel = url.rstrip("/") + f"/{uid}.ics"
            try:
                st, text, _, _ = await self._dav("PUT", ziel, ics, kopf={"If-None-Match": "*"})
            except aiohttp.ClientError as e:
                return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
            if st >= 400:
                return self._fehler(st, text, "dem Eintragen")
            return f"Eingetragen in {name}: {titel.strip()}, {wann}" + (f", {ort}" if ort else "") + f" · id {name}/{uid}.ics"

        name, ziel, f = self._id_aufloesen(kal, id)
        if f:
            return f
        try:
            st, ics, kopf, _ = await self._dav("GET", ziel)
        except aiohttp.ClientError as e:
            return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        if st >= 400:
            return self._fehler(st, ics, "dem Lesen des Termins")
        zeilen = _entfalten(ics)
        bl = _bloecke(zeilen, "VEVENT")
        if not bl:
            return "Fehler: Unter dieser id steht kein Termin."
        master = [x for x in bl if "RECURRENCE-ID" not in _eigenschaften(zeilen[x[0]:x[1] + 1])]
        a, b = (master or bl)[0]
        ev = zeilen[a:b + 1]
        e = _eigenschaften(ev)
        if zeit and ("RRULE" in e or len(bl) > 1):
            return "Fehler: Serientermin – Uhrzeit oder Datum bitte in der Kalender-App ändern; Titel, Ort und Beschreibung gehen hier."
        if not (titel or ort or beschreibung or zeit):
            return "Fehler: Nichts zu ändern (titel, start/ende, ort oder beschreibung angeben)."
        if titel:
            ev = _ersetzen(ev, "SUMMARY", [f"SUMMARY:{_esc(titel.strip())}"])
        if ort:
            ev = _ersetzen(ev, "LOCATION", [f"LOCATION:{_esc(ort)}"])
        if beschreibung:
            ev = _ersetzen(ev, "DESCRIPTION", [f"DESCRIPTION:{_esc(beschreibung)}"])
        if zeit:
            ev = _ersetzen(ev, "DURATION", None)
            ev = _ersetzen(ev, "DTSTART", zeit[0])
            ev = _ersetzen(ev, "DTEND", zeit[1])
        seq = int(re.sub(r"\D", "", e.get("SEQUENCE", [({}, "0")])[0][1]) or 0) + 1
        ev = _ersetzen(ev, "SEQUENCE", [f"SEQUENCE:{seq}"])
        ev = _ersetzen(ev, "LAST-MODIFIED", [f"LAST-MODIFIED:{jetzt}"])
        ev = _ersetzen(ev, "DTSTAMP", [f"DTSTAMP:{jetzt}"])
        neu = zeilen[:a] + ev + zeilen[b + 1:]
        etag = kopf.get("ETag") or kopf.get("Etag")
        try:
            st, text, _, _ = await self._dav("PUT", ziel, "\r\n".join(_falten(z) for z in neu) + "\r\n", kopf={"If-Match": etag} if etag else None)
        except aiohttp.ClientError as e:
            return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        if st >= 400:
            return self._fehler(st, text, "dem Ändern")
        t = _text(_eigenschaften(ev).get("SUMMARY", [({}, "")])[0][1])
        return f"Geändert in {name}: {t}" + (f", {wann}" if zeit else "") + f" · id {id}"

    async def mailbox_termin_loeschen(self, id: str) -> str:
        """
        Löscht einen Termin endgültig (bei Serien die ganze Serie). Nur auf Davids ausdrücklichen Wunsch und wenn das Ventil loeschen_erlaubt an ist.
        :param id: id aus mailbox_termine_lesen, z. B. Privat/abc.ics
        :return: Bestätigung oder Fehler
        """
        f = self._konfig()
        if f:
            return f
        if not self.valves.loeschen_erlaubt:
            return "Fehler: Löschen ist abgeschaltet (Ventil loeschen_erlaubt). David kann den Termin in der Kalender-App löschen."
        kal, _, f = await self._sammlungen()
        if f:
            return f
        name, ziel, f = self._id_aufloesen(kal, id)
        if f:
            return f
        try:
            st, ics, kopf, _ = await self._dav("GET", ziel)
            if st >= 400:
                return self._fehler(st, ics, "dem Lesen des Termins")
            zeilen = _entfalten(ics)
            bl = _bloecke(zeilen, "VEVENT")
            titel = _text(_eigenschaften(zeilen[bl[0][0]:bl[0][1] + 1]).get("SUMMARY", [({}, "")])[0][1]) if bl else ""
            etag = kopf.get("ETag") or kopf.get("Etag")
            st, text, _, _ = await self._dav("DELETE", ziel, kopf={"If-Match": etag} if etag else None)
        except aiohttp.ClientError as e:
            return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        if st >= 400:
            return self._fehler(st, text, "dem Löschen")
        return f"Gelöscht aus {name}: {titel or id}"

    # --- Kontakte ---

    def _kontakt(self, vcf: str) -> dict:
        zeilen = _entfalten(vcf)
        bl = _bloecke(zeilen, "VCARD")
        if not bl:
            return {}
        e = _eigenschaften(zeilen[bl[0][0]:bl[0][1] + 1])
        werte = lambda n: [_text(v) for _, v in e.get(n, []) if v.strip()]
        name = (werte("FN") or [""])[0]
        if not name and e.get("N"):
            teile = [_text(x) for x in e["N"][0][1].split(";")]
            name = " ".join(x for x in (teile[3:4] + teile[1:2] + teile[0:1]) if x).strip()
        adressen = []
        for _, v in e.get("ADR", []):
            t = [_text(x).strip() for x in v.split(";")] + [""] * 7
            adressen.append(", ".join(x for x in [t[2], " ".join(y for y in (t[5], t[3]) if y), t[6]] if x))
        return {"name": name, "email": werte("EMAIL"), "tel": werte("TEL"), "firma": [_text(v.split(";")[0]) for _, v in e.get("ORG", []) if v.strip()],
                "adresse": [a for a in adressen if a], "geburtstag": werte("BDAY"), "notiz": werte("NOTE")}

    async def mailbox_kontakte_suchen(self, suche: str, anzahl: int = 10) -> str:
        """
        Sucht Kontakte im mailbox.org-Adressbuch nach Name, E-Mail, Telefon, Firma oder Ort.
        :param suche: Suchtext, z. B. Müller oder @example.de
        :param anzahl: höchstens so viele Treffer (1–50)
        :return: je Kontakt Name, E-Mail, Telefon, Firma, Adresse, Geburtstag und id
        """
        f = self._konfig()
        if f:
            return f
        q = (suche or "").strip().lower()
        if not q:
            return "Fehler: suche angeben."
        _, adr, f = await self._sammlungen()
        if f:
            return f
        if not adr:
            return "Fehler: Kein Adressbuch gefunden."
        c = self._cache.get("kontakte")
        if not c or time.time() - c[0] > 300 or c[1] != self.valves.benutzer:
            body = ('<?xml version="1.0" encoding="utf-8"?><a:addressbook-query xmlns:d="DAV:" xmlns:a="urn:ietf:params:xml:ns:carddav">'
                    '<d:prop><d:getetag/><a:address-data/></d:prop><a:filter/></a:addressbook-query>')
            alle = []
            for name, url in adr.items():
                try:
                    res, st, text = await self._report(url, body)
                except aiohttp.ClientError as e:
                    return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
                if res is None:
                    return self._fehler(st, text, f"der Abfrage von {name}")
                for href, _, vcf in res:
                    k = self._kontakt(vcf)
                    if k:
                        k["id"] = f"{name}/{unquote(href.rstrip('/').rsplit('/', 1)[-1])}"
                        alle.append(k)
            c = (time.time(), self.valves.benutzer, alle)
            self._cache["kontakte"] = c
        treffer = []
        for k in c[2]:
            heu = " ".join([k["name"], *k["email"], *k["tel"], *k["firma"], *k["adresse"]]).lower()
            ziffern = re.sub(r"\D", "", q)
            if q in heu or (len(ziffern) >= 4 and ziffern in re.sub(r"\D", "", " ".join(k["tel"]))):
                treffer.append(k)
        treffer.sort(key=lambda k: (not k["name"].lower().startswith(q), k["name"].lower()))
        n = min(50, max(1, int(anzahl or 10)))
        zeilen = [f"{len(treffer)} Kontakte mit „{suche}“" + (f", die ersten {n}" if len(treffer) > n else "") + ":"]
        for k in treffer[:n]:
            z = f"- {k['name'] or '(ohne Name)'}"
            for feld, wort in (("email", "E-Mail"), ("tel", "Tel."), ("firma", "Firma"), ("adresse", "Adresse"), ("geburtstag", "Geburtstag")):
                if k[feld]:
                    z += f" · {wort} {', '.join(k[feld])}"
            if k["notiz"]:
                z += f" · Notiz {k['notiz'][0][:80]}"
            z += f" · id {k['id']}"
            zeilen.append(z)
        return "\n".join(zeilen)

    async def mailbox_kontakt_speichern(self, name: str = "", email: str = "", telefon: str = "", firma: str = "", adresse: str = "", geburtstag: str = "", notiz: str = "", id: str = "") -> str:
        """
        Legt einen Kontakt an (ohne id) oder ergänzt einen bestehenden (mit id aus mailbox_kontakte_suchen). E-Mail und Telefon kommen beim Ergänzen dazu, ohne vorhandene zu entfernen; Name, Firma, Adresse, Geburtstag und Notiz werden ersetzt. Nur nach Davids Bestätigung aufrufen.
        :param name: voller Name, z. B. Anna Müller (Pflicht bei neuem Kontakt)
        :param email: E-Mail-Adresse
        :param telefon: Telefonnummer
        :param firma: Firma oder Organisation
        :param adresse: Postanschrift als „Straße Nr, PLZ Ort, Land“
        :param geburtstag: 1980-05-17
        :param notiz: Notiz
        :param id: id eines bestehenden Kontakts zum Ergänzen
        :return: Bestätigung mit id oder Fehler
        """
        f = self._konfig()
        if f:
            return f
        if not self.valves.kontakte_schreiben:
            return "Fehler: Kontakte schreiben ist abgeschaltet (Ventil kontakte_schreiben)."
        if geburtstag and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", geburtstag.strip()):
            return "Fehler: geburtstag als 1980-05-17 angeben."
        _, adr, f = await self._sammlungen()
        if f:
            return f
        if not adr:
            return "Fehler: Kein Adressbuch gefunden."

        def adr_zeile(text: str) -> str:
            t = [x.strip() for x in text.split(",")]
            strasse = t[0] if t else ""
            plz, ort = "", ""
            if len(t) > 1:
                m = re.match(r"(\d{4,5})\s+(.*)", t[1])
                plz, ort = (m.group(1), m.group(2)) if m else ("", t[1])
            land = t[2] if len(t) > 2 else ""
            return "ADR;TYPE=HOME:;;" + ";".join(_esc(x) for x in (strasse, ort, "", plz, land))

        def n_zeile(voll: str) -> str:
            teile = voll.strip().split()
            return f"N:{_esc(teile[-1]) if teile else ''};{_esc(' '.join(teile[:-1]))};;;"

        self._cache.pop("kontakte", None)
        if not id:
            if not (name or "").strip():
                return "Fehler: Für einen neuen Kontakt name angeben."
            uid = str(uuid.uuid4())
            karte = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//Open WebUI//mailbox_dav//DE", f"UID:{uid}", f"FN:{_esc(name.strip())}", n_zeile(name)]
            if email:
                karte.append(f"EMAIL;TYPE=INTERNET:{_esc(email.strip())}")
            if telefon:
                karte.append(f"TEL;TYPE=VOICE:{_esc(telefon.strip())}")
            if firma:
                karte.append(f"ORG:{_esc(firma.strip())}")
            if adresse:
                karte.append(adr_zeile(adresse))
            if geburtstag:
                karte.append(f"BDAY:{geburtstag.strip()}")
            if notiz:
                karte.append(f"NOTE:{_esc(notiz)}")
            karte += [f"REV:{_utc(datetime.now(timezone.utc))}", "END:VCARD"]
            buch, url = next(iter(adr.items()))
            ziel = url.rstrip("/") + f"/{uid}.vcf"
            try:
                st, text, _, _ = await self._dav("PUT", ziel, "\r\n".join(_falten(z) for z in karte) + "\r\n", kopf={"If-None-Match": "*"})
            except aiohttp.ClientError as e:
                return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
            if st >= 400:
                return self._fehler(st, text, "dem Anlegen")
            return f"Angelegt in {buch}: {name.strip()} · id {buch}/{uid}.vcf"

        buch, ziel, f = self._id_aufloesen(adr, id)
        if f:
            return f
        if not any((name, email, telefon, firma, adresse, geburtstag, notiz)):
            return "Fehler: Nichts zu ändern."
        try:
            st, vcf, kopf, _ = await self._dav("GET", ziel)
        except aiohttp.ClientError as e:
            return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        if st >= 400:
            return self._fehler(st, vcf, "dem Lesen des Kontakts")
        zeilen = _entfalten(vcf)
        bl = _bloecke(zeilen, "VCARD")
        if not bl:
            return "Fehler: Unter dieser id steht kein Kontakt."
        a, b = bl[0]
        karte = zeilen[a:b + 1]
        vorher = self._kontakt("\r\n".join(karte))
        if name:
            karte = _ersetzen(karte, "FN", [f"FN:{_esc(name.strip())}"])
            karte = _ersetzen(karte, "N", [n_zeile(name)])
        if email and email.strip().lower() not in [x.lower() for x in vorher["email"]]:
            karte = karte[:-1] + [f"EMAIL;TYPE=INTERNET:{_esc(email.strip())}"] + karte[-1:]
        if telefon and re.sub(r"\D", "", telefon) not in [re.sub(r"\D", "", x) for x in vorher["tel"]]:
            karte = karte[:-1] + [f"TEL;TYPE=VOICE:{_esc(telefon.strip())}"] + karte[-1:]
        if firma:
            karte = _ersetzen(karte, "ORG", [f"ORG:{_esc(firma.strip())}"])
        if adresse:
            karte = _ersetzen(karte, "ADR", [adr_zeile(adresse)])
        if geburtstag:
            karte = _ersetzen(karte, "BDAY", [f"BDAY:{geburtstag.strip()}"])
        if notiz:
            karte = _ersetzen(karte, "NOTE", [f"NOTE:{_esc(notiz)}"])
        karte = _ersetzen(karte, "REV", [f"REV:{_utc(datetime.now(timezone.utc))}"])
        neu = zeilen[:a] + karte + zeilen[b + 1:]
        etag = kopf.get("ETag") or kopf.get("Etag")
        try:
            st, text, _, _ = await self._dav("PUT", ziel, "\r\n".join(_falten(z) for z in neu) + "\r\n", kopf={"If-Match": etag} if etag else None)
        except aiohttp.ClientError as e:
            return f"Fehler: mailbox.org nicht erreichbar ({type(e).__name__}: {e})."
        if st >= 400:
            return self._fehler(st, text, "dem Ändern")
        return f"Geändert in {buch}: {self._kontakt(chr(10).join(karte))['name']} · id {id}"
