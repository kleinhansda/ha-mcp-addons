#!/usr/bin/env bash
# Test der Build-Patches patches/imap_mcp.mjs und patches/smtp_mcp.mjs: imap-mcp und smtp-mcp in der
# Version aus dem Dockerfile holen, patchen und die Werkzeuge mit nachgebauten Servern aufrufen.
set -euo pipefail
cd "$(dirname "$0")"
imap="$(grep -o '@ni-c/imap-mcp@[0-9.]*' ../../Dockerfile | cut -d@ -f3)"
smtp="$(grep -o '@ni-c/smtp-mcp@[0-9.]*' ../../Dockerfile | cut -d@ -f3)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
( cd "$tmp" && npm init -y >/dev/null \
  && npm install --ignore-scripts --no-audit --no-fund "@ni-c/imap-mcp@$imap" "@ni-c/smtp-mcp@$smtp" >/dev/null )
for p in imap smtp; do
  dist="$tmp/node_modules/@ni-c/$p-mcp/dist"
  node "../../patches/${p}_mcp.mjs" "$dist"
  if node "../../patches/${p}_mcp.mjs" "$dist" 2>/dev/null; then
    echo "FEHLER: zweiter Lauf von ${p}_mcp.mjs hätte abbrechen müssen"; exit 1
  fi
done
MBX_FROM_ADDRESSES="dkleinhans@mailbox.org, mail@ddsk.cloud" MBX_FROM_NAME="David Kleinhans" \
  node test_imap.mjs "$tmp/node_modules/@ni-c/imap-mcp/dist"
MBX_FROM_ADDRESSES="" MBX_FROM_NAME="" node test_imap.mjs "$tmp/node_modules/@ni-c/imap-mcp/dist" ohne
MBX_FROM_ADDRESSES="dkleinhans@mailbox.org, mail@ddsk.cloud" MBX_FROM_NAME="David Kleinhans" \
  node test_smtp.mjs "$tmp/node_modules/@ni-c/smtp-mcp/dist"
