"""Erzeugt Beispielformulare für formular: ein Word-Formular mit allen unterstützten Feldarten
und ein ausfüllbares PDF. Aufruf: python3 beispiele_bauen.py ZIELORDNER"""

import io
import sys
from pathlib import Path

from docx import Document
from docx.shared import Mm
from lxml import etree
from PIL import Image

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NSDECL = f'xmlns:w="{W}" xmlns:w14="{W14}"'


def x(xml: str):
    return etree.fromstring(xml)


def sdt_text(tag, alias, platzhalter, gelb=False):
    hl = '<w:highlight w:val="yellow"/>' if gelb else ""
    return x(f'''<w:sdt {NSDECL}><w:sdtPr><w:alias w:val="{alias}"/><w:tag w:val="{tag}"/><w:showingPlcHdr/><w:text/></w:sdtPr>
<w:sdtContent><w:r><w:rPr><w:rStyle w:val="PlaceholderText"/>{hl}</w:rPr><w:t>{platzhalter}</w:t></w:r></w:sdtContent></w:sdt>''')


def sdt_datum(tag):
    return x(f'''<w:sdt {NSDECL}><w:sdtPr><w:tag w:val="{tag}"/><w:showingPlcHdr/><w:date><w:dateFormat w:val="dd.MM.yyyy"/><w:lid w:val="de-DE"/></w:date></w:sdtPr>
<w:sdtContent><w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t>Datum wählen</w:t></w:r></w:sdtContent></w:sdt>''')


def sdt_check(tag):
    return x(f'''<w:sdt {NSDECL}><w:sdtPr><w:tag w:val="{tag}"/><w14:checkbox><w14:checked w14:val="0"/>
<w14:checkedState w14:val="2612" w14:font="MS Gothic"/><w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/></w14:checkbox></w:sdtPr>
<w:sdtContent><w:r><w:rPr><w:rFonts w:ascii="MS Gothic" w:hAnsi="MS Gothic"/></w:rPr><w:t>☐</w:t></w:r></w:sdtContent></w:sdt>''')


def sdt_liste(tag):
    return x(f'''<w:sdt {NSDECL}><w:sdtPr><w:tag w:val="{tag}"/><w:showingPlcHdr/><w:dropDownList>
<w:listItem w:displayText="Mutter" w:value="m"/><w:listItem w:displayText="Vater" w:value="v"/></w:dropDownList></w:sdtPr>
<w:sdtContent><w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t>Element wählen</w:t></w:r></w:sdtContent></w:sdt>''')


def legacy(typ, name):
    if typ == "text":
        ff = f'<w:ffData><w:name w:val="{name}"/><w:enabled/><w:textInput/></w:ffData>'
        code, ergebnis = " FORMTEXT ", '<w:r><w:t xml:space="preserve">     </w:t></w:r>'
    else:
        ff = f'<w:ffData><w:name w:val="{name}"/><w:enabled/><w:checkBox><w:sizeAuto/><w:default w:val="0"/></w:checkBox></w:ffData>'
        code, ergebnis = " FORMCHECKBOX ", ""
    return [x(f'<w:r {NSDECL}><w:fldChar w:fldCharType="begin">{ff}</w:fldChar></w:r>'),
            x(f'<w:r {NSDECL}><w:instrText xml:space="preserve">{code}</w:instrText></w:r>'),
            x(f'<w:r {NSDECL}><w:fldChar w:fldCharType="separate"/></w:r>')] + \
           ([x(ergebnis.replace("<w:r>", f"<w:r {NSDECL}>"))] if ergebnis else []) + \
           [x(f'<w:r {NSDECL}><w:fldChar w:fldCharType="end"/></w:r>')]


def word(ziel: Path):
    d = Document()
    d.add_heading("Anmeldung Elternzeit (Beispiel)", 1)
    p = d.add_paragraph("Name | Name: ")
    p._p.append(sdt_text("name", "Name", "Klicken Sie hier, um Text einzugeben.", gelb=True))
    p = d.add_paragraph("Geburtsdatum des Kindes: ")
    p._p.append(sdt_datum("geburt"))
    p = d.add_paragraph("Antrag stellt: ")
    p._p.append(sdt_liste("person"))
    p = d.add_paragraph()
    p._p.append(sdt_check("nachreichen"))
    p.add_run(" Geburtsurkunde wird zeitnah nachgereicht")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Personalnummer"
    t.cell(0, 1).paragraphs[0]._p.extend(legacy("text", "PersNr"))
    t.cell(1, 0).text = "Teilzeit gewünscht"
    t.cell(1, 1).paragraphs[0]._p.extend(legacy("check", "Teilzeit"))
    p = d.add_paragraph("Name des Kindes: ")
    p.add_run("[Name des")
    p.add_run(" Kindes]")
    d.add_paragraph("☐ Elternzeit aufgeteilt")
    d.add_paragraph("Ort, Datum: ________________")
    d.add_paragraph("______________________________")
    d.add_paragraph("Unterschrift | Signature")
    # Bild-Steuerelement (zweite Unterschrift) mit leerem Platzhalterbild
    leer = io.BytesIO()
    Image.new("RGB", (400, 120), "white").save(leer, "PNG")
    p = d.add_paragraph()
    lauf = p.add_run()
    lauf.add_picture(io.BytesIO(leer.getvalue()), width=Mm(40))
    sdt = x(f'<w:sdt {NSDECL}><w:sdtPr><w:tag w:val="unterschrift2"/><w:showingPlcHdr/><w:picture/></w:sdtPr><w:sdtContent/></w:sdt>')
    p._p.remove(lauf._r)
    sdt.find(f"{{{W}}}sdtContent").append(lauf._r)
    p._p.append(sdt)
    d.add_paragraph("Unterschrift Partner | Signature partner")
    d.save(ziel)


def unterschrift(ziel: Path):
    from PIL import ImageDraw

    im = Image.new("RGBA", (600, 180), (255, 255, 255, 0))
    dr = ImageDraw.Draw(im)
    dr.line([(20, 140), (120, 40), (200, 130), (300, 50), (420, 120), (560, 60)], fill=(10, 30, 120, 255), width=8)
    im.save(ziel)


def pdf(ziel: Path):
    from reportlab.lib.colors import black
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(ziel))
    form = c.acroForm
    c.drawString(50, 780, "Antrag (Beispiel-PDF)")
    c.drawString(50, 740, "Name:")
    form.textfield(name="name", tooltip="Name", x=150, y=730, width=250, height=20, borderColor=black)
    c.drawString(50, 700, "Einverstanden:")
    form.checkbox(name="ok", tooltip="Einverstanden", x=150, y=695, buttonStyle="check", size=15)
    c.drawString(50, 660, "Zahlweise:")
    form.radio(name="zahlung", tooltip="Zahlweise", value="bar", selected=False, x=150, y=655, size=15)
    form.radio(name="zahlung", tooltip="Zahlweise", value="karte", selected=False, x=200, y=655, size=15)
    c.drawString(50, 620, "Land:")
    form.choice(name="land", tooltip="Land", value="Deutschland", options=["Deutschland", "Österreich"],
                x=150, y=610, width=150, height=20)
    c.drawString(50, 560, "Unterschrift:")
    form.textfield(name="unterschrift", tooltip="Unterschrift", x=150, y=540, width=200, height=50)
    c.save()


if __name__ == "__main__":
    z = Path(sys.argv[1])
    z.mkdir(parents=True, exist_ok=True)
    word(z / "beispiel.docx")
    pdf(z / "beispiel.pdf")
    unterschrift(z / "unterschrift.png")
    print("ok")
