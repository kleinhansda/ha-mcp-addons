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

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  WORK="$(opt work_dir)"
  PDFCRAFT_COMPACT="$(opt pdfcraft_compact)"
  [ -n "$WORK" ] || fehler "work_dir ist leer"
  mkdir -p "$WORK"
  log "Arbeitsordner: $WORK"
}

# Werte für den Selbsttest (ohne Add-on-Optionen).
selftest_setup() {
  WORK="$SELFTEST_DIR/work"
  PDFCRAFT_COMPACT=true
  mkdir -p "$WORK"
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
