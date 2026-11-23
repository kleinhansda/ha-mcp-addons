# Open Terminal: offizielles Image (volle Variante, ~4 GB: Python mit Datenpaketen,
# Node.js, LibreOffice, Pandoc, LaTeX, ffmpeg, sudo), dazu R. Ergänzt um ein Startskript, das
# den Schlüssel verwaltet und das Home-Verzeichnis nach /data legt (bleibt bei Updates
# erhalten und ist im Backup).
# OPEN_TERMINAL_VERSION und version in config.yaml pflegt .github/workflows/update.yml
# (neue Releases nach bestandenem Test). Eigene Änderungen: version mit Endung -N.
ARG OPEN_TERMINAL_VERSION=0.17.22
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

# uv für die Python-Pakete aus den Optionen (Installation in ~/.venv beim Start, siehe
# /usr/local/bin/terminal-pakete), dazu rsvg-convert und cairo für SVG nach PNG/PDF und rclone
# für WebDAV (Option webdav).
RUN pip install --no-cache-dir uv \
 && apt-get update && apt-get install -y --no-install-recommends librsvg2-bin libcairo2 rclone \
 && rm -rf /var/lib/apt/lists/* \
 && uv --version && rsvg-convert --version && rclone version | head -n 1

# Quarto (mit Pandoc, Typst und Deno) für dokument und eigene Quarto-/R-Markdown-Berichte: feste
# Version, Prüfsumme je Architektur. typst aus dem Paket zusätzlich als Befehl.
ARG QUARTO_VERSION=1.12.2
ARG QUARTO_SHA256_AMD64=dd5b288f2a4c01fff06887d2627c7c25562b6debfb6c180d8abdee6c5736c01d
ARG QUARTO_SHA256_ARM64=88c64e56669990753d926cfac31d7dd1a74433e53f49bdf32b8589203e2a5860
RUN set -eu; \
  case "$(uname -m)" in \
    x86_64) a=amd64; s="$QUARTO_SHA256_AMD64" ;; \
    aarch64) a=arm64; s="$QUARTO_SHA256_ARM64" ;; \
    *) echo "Quarto: Architektur $(uname -m) nicht unterstützt"; exit 1 ;; \
  esac; \
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o /tmp/quarto.tar.gz \
    "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${a}.tar.gz"; \
  echo "$s  /tmp/quarto.tar.gz" | sha256sum -c -; \
  rm -rf /opt/quarto && mkdir -p /opt/quarto; \
  tar -xzf /tmp/quarto.tar.gz -C /opt/quarto --strip-components=1; rm /tmp/quarto.tar.gz; \
  ln -sf /opt/quarto/bin/quarto /usr/local/bin/quarto; \
  ln -sf "/opt/quarto/bin/tools/$(uname -m)/typst" /usr/local/bin/typst; \
  command -v pdftotext >/dev/null 2>&1 || { apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*; }; \
  quarto --version; typst --version

COPY rootfs /
# Dokumentvorlagen (dokument, Quarto-Erweiterung dokument): Schriften systemweit für LibreOffice und
# Typst, danach Selbsttest (alle Beispiele in allen Formaten, Absender je Person, Bildpfade).
RUN chmod 755 /usr/local/bin/dokument \
  && mkdir -p /usr/local/share/fonts && ln -sfn /usr/local/share/dokumente/schriften /usr/local/share/fonts/dokumente \
  && (fc-cache -f >/dev/null 2>&1 || true) \
  && python3 /usr/local/share/dokumente/test.py

# Arbeitsbereich-Werkzeuge für Open WebUI (werkzeug-pruefen): Vorlage muss bestehen, ein Werkzeug mit
# den häufigsten Fehlern (get_valves, kein self.valves, Args-Docstring) muss scheitern. aiohttp wie in
# Open WebUI, falls das Image es nicht mitbringt.
RUN chmod 755 /usr/local/bin/werkzeug-pruefen \
  && (python3 -c 'import aiohttp' 2>/dev/null || pip install --no-cache-dir aiohttp) \
  && werkzeug-pruefen /usr/local/share/vorlagen/owui-werkzeug/rest_api.py \
  && t=$(mktemp -d) && printf '%s\n' 'from pydantic import BaseModel' 'class Tools:' \
       '    class Valves(BaseModel):' '        key: str = ""' \
       '    def abfrage(self, q: str) -> str:' '        """Sucht.' '        Args:' '            q: Suchwort' '        """' \
       '        return self.get_valves().key' > "$t/kaputt.py" \
  && if werkzeug-pruefen "$t/kaputt.py" > "$t/out.txt"; then cat "$t/out.txt"; exit 1; fi \
  && grep -c '^FEHLER' "$t/out.txt" | grep -qx 3 && rm -rf "$t"

# Formulare (formular): eigene venv mit festen Paketen und Prüfsummen, damit die Pakete des
# Images unberührt bleiben; danach Selbsttest mit den Beispielformularen.
RUN python3 -m venv /opt/formular \
  && /opt/formular/bin/pip install --no-cache-dir --require-hashes -r /usr/local/share/formular/requirements.txt \
  && chmod 755 /usr/local/bin/formular \
  && /opt/formular/bin/python3 /usr/local/share/formular/test.py

# Fotos (foto) und Flaschenetiketten (etikett): Bildbearbeitung aus Foto MCP (OpenCV, MediaPipe,
# Quellen per sync_common.py aus foto_mcp) in eigener venv mit festen Paketen und Prüfsummen
# (requirements.txt von .github/scripts/foto_lock.py, dazu zxing-cpp für etikett), Gesichts-,
# Objekt- und Szenenmodell gegen ihre SHA-256 geprüft; danach Selbsttests. libegl1/libgles2: libmediapipe.so ist
# dagegen gelinkt, gerechnet wird auf der CPU.
ARG FOTO_FACE_MODEL_URL=https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
ARG FOTO_FACE_MODEL_SHA256=64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
ARG FOTO_ZOO_COMMIT=48b10fa505aeb51fbd127fc60a5c660040e823b7
ARG FOTO_DET_MODEL=object_detection_nanodet/object_detection_nanodet_2022nov.onnx
ARG FOTO_DET_MODEL_SHA256=4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186
ARG FOTO_CLS_MODEL=image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx
ARG FOTO_CLS_MODEL_SHA256=c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5
RUN set -eu; \
  apt-get update; apt-get install -y --no-install-recommends libegl1 libgles2 fonts-liberation; rm -rf /var/lib/apt/lists/*; \
  python3 -m venv /opt/foto; \
  /opt/foto/bin/pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
    -r /usr/local/share/foto/requirements.txt; \
  mkdir -p /opt/foto/modelle; \
  hol() { curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o "/opt/foto/modelle/$(basename "$1")" "$1"; \
    echo "$2  /opt/foto/modelle/$(basename "$1")" | sha256sum -c -; }; \
  hol "$FOTO_FACE_MODEL_URL" "$FOTO_FACE_MODEL_SHA256"; \
  ZOO="https://media.githubusercontent.com/media/opencv/opencv_zoo/$FOTO_ZOO_COMMIT/models"; \
  hol "$ZOO/$FOTO_DET_MODEL" "$FOTO_DET_MODEL_SHA256"; \
  hol "$ZOO/$FOTO_CLS_MODEL" "$FOTO_CLS_MODEL_SHA256"; \
  chmod 644 /opt/foto/modelle/*; chmod 755 /usr/local/bin/foto /usr/local/bin/etikett; \
  /opt/foto/bin/python3 /usr/local/share/foto/test.py /tmp/foto-test; \
  /opt/foto/bin/python3 /usr/local/share/etikett/test.py /tmp/etikett-test; \
  rm -rf /tmp/foto-test /tmp/etikett-test /tmp/matplotlib-* /tmp/etikett-fc-*

# Mehrbenutzer: Datei-Werkzeuge für Nicht-Administratoren auf Home und Arbeitsbereich beschränken.
# Die .pth lädt ot_schutz in jedem Python des Images, aktiv wird es nur mit OT_SCHUTZ=1 (run.sh).
# Selbsttest gegen die eingebaute Version von Open Terminal: ändert sich deren Datei-API,
# bricht der Bau ab statt still ungeschützt zu laufen.
RUN site=$(python3 -c 'import open_terminal, os; print(os.path.dirname(os.path.dirname(open_terminal.__file__)))') \
  && printf 'import sys; sys.path.append("/usr/local/lib/open-terminal-app"); import ot_schutz\n' > "$site/zz_ot_schutz.pth" \
  && python3 /usr/local/lib/open-terminal-app/test_ot_schutz.py \
  && OT_SCHUTZ=1 python3 -c 'import open_terminal.utils.fs as f; assert f.UserFS._ot_schutz' \
  && python3 -c 'import open_terminal.utils.fs as f; assert not getattr(f.UserFS, "_ot_schutz", False)'

RUN chmod 755 /run.sh /usr/local/bin/terminal-pakete /usr/local/bin/terminal-konten \
  && sed -i -E 's/^#?\s*UID_MIN\s.*/UID_MIN 20000/; s/^#?\s*GID_MIN\s.*/GID_MIN 20000/' /etc/login.defs \
  && grep -E '^(UID|GID)_MIN' /etc/login.defs \
  && printf '\n# Python aus ~/.venv (App Open Terminal)\n. /etc/profile.d/zz-venv.sh\n' >> /etc/bash.bashrc \
  && cat /etc/R/Rprofile.site.ha >> /etc/R/Rprofile.site && rm /etc/R/Rprofile.site.ha \
  && cat /etc/R/Renviron.site.ha >> /etc/R/Renviron.site && rm /etc/R/Renviron.site.ha

HEALTHCHECK --interval=30s --timeout=5s --start-period=2m --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT []
CMD ["/run.sh"]
