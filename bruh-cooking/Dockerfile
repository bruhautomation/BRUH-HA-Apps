# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own (multi-arch manifest).
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
FROM ${BUILD_FROM}

ARG ADDON_VERSION=dev
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    COOKING_HOME=/opt/bruh-cooking

# The integration runs inside Home Assistant Core, not here: this image only
# copies it into /config, announces it, and checks that brAIn is installed.
# Shell, curl and jq are all of that.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    coreutils

COPY custom_components/ /opt/bruh-cooking/custom_components/
COPY CHANGELOG.md /opt/bruh-cooking/CHANGELOG.md
COPY config.yaml /opt/bruh-cooking/config.yaml
COPY run.sh /run.sh

RUN chmod +x /run.sh

# The HA base image provides s6-overlay as /init. Do NOT override ENTRYPOINT.
CMD ["/run.sh"]
