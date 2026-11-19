#!/usr/bin/env python3
"""Selbsttest für den Befehl etikett (Bau des Images und CI): synthetisches Etikett mit Feld rect592 in
der Gruppe ean, Word-Vorlage mit genau einem PNG; komplett muss 6 lesbare Barcodes und die docx liefern,
eine falsche Prüfziffer und ein vorhandener Bogen ohne --force werden abgelehnt.
"""
import io
import os
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image

ETIKETT = os.environ.get("ETIKETT_CLI", "/usr/local/bin/etikett")
root = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="etikett-test-")
for d in ("01_etiketten", "02_zweckform", "03_templates"):
    os.makedirs(os.path.join(root, d), exist_ok=True)

# Etikett hochkant im Maßstab 10:1 wie die Originale (Feld des 0,33er-Etiketts)
svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="263.9mm" height="280.9mm" viewBox="0 0 2639 2809">
  <rect width="2639" height="2809" fill="#f2e6c9"/>
  <text x="200" y="400" font-family="Liberation Sans" font-size="220" fill="#7a1f1f">Pils</text>
  <g id="ean"><rect id="rect592" x="1535.61" y="648.90" width="592.13" height="251.26" fill="#ffffff"/>
  <g id="barcode_0000000000000"><rect x="0" y="0" width="1" height="1"/></g></g>
</svg>"""
with open(os.path.join(root, "01_etiketten", "etikett_l7166_test_03.svg"), "w") as fh:
    fh.write(svg)
buf = io.BytesIO(); Image.new("RGB", (10, 10), "white").save(buf, "PNG")
with zipfile.ZipFile(os.path.join(root, "03_templates", "AZ-l7166_vorlage_03.docx"), "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("word/document.xml", "<w:document/>")
    z.writestr("word/media/image1.png", buf.getvalue())

fails = []


def check(ok, msg):
    print(("ok    " if ok else "FEHLER ") + "etikett: " + msg, flush=True)
    if not ok:
        fails.append(msg)


def etikett(*args):
    r = subprocess.run([ETIKETT, "--ordner", root, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


rc, out = etikett("komplett", "test", "03", "0640813463328")
docx = os.path.join(root, "03_templates", "AZ-l7166_test_03.docx")
png = os.path.join(root, "02_zweckform", "bogen_l7166_test03.png")
check(rc == 0 and "6 Barcodes" in out and os.path.isfile(docx), f"komplett: {out.strip()[-400:]}")
if os.path.isfile(png):
    im = Image.open(png)
    check(im.size[0] == 2480 and abs(im.size[1] - 3508) <= 1, f"Bogen 2480 × 3508 px ({im.size})")
if os.path.isfile(docx):
    with zipfile.ZipFile(docx) as z:
        check(z.read("word/media/image1.png") == open(png, "rb").read(), "Bogen steckt in der Word-Datei")
src = open(os.path.join(root, "01_etiketten", "etikett_l7166_test_03.svg")).read()
check("barcode_0000000000000" in src, "Quell-Etikett unverändert")
mit = open(os.path.join(root, "01_etiketten", "etikett_l7166_test_03_ean.svg")).read()
check("barcode_0640813463328" in mit and "barcode_0000000000000" not in mit, "alter Barcode ersetzt")
rc, out = etikett("komplett", "test", "03", "0640813463328")
check(rc != 0 and "gibt es schon" in out, "vorhandener Bogen ohne --force nicht überschrieben")
rc, out = etikett("barcode", "0640813463327", "100", "40")
check(rc != 0 and "Prüfziffer" in out, "falsche Prüfziffer abgelehnt")
sys.exit(1 if fails else 0)
