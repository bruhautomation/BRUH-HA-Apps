# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

This repository contains three Home Assistant add-ons by BRUH Automation:

- **BRUH Terminal** (`bruh-claude-terminal/`) - an enhanced Claude Code terminal for Home Assistant with native HA API access, auto-backup, context generation, and deep HA integration. The primary add-on; its architecture is documented in detail below.
- **BRUH Insights** (`bruh-insights/`) - an AI insights dashboard: Claude analyzes HA data (states, history, statistics) and generates interactive visualizations served through an Ingress panel (`bruh-insights/panel/`).
- **BRUH Minecraft** (`bruh-minecraft-server/`) - a Minecraft Java Edition server with an ingress management panel, git-based world version control, RCON, and a companion `bruh_minecraft` custom integration.

Shared brand sources live in `branding/` (Solid Blocks icon SVGs) and `brands/` (home-assistant/brands submission assets); cross-add-on tests live in `tests/`.

## Repository Structure

```
BRUH-HA-Apps/
├── repository.yaml              # HA add-on repository metadata
├── bruh-claude-terminal/        # Main add-on
│   ├── config.yaml              # HA add-on configuration manifest
│   ├── build.yaml               # Multi-arch build config
│   ├── Dockerfile               # Container build definition
│   ├── run.sh                   # Main startup/entrypoint script
│   ├── ha-mcp-server/           # MCP server for HA API access
│   │   └── ha_mcp_server.py     # Python MCP server (stdio-based)
│   ├── scripts/                 # Shell scripts and tools
│   │   ├── ha-reload.sh         # Config reload CLI tool
│   │   ├── ha-log.sh            # Log viewer CLI tool
│   │   ├── ha-context-gen.sh    # CLAUDE.md context generator
│   │   ├── ha-backup.sh         # Manual backup tool
│   │   ├── ha-backup-watcher.sh # Background auto-backup daemon
│   │   ├── ha-addon.sh / ha-entity.sh / ha-service.sh / ha-notify.sh / ha-share.sh  # HA helper CLIs
│   │   ├── ha-yaml-check.sh     # YAML validation CLI
│   │   ├── ha-selftest.sh       # In-situ end-to-end diagnostic (MCP, auth, listeners)
│   │   ├── usage-limits-tracker.py   # Background Anthropic usage-limits daemon
│   │   ├── build-mobile-index.py     # Splices mobile UI into ttyd's HTML at startup
│   │   ├── claude-session-picker.sh  # Enhanced session picker
│   │   ├── claude-auth-helper.sh     # Auth workaround helper
│   │   ├── health-check.sh      # Startup diagnostics
│   │   ├── persist-install.sh   # Persistent package manager
│   │   ├── ha-api-examples.sh   # API usage examples
│   │   └── tmux.conf            # tmux configuration
│   ├── ttyd-assets/             # Mobile toolbar + iOS fixes injected into ttyd
│   │   └── inject.html          # Toolbar, swipe-scroll, OSC-52 copy, dictation fix
│   ├── integrations/            # HA integrations (add-on side)
│   │   ├── assist-worker-pool.py  # Fast mode: pre-warmed persistent Claude workers (default)
│   │   ├── assist-listener.sh   # Classic conversation listener (assist_fast_mode: false)
│   │   └── automation-listener.sh # Task request file watcher
│   └── custom_components/       # HA custom integration (deployed at runtime)
│       └── bruh_claude/
│           ├── __init__.py      # Integration setup + service registration
│           ├── manifest.json    # HA integration metadata
│           ├── config_flow.py   # UI config flow
│           ├── conversation.py  # ConversationEntity for Assist
│           ├── power_tools.py   # BRUH Power Tools: 36 registry admin services (from Spook, MIT)
│           ├── sensor.py        # Anthropic usage-limit sensors
│           ├── bridge.py        # File-based IPC with the add-on
│           ├── repairs.py       # "Restart required" repair flow
│           ├── const.py         # Constants
│           ├── services.yaml    # Service definitions
│           ├── strings.json     # UI strings
│           ├── icons.json       # Entity/service icons
│           └── translations/en.json
├── .gitignore
├── LICENSE
└── CLAUDE.md                    # This file
```

## Key Architecture

### MCP Server (`ha-mcp-server/ha_mcp_server.py`)
- Stdio-based MCP server that Claude Code launches automatically
- Uses `SUPERVISOR_TOKEN` for HA API authentication
- Provides tools for entity states, device control, area listings (`get_areas`), registry listings (`get_registry`: areas/floors/labels/devices/entities/integrations via the WebSocket API), camera snapshots (`get_camera_snapshot`, returned as MCP image blocks), history/long-term statistics (`get_history`, `get_statistics` via the WebSocket API), service calls (`call_service`, optional `return_response` over WebSocket for services with response data), logs, template rendering, config reload
- Tools are registered via `TOOL_IMPLEMENTATIONS` (name → function name, late-bound) with argument contracts derived from each tool's inputSchema; add a tool = function + schema in `TOOLS` + one mapping line

### Startup Flow (`run.sh`)
1. Health check
2. Environment initialization (`/data` for persistence)
3. Non-root user setup (`claude` UID 1000, `claude-run` wrapper, shell profile)
4. Tool installation
5. CLI tools setup (ha-reload, ha-log, ha-backup, etc.)
6. Persistent packages
7. Auto-backup (git init + background watcher)
8. Context generation (CLAUDE.md)
9. Broken plugin cleanup (removes stale `claude-homeassistant-plugins` entries)
10. MCP server configuration (writes `.mcp.json` with proper ownership)
11. Custom integration deployment to `/config/custom_components/bruh_claude/`
12. Usage-limits tracker (background daemon querying the Anthropic usage endpoint)
13. Optional: Assist + Automation integrations
14. ttyd web terminal launch (with the mobile UI spliced in via `build-mobile-index.py`)

### Custom Integration (`custom_components/bruh_claude/`)
- Deployed automatically to `/config/custom_components/` by the add-on at startup
- Registers a `ConversationEntity` so "BRUH Claude" appears in Settings > Voice Assistants
- Provides `bruh_claude.send_prompt`, `bruh_claude.run_task`, `bruh_claude.run_insight`, and `bruh_claude.clear_conversation` services
- BRUH Power Tools (`power_tools.py`): 36 admin-gated registry-management services under `bruh_claude.*` (areas, floors, labels, entities, devices, integrations, zones, persons, repair issues), adapted from [Spook](https://github.com/frenck/spook) (MIT) with validation-first handlers, response data on creation services, and dry-run-by-default orphan cleanup; catalog metadata generated in `services.yaml`/`strings.json`/`translations/en.json`/`icons.json`, consistency enforced by `tests/test_power_tools.py`
- Insight jobs (config entries of type `insight`): scheduled Claude reports rendered to `sensor.<job>_insight` (markdown attribute + ready-to-paste `card_yaml`); prompts support HA templating
- 3.0 transport: worker pool serves an internal HTTP API (:8099, token on the shared volume); integration streams deltas into the chat log (SSE) and falls back to file IPC; `binary_sensor` reports pool health
- Usage-limit sensors reading from `/config/.bruh_claude/usage_limits.json` (real Anthropic account utilization; requires OAuth/subscription login)
- Communicates with the add-on via shared files in `/config/.bruh_claude/`
- Request/response flow: integration writes JSON (unique per-request file id) → add-on processes → add-on writes JSON response named after the request id
- Conversation continuity: the assist listener maps `conversation_id` → Claude session uuid in `/config/.bruh_claude/sessions/` and resumes the session on follow-up turns (`--session-id` / `--resume`); falls back to replaying recent history when resume isn't possible

### Permissions Architecture
- **Interactive terminal**: `dangerously_skip_permissions` config option (default: **off**)
- **Background listeners (Assist, Automation)**: Do NOT use `--dangerously-skip-permissions`. Instead, tool permissions are granted via `/config/.claude/settings.local.json`, which pre-approves MCP, Bash, Read, Write, Edit, WebFetch, and WebSearch tools. This avoids root-user restrictions of the flag.
- **Project settings**: Written to `/config/.claude/settings.local.json` at startup by `setup_claude_settings()` in `run.sh`
- **Non-root execution**: Claude Code runs as UID 1000 (`claude` user) via a wrapper script at `/usr/local/bin/claude-run` that uses `su-exec`
- **Listener speed**: Both listeners use `--max-turns` to limit agentic loops (defaults: 5 for Assist, 10 for Automation; configurable). The assist path splices a cached area→entity map (controllable domains + Weather/People) into the system prompt so most voice commands skip lookup turns. With `assist_fast_mode` (default) the assist channel runs as a worker pool (`assist-worker-pool.py`): persistent `claude --input-format stream-json` processes per conversation plus a pre-warmed spare, falling back to one-shot spawns on any worker error

### Container Environment
- Base: Home Assistant Alpine Linux 3.24 (Dockerfile `ARG BUILD_FROM` default; `build.yaml` only applies to Supervisor < 2026.04)
- HOME: `/data/home` (persistent across restarts)
- Config: `/data/.config/claude`
- HA config: `/config` (read-write)
- Tools live in `/opt/scripts/` and get copied to `/usr/local/bin/`

## Development

### Build locally
```bash
podman build -t local/bruh-claude-terminal ./bruh-claude-terminal
```

### Run locally
```bash
podman run -p 7681:7681 -v $(pwd)/config:/config local/bruh-claude-terminal
```

### File Conventions
- Shell scripts: `#!/usr/bin/with-contenv bashio` for HA scripts, `#!/bin/bash` for standalone
- YAML: 2-space indentation
- Shell: 4-space indentation
- Error handling: `bashio::log.error` for HA scripts, colored output for user-facing tools
