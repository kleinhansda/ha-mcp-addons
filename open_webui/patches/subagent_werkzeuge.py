"""Beim Bau: Sub-Agenten mit eigenem Modell bekommen dessen Werkzeuge und Skills.

Open WebUI gibt einem Sub-Agenten (delegate_task mit model_id) die Werkzeuge und Skills des
aufrufenden Modells mit, nicht die des Sub-Agenten-Modells. Ein HA-Modell als Sub-Agent eines
Assistenten hätte so keine HA-Werkzeuge. Dieser Patch setzt bei einem anderen Modell dessen
toolIds und skillIds aus den Modell-Einstellungen ein (wie Open WebUI es bei Automationen tut).
Passt die Stelle nach einem Update nicht mehr, bricht der Bau ab.
"""
import sys

DATEI = sys.argv[1] if len(sys.argv) > 1 else "/app/backend/open_webui/utils/subagents.py"
ANKER = "    model_id = model_id or run['model_id']\n"
MARKE = "# [ha-addons] Sub-Agent-Werkzeuge"
EINSATZ = ANKER + f"""    {MARKE}: anderes Modell -> dessen eigene Werkzeuge und Skills statt der des Aufrufers
    if model_id != run['model_id']:
        _sub_info = (getattr(request.app.state, 'MODELS', {{}}) or {{}}).get(model_id) or {{}}
        _sub_meta = (_sub_info.get('info') or {{}}).get('meta') or {{}}
        if 'toolIds' in _sub_meta:
            run['tool_ids'] = list(_sub_meta.get('toolIds') or [])
        if 'skillIds' in _sub_meta:
            run['skill_ids'] = list(_sub_meta.get('skillIds') or [])
"""

text = open(DATEI, encoding="utf-8").read()
if MARKE in text:
    print("subagent_werkzeuge: schon gepatcht")
    sys.exit(0)
if text.count(ANKER) != 1:
    sys.exit(f"subagent_werkzeuge: Stelle {ANKER.strip()!r} {text.count(ANKER)}x gefunden statt 1x – Patch an neue Open-WebUI-Version anpassen")
text = text.replace(ANKER, EINSATZ)
compile(text, DATEI, "exec")
open(DATEI, "w", encoding="utf-8").write(text)
print("subagent_werkzeuge: eingesetzt")
