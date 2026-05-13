ARG BUILD_FROM

# ---------- Stage 1: build the chat UI ----------
# Astro + Preact static bundle. We compile in a clean node image and copy the
# `dist/` output into the runtime image — keeps node_modules out of the final
# layer.
FROM node:20-alpine AS chat-ui-builder
WORKDIR /build
COPY chat-ui/package.json ./
# `npm install` (not `npm ci`) so the build works without a checked-in
# package-lock.json. If one ends up committed, npm respects it automatically.
RUN npm install --no-audit --no-fund --loglevel=error
COPY chat-ui/ ./
RUN npm run build && ls -la dist

# ---------- Stage 2: runtime image ----------
FROM ${BUILD_FROM}

# Install system packages and development tools
RUN apk add --no-cache \
    bash \
    curl \
    nano \
    nodejs \
    npm \
    python3 \
    py3-pip \
    py3-requests \
    py3-aiohttp \
    py3-yaml \
    py3-beautifulsoup4 \
    git \
    vim \
    wget \
    jq \
    tree \
    tmux \
    yq \
    ttyd \
    openssh-client \
    inotify-tools \
    socat \
    su-exec \
    rsync \
    sqlite

# Install websocat from community repo (may not be in all base images)
RUN apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community \
    websocat 2>/dev/null || true

# Install Python packages for HA MCP server, integrations, YAML validation,
# and the chat-server (FastAPI + uvicorn). Pinning fastapi/uvicorn so the
# Alpine wheel availability matches and the WS event shapes don't drift
# between addon releases.
RUN pip3 install --break-system-packages --no-cache-dir \
    websockets \
    aiohttp \
    pyyaml \
    yamllint \
    fastapi==0.115.5 \
    uvicorn==0.32.1

# Install Claude Code CLI via npm (not the binary installer).
# The binary installer downloads a native musl build that may require
# symbols missing from Alpine 3.19's musl 1.2.4 (e.g. posix_getdents).
# npm install uses the Node.js package which works on any musl version.
#
# We symlink the npm-installed binary to /root/.local/bin/claude so the
# claude-run wrapper and persistent symlinks have a stable path.
# NOTE: Do NOT symlink to /usr/local/bin/claude — Claude Code diagnostics
# detects that path as an "npm-global" installation, causing misleading
# warnings.
RUN npm install -g @anthropic-ai/claude-code \
    && mkdir -p /root/.local/bin \
    && ln -sf "$(readlink -f "$(command -v claude)")" /root/.local/bin/claude \
    && chmod 755 /root /root/.local /root/.local/bin

# Remove config directories that the Claude Code installer may have created.
# At runtime, run.sh symlinks these paths to persistent storage (/data volume).
# If real directories exist here, `ln -sfn` cannot replace them with symlinks,
# causing Claude Code to find an empty config dir instead of stored credentials.
RUN rm -rf /root/.config/claude /root/.config/anthropic /root/.claude 2>/dev/null; true

# Create non-root user for Claude Code
# Claude Code should run as non-root inside the container
RUN adduser -D -s /bin/bash -u 1000 claude

# Create directory structure
RUN mkdir -p /config/claude-config \
    && mkdir -p /opt/scripts \
    && mkdir -p /opt/ha-mcp-server \
    && mkdir -p /opt/integrations \
    && mkdir -p /opt/chat-server \
    && mkdir -p /opt/chat-ui-dist

WORKDIR /config

# Copy startup script
COPY run.sh /run.sh

# Copy modular scripts
COPY scripts/ /opt/scripts/

# Copy HA MCP server
COPY ha-mcp-server/ /opt/ha-mcp-server/

# Copy integrations
COPY integrations/ /opt/integrations/

# Copy custom HA integration (deployed to /config/custom_components at runtime)
COPY custom_components/ /opt/custom_components/

# Copy ttyd asset template. run.sh runs scripts/build-mobile-index.py at
# startup to probe ttyd's bundle filename and render the final index.html
# so ttyd --index can serve a mobile toolbar + iOS dictation fix on top
# of whatever frontend bundle ttyd happens to ship this version.
COPY ttyd-assets/ /opt/ttyd-assets/

# Copy chat server (FastAPI). Mounted at /opt/chat-server; uvicorn is
# launched from run.sh when `enable_chat_ui` is true.
COPY chat-server/ /opt/chat-server/

# Copy the chat UI bundle from the builder stage. STATIC_DIR in app.py
# (/opt/chat-ui-dist) points here; missing index.html surfaces a clean
# 500 with a hint instead of a silent black screen.
COPY --from=chat-ui-builder /build/dist /opt/chat-ui-dist

# Set permissions
RUN chmod +x /run.sh \
    && find /opt/scripts -name "*.sh" -exec chmod +x {} \; \
    && find /opt/scripts -name "*.py" -exec chmod +x {} \; \
    && find /opt/integrations -name "*.sh" -exec chmod +x {} \;

# Use exec form for better signal handling
CMD ["/run.sh"]
