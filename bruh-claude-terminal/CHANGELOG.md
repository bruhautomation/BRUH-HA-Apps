# Changelog

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
