# Foto MCP: eigener MCP-Server (Python, OpenCV, MediaPipe) hinter mcp-auth-proxy.
# Python-Pakete mit festen Versionen und Prüfsummen (requirements.txt, erzeugt von
# .github/scripts/foto_lock.py), Gesichtsmodell und Proxy gegen ihre SHA-256 geprüft.
# libegl1/libgles2: libmediapipe.so ist dagegen gelinkt, gerechnet wird auf der CPU.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG FACE_MODEL_URL=https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
ARG FACE_MODEL_SHA256=64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
ARG PROXY_VERSION=2.10.2
ARG PROXY_SHA256_ARM64=924c5335e5f684eb22c681cca1daff86d96fa35f644950cbd8f4c8f3e290bc3d
ARG PROXY_SHA256_AMD64=1c76b230fdb6c536a0912c059232cba2229acbcf1f02a11a5d0664781326bcd6

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/kleinhansda/ha-mcp-addons"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY requirements.txt /tmp/requirements.txt

RUN set -eu; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl jq python3 python3-venv \
    libegl1 libgles2; \
  case "$(uname -m)" in \
    aarch64) P=arm64; PSUM="$PROXY_SHA256_ARM64" ;; \
    x86_64)  P=amd64; PSUM="$PROXY_SHA256_AMD64" ;; \
    *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;; \
  esac; \
  python3 -m venv /opt/venv; \
  /opt/venv/bin/pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
    -r /tmp/requirements.txt; \
  rm /tmp/requirements.txt; \
  /opt/venv/bin/pip uninstall -y pip setuptools >/dev/null 2>&1 || true; \
  echo "python $(python3 -c 'import platform; print(platform.python_version())')" >> /usr/local/share/mcp-versions; \
  /opt/venv/bin/python -c 'import cv2, mediapipe; print("opencv", cv2.__version__); print("mediapipe", mediapipe.__version__)' \
    >> /usr/local/share/mcp-versions; \
  mkdir -p /opt/foto; \
  curl -fsSL -o /opt/foto/face_landmarker.task "$FACE_MODEL_URL"; \
  echo "$FACE_MODEL_SHA256  /opt/foto/face_landmarker.task" | sha256sum -c -; \
  curl -fsSL -o /usr/local/bin/mcp-auth-proxy \
    "https://github.com/sigbit/mcp-auth-proxy/releases/download/v$PROXY_VERSION/mcp-auth-proxy-linux-$P"; \
  echo "$PSUM  /usr/local/bin/mcp-auth-proxy" | sha256sum -c -; \
  chmod 755 /usr/local/bin/mcp-auth-proxy; \
  echo "mcp-auth-proxy $PROXY_VERSION" >> /usr/local/share/mcp-versions; \
  apt-get purge -y --auto-remove curl; \
  rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 755 /run.sh /usr/local/bin/mcp-selftest \
  && echo "foto-mcp ${BUILD_VERSION}" >> /usr/local/share/mcp-versions

ENV FOTO_MODEL=/opt/foto/face_landmarker.task \
    FOTO_VERSION=${BUILD_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

CMD ["/run.sh"]
