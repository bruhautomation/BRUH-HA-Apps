# Default base: Supervisor 2026.04.0+ no longer reads build.yaml or passes
# BUILD_FROM, so the default must stand on its own (multi-arch manifest —
# docker resolves amd64/aarch64 automatically). Older Supervisors still
# override this per-arch via build.yaml.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
FROM ${BUILD_FROM}

# Install system packages. Alpine 3.24+ is required for the Claude Code
# native binary (musl 1.2.6 / posix_getdents — see bruh-claude-terminal).
RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    nodejs \
    npm \
    python3 \
    py3-pip \
    py3-aiohttp \
    su-exec \
    tzdata

# Install Claude Code CLI via npm and give it a stable path.
# NOTE: Do NOT symlink to /usr/local/bin/claude — Claude Code diagnostics
# detects that path as an "npm-global" installation, causing misleading
# warnings.
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && mkdir -p /root/.local/bin \
    && ln -sf "$(readlink -f "$(command -v claude)")" /root/.local/bin/claude \
    && chmod 755 /root /root/.local /root/.local/bin

# Non-root user that runs the Claude CLI (mirrors bruh-claude-terminal)
RUN adduser -D -s /bin/bash -u 1000 claude

# Panel + engine
RUN mkdir -p /opt/panel
COPY panel/ /opt/panel/
COPY run.sh /run.sh
RUN chmod +x /run.sh /opt/panel/server.py

# Use exec form for better signal handling
CMD ["/run.sh"]
