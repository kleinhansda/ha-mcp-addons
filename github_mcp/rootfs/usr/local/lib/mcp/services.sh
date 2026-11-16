# Dienste des Add-ons GitHub MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(github)
declare -A PORTS=([github]=8080)
declare -A URL_OPTION=([github]=external_url)

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  GITHUB_PERSONAL_ACCESS_TOKEN="$(opt github_token)"
  [ -n "$GITHUB_PERSONAL_ACCESS_TOKEN" ] || fehler "github_token ist leer"
  export GITHUB_PERSONAL_ACCESS_TOKEN
  TOOLSETS="$(opt toolsets)"
  READ_ONLY="$(opt read_only)"
  EXCLUDE_TOOLS="$(opt exclude_tools)"
  GH_HOST="$(opt gh_host)"
  log "Toolsets: ${TOOLSETS:-Standard}, nur lesen: $READ_ONLY, gesperrt: ${EXCLUDE_TOOLS:-keine}"
}

# Werte für den Selbsttest: Die Tool-Liste kommt ohne gültigen Token.
selftest_setup() {
  export GITHUB_PERSONAL_ACCESS_TOKEN=selftest
  TOOLSETS=all
  READ_ONLY=false
  EXCLUDE_TOOLS=""
  GH_HOST=""
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(github-mcp-server stdio)
  if [ -n "$TOOLSETS" ]; then CMD+=("--toolsets=$TOOLSETS"); fi
  if [ "$READ_ONLY" = true ]; then CMD+=(--read-only); fi
  if [ -n "$EXCLUDE_TOOLS" ]; then CMD+=("--exclude-tools=$EXCLUDE_TOOLS"); fi
  if [ -n "$GH_HOST" ]; then CMD+=("--gh-host=$GH_HOST"); fi
}
