"""
title: HA-Aufgaben
author: David
version: 1.1.1
description: Aufgabenlisten und Einkaufsliste aus Home Assistant: lesen, Einträge anlegen, abhaken, ändern. Nur die in den Ventilen freigegebenen Listen, sonst nichts an Home Assistant. Termine stehen im Werkzeug mailbox.org Kalender & Kontakte.
requirements:
"""

# Ersetzt ha-mcp für den persönlichen Assistenten: vier kleine Funktionen statt der allgemeinen
# HA-Werkzeuge. Zugriff über die REST-API mit einem eigenen Token (am besten eines Nicht-Admin-
# Benutzers), beschränkt auf die freigegebenen Entitäten.

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import BaseModel, Field

TZ = ZoneInfo("Europe/Berlin")
WOCHENTAG = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
AKTIONEN = ("neu", "erledigt", "offen", "aendern", "entfernen")


def _liste(text: str) -> list:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def _zeit(wert: Any) -> str:
    """ISO-Datum oder -Zeit lesbar mit Wochentag: Do, 20.11.2026 14:00."""
    if isinstance(wert, dict):
        wert = wert.get("dateTime") or wert.get("date")
    s = str(wert or "")
    try:
        if len(s) == 10:
            d = date.fromisoformat(s)
            return f"{WOCHENTAG[d.weekday()]}, {d:%d.%m.%Y}"
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = dt.astimezone(TZ) if dt.tzinfo else dt
        return f"{WOCHENTAG[dt.weekday()]}, {dt:%d.%m.%Y %H:%M}"
    except ValueError:
        return s


def _datum_oder_zeit(s: str) -> tuple:
    """'2026-11-20' -> ('date', ...); '2026-11-20T14:00' -> ('datetime', aware)."""
    s = (s or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "date", date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))
    return "datetime", dt if dt.tzinfo else dt.replace(tzinfo=TZ)


class Tools:
    class Valves(BaseModel):
        ha_url: str = Field(default="http://homeassistant:8123", description="Adresse von Home Assistant aus Sicht von Open WebUI, ohne / am Ende")
        token: str = Field(default="", description="Langlebiges Zugriffstoken, am besten eines eigenen Nicht-Admin-Benutzers (Profil → Sicherheit)")
        erlaubte_listen: str = Field(default="todo.aufgaben,todo.shopping_list", description="Aufgabenlisten (todo.*), Komma-getrennt")
        schreiben_erlaubt: bool = Field(default=True, description="Einträge anlegen, abhaken, ändern")
        entfernen_erlaubt: bool = Field(default=False, description="Einträge endgültig entfernen")
        timeout: int = Field(default=20, description="Zeitlimit je Aufruf in Sekunden")

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()

    def _konfig(self) -> Optional[str]:
        if not self.valves.token:
            return "Fehler: Kein Token im Ventil token. David muss es in den Ventilen des Werkzeugs „HA-Aufgaben“ eintragen."
        return None

    def _entitaet(self, wert: str, erlaubt: str, art: str) -> tuple:
        e = (wert or "").strip()
        liste = _liste(erlaubt)
        if not e and liste:
            e = liste[0]
        if e not in liste:
            return None, f"Fehler: {art} „{e}“ ist nicht freigegeben. Erlaubt: {', '.join(liste) or 'keine'}."
        return e, None

    async def _anfrage(self, methode: str, pfad: str, daten: Any = None) -> tuple:
        kopf = {"Authorization": "Bearer " + self.valves.token, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout)) as s:
            async with s.request(methode, self.valves.ha_url.rstrip("/") + pfad, headers=kopf, json=daten) as r:
                text = (await r.text()).replace(self.valves.token, "***")
                try:
                    return r.status, json.loads(text) if text.strip() else None
                except ValueError:
                    return r.status, text

    async def _dienst(self, dienst: str, daten: dict, antwort: bool = False) -> tuple:
        pfad = "/api/services/" + dienst.replace(".", "/") + ("?return_response" if antwort else "")
        try:
            st, d = await self._anfrage("POST", pfad, daten)
        except Exception as e:
            return None, f"Fehler: Home Assistant nicht erreichbar ({type(e).__name__}: {e})."
        if st == 401:
            return None, "Fehler: Token abgelehnt (HTTP 401). David muss das Token im Ventil prüfen."
        if st >= 400:
            msg = d.get("message") if isinstance(d, dict) else str(d)[:300]
            if "did not match any entities" in str(msg):
                msg = f"{msg} – die Liste gibt es in Home Assistant nicht; Entität in den Ventilen prüfen ({self.valves.erlaubte_listen})"
            return None, f"Fehler von Home Assistant bei {dienst} (HTTP {st}): {msg}"
        return d, None

    async def ha_aufgaben_lesen(self, liste: str = "", status: str = "offen", suche: str = "") -> str:
        """
        Liest Einträge einer Aufgabenliste (z. B. todo.aufgaben, todo.einkaufsliste) oder aller freigegebenen Listen (liste="alle").
        :param liste: Entität der Liste oder "alle"; leer = erste freigegebene Liste
        :param status: offen, erledigt oder alle
        :param suche: optional nur Einträge, die diesen Text enthalten (ohne Groß-/Kleinschreibung), z. B. @David@
        :return: je Eintrag eine Zeile: Status, Text, Fälligkeit
        """
        f = self._konfig()
        if f:
            return f
        if (liste or "").strip().lower() == "alle":
            listen = _liste(self.valves.erlaubte_listen)
        else:
            e, f = self._entitaet(liste, self.valves.erlaubte_listen, "Liste")
            if f:
                return f
            listen = [e]
        st_map = {"offen": ["needs_action"], "erledigt": ["completed"], "alle": ["needs_action", "completed"]}
        if status not in st_map:
            return "Fehler: status muss offen, erledigt oder alle sein."
        d, f = await self._dienst("todo.get_items", {"entity_id": listen, "status": st_map[status]}, antwort=True)
        if f:
            return f
        antwort = (d or {}).get("service_response", d) if isinstance(d, dict) else {}
        zeilen = []
        for e in listen:
            if e not in (antwort or {}):
                zeilen.append(f"{e}: gibt es in Home Assistant nicht (Entität in den Ventilen prüfen).")
                continue
            items = ((antwort or {}).get(e) or {}).get("items") or []
            if suche:
                items = [i for i in items if suche.lower() in (i.get("summary", "") + " " + (i.get("description") or "")).lower()]
            zeilen.append(f"{e} ({len(items)}):")
            for i in items:
                z = f"- [{'x' if i.get('status') == 'completed' else ' '}] {i.get('summary', '')}"
                if i.get("due"):
                    z += f" (fällig {_zeit(i['due'])})"
                if i.get("description"):
                    z += f" – {i['description'][:120]}"
                zeilen.append(z)
        return "\n".join(zeilen)

    async def ha_aufgaben_aendern(self, liste: str, aenderungen: list[dict]) -> str:
        """
        Ändert Einträge einer Aufgabenliste, mehrere in einem Schritt. Jede Änderung: {"aktion": "neu"|"erledigt"|"offen"|"aendern"|"entfernen", "eintrag": "<Text oder uid>", "neu": "<neuer Text, nur aendern>", "faellig": "2026-11-20" oder "2026-11-20T18:00", "beschreibung": "…"}.
        :param liste: Entität der Liste, z. B. todo.aufgaben
        :param aenderungen: Liste der Änderungen (als Liste, nicht als Text)
        :return: je Änderung eine Zeile mit Ergebnis
        """
        f = self._konfig()
        if f:
            return f
        if not self.valves.schreiben_erlaubt:
            return "Fehler: Schreiben ist abgeschaltet (Ventil schreiben_erlaubt)."
        e, f = self._entitaet(liste, self.valves.erlaubte_listen, "Liste")
        if f:
            return f
        if isinstance(aenderungen, str):
            try:
                aenderungen = json.loads(aenderungen)
            except ValueError:
                return "Fehler: aenderungen ist kein gültiges JSON."
        if not isinstance(aenderungen, list) or not aenderungen or not all(isinstance(a, dict) for a in aenderungen):
            return 'Fehler: aenderungen muss eine Liste sein, z. B. [{"aktion": "neu", "eintrag": "@David@ Steuer"}].'
        zeilen = []
        for n, a in enumerate(aenderungen):
            akt, text = str(a.get("aktion", "")).lower(), str(a.get("eintrag", "")).strip()
            if akt not in AKTIONEN or not text:
                zeilen.append(f"[{n}] Fehler: aktion ({', '.join(AKTIONEN)}) und eintrag angeben.")
                continue
            daten: dict = {"entity_id": e, "item": text}
            if akt == "entfernen":
                if not self.valves.entfernen_erlaubt:
                    zeilen.append(f"[{n}] Fehler: Entfernen ist abgeschaltet (Ventil entfernen_erlaubt); stattdessen abhaken.")
                    continue
                dienst = "todo.remove_item"
            elif akt == "neu":
                dienst = "todo.add_item"
            else:
                dienst = "todo.update_item"
                if akt == "erledigt":
                    daten["status"] = "completed"
                elif akt == "offen":
                    daten["status"] = "needs_action"
                elif a.get("neu"):
                    daten["rename"] = str(a["neu"])
            if a.get("faellig") and akt != "entfernen":
                try:
                    art, wert = _datum_oder_zeit(str(a["faellig"]))
                except ValueError:
                    zeilen.append(f"[{n}] Fehler: faellig als 2026-11-20 oder 2026-11-20T18:00 angeben.")
                    continue
                daten["due_date" if art == "date" else "due_datetime"] = wert.isoformat()
            if a.get("beschreibung") and akt != "entfernen":
                daten["description"] = str(a["beschreibung"])
            if dienst == "todo.update_item" and len(daten) == 2:
                zeilen.append(f"[{n}] Fehler: für aendern neu, faellig oder beschreibung angeben.")
                continue
            if dienst == "todo.add_item":
                daten["item"] = text
            _, f = await self._dienst(dienst, daten)
            zeilen.append(f"[{n}] {akt} „{text}“: " + (f or "ok"))
        return "\n".join(zeilen)
