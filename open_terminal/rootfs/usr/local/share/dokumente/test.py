#!/usr/bin/env python3
"""Selbsttest für `dokument` (läuft beim Bau des Images): alle Beispiele in allen Formaten, dazu
Absender je Person, Stil hannesbraeu nur mit eigenem Absender, absolute Bildpfade und dass
vorhandene Dateien im Eingabeordner unberührt bleiben."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASIS = Path(os.environ.get("DOKUMENT_BASIS", "/usr/local/share/dokumente"))
DOKUMENT = os.environ.get("DOKUMENT_BIN", "dokument")
fehler = []


def lauf(args, eigene, cwd, **env):
    e = dict(os.environ, DOKUMENT_EIGENE=str(eigene), **env)
    return subprocess.run([sys.executable, shutil.which(DOKUMENT) or DOKUMENT, *args],
                          cwd=cwd, env=e, capture_output=True, text=True)


def soll(bed, text, r=None):
    print(("ok    " if bed else "FEHLER ") + text)
    if not bed:
        fehler.append(text)
        if r is not None:
            print(r.stdout + r.stderr)


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    leer = t / "leer"           # Person ohne eigene Absender
    eigene = t / "eigene"       # Person mit ich.yaml
    (eigene / "absender").mkdir(parents=True)
    leer.mkdir()
    shutil.copyfile(BASIS / "absender" / "beispiel.yaml", eigene / "absender" / "ich.yaml")
    (eigene / "absender" / "verein.yaml").write_text("absender:\n  name: Verein Beispiel e. V.\n  ort: 12345 Beispielort\n")

    # 1. Alle Beispiele (Absender stehen im Kopf; hannesbraeu für den Test freigegeben)
    b = t / "beispiele"
    shutil.copytree(BASIS / "beispiele", b)
    for md in sorted(b.glob("*.md")):
        r = lauf([md.name, "-f", "pdf,docx,html"], leer, b, DOKUMENT_ALLE_STILE="1")
        soll(r.returncode == 0 and all((b / f"{md.stem}.{f}").stat().st_size > 1000 for f in ("pdf", "docx", "html")),
             f"Beispiel {md.name} als PDF, Word und HTML", r)

    # 2. Absender je Person
    a = t / "arbeit"
    a.mkdir()
    (a / "brief.md").write_text("---\nart: brief\nempfaenger: [Firma, Weg 1, 12345 Ort]\nbetreff: Test\n---\n\nText.\n")
    r = lauf(["brief.md"], leer, a)
    soll(r.returncode == 1 and "ich.yaml" in r.stderr, "Brief ohne eigenen Absender bricht mit Hinweis auf ich.yaml ab", r)
    r = lauf(["brief.md", "--vorschau"], eigene, a)
    txt = subprocess.run(["pdftotext", str(a / "brief.pdf"), "-"], capture_output=True, text=True).stdout
    soll(r.returncode == 0 and "Max Mustermann" in txt, "Brief nimmt ich.yaml der Person", r)
    soll((a / "brief_vorschau-1.png").exists(), "Vorschau als PNG")
    r = lauf(["brief.md", "--absender", "verein"], eigene, a)
    txt = subprocess.run(["pdftotext", str(a / "brief_2.pdf"), "-"], capture_output=True, text=True).stdout
    soll(r.returncode == 0 and "Verein Beispiel" in txt, "--absender verein, vorhandenes brief.pdf bleibt (brief_2.pdf)", r)
    r = lauf(["brief.md", "-s", "hannesbraeu"], eigene, a)
    soll(r.returncode == 1 and "hannesbraeu.yaml" in r.stderr, "Stil hannesbraeu ohne eigenen Absender abgelehnt", r)
    r = lauf(["--liste"], eigene, a)
    soll(r.returncode == 0 and "hannesbraeu" not in r.stdout.split("\n")[0] and "ich, verein" in r.stdout,
         "--liste zeigt nur eigene Absender und verfügbare Stile", r)

    # 3. Bilder relativ und absolut; Dateien im Eingabeordner mit gleichem Namen bleiben unberührt
    shutil.copytree(BASIS / "beispiele" / "reise-bilder", a / "bilder")
    absolut = a / "bilder" / "abend.jpg"
    (a / "notiz.md").write_text(f"---\nart: notiz\ntitle: Bilder\n---\n\n![relativ](bilder/fluss.jpg)\n\n![absolut]({absolut})\n")
    (a / "notiz.html").write_text("ALT")
    os.mkdir(a / "notiz_files")
    r = lauf(["notiz.md", "-f", "pdf,html"], leer, a)
    bilder = subprocess.run(["pdfimages", "-list", str(a / "notiz.pdf")], capture_output=True, text=True).stdout
    soll(r.returncode == 0 and len(bilder.strip().splitlines()) >= 4, "Bilder mit relativem und absolutem Pfad im PDF", r)
    soll((a / "notiz.html").read_text() == "ALT" and (a / "notiz_2.html").exists(),
         "vorhandene notiz.html unverändert, Ausgabe als notiz_2.html")

if fehler:
    print(f"{len(fehler)} Fehler")
    sys.exit(1)
print("dokument: alle Tests bestanden")
