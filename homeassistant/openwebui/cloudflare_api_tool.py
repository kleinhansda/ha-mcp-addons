"""
title: Cloudflare-API
author: David
version: 1.1.0
description: Cloudflare-API (client/v4) mit API-Token: Zonen, DNS-Einträge, Tunnel, Zugriffsregeln, Workers lesen und nach Freigabe ändern; ein Aufruf oder viele in einem Schritt. Löschen per Ventil. Tunnel-Routen (Public Hostnames) einzeln ändern, mit Bestätigungsdialog und Sicherung.
"""

# Nachfolger von cloudflare_api2 (lud seine Ventile nie, blockierende Aufrufe, falscher Import).
# Aus der Vorlage owui-werkzeug/rest_api.py; Cloudflare meldet Fehler im Feld errors (success=false).

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, Field

# {{n:pfad.im.json}} = Wert aus der Antwort von Aufruf n (ab 0), z. B. {{0:data.id}}
VERWEIS_RE = re.compile(r"\{\{(\d+):([\w.\-]*)\}\}")
HOST_RE = re.compile(r"^(?=.{1,253}$)(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
ZIEL_RE = re.compile(r"^(https?|tcp|ssh|rdp|unix|smb)://[A-Za-z0-9._\[\]:/-]{1,200}$|^http_status:[1-5][0-9]{2}$|^hello_world$")
PFAD_ROUTE_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@/^\\\[\]{}|?-]{1,200}$")


def _regel_text(r: dict) -> str:
    """Eine Ingress-Regel als Zeile: host[/pfad] -> ziel (Optionen)."""
    if not isinstance(r, dict):
        return str(r)
    ziel = f"{r.get('hostname') or '*'}{('/' + r['path'].lstrip('/')) if r.get('path') else ''} -> {r.get('service')}"
    o = r.get("originRequest") or {}
    return ziel + (f"  ({', '.join(f'{k}={v}' for k, v in sorted(o.items()))})" if o else "")


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
        konto_id: str = Field(default="", description="Cloudflare-Konto-ID für Tunnel; leer = automatisch, wenn das Token genau ein Konto sieht")
        tunnel_schreiben_erlaubt: bool = Field(default=True, description="cloudflare_tunnel_route_setzen darf Routen ändern (immer nur nach Bestätigung im Dialog)")
        sicherungs_ordner: str = Field(default="", description="Ordner für Sicherungen der Tunnel-Konfiguration; leer = DATA_DIR/cloudflare_tunnel_sicherungen")

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

    # ---------------------------------------------------------------- Tunnel-Routen

    async def _aufruf(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten: Any = None) -> Any:
        """Aufruf mit Prüfung; gibt result zurück oder wirft ValueError mit der Cloudflare-Meldung."""
        f = self._pruefen(methode, pfad)
        if f:
            raise ValueError(f)
        status, text = await self._senden(s, methode, pfad, daten)
        try:
            d = json.loads(text) if text else {}
        except ValueError:
            d = {}
        if status >= 400:
            fehler = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in (d.get("errors") or []) if isinstance(e, dict))
            if status in (403, 404) and "/cfd_tunnel" in pfad:
                fehler += " (Hat das Token das Recht Konto → Cloudflare Tunnel → Bearbeiten/Lesen?)"
            raise ValueError(f"{methode} {pfad.split('?')[0]}: HTTP {status} {fehler}".strip())
        return d.get("result")

    async def _tunnel(self, s: aiohttp.ClientSession, tunnel: str) -> tuple:
        """Konto-ID und Tunnel (id, name) aus Name oder ID ermitteln."""
        konto = self.valves.konto_id.strip()
        if not konto:
            konten = await self._aufruf(s, "GET", "/accounts?per_page=50") or []
            if len(konten) != 1:
                raise ValueError(f"Token sieht {len(konten)} Konten; Ventil konto_id setzen.")
            konto = konten[0]["id"]
        if not re.fullmatch(r"[0-9a-f]{32}", konto):
            raise ValueError("konto_id ungültig.")
        liste = await self._aufruf(s, "GET", f"/accounts/{konto}/cfd_tunnel?is_deleted=false&per_page=100") or []
        t = (tunnel or "").strip()
        treffer = [x for x in liste if t and (x.get("id") == t or x.get("name") == t)] if t else liste
        if len(treffer) != 1:
            namen = ", ".join(f"{x.get('name')}" for x in liste) or "keine"
            raise ValueError(f"Tunnel „{t}“ nicht eindeutig gefunden. Vorhanden: {namen}.")
        return konto, treffer[0]["id"], treffer[0].get("name")

    async def cloudflare_tunnel_routen(self, tunnel: str = "", __event_emitter__=None) -> str:
        """
        Zeigt die Routen (Public Hostnames) eines im Dashboard verwalteten Cloudflare-Tunnels: Hostname, Pfad, Ziel, Optionen. Nur lesend.
        :param tunnel: Name oder ID des Tunnels, z. B. hassio; leer = der einzige Tunnel
        :return: Routen in Reihenfolge, letzte ist die Auffangregel
        """
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout)) as s:
                konto, tid, name = await self._tunnel(s, tunnel)
                cfg = await self._aufruf(s, "GET", f"/accounts/{konto}/cfd_tunnel/{tid}/configurations") or {}
        except Exception as e:
            return f"Fehler: {e}"
        ingress = ((cfg.get("config") or {}).get("ingress")) or []
        zeilen = [f"Tunnel {name} ({tid}), Version {cfg.get('version')}, verwaltet: {cfg.get('source') or '?'}"]
        zeilen += [f"{i}. {_regel_text(r)}" for i, r in enumerate(ingress, 1)]
        return "\n".join(zeilen)

    async def cloudflare_tunnel_route_setzen(self, hostname: str, ziel: str = "", tunnel: str = "", pfad: str = "",
                                            tls_pruefen: bool = True, alter_hostname: str = "", entfernen: bool = False,
                                            dns_anlegen: bool = True, __event_emitter__=None, __event_call__=None) -> str:
        """
        Ändert GENAU EINE Route eines im Dashboard verwalteten Cloudflare-Tunnels und lässt alle anderen unverändert: anlegen, Ziel ändern, umbenennen (alter_hostname) oder entfernen. Zeigt David vorher einen Bestätigungsdialog mit alt → neu, sichert die bisherige Konfiguration und liest danach zurück. Legt auf Wunsch den DNS-Eintrag (CNAME auf den Tunnel) an, löscht aber nie DNS-Einträge.
        :param hostname: Hostname der Route, z. B. office.ddsk.cloud
        :param ziel: Dienst hinter der Route, z. B. http://192.168.10.40:9980 oder https://192.168.10.40:447 (leer nur beim Entfernen)
        :param tunnel: Name oder ID des Tunnels, z. B. hassio; leer = der einzige Tunnel
        :param pfad: optionaler Pfad (Regex) der Route; leer = ganzer Hostname (beim Umbenennen fällt ein alter Pfad dann weg)
        :param tls_pruefen: false = Zertifikat des Ziels nicht prüfen (noTLSVerify), z. B. bei selbst signiertem HTTPS
        :param alter_hostname: zum Umbenennen: bisheriger Hostname; Position und übrige Optionen bleiben
        :param entfernen: true = Route entfernen
        :param dns_anlegen: CNAME für hostname anlegen, falls er fehlt
        :return: Ergebnis mit Unterschied, Sicherung und Prüfung
        """
        if not self.valves.tunnel_schreiben_erlaubt:
            return "Fehler: Routen ändern ist abgeschaltet (Ventil tunnel_schreiben_erlaubt)."
        h, alt_h = (hostname or "").strip().lower().rstrip("."), (alter_hostname or "").strip().lower().rstrip(".")
        if not HOST_RE.match(h) or (alt_h and not HOST_RE.match(alt_h)):
            return "Fehler: Hostname ungültig, z. B. office.ddsk.cloud."
        z = (ziel or "").strip()
        if not entfernen and not ZIEL_RE.match(z):
            return "Fehler: ziel ungültig, z. B. http://192.168.10.40:9980, https://host:447 oder http_status:404."
        pf = (pfad or "").strip()
        if pf and not PFAD_ROUTE_RE.match(pf):
            return "Fehler: pfad ungültig."
        if __event_call__ is None:
            return "Fehler: Ohne Bestätigungsdialog (kein Chat) wird nichts geändert."
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.valves.timeout)) as s:
                konto, tid, name = await self._tunnel(s, tunnel)
                cfg_pfad = f"/accounts/{konto}/cfd_tunnel/{tid}/configurations"
                cfg = await self._aufruf(s, "GET", cfg_pfad) or {}
                if cfg.get("source") and cfg.get("source") != "cloudflare":
                    return f"Fehler: Tunnel {name} wird lokal verwaltet (source={cfg.get('source')}); Routen stehen in seiner config.yml."
                config = dict(cfg.get("config") or {})
                ingress = [dict(r) for r in (config.get("ingress") or [])]
                if not ingress or ingress[-1].get("hostname"):
                    ingress.append({"service": "http_status:404"})   # Auffangregel muss die letzte sein
                if alt_h:   # Umbenennen: alte Route nur am Hostnamen erkennen (Pfad egal), muss eindeutig sein
                    idx = [i for i, r in enumerate(ingress) if (r.get("hostname") or "").lower() == alt_h]
                    if len(idx) != 1:
                        return f"Fehler: Route {alt_h} gibt es {len(idx)}-mal statt einmal. Nichts geändert."
                else:
                    idx = [i for i, r in enumerate(ingress) if (r.get("hostname") or "").lower() == h and (r.get("path") or "") == pf]
                if alt_h and any((r.get("hostname") or "").lower() == h and (r.get("path") or "") == pf for r in ingress):
                    return f"Fehler: Route {h} gibt es schon. Nichts geändert."
                vorher = [_regel_text(r) for r in ingress]
                if entfernen:
                    if not idx:
                        return f"Route {h} gibt es nicht. Nichts geändert."
                    alt_regel = ingress.pop(idx[0])
                    aenderung = f"entfernen: {_regel_text(alt_regel)}"
                else:
                    if idx:
                        r = ingress[idx[0]]
                        alt_text = _regel_text(r)
                    else:
                        r, alt_text = {}, "(neu)"
                        ingress.insert(len(ingress) - 1, r)
                    r["hostname"] = h
                    if pf:
                        r["path"] = pf
                    else:
                        r.pop("path", None)
                    r["service"] = z
                    o = dict(r.get("originRequest") or {})
                    if tls_pruefen:
                        o.pop("noTLSVerify", None)
                    else:
                        o["noTLSVerify"] = True
                    if o:
                        r["originRequest"] = o
                    else:
                        r.pop("originRequest", None)
                    aenderung = f"{alt_text}  →  {_regel_text(r)}"
                config["ingress"] = ingress
                nachher = [_regel_text(r) for r in ingress]
                if nachher == vorher:
                    return f"Keine Änderung nötig: {_regel_text(ingress[idx[0]]) if idx else h}."
                # Bestätigung durch David
                ok = await __event_call__({"type": "confirmation", "data": {
                    "title": f"Cloudflare-Tunnel {name}: Route ändern?",
                    "message": f"{aenderung}\n\nAlle anderen {len(ingress) - (0 if entfernen else 1)} Routen bleiben unverändert."}})
                if not ok:
                    return "Abgebrochen: David hat nicht bestätigt. Nichts geändert."
                # Sicherung
                ordner = self.valves.sicherungs_ordner.strip() or os.path.join(os.environ.get("DATA_DIR", "/app/backend/data"), "cloudflare_tunnel_sicherungen")
                os.makedirs(ordner, mode=0o700, exist_ok=True)
                datei = os.path.join(ordner, f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.json")
                n = 1
                while os.path.exists(datei):
                    n += 1
                    datei = os.path.join(ordner, f"{name}_{time.strftime('%Y%m%d-%H%M%S')}_{n}.json")
                with open(datei, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, ensure_ascii=False, indent=1)
                await self._aufruf(s, "PUT", cfg_pfad, {"config": config})
                neu = await self._aufruf(s, "GET", cfg_pfad) or {}
                gelesen = [_regel_text(r) for r in ((neu.get("config") or {}).get("ingress") or [])]
                pruefung = "zurückgelesen, stimmt" if gelesen == nachher else "ABWEICHUNG beim Zurücklesen, bitte Routen prüfen"
                dns = ""
                if dns_anlegen and not entfernen:
                    dns = await self._dns_sicherstellen(s, h, tid)
        except Exception as e:
            return f"Fehler: {e}. Nichts geändert, außer es steht oben anders."
        teile = [f"Tunnel {name}: {aenderung}", f"Prüfung: {pruefung}", f"Sicherung: {datei}"]
        if dns:
            teile.append(f"DNS: {dns}")
        if alt_h:
            teile.append(f"Hinweis: Der DNS-Eintrag {alt_h} bleibt bestehen; bei Bedarf David fragen, ob er gelöscht werden soll.")
        return "\n".join(teile)

    async def _dns_sicherstellen(self, s: aiohttp.ClientSession, h: str, tid: str) -> str:
        """CNAME h -> <tunnel>.cfargotunnel.com anlegen, falls kein Eintrag da ist. Ändert und löscht nie."""
        ziel = f"{tid}.cfargotunnel.com"
        teile = h.lstrip("*.").split(".")
        zone = None
        for i in range(len(teile) - 1):
            kandidat = ".".join(teile[i:])
            z = await self._aufruf(s, "GET", f"/zones?name={kandidat}") or []
            if z:
                zone = z[0]
                break
        if not zone:
            return f"keine passende Zone für {h} gefunden, CNAME bitte selbst anlegen"
        da = await self._aufruf(s, "GET", f"/zones/{zone['id']}/dns_records?name={h}") or []
        if da:
            r = da[0]
            if r.get("type") == "CNAME" and r.get("content") == ziel:
                return f"CNAME {h} zeigt schon auf den Tunnel"
            return f"Eintrag {h} existiert schon ({r.get('type')} → {r.get('content')}), nicht geändert"
        await self._aufruf(s, "POST", f"/zones/{zone['id']}/dns_records",
                           {"type": "CNAME", "name": h, "content": ziel, "proxied": True, "comment": "Tunnel-Route (Open WebUI)"})
        return f"CNAME {h} → Tunnel angelegt (proxied)"
