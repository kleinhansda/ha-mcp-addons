# Open Terminal: offizielles Image (volle Variante, ~4 GB: Python mit Datenpaketen,
# Node.js, LibreOffice, Pandoc, LaTeX, ffmpeg, sudo). Ergänzt um ein Startskript, das
# den Schlüssel verwaltet und das Home-Verzeichnis nach /data legt (bleibt bei Updates
# erhalten und ist im Backup).
# OPEN_TERMINAL_VERSION und version in config.yaml pflegt .github/workflows/update.yml
# (neue Releases nach bestandenem Test). Eigene Änderungen: version mit Endung -N.
ARG OPEN_TERMINAL_VERSION=0.14.7
FROM ghcr.io/open-webui/open-terminal:${OPEN_TERMINAL_VERSION}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

# Startskript läuft als root (Schlüssel in /data, Home vorbereiten) und startet den
# Server dann als "user" über das unveränderte entrypoint.sh des Images.
USER root
# setfacl gibt "user" Schreibrechte im Arbeitsordner unter /share, auch für Dateien, die
# andere Apps (als root) später anlegen.
RUN command -v setfacl >/dev/null 2>&1 || { \
      apt-get update && apt-get install -y --no-install-recommends acl && rm -rf /var/lib/apt/lists/*; }
COPY rootfs /
RUN chmod 755 /run.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=2m --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT []
CMD ["/run.sh"]
