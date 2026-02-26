# Changelog

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
