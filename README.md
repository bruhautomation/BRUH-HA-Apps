# BRUH HA Apps

Home Assistant add-on repository by [BRUH Automation](https://bruhautomation.com).

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbruhautomation%2FBRUH-HA-Apps)

Full documentation for every add-on lives at **[bruhautomation.com](https://bruhautomation.com)**.

## Add-ons

### [brAIn](brain/)

**Your house already has nerves. Now give it a brAIn.** Claude plus a suite of new tools hands it the keys. Stop programming your house — let it think.

A Home Assistant add-on that runs Claude Code and a suite of tools inside HA, which builds a permanent memory of your house. It sees the whole system — every entity, device, area, floor, dashboard, helper and automation — and it can change any of it. Explain a broken automation. Fix it. Write a new one. Remember why, next time.

That memory isn't a black box: open it, read it, edit it, correct it. An insights panel shows what it knows about your house and what it's done there — in the sidebar, or embedded straight into your dashboards. Reach it as your conversation agent, through a full-featured chat interface, or from native Claude Code; your automations can call it too, which means your house can ask for help before you notice anything's wrong.

Most of what it eventually tells you is **measured** rather than guessed — when the house gets up, what a reading normally is at this hour of this week, how fast each room loses heat, what you keep doing by hand — worked out overnight from what Home Assistant already records, with no Claude run at all. Every one of those has a floor under it, so a new install is quiet for a while; the **Knowledge** tab is what says which measurement is waiting on what, and roughly when. And when something does go wrong, brAIn writes the evidence down by itself: one redacted text file per problem, where you can read it and paste it.

One install, one sidebar panel, one login. **Runs on the Claude Pro or Max subscription — or your own API key**.

📖 **[bruhautomation.com/brain](https://bruhautomation.com/brain/)** · [add-on README](brain/)

### [BRUH Minecraft](bruh-minecraft-server/)

> ⚠️ **Experimental.** Works, and is still settling — expect rough edges.

Rock-solid Minecraft **Java Edition** server add-on with an ingress management panel, git-based world version control, RCON, and a first-class HA integration:

- **Any flavour** - Paper, Purpur, Folia, Vanilla, Fabric, or Forge, `LATEST` / `SNAPSHOT` / explicit versions resolved from upstream APIs
- **Ingress panel** - dashboard, live console, player management, editable `server.properties`, plugin installer, backup browser
- **Git-based world version control** - every snapshot committed; one-click restore
- **Deep HA integration** - 12 sensors, 2 binary sensors, 4 buttons, 13 services; config-flow + discovery
- **Aikar-tuned JVM** on Java 25, crash auto-restart, graceful shutdown
- **Plugin management** with `If-Modified-Since` caching

### [BRight](bright/)

> ⚠️ **Experimental.** Works, and is still settling — expect rough edges.

**Your music, your lights, actually in time.** Point BRight at a folder of
music and it analyzes every track once — tempo and beat grid, song sections
and drops, synced lyrics — then compiles a light show for *your* lights ahead
of time. Say "start party mode" and the music plays while LIFX bulbs and
switch-driven party lights run the show in sync.

- **LIFX over the LAN, not through service calls** — beat-locked effects are
  pushed *onto* the bulbs as LIFX waveforms, so the network only carries
  scene changes and hits
- **The speaker's delay is measured, not guessed** — a click track, your
  phone's microphone, and a cross-correlation, per media player
- **Everything expensive happens before the party** — at show time the engine
  is a clock and a cue list
- **A light map with roles** — candles glow and never strobe, lamps and
  downlights carry the beat, strips carry sweeps, party lights and lasers are
  saved for the moments that earn them
- **Two directors** — a built-in algorithmic choreographer that always
  compiles, and Claude (through brAIn, when it is installed) when you want a
  show designed rather than derived

📖 [add-on README](bright/) · [full documentation](bright/DOCS.md)

### [BRUH Print](bruh-print/)

**Type a word, get a label.** Plug a DYMO LabelWriter into your Home
Assistant box over USB and print to it from the sidebar, from a dashboard, or
from an automation.

- **A real designer** — text, Code 128 barcodes, QR codes, boxes, rules and
  images, dragged and resized on the label itself, in millimetres
- **Type it and print it** — every way of breaking your words across lines is
  rendered and the biggest wins, so you only say the words
- **Templates** — write `{{sample}}` anywhere and it becomes a box to fill in,
  in the panel, in the card, and in `bruh_print.print_template`
- **It knows what is in the printer** — which stock is in which roll, checked
  before every print, because a LabelWriter cannot tell you itself and a
  2.25″ label on a 0.56″ roll prints across the liner once per copy
- **Twin Turbo roll selection**, and no roll control at all on a printer that
  has one
- **No CUPS, no drivers** — it speaks the LabelWriter's raster protocol
  directly over USB
- **A Lovelace card** with a text mode, a template mode and one-press buttons

📖 [add-on README](bruh-print/) · [full documentation](bruh-print/DOCS.md)

### [BRUH Bambu Studio](bruh-bambu-studio/)

> ⚠️ **Experimental.** Keep Bambu Handy or the printer's screen within reach
> the first few times you start a print from Home Assistant.

**Slice and print on your Bambu Lab printers from Home Assistant.** Bambu
Studio itself, in the sidebar, and every printer on your LAN under Home
Assistant's control.

- **The real slicer** — Bambu Lab's own Bambu Studio, downloaded on first
  start and run on a virtual screen you use from the sidebar
- **Live printer status** — state, progress, time left, temperatures, speed
  and AMS trays, as sensors per printer
- **Print from anywhere** — drop a project or model into `/share/bambu` and
  print it; unsliced projects are sliced first by Bambu Studio's own command
  line, uploaded and started
- **Full control** — pause, resume, stop, speed, chamber light, temperatures,
  homing and G-code, on the panel and as `bruh_bambu.*` services
- **Design parts with brAIn** (optional) — describe a part, shape it in
  conversation, watch it in a 3D view with measuring, keep every version, and
  say *print it*: brAIn picks the printer, a tray per colour and the settings
- **brAIn runs it** — "how long is left on the print?", "pause the printer",
  "print the benchy on the X1C"
- **Printer cards** for Lovelace and Morph
- **amd64 only** — Bambu Lab publishes Bambu Studio for Linux on x86-64 only

📖 [add-on README](bruh-bambu-studio/) · [full documentation](bruh-bambu-studio/DOCS.md)

### [Morph](morph/)

> ⚠️ **Experimental — not recommended for general use yet.** Try it beside your
> normal dashboards, not instead of them.

**A dashboard that moves, and that you change by saying what you want.**
Morph lives in the sidebar: rooms are sections, cards open in place while
everything else makes room, and in Edit you hold anything and tell brAIn what
should change.

- **One grammar** — tap does the main thing, slide sets a level, hold opens
  the card in place with its history
- **Any Lovelace card**, hosted inside a section
- **Tell brAIn** — it acts at once, on the dashboard or the house, and every
  change is one git commit you can keep or undo
- **It learns, and asks first** — suggestions from how the dashboard is used,
  shown in place with Do it, Not now and No
- **It fixes itself** — Morph's own faults go through brAIn's development loop
  to be fixed in its code

📖 [add-on README](morph/) · [full documentation](morph/DOCS.md)

## Installation

Click the badge above, or add this repository URL to your Home Assistant add-on store (**Settings → Add-ons → Add-on Store → ⋮ → Repositories**):

```
https://github.com/bruhautomation/BRUH-HA-Apps
```

## Community

[**Discussions**](https://github.com/bruhautomation/BRUH-HA-Apps/discussions) is where questions, ideas and setups go:

- [**Q&A**](https://github.com/bruhautomation/BRUH-HA-Apps/discussions/categories/q-a) — stuck on install, config or a prompt? Ask here.
- [**Ideas**](https://github.com/bruhautomation/BRUH-HA-Apps/discussions/categories/ideas) — propose a feature; the ones people want become roadmap issues.
- [**Show and tell**](https://github.com/bruhautomation/BRUH-HA-Apps/discussions/categories/show-and-tell) — automations brAIn wrote, dashboards, server setups.
- [**Announcements**](https://github.com/bruhautomation/BRUH-HA-Apps/discussions/categories/announcements) — releases and breaking changes.

[Issues](https://github.com/bruhautomation/BRUH-HA-Apps/issues) are for reproducible bugs and accepted work.

## Disclaimer

BRUH Automation and these add-ons are independent projects, **not affiliated with, endorsed by, or sponsored by Anthropic, Home Assistant / Nabu Casa, Mojang, or Microsoft**. "Claude" and "Claude Code" are trademarks of Anthropic, PBC; "Minecraft" is a trademark of Mojang Synergies AB; "Home Assistant" is a trademark of the Open Home Foundation; "LIFX" is a trademark of LIFX Pty Ltd, and BRight speaks the published LIFX LAN protocol without being affiliated with or endorsed by them; "DYMO" and "LabelWriter" are trademarks of Newell Brands, and BRUH Print speaks the published LabelWriter raster protocol without being affiliated with or endorsed by them. The brAIn add-on runs the official Claude Code CLI under **your own** Anthropic account — your use of Claude through it is governed by [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms). The BRUH Minecraft add-on downloads server software from official upstream sources at runtime and requires you to accept the [Minecraft EULA](https://www.minecraft.net/eula) yourself.

## Credits

brAIn's web terminal began as
[Claude Terminal](https://github.com/heytcass/home-assistant-addons) by Tom
Cassady — that add-on is what showed Claude Code could live inside Home
Assistant behind ingress at all. BRUH Terminal was built on it, and brAIn is
what BRUH Terminal grew into.

BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) by
Franck Nijhof (MIT).

## License

[MIT](LICENSE)
