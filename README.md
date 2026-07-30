# BRUH HA Apps

Home Assistant add-on repository by [BRUH Automation](https://bruhautomation.com).

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbruhautomation%2FBRUH-HA-Apps)

Full documentation for every add-on lives at **[bruhautomation.com](https://bruhautomation.com)**.

## Add-ons

### [brAIn](brain/)

**Give your smart home a mind.** Claude inside Home Assistant with full run of the place — every entity, every device, every area, floor, label, dashboard, helper, automation and add-on. One add-on, one sidebar panel, one Claude login, running on your own Claude subscription.

- **It runs Home Assistant** — 36 native tools for reading and controlling, 65 registry-management services for the parts that normally live behind the Settings UI, and a real shell in `/config` for everything that's still YAML. Create, rename, move, disable and delete areas, floors, labels, devices, entities, integrations, helpers, zones, people, users and dashboards
- **It finds what's broken** — dead batteries, sensors that stopped reporting, devices stuck unavailable, automations that can never fire. **Fix it** makes the change; **Not a problem** means it never asks again
- **It explains your house** — insight cards with real interactive visualisations, proposed for *your* home rather than shipped as defaults. Ask anything and get a card back; keep the good ones as recurring, or drop any of them on a dashboard
- **It remembers** — one editable document of durable facts about your home, learned from conversations, insight runs and study sessions, and read by every part of brAIn
- **It talks** — a conversation agent for Assist, answering in seconds from pre-warmed workers, area-aware and memory-aware
- **It has a terminal** — the real Claude Code CLI in your browser, built for a phone as well as a desk
- **It can be undone** — every file Claude writes under `/config` is snapshotted first; `brain undo` puts it back
- **It shows what it costs** — your Anthropic session and weekly usage in the bar and as HA sensors, with a budget that pauses automatic work before it eats your plan

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

BRUH Automation and these add-ons are independent projects, **not affiliated with, endorsed by, or sponsored by Anthropic, Home Assistant / Nabu Casa, Mojang, or Microsoft**. "Claude" and "Claude Code" are trademarks of Anthropic, PBC; "Minecraft" is a trademark of Mojang Synergies AB; "Home Assistant" is a trademark of the Open Home Foundation. The brAIn add-on runs the official Claude Code CLI under **your own** Anthropic account — your use of Claude through it is governed by [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms). The BRUH Minecraft add-on downloads server software from official upstream sources at runtime and requires you to accept the [Minecraft EULA](https://www.minecraft.net/eula) yourself.

## License

[MIT](LICENSE)
