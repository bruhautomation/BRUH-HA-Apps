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
    JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    MC_SERVER_DIR=/config/minecraft \
    MC_BACKUP_DIR=/config/minecraft-backups \
    MC_PANEL_STATE=/data/panel \
    MC_LOG_FIFO=/tmp/mc-console.fifo

# Core packages: utilities, Python for panel + stats, git for world version
# control, jq for JSON tooling. Java is installed below from Eclipse Temurin
# (Alpine doesn't ship a recent enough JDK; see the next RUN block).
RUN apk add --no-cache \
    bash \
    curl \
    wget \
    jq \
    git \
    git-lfs \
    tar \
    gzip \
    xz \
    zip \
    unzip \
    python3 \
    py3-pip \
    py3-aiohttp \
    py3-yaml \
    py3-requests \
    coreutils \
    procps \
    tzdata \
    su-exec \
    tmux \
    socat \
    iproute2 \
    inotify-tools

# Java 25 from Eclipse Temurin (Adoptium). Why not Alpine's openjdk21?
# When Mojang shipped Minecraft 26.1, plugins that support the new
# protocol (ViaVersion, ViaBackwards, recent VeinMiner, etc.) started
# being compiled against Java 25 — class file version 69. Loading them
# on Java 21 fails with `UnsupportedClassVersionError`, which Paper logs
# as `[EntrypointUtil] ... has been compiled by a more recent version of
# the Java Runtime`. The plugin is silently skipped, so e.g. ViaVersion
# never loads, ViaBackwards then fails with "Unknown/missing dependency
# plugins: [ViaVersion]", and Bedrock clients on 26.1 still get kicked
# with "Outdated server! I'm still on 1.21.11". Java 25 also runs
# Paper 1.21.11 and earlier MC versions just fine — class files are
# backwards-compatible. Alpine 3.22 still only ships up through
# openjdk21, so we install Temurin's official Alpine-musl JRE directly.
ARG TEMURIN_VERSION=25.0.3+9
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64)  jdk_arch=x64 ;; \
        aarch64) jdk_arch=aarch64 ;; \
        *)       echo "unsupported arch: $arch"; exit 1 ;; \
    esac; \
    plain_ver="$(printf '%s' "${TEMURIN_VERSION}" | tr '+' '_')"; \
    enc_ver="$(printf '%s' "${TEMURIN_VERSION}" | sed 's/+/%2B/')"; \
    url="https://github.com/adoptium/temurin25-binaries/releases/download/jdk-${enc_ver}/OpenJDK25U-jre_${jdk_arch}_alpine-linux_hotspot_${plain_ver}.tar.gz"; \
    mkdir -p /opt/java/openjdk; \
    curl -fsSL -o /tmp/jre.tar.gz "$url"; \
    tar -xzf /tmp/jre.tar.gz -C /opt/java/openjdk --strip-components=1; \
    rm /tmp/jre.tar.gz; \
    java -version

# Python libs used by the ingress panel.
# aiohttp ships with base image; we add aiofiles for async file IO and
# mcstatus for the status-ping probe. The RCON client is built-in
# (scripts/rcon_client.py) so we no longer depend on `mcrcon`, which uses
# signal.SIGALRM for timeouts and breaks in aiohttp worker threads.
RUN pip3 install --break-system-packages --no-cache-dir \
    aiofiles \
    mcstatus

# Dedicated, non-root minecraft user (UID 1000). The JVM should not run as root.
RUN addgroup -g 1000 minecraft \
    && adduser -D -u 1000 -G minecraft -s /bin/bash minecraft

# Filesystem layout
RUN mkdir -p \
      /opt/bruh-mc/scripts \
      /opt/bruh-mc/panel \
      /opt/bruh-mc/integrations \
      /opt/bruh-mc/custom_components \
      /config/minecraft \
      /config/minecraft-backups \
      /data/panel \
      /data/server-cache

WORKDIR /config/minecraft

# Startup entrypoint
COPY run.sh /run.sh

# Modular scripts, panel assets, integrations, custom integration payload
COPY scripts/ /opt/bruh-mc/scripts/
COPY panel/ /opt/bruh-mc/panel/
COPY integrations/ /opt/bruh-mc/integrations/
COPY custom_components/ /opt/bruh-mc/custom_components/

# Bake config.yaml into the image so run.sh can read the add-on version at
# runtime. build.yaml passes `ADDON_VERSION: "{{ version }}"` but not every
# Supervisor build path renders the Jinja template — local builds and some
# Supervisor releases leave the literal string `{{ version }}` in the ENV,
# which then shows up in the startup banner. Reading config.yaml at runtime
# is authoritative and sidesteps the templating question entirely.
COPY config.yaml /opt/bruh-mc/config.yaml

# Ensure every shell / python entrypoint is executable
RUN chmod +x /run.sh \
    && find /opt/bruh-mc/scripts -type f \( -name "*.sh" -o -name "*.py" \) -exec chmod +x {} \; \
    && find /opt/bruh-mc/integrations -type f -name "*.sh" -exec chmod +x {} \; \
    && find /opt/bruh-mc/panel -type f -name "*.py" -exec chmod +x {} \;

# Drop default perms on /data + /config paths the minecraft user manages.
# The add-on startup will re-chown at runtime because the volumes are bind-mounted.
RUN chown -R minecraft:minecraft /opt/bruh-mc /data /config/minecraft /config/minecraft-backups

# The HA base image provides s6-overlay as /init, which handles signals and
# sets up /run/s6/container_environment so `with-contenv bashio` works. Do
# NOT override ENTRYPOINT — it would bypass s6 init and break bashio.
CMD ["/run.sh"]
