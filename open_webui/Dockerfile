# Open WebUI: offizielles Image (amd64/arm64), nur um ein Startskript ergänzt.
# Volles Image statt "-slim": slim bringt keine eingebaute Vektordatenbank (Chroma) mit
# und verlangt Postgres mit pgvector. Lokale Modelle lädt das volle Image nur, wenn sie
# in den Einstellungen gewählt sind; mit externen Embeddings bleibt der Speicherbedarf klein.
# OPEN_WEBUI_VERSION und version in config.yaml pflegt .github/workflows/update.yml
# (neue Releases nach bestandenem Test). Eigene Änderungen: version mit Endung .N (z. B. 0.13.3.2; nicht -N, das hält Home Assistant für eine Vorabversion).
ARG OPEN_WEBUI_VERSION=0.13.3
FROM ghcr.io/open-webui/open-webui:${OPEN_WEBUI_VERSION}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-addons"

# SearXNG als private Suchmaschine für die Web-Suche, nur auf 127.0.0.1 erreichbar.
# Eigenes venv, damit sich die Pakete nicht mit denen von Open WebUI beißen. SearXNG hat
# keine Releases; gepinnt wird ein Commit, aktualisiert wird von Hand.
ARG SEARXNG_COMMIT=ffa88e3ba3ade64185d5754c839cdf5a80708c4a
RUN set -eux; \
  mkdir -p /opt/searxng; \
  curl -fsSL "https://github.com/searxng/searxng/archive/${SEARXNG_COMMIT}.tar.gz" | tar -xz -C /opt/searxng; \
  mv "/opt/searxng/searxng-${SEARXNG_COMMIT}" /opt/searxng/src; \
  python3 -m venv /opt/searxng/venv; \
  /opt/searxng/venv/bin/pip install --no-cache-dir --prefer-binary \
    -r /opt/searxng/src/requirements.txt -r /opt/searxng/src/requirements-server.txt; \
  echo "${SEARXNG_COMMIT}" > /opt/searxng/COMMIT

COPY rootfs /
RUN chmod 755 /run.sh

# Das Image prüft /health ohne Anlaufzeit. Beim ersten Start nach einer Übernahme oder
# einem Versionssprung laufen Datenbank-Migrationen, die mehrere Minuten dauern können. Ohne lange Anlaufzeit hielte der Watchdog das für einen Absturz und startete
# mitten in der Migration neu.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15m --retries=5 \
  CMD curl --silent --fail http://127.0.0.1:8080/health | jq -ne 'input.status == true' || exit 1

CMD ["/run.sh"]
