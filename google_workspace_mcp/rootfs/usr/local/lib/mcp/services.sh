# Dienste des Add-ons Google Workspace MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(google)
declare -A PORTS=([google]=8080)
declare -A URL_OPTION=([google]=external_url)

GWS_PY=/opt/venv/bin/python

# Rechte aus den Optionen in die Syntax von workspace-mcp (--permissions) übersetzen.
gws_permissions() {
  local p=()
  case "$1" in lesen) p+=(gmail:readonly) ;; entwuerfe) p+=(gmail:drafts) ;; esac
  case "$2" in lesen) p+=(calendar:readonly) ;; schreiben) p+=(calendar:full) ;; esac
  case "$3" in lesen) p+=(drive:readonly) ;; schreiben) p+=(drive:full) ;; esac
  echo "${p[*]}"
}

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  export MCP_SINGLE_USER_MODE=1
  export USER_GOOGLE_EMAIL="$(opt google_email)"
  export GOOGLE_OAUTH_CLIENT_ID="$(opt oauth_client_id)"
  export GOOGLE_OAUTH_CLIENT_SECRET="$(opt oauth_client_secret)"
  export WORKSPACE_MCP_CREDENTIALS_DIR="$DATA/google-auth/credentials"
  export GWS_PENDING="$DATA/google-auth/anmeldung_offen.json"
  WORKSPACE_MCP_PERMISSIONS="$(gws_permissions "$(opt gmail)" "$(opt calendar)" "$(opt drive)")"
  [ -n "$WORKSPACE_MCP_PERMISSIONS" ] || fehler "Gmail, Kalender und Drive sind alle aus"
  export WORKSPACE_MCP_PERMISSIONS
  export WORKSPACE_MCP_TOOL_TIER="$(opt tool_tier)"
  # Die eigene Anmeldung von workspace-mcp braucht einen Rückruf auf localhost:8000, das
  # übernimmt hier gws_auth.py über die Option auth_response.
  export WORKSPACE_MCP_DISABLED_TOOLS=start_google_auth
  export ALLOWED_FILE_DIRS="$(opt upload_dirs)"
  export WORKSPACE_ATTACHMENT_DIR="$(opt download_dir)"
  [ -n "$WORKSPACE_ATTACHMENT_DIR" ] && mkdir -p "$WORKSPACE_ATTACHMENT_DIR"
  mkdir -p "$DATA/google-auth"; chmod 700 "$DATA/google-auth"
  log "Rechte: $WORKSPACE_MCP_PERMISSIONS, Werkzeugumfang: $WORKSPACE_MCP_TOOL_TIER"
  GWS_AUTH_RESPONSE="$(opt auth_response)" "$GWS_PY" /usr/local/lib/mcp/gws_auth.py \
    || log "Achtung: ohne gültige Anmeldung melden alle Werkzeuge einen Fehler"
  return 0
}

# Werte für den Selbsttest: tools/list braucht keine Anmeldung.
selftest_setup() {
  export MCP_SINGLE_USER_MODE=1 USER_GOOGLE_EMAIL=selftest@example.com
  export GOOGLE_OAUTH_CLIENT_ID=selftest.apps.googleusercontent.com GOOGLE_OAUTH_CLIENT_SECRET=selftest
  export WORKSPACE_MCP_CREDENTIALS_DIR="$HOME/credentials" WORKSPACE_ATTACHMENT_DIR="$HOME/downloads"
  export WORKSPACE_MCP_PERMISSIONS="gmail:readonly calendar:full drive:full" WORKSPACE_MCP_TOOL_TIER=core
  export WORKSPACE_MCP_DISABLED_TOOLS=start_google_auth
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(/opt/venv/bin/workspace-mcp --single-user)
}
