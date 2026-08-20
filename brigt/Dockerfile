# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own (multi-arch manifest —
# docker resolves amd64/aarch64 automatically). Older Supervisors still
# override this per-arch via build.yaml.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    BRIGT_HOME=/opt/brigt \
    BRIGT_DATA=/data

# Core packages: Python + aiohttp for the ingress panel, jq for JSON
# tooling in run.sh, su-exec to drop privileges, numpy for the calibration
# cross-correlation and the analyzer's DSP, ffmpeg to decode whatever the
# music folder actually contains. The beat tracker is pure numpy on
# purpose — librosa needs numba (painful on musl) and the aubio python
# binding isn't packaged here, so the analyzer depends on nothing this
# image doesn't already carry.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    coreutils \
    tzdata \
    su-exec \
    python3 \
    py3-pip \
    py3-aiohttp \
    py3-yaml \
    py3-numpy \
    ffmpeg

# Python libs used by the ingress panel: async file IO, and the LIFX LAN
# protocol library Home Assistant itself uses (discovery + product caps —
# the playback engine sends its own pre-serialized packets).
RUN pip3 install --break-system-packages --no-cache-dir \
    aiofiles \
    aiolifx \
    mutagen

# Dedicated, non-root brigt user (UID 1000). The panel should not run as root.
RUN addgroup -g 1000 brigt \
    && adduser -D -u 1000 -G brigt -s /bin/bash brigt

# Filesystem layout
RUN mkdir -p \
      /opt/brigt/panel \
      /opt/brigt/integrations \
      /opt/brigt/custom_components \
      /data

WORKDIR /opt/brigt

# Startup entrypoint
COPY run.sh /run.sh

# Panel, bridge, custom integration payload
COPY panel/ /opt/brigt/panel/
COPY integrations/ /opt/brigt/integrations/
COPY custom_components/ /opt/brigt/custom_components/

# Bake config.yaml into the image so run.sh can read the add-on version at
# runtime — `{{ version }}` templating is not rendered on every Supervisor
# build path, and reading config.yaml is authoritative either way.
COPY config.yaml /opt/brigt/config.yaml

RUN chmod +x /run.sh \
    && find /opt/brigt/panel -type f -name "*.py" -exec chmod +x {} \; \
    && find /opt/brigt/integrations -type f -name "*.py" -exec chmod +x {} \; \
    && chown -R brigt:brigt /opt/brigt /data

# The HA base image provides s6-overlay as /init, which handles signals and
# sets up /run/s6/container_environment so `with-contenv bashio` works. Do
# NOT override ENTRYPOINT — it would bypass s6 init and break bashio.
CMD ["/run.sh"]
