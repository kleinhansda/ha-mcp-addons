# shellcheck shell=bash disable=SC2034  # wird von run.sh und artcraft-selftest eingebunden
# Gemeinsame Definitionen für run.sh und artcraft-selftest.
# Hier steht, mit welchen Optionen jede App ihren MCP-Server startet.
# Ändert ein neues Release eine Option, schlägt der Selbsttest im Build fehl.

APPS=(vectorcraft photocraft pdfcraft cadcraft wordcraft deckcraft gridcraft figcraft craft-anything)

declare -A PORTS=(
  [vectorcraft]=8081
  [photocraft]=8082
  [pdfcraft]=8083
  [cadcraft]=8085
  [wordcraft]=8086
  [deckcraft]=8087
  [gridcraft]=8088
  [figcraft]=8089
  [craft-anything]=8090
)

# Interner Zugriff ohne Anmeldung (internal_apps): je App Port + 1000, also 9081 bis 9090.
# Diese Ports stehen bewusst nicht in config.yaml und werden nie auf den Host gelegt.
declare -A INTERNAL_PORTS=()
for _app in "${!PORTS[@]}"; do INTERNAL_PORTS[$_app]=$(( PORTS[$_app] + 1000 )); done
unset _app

# schriften_einrichten <arbeitsordner> <kopieren>: Das Image bringt offene Schriften unter
# /usr/share/fonts mit. VectorCraft und PhotoCraft finden sie dort. PdfCraft sucht nur innerhalb
# von --root und folgt keinen Symlinks, deshalb liegen Kopien in <arbeitsordner>/fonts/standard
# (kopieren=true, Option fonts_to_work). Eigene Schriften kommen nach <arbeitsordner>/fonts,
# eine fontconfig-Datei macht sie auch VectorCraft, PhotoCraft und den übrigen Apps bekannt.
schriften_einrichten() {
  local work=$1 kopieren=$2 quelle="${FONTS_SRC:-/usr/share/fonts}"
  local ziel="$work/fonts/standard" conf="$HOME/artcraft-fonts.conf"
  mkdir -p "$work/fonts"
  if [ "$kopieren" = true ]; then
    mkdir -p "$ziel"
    # -p übernimmt die Zeit aus dem Image, -u kopiert nur neuere: neue Image-Versionen kommen an.
    find "$quelle" -type f \( -name '*.ttf' -o -name '*.otf' \) \
      -exec cp -p -u -t "$ziel" {} +
  fi
  printf '<?xml version="1.0"?>\n<fontconfig>\n  <dir>%s</dir>\n  <dir>%s</dir>\n</fontconfig>\n' \
    "$quelle" "$work/fonts" > "$conf"
  export FONTCONFIG_FILE="$conf"
}

# app_cmd <app> <arbeitsordner>: setzt das Array CMD auf den Startbefehl der App.
# PDFCRAFT_COMPACT=false schaltet bei PdfCraft die kompakte Tool-Liste ab.
# WordCraft, DeckCraft und FigCraft begrenzen den Dateizugriff der Tools auf den
# Arbeitsordner (--automation-read-root/--write-root). CADCraft, GridCraft und
# Craft Anything bieten diese Optionen nicht, ihre Tools sind nicht begrenzt.
app_cmd() {
  local app=$1 work=$2
  case "$app" in
    vectorcraft)
      CMD=(vectorcraft-cli mcp --headless --automation-read-root "$work" --automation-write-root "$work") ;;
    photocraft)
      CMD=(photocraft-cli mcp --automation-read-root "$work" --automation-write-root "$work") ;;
    pdfcraft)
      CMD=(pdfcraft-cli mcp --root "$work")
      if [ "${PDFCRAFT_COMPACT:-true}" = true ]; then CMD+=(--compact); fi ;;
    cadcraft)
      CMD=(cadcraft-cli mcp) ;;
    wordcraft)
      CMD=(wordcraft-cli mcp --automation-read-root "$work" --automation-write-root "$work") ;;
    deckcraft)
      CMD=(deckcraft-cli mcp --automation-read-root "$work" --automation-write-root "$work") ;;
    gridcraft)
      CMD=(gridcraft-cli mcp) ;;
    figcraft)
      CMD=(figcraft-cli mcp --automation-read-root "$work" --automation-write-root "$work") ;;
    craft-anything)
      CMD=(craft-anything-cli mcp) ;;
    *)
      echo "Unbekannte App: $app" >&2; return 1 ;;
  esac
}
