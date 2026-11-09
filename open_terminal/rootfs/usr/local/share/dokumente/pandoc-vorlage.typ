// Pandoc-Vorlage (Typst): übergibt die YAML-Angaben an dokument.typ. Erzeugt von `dokument`.
#import "/usr/local/share/dokumente/dokument.typ": dokument

$definitions.typst()$
// Eigene Fassungen, gestaltet in dokument.typ
#let blockquote(body) = quote(block: true, body)
#let horizontalrule = block(above: 1em, below: 1em, line(length: 100%, stroke: 0.4pt + luma(200)))

#show: dokument.with(
  stil: "$if(stil)$$stil$$else$persoenlich$endif$",
  art: "$if(art)$$art$$else$bericht$endif$",
$if(title)$  titel: [#[]$title$],
$endif$$if(untertitel)$  untertitel: [#[]$untertitel$],
$endif$$if(autor)$  autor: [#[]$autor$],
$endif$$if(datum)$  datum: [#[]$datum$],
$endif$$if(inhaltsverzeichnis)$  inhaltsverzeichnis: true,
$endif$$if(nummeriert)$  nummeriert: true,
$endif$$if(absender)$  absender: (
$if(absender.name)$    name: [#[]$absender.name$],
$endif$$if(absender.strasse)$    strasse: [#[]$absender.strasse$],
$endif$$if(absender.ort)$    ort: [#[]$absender.ort$],
$endif$$if(absender.telefon)$    telefon: [#[]$absender.telefon$],
$endif$$if(absender.mail)$    mail: [#[]$absender.mail$],
$endif$$if(absender.web)$    web: [#[]$absender.web$],
$endif$$if(absender.ansprechpartner)$    ansprechpartner: [#[]$absender.ansprechpartner$],
$endif$$if(absender.fusszeile)$    fusszeile: ($for(absender.fusszeile)$($for(it)$[#[]$it$],$endfor$),$endfor$),
$endif$  ),
$endif$$if(empfaenger)$  empfaenger: ($for(empfaenger)$[#[]$empfaenger$],$endfor$),
$endif$$if(ruecksendung)$  ruecksendung: [#[]$ruecksendung$],
$endif$$if(betreff)$  betreff: [#[]$betreff$],
$endif$$if(bezug)$  bezug: [#[]$bezug$],
$endif$$if(ihr-zeichen)$  ihr-zeichen: [#[]$ihr-zeichen$],
$endif$$if(ihre-nachricht)$  ihre-nachricht: [#[]$ihre-nachricht$],
$endif$$if(unser-zeichen)$  unser-zeichen: [#[]$unser-zeichen$],
$endif$$if(anrede)$  anrede: [#[]$anrede$],
$endif$$if(gruss)$  gruss: [#[]$gruss$],
$endif$$if(unterschrift)$  unterschrift: ($for(unterschrift)$[#[]$unterschrift$],$endfor$),
$endif$$if(unterschrift-bild)$  unterschrift-bild: "$unterschrift-bild$",
$endif$$if(anlagen)$  anlagen: ($for(anlagen)$[#[]$anlagen$],$endfor$),
$endif$$if(verteiler)$  verteiler: ($for(verteiler)$[#[]$verteiler$],$endfor$),
$endif$)

$body$
