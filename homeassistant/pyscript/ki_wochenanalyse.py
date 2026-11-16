"""Wöchentliche Auswertung der Open-WebUI-Antworten (Pyscript für Home Assistant).

Grundlage für Verbesserungen an Modellen, Prompts und Werkzeugen: zählt und misst, liest keine
Inhalte. Ausnahmen, nur für Chats des eigenen Kontos (Besitzer des Schlüssels owui_auth): Zeilen
„Werkzeugproblem: …“ (Regel im Harness-Filter), Fehlermeldungen und Kommentare zu Bewertungen
erscheinen wörtlich, dazu Links auf die Chats. Chats anderer Nutzer gehen nur in die Zahlen ein.

Quellen (Admin-Analytics von Open WebUI):
  GET /api/v1/analytics/models, /api/v1/analytics/messages?model_id=…   Antworten mit usage und output
  GET /api/v1/evaluations/feedbacks/list                               Daumen hoch/runter
  GET /api/models, /api/v1/models/model, /api/v1/functions/export      Grundmodelle, Konfiguration
  Der API-Schlüssel braucht diese Pfade in den Endpunkt-Freigaben (Admin -> Einstellungen -> Allgemein).

Ergebnis:
  /share/ki_analyse/woche_<datum>.md, Benachrichtigung „KI-Wochenanalyse“
  /share/ki_analyse/modelle/<id>.md   Systemprompt und Einstellungen der genutzten Modelle,
                                      _harness_filter.py (Grundlage für Vorschläge, wöchentlich ersetzt)
  sensor.ki_analyse_antworten_woche   Antworten der letzten 7 Tage, Attribute je Modell
  sensor.ki_analyse_euro_je_antwort   geschätzte € je Antwort (Scaleway-Listenpreise)
  sensor.ki_analyse_auffaelligkeiten  Werkzeugprobleme + Schrittgrenze + Fehler + Daumen runter

Zeitplan: montags 06:30. Manuell: Dienst pyscript.ki_wochenanalyse (optional tage).
Schlüssel in secrets.yaml (nur gelesen, nie ausgegeben): owui_auth: "Bearer sk-..." (Admin-Konto)
"""

OWUI = "http://be60cb4b-open-webui:8080"
CHAT_LINK = "https://ai.ddsk.cloud/c/"
# Eigenes Konto (Besitzer von owui_auth). Der API-Schlüssel darf /api/v1/auths nicht abfragen
# (Endpunkt-Freigaben), deshalb fest eingetragen.
EIGENER_NUTZER = "0928ab8c-3c96-4e3c-a2ef-ba1859ed330e"
ZIEL = "/share/ki_analyse"
TAGE = 7
SCHRITT_GRENZE = 40          # CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS der Open-WebUI-App
ZEICHEN_JE_TOKEN = 3.5
MISTRAL_PRAEFIX = "mstrl."
# Euro je 1 Mio. Tokens (Eingabe, Eingabe aus dem Cache, Ausgabe); None = unbekannt.
# Schlüssel = Teil der Grundmodell-ID, der längste passende gewinnt. Werte aus der Scaleway-Abrechnung.
PREISE = {
    "glm-5.3": (1.80, None, 5.51),
    "glm-5.2": (1.82, None, None),
    "qwen3.8-27b": (0.60, 0.12, 3.30),
    "qwen3.6-35b": (0.25, None, 1.51),
    "qwen3.5-397b": (0.60, None, None),
    "mistral-medium": (1.50, None, None),
    "mistral-large": (0.5, None, 1.5),
}


@pyscript_compile
def _secret(name):
    import re
    with open("/config/secrets.yaml", encoding="utf-8") as f:
        m = re.search(r'^\s*' + re.escape(name) + r':\s*["\']?([^"\'\n]+)', f.read(), re.MULTILINE)
    if not m:
        raise ValueError(f"{name} nicht in secrets.yaml gefunden")
    v = m.group(1).strip()
    return v if v.lower().startswith("bearer ") else "Bearer " + v


@pyscript_compile
def _get(pfad, auth):
    import json, urllib.request
    req = urllib.request.Request(OWUI + pfad, headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


@pyscript_compile
def _preis(basis):
    name = basis[len(MISTRAL_PRAEFIX):] if basis.startswith(MISTRAL_PRAEFIX) else basis
    treffer = [k for k in PREISE if k in name]
    return PREISE[max(treffer, key=len)] if treffer else None


@pyscript_compile
def _euro(basis, ein, cache, aus):
    """Geschätzte Kosten einer Antwort; None, wenn ein nötiger Preis fehlt."""
    p = _preis(basis)
    if not p or p[0] is None or (aus and p[2] is None):
        return None
    pc = p[1] if p[1] is not None else p[0]
    return ((ein - cache) * p[0] + cache * pc + aus * (p[2] or 0)) / 1e6


@pyscript_compile
def _laenge(x):
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


@pyscript_compile
def _texte(msg):
    """Sichtbarer Antworttext (für die Suche nach „Werkzeugproblem:“)."""
    teile = []
    c = msg.get("content")
    if isinstance(c, str):
        teile.append(c)
    elif isinstance(c, list):
        teile += [str(t.get("text") or "") for t in c if isinstance(t, dict)]
    for it in msg.get("output") or []:
        if isinstance(it, dict) and it.get("type") == "message":
            for t in it.get("content") or []:
                if isinstance(t, dict):
                    teile.append(str(t.get("text") or ""))
    return "\n".join(teile)


@pyscript_compile
def _antwort(msg):
    """Kennzahlen einer Antwort: Tokens, Schritte, Werkzeuge mit Ergebnisgröße und Mitschlepp."""
    u = msg.get("usage") or {}
    ein = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
    aus = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
    det = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    cache = int((det.get("cached_tokens") if isinstance(det, dict) else 0) or 0)
    namen, schritte = {}, []
    for it in msg.get("output") or []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == "function_call":
            namen[it.get("call_id")] = (it.get("name") or "?", len(str(it.get("arguments") or "")))
        elif it.get("type") == "function_call_output":
            name, arg = namen.get(it.get("call_id"), ("?", 0))
            schritte.append((name, arg, _laenge(it.get("output"))))
    return ein, aus, min(cache, ein), schritte


@pyscript_compile
def _abrufen(auth, start, ende):
    """Alle Antworten im Zeitraum, je Modell seitenweise."""
    modelle = [e["model_id"] for e in (_get(f"/api/v1/analytics/models?start_date={start}&end_date={ende}", auth)
                                       or {}).get("models", []) if e.get("model_id")]
    msgs = []
    for mid in modelle:
        skip = 0
        while True:
            from urllib.parse import quote
            seite = _get(f"/api/v1/analytics/messages?model_id={quote(mid, safe='')}&start_date={start}"
                         f"&end_date={ende}&skip={skip}&limit=100", auth) or []
            msgs += [m for m in seite if m.get("role") == "assistant"]
            if len(seite) < 100:
                break
            skip += 100
    return msgs


@pyscript_compile
def _bewertungen(auth, start):
    out, seite = [], 1
    while True:
        d = _get(f"/api/v1/evaluations/feedbacks/list?page={seite}", auth) or {}
        items = d.get("items") or []
        out += [f for f in items if (f.get("created_at") or 0) >= start]
        if not items or (items[-1].get("created_at") or 0) < start or seite * len(items) >= (d.get("total") or 0):
            break
        seite += 1
    return out


@pyscript_compile
def _auswerten(msgs, grund, ich, start_jetzt):
    """Kennzahlen je Modell für die aktuelle Woche (created_at >= start_jetzt) und die Vorwoche."""
    import re
    WP = re.compile(r"Werkzeugproblem:[^\n]{0,300}")
    woche = {"jetzt": {}, "vorher": {}}
    wz = {}
    auff = {"werkzeugproblem": [], "grenze": [], "fehler": [], "teuer": []}
    zaehler = {"werkzeugproblem": 0, "grenze": 0, "fehler": 0}
    for m in msgs:
        jetzt = (m.get("created_at") or 0) >= start_jetzt
        mid = m.get("model_id") or "?"
        basis = grund(mid)
        ein, aus, cache, s = _antwort(m)
        eur = _euro(basis, ein, cache, aus)
        z = woche["jetzt" if jetzt else "vorher"].setdefault(mid, {
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
        if not jetzt:
            continue
        for i, (name, arg, n) in enumerate(s):
            w = wz.setdefault(name, {"aufrufe": 0, "zeichen": 0, "max": 0, "mitschlepp": 0})
            w["aufrufe"] += 1
            w["zeichen"] += n
            w["max"] = max(w["max"], n)
            w["mitschlepp"] += (n + arg) * (len(s) - i - 1)
        eigen = m.get("user_id") == ich
        link = CHAT_LINK + str(m.get("chat_id") or "")
        probleme = WP.findall(_texte(m))
        if probleme:
            zaehler["werkzeugproblem"] += 1
            if eigen:
                auff["werkzeugproblem"].append((mid, link, probleme[0]))
        if len(s) >= SCHRITT_GRENZE:
            zaehler["grenze"] += 1
            if eigen:
                auff["grenze"].append((mid, link, f"{len(s)} Schritte"))
        fehler = m.get("error")
        if fehler and fehler not in ({}, "", False):
            zaehler["fehler"] += 1
            if eigen:
                text = fehler.get("content") or fehler.get("message") or str(fehler) if isinstance(fehler, dict) else str(fehler)
                auff["fehler"].append((mid, link, " ".join(str(text).split())[:200]))
        if eigen:
            auff["teuer"].append((eur or 0.0, ein + aus, mid, link, len(s)))
    auff["teuer"] = sorted(auff["teuer"], reverse=True)[:5]
    return woche, wz, auff, zaehler


@pyscript_compile
def _analyse(auth, tage):
    import time
    jetzt = int(time.time())
    start_jetzt = jetzt - tage * 86400
    start_vorher = start_jetzt - tage * 86400
    ich = EIGENER_NUTZER
    modelle = {m["id"]: m for m in (_get("/api/models", auth) or {}).get("data", [])}

    def grund(mid):
        gesehen = set()
        while mid in modelle and mid not in gesehen:
            gesehen.add(mid)
            b = (modelle[mid].get("info") or {}).get("base_model_id")
            if not b:
                break
            mid = b
        return mid

    msgs = _abrufen(auth, start_vorher, jetzt)
    woche, wz, auff, zaehler = _auswerten(msgs, grund, ich, start_jetzt)
    try:
        fb = _bewertungen(auth, start_jetzt)
        bewertungen_ok = True
    except Exception:            # Endpunkt für den Schlüssel nicht freigegeben
        fb, bewertungen_ok = [], False
    runter = [f for f in fb if str((f.get("data") or {}).get("rating")) in ("-1", "-1.0")]
    hoch = [f for f in fb if str((f.get("data") or {}).get("rating")) in ("1", "1.0")]
    auff["runter"] = []
    for f in runter:
        if f.get("user_id") == ich:
            d, meta = f.get("data") or {}, f.get("meta") or {}
            grund_text = " ".join(str(x) for x in (d.get("reason"), d.get("comment")) if x)
            auff["runter"].append((d.get("model_id") or "?", CHAT_LINK + str(meta.get("chat_id") or ""),
                                   " ".join(grund_text.split())[:200] or "ohne Kommentar"))
    zaehler["runter"] = len(runter)
    zaehler["hoch"] = len(hoch)
    zaehler["bewertungen_ok"] = bewertungen_ok
    return woche, wz, auff, zaehler


@pyscript_compile
def _je_modell(woche):
    """Attribute je Modell der aktuellen Woche mit Vergleich zur Vorwoche."""
    out = {}
    for mid, z in sorted(woche["jetzt"].items(), key=lambda kv: -kv[1]["euro"]):
        n = max(1, z["antworten"])
        bepreist = max(1, z["antworten"] - z["ohne_preis"])
        v = woche["vorher"].get(mid)
        e = {
            "grundmodell": z["basis"],
            "antworten": z["antworten"],
            "schritte_schnitt": round(z["schritte"] / n, 1),
            "schritte_max": z["max_schritte"],
            "eingabe_tokens_schnitt": round(z["ein"] / n),
            "ausgabe_tokens_schnitt": round(z["aus"] / n),
            "cache_anteil": round(z["cache"] / z["ein"], 2) if z["ein"] else 0,
            "euro": round(z["euro"], 2),
            "euro_je_antwort": round(z["euro"] / bepreist, 4) if z["antworten"] > z["ohne_preis"] else None,
        }
        if v and v["antworten"] > v["ohne_preis"]:
            e["euro_je_antwort_vorwoche"] = round(v["euro"] / max(1, v["antworten"] - v["ohne_preis"]), 4)
        out[mid] = e
    return out


@pyscript_compile
def _konfig_export(auth, modell_ids):
    """Aktuelle Konfiguration der genutzten eigenen Modelle und den Harness-Prompt nach ZIEL/modelle/
    schreiben, damit ein Modell Änderungen mit exakt passendem Text vorschlagen kann."""
    import json, os, re
    from urllib.parse import quote
    ordner = os.path.join(ZIEL, "modelle")
    os.makedirs(ordner, exist_ok=True)
    geschrieben = []
    for mid in modell_ids:
        try:
            m = _get("/api/v1/models/model?id=" + quote(mid, safe=""), auth) or {}
        except Exception:
            continue                      # Grundmodell ohne eigene Einstellungen
        p, meta = m.get("params") or {}, m.get("meta") or {}
        kopf = {"id": mid, "name": m.get("name"), "base_model_id": m.get("base_model_id"),
                "toolIds": meta.get("toolIds"), "skillIds": meta.get("skillIds"),
                "subagents": (meta.get("subagents") or {}).get("model_ids"),
                "capabilities": meta.get("capabilities"), "model_controls": p.get("model_controls")}
        name = re.sub(r"[^A-Za-z0-9._-]", "_", mid)
        with open(os.path.join(ordner, name + ".md"), "w", encoding="utf-8") as f:
            f.write("# Modell " + mid + "\n\n```json\n" + json.dumps(kopf, ensure_ascii=False, indent=1)
                    + "\n```\n\n## Systemprompt (params.system)\n\n" + (p.get("system") or "") + "\n")
        geschrieben.append(mid)
    try:
        h = [f for f in _get("/api/v1/functions/export", auth) if f.get("id") == "harness_filter"]
        if h:
            with open(os.path.join(ordner, "_harness_filter.py"), "w", encoding="utf-8") as f:
                f.write(h[0].get("content") or "")
            geschrieben.append("harness_filter")
    except Exception:
        pass
    return geschrieben


@pyscript_compile
def _teuerste(je_modell):
    return ", ".join(f"{m} {e['euro']:.2f} €" for m, e in list(je_modell.items())[:3])


@pyscript_compile
def _bericht(tage, je_modell, wz, auff, zaehler, woche):
    import datetime as dt, os
    t = lambda zeichen: f"{zeichen / ZEICHEN_JE_TOKEN / 1e6:.2f}"
    eur = lambda x: "–" if x is None else f"{x:.3f}"
    summe = sum(e["euro"] for e in je_modell.values())
    summe_v = sum(z["euro"] for z in woche["vorher"].values())
    n = sum(e["antworten"] for e in je_modell.values())
    n_v = sum(z["antworten"] for z in woche["vorher"].values())
    z = [f"# KI-Wochenanalyse ({dt.date.today():%d.%m.%Y}, letzte {tage} Tage)", "",
         f"- Antworten: {n} (Vorwoche {n_v})",
         f"- Geschätzte Kosten: {summe:.2f} € (Vorwoche {summe_v:.2f} €), je Antwort "
         f"{summe / max(1, n):.3f} € (Vorwoche {summe_v / max(1, n_v):.3f} €). Listenpreise, ohne Modelle mit unbekanntem Preis.",
         f"- Auffällig: {zaehler['werkzeugproblem']} Antworten mit Werkzeugproblem, {zaehler['grenze']} an der "
         f"Schrittgrenze ({SCHRITT_GRENZE}), {zaehler['fehler']} mit Fehler; Bewertungen {zaehler['hoch']} hoch, "
         f"{zaehler['runter']} runter" + ("." if zaehler["bewertungen_ok"] else
         " (Bewertungen nicht lesbar: /api/v1/evaluations für den API-Schlüssel freigeben)."), "",
         "## Modelle", "",
         "| Modell | Grundmodell | Antworten | Ø Schritte | max | Ø Eingabe-Tok | Cache | € | € je Antwort | Vorwoche |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for mid, e in je_modell.items():
        z.append(f"| {mid} | {e['grundmodell']} | {e['antworten']} | {e['schritte_schnitt']} | {e['schritte_max']} | "
                 f"{e['eingabe_tokens_schnitt']} | {e['cache_anteil']:.0%} | {e['euro']:.2f} | {eur(e['euro_je_antwort'])} | "
                 f"{eur(e.get('euro_je_antwort_vorwoche'))} |")
    z += ["", "## Werkzeuge nach Mitschlepp", "",
          "Mitschlepp = Ergebnis x Zahl der folgenden Schritte derselben Antwort (so oft geht es erneut ans Modell).", "",
          "| Werkzeug | Aufrufe | Ø Ergebnis (Zeichen) | max | Mitschlepp (Mio. Tok) |", "|---|---|---|---|---|"]
    for name, w in sorted(wz.items(), key=lambda kv: -kv[1]["mitschlepp"])[:15]:
        z.append(f"| {name} | {w['aufrufe']} | {w['zeichen'] // max(1, w['aufrufe'])} | {w['max']} | {t(w['mitschlepp'])} |")
    z += ["", "## Auffälligkeiten in eigenen Chats", ""]
    abschnitte = [("Werkzeugprobleme", "werkzeugproblem"), (f"Schrittgrenze erreicht", "grenze"),
                  ("Fehler", "fehler"), ("Daumen runter", "runter")]
    for titel, k in abschnitte:
        z.append(f"### {titel}")
        z += [f"- {mid}: [Chat]({link}) {text}" for mid, link, text in auff[k][:20]] or ["- keine"]
        z.append("")
    z.append("### Teuerste Antworten")
    z += [f"- {mid}: {e:.3f} €, {tok} Tokens, {s} Schritte, [Chat]({link})" for e, tok, mid, link, s in auff["teuer"]] or ["- keine"]
    z += ["", "## Nächster Schritt", "",
          "Für Verbesserungsvorschläge diesen Bericht einem Modell (z. B. Zora) geben: konkrete Änderungen an "
          "Prompts, Skills, Werkzeugen oder Ventilen als Diff und als owui_patch.json mit \"dry_run\": true. "
          "Gespeichert wird erst nach Freigabe."]
    os.makedirs(ZIEL, exist_ok=True)
    pfad = os.path.join(ZIEL, f"woche_{dt.date.today():%Y-%m-%d}.md")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(z) + "\n")
    return pfad, summe, n, summe_v / max(1, n_v) if n_v else None


async def _lauf(tage):
    tage = int(tage or TAGE)
    auth = await task.executor(_secret, "owui_auth")
    woche, wz, auff, zaehler = await task.executor(_analyse, auth, tage)
    je_modell = _je_modell(woche)
    pfad, summe, n, je_vorher = await task.executor(_bericht, tage, je_modell, wz, auff, zaehler, woche)
    await task.executor(_konfig_export, auth, list(je_modell.keys()))
    je = round(summe / n, 4) if n else 0
    anzahl_auff = zaehler["werkzeugproblem"] + zaehler["grenze"] + zaehler["fehler"] + zaehler["runter"]
    state.set("sensor.ki_analyse_antworten_woche", n, {
        "friendly_name": "KI Antworten (7 Tage)", "icon": "mdi:message-processing-outline",
        "unit_of_measurement": "Antworten", "state_class": "measurement",
        "modelle": je_modell, "bericht": pfad, "tage": tage})
    state.set("sensor.ki_analyse_euro_je_antwort", je, {
        "friendly_name": "KI € je Antwort (7 Tage)", "icon": "mdi:cash-clock", "unit_of_measurement": "EUR",
        "state_class": "measurement", "vorwoche": round(je_vorher, 4) if je_vorher is not None else None,
        "euro_gesamt": round(summe, 2)})
    state.set("sensor.ki_analyse_auffaelligkeiten", anzahl_auff, {
        "friendly_name": "KI Auffälligkeiten (7 Tage)", "icon": "mdi:alert-circle-outline",
        "unit_of_measurement": "Antworten", "state_class": "measurement",
        "werkzeugprobleme": zaehler["werkzeugproblem"], "schrittgrenze": zaehler["grenze"],
        "fehler": zaehler["fehler"], "daumen_runter": zaehler["runter"], "daumen_hoch": zaehler["hoch"]})
    teuerste = _teuerste(je_modell)
    vorher = f" (Vorwoche {je_vorher:.3f} €)" if je_vorher is not None else ""
    await service.call("persistent_notification", "create", title="KI-Wochenanalyse",
                       notification_id="ki_wochenanalyse",
                       message=(f"{n} Antworten, ca. {summe:.2f} €, {je:.3f} € je Antwort{vorher}.\n"
                                f"Teuerste Modelle: {teuerste}\n"
                                f"Werkzeugprobleme {zaehler['werkzeugproblem']}, Schrittgrenze {zaehler['grenze']}, "
                                f"Fehler {zaehler['fehler']}, Daumen runter {zaehler['runter']}.\n"
                                f"Bericht: {pfad}"))
    log.info(f"ki_wochenanalyse: {n} Antworten, {summe:.2f} EUR -> {pfad}")


@time_trigger("cron(30 6 * * 1)")
async def ki_wochenanalyse_zeitplan():
    await _lauf(TAGE)


@service
async def ki_wochenanalyse(tage=None):
    """yaml
name: KI-Wochenanalyse
description: Wertet die Open-WebUI-Antworten der letzten Tage aus (Kosten, Schritte, Werkzeuge, Auffälligkeiten) und schreibt einen Bericht nach /share/ki_analyse/.
fields:
  tage:
    name: Tage
    description: Zeitraum in Tagen (Standard 7, die Vorwoche gleich lang)
    selector:
      number:
        min: 1
        max: 45
"""
    await _lauf(tage)
