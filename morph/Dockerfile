# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own (multi-arch manifest).
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    MORPH_HOME=/opt/morph \
    MORPH_DATA=/data

# `git` is the dashboard's history: every change to /config/morph — made in
# Edit, by brAIn, or by a suggestion somebody approved — is one commit, and
# Undo is a revert of it. aiohttp is the Core WebSocket client (registries,
# for the first dashboard) and the loopback health server.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    git \
    coreutils \
    tzdata \
    python3 \
    py3-aiohttp \
    py3-yaml

RUN mkdir -p /opt/morph /data
WORKDIR /opt/morph

COPY run.sh /run.sh
COPY service/ /opt/morph/service/
COPY defaults/ /opt/morph/defaults/
COPY custom_components/ /opt/morph/custom_components/

# Baked in so run.sh can read the version at runtime — `{{ version }}` is not
# rendered on every Supervisor build path.
COPY config.yaml /opt/morph/config.yaml

RUN chmod +x /run.sh

# s6-overlay is /init in the base image; do NOT override ENTRYPOINT.
CMD ["/run.sh"]
