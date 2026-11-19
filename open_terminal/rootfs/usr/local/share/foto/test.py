#!/usr/bin/env python3
"""Selbsttest für den Befehl foto (läuft beim Bau des Images und in der CI).

  test.py [arbeitsordner]

Wie der Selbsttest von Foto MCP, aber über die Kommandozeile: Schräglage (Gitter: Senkrechte, Meer:
Horizont), Gesichts-, Objekt- und Szenenmodell, Sichtung mit Kontaktbogen, Vorschau, optimieren mit
Ergebnis, Protokoll und Vorschau, Rezept (nicht überschreiben), anpassen, falscher Regler, aussortieren.
Rückgabewert 0 = alles in Ordnung.
"""
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

FOTO = os.environ.get("FOTO_CLI", "/usr/local/bin/foto")
root = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="foto-test-")
os.environ["FOTO_REZEPTE"] = os.path.join(root, "rezepte")
os.makedirs(os.path.join(root, "test"), exist_ok=True)
os.makedirs(os.path.join(root, "meer"), exist_ok=True)

# Gitter, um +2° gekippt -> Messung etwa -2° (Senkrechte)
img = np.full((1600, 2400, 3), 200, np.uint8)
for x in range(200, 2400, 200):
    cv2.line(img, (x, 100), (x, 1500), (40, 40, 40), 6)
for y in range(200, 1600, 300):
    cv2.line(img, (100, y), (2300, y), (60, 60, 60), 4)
M = cv2.getRotationMatrix2D((1200, 800), 2.0, 1.0)
img = cv2.warpAffine(img, M, (2400, 1600), borderValue=(200, 200, 200))
gitter = os.path.join(root, "test", "gitter.jpg")
cv2.imwrite(gitter, img, [cv2.IMWRITE_JPEG_QUALITY, 92])

# Meer mit Horizont, um +2° gekippt -> Horizont, etwa -2°
rng = np.random.default_rng(3); H, W = 1600, 2400; hy = int(0.45 * H)
meer = np.zeros((H, W, 3), np.float32)
t = np.linspace(0, 1, hy)[:, None, None]
meer[:hy] = (1 - t) * np.array([225, 140, 90]) + t * np.array([235, 200, 170])
meer[hy:] = np.array([115, 65, 25], np.float32) + rng.normal(0, 5, (H - hy, W, 1))
for y in range(hy + 20, H, 37):
    meer[y:y + 2] += 12
meer = cv2.warpAffine(np.clip(meer, 0, 255).astype(np.uint8), M, (W, H), flags=cv2.INTER_CUBIC,
                      borderMode=cv2.BORDER_REFLECT)
meerdatei = os.path.join(root, "meer", "meer.jpg")
cv2.imwrite(meerdatei, meer, [cv2.IMWRITE_JPEG_QUALITY, 92])

fails = []


def check(ok, msg):
    print(("ok    " if ok else "FEHLER ") + "foto: " + msg, flush=True)
    if not ok:
        fails.append(msg)


def foto(*args):
    r = subprocess.run([FOTO, *args], capture_output=True, text=True, cwd=root)
    return r.returncode, r.stdout, r.stderr


def erstes_json(text):
    """Der erste JSON-Block der Ausgabe (Liste oder Objekt)."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                return dec.raw_decode(text[i:])[0]
            except ValueError:
                continue
    return None


def vorschauen(text):
    return [z.split(": ", 1)[1] for z in text.splitlines() if z.startswith("Vorschau: ")]


rc, out, err = foto("info")
info = erstes_json(out) or {}
check(rc == 0 and info.get("modelle", {}).get("objekte") and info.get("modelle", {}).get("szene"),
      f"Objekt- und Szenenmodell geladen ({info.get('modelle')})")

rc, out, err = foto("neigung", gitter)
res = (erstes_json(out) or [{}])[0]
check(rc == 0 and abs(res.get("winkel", 9) + 2.0) < 0.3, f"Schräglage {res.get('winkel')}° ({res.get('quelle')}), erwartet etwa -2°")
check(res.get("gesichter") == 0, f"Gesichtsmodell geladen, {res.get('gesichter')} Gesichter auf dem Gitter {err[-300:]}")

rc, out, err = foto("neigung", "meer/meer.jpg")
res = (erstes_json(out) or [{}])[0]
check(res.get("quelle") == "horizont" and abs(res.get("winkel", 9) + 2.0) < 0.3,
      f"Horizont {res.get('winkel')}° ({res.get('quelle')}), relativer Pfad")

rc, out, err = foto("sichten", os.path.join(root, "test"))
sicht = erstes_json(out) or {}
v = vorschauen(out)
check(rc == 0 and sicht.get("bilder") == 1 and "typ" in sicht["details"][0] and v and os.path.isfile(v[0]),
      f"Sichtung mit Kontaktbogen {v}")

ziel = os.path.join(root, "vorschau.jpg")
rc, out, err = foto("vorschau", gitter, gitter, "--winkel", "0,-2", "-o", ziel)
check(rc == 0 and os.path.isfile(ziel), f"Vorschau mit zwei Winkeln nach {ziel} {err[-200:]}")

rc, out, err = foto("optimieren", gitter, "--effekte", "gitter=bw")
st = erstes_json(out) or {}
erg = (st.get("ergebnisse") or [{}])[0]
final = os.path.join(root, "test", "final")
check(rc == 0 and st.get("status") == "fertig" and not st.get("fehler") and abs(erg.get("winkel", 9) + 2.0) < 0.3,
      f"optimieren: {st.get('status')}, Winkel {erg.get('winkel')}, Fehler {st.get('fehler')} {err[-300:]}")
check(os.path.isfile(os.path.join(final, "gitter_final.jpg")) and os.path.isfile(os.path.join(final, "gitter_bw.jpg")),
      "Ergebnisdateien in test/final")
check(os.path.isfile(gitter), "Original unverändert vorhanden")
pr = st.get("protokoll_dateien") or []
check(len(pr) == 1 and os.path.isfile(pr[0]) and any(os.path.isfile(p) for p in vorschauen(out)),
      f"Protokoll {pr} und Vorschau {vorschauen(out)}")

rezept = os.path.join(root, "rezept.json")
with open(rezept, "w") as fh:
    json.dump({"anpassen": {"struktur": 20, "himmel": {"helligkeit": -10}}, "effekte": ["tonal"]}, fh)
rc, out, err = foto("rezept-speichern", "test", rezept)
check(rc == 0, "Rezept gespeichert")
rc, out, err = foto("rezept-speichern", "test", rezept)
check(rc == 2 and "schon" in err, "Vorhandenes Rezept wird ohne --ueberschreiben nicht ersetzt")

rc, out, err = foto("anpassen", meerdatei, "--rezept", "test", "--regler", "kontrast=10,wasser.saettigung=5")
check(rc == 0 and os.path.isfile(os.path.join(root, "meer", "meer_angepasst.jpg"))
      and os.path.isfile(os.path.join(root, "meer", "meer_tonal.jpg")), f"anpassen mit Rezept und Bereich {err[-300:]}")
rc, out, err = foto("anpassen", meerdatei, "--regler", "struktuur=5")
check(rc == 2 and "struktuur" in err, "Unbekannter Regler wird abgelehnt")

rc, out, err = foto("aussortieren", meerdatei)
check(rc == 0 and os.path.isfile(os.path.join(root, "meer", "_aussortiert", "meer.jpg")) and not os.path.exists(meerdatei),
      "aussortieren verschiebt")

sys.exit(1 if fails else 0)
