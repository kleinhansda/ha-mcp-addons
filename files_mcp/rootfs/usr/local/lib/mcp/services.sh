# Dienste des Add-ons Files MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(files)
declare -A PORTS=([files]=8080)
declare -A URL_OPTION=([files]=external_url)

FILES_SERVER=/usr/local/lib/mcp/files_mcp.py

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  FILES_ROOT="$(opt root)"
  FILES_ROOT="${FILES_ROOT%/}"
  [[ "$FILES_ROOT" =~ ^/share(/[^[:space:]]+)?$ ]] || fehler "root muss /share oder ein Ordner darunter sein"
  mkdir -p "$FILES_ROOT"
  export FILES_READ_ONLY="$(opt read_only)"
  export FILES_PROTECTED="$(opt protected)"
  local mb; mb="$(opt max_mb)"
  export FILES_MAX_BYTES=$(( ${mb:-10} * 1024 * 1024 ))
  log "Wurzel: $FILES_ROOT, nur lesen: ${FILES_READ_ONLY:-false}, geschützt: ${FILES_PROTECTED:-nichts}, Grenze: ${mb:-10} MB"
  [ "$FILES_ROOT" = /share ] && log "Achtung: Wurzel ist ganz /share, alle Daten anderer Apps darunter sind erreichbar"
  return 0
}

# Werte für den Selbsttest: eigener leerer Ordner.
selftest_setup() {
  FILES_ROOT="$SELFTEST_DIR/root"
  mkdir -p "$FILES_ROOT"
  export FILES_READ_ONLY=false FILES_PROTECTED=.obsidian
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(python3 "$FILES_SERVER" "$FILES_ROOT")
}
