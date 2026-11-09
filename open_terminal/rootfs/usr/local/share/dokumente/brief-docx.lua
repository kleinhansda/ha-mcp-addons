-- Pandoc-Filter für Briefe und Anschreiben im Word-Format (dokument -f docx).
-- Setzt Kopf, Anschrift, Infoblock, Betreff, Anrede, Gruß, Unterschrift und Anlagen aus dem
-- YAML-Kopf als Absätze mit den Formatvorlagen aus referenz-<stil>.docx. Die exakte DIN-Lage
-- (Fensterumschlag) liefert nur das PDF; Word gibt die Reihenfolge und Abstände nach DIN 5008 wieder.

local function txt(v)
  if v == nil then return nil end
  if type(v) == "table" and v.t == nil and #v > 0 and type(v[1]) ~= "string" then return v end
  return pandoc.utils.stringify(v)
end

local function para(style, inlines)
  if type(inlines) == "string" then inlines = { pandoc.Str(inlines) } end
  return pandoc.Div({ pandoc.Para(inlines) }, { ["custom-style"] = style })
end

local function zeilen(liste)
  local out = {}
  if liste == nil then return out end
  if pandoc.utils.type(liste) ~= "List" then return { pandoc.utils.stringify(liste) } end
  for _, z in ipairs(liste) do table.insert(out, pandoc.utils.stringify(z)) end
  return out
end

local function mehrzeilig(style, liste)
  local inl = {}
  for i, z in ipairs(liste) do
    if i > 1 then table.insert(inl, pandoc.LineBreak()) end
    table.insert(inl, pandoc.Str(z))
  end
  return para(style, inl)
end

function Pandoc(doc)
  local m = doc.meta
  local a = m.absender or {}
  local name = a.name and pandoc.utils.stringify(a.name) or ""
  local adresse, kontakt = {}, {}
  for _, k in ipairs({ "strasse", "ort" }) do if a[k] then table.insert(adresse, pandoc.utils.stringify(a[k])) end end
  for _, k in ipairs({ "telefon", "mail", "web" }) do if a[k] then table.insert(kontakt, pandoc.utils.stringify(a[k])) end end
  local kopf = {}
  if name ~= "" then table.insert(kopf, para("Briefkopf", name)) end
  local alle = {}
  for _, x in ipairs(adresse) do table.insert(alle, x) end
  for _, x in ipairs(kontakt) do table.insert(alle, x) end
  if #alle > 0 then table.insert(kopf, para("Briefkopf Kontakt", table.concat(alle, "  ·  "))) end
  local rueck = m.ruecksendung and pandoc.utils.stringify(m.ruecksendung)
  if not rueck and name ~= "" then rueck = table.concat({ name, table.unpack(adresse) }, ", ") end
  if rueck then table.insert(kopf, para("Ruecksendung", rueck)) end
  local empf = zeilen(m.empfaenger)
  if #empf > 0 then table.insert(kopf, mehrzeilig("Anschrift", empf)) end
  local info = {}
  for _, p in ipairs({ { "ihr-zeichen", "Ihr Zeichen" }, { "ihre-nachricht", "Ihre Nachricht vom" },
                       { "unser-zeichen", "Unser Zeichen" } }) do
    if m[p[1]] then table.insert(info, p[2] .. ": " .. pandoc.utils.stringify(m[p[1]])) end
  end
  local datum = m.datum and pandoc.utils.stringify(m.datum) or os.date("%d.%m.%Y")
  table.insert(info, datum)
  table.insert(kopf, mehrzeilig("Infoblock", info))
  if m.betreff then table.insert(kopf, para("Betreff", pandoc.utils.stringify(m.betreff))) end
  if m.anrede then table.insert(kopf, pandoc.Para({ pandoc.Str(pandoc.utils.stringify(m.anrede)) })) end

  local fuss = {}
  local gruss = m.gruss and pandoc.utils.stringify(m.gruss) or "Mit freundlichen Grüßen"
  table.insert(fuss, para("Gruss", gruss))
  local u = zeilen(m.unterschrift)
  if #u == 0 and name ~= "" then u = { name } end
  if #u > 0 then table.insert(fuss, mehrzeilig("Anschrift", u)) end
  local anl = zeilen(m.anlagen)
  if #anl > 0 then
    table.insert(fuss, para("Anlagen", #anl > 1 and "Anlagen" or "Anlage"))
    table.insert(fuss, mehrzeilig("Anschrift", anl))
  end
  local bl = {}
  for _, b in ipairs(kopf) do table.insert(bl, b) end
  for _, b in ipairs(doc.blocks) do table.insert(bl, b) end
  for _, b in ipairs(fuss) do table.insert(bl, b) end
  -- Titel nicht als Word-Titel ausgeben
  m.title = nil
  return pandoc.Pandoc(bl, m)
end
