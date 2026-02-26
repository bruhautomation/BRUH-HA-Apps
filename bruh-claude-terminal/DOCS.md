# BRUH Claude Terminal Documentation

## Quick Start

1. Install the add-on from the BRUH HA Apps repository
2. Start the add-on - it will open a web terminal
3. Home Assistant will automatically discover the BRUH Claude integration and prompt you to set it up via a notification in Settings > Devices & Services
4. Authenticate with your Anthropic account
5. Claude Code now has full access to your HA config and live API

> **Note:** The BRUH Claude integration is discovered automatically when the add-on starts. If you prefer manual setup, go to Settings > Devices & Services > Add Integration > BRUH Claude.

## CLI Tools Reference

### ha-reload

Reload Home Assistant configurations after editing YAML files.

```bash
ha-reload automations     # Reload automations
ha-reload scripts         # Reload scripts
ha-reload scenes          # Reload scenes
ha-reload groups          # Reload groups
ha-reload core            # Reload core configuration
ha-reload all             # Reload everything
ha-reload check           # Validate configuration (no reload)
```

### ha-log

View Home Assistant logs.

```bash
ha-log core               # Core logs (last 100 lines)
ha-log supervisor         # Supervisor logs
ha-log host               # Host system logs
ha-log addon mosquitto    # Specific add-on logs
ha-log errors             # Filter for errors/warnings only
ha-log all                # Core + supervisor + errors
ha-log core -f            # Follow mode (real-time)
ha-log core -n 50         # Last 50 lines
```

### ha-backup

Git-based configuration backup.

```bash
ha-backup                           # Backup with default message
ha-backup "Updated automations"     # Backup with custom message
ha-backup history                   # View backup history
ha-backup diff                      # Show changes since last backup
ha-backup diff HEAD~3               # Show changes since 3 backups ago
ha-backup restore automations.yaml  # Restore a file from previous backup
```

### ha-context-gen

Regenerate the CLAUDE.md context file with current HA system information.

```bash
ha-context-gen
```

### persist-install

Install packages that survive container restarts.

```bash
persist-install apk vim htop        # Install Alpine packages
persist-install pip pandas numpy    # Install Python packages
persist-install list                # List persistent packages
persist-install remove apk vim      # Remove from persistence
```

## MCP Server

The built-in MCP server gives Claude Code these capabilities:

| Tool | Description |
|------|-------------|
| `get_entity_state` | Get current state of any entity |
| `get_all_states` | List all entities (filterable by domain) |
| `call_service` | Call any HA service (turn on lights, etc.) |
| `get_automations` | List all automations with status |
| `get_automation_trace` | Get execution traces for debugging |
| `get_ha_config` | Get HA configuration details |
| `get_services` | List all available services |
| `get_device_registry` | Get device/entity summary |
| `get_logbook` | Get recent logbook entries |
| `get_error_log` | Get HA error log |
| `render_template` | Render Jinja2 templates |
| `fire_event` | Fire custom events |
| `get_supervisor_info` | Get system information |
| `reload_config` | Reload configurations |

## Automation Integration

To trigger Claude tasks from automations, create a JSON file in `/data/automation-tasks/`:

```yaml
# Example HA automation
automation:
  - alias: "Morning Claude Report"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: shell_command.create_claude_task
        data:
          command: >
            echo '{"prompt": "Check my HA error log and summarize any issues from the last 24 hours", "notify": true, "notify_entity": "notify.mobile_app"}' > /config/claude-tasks/morning_report.json

# In configuration.yaml
shell_command:
  create_claude_task: "cp /config/claude-tasks/{{ task }}.json /data/automation-tasks/"
```

## BRUH Claude Integration

The BRUH Claude integration is automatically discovered when the add-on starts. It provides:

- **Conversation Agent** - Select "BRUH Claude" as a conversation agent in Settings > Voice Assistants
- **`bruh_claude.send_prompt`** service - Send a one-shot prompt to Claude and get a response
- **`bruh_claude.run_task`** service - Run a Claude task with optional completion notification

### Assist Integration

When the integration is set up, "BRUH Claude" appears as a conversation agent in Settings > Voice Assistants. Select it as your default assistant to route voice/text queries through Claude.

### Services

```yaml
# Send a prompt and get a response
service: bruh_claude.send_prompt
data:
  prompt: "What entities are offline?"
  timeout: 120

# Run a background task with notification
service: bruh_claude.run_task
data:
  prompt: "Check my error log and summarize issues"
  notify: true
  timeout: 300
```
