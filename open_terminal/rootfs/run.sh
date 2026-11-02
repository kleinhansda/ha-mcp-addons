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

# GitHub-Zugang (optional): Token nur als Umgebungsvariable GH_TOKEN, nie in eine Datei.
# gh liest GH_TOKEN direkt; git bekommt einen Credential-Helper für https://github.com,
# der GH_TOKEN erst beim Aufruf ausliest. In ~/.gitconfig steht also kein Token.
git_user() { runuser -u user -- env HOME=/home/user git "$@"; }
HELPER_KEY='credential.https://github.com.helper'
gh_token=$(jq -r '.github_token // empty' "$OPTIONS")
if command -v git >/dev/null 2>&1; then
  git_user config --global --unset-all "$HELPER_KEY" 2>/dev/null || true
  if [ -n "$gh_token" ]; then
    export GH_TOKEN="$gh_token"
    git_user config --global --add "$HELPER_KEY" ''
    git_user config --global --add "$HELPER_KEY" \
      '!f() { test "$1" = get || exit 0; echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
    log "GitHub: Token gesetzt (GH_TOKEN; git über HTTPS, gh)"
  else
    log "GitHub: kein Token (Option github_token leer)"
  fi
else
  log "WARNUNG: git nicht gefunden, GitHub-Zugang nicht eingerichtet"
fi
unset gh_token

export OPEN_TERMINAL_API_KEY="$key"
unset key SUPERVISOR_TOKEN HASSIO_TOKEN
log "Starte Open Terminal $(python3 -c 'import importlib.metadata as m; print(m.version("open-terminal"))' 2>/dev/null || echo '?') auf Port 8000"
cd /home/user
exec runuser -u user -- /app/entrypoint.sh run --host 0.0.0.0 --port 8000
