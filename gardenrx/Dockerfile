# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own (multi-arch manifest).
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24

# ── Build the app ────────────────────────────────────────────────────────
# A separate stage so the image carries the standalone server and none of the
# toolchain. Alpine on both sides, so anything native that Next traces into
# the standalone tree is built for the same libc it runs on.
FROM node:22-alpine AS build
WORKDIR /src
COPY app/package.json app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ ./
# The ingress path belongs to the install, not the image, so the app is built
# under a placeholder that run.sh replaces (gateway/prepare-base.mjs). The
# database path keeps a build that happens to open it out of the image.
ENV NEXT_TELEMETRY_DISABLED=1 \
    GARDENRX_BASE_PATH=/__gardenrx_base_path__ \
    GARDENRX_DB_PATH=/tmp/build.db
RUN npx next build \
    && cp -a .next/static .next/standalone/.next/static \
    && cp -a public .next/standalone/public \
    && mkdir -p .next/standalone/seed \
    && cp -a seed/catalog.json .next/standalone/seed/catalog.json

# ── The add-on ───────────────────────────────────────────────────────────
FROM ${BUILD_FROM}

ARG ADDON_VERSION=dev
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    GARDENRX_HOME=/opt/gardenrx \
    NEXT_TELEMETRY_DISABLED=1

# `nodejs` runs the app and the gateway. The database is Node's built-in
# node:sqlite, so there is no native module and no sqlite package to install.
# `icu-data-full` because Alpine's Node otherwise carries English-only locale
# data, and the app formats dates and times by locale and time zone.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    coreutils \
    tzdata \
    su-exec \
    nodejs \
    icu-data-full

RUN addgroup -g 1000 gardenrx \
    && adduser -D -u 1000 -G gardenrx -s /bin/bash gardenrx

COPY --from=build /src/.next/standalone /opt/gardenrx/app-build
COPY gateway/ /opt/gardenrx/gateway/
COPY custom_components/ /opt/gardenrx/custom_components/
COPY CHANGELOG.md /opt/gardenrx/CHANGELOG.md
COPY config.yaml /opt/gardenrx/config.yaml
COPY run.sh /run.sh

RUN chmod +x /run.sh \
    && node -e "process.getBuiltinModule('node:sqlite') || process.exit(1)" \
    && mkdir -p /data

# The HA base image provides s6-overlay as /init. Do NOT override ENTRYPOINT.
CMD ["/run.sh"]
