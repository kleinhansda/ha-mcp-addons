#!/usr/bin/env python3
"""Erzeugt Optionen, Schema und Übersetzungen der Apps aus einem gemeinsamen Gerüst.

Quelle: common/options/blocks.yaml (gemeinsame Felder und Abschnitte) und je App
<app>/options.yaml (eigene Felder, Reihenfolge, Abschnitte, Platzhalter). Geschrieben wird
<app>/config.yaml ab der Zeile "options:" (alles davor bleibt unverändert, auch die Version)
und <app>/translations/{de,en}.yaml unter "configuration:" (andere Schlüssel wie "network"
bleiben erhalten).

  python3 .github/scripts/build_options.py          erzeugen
  python3 .github/scripts/build_options.py --check  nur prüfen (Build), Fehler bei Abweichung

Format von <app>/options.yaml:

  vars: {internal_port: 9080, ...}          Werte für {Platzhalter} in Texten
  entries:                                  Reihenfolge in der Oberfläche
    - key: internal_access                  Standardfeld aus blocks.yaml
      de: {description: ...}                optional: Text/Schema/Standard überschreiben
    - key: netlify_token                    eigenes Feld
      default: null
      schema: password
      de: {name: ..., description: ...}
      en: {name: ..., description: ...}
    - section: public                       aufklappbarer Abschnitt
      fields: [external_url, ...]           optional, Standard aus blocks.yaml; Einträge wie oben
      legacy: true                          Felder bleiben zusätzlich auf oberster Ebene gültig
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BLOCKS = yaml.safe_load((ROOT / "common/options/blocks.yaml").read_text(encoding="utf-8"))
LANGS = ("de", "en")


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper, s):
    # Lange Texte als Block, sonst Standard (Anführungszeichen nur wo nötig)
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=">" if len(s) > 100 and " " in s and "\n" not in s else None)


Dumper.add_representer(str, _str)
Dumper.ignore_aliases = lambda self, data: True


def dump(data) -> str:
    return yaml.dump(data, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=100, default_flow_style=False)


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out.get(k, {}), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def feld(eintrag, app: str) -> dict:
    if isinstance(eintrag, str):
        eintrag = {"key": eintrag}
    key = eintrag["key"]
    basis = BLOCKS["fields"].get(key, {})
    f = merge(basis, {k: v for k, v in eintrag.items() if k != "key"})
    if "schema" not in f:
        sys.exit(f"{app}: Feld '{key}' ohne Schema (weder in options.yaml noch in blocks.yaml)")
    f["key"] = key
    return f


def text(t: dict | None, vars_: dict, app: str, key: str) -> dict | None:
    if not t:
        return None
    try:
        return {k: (v.format_map(vars_).strip() if isinstance(v, str) else v) for k, v in t.items() if v not in (None, "")}
    except KeyError as e:
        sys.exit(f"{app}: Platzhalter {e} in Text von '{key}' fehlt in vars")


def optional_schema(s):
    if isinstance(s, list):
        return [optional_schema(x) for x in s]
    return s if str(s).endswith("?") else f"{s}?"


def bauen(app_dir: Path) -> tuple[dict, dict, dict]:
    app = app_dir.name
    src = yaml.safe_load((app_dir / "options.yaml").read_text(encoding="utf-8"))
    vars_ = src.get("vars", {})
    options, schema = {}, {}
    trans = {l: {} for l in LANGS}
    legacy_felder = []
    for e in src["entries"]:
        if "section" in e:
            name = e["section"]
            sdef = merge(BLOCKS["sections"].get(name, {}), {k: v for k, v in e.items() if k not in ("section", "fields", "legacy")})
            felder = [feld(x, app) for x in e.get("fields", sdef.get("fields", []))]
            options[name] = {f["key"]: f.get("default") for f in felder if "default" in f}
            schema[name] = {f["key"]: f["schema"] for f in felder}
            for l in LANGS:
                kopf = text(sdef.get(l), vars_, app, name) or {}
                kopf["fields"] = {f["key"]: text(f.get(l), vars_, app, f["key"]) or {} for f in felder}
                trans[l][name] = kopf
            if e.get("legacy"):
                legacy_felder += [(f, {l: (sdef.get(l) or {}).get("name", name) for l in LANGS}) for f in felder]
        else:
            f = feld(e, app)
            if "default" in f:
                options[f["key"]] = f["default"]
            schema[f["key"]] = f["schema"]
            for l in LANGS:
                t = text(f.get(l), vars_, app, f["key"])
                if t:
                    trans[l][f["key"]] = t
    for f, sec_namen in legacy_felder:
        if f["key"] in schema:
            continue
        schema[f["key"]] = optional_schema(f["schema"])
        for l in LANGS:
            lt = BLOCKS["legacy"][l]
            name = (text(f.get(l), vars_, app, f["key"]) or {}).get("name", f["key"])
            trans[l][f["key"]] = {"name": lt["prefix"] + name, "description": lt["description"].format(section=sec_namen[l])}
    for k in src.get("extra_schema", {}):
        schema[k] = src["extra_schema"][k]["schema"]
        for l in LANGS:
            t = text(src["extra_schema"][k].get(l), vars_, app, k)
            if t:
                trans[l][k] = t
    return options, schema, trans


def config_text(path: Path, options: dict, schema: dict) -> str:
    alt = path.read_text(encoding="utf-8")
    m = re.search(r"^options:", alt, re.M)
    kopf = alt[: m.start()] if m else alt.rstrip("\n") + "\n"
    hinweis = "# options und schema: erzeugt von .github/scripts/build_options.py aus options.yaml, nicht von Hand ändern\n"
    if hinweis not in kopf:
        kopf += hinweis
    return kopf + dump({"options": options, "schema": schema})


def trans_text(path: Path, conf: dict) -> str:
    alt = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    neu = {"configuration": conf}
    for k, v in (alt or {}).items():
        if k != "configuration":
            neu[k] = v
    return dump(neu)


def main() -> int:
    check = "--check" in sys.argv
    bad = []
    apps = sorted(p.parent for p in ROOT.glob("*/options.yaml"))
    for app_dir in apps:
        options, schema, trans = bauen(app_dir)
        ziele = {app_dir / "config.yaml": config_text(app_dir / "config.yaml", options, schema)}
        for l in LANGS:
            p = app_dir / "translations" / f"{l}.yaml"
            ziele[p] = trans_text(p, trans[l])
        for p, inhalt in ziele.items():
            if p.exists() and p.read_text(encoding="utf-8") == inhalt:
                continue
            if check:
                bad.append(str(p.relative_to(ROOT)))
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(inhalt, encoding="utf-8")
                print(f"geschrieben: {p.relative_to(ROOT)}")
    if bad:
        print("Nicht aus options.yaml erzeugt (build_options.py ausführen):\n  " + "\n  ".join(bad))
        return 1
    print(f"Optionen aus dem Gerüst: {', '.join(a.name for a in apps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
