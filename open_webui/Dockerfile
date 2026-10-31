# Open WebUI: offizielles Image (amd64/arm64), nur um ein Startskript ergänzt.
# Volles Image statt "-slim": slim bringt keine eingebaute Vektordatenbank (Chroma) mit
# und verlangt Postgres mit pgvector. Lokale Modelle lädt das volle Image nur, wenn sie
# in den Einstellungen gewählt sind; mit externen Embeddings bleibt der Speicherbedarf klein.
# Version von Hand pflegen: OPEN_WEBUI_VERSION und version in config.yaml gemeinsam erhöhen.
ARG OPEN_WEBUI_VERSION=0.12.5
FROM ghcr.io/open-webui/open-webui:${OPEN_WEBUI_VERSION}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

COPY rootfs /
RUN chmod 755 /run.sh

# Das Image prüft /health ohne Anlaufzeit. Beim ersten Start nach einer Übernahme oder
# einem Versionssprung laufen Datenbank-Migrationen, auf einem Raspberry Pi auch mehrere
# Minuten. Ohne lange Anlaufzeit hielte der Watchdog das für einen Absturz und startete
# mitten in der Migration neu.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15m --retries=5 \
  CMD curl --silent --fail http://127.0.0.1:8080/health | jq -ne 'input.status == true' || exit 1

CMD ["/run.sh"]
