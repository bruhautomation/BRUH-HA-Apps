# Debian, not Alpine: Google Chrome is published for Linux as a glibc .deb
# for x86-64, and the Claude in Chrome extension is documented for Google
# Chrome (or Edge), not Chromium. Alpine's musl runs neither.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
ARG ADDON_VERSION=dev
FROM ${BUILD_FROM}

ARG ADDON_VERSION
ENV ADDON_VERSION=${ADDON_VERSION} \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    BROWSER_HOME=/opt/bruh-browser

# The screen: Xvfb is the display Chrome draws on, openbox keeps its windows
# maximised, x11vnc reads the screen on loopback, and noVNC is the browser
# half the panel serves (the panel bridges its websocket, as BRUH Bambu
# Studio's does: no websockify). xterm is the one window Claude Code's own
# sign-in (`/login`) happens in; xdg-utils is how that sign-in opens its page
# in this same Chrome. Node and npm are only for installing Claude Code.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl jq gnupg \
      xvfb x11vnc openbox x11-utils xdotool dbus-x11 xterm xdg-utils \
      novnc \
      fonts-dejavu-core fonts-liberation2 fonts-noto-color-emoji \
      python3 python3-aiohttp \
      nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome stable, Google's own .deb (apt resolves its dependencies).
# The .deb also adds Google's apt source, which nothing here uses again.
RUN curl -fsSL -o /tmp/chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb /etc/apt/sources.list.d/google-chrome.list \
    && rm -rf /var/lib/apt/lists/* \
    && google-chrome --version

# Chrome's managed policy: the Claude extension is force-installed from the
# Web Store, remote debugging is off for good, and nothing syncs a Google
# account into this container. Root-owned, so the browser user cannot edit it.
COPY chrome-policy.json /etc/opt/chrome/policies/managed/bruh-browser.json

# Claude Code, the way brAIn installs it: the npm package, which fetches the
# platform's native binary. Pin with CLAUDE_CODE_VERSION if a release ever
# regresses; --chrome needs a recent one.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && claude --version \
    && claude --help | grep -q -- '--chrome'

# The one user everything runs as. Chrome, the X server, Claude Code and the
# panel all run unprivileged; run.sh uses root only to lay out /data.
RUN groupadd -g 1000 browser \
    && useradd -m -u 1000 -g browser -s /bin/bash -d /data/home browser

RUN mkdir -p /opt/bruh-browser/panel /data

WORKDIR /opt/bruh-browser

COPY run.sh /run.sh
COPY openbox-rc.xml /opt/bruh-browser/openbox-rc.xml
COPY open-in-chrome.sh /opt/bruh-browser/open-in-chrome.sh
COPY panel/ /opt/bruh-browser/panel/
COPY config.yaml /opt/bruh-browser/config.yaml

RUN chmod +x /run.sh /opt/bruh-browser/open-in-chrome.sh \
    && find /opt/bruh-browser -type f -name "*.py" -exec chmod +x {} \;

# s6-overlay is /init in the HA base image; overriding ENTRYPOINT would
# bypass it and break bashio.
CMD ["/run.sh"]
