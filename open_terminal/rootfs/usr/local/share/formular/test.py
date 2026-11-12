"""Selbsttest für formular (läuft beim Bau des Images): füllt die Beispiele aus und prüft das Ergebnis."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
FORMULAR = os.environ.get("FORMULAR", "/usr/local/bin/formular")


def lauf(*args, ok=True):
    r = subprocess.run([sys.executable, FORMULAR, *map(str, args)], capture_output=True, text=True)
    if ok and r.returncode:
        sys.exit(f"formular {' '.join(map(str, args))} schlug fehl:\n{r.stdout}{r.stderr}")
    return r


def felder(p):
    return {f["kennung"]: f for f in json.loads(lauf("felder", p, "--json").stdout)}


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    for n in ("beispiel.docx", "beispiel.pdf", "unterschrift.png", "werte_docx.yaml", "werte_pdf.yaml"):
        shutil.copy(HIER / "beispiele" / n, t / n)
    os.chdir(t)
    vor = felder("beispiel.docx")
    assert len(vor) == 11, f"Word: {len(vor)} Felder statt 11"
    lauf("ausfuellen", "beispiel.docx", "werte_docx.yaml", "-o", "aus.docx")
    nach = felder("aus.docx")
    soll = {"S1": "David Muster", "S2": "14.03.2026", "S3": "Vater", "S4": True, "L1": "4711", "L2": True}
    for k, v in soll.items():
        assert nach[k]["wert"] == v, f"Word {k}: {nach[k]['wert']!r} statt {v!r}"
    assert not any(f["art"] == "platzhalter" for f in nach.values()), "Platzhalter nicht ersetzt"
    assert (t / "beispiel.docx").read_bytes() == (HIER / "beispiele" / "beispiel.docx").read_bytes(), "Vorlage verändert"
    lauf("ausfuellen", "beispiel.pdf", "werte_pdf.yaml", "-o", "aus.pdf")
    p = felder("aus.pdf")
    werte = {f["name"]: f["wert"] for f in p.values()}
    assert werte == {"name": "David Muster", "ok": True, "zahlung": "karte", "land": "Österreich"}, werte
    lauf("ausfuellen", "beispiel.pdf", "werte_pdf.yaml", "-o", "flach.pdf", "--flach")
    assert felder("flach.pdf") == {}, "flach: Felder übrig"
    (t / "falsch.yaml").write_text("S3: Oma\n", encoding="utf-8")
    r = lauf("ausfuellen", "beispiel.docx", "falsch.yaml", "-o", "x.docx", ok=False)
    assert r.returncode == 2 and not (t / "x.docx").exists(), "ungültiger Wert nicht abgefangen"
print("formular: Selbsttest ok")
