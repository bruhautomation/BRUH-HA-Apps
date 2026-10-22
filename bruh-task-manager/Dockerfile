# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    TASK_MANAGER_HOME=/opt/bruh-task-manager

# Everything this add-on reads is /proc and the Supervisor's HTTP API, so the
# image is Python, aiohttp and nothing else. No psutil: what it would give us
# is a parser for the same /proc files, and reading them directly is what
# lets the panel say exactly which file a figure came from — and lets the
# tests point the whole reader at a fake /proc.
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    coreutils \
    tzdata \
    python3 \
    py3-aiohttp \
    py3-yaml

RUN mkdir -p /opt/bruh-task-manager/panel /opt/bruh-task-manager/custom_components /data

WORKDIR /opt/bruh-task-manager

COPY run.sh /run.sh
COPY panel/ /opt/bruh-task-manager/panel/
COPY custom_components/ /opt/bruh-task-manager/custom_components/
COPY config.yaml /opt/bruh-task-manager/config.yaml

RUN chmod +x /run.sh

# NOT s6-overlay. The base image's ENTRYPOINT is /init, and s6-overlay
# refuses to run unless it is PID 1 ("s6-overlay-suexec: fatal: can only run
# as pid 1"). With Protection mode off the Supervisor starts this container
# in the HOST's PID namespace (host_pid in config.yaml), where PID 1 is the
# host's own init — so under /init, Level 2 could never start. run.sh is the
# entrypoint instead, run by bashio directly rather than through with-contenv:
# the Supervisor's token reaches it as an ordinary environment variable, so
# nothing here needs s6's copy of the environment. config.yaml's `init:
# false` keeps Docker from putting tini in front of it, and run.sh traps TERM
# itself.
ENTRYPOINT ["/run.sh"]
CMD []
