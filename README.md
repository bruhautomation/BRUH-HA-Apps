# BRUH HA Apps

Home Assistant add-on repository by BRUH Automation.

## Add-ons

### [BRUH Claude Terminal](bruh-claude-terminal/)

<img src="bruh-claude-terminal/logo.png" alt="BRUH Claude Terminal logo" width="400">

Claude Code for Home Assistant — terminal, voice assistant, and proactive AI in one add-on:

- **Fast voice assistant** - pre-warmed Claude workers (~3-5s commands), streaming TTS, conversation memory, multiple personalities, area-aware control
- **Insight jobs** - scheduled Claude reports (daily briefing, anomaly watch, camera check) written to dashboard-ready sensors
- **Native HA API access** via built-in MCP server - entity control, camera vision, history & statistics, automation traces, logs
- **Auto-generated context** - CLAUDE.md describes your installation on startup
- **Git-based config backup** - automatic versioning of your /config directory
- **CLI tools** - `ha-reload`, `ha-log -f`, `ha-entity`, `ha-selftest`, and more
- **Persistent environment** - packages survive restarts; tmux multi-session; mobile UI
- **Usage limit sensors** - your Anthropic session/weekly utilization as HA sensors
- **Automation integration** - trigger Claude tasks from HA automations

### [BRUH Minecraft Server](bruh-minecraft-server/)

<img src="bruh-minecraft-server/logo.png" alt="BRUH Minecraft Server logo" width="400">

Rock-solid Minecraft **Java Edition** server add-on with an ingress management panel, git-based world version control, RCON, and a first-class HA integration:

- **Any flavour** - Paper, Purpur, Folia, Vanilla, Fabric, or Forge, `LATEST` / `SNAPSHOT` / explicit versions resolved from upstream APIs
- **Ingress panel** - dashboard, live console, player management, editable `server.properties`, plugin installer, backup browser
- **Git-based world version control** - every snapshot committed; one-click restore
- **Deep HA integration** - 12 sensors, 2 binary sensors, 4 buttons, 13 services; config-flow + discovery
- **Aikar-tuned JVM** on Java 21, crash auto-restart, graceful shutdown
- **Plugin management** with `If-Modified-Since` caching

## Installation

Add this repository URL to your Home Assistant add-on store:

```
https://github.com/bruhautomation/BRUH-HA-Apps
```

## License

MIT
