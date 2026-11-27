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
# smtp-mcp bekommt für den Test ein nachgebautes imapflow; das echte wird nur aufgelöst und geprüft.
echte_imapflow="$(node -e "console.log(require.resolve('imapflow',{paths:[process.argv[1]]}))" "$tmp/node_modules/@ni-c/imap-mcp")"
node -e "import(require('url').pathToFileURL(process.argv[1]).href).then(m => { if (typeof (m.ImapFlow ?? m.default?.ImapFlow) !== 'function') process.exit(1) })" "$echte_imapflow"
for p in imap smtp; do
  dist="$tmp/node_modules/@ni-c/$p-mcp/dist"
  extra=""; [ "$p" = smtp ] && extra="$PWD/imapflow_fake.mjs"
  node "../../patches/${p}_mcp.mjs" "$dist" $extra
  if node "../../patches/${p}_mcp.mjs" "$dist" $extra 2>/dev/null; then
    echo "FEHLER: zweiter Lauf von ${p}_mcp.mjs hätte abbrechen müssen"; exit 1
  fi
done
export MBX_SENDERS_FILE="$tmp/absender.json"
MBX_FROM_ADDRESSES="dkleinhans@mailbox.org, mail@ddsk.cloud" MBX_FROM_NAME="David Kleinhans" \
  node test_imap.mjs "$tmp/node_modules/@ni-c/imap-mcp/dist"
MBX_FROM_ADDRESSES="" MBX_FROM_NAME="" node test_imap.mjs "$tmp/node_modules/@ni-c/imap-mcp/dist" ohne
MBX_FROM_ADDRESSES="dkleinhans@mailbox.org, mail@ddsk.cloud" MBX_FROM_NAME="David Kleinhans" MBX_SENT_COPY=true \
  MBX_SENT_IMAP_HOST=imap.example.org MBX_SENT_IMAP_USER=mail@ddsk.cloud MBX_SENT_IMAP_PASSWORD=x \
  node test_smtp.mjs "$tmp/node_modules/@ni-c/smtp-mcp/dist"
MBX_FROM_ADDRESSES="" MBX_FROM_NAME="" node test_smtp.mjs "$tmp/node_modules/@ni-c/smtp-mcp/dist" ohne
