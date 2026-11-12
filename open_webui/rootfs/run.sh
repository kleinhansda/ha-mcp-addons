#!/usr/bin/env bash
# Startskript der App: liest die Optionen, übernimmt bei Bedarf einmalig Daten aus
# /config/import und startet dann das unveränderte start.sh von Open WebUI.
set -euo pipefail

# Pfade nur für Tests überschreibbar
DATA=${ADDON_DATA_DIR:-/data}
OPTIONS="$DATA/options.json"
IMPORT=${ADDON_IMPORT_DIR:-/config/import}
BACKEND=${OPEN_WEBUI_BACKEND:-/app/backend}

log() { echo "[open-webui-app] $*"; }
fail() { log "FEHLER: $*"; exit 1; }
opt() { jq -r --arg k "$1" '.[$k] // empty' "$OPTIONS"; }
optb() { [ "$(jq -r --arg k "$1" '.[$k] // false' "$OPTIONS")" = "true" ] && echo True || echo False; }

[ -f "$OPTIONS" ] || fail "$OPTIONS fehlt"

# --- Einmalige Übernahme bestehender Daten --------------------------------
# Inhalt des alten Datenordners (webui.db, uploads/, vector_db/ …) nach
# /addon_configs/<repo>_open_webui/import legen. Übernommen wird nur, solange
# die App noch keine eigene Datenbank hat; danach wird der Ordner umbenannt.
if [ -f "$IMPORT/webui.db" ]; then
  if [ -f "$DATA/webui.db" ]; then
    log "WARNUNG: $IMPORT/webui.db liegt bereit, die App hat aber schon eine Datenbank."
    log "WARNUNG: Nichts übernommen. Zum Überschreiben die App deinstallieren (löscht /data) oder den Import-Ordner entfernen."
  else
    log "Übernehme Daten aus $IMPORT (ohne heruntergeladene Modelle) ..."
    (cd "$IMPORT" && tar --exclude=./cache/embedding --exclude=./cache/whisper --exclude=./.webui_secret_key -cf - .) | (cd "$DATA" && tar -xf -)
    if [ -f "$IMPORT/.webui_secret_key" ] && [ ! -f "$DATA/.webui_secret_key" ]; then
      install -m 600 "$IMPORT/.webui_secret_key" "$DATA/.webui_secret_key"
      log "Schlüssel aus $IMPORT/.webui_secret_key übernommen."
    fi
    check=$(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0])" "$DATA/webui.db" 2>&1 | tail -n 1 || true)
    if [ "$check" != "ok" ]; then
      mv "$DATA/webui.db" "$DATA/webui.db.defekt-$(date +%Y%m%d-%H%M%S)"
      fail "Übernommene webui.db ist beschädigt ($check). Alten Container vor dem Kopieren stoppen und erneut kopieren."
    fi
    done_dir="$(dirname "$IMPORT")/import.erledigt-$(date +%Y%m%d-%H%M%S)"
    mv "$IMPORT" "$done_dir"
    log "Übernahme fertig, Datenbank geprüft. Quelle umbenannt in $(basename "$done_dir")."
  fi
fi

# --- Grundeinstellungen -----------------------------------------------------
export DATA_DIR="$DATA"
WEBUI_URL=$(opt webui_url); WEBUI_URL=${WEBUI_URL%/}
[ -n "$WEBUI_URL" ] || fail "'webui_url' ist Pflicht, z. B. https://ai.example.net"
export WEBUI_URL

# Schlüssel für Sitzungen und verschlüsselte Tokens (u. a. OAuth-Tokens der
# Tool-Server). Muss nach einem Umzug derselbe bleiben, sonst sind alle
# abgemeldet und Tool-Server müssen neu verbunden werden.
key=$(opt webui_secret_key)
if [ -n "$key" ]; then
  export WEBUI_SECRET_KEY="$key"
  log "Schlüssel: aus der Option webui_secret_key"
else
  export WEBUI_SECRET_KEY_FILE="$DATA/.webui_secret_key"
  [ -f "$WEBUI_SECRET_KEY_FILE" ] && log "Schlüssel: $WEBUI_SECRET_KEY_FILE" || log "Schlüssel: wird neu erzeugt in $WEBUI_SECRET_KEY_FILE"
fi
unset key

# --- Login über OIDC (z. B. Pocket ID) ---------------------------------------
oidc_id=$(opt oidc_client_id)
login_form=$(optb login_form)
if [ -n "$oidc_id" ]; then
  oidc_url=$(opt oidc_configuration_url)
  oidc_secret=$(opt oidc_client_secret)
  [ -n "$oidc_url" ] || fail "'oidc_configuration_url' fehlt (Discovery-URL, z. B. https://id.example.net/.well-known/openid-configuration)"
  [ -n "$oidc_secret" ] || fail "'oidc_client_secret' fehlt"
  export OAUTH_CLIENT_ID="$oidc_id"
  export OAUTH_CLIENT_SECRET="$oidc_secret"
  export OPENID_PROVIDER_URL="$oidc_url"
  export OAUTH_PROVIDER_NAME="$(opt oidc_provider_name)"
  export OPENID_REDIRECT_URI="$WEBUI_URL/oauth/oidc/callback"
  export ENABLE_OAUTH_SIGNUP="$(optb oidc_signup)"
  export OAUTH_MERGE_ACCOUNTS_BY_EMAIL="$(optb oidc_merge_by_email)"
  log "OIDC: $OAUTH_PROVIDER_NAME, Callback $OPENID_REDIRECT_URI, Registrierung $ENABLE_OAUTH_SIGNUP"
  unset oidc_secret
elif [ "$login_form" = "False" ]; then
  log "WARNUNG: login_form ist aus, aber kein OIDC eingerichtet. Formular bleibt an, sonst wäre kein Login möglich."
  login_form=True
fi
export ENABLE_LOGIN_FORM="$login_form"

# --- SearXNG (Web-Suche) --------------------------------------------------------
# Läuft im selben Container auf 127.0.0.1:8888 und startet bei einem Absturz neu.
# Engine und URL stehen bei frischer Datenbank über die Umgebung, bei bestehender
# schreibt provision.py sie vor dem Start (Open WebUI liest Umgebungsvariablen nur als
# Vorgabe für Schlüssel, die noch nicht in der Datenbank stehen).
if [ "$(optb searxng)" = "True" ]; then
  (
    set +e
    export SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml
    SEARXNG_SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    export SEARXNG_SECRET
    cd /opt/searxng/src || exit 1
    while true; do
      PYTHONPATH=/opt/searxng/src /opt/searxng/venv/bin/granian --interface wsgi \
        --host 127.0.0.1 --port 8888 --workers 1 searx.webapp:app 2>&1 | sed -u 's/^/[searxng] /'
      echo "[open-webui-app] SearXNG beendet, Neustart in 10 s"
      sleep 10
    done
  ) &
  export ENABLE_WEB_SEARCH=True WEB_SEARCH_ENGINE=searxng
  export SEARXNG_QUERY_URL="http://127.0.0.1:8888/search?q=<query>"
  log "SearXNG: Start auf 127.0.0.1:8888 (Commit $(cut -c1-8 /opt/searxng/COMMIT 2>/dev/null || echo '?'))"
else
  log "SearXNG: aus"
fi

# --- Open Terminal (eigene App) ---------------------------------------------------
# Die App "Open Terminal" läuft in einem eigenen Container, damit Befehle des Modells
# nicht an Datenbank und Schlüssel dieser App kommen. Adresse aus dem eigenen Hostnamen
# (<repo-hash>-open-webui → <repo-hash>-open-terminal), Schlüssel aus der Option.
APP_TERMINAL_KEY=$(opt open_terminal_api_key)
APP_TERMINAL_URL=$(opt open_terminal_url); APP_TERMINAL_URL=${APP_TERMINAL_URL%/}
if [ -n "$APP_TERMINAL_KEY" ] && [ -z "$APP_TERMINAL_URL" ]; then
  host=$(hostname)
  if [ "${host%-open-webui}" != "$host" ]; then
    APP_TERMINAL_URL="http://${host%-open-webui}-open-terminal:8000"
  else
    log "WARNUNG: Adresse von Open Terminal nicht ableitbar (Hostname $host). Option open_terminal_url setzen."
  fi
fi
if [ -n "$APP_TERMINAL_KEY" ] && [ -n "$APP_TERMINAL_URL" ]; then
  TERMINAL_SERVER_CONNECTIONS=$(jq -cn --arg url "$APP_TERMINAL_URL" --arg key "$APP_TERMINAL_KEY" \
    '[{id:"ha-open-terminal",name:"Open Terminal",enabled:true,url:$url,path:"/openapi.json",key:$key,auth_type:"bearer",config:{}}]')
  export TERMINAL_SERVER_CONNECTIONS
  log "Open Terminal: $APP_TERMINAL_URL (nur für Admins, Freigaben im Admin-Bereich unter Integrationen)"
fi
export APP_TERMINAL_KEY APP_TERMINAL_URL

if [ -f "$DATA/webui.db" ]; then
  python3 /usr/local/lib/open-webui-app/provision.py "$DATA/webui.db" || fail "Eintragen von SearXNG/Open Terminal in die Datenbank fehlgeschlagen"
fi
unset APP_TERMINAL_KEY

# --- Zusätzliche Umgebungsvariablen -------------------------------------------
while IFS= read -r line; do
  [ -n "$line" ] || continue
  name=${line%%=*}
  export "$name=${line#*=}"
  log "Zusatzvariable: $name"
done < <(jq -r '.extra_env // [] | .[]' "$OPTIONS")

# --- Eigenes CSS -------------------------------------------------------------
# /addon_configs/<repo>_open_webui/custom.css (in der App /config/custom.css) wird beim Start
# nach build/static kopiert; Open WebUI lädt /static/custom.css auf jeder Seite.
CONFIG=${ADDON_CONFIG_DIR:-/config}
FRONTEND_STATIC=${OPEN_WEBUI_FRONTEND_STATIC:-$BACKEND/../build/static}
if [ -d "$CONFIG" ] && [ ! -e "$CONFIG/custom.css" ]; then
  cat > "$CONFIG/custom.css" <<'CSS'
/* Eigenes CSS für Open WebUI. Wird beim Start der App übernommen (App neu starten).
   Selektoren können sich mit Updates von Open WebUI ändern. */

/* Beispiel: Modell-Icon auf der Startseite eines neuen Chats größer (Standard 2.5rem) */
/*
img[src*="/models/model/profile/image"].rounded-2xl {
  width: 4.5rem !important;
  height: 4.5rem !important;
}
*/
CSS
  log "Vorlage für eigenes CSS angelegt: custom.css im App-Konfigurationsordner"
fi
# Design (Option „design“) zuerst, dann die Chat-Schrift (Option „chat_schrift“), eigenes CSS
# zuletzt, damit es beides überschreiben kann. Die Schriftdateien liegen im Image und werden
# nach build/static/schriften kopiert (ausgeliefert unter /static/schriften/, ohne externe Abrufe).
DESIGNS=${OPEN_WEBUI_DESIGNS:-/usr/local/lib/open-webui-app/designs}
SCHRIFTEN=${OPEN_WEBUI_SCHRIFTEN:-/usr/local/lib/open-webui-app/schriften}
DESIGN=$(opt design); DESIGN=${DESIGN:-standard}
CHAT_SCHRIFT=$(opt chat_schrift); CHAT_SCHRIFT=${CHAT_SCHRIFT:-standard}
if [ -d "$FRONTEND_STATIC" ]; then
  rm -rf "$FRONTEND_STATIC/schriften"
  if [ "$CHAT_SCHRIFT" != standard ]; then
    if [ -f "$SCHRIFTEN/$CHAT_SCHRIFT.css" ] && [ -d "$SCHRIFTEN/$CHAT_SCHRIFT" ]; then
      mkdir -p "$FRONTEND_STATIC/schriften"
      cp -r "$SCHRIFTEN/$CHAT_SCHRIFT" "$FRONTEND_STATIC/schriften/"
    else
      log "WARNUNG: Chat-Schrift $CHAT_SCHRIFT unbekannt"; CHAT_SCHRIFT=standard
    fi
  fi
  {
    if [ "$DESIGN" != standard ]; then
      if [ -f "$DESIGNS/$DESIGN.css" ]; then cat "$DESIGNS/$DESIGN.css"; echo; else log "WARNUNG: Design $DESIGN unbekannt"; fi
    fi
    if [ "$CHAT_SCHRIFT" != standard ]; then cat "$SCHRIFTEN/$CHAT_SCHRIFT.css"; echo; fi
    [ -f "$CONFIG/custom.css" ] && cat "$CONFIG/custom.css"
  } > "$FRONTEND_STATIC/custom.css"
  log "Design: $DESIGN, Chat-Schrift: $CHAT_SCHRIFT, eigenes CSS: $([ -f "$CONFIG/custom.css" ] && echo "$(wc -c < "$CONFIG/custom.css") Bytes" || echo keines)"
fi

log "Starte Open WebUI $(jq -r .version "$BACKEND/../package.json" 2>/dev/null || echo '?') mit Daten in $DATA_DIR, URL $WEBUI_URL"
cd "$BACKEND"
exec bash start.sh
