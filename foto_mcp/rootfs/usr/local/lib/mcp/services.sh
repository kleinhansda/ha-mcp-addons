# Dienste des Add-ons Foto MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(foto)
declare -A PORTS=([foto]=8080)
declare -A URL_OPTION=([foto]=external_url)

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  WORK="$(opt work_dir)"
  [ -n "$WORK" ] || fehler "work_dir ist leer"
  mkdir -p "$WORK"
  log "Arbeitsordner: $WORK"
}

# Werte für den Selbsttest (ohne Add-on-Optionen).
selftest_setup() {
  WORK="$SELFTEST_DIR/work"
  mkdir -p "$WORK"
}

# Funktionstest auf der jeweiligen Architektur: Schräglage, Gesichtsmodell, Job, Pfadgrenze.
selftest_extra() {
  /opt/venv/bin/python /opt/foto/selbsttest.py "$WORK" 2>/dev/null
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(/opt/venv/bin/python /opt/foto/server.py --root "$WORK")
}
