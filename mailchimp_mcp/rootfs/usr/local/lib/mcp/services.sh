# Dienste des Add-ons Mailchimp MCP. Wird von run.sh und mcp-selftest eingebunden.

SERVICES=(mailchimp)
declare -A PORTS=([mailchimp]=8080)
declare -A URL_OPTION=([mailchimp]=external_url)

# Werkzeuge je Umfang (Namen aus mailchimp-mcp, Risikostufe "read" bzw. Entwürfe ohne Versand).
MC_LESEN="ping,get_account_info,list_audiences,get_audience_details,get_audience_growth_history,list_audience_members,search_members,get_member_activity,get_member_tags,list_segments,list_campaigns,search_campaigns,get_campaign_details,get_campaign_content,get_campaign_report,get_campaign_click_details,get_open_details,get_campaign_send_checklist,list_templates,get_template"
MC_ENTWUERFE="create_campaign,update_campaign,set_campaign_content,replicate_campaign,send_test_email"

# Liest die Add-on-Optionen (nur in run.sh, dort gibt es opt, log und fehler).
service_setup() {
  export MAILCHIMP_API_KEY="$(opt api_key)"
  local scope extra
  scope="$(opt scope)"; extra="$(opt extra_tools | tr -d ' ')"
  case "$scope" in
    alle)      MAILCHIMP_TOOLS=""; MAILCHIMP_READ_ONLY=false
               log "Umfang: alle Werkzeuge, auch Versand und Löschen" ;;
    entwuerfe) MAILCHIMP_TOOLS="$MC_LESEN,$MC_ENTWUERFE"; MAILCHIMP_READ_ONLY=false
               log "Umfang: lesen und Entwürfe (kein Versand, kein Löschen)" ;;
    *)         MAILCHIMP_TOOLS="$MC_LESEN"; MAILCHIMP_READ_ONLY=true
               log "Umfang: nur lesen" ;;
  esac
  if [ -n "$extra" ] && [ -n "$MAILCHIMP_TOOLS" ]; then
    MAILCHIMP_TOOLS="$MAILCHIMP_TOOLS,$extra"; log "Weitere Werkzeuge: $extra"
  fi
  export MAILCHIMP_TOOLS MAILCHIMP_READ_ONLY
  export MAILCHIMP_DRY_RUN="$(opt dry_run)"
  [ "$MAILCHIMP_DRY_RUN" = true ] && log "Probelauf: schreibende Werkzeuge rufen Mailchimp nicht auf"
  if [ -z "$MAILCHIMP_API_KEY" ]; then
    log "Achtung: kein API-Schlüssel eingetragen, alle Werkzeuge melden einen Fehler"
    return 0
  fi
  case "$MAILCHIMP_API_KEY" in *-*) ;; *) log "Achtung: API-Schlüssel ohne Rechenzentrum (…-us21)";; esac
  local code
  code="$(python3 - <<'PY'
import base64, os, urllib.request, urllib.error
k = os.environ["MAILCHIMP_API_KEY"]; dc = k.rsplit("-", 1)[-1] if "-" in k else "us1"
req = urllib.request.Request(f"https://{dc}.api.mailchimp.com/3.0/ping",
                             headers={"Authorization": "Basic " + base64.b64encode(b"x:" + k.encode()).decode()})
try:
    print(urllib.request.urlopen(req, timeout=10).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print("nicht erreichbar:", getattr(e, "reason", e))
PY
)"
  case "$code" in
    200) log "Mailchimp erreichbar, API-Schlüssel gültig" ;;
    401|403) log "Achtung: Mailchimp lehnt den API-Schlüssel ab ($code)" ;;
    *) log "Achtung: Mailchimp antwortet nicht wie erwartet ($code)" ;;
  esac
  return 0
}

# Werte für den Selbsttest: tools/list braucht keine Verbindung zu Mailchimp.
selftest_setup() {
  export MAILCHIMP_API_KEY=selftest-us1 MAILCHIMP_READ_ONLY=true MAILCHIMP_TOOLS="$MC_LESEN"
}

# service_cmd <dienst>: setzt das Array CMD auf den Startbefehl.
# mailchimp_plus.py = mailchimp-mcp plus Suchen/Ersetzen im Kampagnen-HTML und Bild-Upload aus /share.
service_cmd() {
  CMD=(/opt/venv/bin/python3 /usr/local/lib/mcp/mailchimp_plus.py)
}
