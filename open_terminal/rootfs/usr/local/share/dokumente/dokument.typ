// Dokumentvorlagen für Open Terminal: Briefe nach DIN 5008 (Form B), Anschreiben, Berichte, Notizen.
// Stile: "persoenlich" (angelehnt an IBM Carbon: IBM Plex, Grau 100, Blau 60) und "hannesbraeu"
// (HannesBräu-Designsystem: monochrom, Nunito Sans statt Avenir Next, Crimson Pro statt Athelas).
// Aufruf normalerweise über das Programm `dokument` (Pandoc → Typst → PDF).

#let STILE = (
  persoenlich: (
    sans: "IBM Plex Sans", serif: "IBM Plex Sans", mono: "IBM Plex Mono",
    text: rgb("#161616"), leise: rgb("#525252"), linie: rgb("#c6c6c6"), akzent: rgb("#0f62fe"),
    flaeche: rgb("#f4f4f4"),
    groesse: 10.5pt, zeile: 0.62em,
    titel-font: "IBM Plex Sans", titel-gewicht: 300, kopf-gewicht: 600,
    logo: none, claim: none,
  ),
  hannesbraeu: (
    sans: "Nunito Sans", serif: "Crimson Pro", mono: "IBM Plex Mono",
    text: rgb("#333333"), leise: rgb("#555555"), linie: rgb("#cccccc"), akzent: rgb("#000000"),
    flaeche: rgb("#f4f4f4"),
    groesse: 10.5pt, zeile: 0.62em,
    titel-font: "Crimson Pro", titel-gewicht: 200, kopf-gewicht: 700,
    logo: "/usr/local/share/dokumente/logos/hannesbraeu-logo.svg",
    claim: "FRISCH | REGIONAL | NATURBELASSEN",
  ),
)

#let _leer(x) = x == none or x == "" or x == [] or x == ()
#let _zeilen(x) = if type(x) == array { x.filter(z => not _leer(z)).join(linebreak()) } else { x }

// Gemeinsame Grundeinstellungen: Schrift, Absätze, Überschriften, Listen, Tabellen, Zitate, Code.
#let _grundlage(s, body) = {
  set text(font: s.sans, size: s.groesse, fill: s.text, lang: "de", region: "DE",
           hyphenate: true, number-type: "lining")
  set par(justify: false, leading: s.zeile, spacing: 1.1em)
  set heading(numbering: none)
  show heading: it => block(above: 1.6em, below: 0.7em, sticky: true)[
    #set text(weight: s.kopf-gewicht, fill: s.text)
    #it.body
  ]
  show heading.where(level: 1): set text(size: 1.45em)
  show heading.where(level: 2): set text(size: 1.18em)
  show heading.where(level: 3): set text(size: 1em)
  set list(indent: 0.2em, body-indent: 0.6em, marker: ([–], [·]))
  set enum(indent: 0.2em, body-indent: 0.6em)
  show link: it => {
    set text(fill: if s.akzent == rgb("#000000") { s.text } else { s.akzent })
    underline(offset: 2pt, stroke: 0.4pt, it)
  }
  show raw: set text(font: s.mono, size: 0.92em)
  show raw.where(block: true): it => block(fill: s.flaeche, inset: 8pt, radius: 2pt, width: 100%, it)
  show quote.where(block: true): it => block(inset: (left: 12pt, y: 2pt), stroke: (left: 1.5pt + s.linie),
    text(fill: s.leise, style: "italic", it.body))
  set table(stroke: (x, y) => (
      top: if y == 0 { 0.8pt + s.text } else if y == 1 { 0.6pt + s.text } else { 0.3pt + s.linie },
      bottom: none, left: none, right: none),
    inset: (x: 6pt, y: 5pt), align: left)
  show table.cell.where(y: 0): set text(weight: s.kopf-gewicht)
  show table: it => block(stroke: (bottom: 0.8pt + s.text), it)
  show figure.caption: set text(size: 0.88em, fill: s.leise)
  body
}

// ---------------------------------------------------------------- Brief (DIN 5008, Form B)

#let _falzmarken(s) = place(top + left, dx: -25mm, {
  // Falzmarken bei 105 und 210 mm, Lochmarke bei 148,5 mm (Form B), am linken Rand.
  for (y, l) in ((105mm, 4mm), (148.5mm, 6mm), (210mm, 4mm)) {
    place(top + left, dx: 4mm, dy: y - 27mm, line(length: l, stroke: 0.3pt + s.linie))
  }
})

#let brief(
  stil: "persoenlich", art: "brief",
  absender: (:), empfaenger: (), ruecksendung: none,
  datum: none, ort: none, betreff: none, bezug: none,
  ihr-zeichen: none, ihre-nachricht: none, unser-zeichen: none,
  anrede: none, gruss: "Mit freundlichen Grüßen", unterschrift: none, unterschrift-bild: none,
  anlagen: (), verteiler: (), fusszeile: auto, body,
) = {
  let s = STILE.at(stil)
  let a = absender
  let name = a.at("name", default: none)
  let kontakt = (a.at("telefon", default: none), a.at("mail", default: none), a.at("web", default: none))
    .filter(x => not _leer(x))
  let adresse = (a.at("strasse", default: none), a.at("ort", default: none)).filter(x => not _leer(x))

  // Kopf: Form B lässt oben 45 mm; erste Seite oben 27 mm Rand, der Kopf steht darin.
  let kopf-persoenlich() = {
    if art == "anschreiben" {
      text(size: 22pt, weight: 300, tracking: 0.2pt, name)
      v(1mm)
      text(size: 8.5pt, fill: s.leise, (adresse + kontakt).join("  ·  "))
      v(2mm)
      line(length: 100%, stroke: 0.6pt + s.akzent)
    } else {
      grid(columns: (1fr, auto), align: (left + bottom, right + bottom),
        text(size: 15pt, weight: 600, name),
        text(size: 8pt, fill: s.leise, (adresse + kontakt).join(linebreak())))
      v(2mm)
      line(length: 100%, stroke: 0.4pt + s.linie)
    }
  }
  let kopf-hb() = {
    grid(columns: (1fr, 26mm), align: (left + bottom, right + top),
      {
        text(size: 20pt, weight: 200, tracking: 0.3pt, "HannesBräu")
        v(0.5mm)
        text(size: 7pt, weight: 300, tracking: 1.2pt, fill: s.leise, s.claim)
      },
      image(s.logo, width: 26mm))
  }

  set page(paper: "a4",
    margin: (left: 25mm, right: 20mm, top: 27mm, bottom: 30mm),
    header: context {
      if counter(page).get().first() > 1 {
        set text(size: 8pt, fill: s.leise)
        grid(columns: (1fr, auto),
          [#if stil == "hannesbraeu" [HannesBräu] else [#name]#if not _leer(betreff) [ · #betreff]],
          [Seite #counter(page).display() von #counter(page).final().first()])
        v(-1mm); line(length: 100%, stroke: 0.3pt + s.linie)
      }
    },
    header-ascent: 8mm,
    footer: context {
      set text(size: 7pt, fill: s.leise)
      if fusszeile == auto {
        let f = a.at("fusszeile", default: ())
        if type(f) == array and f.len() > 0 {
          line(length: 100%, stroke: 0.3pt + s.linie)
          v(-1mm)
          grid(columns: f.len() * (1fr,), column-gutter: 4mm, ..f.map(spalte => _zeilen(spalte)))
        }
      } else if fusszeile != none { fusszeile }
      if counter(page).final().first() > 1 and counter(page).get().first() == 1 {
        place(bottom + right, dy: -1mm, text(size: 7pt)[Seite 1 von #counter(page).final().first()])
      }
    },
    footer-descent: 6mm,
  )
  show: _grundlage.with(s)

  // Erste Seite: Kopf im oberen Rand (Form B: 45 mm).
  place(top + left, dy: -27mm + 10mm, block(width: 100%, height: 30mm,
    align(bottom, if stil == "hannesbraeu" { kopf-hb() } else { kopf-persoenlich() })))
  _falzmarken(s)

  // Anschriftfeld: 20 mm vom linken Rand, 45 mm von oben, 85 × 45 mm. Zusatz- und Vermerkzone 17,7 mm.
  place(top + left, dx: -5mm, dy: 45mm - 27mm, block(width: 85mm, height: 45mm, inset: (left: 5mm), {
    block(height: 17.7mm, width: 100%, align(bottom, {
      let r = if ruecksendung != none { ruecksendung } else {
        ((name,) + adresse).filter(x => not _leer(x)).join(", ")
      }
      if not _leer(r) { text(size: 6.5pt, fill: s.leise, r) }
    }))
    block(height: 27.3mm, width: 100%, inset: (top: 1mm), text(size: 10pt, _zeilen(empfaenger)))
  }))

  // Informationsblock: 125 mm vom linken Rand, 50 mm von oben, 75 mm breit.
  let info = (
    ("Ihr Zeichen", ihr-zeichen), ("Ihre Nachricht vom", ihre-nachricht), ("Unser Zeichen", unser-zeichen),
    ("Name", if art == "brief" and not _leer(a.at("ansprechpartner", default: none)) { a.ansprechpartner } else { none }),
    ("Telefon", a.at("telefon", default: none)), ("E-Mail", a.at("mail", default: none)),
    ("Datum", if _leer(datum) { datetime.today().display("[day].[month].[year]") } else { datum }),
  ).filter(((k, v)) => not _leer(v))
  place(top + left, dx: 125mm - 25mm, dy: 50mm - 27mm, block(width: 75mm - 5mm,
    text(size: 8pt, grid(columns: (auto, 1fr), column-gutter: 3mm, row-gutter: 1.6mm,
      ..info.map(((k, v)) => (text(fill: s.leise, k), v)).flatten()))))

  // Betreff ab ca. 98,5 mm von oben (zwei Leerzeilen unter dem Anschriftfeld).
  v(98.5mm - 27mm)
  if not _leer(betreff) {
    text(weight: s.kopf-gewicht, size: 1.05em, betreff)
    if not _leer(bezug) { linebreak(); text(fill: s.leise, size: 0.9em, bezug) }
    v(1.4em)
  }
  if not _leer(anrede) { anrede; v(0.4em) }
  body
  v(1.2em)
  block(breakable: false, {
    gruss
    v(if unterschrift-bild != none { 2mm } else { 13mm })
    if unterschrift-bild != none { image(unterschrift-bild, height: 13mm); v(1mm) }
    let u = if _leer(unterschrift) { if stil == "hannesbraeu" { name } else { name } } else { unterschrift }
    _zeilen(u)
  })
  if anlagen.len() > 0 { v(1.6em); text(weight: s.kopf-gewicht)[Anlage#if anlagen.len() > 1 [n]]; linebreak(); _zeilen(anlagen) }
  if verteiler.len() > 0 { v(1em); text(weight: s.kopf-gewicht)[Verteiler]; linebreak(); _zeilen(verteiler) }
}

// ---------------------------------------------------------------- Bericht und Notiz

#let bericht(stil: "persoenlich", art: "bericht", titel: none, untertitel: none, autor: none,
             datum: none, inhaltsverzeichnis: false, nummeriert: false, absender: (:), body) = {
  let s = STILE.at(stil)
  let datum = if _leer(datum) { datetime.today().display("[day].[month].[year]") } else { datum }
  set document(title: if titel != none { titel } else { "" })
  set page(paper: "a4", margin: (left: 25mm, right: 22mm, top: 25mm, bottom: 25mm),
    header: context if counter(page).get().first() > 1 {
      set text(size: 8pt, fill: s.leise)
      grid(columns: (1fr, auto), titel, if stil == "hannesbraeu" [HannesBräu] else [#autor])
      v(-1mm); line(length: 100%, stroke: 0.3pt + s.linie)
    },
    footer: context {
      set text(size: 8pt, fill: s.leise)
      grid(columns: (1fr, auto),
        if s.claim != none { text(tracking: 1pt, size: 6.5pt, s.claim) } else { datum },
        [#counter(page).display() / #counter(page).final().first()])
    })
  show: _grundlage.with(s)
  set heading(numbering: if nummeriert { "1.1" } else { none })

  // Titelblock
  if stil == "hannesbraeu" {
    grid(columns: (1fr, 22mm), align: (left + bottom, right + top),
      text(size: 8pt, weight: 300, tracking: 1.2pt, fill: s.leise)[HANNESBRÄU · #datum],
      image(s.logo, width: 22mm))
    v(if art == "notiz" { 4mm } else { 10mm })
  } else {
    text(size: 8pt, fill: s.leise, tracking: 0.4pt, upper[#if not _leer(autor) [#autor · ]#datum])
    v(2mm)
  }
  if not _leer(titel) {
    block(below: 3mm, text(font: s.titel-font, weight: s.titel-gewicht,
      size: if art == "notiz" { 20pt } else { 30pt }, fill: s.text, titel))
  }
  if not _leer(untertitel) { block(below: 2mm, text(size: 13pt, fill: s.leise, weight: 300, untertitel)) }
  if stil == "persoenlich" { line(length: 18mm, stroke: 1.6pt + s.akzent) } else { line(length: 100%, stroke: 0.4pt + s.linie) }
  v(if art == "notiz" { 4mm } else { 8mm })
  if inhaltsverzeichnis {
    outline(title: text(weight: s.kopf-gewicht)[Inhalt], indent: 1em)
    v(6mm)
  }
  body
}

#let dokument(stil: "persoenlich", art: "bericht", ..args, body) = {
  let p = args.named()
  if art in ("brief", "anschreiben") { brief(stil: stil, art: art, ..p, body) }
  else { bericht(stil: stil, art: art, ..p, body) }
}
