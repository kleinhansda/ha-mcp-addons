# Dienste des Add-ons Paperless MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(paperless)
declare -A PORTS=([paperless]=8080)
declare -A URL_OPTION=([paperless]=external_url)

PAPERLESS_SERVER=/usr/local/lib/mcp/paperless_mcp.py

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  export PAPERLESS_URL="$(opt paperless_url)"
  export PAPERLESS_TOKEN="$(opt paperless_token)"
  export PAPERLESS_PUBLIC_URL="$(opt public_ui_url)"
  export PAPERLESS_READ_ONLY="$(opt read_only)"
  export PAPERLESS_UPLOAD_ROOT=/share
  [ -n "$PAPERLESS_TOKEN" ] || log "Achtung: kein API-Token eingetragen, alle Werkzeuge melden einen Fehler"
  local code
  code="$(python3 - <<'PY'
import os, urllib.request, urllib.error
req = urllib.request.Request(os.environ["PAPERLESS_URL"].rstrip("/") + "/api/tags/?page_size=1",
                             headers={"Authorization": "Token " + os.environ.get("PAPERLESS_TOKEN", "")})
try:
    print(urllib.request.urlopen(req, timeout=10).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print("nicht erreichbar:", getattr(e, "reason", e))
PY
)"
  case "$code" in
    200) log "Paperless $PAPERLESS_URL erreichbar, Token gültig" ;;
    401|403) log "Achtung: Paperless $PAPERLESS_URL lehnt das Token ab ($code)" ;;
    *) log "Achtung: Paperless $PAPERLESS_URL antwortet nicht wie erwartet ($code)" ;;
  esac
  log "Nur lesen: ${PAPERLESS_READ_ONLY:-true}"
  return 0
}

# Werte für den Selbsttest: tools/list braucht keine Verbindung zu Paperless.
selftest_setup() {
  export PAPERLESS_URL=http://127.0.0.1:9 PAPERLESS_TOKEN=selftest PAPERLESS_READ_ONLY=false
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(python3 "$PAPERLESS_SERVER")
}
