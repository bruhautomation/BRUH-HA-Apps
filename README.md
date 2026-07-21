# BRUH HA Apps

Home Assistant add-on repository by [BRUH Automation](https://bruhautomation.com).

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbruhautomation%2FBRUH-HA-Apps)

Full documentation for every add-on lives at **[bruhautomation.com](https://bruhautomation.com)**.

## Add-ons

### [BRUH Terminal](bruh-claude-terminal/)

Claude Code for Home Assistant — terminal, voice assistant, and proactive AI in one add-on:

- **Fast voice assistant** - pre-warmed Claude workers (~3-5s commands), streaming TTS, conversation memory, multiple personalities, area-aware control
- **Insight jobs** - scheduled Claude reports (daily briefing, anomaly watch, camera check) written to dashboard-ready sensors
- **Native HA API access** via built-in MCP server - entity control, camera vision, history & statistics, automation traces, logs
- **Auto-generated context** - CLAUDE.md describes your installation on startup
- **Long-term memory** - the assistant learns your home's nicknames, patterns, and preferences over time
- **Git-based config backup** - automatic versioning of your /config directory
- **CLI tools** - `ha-reload`, `ha-log -f`, `ha-entity`, `ha-selftest`, and more
- **Persistent environment** - packages survive restarts; tmux multi-session; mobile UI
- **Usage limit sensors** - your Anthropic session/weekly utilization as HA sensors
- **Automation integration** - trigger Claude tasks from HA automations

### [BRUH Insights](bruh-insights/)

AI-powered insights dashboard — Claude analyzes your Home Assistant data and generates beautiful, interactive visualizations in the sidebar:

- **Nine built-in categories** - Overview, Energy, Climate, Lighting, Security, Presence, Media, Device Health, Automations
- **Ask anything** - free-form questions become bespoke insight cards; one click makes them recurring
- **Memory that loops** - findings, answers, and feedback persist and feed every future analysis; questions are never asked twice
- **Deep presence** - cross-references phone sensors (WiFi, geocoded address, charging) and cites its evidence
- **Dashboard cards** - embed any insight on an HA dashboard via token-protected Webpage cards
- **Sandboxed rendering** - visualizations run in sandboxed iframes; `/config` is mounted read-only

### [BRUH Minecraft](bruh-minecraft-server/)

Rock-solid Minecraft **Java Edition** server add-on with an ingress management panel, git-based world version control, RCON, and a first-class HA integration:

- **Any flavour** - Paper, Purpur, Folia, Vanilla, Fabric, or Forge, `LATEST` / `SNAPSHOT` / explicit versions resolved from upstream APIs
- **Ingress panel** - dashboard, live console, player management, editable `server.properties`, plugin installer, backup browser
- **Git-based world version control** - every snapshot committed; one-click restore
- **Deep HA integration** - 12 sensors, 2 binary sensors, 4 buttons, 13 services; config-flow + discovery
- **Aikar-tuned JVM** on Java 25, crash auto-restart, graceful shutdown
- **Plugin management** with `If-Modified-Since` caching

## Installation

Click the badge above, or add this repository URL to your Home Assistant add-on store (**Settings → Add-ons → Add-on Store → ⋮ → Repositories**):

```
https://github.com/bruhautomation/BRUH-HA-Apps
```

## Disclaimer

BRUH Automation and these add-ons are independent projects, **not affiliated with, endorsed by, or sponsored by Anthropic, Home Assistant / Nabu Casa, Mojang, or Microsoft**. "Claude" and "Claude Code" are trademarks of Anthropic, PBC; "Minecraft" is a trademark of Mojang Synergies AB; "Home Assistant" is a trademark of the Open Home Foundation. The BRUH Terminal and BRUH Insights add-ons run the official Claude Code CLI under **your own** Anthropic account — your use of Claude through them is governed by [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms). The BRUH Minecraft add-on downloads server software from official upstream sources at runtime and requires you to accept the [Minecraft EULA](https://www.minecraft.net/eula) yourself.

## License

[MIT](LICENSE)
