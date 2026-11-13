# ArtCraft MCP: VectorCraft, PhotoCraft, PdfCraft und CADCraft, WordCraft, DeckCraft,
# GridCraft, FigCraft, Craft Anything als MCP-Server über mcp-auth-proxy.
# Release-Binaries von GitHub, geprüft gegen die SHA256SUMS.txt des Releases.
# Offene Schriften (SIL OFL, Apache, Bitstream Vera) aus Debian, siehe docs/ARTCRAFT.md.
# Versionen werden über .github/workflows/update.yml gepflegt.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

# Alte Tools
ARG VECTORCRAFT_VERSION=0.24.1
ARG PHOTOCRAFT_VERSION=0.23.1
ARG PDFCRAFT_VERSION=0.21.1
# Neue Tools
ARG CADCRAFT_VERSION=0.20.1
ARG WORDCRAFT_VERSION=0.18.1
ARG DECKCRAFT_VERSION=0.18.1
ARG GRIDCRAFT_VERSION=0.19.1
ARG FIGCRAFT_VERSION=0.18.1
ARG CRAFT_ANYTHING_VERSION=0.6.1
# Proxy
ARG PROXY_VERSION=2.10.4
ARG PROXY_SHA256_ARM64=d715360d8eb40998d1cc9175d258076e3ced645d1824de15a907ce5c0e80e42e
ARG PROXY_SHA256_AMD64=038bc5af6f83d2371cd985a5de0a73c320395e0d6a09ceeb889bfe3c9d2267d7

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Schriften klein halten: je Familie nur Regular, Italic, Bold und BoldItalic, DejaVu ganz.
RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq python3 \
    fonts-dejavu-core fonts-liberation2 fonts-open-sans fonts-lato fonts-inter; \
  find /usr/share/fonts -type f \( -name '*.ttf' -o -name '*.otf' \) \
    ! -name 'DejaVu*' ! -regex '.*-\(Regular\|Italic\|Bold\|BoldItalic\)\.\(ttf\|otf\)' -delete; \
  find /usr/share/fonts -name 'InterDisplay*' -delete; \
  case "$(uname -m)" in \
    aarch64) A=aarch64; P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  A=x86_64;  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  cd /tmp; \
  # hol() lädt ein Release-Archiv, prüft es gegen SHA256SUMS.txt des Releases und
  # installiert das CLI-Binary nach /usr/local/bin. $1=repo, $2=version, $3=asset-name,
  # $4=pfad-ins-archiv. Der Proxy behält seine festen SHAs (kein SHA256SUMS.txt).
  hol() { repo=$1; v=$2; name=$3; inner=$4; \
    asset="$name-$v-linux-$A.tar.gz"; \
    base="https://github.com/storytold/$repo/releases/download/v$v"; \
    curl -fsSLO "$base/$asset"; \
    curl -fsSL "$base/SHA256SUMS.txt" -o sums; \
    grep " $asset\$" sums | sha256sum -c -; \
    tar xzf "$asset" -C /usr/local/bin --no-same-owner \
      --strip-components="$(echo "$inner" | awk -F/ '{print NF}')" "${asset%.tar.gz}/$inner"; \
    echo "$repo $v" >> /usr/local/share/artcraft-versions; \
    rm -f "$asset" sums; }; \
  # Asset-Name = Repo-Name, nur PdfCraft veröffentlicht zusätzlich ein pdfcraft-cli-Archiv.
  hol vectorcraft "$VECTORCRAFT_VERSION" vectorcraft bin/vectorcraft-cli; \
  hol photocraft  "$PHOTOCRAFT_VERSION"  photocraft  bin/photocraft-cli; \
  hol pdfcraft    "$PDFCRAFT_VERSION"    pdfcraft-cli pdfcraft-cli; \
  hol cadcraft    "$CADCRAFT_VERSION"    cadcraft    bin/cadcraft-cli; \
  hol wordcraft   "$WORDCRAFT_VERSION"   wordcraft   bin/wordcraft-cli; \
  hol deckcraft   "$DECKCRAFT_VERSION"   deckcraft   bin/deckcraft-cli; \
  hol gridcraft   "$GRIDCRAFT_VERSION"   gridcraft   bin/gridcraft-cli; \
  hol figcraft    "$FIGCRAFT_VERSION"    figcraft    bin/figcraft-cli; \
  hol craft-anything "$CRAFT_ANYTHING_VERSION" craft-anything bin/craft-anything-cli; \
  curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
    "https://github.com/sigbit/mcp-auth-proxy/releases/download/v$PROXY_VERSION/mcp-auth-proxy-linux-$P"; \
  echo "$PSUM  /usr/local/bin/mcp-auth-proxy" | sha256sum -c -; \
  chmod 755 /usr/local/bin/mcp-auth-proxy; \
  echo "mcp-auth-proxy $PROXY_VERSION" >> /usr/local/share/artcraft-versions; \
  apt-get purge -y --auto-remove curl; \
  rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 755 /run.sh /usr/local/bin/artcraft-selftest \
  /usr/local/lib/artcraft/mcp_bridge.py \
  && ln -s artcraft-selftest /usr/local/bin/mcp-selftest

CMD ["/run.sh"]
