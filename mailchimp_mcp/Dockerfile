# Mailchimp MCP: mailchimp-mcp (Damien Tilman, MIT, stdio, Python) hinter mcp-auth-proxy.
# Python-Pakete fest aus requirements.txt mit Prüfsummen (erzeugt mit
# uv pip compile --universal --generate-hashes aus mailchimp-mcp==<version> und mcp<2;
# mailchimp-mcp 1.2.0 nutzt FastMCP aus dem MCP-SDK 1.x). --no-deps, weil die Datei alle
# Abhängigkeiten schon enthält und pip 23 (bookworm) das Extra mcp[cli] sonst nicht zuordnet;
# pip check prüft danach die Vollständigkeit.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG PROXY_VERSION=2.10.2
ARG PROXY_SHA256_ARM64=924c5335e5f684eb22c681cca1daff86d96fa35f644950cbd8f4c8f3e290bc3d
ARG PROXY_SHA256_AMD64=1c76b230fdb6c536a0912c059232cba2229acbcf1f02a11a5d0664781326bcd6

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-addons"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY requirements.txt /opt/requirements.txt

RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq python3 python3-venv; \
  case "$(uname -m)" in \
    aarch64) P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  python3 -m venv /opt/venv; \
  /opt/venv/bin/pip install --no-cache-dir --require-hashes --no-deps --only-binary=:all: -r /opt/requirements.txt; \
  /opt/venv/bin/pip check; \
  echo "mailchimp-mcp $(/opt/venv/bin/pip show mailchimp-mcp | sed -n 's/^Version: //p')" >> /usr/local/share/mcp-versions; \
  echo "mcp (SDK) $(/opt/venv/bin/pip show mcp | sed -n 's/^Version: //p')" >> /usr/local/share/mcp-versions; \
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
