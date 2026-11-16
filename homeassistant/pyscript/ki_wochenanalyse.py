"""Sensoren zur KI-Wochenanalyse (Pyscript für Home Assistant).

Die Auswertung selbst läuft in Open WebUI: das Werkzeug „KI-Wochenanalyse“ (openwebui/ki_wochenanalyse_tool.py)
liest dort die Datenbank und schreibt nur Kennzahlen und Bericht nach /share/ki_analyse/. Home Assistant
hat damit keinen Zugriff auf Chats und braucht keinen API-Schlüssel; es liest nur woche_latest.json.

Entitäten:
  sensor.ki_analyse_antworten_woche   Antworten im Zeitraum, Attribute je Modell
  sensor.ki_analyse_euro_je_antwort   geschätzte € je Antwort (Listenpreise), Vorwoche als Attribut
  sensor.ki_analyse_auffaelligkeiten  Werkzeugprobleme + Schrittgrenze + Fehler + Daumen runter

Aktualisierung: beim Start, montags 07:45 (nach der Automation in Open WebUI um 07:00) mit
Benachrichtigung, manuell über den Dienst pyscript.ki_wochenanalyse_lesen.
"""

QUELLE = "/share/ki_analyse/woche_latest.json"


@pyscript_compile
def _lesen():
    import json
    try:
        with open(QUELLE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@pyscript_compile
def _teuerste(modelle):
    return ", ".join(f"{m} {e.get('euro', 0):.2f} €" for m, e in list((modelle or {}).items())[:3])


async def _setzen(benachrichtigen):
    k = await task.executor(_lesen)
    if not k:
        log.warning(f"ki_wochenanalyse: {QUELLE} fehlt oder ist ungültig")
        return
    bericht = f"/share/ki_analyse/woche_{k.get('datum')}.md"
    state.set("sensor.ki_analyse_antworten_woche", k.get("antworten", 0), {
        "friendly_name": "KI Antworten (Woche)", "icon": "mdi:message-processing-outline",
        "unit_of_measurement": "Antworten", "state_class": "measurement",
        "datum": k.get("datum"), "tage": k.get("tage"), "vorwoche": k.get("antworten_vorwoche"),
        "modelle": k.get("modelle"), "bericht": bericht})
    state.set("sensor.ki_analyse_euro_je_antwort", k.get("euro_je_antwort", 0), {
        "friendly_name": "KI € je Antwort (Woche)", "icon": "mdi:cash-clock", "unit_of_measurement": "EUR",
        "state_class": "measurement", "datum": k.get("datum"), "vorwoche": k.get("euro_je_antwort_vorwoche"),
        "euro_gesamt": k.get("euro"), "euro_vorwoche": k.get("euro_vorwoche")})
    anzahl = sum([k.get("werkzeugprobleme", 0), k.get("schrittgrenze", 0), k.get("fehler", 0), k.get("daumen_runter", 0)])
    state.set("sensor.ki_analyse_auffaelligkeiten", anzahl, {
        "friendly_name": "KI Auffälligkeiten (Woche)", "icon": "mdi:alert-circle-outline",
        "unit_of_measurement": "Antworten", "state_class": "measurement", "datum": k.get("datum"),
        "werkzeugprobleme": k.get("werkzeugprobleme"), "schrittgrenze": k.get("schrittgrenze"),
        "fehler": k.get("fehler"), "daumen_runter": k.get("daumen_runter"), "daumen_hoch": k.get("daumen_hoch")})
    if benachrichtigen:
        vorher = k.get("euro_je_antwort_vorwoche")
        vorher = f" (Vorwoche {vorher:.3f} €)" if vorher is not None else ""
        await service.call("persistent_notification", "create", title="KI-Wochenanalyse",
                           notification_id="ki_wochenanalyse",
                           message=(f"{k.get('antworten', 0)} Antworten, ca. {k.get('euro', 0):.2f} €, "
                                    f"{k.get('euro_je_antwort', 0):.3f} € je Antwort{vorher}. "
                                    f"Teuerste Modelle: {_teuerste(k.get('modelle'))}. "
                                    f"Werkzeugprobleme {k.get('werkzeugprobleme', 0)}, Schrittgrenze {k.get('schrittgrenze', 0)}, "
                                    f"Fehler {k.get('fehler', 0)}, Daumen runter {k.get('daumen_runter', 0)}. "
                                    f"Bericht: {bericht}, Vorschläge im Chat der Automation."))


@time_trigger("startup")
async def ki_wochenanalyse_start():
    await _setzen(False)


@time_trigger("cron(45 7 * * 1)")
async def ki_wochenanalyse_zeitplan():
    await _setzen(True)


@service
async def ki_wochenanalyse_lesen():
    """yaml
name: KI-Wochenanalyse lesen
description: Liest /share/ki_analyse/woche_latest.json (vom Werkzeug KI-Wochenanalyse in Open WebUI) in die Sensoren und benachrichtigt.
"""
    await _setzen(True)
