# Changelog

## 1.14.0

### Auto-Update Claude Code on Startup

**Claude Code Auto-Update**
- Added `update_claude_code()` function that runs the official Claude Code installer on every container startup
- Ensures the add-on always uses the latest Claude Code version without requiring a Docker image rebuild
- Logs current and updated version numbers for visibility
- Gracefully falls back to the existing version if the update check fails
- Refreshes persistent binary symlinks after updates

## 1.13.0

### Version Bump, Documentation & Changelog Catch-Up

**Documentation Updates**
- Added missing CHANGELOG entries for v1.11.0 and v1.12.0
- Synced version numbers across all files (config.yaml, manifest.json, run.sh)

## 1.12.0

### Deep MCP Cleanup, Device Separation & Agent Timeout Fix

**Comprehensive MCP Auth Cleanup**
- Replaced `cleanup_broken_plugins()` with `cleanup_all_mcp_references()` that scans all Claude Code config locations with unlimited depth
- Clears ALL persistent conversation sessions on startup (fixes v1.8.0 `--resume` regression where stale MCP state survived config cleanup)
- Cleans ALL `.mcp.json` files across `/data`, `/config`, `/root`, and `~/.claude.json`
- Added MCP watchdog background process that monitors for `/api/mcp` entries being re-created after cleanup, auto-cleans them, and logs the source
- Added `CLAUDE_CODE_DISABLE_MCP_DISCOVERY` and `CLAUDE_MCP_SERVERS_OVERRIDE` env vars to block Claude Code from auto-discovering HA's native `/api/mcp`
- Enhanced `verify_mcp_config()` in both listeners to check and clean Claude Code's project-level configs before each invocation
- Added `/api/mcp` error detection in listeners — auto-cleans configs and retries

**Entity & Device Separation**
- Each conversation agent now gets its own `DeviceInfo`, appearing as a distinct device card in HA
- Agents show as "BRUH Claude" / "BRUH OPUS" devices with model "Claude Conversation Agent"
- Usage sensors remain grouped under "BRUH Claude Usage Limits" device

**Agent Timeout Fix**
- Simplified `assist-listener.sh` to match the proven `automation-listener` pattern (single invocation, plain text output)
- Removed `--output-format json`, `--resume`, session persistence, and nested retry loops from assist-listener
- Added `~/.claude.json` cleanup — the primary hiding spot for stale `/api/mcp` entries that caused Claude Code to hang on MCP connection
- Changed `setup_mcp_server()` from warning about extra configs to actively cleaning them

**Config Flow UX Improvements**
- Improved first_setup, add_agent, and options flow descriptions for clarity
- Updated both `strings.json` and `translations/en.json`

## 1.11.0

### Simplified Onboarding & /api/mcp Auth Fix

**Integration Onboarding Redesign**
- Redesigned config flow with context-aware routing
- First setup shows only a name field and creates a conversation agent + sensors with all defaults (one click)
- "Add Service" shows the full agent personality form (name, model, system prompt, timeout)
- Removed the confusing two-step feature-toggle flow from v1.10.0
- Options flow now only shows the sensor toggle when this is the sole config entry
- Config entry migration v2 → v3

**Fixed /api/mcp Authentication Errors**
- `setup_mcp_server()` now always overwrites `/config/.mcp.json` with a clean config instead of merging (which preserved stale entries)
- `cleanup_broken_plugins()` now stringifies entire MCP entry values for matching (catches URLs in any field, not just `.url`/`.args`)
- Both listeners verify MCP config is clean before each Claude invocation, preventing runtime re-contamination
- Broader cleanup search locations, broken npm package removal, MCP diagnostic logging

## 1.10.0

### Feature Toggles & MCP Cleanup Hardening

**Integration Onboarding Redesign**
- New two-step config flow: first choose which features to enable, then configure agent settings
- Conversation agent and usage limit sensors are now independently toggleable
- Users can enable just sensors, just a conversation agent, or both
- Options flow updated with feature toggles — easily turn features on/off after setup
- Config entry migration (v1 → v2) ensures existing installs keep working seamlessly

**Hardened /api/mcp Cleanup**
- Increased search depth from 2 to 4 levels to catch entries in Claude Code project config files
- Added post-write sanitization to `setup_mcp_server()` — even if cleanup misses a stale entry, the final `.mcp.json` is always verified clean
- Now also checks `.args` fields (not just `.url`) for `/api/mcp` references
- Added `/root/.mcp.json` to the list of checked locations

**Fixed: Conversation Agent Not Responding**
- Added process-level `timeout` to all `claude -p` calls in both assist and automation listeners
- Previously, if Claude Code hung (e.g., broken MCP server connection), the listener blocked forever and no response file was ever written — the user got nothing
- Now Claude Code is killed after 105s (assist) or 300s (automation), and a meaningful error message is returned
- Added timeout-specific error messages so users know what happened
- Added `asyncio.CancelledError` handling in the conversation entity for cases where HA cancels the request

## 1.9.0

### Remove Legacy Token Sensors & Fix /api/mcp Auth Error

**Removed Legacy Token Sensors**
- Removed the old token-counting sensors (session/daily/weekly/all-time token counts)
- The `token-stats-tracker.py` script is no longer started
- Kept the Anthropic usage limit sensors (session/weekly usage %, reset times) which read real API data

**Fixed /api/mcp Authentication Error**
- Added `cleanup_broken_plugins()` to startup that removes stale MCP server entries from the broken `claude-homeassistant-plugins` marketplace plugin
- The plugin registered an SSE MCP server pointing to HA's `/api/mcp` endpoint with invalid auth, causing "invalid authentication" errors and blocking conversation agent responses
- Cleanup removes plugin/extension references and stale `mcpServers` entries from all Claude Code config locations

## 1.8.0

### Anthropic Usage Sensors, Persistent Sessions & Configurable Turns

**Real Anthropic Usage Limit Sensors**
- New sensors that show your actual Claude account usage — the same data shown on claude.ai Settings > Usage
- A background tracker (`usage-limits-tracker.py`) queries the Anthropic OAuth usage API every 2 minutes
- Reads the OAuth token from Claude Code's credentials file automatically
- New sensors:
  - Session Usage (%) — 5-hour rolling window utilization percentage
  - Session Usage Resets At — timestamp when the session window resets
  - Weekly Usage (%) — 7-day utilization percentage
  - Weekly Usage Resets At — timestamp when the weekly limit resets
- Sensors grouped under a "BRUH Claude Usage Limits" device
- Gracefully shows "unavailable" if Claude Code is not authenticated or using an API key

**Persistent Conversation Sessions**
- Each conversation agent now maintains a persistent Claude Code session using `--resume`
- First message creates a new session; subsequent messages resume it with full context
- Claude remembers conversation history natively — no more re-sending history as text
- MCP tool state is preserved across messages (no cold-start MCP discovery)
- Automatic fallback to new session if resume fails (e.g., session deleted)
- New `bruh_claude.clear_conversation` HA service to reset sessions:
  - Pass `conversation_id` to clear one specific agent's session
  - Omit it to clear ALL sessions
- Session IDs stored in `/config/.bruh_claude/sessions/`

**Configurable Max Turns**
- Assist max turns increased from 3 to 5 (default)
- Both `assist_max_turns` and `automation_max_turns` are now configurable via the add-on config UI
- Assist: 1–20 (default 5), Automation: 1–50 (default 10)

**Per-Model Token Tracking**
- Token stats tracker now parses model names from JSONL session files
- Tracks per-model usage (Sonnet, Opus, Haiku) for session and weekly periods
- Adds estimated session reset time based on session activity window
- Per-model data available in `token_stats.json` under `models_week` and `models_session` keys

## 1.6.3

### Fix Duplicate Sensors & Add Reset Time Sensors

**Fixed Duplicate Token Sensors**
- Token usage sensors were being created per conversation config entry, causing duplicates when multiple conversation agents existed
- Sensors now use fixed unique IDs and are only created once (account-wide, not per conversation agent)
- All sensors are grouped under a single "BRUH Claude Token Usage" device for cleaner organization
- If the config entry owning the sensors is removed, sensor ownership automatically migrates to another entry

**Added Reset Time Sensors**
- Session Started — timestamp sensor showing when the current Claude session began
- Today Resets At — timestamp sensor showing when today's token counters reset (midnight UTC)
- Weekly Resets At — timestamp sensor showing when weekly token counters reset (next Monday UTC)

**Note:** After updating, old duplicate sensor entities will show as unavailable and can be removed from the entity registry.

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
