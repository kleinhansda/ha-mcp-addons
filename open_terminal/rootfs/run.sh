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
# Eigene R-Bibliothek im Home (R_LIBS_USER in /etc/R/Renviron.site): install.packages()
# landet hier und bleibt bei Updates erhalten.
if [ ! -d "$HOME_DIR/R/library" ]; then
  mkdir -p "$HOME_DIR/R/library"
  chown -R user:user "$HOME_DIR/R"
fi
if [ ! -L /home/user ]; then
  rm -rf /home/user
  ln -s "$HOME_DIR" /home/user
fi

# Arbeitsordner unter /share (gemeinsam mit ArtCraft und Foto MCP) als ~/work.
# inbox/ für Eingänge, out/ für Ergebnisse; das Aufräumen übernimmt Home Assistant.
WORK=$(jq -r '.work_dir // empty' "$OPTIONS")
LINK="$HOME_DIR/work"
if [ -n "$WORK" ]; then
  mkdir -p "$WORK/inbox" "$WORK/out"
  # Rechte für "user", auch als Vorgabe für später angelegte Dateien. Ohne ACL-Unterstützung
  # gehören inbox/ und out/ dann "user"; fremde Dateien bleiben lesbar und löschbar.
  if setfacl -R -m u:user:rwX -m d:u:user:rwX "$WORK" 2>/dev/null; then
    log "Arbeitsordner: $WORK als ~/work (Rechte per ACL)"
  else
    chown -R user:user "$WORK/inbox" "$WORK/out"
    chmod -R u+rwX "$WORK/inbox" "$WORK/out"
    log "Arbeitsordner: $WORK als ~/work (ohne ACL, nur inbox/ und out/ gehören user)"
  fi
  if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    ln -sfn "$WORK" "$LINK"
    chown -h user:user "$LINK"
  else
    log "WARNUNG: $LINK existiert und ist kein Link, nicht ersetzt"
  fi
else
  [ -L "$LINK" ] && rm -f "$LINK"
  log "Arbeitsordner: aus (work_dir leer)"
fi

export OPEN_TERMINAL_API_KEY="$key"
unset key SUPERVISOR_TOKEN HASSIO_TOKEN
log "Starte Open Terminal $(python3 -c 'import importlib.metadata as m; print(m.version("open-terminal"))' 2>/dev/null || echo '?') auf Port 8000"
cd /home/user
exec runuser -u user -- /app/entrypoint.sh run --host 0.0.0.0 --port 8000
