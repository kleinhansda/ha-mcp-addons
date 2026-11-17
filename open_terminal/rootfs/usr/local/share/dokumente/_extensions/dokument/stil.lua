-- Quarto-Filter der Erweiterung „dokument“ für Word und HTML.
-- HTML: CSS des Stils (persoenlich.css oder hannesbraeu.css) in den Kopf, Seitentitel setzen.
-- Berichte, Notizen, Reiseberichte: deutsche Schlüssel (untertitel, autor, datum) auf die
-- Standardfelder abbilden, damit Titelblock und Word-Formatvorlagen sie zeigen.

local function lesen(pfad)
  local f = io.open(pfad, "r")
  if not f then return nil end
  local t = f:read("a"); f:close(); return t
end

function Meta(m)
  local stil = m.stil and pandoc.utils.stringify(m.stil) or "persoenlich"
  local art = m.art and pandoc.utils.stringify(m.art) or "bericht"
  if quarto.doc.is_format("html") then
    local css = lesen(quarto.utils.resolve_path(stil .. ".css"))
    if css then quarto.doc.include_text("in-header", "<style>\n" .. css .. "\n</style>") end
    if not m.pagetitle then
      m.pagetitle = m.title or m.betreff or pandoc.MetaString(art)
    end
  end
  if art ~= "brief" and art ~= "anschreiben" then
    if m.untertitel and not m.subtitle then m.subtitle = m.untertitel end
    if m.autor and not m.author then m.author = m.autor end
    if m.datum and not m.date then m.date = m.datum end
  end
  return m
end
