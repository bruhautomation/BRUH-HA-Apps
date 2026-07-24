#!/usr/bin/with-contenv bashio
# ==============================================================================
# BRUH Insights — startup
#
# 1. Prepares persistent storage under /data (HOME for the claude user,
#    generated insights, auth secrets)
# 2. Exports add-on options as BRUH_INSIGHTS_* environment variables
# 3. Launches the ingress panel (aiohttp) on 0.0.0.0:8099 in the foreground
# ==============================================================================
set -e

bashio::log.info "Starting BRUH Insights..."

# ------------------------------------------------------------------------------
# Persistent storage layout
# ------------------------------------------------------------------------------
DATA_HOME="/data/home"
INSIGHTS_DIR="/data/insights"
SECRETS_DIR="/data/secrets"

mkdir -p "${DATA_HOME}" "${INSIGHTS_DIR}" "${SECRETS_DIR}" "${DATA_HOME}/.claude"
chmod 700 "${SECRETS_DIR}"

# The Claude CLI runs as the non-root `claude` user (UID 1000) via su-exec.
# Its HOME lives on the /data volume so CLI state survives restarts.
chown -R claude:claude "${DATA_HOME}" 2>/dev/null || true

# ------------------------------------------------------------------------------
# Options → environment
# ------------------------------------------------------------------------------
export BRUH_INSIGHTS_REFRESH_HOURS="$(bashio::config 'auto_refresh_hours' '24')"
export BRUH_INSIGHTS_HISTORY_DAYS="$(bashio::config 'history_days' '7')"
export BRUH_INSIGHTS_HISTORY_KEEP_RUNS="$(bashio::config 'history_keep_runs' '40')"
export BRUH_INSIGHTS_HISTORY_KEEP_DAYS="$(bashio::config 'history_keep_days' '30')"
export BRUH_INSIGHTS_MODEL="$(bashio::config 'model' '')"
export BRUH_INSIGHTS_TIMEOUT_MIN="$(bashio::config 'generation_timeout_minutes' '8')"
export BRUH_INSIGHTS_LOG_LEVEL="$(bashio::config 'log_level' 'info')"

export BRUH_INSIGHTS_HOME="${DATA_HOME}"
export BRUH_INSIGHTS_DIR="${INSIGHTS_DIR}"
export BRUH_INSIGHTS_SECRETS="${SECRETS_DIR}"

# Add-on version for browser cache-busting of panel assets
if bashio::supervisor.ping 2>/dev/null; then
    export ADDON_VERSION="$(bashio::addon.version 2>/dev/null || echo 'dev')"
else
    export ADDON_VERSION="dev"
fi

# Timezone from the Supervisor so timestamps in insights match the house
if bashio::supervisor.ping 2>/dev/null; then
    TZ_VALUE="$(bashio::info.timezone 2>/dev/null || true)"
    if [ -n "${TZ_VALUE}" ] && [ "${TZ_VALUE}" != "null" ]; then
        export TZ="${TZ_VALUE}"
    fi
fi

bashio::log.info "Options: refresh=${BRUH_INSIGHTS_REFRESH_HOURS}h history=${BRUH_INSIGHTS_HISTORY_DAYS}d model='${BRUH_INSIGHTS_MODEL:-default}' timeout=${BRUH_INSIGHTS_TIMEOUT_MIN}m"

# ------------------------------------------------------------------------------
# Claude CLI sanity check (non-fatal — the panel shows setup guidance)
# ------------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
    CLAUDE_VERSION="$(su-exec claude env HOME="${DATA_HOME}" claude --version 2>/dev/null | head -1 || echo 'unknown')"
    bashio::log.info "Claude Code CLI: ${CLAUDE_VERSION}"
    export BRUH_CLAUDE_VERSION="${CLAUDE_VERSION}"
else
    bashio::log.warning "Claude Code CLI not found on PATH — insights generation will fail"
fi

# ------------------------------------------------------------------------------
# Launch the ingress panel (foreground — its lifetime is the add-on's lifetime)
# ------------------------------------------------------------------------------
bashio::log.info "Starting ingress panel on 0.0.0.0:8099"
exec python3 /opt/panel/server.py
