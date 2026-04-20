# BRUH Claude Terminal

Enhanced Claude Code terminal for Home Assistant with native HA API access, auto-backup, context generation, and deep Home Assistant integration.

## Features

### Native HA API Access (MCP Server)
A built-in MCP server gives Claude Code real-time access to your Home Assistant installation:
- Get entity states, call services, trigger automations
- View automation state and stored execution traces for debugging
- Check HA logs via Supervisor journal
- Render Jinja2 templates
- Reload configurations after YAML edits

### Auto-Generated Project Context
On startup, automatically generates a `CLAUDE.md` file that describes your HA installation:
- Entity registry summary (counts by domain)
- Automation list with states and last-triggered times
- Installed add-ons and integrations
- File structure guide

### Git-Based Config Backup
Automatic git versioning of your `/config` directory:
- Initializes a git repo on first run
- Periodic auto-commits (configurable interval)
- Manual backup via `ha-backup` command
- File restore from any previous backup
- Sensible `.gitignore` (excludes secrets, databases, logs)

### Config Reload Integration
After editing YAML files, reload without leaving the terminal:
- `ha-reload automations` - Reload automations
- `ha-reload scripts` - Reload scripts
- `ha-reload all` - Reload everything
- `ha-reload check` - Validate configuration

### Log Access
Real-time access to HA logs:
- `ha-log core` - Core logs
- `ha-log supervisor` - Supervisor logs
- `ha-log errors` - Error-only filter
- `ha-log core -f` - Follow mode

### Persistent Environment
Packages survive container restarts:
- Configure via add-on settings or `persist-install` command
- Both APK and pip packages supported

### Multi-Session & Background Tasks
- tmux-based session management
- Open multiple Claude windows
- Queue background tasks that Claude works through autonomously

### Home Assistant Assist Integration
Connect Claude to HA's conversation agent for voice/text assistant responses.

### Token Usage Sensors
Track Claude Code token usage directly in Home Assistant:
- Session, daily, weekly, and all-time token counts (real Anthropic API values)
- Session start time, last activity, and period reset timestamps
- Weekly session count

### Home Assistant Automation Integration
Trigger Claude tasks from HA automations via file-based task queue.

## Installation

1. Add this repository to your Home Assistant app store
2. Install "BRUH Claude Terminal"
3. Start the app
4. **Restart Home Assistant** (Settings > System > Restart) — required on first install so HA loads the BRUH Claude integration
5. Home Assistant will automatically discover the BRUH Claude integration and prompt you to set it up
6. Authenticate with your Anthropic account in the terminal

> **After upgrades:** If the app version changes, restart HA again so the updated integration code is loaded. The app will send a persistent notification when this is needed.

The integration can also be added manually via Settings > Devices & Services > Add Integration > BRUH Claude.

## Configuration

See [DOCS.md — Configuration Reference](DOCS.md#configuration-reference) for a description of every option. Quick overview of the defaults:

| Option | Default | Description |
|--------|---------|-------------|
| `auto_launch_claude` | `true` | Auto-start Claude or show session picker |
| `auto_backup` | `true` | Enable git-based config backup |
| `auto_generate_context` | `true` | Generate CLAUDE.md on startup |
| `backup_interval_minutes` | `30` | Minutes between auto-backups |
| `enable_ha_mcp_server` | `true` | Enable HA MCP server for Claude |
| `enable_assist_integration` | `true` | Enable Assist conversation agent |
| `enable_automation_integration` | `true` | Enable automation task queue |
| `assist_max_turns` | `5` | Max agentic turns per Assist request |
| `automation_max_turns` | `10` | Max agentic turns per automation task |
| `dangerously_skip_permissions` | `false` | Skip per-action confirmation prompts in the terminal (see [Permissions docs](DOCS.md#permissions-dangerously_skip_permissions)) |
| `access_share` | `true` | Expose `/share` to Claude |
| `access_media` | `true` | Expose `/media` to Claude |
| `access_backup` | `true` | Expose `/backup` to Claude (read-only) |
| `access_addon_configs` | `true` | Expose `/addon_configs` to Claude |
| `access_addons` | `true` | Expose `/addons` to Claude |
| `additional_directories` | `[]` | Extra directories to expose to Claude |
| `persistent_apk_packages` | `[]` | APK packages to install on startup |
| `persistent_pip_packages` | `[]` | pip packages to install on startup |
| `log_level` | `info` | Logging verbosity |

## Credits

Based on the excellent [Claude Terminal](https://github.com/heytcass/home-assistant-addons) by Tom Cassady.
