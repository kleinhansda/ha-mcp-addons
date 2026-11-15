"""KI-Verbrauch und -Kosten des laufenden Monats (Pyscript für Home Assistant).

Quellen:
  Open WebUI   GET /api/v1/analytics/tokens (Admin-Analytics): Tokens je Modell seit Monatsanfang.
               Eigene Modelle (z. B. "zora") werden über base_model_id auf das Grundmodell und damit
               auf den Anbieter zurückgeführt. Kosten für Mistral = Tokens x PREISE (Richtwert).
  Scaleway     GET /billing/v2beta1/consumptions: tatsächliche Kosten und Mengen laut Abrechnung
               (nur wenn scaleway_billing_key in secrets.yaml steht; Schlüssel mit BillingReadOnly).

Schlüssel in secrets.yaml (werden nur gelesen, nie ausgegeben):
  owui_auth: "Bearer sk-..."            API-Schlüssel eines Admin-Kontos von Open WebUI
  scaleway_billing_key: "<secret key>"  optional
  scaleway_org_id: "<organisations-id>" optional

Entitäten (Attribute je Modell bzw. Produkt):
  sensor.ki_tokens_mistral_monat, sensor.ki_tokens_scaleway_monat, sensor.ki_tokens_monat
  sensor.ki_kosten_mistral_monat (geschätzt), sensor.ki_kosten_scaleway_monat (Abrechnung)

Installation: nach /config/pyscript/ki_verbrauch.py kopieren. Manuell: pyscript.ki_verbrauch_run.
"""

OWUI = "http://be60cb4b-open-webui:8080"
SCW = "https://api.scaleway.com/billing/v2beta1/consumptions"
MISTRAL_PRAEFIX = "mstrl."          # Präfix der Mistral-Verbindung in Open WebUI
# Euro je 1 Mio. Tokens (Eingabe, Ausgabe), Richtwerte; aktuelle Preise: https://mistral.ai/pricing
# Schlüssel = Teil der Modell-ID ohne Präfix, der längste passende gewinnt.
PREISE = {
    "mistral-large": (0.5, 1.5),
    "mistral-medium": (0.4, 2.0),
    "mistral-small": (0.1, 0.3),
    "magistral-medium": (2.0, 5.0),
    "magistral-small": (0.5, 1.5),
    "codestral": (0.3, 0.9),
    "devstral": (0.4, 2.0),
    "ministral": (0.1, 0.1),
    "pixtral": (2.0, 6.0),
}
PREIS_UNBEKANNT = (2.0, 6.0)        # vorsichtig hoch, damit nichts unterschätzt wird


@pyscript_compile
def _secret(name, pflicht=True):
    import re
    with open("/config/secrets.yaml", encoding="utf-8") as f:
        m = re.search(r'^\s*' + re.escape(name) + r':\s*["\']?([^"\'\n]+)', f.read(), re.MULTILINE)
    if not m:
        if pflicht:
            raise ValueError(f"{name} nicht in secrets.yaml gefunden")
        return None
    return m.group(1).strip()


@pyscript_compile
def _get(url, headers):
    import json, urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


@pyscript_compile
def _monatsanfang():
    import datetime as dt
    jetzt = dt.datetime.now().astimezone()
    return int(jetzt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()), jetzt.strftime("%Y-%m")


@pyscript_compile
def _owui(auth, start):
    """Tokens je Modell seit start, aufgeteilt auf Anbieter."""
    h = {"Authorization": auth if auth.lower().startswith("bearer ") else "Bearer " + auth}
    tokens = _get(f"{OWUI}/api/v1/analytics/tokens?start_date={start}", h)
    modelle = {m["id"]: m for m in _get(f"{OWUI}/api/models", h).get("data", [])}

    def grundmodell(mid):
        gesehen = set()
        while mid in modelle and mid not in gesehen:
            gesehen.add(mid)
            basis = ((modelle[mid].get("info") or {}).get("base_model_id"))
            if not basis:
                break
            mid = basis
        return mid

    def preis(mid):
        name = mid[len(MISTRAL_PRAEFIX):] if mid.startswith(MISTRAL_PRAEFIX) else mid
        treffer = [k for k in PREISE if k in name]
        return PREISE[max(treffer, key=len)] if treffer else PREIS_UNBEKANNT

    def anbieter_von(basis):
        if basis.startswith(MISTRAL_PRAEFIX):
            return "mistral"
        m = modelle.get(basis) or {}
        # Funktionen (Pipes) und Ollama/Arena sind keine Scaleway-Modelle
        return "scaleway" if m.get("owned_by") == "openai" and not m.get("pipe") else "sonstige"

    out = {"mistral": {}, "scaleway": {}, "sonstige": {}}
    for e in tokens.get("models", []):
        basis = grundmodell(e["model_id"])
        anbieter = anbieter_von(basis)
        z = out[anbieter].setdefault(basis, {"eingabe": 0, "ausgabe": 0, "antworten": 0, "ueber": []})
        z["eingabe"] += e["input_tokens"]
        z["ausgabe"] += e["output_tokens"]
        z["antworten"] += e["message_count"]
        if e["model_id"] != basis:
            z["ueber"].append(e["model_id"])
    for basis, z in out["mistral"].items():
        pe, pa = preis(basis)
        z["euro"] = round(z["eingabe"] / 1e6 * pe + z["ausgabe"] / 1e6 * pa, 4)
        z["preis_je_mio"] = [pe, pa]
    return out


@pyscript_compile
def _scaleway(key, org, periode):
    seite, posten = 1, []
    while True:
        d = _get(f"{SCW}?organization_id={org}&billing_period={periode}&page_size=100&page={seite}",
                 {"X-Auth-Token": key})
        posten += d.get("consumptions", [])
        if len(posten) >= int(d.get("total_count") or 0) or not d.get("consumptions"):
            break
        seite += 1
    gesamt = 0.0
    produkte = []
    for c in posten:
        v = c.get("value") or {}
        euro = int(v.get("units") or 0) + int(v.get("nanos") or 0) / 1e9
        gesamt += euro
        produkte.append({"kategorie": c.get("category_name"), "produkt": c.get("product_name"),
                         "sku": c.get("sku"), "ressource": c.get("resource_name"),
                         "menge": c.get("billed_quantity"), "einheit": c.get("unit"), "euro": round(euro, 4)})
    produkte.sort(key=lambda p: -p["euro"])
    # Je Modell: ressource ist z. B. "GLM 5.3 - Input - FR-PAR" oder "Qwen3.8 27B - Input - Cached - fr-par";
    # billed_quantity zählt bei Tokens in Tausend.
    modelle = {}
    for p in produkte:
        teile = [x.strip() for x in (p["ressource"] or "").split(" - ")]
        if p["einheit"] != "token" or len(teile) < 3:
            continue
        art = "gecacht" if "Cached" in teile else ("ausgabe" if teile[1] == "Output" else "eingabe")
        z = modelle.setdefault(teile[0], {"eingabe": 0, "gecacht": 0, "ausgabe": 0, "euro": 0.0})
        z[art] += int(float(p["menge"] or 0) * 1000)
        z["euro"] = round(z["euro"] + p["euro"], 2)
    modelle = dict(sorted(modelle.items(), key=lambda kv: -kv[1]["euro"]))
    return round(gesamt, 2), produkte, d.get("updated_at"), modelle


@pyscript_compile
def _summen(gruppe):
    """Eingabe, Ausgabe und Euro einer Anbietergruppe (Pyscript kann keine Generatorausdrücke)."""
    return (sum(z["eingabe"] for z in gruppe.values()), sum(z["ausgabe"] for z in gruppe.values()),
            round(sum(z.get("euro", 0) for z in gruppe.values()), 2))


@time_trigger("startup", "cron(*/15 * * * *)")
@service
async def ki_verbrauch_run():
    """yaml
name: KI-Verbrauch aktualisieren
description: Liest Tokens aus Open WebUI und, falls eingerichtet, die Scaleway-Abrechnung des laufenden Monats.
"""
    start, periode = _monatsanfang()
    gemeinsam = {"zeitraum": periode, "state_class": "total", "icon": "mdi:counter"}

    try:
        auth = await task.executor(_secret, "owui_auth")
        daten = await task.executor(_owui, auth, start)
    except Exception as e:
        log.warning(f"ki_verbrauch: Open WebUI nicht abrufbar: {type(e).__name__}: {e}")
        daten = None
    if daten is not None:
        m, s = daten["mistral"], daten["scaleway"]
        me, ma, meuro = _summen(m)
        se, sa, _ = _summen(s)
        state.set("sensor.ki_tokens_mistral_monat", me + ma, friendly_name="Mistral Tokens (Monat)",
                  unit_of_measurement="Tokens", modelle=m, eingabe=me, ausgabe=ma, **gemeinsam)
        state.set("sensor.ki_tokens_scaleway_monat", se + sa, friendly_name="Scaleway Tokens (Monat, Open WebUI)",
                  unit_of_measurement="Tokens", modelle=s, eingabe=se, ausgabe=sa, **gemeinsam)
        oe, oa, _ = _summen(daten["sonstige"])
        state.set("sensor.ki_tokens_monat", me + ma + se + sa + oe + oa, friendly_name="KI Tokens (Monat)",
                  unit_of_measurement="Tokens", sonstige=daten["sonstige"], **gemeinsam)
        state.set("sensor.ki_kosten_mistral_monat", meuro,
                  friendly_name="Mistral Kosten (Monat, geschätzt)", unit_of_measurement="€",
                  device_class="monetary", state_class="total", zeitraum=periode, icon="mdi:currency-eur",
                  hinweis="Tokens aus Open WebUI x Listenpreis; Aufrufe außerhalb von Open WebUI fehlen")

    key = await task.executor(_secret, "scaleway_billing_key", False)
    org = await task.executor(_secret, "scaleway_org_id", False)
    if key and org:
        try:
            gesamt, produkte, stand, modelle = await task.executor(_scaleway, key, org, periode)
            state.set("sensor.ki_kosten_scaleway_monat", gesamt, friendly_name="Scaleway Kosten (Monat)",
                      unit_of_measurement="€", device_class="monetary", state_class="total",
                      zeitraum=periode, stand=stand, modelle=modelle, produkte=produkte[:30], icon="mdi:currency-eur",
                      hinweis="laut Scaleway-Abrechnung, ohne MwSt.")
        except Exception as e:
            log.warning(f"ki_verbrauch: Scaleway-Abrechnung nicht abrufbar: {type(e).__name__}: {e}")
