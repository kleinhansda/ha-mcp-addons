#!/usr/bin/env bash
# Test des Build-Patches patches/imap_draft_thread.mjs: imap-mcp in der Version aus dem Dockerfile
# holen, patchen und save_draft mit einem nachgebauten IMAP-Client aufrufen.
set -euo pipefail
cd "$(dirname "$0")"
version="$(grep -o '@ni-c/imap-mcp@[0-9.]*' ../../Dockerfile | cut -d@ -f3)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
( cd "$tmp" && npm init -y >/dev/null && npm install --ignore-scripts --no-audit --no-fund "@ni-c/imap-mcp@$version" >/dev/null )
write="$tmp/node_modules/@ni-c/imap-mcp/dist/tools/write.js"
node ../../patches/imap_draft_thread.mjs "$write"
if node ../../patches/imap_draft_thread.mjs "$write" 2>/dev/null; then
  echo "FEHLER: zweiter Patch-Lauf hätte abbrechen müssen"; exit 1
fi
node test.mjs "$write"
