# ArtCraft MCP: VectorCraft, PhotoCraft und PdfCraft (storytold) hinter mcp-auth-proxy.
# Fertige Release-Binaries von GitHub, kein Rust-Build. Jede Datei wird gegen ihre
# Prüfsumme geprüft. Die Versionen unten pflegt .github/workflows/update.yml.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG VECTORCRAFT_VERSION=0.16.0
ARG PHOTOCRAFT_VERSION=0.15.1
ARG PDFCRAFT_VERSION=0.13.0
ARG PROXY_VERSION=2.10.2
ARG PROXY_SHA256_ARM64=924c5335e5f684eb22c681cca1daff86d96fa35f644950cbd8f4c8f3e290bc3d
ARG PROXY_SHA256_AMD64=1c76b230fdb6c536a0912c059232cba2229acbcf1f02a11a5d0664781326bcd6

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq; \
  case "$(uname -m)" in \
    aarch64) A=aarch64; P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  A=x86_64;  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  cd /tmp; \
  hol() { repo=$1; v=$2; name=$3; inner=$4; \
    asset="$name-$v-linux-$A.tar.gz"; \
    base="https://github.com/storytold/$repo/releases/download/v$v"; \
    curl -fsSLO "$base/$asset"; \
    curl -fsSL "$base/SHA256SUMS.txt" -o sums; \
    grep " $asset\$" sums | sha256sum -c -; \
    tar xzf "$asset" -C /usr/local/bin --no-same-owner \
      --strip-components="$(echo "$inner" | awk -F/ '{print NF}')" "${asset%.tar.gz}/$inner"; \
    echo "$repo $v" >> /usr/local/share/mcp-versions; \
    rm -f "$asset" sums; }; \
  hol vectorcraft "$VECTORCRAFT_VERSION" vectorcraft  bin/vectorcraft-cli; \
  hol photocraft  "$PHOTOCRAFT_VERSION"  photocraft   bin/photocraft-cli; \
  hol pdfcraft    "$PDFCRAFT_VERSION"    pdfcraft-cli pdfcraft-cli; \
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
