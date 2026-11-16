"""
title: KI-Wochenanalyse
author: David
version: 0.1.0
description: Wertet die Antworten der letzten Tage direkt in der Open-WebUI-Datenbank aus (Kosten je Antwort, Werkzeugschritte, Werkzeuge nach Mitschlepp, Werkzeugprobleme, Schrittgrenze, Fehler, Bewertungen) und schreibt Bericht, Kennzahlen und die Konfiguration der genutzten Modelle nach /share/ki_analyse/. Chat-Inhalte verlassen Open WebUI nicht; wörtlich erscheinen nur „Werkzeugproblem:“-Zeilen und Fehlermeldungen aus Chats des aufrufenden Admins. Nur für Admins.
"""

import json
import os
import re
import time
from datetime import date

from pydantic import BaseModel, Field

NL = chr(10)
WP = re.compile("Werkzeugproblem:.{0,300}")   # Punkt ohne Zeilenumbruch


def _laenge(x) -> int:
    if isinstance(x, str):
        return len(x)
    if isinstance(x, list):
        n = 0
        for t in x:
            if isinstance(t, dict):
                if t.get("type") not in ("input_image", "image_url", "image"):
                    n += len(str(t.get("text") or t.get("output") or ""))
            else:
                n += len(str(t))
        return n
    return len(str(x)) if x is not None else 0


def _texte(content, output) -> str:
    teile = []
    if isinstance(content, str):
        teile.append(content)
    elif isinstance(content, list):
        teile += [str(t.get("text") or "") for t in content if isinstance(t, dict)]
    for it in output or []:
        if isinstance(it, dict) and it.get("type") == "message":
            teile += [str(t.get("text") or "") for t in it.get("content") or [] if isinstance(t, dict)]
    return NL.join(teile)


def _kennzahlen(usage, output):
    u = usage or {}
    ein = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
    aus = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
    det = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    cache = int((det.get("cached_tokens") if isinstance(det, dict) else 0) or 0)
    namen, schritte = {}, []
    for it in output or []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == "function_call":
            namen[it.get("call_id")] = (it.get("name") or "?", len(str(it.get("arguments") or "")))
        elif it.get("type") == "function_call_output":
            name, arg = namen.get(it.get("call_id"), ("?", 0))
            schritte.append((name, arg, _laenge(it.get("output"))))
    return ein, aus, min(cache, ein), schritte


class Tools:
    class Valves(BaseModel):
        ziel: str = Field(default="/share/ki_analyse", description="Ordner für Bericht, Kennzahlen und Modellkonfiguration")
        chat_link: str = Field(default="https://ai.ddsk.cloud/c/", description="Basis für Links auf Chats im Bericht")
        schritt_grenze: int = Field(default=40, description="CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS")
        preise: str = Field(
            default='{"glm-5.3": [1.80, null, 5.51], "glm-5.2": [1.82, null, null], "qwen3.8-27b": [0.60, 0.12, 3.30], '
            '"qwen3.6-35b": [0.25, null, 1.51], "qwen3.5-397b": [0.60, null, null], "mistral-medium": [1.50, null, null], '
            '"mistral-large": [0.5, null, 1.5]}',
            description="Euro je 1 Mio. Tokens [Eingabe, Eingabe aus Cache, Ausgabe] je Teil der Grundmodell-ID (JSON, null = unbekannt)",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _euro(self, preise, basis, ein, cache, aus):
        name = basis.split(".", 1)[1] if basis.startswith("mstrl.") else basis
        treffer = [k for k in preise if k in name]
        if not treffer:
            return None
        p = preise[max(treffer, key=len)]
        if p[0] is None or (aus and p[2] is None):
            return None
        pc = p[1] if p[1] is not None else p[0]
        return ((ein - cache) * p[0] + cache * pc + aus * (p[2] or 0)) / 1e6

    async def ki_wochenanalyse(self, tage: int = 7, __user__: dict = None, __event_emitter__=None) -> str:
        """
        Erstellt die KI-Wochenanalyse: Kennzahlen je Modell und Werkzeug für die letzten Tage mit Vergleich
        zum gleich langen Zeitraum davor. Schreibt woche_<datum>.md (Bericht), woche_<datum>.json und
        woche_latest.json (Kennzahlen) sowie modelle/<id>.md und modelle/_harness_filter.py (aktuelle
        Konfiguration) in den Zielordner.
        :param tage: Zeitraum in Tagen, Standard 7
        :return: Pfad des Berichts und Kurzfassung
        """
        if (__user__ or {}).get("role") != "admin":
            return "Fehler: Die KI-Wochenanalyse ist nur für Admins."
        from open_webui.internal.db import get_async_db_context
        from open_webui.models.chat_messages import ChatMessage
        from open_webui.models.feedbacks import Feedbacks
        from open_webui.models.functions import Functions
        from open_webui.models.models import Models
        from sqlalchemy import select

        v = self.valves
        ich = __user__.get("id")
        tage = max(1, min(int(tage or 7), 45))
        jetzt = int(time.time())
        start = jetzt - tage * 86400
        start_vorher = start - tage * 86400
        preise = json.loads(v.preise)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "KI-Wochenanalyse: lese Antworten", "done": False}})

        async with get_async_db_context() as db:
            res = await db.execute(
                select(ChatMessage.model_id, ChatMessage.user_id, ChatMessage.chat_id, ChatMessage.created_at,
                       ChatMessage.usage, ChatMessage.output, ChatMessage.error, ChatMessage.content)
                .where(ChatMessage.role == "assistant", ChatMessage.created_at >= start_vorher)
            )
            zeilen = res.all()
        modelle = {m.id: m for m in await Models.get_all_models()}

        def grund(mid):
            gesehen = set()
            while mid in modelle and mid not in gesehen:
                gesehen.add(mid)
                if not modelle[mid].base_model_id:
                    break
                mid = modelle[mid].base_model_id
            return mid

        woche = {"jetzt": {}, "vorher": {}}
        wz = {}
        auff = {"werkzeugproblem": [], "grenze": [], "fehler": [], "runter": [], "teuer": []}
        zaehler = {"werkzeugproblem": 0, "grenze": 0, "fehler": 0, "runter": 0, "hoch": 0}
        for mid, uid, cid, t, usage, output, fehler, content in zeilen:
            jetzt_ = (t or 0) >= start
            mid = mid or "?"
            basis = grund(mid)
            ein, aus, cache, s = _kennzahlen(usage, output)
            eur = self._euro(preise, basis, ein, cache, aus)
            z = woche["jetzt" if jetzt_ else "vorher"].setdefault(mid, {
                "basis": basis, "antworten": 0, "schritte": 0, "max_schritte": 0, "ein": 0, "aus": 0,
                "cache": 0, "euro": 0.0, "ohne_preis": 0})
            z["antworten"] += 1
            z["schritte"] += len(s)
            z["max_schritte"] = max(z["max_schritte"], len(s))
            z["ein"] += ein
            z["aus"] += aus
            z["cache"] += cache
            if eur is None:
                z["ohne_preis"] += 1
            else:
                z["euro"] += eur
            if not jetzt_:
                continue
            for i, (name, arg, n) in enumerate(s):
                w = wz.setdefault(name, {"aufrufe": 0, "zeichen": 0, "max": 0, "mitschlepp": 0})
                w["aufrufe"] += 1
                w["zeichen"] += n
                w["max"] = max(w["max"], n)
                w["mitschlepp"] += (n + arg) * (len(s) - i - 1)
            eigen = uid == ich
            link = v.chat_link + str(cid or "")
            probleme = WP.findall(_texte(content, output))
            if probleme:
                zaehler["werkzeugproblem"] += 1
                if eigen:
                    auff["werkzeugproblem"].append((mid, link, probleme[0]))
            if len(s) >= v.schritt_grenze:
                zaehler["grenze"] += 1
                if eigen:
                    auff["grenze"].append((mid, link, f"{len(s)} Schritte"))
            if fehler and fehler not in ({}, "", False):
                zaehler["fehler"] += 1
                if eigen:
                    text = (fehler.get("content") or fehler.get("message") or str(fehler)) if isinstance(fehler, dict) else str(fehler)
                    auff["fehler"].append((mid, link, " ".join(str(text).split())[:200]))
            if eigen:
                auff["teuer"].append((eur or 0.0, ein + aus, mid, link, len(s)))
        auff["teuer"] = sorted(auff["teuer"], reverse=True)[:5]

        for f in await Feedbacks.get_all_feedbacks():
            if (f.created_at or 0) < start:
                continue
            d, meta = f.data or {}, f.meta or {}
            r = str(d.get("rating"))
            if r in ("1", "1.0"):
                zaehler["hoch"] += 1
            elif r in ("-1", "-1.0"):
                zaehler["runter"] += 1
                if f.user_id == ich:
                    grund_text = " ".join(str(x) for x in (d.get("reason"), d.get("comment")) if x)
                    auff["runter"].append((d.get("model_id") or "?", v.chat_link + str(meta.get("chat_id") or ""),
                                           " ".join(grund_text.split())[:200] or "ohne Kommentar"))

        je_modell = {}
        for mid, z in sorted(woche["jetzt"].items(), key=lambda kv: -kv[1]["euro"]):
            n = max(1, z["antworten"])
            vz = woche["vorher"].get(mid)
            e = {
                "grundmodell": z["basis"], "antworten": z["antworten"],
                "schritte_schnitt": round(z["schritte"] / n, 1), "schritte_max": z["max_schritte"],
                "eingabe_tokens_schnitt": round(z["ein"] / n), "ausgabe_tokens_schnitt": round(z["aus"] / n),
                "cache_anteil": round(z["cache"] / z["ein"], 2) if z["ein"] else 0, "euro": round(z["euro"], 2),
                "euro_je_antwort": round(z["euro"] / max(1, z["antworten"] - z["ohne_preis"]), 4)
                if z["antworten"] > z["ohne_preis"] else None,
            }
            if vz and vz["antworten"] > vz["ohne_preis"]:
                e["euro_je_antwort_vorwoche"] = round(vz["euro"] / max(1, vz["antworten"] - vz["ohne_preis"]), 4)
            je_modell[mid] = e

        summe = sum(e["euro"] for e in je_modell.values())
        summe_v = sum(z["euro"] for z in woche["vorher"].values())
        n = sum(e["antworten"] for e in je_modell.values())
        n_v = sum(z["antworten"] for z in woche["vorher"].values())
        heute = date.today().isoformat()
        kennzahlen = {
            "datum": heute, "tage": tage, "antworten": n, "antworten_vorwoche": n_v,
            "euro": round(summe, 2), "euro_vorwoche": round(summe_v, 2),
            "euro_je_antwort": round(summe / n, 4) if n else 0,
            "euro_je_antwort_vorwoche": round(summe_v / n_v, 4) if n_v else None,
            "werkzeugprobleme": zaehler["werkzeugproblem"], "schrittgrenze": zaehler["grenze"],
            "fehler": zaehler["fehler"], "daumen_runter": zaehler["runter"], "daumen_hoch": zaehler["hoch"],
            "modelle": je_modell,
        }

        eur = lambda x: "–" if x is None else f"{x:.3f}"
        b = [f"# KI-Wochenanalyse ({date.today():%d.%m.%Y}, letzte {tage} Tage)", "",
             f"- Antworten: {n} (Vorwoche {n_v})",
             f"- Geschätzte Kosten: {summe:.2f} € (Vorwoche {summe_v:.2f} €), je Antwort {summe / max(1, n):.3f} € "
             f"(Vorwoche {summe_v / max(1, n_v):.3f} €). Listenpreise, ohne Modelle mit unbekanntem Preis.",
             f"- Auffällig: {zaehler['werkzeugproblem']} Antworten mit Werkzeugproblem, {zaehler['grenze']} an der "
             f"Schrittgrenze ({v.schritt_grenze}), {zaehler['fehler']} mit Fehler; Bewertungen {zaehler['hoch']} hoch, "
             f"{zaehler['runter']} runter.", "",
             "## Modelle", "",
             "| Modell | Grundmodell | Antworten | Ø Schritte | max | Ø Eingabe-Tok | Cache | € | € je Antwort | Vorwoche |",
             "|---|---|---|---|---|---|---|---|---|---|"]
        for mid, e in je_modell.items():
            b.append(f"| {mid} | {e['grundmodell']} | {e['antworten']} | {e['schritte_schnitt']} | {e['schritte_max']} | "
                     f"{e['eingabe_tokens_schnitt']} | {e['cache_anteil']:.0%} | {e['euro']:.2f} | {eur(e['euro_je_antwort'])} | "
                     f"{eur(e.get('euro_je_antwort_vorwoche'))} |")
        b += ["", "## Werkzeuge nach Mitschlepp", "",
              "Mitschlepp = Ergebnis x Zahl der folgenden Schritte derselben Antwort (so oft geht es erneut ans Modell).", "",
              "| Werkzeug | Aufrufe | Ø Ergebnis (Zeichen) | max | Mitschlepp (Mio. Tok) |", "|---|---|---|---|---|"]
        for name, w in sorted(wz.items(), key=lambda kv: -kv[1]["mitschlepp"])[:15]:
            b.append(f"| {name} | {w['aufrufe']} | {w['zeichen'] // max(1, w['aufrufe'])} | {w['max']} | "
                     f"{w['mitschlepp'] / 3.5 / 1e6:.2f} |")
        b += ["", "## Auffälligkeiten in eigenen Chats", ""]
        for titel, k in (("Werkzeugprobleme", "werkzeugproblem"), ("Schrittgrenze erreicht", "grenze"),
                         ("Fehler", "fehler"), ("Daumen runter", "runter")):
            b.append(f"### {titel}")
            b += [f"- {mid}: [Chat]({link}) {text}" for mid, link, text in auff[k][:20]] or ["- keine"]
            b.append("")
        b.append("### Teuerste Antworten")
        b += [f"- {mid}: {e:.3f} €, {tok} Tokens, {s} Schritte, [Chat]({link})" for e, tok, mid, link, s in auff["teuer"]] or ["- keine"]

        os.makedirs(os.path.join(v.ziel, "modelle"), exist_ok=True)
        pfad = os.path.join(v.ziel, f"woche_{heute}.md")
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(NL.join(b) + NL)
        for name in (f"woche_{heute}.json", "woche_latest.json"):
            with open(os.path.join(v.ziel, name), "w", encoding="utf-8") as f:
                json.dump(kennzahlen, f, ensure_ascii=False, indent=1)

        # Aktuelle Konfiguration der genutzten eigenen Modelle und der Harness-Regeln
        for mid in je_modell:
            m = modelle.get(mid)
            if not m:
                continue
            p, meta = m.params.model_dump(), m.meta.model_dump()
            kopf = {"id": mid, "name": m.name, "base_model_id": m.base_model_id,
                    "toolIds": meta.get("toolIds"), "skillIds": meta.get("skillIds"),
                    "subagents": (meta.get("subagents") or {}).get("model_ids"),
                    "capabilities": meta.get("capabilities"), "model_controls": p.get("model_controls")}
            with open(os.path.join(v.ziel, "modelle", re.sub(r"[^A-Za-z0-9._-]", "_", mid) + ".md"), "w", encoding="utf-8") as f:
                f.write(NL.join([f"# Modell {mid}", "", "```json", json.dumps(kopf, ensure_ascii=False, indent=1), "```", "",
                                 "## Systemprompt (params.system)", "", p.get("system") or "", ""]))
        h = await Functions.get_function_by_id("harness_filter")
        if h:
            with open(os.path.join(v.ziel, "modelle", "_harness_filter.py"), "w", encoding="utf-8") as f:
                f.write(h.content)

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"KI-Wochenanalyse: {n} Antworten ausgewertet", "done": True}})
        teuerste = ", ".join(f"{m} {e['euro']:.2f} €" for m, e in list(je_modell.items())[:3])
        return (f"Bericht: {pfad}. Konfiguration: {v.ziel}/modelle/. {n} Antworten, ca. {summe:.2f} € "
                f"({kennzahlen['euro_je_antwort']:.3f} € je Antwort, Vorwoche {eur(kennzahlen['euro_je_antwort_vorwoche'])}). "
                f"Teuerste Modelle: {teuerste}. Werkzeugprobleme {zaehler['werkzeugproblem']}, Schrittgrenze "
                f"{zaehler['grenze']}, Fehler {zaehler['fehler']}, Daumen runter {zaehler['runter']}.")
