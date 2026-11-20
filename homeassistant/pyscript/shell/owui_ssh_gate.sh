#!/bin/bash
# Prüfskript für den SSH-Schlüssel des Open-WebUI-Werkzeugs „HA-SSH“.
# Wird im Advanced-SSH-Add-on über authorized_keys erzwungen:
#   restrict,command="bash /config/pyscript/shell/owui_ssh_gate.sh" ssh-ed25519 AAAA… owui-ha-ssh
# Der Schlüssel kann damit nur die Aktionen unten ausführen, nie eine freie Shell. Argumente sind auf
# harmlose Zeichen beschränkt, Pfade auf freigegebene Ordner ohne versteckte Dateien und Geheimnisse.
# Jeder Aufruf wird in owui_ssh_gate.log protokolliert.
set -u
export LC_ALL=C.UTF-8
MAX_BYTES=200000
WURZELN="/config /homeassistant /share /media /addon_configs"
LOG="$(dirname "$(readlink -f "$0")")/owui_ssh_gate.log"
cmd="${SSH_ORIGINAL_COMMAND:-}"

fehler() { echo "FEHLER: $*"; echo "$(date -Iseconds) ABGELEHNT ${cmd:0:200} :: $*" >> "$LOG" 2>/dev/null; exit 2; }

# ha-CLI braucht das Supervisor-Token; in Befehlen ohne Login-Shell fehlt es sonst
if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
  for f in /run/s6/container_environment/SUPERVISOR_TOKEN /var/run/s6/container_environment/SUPERVISOR_TOKEN; do
    if [ -r "$f" ]; then SUPERVISOR_TOKEN="$(cat "$f")"; export SUPERVISOR_TOKEN; break; fi
  done
fi

[ -n "$cmd" ] || fehler "kein Befehl (Aufruf nur über das Werkzeug)"
[ "${#cmd}" -le 400 ] || fehler "Befehl zu lang"
[[ "$cmd" =~ ^[A-Za-z0-9_./:@+=\ -]+$ ]] || fehler "unerlaubte Zeichen (erlaubt: Buchstaben, Ziffern, _ . / : @ + = - und Leerzeichen)"
[[ "$cmd" != *..* ]] || fehler "'..' ist nicht erlaubt"
read -r -a a <<< "$cmd"
akt="${a[0]}"; x1="${a[1]:-}"; x2="${a[2]:-}"
[ "${#a[@]}" -le 3 ] || fehler "zu viele Argumente"
echo "$(date -Iseconds) OK ${cmd}" >> "$LOG" 2>/dev/null

zahl() { [[ "${1:-}" =~ ^[0-9]{1,5}$ ]] && echo "$1" || echo "${2}"; }
slug() { [[ "${1:-}" =~ ^[a-z0-9_]{2,64}$ ]] || fehler "App-Slug ungültig (z. B. core_mosquitto, a0d7b954_ssh)"; }

# setzt P auf den geprüften, aufgelösten Pfad (kein Subshell-Aufruf, damit fehler() wirkt)
pfad() {
  local p="${1:-}" r w ok=0
  [[ "$p" == /* ]] || fehler "Pfad muss absolut sein, z. B. /config/automations.yaml"
  r="$(readlink -m -- "$p")"
  for w in $WURZELN; do
    w="$(readlink -m -- "$w")"
    if [ "$r" = "$w" ] || [[ "$r" == "$w"/* ]]; then ok=1; fi
  done
  [ "$ok" = 1 ] || fehler "Pfad außerhalb der freigegebenen Ordner ($WURZELN)"
  [[ "/$r/" != */.* ]] || fehler "versteckte Dateien und Ordner (.storage, .ssh, …) sind gesperrt"
  case "${r,,}" in
    *secret*|*token*|*passw*|*credential*|*.pem|*.key|*/id_rsa*|*/id_ed25519*|*/pyscript/shell/backup*|*.db|*.db-wal|*.db-shm|*owui_ssh_gate*)
      fehler "Datei mit Geheimnissen ist gesperrt" ;;
  esac
  P="$r"
}

ha_apps() { ha apps "$@" 2>/dev/null || ha addons "$@"; }

# shellcheck disable=SC2010  # ls | grep: versteckte Einträge aus der Ausgabe nehmen
case "$akt" in
  hilfe)
    echo "Aktionen: info [core|supervisor|os|host|resolution], check, logs <core|supervisor|host|<app>> [zeilen],"
    echo "apps, ls <pfad>, cat <datei>, tail <datei> [zeilen], grep <muster> <datei>, du <pfad>, df,"
    echo "neustart <core|<app>>, app_start <app>, app_stop <app>" ;;
  info)
    case "${x1:-core}" in
      core|supervisor|os|host|resolution) ha "${x1:-core}" info --no-progress 2>&1 || ha "${x1:-core}" info 2>&1 ;;
      *) fehler "info: core, supervisor, os, host oder resolution" ;;
    esac ;;
  check) ha core check --no-progress 2>&1 || ha core check 2>&1 ;;
  logs)
    n="$(zahl "$x2" 200)"
    case "$x1" in
      core|supervisor|host) ha "$x1" logs 2>&1 | tail -n "$n" ;;
      *) slug "$x1"; ha_apps logs "$x1" 2>&1 | tail -n "$n" ;;
    esac ;;
  apps) ha_apps 2>&1 | head -c "$MAX_BYTES" ;;
  ls) pfad "$x1"; ls -la --time-style=long-iso -- "$P" 2>&1 | grep -v ' \.[^ ]*$' | head -n 500 ;;
  cat)
    pfad "$x1"
    [ -f "$P" ] || fehler "keine Datei: $P"
    grep -Iq . -- "$P" 2>/dev/null || [ ! -s "$P" ] || fehler "Binärdatei, wird nicht angezeigt"
    head -c "$MAX_BYTES" -- "$P"
    [ "$(stat -c %s -- "$P")" -le "$MAX_BYTES" ] || echo -e "\n[…gekürzt auf $MAX_BYTES Bytes; mit tail oder grep gezielt lesen]" ;;
  tail)
    pfad "$x1"
    [ -f "$P" ] || fehler "keine Datei: $P"
    tail -n "$(zahl "$x2" 100)" -- "$P" | head -c "$MAX_BYTES" ;;
  grep)
    [ -n "$x1" ] && [ -n "$x2" ] || fehler "grep <muster> <datei>"
    pfad "$x2"
    [ -f "$P" ] || fehler "keine Datei: $P"
    grep -n -I -F -e "$x1" -- "$P" 2>&1 | head -n 300 ;;
  du) pfad "$x1"; du -h -d 1 -- "$P" 2>/dev/null | sort -rh | head -n 50 ;;
  df) df -h 2>&1 | grep -v -E '^(overlay|shm|tmpfs)' ;;
  neustart)
    case "$x1" in
      core) ha core check 2>&1 && ha core restart 2>&1 || fehler "Konfigurationsprüfung fehlgeschlagen, kein Neustart" ;;
      *) slug "$x1"; ha_apps restart "$x1" 2>&1 ;;
    esac ;;
  app_start) slug "$x1"; ha_apps start "$x1" 2>&1 ;;
  app_stop)
    slug "$x1"
    case "$x1" in *_ssh|*ssh*) fehler "Das SSH-Add-on selbst wird nicht gestoppt" ;; esac
    ha_apps stop "$x1" 2>&1 ;;
  *) fehler "unbekannte Aktion '$akt' (hilfe zeigt die Liste)" ;;
esac
