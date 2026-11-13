# Netlify MCP: offizieller @netlify/mcp (stdio, Node) hinter mcp-auth-proxy.
# Das npm-Paket wird beim Bau aus package-lock.json installiert (feste Versionen und
# Prüfsummen aller Abhängigkeiten), nicht bei jedem Start per npx.
# Node 22, weil @netlify/mcp mindestens Node 20 verlangt.
# Die Versionen pflegt .github/workflows/update.yml (hier und in package.json).
FROM node:22-bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG PROXY_VERSION=2.10.4
ARG PROXY_SHA256_ARM64=d715360d8eb40998d1cc9175d258076e3ced645d1824de15a907ce5c0e80e42e
ARG PROXY_SHA256_AMD64=038bc5af6f83d2371cd985a5de0a73c320395e0d6a09ceeb889bfe3c9d2267d7

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY package.json package-lock.json /opt/netlify-mcp/

RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq python3; \
  case "$(uname -m)" in \
    aarch64) P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  cd /opt/netlify-mcp; \
  npm ci --omit=dev --no-audit --no-fund; \
  npm cache clean --force; \
  ln -s /opt/netlify-mcp/node_modules/.bin/netlify-mcp /usr/local/bin/netlify-mcp; \
  echo "@netlify/mcp $(node -p 'require("@netlify/mcp/package.json").version')" >> /usr/local/share/mcp-versions; \
  echo "node $(node --version)" >> /usr/local/share/mcp-versions; \
  curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
    "https://github.com/sigbit/mcp-auth-proxy/releases/download/v$PROXY_VERSION/mcp-auth-proxy-linux-$P"; \
  echo "$PSUM  /usr/local/bin/mcp-auth-proxy" | sha256sum -c -; \
  chmod 755 /usr/local/bin/mcp-auth-proxy; \
  echo "mcp-auth-proxy $PROXY_VERSION" >> /usr/local/share/mcp-versions; \
  apt-get purge -y --auto-remove curl; \
  rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 755 /run.sh /usr/local/bin/mcp-selftest

CMD ["/run.sh"]
