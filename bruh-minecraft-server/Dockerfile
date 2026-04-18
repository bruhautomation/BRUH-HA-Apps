ARG BUILD_FROM
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/java-21-openjdk \
    PATH=/usr/lib/jvm/java-21-openjdk/bin:$PATH \
    MC_SERVER_DIR=/config/minecraft \
    MC_BACKUP_DIR=/config/minecraft-backups \
    MC_PANEL_STATE=/data/panel \
    MC_LOG_FIFO=/tmp/mc-console.fifo

# Core packages: OpenJDK 21 (required for MC 1.20.5+), utilities,
# Python for panel + stats, git for world version control, jq for JSON tooling.
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
    openjdk21-jre-headless \
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

# Python libs used by the ingress panel and RCON client.
# aiohttp ships with base image; we add aiofiles + mcrcon.
RUN pip3 install --break-system-packages --no-cache-dir \
    aiofiles \
    mcrcon \
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
