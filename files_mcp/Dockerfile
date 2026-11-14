# Files MCP: eigener Datei-Server (common/files_mcp.py, stdio) hinter mcp-auth-proxy.
# Pillow, pypdf und mutagen für Metadaten und Vorschau kommen aus Debian, pdftoppm aus
# poppler-utils. Die Proxy-Version pflegt .github/workflows/update.yml.
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

RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq python3 \
    python3-pil python3-pypdf python3-mutagen poppler-utils; \
  case "$(uname -m)" in \
    aarch64) P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
    "https://github.com/sigbit/mcp-auth-proxy/releases/download/v$PROXY_VERSION/mcp-auth-proxy-linux-$P"; \
  echo "$PSUM  /usr/local/bin/mcp-auth-proxy" | sha256sum -c -; \
  chmod 755 /usr/local/bin/mcp-auth-proxy; \
  echo "mcp-auth-proxy $PROXY_VERSION" >> /usr/local/share/mcp-versions; \
  python3 -c "import PIL, pypdf, mutagen; print('files-mcp: Pillow', PIL.__version__, '| pypdf', pypdf.__version__, '| mutagen', mutagen.version_string)" \
    | tee -a /usr/local/share/mcp-versions; \
  pdftoppm -v 2>&1 | sed -n '1s/^/files-mcp: /p' >> /usr/local/share/mcp-versions; \
  apt-get purge -y --auto-remove curl; \
  rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 755 /run.sh /usr/local/bin/mcp-selftest /usr/local/lib/mcp/files_mcp.py

CMD ["/run.sh"]
