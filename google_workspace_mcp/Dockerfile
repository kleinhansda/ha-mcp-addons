# Google Workspace MCP: workspace-mcp (Taylor Wilsdon, MIT, stdio, Python) hinter mcp-auth-proxy.
# Python-Pakete fest aus requirements.txt mit Prüfsummen (erzeugt mit
# uv pip compile --universal --python-version 3.11 --generate-hashes aus workspace-mcp==<version>).
# --no-deps: die Datei enthält alle Abhängigkeiten; pip check prüft die Vollständigkeit.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG PROXY_VERSION=2.10.6
ARG PROXY_SHA256_ARM64=10370ef8e9daee2b7575959680755f932adfdcd724bba67335bdd3c97da72ecb
ARG PROXY_SHA256_AMD64=f690e2125794f00b2bc3ef980d1514766e6bc02562c47a4783455893dda775e9

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

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
  echo "workspace-mcp $(/opt/venv/bin/pip show workspace-mcp | sed -n 's/^Version: //p')" >> /usr/local/share/mcp-versions; \
  echo "fastmcp $(/opt/venv/bin/pip show fastmcp | sed -n 's/^Version: //p')" >> /usr/local/share/mcp-versions; \
  curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
    "https://github.com/sigbit/mcp-auth-proxy/releases/download/v$PROXY_VERSION/mcp-auth-proxy-linux-$P"; \
  echo "$PSUM  /usr/local/bin/mcp-auth-proxy" | sha256sum -c -; \
  chmod 755 /usr/local/bin/mcp-auth-proxy; \
  echo "mcp-auth-proxy $PROXY_VERSION" >> /usr/local/share/mcp-versions; \
  apt-get purge -y --auto-remove curl; \
  rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 755 /run.sh /usr/local/bin/mcp-selftest /usr/local/lib/mcp/gws_auth.py

CMD ["/run.sh"]
