# BRUH HA Apps

Home Assistant add-on repository by [BRUH Automation](https://bruhautomation.com).

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbruhautomation%2FBRUH-HA-Apps)

Full documentation for every add-on lives at **[bruhautomation.com](https://bruhautomation.com)**.

## Add-ons

### [BRain](brain/)

Your home's brain — a Claude Code terminal, an AI insights dashboard, and one shared memory that learns your house over time, in a single add-on behind one sidebar panel and one Claude login.

**Terminal**

- **Native HA API access** via a built-in MCP server — entity control, camera vision, history & statistics, automation traces, logs
- **Fast voice assistant** — pre-warmed workers (~3-5s commands), streaming TTS, conversation memory, area-aware control
- **Auto-generated context** — `CLAUDE.md` describes your installation on startup
- **Two-command CLI** — `brain` for memory, learning and undo; `ha` for `ha log`, `ha reload`, `ha entity`, and the rest
- **Undo for Claude's edits** — every file Claude writes under `/config` is snapshotted first; `brain undo` puts it back
- **Persistent environment** — packages survive restarts; tmux multi-session; mobile UI
- **Usage limit sensors** — your Anthropic session/weekly utilisation as HA sensors

**Insights**

- **Nine built-in categories** — Overview, Energy, Climate, Lighting, Security, Presence, Media, Device Health, Automations
- **Ask anything** — free-form questions become bespoke insight cards; one click makes them recurring
- **Dashboard cards** — embed any insight on an HA dashboard via token-protected Webpage cards
- **Sandboxed rendering** — visualisations run in sandboxed iframes

**Memory**

- **One document** of durable facts about your home, shared by the terminal, voice, and every insight run
- **Guesses, not questionnaires** — BRain proposes what it believes and you confirm or reject; never more than three waiting on you
- **Study sessions** — `brain learn energy` sends it off to investigate a topic and write down what it finds
- **A change log with undo** — see exactly what it learned this week, and revert any single line

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
