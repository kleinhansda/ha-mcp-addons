# Open Terminal: offizielles Image (volle Variante, ~4 GB: Python mit Datenpaketen,
# Node.js, LibreOffice, Pandoc, LaTeX, ffmpeg, sudo), dazu R. Ergänzt um ein Startskript, das
# den Schlüssel verwaltet und das Home-Verzeichnis nach /data legt (bleibt bei Updates
# erhalten und ist im Backup).
# OPEN_TERMINAL_VERSION und version in config.yaml pflegt .github/workflows/update.yml
# (neue Releases nach bestandenem Test). Eigene Änderungen: version mit Endung -N.
ARG OPEN_TERMINAL_VERSION=0.17.1
FROM ghcr.io/open-webui/open-terminal:${OPEN_TERMINAL_VERSION}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-addons"

# Startskript läuft als root (Schlüssel in /data, Home vorbereiten) und startet den
# Server dann als "user" über das unveränderte entrypoint.sh des Images.
USER root
# setfacl gibt "user" Schreibrechte im Arbeitsordner unter /share, auch für Dateien, die
# andere Apps (als root) später anlegen.
RUN command -v setfacl >/dev/null 2>&1 || { \
      apt-get update && apt-get install -y --no-install-recommends acl && rm -rf /var/lib/apt/lists/*; }

# R aus Debian (das Image basiert auf python:3.12, also Debian trixie): fertige Binärpakete
# für amd64 und arm64, nichts wird beim Bau kompiliert. Pflicht: R, Compiler-Anbindung,
# empfohlene Pakete und tidyverse. Die optionalen Pakete werden übersprungen, wenn Debian sie
# nicht (mehr) führt, statt den Bau abbrechen zu lassen.
ARG R_PAKETE_OPTIONAL="r-cran-data.table r-cran-renv r-cran-rmarkdown r-cran-knitr r-cran-readxl r-cran-writexl r-cran-openxlsx r-cran-irkernel"
RUN set -eu; \
  apt-get update; \
  opt=""; \
  for p in $R_PAKETE_OPTIONAL; do \
    if apt-cache show "$p" >/dev/null 2>&1; then opt="$opt $p"; else echo "Hinweis: $p nicht in Debian, übersprungen"; fi; \
  done; \
  apt-get install -y --no-install-recommends r-base-core r-base-dev r-recommended r-cran-tidyverse $opt; \
  rm -rf /var/lib/apt/lists/*; \
  if Rscript -e 'quit(status = if (requireNamespace("IRkernel", quietly = TRUE)) 0 else 1)'; then \
    Rscript -e 'IRkernel::installspec(user = FALSE, name = "ir", displayname = "R")'; \
  fi; \
  R --version | head -n 1

COPY rootfs /
RUN chmod 755 /run.sh \
  && cat /etc/R/Rprofile.site.ha >> /etc/R/Rprofile.site && rm /etc/R/Rprofile.site.ha \
  && cat /etc/R/Renviron.site.ha >> /etc/R/Renviron.site && rm /etc/R/Renviron.site.ha

HEALTHCHECK --interval=30s --timeout=5s --start-period=2m --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT []
CMD ["/run.sh"]
