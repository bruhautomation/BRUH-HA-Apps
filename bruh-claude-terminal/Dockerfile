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
    su-exec

# Install websocat from community repo (may not be in all base images)
RUN apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community \
    websocat 2>/dev/null || true

# Install Python packages for HA MCP server, integrations, and YAML validation
RUN pip3 install --break-system-packages --no-cache-dir \
    websockets \
    aiohttp \
    pyyaml \
    yamllint

# Install Claude Code CLI using native installer
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && chmod 755 /root /root/.local /root/.local/bin

# Remove config directories that the Claude Code installer may have created.
# At runtime, run.sh symlinks these paths to persistent storage (/data volume).
# If real directories exist here, `ln -sfn` cannot replace them with symlinks,
# causing Claude Code to find an empty config dir instead of stored credentials.
RUN rm -rf /root/.config/claude /root/.config/anthropic /root/.claude 2>/dev/null; true

# Create non-root user for Claude Code
# --dangerously-skip-permissions requires non-root execution
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

# Set permissions
RUN chmod +x /run.sh \
    && find /opt/scripts -name "*.sh" -exec chmod +x {} \; \
    && find /opt/integrations -name "*.sh" -exec chmod +x {} \;

# Use exec form for better signal handling
CMD ["/run.sh"]
