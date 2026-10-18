# Dienste des Add-ons Netlify MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(netlify)
declare -A PORTS=([netlify]=8080)
declare -A URL_OPTION=([netlify]=external_url)

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  NETLIFY_PERSONAL_ACCESS_TOKEN="$(opt netlify_token)"
  [ -n "$NETLIFY_PERSONAL_ACCESS_TOKEN" ] || fehler "netlify_token ist leer"
  export NETLIFY_PERSONAL_ACCESS_TOKEN
}

# Werte für den Selbsttest: Die Tool-Liste kommt ohne Token.
selftest_setup() {
  unset NETLIFY_PERSONAL_ACCESS_TOKEN
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
service_cmd() {
  CMD=(netlify-mcp)
}
