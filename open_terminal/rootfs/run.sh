#!/usr/bin/env bash
# Startskript der App: Schlüssel aus der Option oder einmalig erzeugt (in /data),
# Home-Verzeichnis unter /data, dann Start als "user" über entrypoint.sh des Images.
set -euo pipefail

DATA=${ADDON_DATA_DIR:-/data}
OPTIONS="$DATA/options.json"
log() { echo "[open-terminal-app] $*"; }
fail() { log "FEHLER: $*"; exit 1; }
[ -f "$OPTIONS" ] || fail "$OPTIONS fehlt"

key=$(jq -r '.api_key // empty' "$OPTIONS")
if [ -z "$key" ]; then
  if [ ! -s "$DATA/api_key" ]; then
    (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$DATA/api_key")
    log "Neuer API-Schlüssel erzeugt."
  fi
  key=$(cat "$DATA/api_key")
  log "API-Schlüssel (in der App Open WebUI als open_terminal_api_key eintragen): $key"
else
  log "API-Schlüssel: aus der Option api_key"
fi

# Home nach /data: Dateien, installierte pip-/npm-Pakete und Einstellungen bleiben bei
# Updates erhalten. Beim ersten Start mit dem Inhalt aus dem Image füllen.
HOME_DIR="$DATA/home"
if [ ! -d "$HOME_DIR" ]; then
  mkdir -p "$HOME_DIR"
  cp -a /home/user/. "$HOME_DIR/" 2>/dev/null || true
  chown -R user:user "$HOME_DIR"
  log "Home-Verzeichnis angelegt: $HOME_DIR"
fi
chown user:user "$HOME_DIR"
if [ ! -L /home/user ]; then
  rm -rf /home/user
  ln -s "$HOME_DIR" /home/user
fi

export OPEN_TERMINAL_API_KEY="$key"
unset key
log "Starte Open Terminal $(python3 -c 'import importlib.metadata as m; print(m.version("open-terminal"))' 2>/dev/null || echo '?') auf Port 8000"
cd /home/user
exec runuser -u user -- /app/entrypoint.sh run --host 0.0.0.0 --port 8000
