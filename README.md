# BRUH HA Apps

Home Assistant add-on repository by BRUH Automation.

## Add-ons

### [BRUH Claude Terminal](bruh-claude-terminal/)

Enhanced Claude Code terminal for Home Assistant. Everything the original Claude Terminal does, plus:

- **Native HA API access** via built-in MCP server - entity states, service calls, automation traces, logs
- **Auto-generated context** - CLAUDE.md describes your installation on startup
- **Git-based config backup** - automatic versioning of your /config directory
- **Config reload** - `ha-reload automations` right from the terminal
- **Log access** - `ha-log core -f` for real-time log tailing
- **Persistent environment** - packages survive restarts
- **Multi-session support** - background tasks, multiple tmux windows
- **Token usage sensors** - real Anthropic API token counts as HA sensors
- **Assist integration** - use Claude as a conversation agent
- **Automation integration** - trigger Claude tasks from HA automations

## Installation

Add this repository URL to your Home Assistant add-on store:

```
https://github.com/bruhautomation/BRUH-HA-Apps
```

## License

MIT
