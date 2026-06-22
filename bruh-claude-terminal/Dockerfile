ARG BUILD_FROM
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
    py3-pillow \
    tzdata \
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

# Install Python packages for HA MCP server, integrations, and YAML validation.
RUN pip3 install --break-system-packages --no-cache-dir \
    websockets \
    aiohttp \
    pyyaml \
    yamllint

# Install Claude Code CLI via npm.
#
# The @anthropic-ai/claude-code npm package installs a prebuilt NATIVE
# binary via platform-specific optionalDependencies (…-linux-x64-musl,
# …-linux-arm64-musl) plus a postinstall (install.cjs). Those musl builds
# need posix_getdents — a symbol musl added in 1.2.6 — so they only run on
# Alpine 3.24+ (this image's base; see build.yaml). On older bases
# (3.19 = musl 1.2.4 … 3.21 = musl 1.2.5) the binary fails to relocate
# ("posix_getdents: symbol not found") and the web terminal opens then
# exits instantly — which is why this add-on was bumped from 3.19 to 3.24.
#
# We install "latest" by default. Pin a specific version with the
# CLAUDE_CODE_VERSION build arg (kept in sync with BRUH_CLAUDE_CODE_VERSION
# in run.sh) if a future release ever regresses.
#
# We symlink the installed binary to /root/.local/bin/claude so the
# claude-run wrapper and persistent symlinks have a stable path.
# NOTE: Do NOT symlink to /usr/local/bin/claude — Claude Code diagnostics
# detects that path as an "npm-global" installation, causing misleading
# warnings.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
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
    && mkdir -p /opt/integrations

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

# Set permissions
RUN chmod +x /run.sh \
    && find /opt/scripts -name "*.sh" -exec chmod +x {} \; \
    && find /opt/scripts -name "*.py" -exec chmod +x {} \; \
    && find /opt/integrations -name "*.sh" -exec chmod +x {} \;

# Use exec form for better signal handling
CMD ["/run.sh"]
