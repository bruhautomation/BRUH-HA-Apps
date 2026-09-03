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
    BRUH_PRINT_HOME=/opt/bruh-print \
    BRUH_PRINT_DATA=/data

# Core packages.
#
# `libusb` is the whole point: there is no CUPS here and no DYMO driver —
# panel/dymo/ speaks the LabelWriter's raster protocol directly over a bulk
# USB endpoint, which is about 300 lines and no daemon. A print server inside
# a container would add a spooler, a PPD, a filter chain and a second place
# for a job to get stuck, to produce the same bytes.
#
# `py3-pillow` renders the artwork and `font-dejavu` gives it something to
# render with — a container with no fonts produces perfectly valid blank
# labels. `ttf-liberation` is the second family so the font picker has more
# than one answer.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    coreutils \
    tzdata \
    su-exec \
    libusb \
    python3 \
    py3-pip \
    py3-aiohttp \
    py3-yaml \
    py3-pillow \
    font-dejavu \
    ttf-liberation

# pyusb is the libusb binding; qrcode is a pure-Python QR encoder (Code 128
# is written out in panel/render/barcode.py — the encoder is the easy half
# and the mode switching is the half that matters).
RUN pip3 install --break-system-packages --no-cache-dir \
    pyusb \
    qrcode

# A non-root user for the HA bridge — the one process here that reads files
# written from outside this container. The panel is NOT this user; see the
# long note above `start_panel` in run.sh for why a process that opens
# /dev/bus/usb cannot be.
RUN addgroup -g 1000 bruhprint \
    && adduser -D -u 1000 -G bruhprint -s /bin/bash bruhprint

RUN mkdir -p \
      /opt/bruh-print/panel \
      /opt/bruh-print/integrations \
      /opt/bruh-print/custom_components \
      /opt/bruh-print/lovelace \
      /data

WORKDIR /opt/bruh-print

COPY run.sh /run.sh
COPY panel/ /opt/bruh-print/panel/
COPY integrations/ /opt/bruh-print/integrations/
COPY custom_components/ /opt/bruh-print/custom_components/
COPY lovelace/ /opt/bruh-print/lovelace/

# Baked in so run.sh can read the add-on version at runtime — `{{ version }}`
# is not rendered on every Supervisor build path, and reading config.yaml is
# authoritative either way.
COPY config.yaml /opt/bruh-print/config.yaml

RUN chmod +x /run.sh \
    && find /opt/bruh-print -type f -name "*.py" -exec chmod +x {} \; \
    && chown -R bruhprint:bruhprint /opt/bruh-print /data

# The HA base image provides s6-overlay as /init, which handles signals and
# sets up /run/s6/container_environment so `with-contenv bashio` works. Do
# NOT override ENTRYPOINT — it would bypass s6 init and break bashio.
CMD ["/run.sh"]
