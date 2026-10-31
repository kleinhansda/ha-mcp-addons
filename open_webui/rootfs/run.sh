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

# --- Zusätzliche Umgebungsvariablen -------------------------------------------
while IFS= read -r line; do
  [ -n "$line" ] || continue
  name=${line%%=*}
  export "$name=${line#*=}"
  log "Zusatzvariable: $name"
done < <(jq -r '.extra_env // [] | .[]' "$OPTIONS")

log "Starte Open WebUI $(jq -r .version "$BACKEND/../package.json" 2>/dev/null || echo '?') mit Daten in $DATA_DIR, URL $WEBUI_URL"
cd "$BACKEND"
exec bash start.sh
