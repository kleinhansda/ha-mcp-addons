# Dienste des Add-ons ArtCraft MCP. Wird von run.sh und mcp-selftest eingebunden.
# Hier steht, mit welchen Optionen jede App ihren MCP-Server startet. Ändert ein neues
# Release eine Option, schlägt der Selbsttest im Build fehl.

SERVICES=(vectorcraft photocraft pdfcraft)

declare -A PORTS=(
  [vectorcraft]=8081
  [photocraft]=8082
  [pdfcraft]=8083
)

declare -A URL_OPTION=(
  [vectorcraft]=vectorcraft_url
  [photocraft]=photocraft_url
  [pdfcraft]=pdfcraft_url
)

# Schriften: Das Image bringt offene Schriften unter /usr/share/fonts mit. VectorCraft und
# PhotoCraft finden sie dort. PdfCraft sucht nur innerhalb von --root und folgt keinen
# Symlinks, deshalb liegen Kopien in $WORK/fonts/standard. Eigene Schriften kommen nach
# $WORK/fonts, eine fontconfig-Datei macht sie auch VectorCraft und PhotoCraft bekannt.
schriften_einrichten() {
  local kopieren=$1 quelle="${FONTS_SRC:-/usr/share/fonts}" ziel="$WORK/fonts/standard" conf="$HOME/artcraft-fonts.conf"
  mkdir -p "$WORK/fonts"
  if [ "$kopieren" = true ]; then
    mkdir -p "$ziel"
    # -p übernimmt die Zeit aus dem Image, -u kopiert nur neuere: neue Image-Versionen kommen an.
    find "$quelle" -type f \( -name '*.ttf' -o -name '*.otf' \) \
      -exec cp -p -u -t "$ziel" {} +
  fi
  printf '<?xml version="1.0"?>\n<fontconfig>\n  <dir>%s</dir>\n  <dir>%s</dir>\n</fontconfig>\n' \
    "$quelle" "$WORK/fonts" > "$conf"
  export FONTCONFIG_FILE="$conf"
}

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  WORK="$(opt work_dir)"
  PDFCRAFT_COMPACT="$(opt pdfcraft_compact)"
  [ -n "$WORK" ] || fehler "work_dir ist leer"
  mkdir -p "$WORK"
  log "Arbeitsordner: $WORK"
  schriften_einrichten "$(opt fonts_to_work)"
  log "Schriften: $(find "$WORK/fonts" -type f \( -name '*.ttf' -o -name '*.otf' \) | wc -l) Dateien in $WORK/fonts"
}

# Werte für den Selbsttest (ohne Add-on-Optionen).
selftest_setup() {
  WORK="$SELFTEST_DIR/work"
  PDFCRAFT_COMPACT=true
  mkdir -p "$WORK"
  schriften_einrichten true
}

# Zusätzliche Prüfungen im Selbsttest (von mcp-selftest aufgerufen, falls vorhanden).
# PdfCraft muss Schriften finden und eine davon in eine PDF einbetten können.
selftest_extra() {
  local n doc="$WORK/schrifttest.pdf" font rc=0
  n="$(pdfcraft-cli run text_font_files --root "$WORK" 2>/dev/null \
    | jq -r '.. | .fonts? // empty | length' | head -n1)"
  if [[ "$n" =~ ^[0-9]+$ ]] && (( n > 0 )); then
    echo "ok    pdfcraft: $n Schriften gefunden"
  else
    echo "FEHLER pdfcraft: keine Schriften gefunden (text_font_files)"; return 1
  fi
  font="$(find "$WORK/fonts/standard" -name 'DejaVuSans.ttf' | head -n1)"
  jq -n --arg font "$font" --arg out "$doc" '[
    {tool: "doc_create", args: {from: "blank", pages: 1}},
    {tool: "page_add_text", args: {doc: 1, page: 1, at: [72, 72], text: "x", size: 12}},
    {tool: "text_font_import", args: {doc: 1, page: 1, path: $font}},
    {tool: "text_edit", args: {doc: 1, page: 1, paragraph: 1, text: "Grüße ÄÖÜ €", font_resource: "PCFull0"}},
    {tool: "doc_save", args: {doc: 1, path: $out}},
    {tool: "doc_open", args: {path: $out}},
    {tool: "text_fonts", args: {doc: 2, page: 1}}
  ]' > "$WORK/schrifttest.json"
  if pdfcraft-cli run --script "$WORK/schrifttest.json" --root "$WORK" --report 2>/dev/null \
      | jq -e '.ok and (.steps[-1].result[0].fonts | any(.font == "DejaVuSans" and .preview_only == false))' >/dev/null; then
    echo "ok    pdfcraft: Schrift eingebettet"
  else
    echo "FEHLER pdfcraft: Schrift ließ sich nicht einbetten"; rc=1
  fi
  return $rc
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  case "$1" in
    vectorcraft)
      CMD=(vectorcraft-cli mcp --headless --automation-read-root "$WORK" --automation-write-root "$WORK") ;;
    photocraft)
      CMD=(photocraft-cli mcp --automation-read-root "$WORK" --automation-write-root "$WORK") ;;
    pdfcraft)
      CMD=(pdfcraft-cli mcp --root "$WORK")
      if [ "$PDFCRAFT_COMPACT" = true ]; then CMD+=(--compact); fi ;;
    *)
      echo "Unbekannter Dienst: $1" >&2; return 1 ;;
  esac
}
