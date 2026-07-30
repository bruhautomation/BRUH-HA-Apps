# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

This repository contains Home Assistant add-ons by BRUH Automation:

- **brAIn** (`brain/`) - **the primary add-on.** A Claude Code terminal, an AI insights dashboard, and one shared memory that learns the house over time, merged into a single add-on behind one ingress panel and one Claude login. Supersedes BRUH Terminal and BRUH Insights. Integration domain: `brain`.
- **BRUH Minecraft** (`bruh-minecraft-server/`) - a Minecraft Java Edition server with an ingress management panel, git-based world version control, RCON, and a companion `bruh_minecraft` custom integration.

BRUH Terminal (`bruh-claude-terminal/`) and BRUH Insights (`bruh-insights/`) were removed in favour of brAIn; the architecture notes below describe the internals brAIn inherited from them.

### brAIn specifics

- One ingress port (8099, the panel). The panel reverse-proxies `/terminal/` through to ttyd on 7681 (`brain/panel/terminal_proxy.py`), so the terminal is a tab. The assist worker pool's internal API moved to **8098** to free 8099.
- `enable_terminal` / `enable_insights` switch either face off; the panel always runs because it is the ingress target.
- **No git auto-backup.** It was removed along with `auto_backup` / `backup_interval_minutes`. In its place, a `PreToolUse` hook (`scripts/brain-edit-snapshot.py`) snapshots files before Claude edits them, and `brain undo` restores them. Never touch a user's existing `/config/.git`.
- **Two CLI dispatchers**, not fourteen scripts: `brain` (memory, learn, ask, undo, doctor) and `ha` (log, reload, entity, service, addon, notify, share, check, context). Both delegate to `/opt/scripts`. Adding a command = a script plus one dispatcher line.
- **Memory**: `memory.md` is the only thing that is "memory". The inbox, the hypothesis queue, and the change log are queues and audit trails, and are never injected into prompts. Every writer goes through the inbox — nothing writes `memory.md` except the consolidator. The Memory tab's "File into memory now" runs the same consolidator with `--once`; it does not become a second writer. **The facts ledger (`knowledge_store`) is a dedup index, not a queue** — nothing may be deleted from it, or the analyst re-announces what you have already seen. What the Memory tab shows as still-waiting is derived instead: a discovery is filed if its `ts` predates the mtime of `memory/.last_consolidated`, which the consolidator stamps only on a pass that actually wrote. Never report a consolidation by the count you asked it to file; read the queue either side of it (a pass can exit 0 and keep the facts, and exit 75 when another pass holds the lock).
- **Hypotheses replace open-ended questions**: capped at 3 open, 14-day expiry, answered ones become plain memory lines and the record is settled. Rejected ones become a capped dead-ends block.
- **Three kinds of knowledge, and they don't mix.** Memory = what is *true* of the home. A hypothesis = what brAIn might have *wrong*. A **finding** (`panel/findings_store.py`) = what is *broken*, with a lifecycle that ends in fixed or ignored. The generation contract keeps them apart too: `learned` feeds memory, `findings` feeds the work list. Ignored findings are injected into every future analysis so a dismissal sticks.
- **One tool-enabled Claude path.** Insight generation is pure analysis over a data bundle with `--disallowedTools "*"`. `engine.run_agent` (used only by the Findings "Fix it" button, via `panel/fixer.py`) is the single exception, and it only ever runs because someone pressed the button — never on a schedule. Fixes share the generation queue, so one Claude invocation is in flight at a time.
- **The ask bar has two verbs.** A question becomes a card; a line starting "learn/study/research/figure out" is routed server-side (`LEARN_RE`) to a study request the CLI-side watcher picks up. There is no separate "new insight" dialog — asking makes the card, and "＋ Make recurring" turns it into a scheduled one.
- **Deleted cards do not come back.** There is no restore list: brAIn proposes the cards a given home should have, so the answer to "I want that card again" is to ask for it and let brAIn build it for the house it now knows. Shipped categories are still `hidden` under the hood because their definitions live in the code, but that is a mechanism, not an offer.
- **Naming**: prefer `brain`/`ha` over `claude` in anything we own. `CLAUDE.md`, `CLAUDE_CONFIG_DIR`, the `claude` user, and the `claude-run` wrapper keep the name because they *are* Claude Code's file, env var, user, and binary. Everything else (`panel/engine.py`, `scripts/brain-*.sh`) is brAIn-named.

Shared brand sources live in `branding/` (SVGs plus `render.mjs`, which regenerates every PNG in the repo) and `brands/` (home-assistant/brands submission assets); cross-add-on tests live in `tests/`. The brAIn mark is a gable that doubles as the `A` in the wordmark, lifted from the parent BRUH logo — never redraw it, and never recolour the roof away from azure. The panel's top bar carries the full wordmark inline, split into `.wm-ink` / `.wm-roof` / `.wm-ai` / `.wm-signal` so one file serves a light and a dark bar.

**The top bar is a fixed 48px single row at every width.** Nothing in it may shrink (`.topbar > * { flex: none }`), so a fit is binary and an overflow is something a test can see. Adding anything to it — a tab, a badge, a button — changes the measured widths behind its five breakpoints: re-run `node tests/manual/measure-topbar.mjs` (Playwright; `CHROMIUM_PATH` if the browser isn't where it expects) and move the breakpoints to what it reports, rather than guessing. It measures three bar states per width (running / paused / failed login) because none is a superset of the others; a chip that only appears in one of them still has to fit. **A status chip that is permanently green does not belong there** — the auth chip renders only for trouble, and the space it used to hold pays for the usage pill's second number (session and week, with both reset times in the hover).

## Repository Structure

```
BRUH-HA-Apps/
├── repository.yaml              # HA add-on repository metadata
├── brain/                       # Main add-on
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
│   │   ├── brain-learn.sh       # Study session: facts → memory inbox, problems → findings inbox
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
│           ├── power_tools.py   # BRUH Power Tools: 56 registry admin services (from Spook, MIT)
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
- Provides tools for entity states, device control, area listings (`get_areas`), registry listings (`get_registry`: areas/floors/labels/devices/entities/integrations/users via the WebSocket API), dashboard reads (`list_dashboards`, `get_dashboard`), camera snapshots (`get_camera_snapshot`, returned as MCP image blocks), history/long-term statistics (`get_history`, `get_statistics` via the WebSocket API), service calls (`call_service`, optional `return_response` over WebSocket for services with response data), logs, template rendering, config reload
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
- BRUH Power Tools (`power_tools.py`): 56 admin-gated registry-management services under `bruh_claude.*` (areas, floors, labels, entities, devices, integrations, helpers, zones, persons, blueprints, statistics, users, diagnostics, dashboards, repair issues), adapted from [Spook](https://github.com/frenck/spook) (MIT) with validation-first handlers, response data on creation services, and dry-run-by-default orphan cleanup; catalog metadata generated in `services.yaml`/`strings.json`/`translations/en.json`/`icons.json`, consistency enforced by `tests/test_power_tools.py`
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
podman build -t local/brain ./brain
```

### Run locally
```bash
podman run -p 8099:8099 -p 7681:7681 -v $(pwd)/config:/config local/brain
```

### File Conventions
- Shell scripts: `#!/usr/bin/with-contenv bashio` for HA scripts, `#!/bin/bash` for standalone
- YAML: 2-space indentation
- Shell: 4-space indentation
- Error handling: `bashio::log.error` for HA scripts, colored output for user-facing tools
