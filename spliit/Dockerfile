# Spliit (https://github.com/spliit-app/spliit) mit eingebautem PostgreSQL.
# Basis ist das offizielle Image (Alpine, Node). Die Version hier gilt für beide Architekturen.
ARG SPLIIT_VERSION=1.22.0
FROM ghcr.io/spliit-app/spliit:${SPLIIT_VERSION}

USER root
RUN apk add --no-cache postgresql16 postgresql16-client su-exec curl jq \
 && pg_ctl --version && psql --version

COPY run.sh /run.sh
RUN chmod +x /run.sh
ENTRYPOINT ["/run.sh"]
