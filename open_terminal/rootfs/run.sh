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
# Besitz bei jedem Start prüfen: Gehört der Inhalt nicht (mehr) "user" – z. B. nach
# einer Migration per scp als root –, repariert das entrypoint.sh des Basis-Images
# das nicht mehr (es chown-t nur, wenn /home/user selbst fremd ist, nicht bei fremden
# Dateien darin). Das rekursive chown nur bei Bedarf, sonst kostet es bei jedem Start.
if find "$HOME_DIR" \! -user user -print -quit | grep -q .; then
  chown -R user:user "$HOME_DIR"
  log "Besitz des Home-Verzeichnisses korrigiert"
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

# Arbeitsordner unter /share (gemeinsam mit ArtCraft, Foto MCP, mailbox.org MCP und Open WebUI)
# als ~/work. Austauschordner: mbox/inbox, mbox/outbox (Mail) und openwebui/inbox (Chat-Anhänge).
WORK=$(jq -r '.work_dir // empty' "$OPTIONS")
LINK="$HOME_DIR/work"
if [ -n "$WORK" ]; then
  AUSTAUSCH="$WORK/mbox/inbox $WORK/mbox/outbox $WORK/openwebui/inbox"
  # shellcheck disable=SC2086
  mkdir -p $AUSTAUSCH
  # Rechte für "user", auch als Vorgabe für später angelegte Dateien. Ist /share selbst der
  # Arbeitsordner, nur auf die Austauschordner, nicht auf alle Daten der anderen Apps.
  if [ "$WORK" = "/share" ]; then ACL_ZIEL="$WORK/mbox $WORK/openwebui"; else ACL_ZIEL="$WORK"; fi
  # shellcheck disable=SC2086
  if setfacl -R -m u:user:rwX -m d:u:user:rwX $ACL_ZIEL 2>/dev/null; then
    log "Arbeitsordner: $WORK als ~/work (Rechte per ACL auf ${ACL_ZIEL// /, })"
  else
    # shellcheck disable=SC2086
    chown -R user:user $ACL_ZIEL
    # shellcheck disable=SC2086
    chmod -R u+rwX $ACL_ZIEL
    log "Arbeitsordner: $WORK als ~/work (ohne ACL, ${ACL_ZIEL// /, } gehören user)"
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

# Pakete: Python per uv in ~/.venv, R aus CRAN (Optionen python_bundles, python_packages,
# update_packages, r_packages). Läuft im Hintergrund als "user", das Terminal startet sofort.
# Fehlt eine Option (z. B. alte options.json), gelten die Standardwerte.
GRUPPEN=$(jq -r 'if has("python_bundles") then (.python_bundles // [] | join(" ")) else "bild vektor pdf office cad" end' "$OPTIONS")
EXTRA=$(jq -r '.python_packages // [] | .[]' "$OPTIONS")
UPDATE=$(jq -r 'if has("update_packages") then (.update_packages | tostring) else "true" end' "$OPTIONS")
RPAKETE=$(jq -r '.r_packages // [] | .[]' "$OPTIONS")
mkdir -p "$HOME_DIR/.config"
{
  printf 'PAKET_GRUPPEN=%q\n' "$GRUPPEN"
  printf 'PAKET_EXTRA=%q\n' "$EXTRA"
  printf 'PAKET_UPDATE=%q\n' "$UPDATE"
  printf 'R_PAKETE=%q\n' "$RPAKETE"
} > "$HOME_DIR/.config/terminal-pakete.env"
chown -R user:user "$HOME_DIR/.config"
if [ -n "$GRUPPEN$EXTRA$RPAKETE" ]; then
  log "Pakete im Hintergrund: ${GRUPPEN:-keine Gruppen}${EXTRA:+ + eigene Python-Pakete}${RPAKETE:+ + R-Pakete} (Fortschritt: [pakete])"
  setsid runuser -u user -- env HOME=/home/user PAKET_GRUPPEN="$GRUPPEN" PAKET_EXTRA="$EXTRA" \
    PAKET_UPDATE="$UPDATE" R_PAKETE="$RPAKETE" /usr/local/bin/terminal-pakete </dev/null &
fi
# Sitzungen des Terminals erben PATH: Python aus ~/.venv zuerst (auch bevor es fertig ist)
export PATH="/home/user/.venv/bin:$PATH" VIRTUAL_ENV=/home/user/.venv

export OPEN_TERMINAL_API_KEY="$key"
unset key SUPERVISOR_TOKEN HASSIO_TOKEN
log "Starte Open Terminal $(python3 -c 'import importlib.metadata as m; print(m.version("open-terminal"))' 2>/dev/null || echo '?') auf Port 8000"
cd /home/user
exec runuser -u user -- /app/entrypoint.sh run --host 0.0.0.0 --port 8000
