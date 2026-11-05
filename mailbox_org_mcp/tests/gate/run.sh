#!/bin/bash
# Gate-Test gegen Mock-IdP und Mock-Hub: bash tests/gate/run.sh [RS256|ES256|EdDSA]
set -u
D=$(cd "$(dirname "$0")" && pwd)
S=$(mktemp -d); head -c 48 /dev/urandom > "$S/secret"
MOCK_ALG=${1:-RS256} node "$D/mocks.mjs" > "$S/mocks.log" 2>&1 & M=$!
GATE_PORT=8099 HUB_PORT=8100 EXTERNAL_URL=http://127.0.0.1:8099 OIDC_ISSUER=http://127.0.0.1:9000 \
OIDC_CLIENT_ID=gate-client OIDC_CLIENT_SECRET=s3cret GATE_ALLOWED_USERS=david@example.org \
HUB_PASSWORD=hub-pw GATE_SECRET_FILE="$S/secret" GATE_INSECURE_COOKIES=1 \
  node "$D/../../gate.mjs" > "$S/gate.log" 2>&1 & G=$!
sleep 1
node "$D/test.mjs"; rc=$?
kill $M $G 2>/dev/null; wait 2>/dev/null
[ $rc -ne 0 ] && cat "$S/gate.log"
rm -rf "$S"; exit $rc
