# Dawarich (https://github.com/Freika/dawarich) mit eingebautem PostgreSQL/PostGIS, Redis und
# nginx für Ingress. Basis ist das offizielle Image; die Startskripte stammen aus
# thomdev-j/dawarich-home-assistant-addon (AGPL-3.0, siehe LICENSE) und sind hier angepasst.
# DAWARICH_VERSION und version in config.yaml pflegt .github/workflows/update.yml
# (neue Releases nach bestandenem Test). Eigene Änderungen: vierte Stelle (1.23.0.1).
ARG DAWARICH_VERSION=1.23.0
FROM freikin/dawarich:${DAWARICH_VERSION}

ARG DAWARICH_VERSION
ARG BUILD_ARCH
ARG BUILD_VERSION
ARG S6_OVERLAY_VERSION="3.2.2.0"
ARG BASHIO_VERSION="0.16.2"

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

USER root
# curl fehlt im Image seit Dawarich 1.23 (Startskript, HA-Tracker, Supervisor-API).
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates xz-utils jq redis-server gnupg nginx \
    && rm -rf /var/lib/apt/lists/*

# PostgreSQL 17 + PostGIS aus PGDG, Codename aus os-release (lsb_release gibt es nicht überall)
RUN . /etc/os-release \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17 postgresql-17-postgis-3 \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/lib/postgresql/17/bin/postgres --version

# s6-overlay v3
RUN S6_ARCH=$([ "$(uname -m)" = "x86_64" ] && echo "x86_64" || echo "aarch64") \
    && base="https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}" \
    && for f in noarch "${S6_ARCH}" symlinks-noarch symlinks-arch; do \
         curl -fsSL "${base}/s6-overlay-${f}.tar.xz" | tar Jxpf - -C /; \
       done

# bashio
RUN curl -fsSL "https://github.com/hassio-addons/bashio/archive/v${BASHIO_VERSION}.tar.gz" | tar xzf - \
    && mv "bashio-${BASHIO_VERSION}/lib" /usr/lib/bashio \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    && rm -rf "bashio-${BASHIO_VERSION}"

RUN mkdir -p /data/postgres /data/redis /data/dawarich/storage /data/dawarich/public \
    && mkdir -p /run/postgresql && chown postgres:postgres /run/postgresql

COPY rootfs /
RUN chmod 755 /usr/local/bin/dawarich-rails /usr/share/dawarich/*.sh /etc/s6-overlay/scripts/*.sh \
    && echo '[ -r /etc/profile.d/dawarich-env.sh ] && . /etc/profile.d/dawarich-env.sh' >> /etc/bash.bashrc \
    && sed 's|INGRESS_PATH|/api/hassio_ingress/test|g' /etc/nginx/nginx.conf.template > /tmp/nginx-test.conf \
    && nginx -t -c /tmp/nginx-test.conf && rm /tmp/nginx-test.conf

ENV DAWARICH_VERSION=${DAWARICH_VERSION} \
    S6_SERVICES_GRACETIME=60000 \
    S6_KILL_GRACETIME=10000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

ENTRYPOINT ["/init"]
