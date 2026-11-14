# Foto MCP: eigener MCP-Server (Python, OpenCV, MediaPipe) hinter mcp-auth-proxy.
# Python-Pakete mit festen Versionen und Prüfsummen (requirements.txt, erzeugt von
# .github/scripts/foto_lock.py), Modelle und Proxy gegen ihre SHA-256 geprüft.
# Objekt- und Szenenmodell aus dem OpenCV Model Zoo (Apache-2.0), fester Commit:
# NanoDet-Plus (COCO, 3,8 MB) und MobileNetV2 (ImageNet, 14 MB), beide über cv2.dnn.
# libegl1/libgles2: libmediapipe.so ist dagegen gelinkt, gerechnet wird auf der CPU.
FROM debian:bookworm-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

ARG FACE_MODEL_URL=https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
ARG FACE_MODEL_SHA256=64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
ARG ZOO_COMMIT=48b10fa505aeb51fbd127fc60a5c660040e823b7
ARG DET_MODEL=object_detection_nanodet/object_detection_nanodet_2022nov.onnx
ARG DET_MODEL_SHA256=4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186
ARG CLS_MODEL=image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx
ARG CLS_MODEL_SHA256=c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5
ARG PROXY_VERSION=2.10.6
ARG PROXY_SHA256_ARM64=10370ef8e9daee2b7575959680755f932adfdcd724bba67335bdd3c97da72ecb
ARG PROXY_SHA256_AMD64=f690e2125794f00b2bc3ef980d1514766e6bc02562c47a4783455893dda775e9

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
  ZOO="https://media.githubusercontent.com/media/opencv/opencv_zoo/$ZOO_COMMIT/models"; \
  curl -fsSL -o "/opt/foto/$(basename "$DET_MODEL")" "$ZOO/$DET_MODEL"; \
  echo "$DET_MODEL_SHA256  /opt/foto/$(basename "$DET_MODEL")" | sha256sum -c -; \
  curl -fsSL -o "/opt/foto/$(basename "$CLS_MODEL")" "$ZOO/$CLS_MODEL"; \
  echo "$CLS_MODEL_SHA256  /opt/foto/$(basename "$CLS_MODEL")" | sha256sum -c -; \
  echo "opencv_zoo ${ZOO_COMMIT:0:7} (nanodet-plus, mobilenetv2)" >> /usr/local/share/mcp-versions; \
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
    FOTO_DETEKTOR=/opt/foto/object_detection_nanodet_2022nov.onnx \
    FOTO_KLASSIFIKATOR=/opt/foto/image_classification_mobilenetv2_2022apr.onnx \
    FOTO_VERSION=${BUILD_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

CMD ["/run.sh"]
