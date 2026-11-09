#!/usr/bin/env python3
"""Erzeugt die Word-Referenzdokumente für `dokument` (Pandoc --reference-doc).

  python3 open_terminal/werkzeuge/referenz_docx.py open_terminal/rootfs/usr/local/share/dokumente

Basis ist Pandocs eigenes reference.docx (alle Formatvorlagen, die Pandoc nutzt), darauf werden
Schriften, Größen, Farben, Abstände, Seitenränder und Fußzeile je Stil gesetzt. Zusätzlich die
Absatzvorlagen für Briefe: Absenderzeile, Anschrift, Infoblock, Betreff, Gruss.
"""
import subprocess, sys, tempfile
from pathlib import Path
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

STILE = {
    "persoenlich": dict(sans="IBM Plex Sans", titel="IBM Plex Sans Light", mono="IBM Plex Mono",
                        text="161616", leise="525252", akzent="0F62FE", linie="C6C6C6", claim=None),
    "hannesbraeu": dict(sans="Avenir Next LT Pro", titel="Avenir Next LT Pro Light", mono="Consolas",
                        text="333333", leise="555555", akzent="000000", linie="CCCCCC",
                        claim="FRISCH | REGIONAL | NATURBELASSEN"),
}


def farbe(h):
    return RGBColor.from_string(h)


def schrift(style, name, size=None, bold=None, color=None, italic=None):
    f = style.font
    f.name = name
    rpr = style.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name)
    if size: f.size = Pt(size)
    if bold is not None: f.bold = bold
    if italic is not None: f.italic = italic
    if color: f.color.rgb = farbe(color)


def absatz(style, vor=0, nach=6, zeile=None, ausr=None):
    pf = style.paragraph_format
    pf.space_before = Pt(vor); pf.space_after = Pt(nach)
    if zeile: pf.line_spacing = zeile
    if ausr is not None: pf.alignment = ausr


def stil_holen(doc, name, basis="Normal"):
    try:
        return doc.styles[name]
    except KeyError:
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles[basis]
        st.quick_style = True
        return st


def seitenfeld(run, feld):
    for typ, txt in (("begin", None), (None, feld), ("end", None)):
        if typ:
            e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), typ); run._r.append(e)
        else:
            e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = txt; run._r.append(e)


def baue(stil, ziel):
    k = STILE[stil]
    with tempfile.TemporaryDirectory() as t:
        roh = Path(t) / "ref.docx"
        subprocess.run(["pandoc", "-o", str(roh), "--print-default-data-file", "reference.docx"], check=True)
        doc = Document(roh)
    alle = {x.name: x for x in doc.styles}
    class _S(dict):
        def __getitem__(self, n):
            return alle[n] if n in alle else doc.styles[n]
    st = _S()
    schrift(st["Normal"], k["sans"], 10.5, color=k["text"])
    for n in ("Body Text", "First Paragraph", "Compact"):
        if n in alle:
            schrift(st[n], k["sans"], 10.5, color=k["text"]); absatz(st[n], 0, 7, 1.15)
    for lvl, size in ((1, 18), (2, 14), (3, 11.5), (4, 10.5)):
        h = st[f"Heading {lvl}"]
        schrift(h, k["sans"], size, bold=True, color=k["text"], italic=False)
        absatz(h, 16 if lvl == 1 else 12, 6)
    schrift(st["Title"], k["titel"], 28, bold=False, color=k["text"]); absatz(st["Title"], 0, 4, ausr=WD_ALIGN_PARAGRAPH.LEFT)
    if "Subtitle" in [s.name for s in st]:
        schrift(st["Subtitle"], k["sans"], 13, color=k["leise"], italic=False); absatz(st["Subtitle"], 0, 14, ausr=WD_ALIGN_PARAGRAPH.LEFT)
    for n in ("Author", "Date"):
        if n in alle:
            schrift(st[n], k["sans"], 9, color=k["leise"]); absatz(st[n], 0, 2, ausr=WD_ALIGN_PARAGRAPH.LEFT)
    for n in ("Block Text",):
        if n in alle:
            schrift(st[n], k["sans"], 10.5, color=k["leise"], italic=True)
    for n in ("Source Code", "Verbatim Char"):
        if n in alle:
            schrift(st[n], k["mono"], 9.5)
    if "Hyperlink" in [s.name for s in st]:
        st["Hyperlink"].font.color.rgb = farbe(k["akzent"] if k["akzent"] != "000000" else k["text"])

    # Briefvorlagen (für dokument --art brief/anschreiben im Word-Format)
    def neu(name, size=10.5, color=None, bold=False, vor=0, nach=0):
        s = alle.get(name) or stil_holen(doc, name); schrift(s, k["sans"], size, bold=bold, color=color or k["text"])
        absatz(s, vor, nach, 1.0); return s
    neu("Briefkopf", 15, bold=True, nach=2)
    neu("Briefkopf Kontakt", 8, k["leise"], nach=0)
    neu("Ruecksendung", 6.5, k["leise"], vor=40, nach=4)
    neu("Anschrift", 10.5, nach=0)
    neu("Infoblock", 8.5, k["leise"], nach=0).paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    neu("Betreff", 11, bold=True, vor=30, nach=14)
    neu("Gruss", 10.5, vor=12, nach=36)
    neu("Anlagen", 10.5, bold=True, vor=18, nach=0)

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin, sec.right_margin = Mm(25), Mm(20)
    sec.top_margin, sec.bottom_margin = Mm(25), Mm(25)
    sec.footer_distance = Mm(10)
    fp = sec.footer.paragraphs[0] if sec.footer.paragraphs else sec.footer.add_paragraph()
    fp.text = ""
    if k["claim"]:
        r = fp.add_run(k["claim"] + "\t"); r.font.size = Pt(7); r.font.color.rgb = farbe(k["leise"]); r.font.name = k["sans"]
    r = fp.add_run(); r.font.size = Pt(8); r.font.color.rgb = farbe(k["leise"]); seitenfeld(r, "PAGE")
    r = fp.add_run(" / "); r.font.size = Pt(8); r.font.color.rgb = farbe(k["leise"])
    r = fp.add_run(); r.font.size = Pt(8); r.font.color.rgb = farbe(k["leise"]); seitenfeld(r, "NUMPAGES")
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT if not k["claim"] else WD_ALIGN_PARAGRAPH.LEFT
    if k["claim"]:
        tabs = fp.paragraph_format.tab_stops
        from docx.enum.text import WD_TAB_ALIGNMENT
        tabs.add_tab_stop(Mm(165), WD_TAB_ALIGNMENT.RIGHT)
    doc.core_properties.author = ""
    doc.core_properties.title = ""
    doc.save(ziel)
    print("geschrieben:", ziel)


if __name__ == "__main__":
    ziel = Path(sys.argv[1])
    for s in STILE:
        baue(s, ziel / f"referenz-{s}.docx")
