# Changelog

## 1.6.1

### MCP Fixes & Token Usage Sensors

**Fixed MCP Tool 404 Errors**
- Fixed `get_error_log` returning HTTP 404 on HA 2025.11+ — the legacy `/api/error_log` REST endpoint broke when supervised installations removed `home-assistant.log`. Now uses the Supervisor's `/core/logs` journal endpoint with automatic fallback to the legacy endpoint for non-supervised setups.
- Fixed `get_automation_trace` returning HTTP 404 — the `/api/trace/automation/{id}` REST endpoint never existed (traces are WebSocket-only). Replaced with automation entity state lookup via `/api/states` plus stored trace reading from `/config/.storage/trace.saved_traces` when available.

**Token Usage Sensors**
- Added token usage sensors to the BRUH Claude custom integration
- A background tracker (`token-stats-tracker.py`) scans Claude Code session JSONL files every 60 seconds and writes aggregated stats to `/config/.bruh_claude/token_stats.json`
- Token counts are the real values from the Anthropic API `usage` field — not estimated
- Sensors:
  - Session Input Tokens / Output Tokens / Total Tokens (with `started_at`, `last_activity` attributes)
  - Today Total Tokens (with `period_start`, `resets_at` attributes)
  - Weekly Total Tokens (with `period_start`, `resets_at`, `session_count` attributes)
  - Weekly Sessions (distinct session count this week)
  - All Time Total Tokens

## 1.5.6

### Auth & Permission Fixes

**Fixed MCP Server Permission Denied**
- `.mcp.json` was written as root but Claude Code runs as UID 1000 — added chown/chmod after writing

**Fixed Broken Plugin Interference**
- A stale `claude-homeassistant-plugins` marketplace plugin was hitting HA's native MCP endpoint with invalid auth — added `cleanup_broken_plugins()` to remove stale plugin references at startup

**Fixed "Multiple Installations" Warnings**
- Renamed wrapper script from `/usr/local/bin/claude` to `/usr/local/bin/claude-run` to prevent Claude Code diagnostics from detecting a conflicting npm-global install

## 1.5.5

### Syntax Fix
- Fixed missing closing brace in `setup_claude_settings()` that caused "syntax error: unexpected end of file"

## 1.5.4

### Conversation Agent Permissions Rework

**Fixed Conversation Agents Returning Empty Responses**
- Replaced `--dangerously-skip-permissions` in listeners with project-level `settings.local.json` tool allowlist
- Added `--max-turns` (3 for Assist, 10 for Automation) to reduce latency
- Added `--system-prompt` flag for cleaner prompt separation
- Added empty-response detection with stderr-based error diagnostics
- Default `dangerously_skip_permissions` changed to `false` in config.yaml

**Updated Branding**
- Updated all icons to Claude AI branding (`mdi:creation` sparkle)

## 1.5.3

## 1.5.2

## 1.5.1

### Repair Flow Fix, Expanded Device Control & Options Flow

**Fixed Repair Flow Not Triggering**
- Fixed the repair issue never appearing after an add-on update
- Root cause: the version comparison read the already-overwritten manifest.json from disk instead of using the in-memory version, so it always thought the restart had already happened
- The loaded version is now captured at module import time, before the add-on can overwrite it
- Fixed repair flow translation strings to use the correct `fix_flow` structure per HA conventions (was incorrectly using a separate top-level `repairs` key)

**Expanded MCP Service Tools**
- Added dedicated tools for controlling all major device types with fully typed parameters:
  - `control_light` — brightness, RGB/HS/XY color, color temperature (Kelvin), color name, effects, transitions, flash
  - `control_climate` — temperature, HVAC mode, fan mode, preset mode, humidity, swing mode
  - `control_media_player` — play/pause/stop, volume, source selection, play media, seek, shuffle, repeat
  - `control_cover` — open/close/stop, set position, set tilt
  - `control_fan` — speed percentage, preset mode, direction, oscillation
  - `control_switch` — on/off/toggle for switches and input_booleans
  - `control_lock` — lock/unlock/open with optional access code
  - `control_alarm` — arm (away/home/night/vacation), disarm, trigger with code
  - `control_vacuum` — start/stop/pause, return home, locate, spot clean, fan speed
  - `send_notification` — persistent notifications or targeted (mobile app, Slack, etc.)
  - `activate_scene` — activate scenes with optional transition
  - `run_script` — run scripts with optional variables
- Added `get_service_details` tool for dynamic service schema lookup
- Improved `call_service` description with comprehensive examples
- Enhanced assist-listener prompt so Claude knows about all available device control tools

**Options Flow for Conversation Agents**
- Added an options flow so users can edit the system prompt and timeout after initial setup
- Go to Settings > Devices & Services > BRUH Claude > Configure to change settings
- The conversation entity reloads automatically when options are changed

**Integration Icon**
- Note: To see the BRUH Claude icon in Settings > Devices & Services, submit the icon to the [home-assistant/brands](https://github.com/home-assistant/brands) repo under `custom_integrations/bruh_claude/`, or wait for HA 2026.3.0 which supports local custom integration icons

## 1.5.0

### HA Repairs Flow, OAuth Persistence & Conversation Memory

**HA Repairs Integration**
- Replaced persistent notification with HA repairs flow for integration updates
- On update, the integration creates a fixable repair issue in Settings > System > Repairs with a "Restart" button
- First installs still use a persistent notification as fallback since no integration is loaded yet
- Added `repairs.py` with `RestartRequiredRepairFlow` that triggers HA restart

**OAuth Persistence**
- OAuth auth symlinks are now recreated on every add-on startup
- Credentials persist across add-on updates and container rebuilds

**Conversation Memory**
- Added conversation memory to the Assist conversation agent
- The bridge tracks per-session history (up to 20 turns) and sends it with each request
- The assist-listener formats history as context for Claude

## 1.4.0

### Permissions Toggle, Restart Documentation & Version Bump

**Configurable Permissions Flag**
- Added `dangerously_skip_permissions` configuration toggle (default: `true`)
- The `--dangerously-skip-permissions` flag is no longer hardcoded — it's now controlled via the app configuration UI
- Setting this to `false` makes Claude Code prompt for confirmation before each tool call (file edits, shell commands, etc.)
- Flag state is persisted in the shared env file so background integrations (Assist, Automation listeners) respect the setting
- Note: Disabling this will make Assist and Automation integrations non-functional since they run non-interactively

**Restart Requirements Documentation**
- Clarified that an HA Core restart is required after first install and after version upgrades
- Added a detailed restart requirements table to DOCS.md explaining each scenario
- Updated Quick Start guides in DOCS.md and README.md to include the restart step
- Added upgrade note to README.md installation instructions
- Documented that disconnecting/reconnecting the integration does NOT reload updated Python code

**Security Documentation**
- Added comprehensive "Permissions" section to DOCS.md explaining what `--dangerously-skip-permissions` does
- Documented the sandboxing context: non-root user (UID 1000), isolated container, limited to /config and /data
- Added inline code comments in `run.sh` explaining the security model

## 1.3.0

_Skipped — reserved for intermediate builds._

## 1.2.0

### Discovery Fix, Version Updates & App Terminology

**Fixed Integration Auto-Discovery**
- Fixed the integration not being auto-discovered on first install
- The app now triggers an HA Core restart after first-time custom component deployment,
  ensuring the integration is loaded before discovery fires
- Uses bashio::discovery for reliable Supervisor API communication with curl fallback
- Discovery payload now includes add-on metadata (slug, name, version)
- Config flow updated to handle both legacy dict and new HassioServiceInfo discovery formats

**Version Update Detection**
- Bumped version to 1.2.0 across all files (config.yaml, manifest.json, run.sh)
- Versions are now kept in sync so the update button appears correctly in Settings > Apps
- When pulling repository updates, HA will detect the new version and show the update button

**Updated to HA 2026.2 Standards**
- Renamed "Add-On" references to "App" throughout (matching HA 2026.2 terminology)
- Added `integration_type: "service"` to manifest.json per latest HA integration standards
- Updated all user-facing strings (config flow, error messages) to use "app" terminology

## 1.1.0

### Auto-Discovery & Versioning

**Automatic Integration Discovery**
- The BRUH Claude integration is now automatically discovered when the add-on starts
- Home Assistant will show a notification prompting you to set up the integration
- No more manual navigation to Settings > Devices & Services to add it
- Manual setup via Settings > Devices & Services still works as a fallback

**Version Display & Update Support**
- Fixed version number not appearing on the add-on store page
- Fixed update button not showing when a new version is available
- Synced version numbers across add-on config, integration manifest, and startup banner

## 1.0.0

### Initial Release

Built on the foundation of [heytcass/claude-terminal](https://github.com/heytcass/home-assistant-addons), BRUH Claude Terminal adds:

**Native HA API Access**
- Built-in MCP server providing Claude Code with real-time Home Assistant access
- Entity states, service calls, automation traces, logs, template rendering
- Auto-configured on startup - no manual MCP setup needed

**Auto-Generated Project Context**
- Generates CLAUDE.md on startup with full system context
- Entity counts, automations, integrations, add-ons, file structure
- Regenerate anytime with `ha-context-gen`

**Git-Based Config Backup**
- Automatic git versioning of /config directory
- Configurable backup interval (default: 30 minutes)
- Manual backup via `ha-backup` command
- File restore from any previous commit
- Smart .gitignore excludes secrets, databases, logs

**Config Reload Integration**
- `ha-reload` command for reloading HA configs from the terminal
- Supports automations, scripts, scenes, groups, input helpers, core, and all
- Configuration validation via `ha-reload check`

**Log Access**
- `ha-log` command for viewing HA core, supervisor, host, and add-on logs
- Error filtering mode
- Follow mode for real-time log tailing

**Persistent Environment**
- APK and pip packages persist across restarts
- Configurable via add-on settings or `persist-install` command

**Multi-Session & Background Tasks**
- Enhanced session picker with tmux window management
- Background task queue for autonomous Claude operations
- HA Tools quick-access menu

**Home Assistant Assist Integration**
- Optional conversation agent bridge to Claude Code
- Event-based communication for voice/text assistant

**Home Assistant Automation Integration**
- File-based task queue for automation-triggered Claude tasks
- Optional notifications on task completion
- Completion events for automation chaining
