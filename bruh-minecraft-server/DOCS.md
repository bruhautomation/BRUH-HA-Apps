# BRUH Minecraft Server — Documentation

Complete configuration reference, operational notes, and integration details.

---

## 0. Feature overview (what this add-on does)

A bird's-eye view so you can skim to the sections that matter to you:

- **Rock-solid Paper / Purpur / Folia / Vanilla / Fabric / Forge** server-jar management. `LATEST`, `SNAPSHOT`, or any pinned version; auto-resolves through PaperMC's `fill.papermc.io/v3` API (with v2 fallback), caches to `/data/server-cache`, re-downloads only when upstream changes.
- **Aikar-flagged Eclipse Temurin 25 JVM** with configurable memory, extra JVM args, and crash auto-restart (rate-limited so a fatal misconfig can't runaway-restart).
- **First-run wizard** for the EULA + online/offline mode + server type — install, start, three clicks, done.
- **Ingress panel** at the add-on's sidebar entry with:
  - Live dashboard — status dot, TPS health badge, *Tune for my hardware* recommender, players, latency.
  - Streaming console over SSE with INFO / WARN / ERROR colouring and a command input.
  - Players tab with one-click op / deop / kick / ban / pardon / whitelist.
  - Per-world **Server Properties** editor (everything that's a `server.properties` key, validated server-side).
  - Plugins tab with curated one-click installers, install-by-URL, and duplicate-jar quarantine.
  - Backups tab browsing git snapshots and tar.gz archives with per-entry restore.
  - Worlds tab — switch / create / **import-from-zip** / delete, plus **Featured worlds** one-click server-side installs (e.g. **Drehmal: APOTHEOSIS**) playable on iPad/iPhone via Geyser with zero installs.
  - Resource Packs tab — upload a pack, get a URL + SHA-1, *Apply* writes them into the active world.
- **Bedrock cross-play** via Geyser (+ Floodgate when applicable). Auto-installed, auto-configured for your auth-type choice, and MTU / auth-type / validate-bedrock-login patched on every boot so iOS, Android, Switch, Xbox, PS and Windows 10/11 can connect.
- **Offline mode done right.** Set a world's `online-mode: false` (panel → Server Properties) and the add-on silently forces `enforce-secure-profile: false`, switches Geyser to `auth-type: offline`, uninstalls Floodgate, and sets `validate-bedrock-login: false` — the full chain of changes Microsoft / Mojang's and GeyserMC's defaults gate behind one flag.
- **Per-world settings.** Each world has its own `server.properties` — one world can be creative, another survival; switching loads each world's own gamemode, difficulty, world-gen, whitelist, etc.
- **World safety.** Incremental git-backed snapshots or tar.gz archive backups on a configurable schedule, with one-click restore from either format.
- **Home Assistant integration** — sensors (players, TPS, MOTD, difficulty, gamemode, …), binary sensors (online, RCON), buttons (Backup / Restart / Stop / Save), and 13 services (`rcon_command`, `say`, `give`, `set_weather`, `set_time`, `backup_now`, lifecycle, player management).
- **Self-healing.** Ghost-session auto-kicker clears stuck Bedrock handshakes; RCON client is thread-safe; bad plugin URLs log a warning instead of tanking startup; crash banner surfaces the last error lines on the dashboard.
- **Zero-dependency architecture.** Everything runs inside the one add-on container — no separate proxy jars, no VPS, no external broker.

> See [CHANGELOG.md](CHANGELOG.md) for the full version history.

---

## 0.1 Quick start

1. **Add the repository** in HA → **Settings → Add-ons → ⋮ → Repositories**:
   ```
   https://github.com/bruhautomation/BRUH-HA-Apps
   ```
2. Install **BRUH Minecraft Server** and click **Start**.
3. Open the sidebar **Minecraft** entry. The **welcome wizard** asks for the EULA, the online/offline mode for the first world, and the server type (Paper is the default). Click *Start the server* — the add-on restarts and the panel takes over.
4. **Connect.** Java Edition → `<your-HA-host>:25565`. Bedrock → `<your-HA-host>:19132` (UDP; on the same LAN the server auto-appears in Minecraft's **Friends** tab).
5. **OP yourself.** Join once, then on the panel's **Players** tab click *op* next to your name. Ops persist in `ops.json` per world.

> The defaults are sensible for a home / family server. The rest of this document is reference reading.

---

## 0.2 Switchable server profiles (multi-world)

Since 1.3.0 the add-on can host multiple independent servers and flip between them with one option change. Each **world profile** is a full server root — its own world files, `server.properties`, plugins, and backup history — living at `/config/minecraft-worlds/<name>/`. Only one is active at a time.

Why you might want this:

- A creative-mode sandbox world for kids, plus a survival world for the adults, without any world-file mixing.
- Seasonal events (a "Halloween" profile, a "Summer vanilla" profile).
- A throwaway test server for trying new plugin combos without risking the main save.

How to switch:

- **Panel → Worlds tab** (recommended). Shows every world, its on-disk size, the active one, and a "Switch" button. Clicking Switch writes `active_world` and restarts the add-on so the new world loads — one click, no second step.
- **Add-on Configuration tab.** Set `active_world: <name>` and restart — same effect.
- **CLI.** From the terminal: `world-manager.sh list | create <name> [seed] | switch <name> | delete <name> | active`. World names are 1–32 characters, letters/digits/underscore/dash only.

### What's per-world vs shared (important!)

Since 1.8.0 **gameplay settings are per-world** — each world has its own `server.properties`, so one world can be creative and another survival. These things **travel with the world** — each has its own copy:

| Per-world | Notes |
|-----------|-------|
| `server.properties` — gamemode, difficulty, PVP, hardcore, whitelist, view/sim distance, world-gen (level name/seed/type, packs, structures, mobs), online-mode, resource pack, command blocks, op level, connection throttle, idle timeout, MOTD, … | Edited from the panel's **Server Properties** tab. Seeded with sensible defaults the first time a world boots, then yours forever. |
| World save files (`world/`, `world_nether/`, `world_the_end/`) | The actual terrain & player data. |
| `plugins/` folder on disk | Jars live under each world's `plugins/`. |
| Backup history | `/config/minecraft-backups/<world>/` — the Backups tab only shows the active world's snapshots. |
| `ops.json`, `whitelist.json`, `banned-players.json` | Each world has its own op / whitelist / ban list. |

These are **install/container-level** and shared across every world (they're in the add-on's Configuration tab):

| Shared | Why |
|--------|-----|
| `memory_mb`, `use_aikar_flags`, `extra_jvm_args` | One JVM runs at a time, so heap/flags are process-level. |
| `server_type`, `minecraft_version` | One server jar is installed at a time. |
| `auto_update_server`, backups, `auto_restart_*` | Lifecycle policy for the add-on. |
| `enable_bedrock_support`, `geyser_*` | Geyser is installed once; "auto" auth reads the **active** world's online-mode. |
| `plugins:` list + `install_*` toggles | Jars get copied into the **active** world's `plugins/` on boot. |
| RCON password | Single secret per install, stored at `/data/panel/rcon.secret`. |
| `enable_ha_integration`, `announce_ha_events`, `auto_kick_ghost_sessions`, `auto_quarantine_duplicates`, `log_level` | Add-on-wide behaviour. |

**Implication:** want a peaceful creative world and a hard survival world? Easy now — set each world's difficulty/gamemode in the panel's Server Properties tab; they don't affect each other. Switching worlds loads that world's own settings.

### Switching — how it works (one click, since 1.2.9)

Panel → **Worlds** tab → click **Switch** on the profile you want. The panel:

1. Writes `active_world: <name>` into your add-on options via the Supervisor API.
2. Immediately triggers a full add-on restart (`POST /addons/self/restart`). The container goes down, `main()` in `run.sh` runs again on startup, `ensure_worlds_layout` re-points the `/config/minecraft` symlink at the new profile, and the server boots with that profile's world / plugins / ops.

The panel is unreachable for ~30 s while the container restarts — refresh after that. If the Supervisor refuses the restart call (rare; only if the add-on was granted reduced permissions), the panel surfaces the exact failure and you can click **Restart** on the HA add-on page manually.

**Why not use the header's Restart button?** That button only RCON-stops the JVM, which `run_server_loop` then relaunches inside the same container. `ensure_worlds_layout` does NOT re-run, so the symlink stays pointed at the old world. JVM-only restart is faster (~15 s vs ~30 s) and is the right tool for applying a Server-Properties edit that needs a restart, but it can't switch worlds.

### Notes

- The legacy `/config/minecraft/` path is migrated to the `default` profile on first boot of 1.3.0, so existing installs keep their world unchanged.
- `delete` refuses to remove the currently-active profile. Switch away first.
- `level-name` is now a **per-world** Server-Properties setting (panel), defaulting to `world`. Changing it makes the server load/generate a different save folder inside that world; the old `world/` stays on disk but isn't loaded.

---

## 0.25 Featured worlds (one-click, server-side — e.g. Drehmal)

Since 1.14.0 the **Worlds** tab has a **Featured worlds** section: curated
community worlds you can install with one click. Everything is hosted
**server-side**, which is the whole point — players (including **iPad / iPhone**
on Bedrock via Geyser) join and explore with **zero local installs**.

**What "Install" does** (runs in the background; the panel shows progress):

1. Downloads the complete world save — including its **bundled datapacks** —
   onto the server and stages it as a **new switchable world profile**. Your
   current world is untouched.
2. Writes that world's `server.properties` from the catalog recipe (gamemode,
   difficulty, command blocks, spawn protection, view distance, …).
3. Records a `.curated.json` marker so the next step knows what the world needs.
4. Downloads the world's resource pack, **hosts it for Java players**, and
   **auto-converts it to a Bedrock pack** dropped into that world's
   `plugins/Geyser-Spigot/packs/` folder.

**Then click Switch** (in the Worlds table). Switching to a featured world also:

- **Pins the server** to the software + Minecraft version the world requires
  (these are global options — one JVM runs at a time). Switching back to one of
  your own worlds may need you to re-pick a version on the Configuration tab.
- **Enables Bedrock support** so the iPads/iPhones can join.
- Restarts the add-on so it boots the new world (~30 s).

### Drehmal: APOTHEOSIS

[Drehmal: APOTHEOSIS](https://www.drehmal.net) is a hand-built 12k × 12k
survival/adventure world (v2.2.2, **Minecraft 1.20.1**, **Paper**). The world
download is ~1.5 GB and comes from Google Drive, so the first install can take
several minutes and a chunk of disk.

**iPad / iPhone (Bedrock) reality check** — this is hosted entirely server-side
so the kids just join, but Bedrock has hard platform limits:

- ✅ **The world + its datapacks run on the server.** Bedrock clients join via
  Geyser and can explore the *entire* map with no install.
- ✅ **Textures are auto-pushed by Geyser.** The converter turns Drehmal's Java
  pack into a Bedrock pack Geyser sends on join — best-effort: vanilla block /
  item retextures come across; **custom 3D models, CustomModelData items, and
  animated textures don't convert** (a Bedrock limitation, not a bug).
- ❌ **Drehmal's optional Fabric mods cannot run on Bedrock at all** — there's no
  Java/Fabric on iPad/iPhone, and nothing server-side can change that. Per
  Drehmal's own docs these mods are **client-side only** (shaders, ambience,
  performance) and **aren't required to play**, so nothing gameplay-wise is lost.

For full visual fidelity you'd play on **Java** with Drehmal's official
installer (mods + pack) — but for family Bedrock play, the server-side install
gets everyone into the map with zero setup.

> **Tip:** if you have a hand-made or better Bedrock conversion of the pack,
> drop the `.mcpack` into `/config/minecraft-worlds/<world>/plugins/Geyser-Spigot/packs/`
> and Geyser will push it instead.

---

## 0.3 Panel access on mobile

The panel is served over HA's ingress, so anywhere the Home Assistant Companion app works (iOS, Android, web), the panel works too. 1.2.6 added a full mobile responsive layout:

- Tab row scrolls horizontally with momentum on iOS; the right edge fades out so you can tell there's more tabs to reach.
- Forms stack vertically on narrow viewports.
- Tables scroll horizontally inside their own container instead of breaking the layout.
- Input fields use 16px font to avoid iOS Safari's auto-zoom on focus.
- Touch targets honour the 40–44px minimum the iOS/Material design guides recommend.

If a page feels cramped, pull the companion app's **Sidebar → Minecraft** tile to full-width (there's no benefit to the "card" view here — the panel's own layout wants the pixels).

---

## 1. Configuration reference

The add-on's **Configuration** tab holds only **install/container-level** options (below). All are validated against the schema in `config.yaml`.

> **Where do gameplay settings live?** Not here. Gamemode, difficulty, PVP, world-gen, whitelist, view distance, resource pack, etc. are **per-world** — edit them in the ingress panel's **Server Properties** tab and they're saved to that world's `server.properties` (see section 1.x "Per-world settings" below).

### Required

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `eula` | bool | `false` | **You must set this to `true` to start the server.** Accepts the Minecraft EULA at <https://www.minecraft.net/eula>. |

### World selection

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `active_world` | `^[A-Za-z0-9_-]{1,32}$` | `default` | Which saved server profile is currently live. Each profile lives under `/config/minecraft-worlds/<name>/` with its own world, `server.properties`, plugins, and backups. See section 0.2 for the full multi-world workflow. |

### Server type & version

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `server_type` | `paper \| purpur \| folia \| vanilla \| fabric \| forge` | `paper` | Which distribution to run. |
| `minecraft_version` | `LATEST \| SNAPSHOT \| x.y[.z]` | `LATEST` | Game version. `LATEST` resolves to the newest stable release of the selected type. |
| `auto_update_server` | bool | `true` | If `true`, re-resolve the jar on every add-on start. Disable to pin to the currently installed jar. |

Forge uses an installer and may need a few extra minutes on the first boot while it downloads its library tree.

### Per-world settings (panel → Server Properties)

These are **not** add-on options. Each world has its own `server.properties`; edit these from the ingress panel's **Server Properties** tab and they save to the active world (so a creative world and a survival world keep their own values). The add-on seeds these defaults the first time a world boots, then never overwrites them. Difficulty, gamemode, and whitelist apply live over RCON; the rest take effect on the next restart.

| Key | Type / values | Default | Notes |
|-----|---------------|---------|-------|
| `motd` | string | `A BRUH Minecraft Server` | Server-list message. |
| `difficulty` | `peaceful \| easy \| normal \| hard` | `normal` | |
| `gamemode` | `survival \| creative \| adventure \| spectator` | `survival` | |
| `force-gamemode` | bool | `true` | Put every player back into `gamemode` on each join — the fix for "I set creative but it keeps loading survival". Set `false` to let players keep their last mode. |
| `max-players` | 1–1000 | `20` | |
| `view-distance` / `simulation-distance` | 3–32 | `10` | `simulation-distance` is the bigger performance lever. |
| `online-mode` | bool | `true` | Validate logins against Microsoft/Mojang. **Off** = cracked/offline play (kids without an Xbox account, LAN). |
| `enforce-secure-profile` | bool | `false` | Require Mojang-signed chat (MC 1.19+). Auto-forced `false` whenever `online-mode` is off. |
| `pvp` / `hardcore` / `allow-flight` | bool | `true` / `false` / `false` | `hardcore=true` forces survival. |
| `white-list` | bool | `false` | Only listed players may join (manage names in the Players tab). |
| `spawn-protection` | 0–10000 | `16` | |
| `level-name` | string | `world` | World save folder. |
| `level-seed` | string | `""` (random) | Only affects a freshly generated world. |
| `level-type` | `minecraft:normal \| :flat \| :large_biomes \| :amplified` | `minecraft:normal` | |
| `initial-enabled-packs` / `initial-disabled-packs` | comma list | `vanilla` / `""` | Experimental feature packs (keep `vanilla`). See note below. |
| `allow-nether` / `generate-structures` | bool | `true` | |
| `spawn-monsters` / `spawn-animals` / `spawn-npcs` | bool | `true` | |
| `prevent-proxy-connections` / `hide-online-players` | bool | `false` | |
| `resource-pack` / `resource-pack-sha1` / `require-resource-pack` | URL / string / bool | `""` / `""` / `false` | |
| `max-world-size` | 1–29999984 | `29999984` | |
| `network-compression-threshold` | -1–65536 | `256` | |
| `entity-broadcast-range-percentage` | 10–1000 | `100` | |
| `enable-command-block` | bool | `false` | Needed for command blocks / many adventure maps. |
| `op-permission-level` | 1–4 | `4` | Power level granted to OPs. |
| `connection-throttle` | 0–60000 | `4000` | Per-IP connection gap (ms). `0` avoids the "Slow down!" kick on rapid iOS retries. |
| `player-idle-timeout` | 0–1440 | `0` | Auto-kick after N idle minutes. `0` disables. |

> **OP a player:** join once, then click **op** on the Players tab (ops persist per-world in `ops.json`). For creative building, set `gamemode=creative` (and `enable-command-block=true` if you want command blocks) on that world.

> **Enabling experiments:** Mojang gates experimental content — and the newest experimental game rules — behind named *feature packs*. Add them to `initial-enabled-packs` (comma-separated, keep `vanilla`). Recent examples on 1.21.x: `minecart_improvements`, `redstone_experiments`, `trade_rebalance`. Experiments are baked in at world **creation**, so this only affects **newly generated** worlds — create a fresh world from the **Worlds** tab with the pack enabled.

#### "Please log into Xbox to join this server" / "You are not permitted to join…"

If you — or your kids — want to play **without an Xbox/Microsoft sign-in** on either Java **or** Bedrock:

1. Set `online-mode: false` on the world (panel → Server Properties).
2. Leave `enforce-secure-profile: false` (the default; auto-forced off whenever `online-mode` is `false`).
3. Leave `geyser_auth_type: auto` (add-on option; resolves to `offline` automatically when the active world's `online-mode` is `false`).
4. Restart. Any Java username now connects, and Bedrock clients join under whatever username is set on their device — **no Xbox sign-in required**.

Two important subtleties with Geyser:

- `geyser_auth_type: floodgate` **still requires the Bedrock client to be signed in to Xbox Live** (Floodgate uses the XUID to identify the player). It's the right default for public-facing servers, but it's not "no login needed."
- `geyser_auth_type: offline` removes the Xbox requirement entirely. Bedrock usernames are taken verbatim from the player's device, and Floodgate's `.`-prefix no longer applies. This is the correct setting for LAN-only / family servers. Two things the add-on does under the hood for this mode:
    1. **Uninstalls Floodgate** (Geyser delegates auth to it whenever the jar is present, and Floodgate requires a valid Xbox XUID).
    2. **Sets `advanced.bedrock.validate-bedrock-login: false`** in Geyser's config — this is the toggle that actually suppresses Geyser's pre-auth signed-chain check. Without it, Geyser kicks every Bedrock client whose login JWT isn't signed by Mojang's Xbox Live root key, which includes every LAN-only device and every client that isn't currently signed in to Xbox.

Offline mode is **not safe for public/internet-exposed servers** — anyone can spoof any username. Use it only on LAN or when you fully trust the player pool.

#### Cheats / creative commands

To use the "cheat" commands (`/gamemode`, `/give`, `/tp`, `/summon`, `/fill`, …):

1. Set that world's `gamemode` (or just OP yourself — OPs can always run them). On the panel's Server Properties tab, set `enable-command-block: true` if you want command blocks.
2. Join once, then click **op** next to your name on the panel's **Players** tab. Ops persist per-world in `ops.json`.

### JVM / performance

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `memory_mb` | 512–65536 | `2048` | Applied as both `-Xms` and `-Xmx` (recommended for steady GC behaviour). |
| `use_aikar_flags` | bool | `true` | Use the widely-recommended Aikar G1GC tuning for Minecraft. |
| `extra_jvm_args` | string | `""` | Append-your-own extra JVM flags. |

### RCON

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `rcon_password` | password | `""` (auto-generated) | Pre-set the RCON password instead of letting the add-on generate one. Leave blank and a random 32-character password is written to `/data/panel/rcon.secret` (mode `0600`) on first boot. |

RCON is always enabled on port `25575` and bound to `127.0.0.1`. The password never leaves the HA host — only the ingress panel and HA bridge use it. You almost never need to set `rcon_password` yourself; the auto-generated one is what you want.

### Backups

| Option | Type | Default |
|--------|------|---------|
| `auto_backup` | bool | `true` |
| `backup_interval_minutes` | 5–1440 | `60` |
| `backup_keep_count` | 1–500 | `48` |
| `backup_use_git` | bool | `true` |

Two modes:

- **git** — worlds are rsynced into a git repo at `/config/minecraft-backups/git/` and committed with a timestamped message. The `backup_keep_count` oldest commits are pruned on each run.
- **tar.gz archives** — timestamped gzip tarballs are written to `/config/minecraft-backups/archives/` and the oldest-past-`backup_keep_count` are removed.

You can trigger a one-shot backup at any time:

- Panel → **Backup** button in the header.
- HA service call: `bruh_minecraft.backup_now`.

### Auto-restart

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_restart_on_crash` | bool | `true` | Re-launch the JVM automatically when it exits unexpectedly. |
| `auto_restart_schedule` | cron-like string | `""` | Optional scheduled restart (for long-running servers with memory creep). Empty string disables. Example: `"03:00"` for a daily 3 AM restart. |

Rate-limited: a maximum of 5 restarts per 5-minute rolling window before the add-on gives up and reports the crash. The **Stop** button in the panel (and the `bruh_minecraft.stop_server` service) writes a `no_restart` flag so the JVM stays down until you start it again.

### Connection handling

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_kick_ghost_sessions` | bool | `true` | When Paper rejects a new login with "You are already connected to this server!" (because a previous connection hung), a background daemon tails the server log and RCON-kicks the stale session so the retry succeeds. No plugin needed. Leave on unless you're debugging a custom auth plugin. |

The related per-IP **connection throttle** and **idle timeout** are now per-world Server-Properties settings (`connection-throttle`, `player-idle-timeout`) — edit them in the panel. Drop `connection-throttle` to `0` (LAN-safe) to avoid the "Slow down, you're connecting too fast!" kick on rapid iOS retries.

### Plugins (Paper / Purpur / Folia)

Two accepted shapes — pick whichever is easier:

```yaml
# Canonical object form — url required, name optional.
plugins:
  - url: https://example.com/Essentials.jar
    name: Essentials.jar           # optional rename on disk
  - url: https://example.com/ViaVersion.jar
```

```yaml
# Shorthand — a plain URL string also works (since 1.2.7). Filename
# is derived from the URL.
plugins:
  - "https://example.com/ViaVersion.jar"
  - "https://example.com/Essentials.jar"
```

You can mix the two forms in one list. Only `paper`, `purpur`, and `folia` load Bukkit plugins; for `fabric`/`forge` the `plugins:` list is ignored (mods go in `/config/minecraft/mods/` instead). Plugins are fetched with `If-Modified-Since`, so restarts don't re-download unchanged files.

**URL gotchas to save you a debug cycle:**

- `releases/latest/download/X.jar` only resolves when the asset is literally named `X.jar`. Many projects version their filenames (`NickNamer-5.15.0.jar`), which 404s the `/latest/download/` URL — pin the exact version in that case (`releases/download/5.15.0/NickNamer-5.15.0.jar`).
- GitHub anonymous rate limits occasionally serve an HTML page instead of a jar. The add-on rejects downloads that don't start with `PK` and logs `download isn't a valid jar` — just restart the add-on a few minutes later.
- Per-plugin failures are isolated since 1.2.5; a single bad URL can't prevent the server from starting (the failing plugin is skipped with a warning).

### Settings precedence — who wins when you change a thing

Two clean, separate sources of truth (since 1.8.0):

1. **Gameplay/world settings → the active world's `server.properties`.** Edit them in the panel's **Server Properties** tab. On boot the add-on only enforces infra keys (RCON/query/ports) and **seeds defaults the first time**; after that it never overwrites your values, so panel edits persist and stay per-world. Difficulty/gamemode/whitelist apply live over RCON; the rest take effect on the next restart. (`enforce-whitelist` is derived from `white-list`, and `enforce-secure-profile` is forced off in offline mode — both managed for you.)
2. **Install/container settings → the add-on Configuration tab.** EULA, RAM, server type/version, backups, Bedrock, plugins, etc. These are global (one JVM, one jar).
3. **Plugin list (`plugins:`) vs the panel Plugins tab.** The add-on downloads every URL in `plugins:` on boot (with `If-Modified-Since`, so it's cheap). Deleting a plugin from the panel removes the jar from disk, but if the URL is still in `plugins:`, it comes back on next restart. Want it gone? Remove the entry from `plugins:` AND delete the jar.
4. **Ops/whitelist/bans** are per-world JSON files; the Players tab edits them and they persist.

**Rule of thumb:** anything about *how this world plays* → Server Properties tab. Anything about *how the add-on runs* → Configuration tab.

### HA integration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_ha_integration` | bool | `true` | Deploy the `bruh_minecraft` custom integration and start the file-IPC bridge. |
| `announce_ha_events` | bool | `true` | Announce HA-triggered events (restarts, backups) in chat with `/say`. |

### Bedrock cross-play (iOS / Android / consoles)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_bedrock_support` | bool | `true` | Auto-install Geyser + Floodgate so Bedrock clients can connect. |
| `geyser_auth_type` | `auto \| floodgate \| online \| offline` | `auto` | Controls Geyser's Bedrock authentication. `auto` picks `offline` whenever Java `online_mode` is `false` (no Xbox sign-in required on Bedrock either) and `floodgate` otherwise. Set explicitly to override. |
| `geyser_mtu` | 576–1492 | `1400` | Geyser's Bedrock UDP MTU. Drop to `1200` if iOS clients hang on **"Connecting multiplayer server…"** — many home Wi-Fi routers fragment UDP packets above ~1200 bytes mid-handshake, which Bedrock doesn't recover from gracefully. |

With this enabled (the default) the add-on downloads the latest Geyser + Floodgate builds from GeyserMC's v2 API on every boot:

- **Geyser** bridges the Bedrock protocol (UDP:19132) to your Java server.
- **Floodgate** lets Bedrock players log in without needing a Java / Mojang / Microsoft account linked to Minecraft Java Edition.

Bedrock clients connect to `your-home-assistant-host` on port `19132` (UDP) — the same port the add-on already exposes. Cross-play "just works" for Paper / Purpur / Folia and Fabric server types. Vanilla and Forge aren't supported by Geyser-as-a-plugin; you'd need to run Geyser-Standalone separately and should set `enable_bedrock_support: false` to avoid the warning log.

**LAN auto-discovery:** Because this add-on runs with `host_network: true`, the server appears automatically in Minecraft's **Friends** tab on any phone/tablet/console on the same LAN. If it doesn't show up:

- Make sure the device is on the **same subnet/VLAN** as your Home Assistant host. Guest networks, "IoT VLANs," and client isolation block UDP multicast.
- Manual fallback: **Servers** tab → **Add Server** → enter `<HA host IPv4>` and port `19132`.
- `homeassistant.local` sometimes fails on iOS — always prefer the raw IPv4 address.

Geyser + Floodgate files land in `/config/minecraft/plugins/` (or `mods/` for Fabric) and can be deleted from the panel's **Plugins** tab just like any other plugin. If you delete them while the toggle is still on, they'll be re-downloaded the next time the add-on restarts.

### Diagnostics

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `log_level` | `trace \| debug \| info \| notice \| warning \| error \| fatal` | `info` | Verbosity of the add-on's own startup / lifecycle logging (the orange text in the add-on **Log** tab). Has no effect on Minecraft server log output, which is controlled by `logback.xml` inside the server jar. Bump to `debug` or `trace` when filing a bug report. |

---

## 2. Ingress panel tour

The panel is reachable from the **Minecraft** entry in HA's sidebar (or directly via the add-on's ingress link).

### Dashboard

- Real-time status dot, version, uptime, memory.
- **Performance** card with TPS (1m/5m/15m) and latency, plus a colored *healthy / degraded / struggling* badge driven by the 5-minute TPS (green ≥ 19.5, yellow ≥ 17, red below).
- **Tune for my hardware** button (1.9.0+): inspects host RAM/CPU and proposes `memory_mb` (global), plus per-world `view-distance` / `simulation-distance`. Click → confirm with rationale → applies. Memory writes back to the add-on Configuration via the Supervisor; distances write to the active world's `server.properties`. Both take effect on the next restart.
- Current player list with pill badges.
- Quick-chat (`/say`) and one-shot RCON command bar.

### Console

- Streams the live JVM log via SSE (`/api/logs/tail`).
- Colour-coded INFO / WARN / ERROR lines.
- Command input at the top — type a command (no leading slash) and press enter.
- Auto-scroll toggle and clear-buffer button.

### Players

- Table of currently-online players with one-click **op / kick / ban / whitelist-add** actions.
- Manual form for any player name + action, including `pardon` and whitelist-remove.

### Server properties

- Shows the active world's `server.properties` keys.
- Keys marked **editable** (MOTD, difficulty, gamemode, PVP, whitelist, world-gen, …) are written to **this world's** `server.properties` — the per-world source of truth, so the change persists and is scoped to this world. Difficulty/gamemode/whitelist apply live via RCON; the rest take effect on the next restart.
- Infra keys (RCON/query/ports) are read-only — the add-on manages them.

### Plugins

- Lists every `.jar` under `/config/minecraft/plugins/` with size and last-modified time.
- Delete button per plugin.
- Install-by-URL form that uses the same engine as the `plugins:` config option.

### Backups

- Git snapshots with short SHA, timestamp, and subject.
- Archive backups with filename, size, and timestamp.
- One-click **Restore** on any row — the server is stopped, worlds are restored, and the add-on restarts the JVM automatically.
- Backups shown are scoped to the **currently-active world profile**. Switch worlds from the Worlds tab to browse another profile's history.

### Worlds

- Lists every world profile under `/config/minecraft-worlds/` with on-disk size and an "Active?" marker.
- **Switch** sets `active_world` and restarts the add-on so the chosen world boots — one click, no second step.
- **Create** stages an empty profile (optional fixed seed); name must be 1–32 characters, `[A-Za-z0-9_-]`.
- **Import** (1.10.0+) accepts a Minecraft world `.zip` (up to 2 GB). The add-on finds the directory containing `level.dat` automatically (works whether it's at the root of the zip, one level deep, or in a re-zipped backup) and stages it as a new switchable world. Then *Switch* into it.
- **Delete** removes both the world directory and its backup history; refuses to delete the active profile (switch away first).

### Resource Packs

- Upload a Minecraft resource pack `.zip` (≤ 250 MB). The add-on stores it under `/config/resource-packs/` and serves it at `http://<your-HA-host>:8099/pack/<filename>` on the LAN.
- The table lists each pack's size, SHA-1, mtime, and serve URL.
- **Apply to active world** writes the URL + SHA-1 into the active world's `server.properties` `resource-pack` and `resource-pack-sha1` keys. Restart the server for clients to pick up the new pack.
- **Delete** removes the pack from disk; worlds referencing it fall back to no pack.

---

## 3. Home Assistant integration

The add-on deploys a companion integration to `/config/custom_components/bruh_minecraft/`. Home Assistant auto-discovers it via the Supervisor (`discovery: - bruh_minecraft` in `config.yaml`).

### Device & entities

All entities live under a single device **BRUH Minecraft Server**. Default entities:

| Platform | Key | Notes |
|----------|-----|-------|
| sensor | `players_online` | with `players` list in attributes |
| sensor | `players_max` | |
| sensor | `tps_1m` / `tps_5m` / `tps_15m` | Paper/Purpur only (reads `/tps`) |
| sensor | `latency_ms` | status ping latency |
| sensor | `uptime` | seconds since JVM started |
| sensor | `version` | with server-brand string in attributes |
| sensor | `server_type` / `motd` / `difficulty` / `gamemode` | |
| binary_sensor | `reachable` | Minecraft status ping succeeds |
| binary_sensor | `rcon_ok` | RCON handshake succeeds (disabled by default) |
| button | `backup_now`, `restart_server`, `stop_server`, `save_all` | |

### Services

| Service | Fields |
|---------|--------|
| `bruh_minecraft.rcon_command` | `command` |
| `bruh_minecraft.say` | `message` |
| `bruh_minecraft.give` | `player`, `item`, optional `amount` |
| `bruh_minecraft.set_weather` | `weather` (clear/rain/thunder) |
| `bruh_minecraft.set_time` | `time` (day/night/noon/midnight or ticks) |
| `bruh_minecraft.backup_now` | — |
| `bruh_minecraft.restart_server` | — |
| `bruh_minecraft.stop_server` | — |
| `bruh_minecraft.op_player` / `deop_player` / `kick_player` / `ban_player` / `whitelist_add` / `whitelist_remove` | `player` |

All services are routed through a file-based IPC bridge at `/config/.bruh_minecraft/`. HA Core drops a JSON request; the add-on watches that folder, handles the request via RCON, and writes a response file back.

### Example automations

**Nightly backup at 04:00:**

```yaml
automation:
  - alias: Minecraft - nightly backup
    trigger: { platform: time, at: "04:00:00" }
    action:
      service: bruh_minecraft.backup_now
```

**Kick everyone when it's bedtime:**

```yaml
automation:
  - alias: Minecraft - bedtime
    trigger:
      platform: numeric_state
      entity_id: sensor.bruh_minecraft_players_online
      above: 0
    condition:
      condition: time
      after: "22:30:00"
      before: "06:00:00"
    action:
      - service: bruh_minecraft.say
        data: { message: "Server going to sleep in 60s — save your work!" }
      - delay: "00:01:00"
      - service: bruh_minecraft.stop_server
```

---

## 4. File layout inside the container

```
/config/
├── minecraft  ->  minecraft-worlds/<active_world>/   # symlink to the active profile
├── minecraft-worlds/                                 # all world profiles live here
│   ├── default/                                      # auto-migrated from pre-1.3.0
│   │   ├── server.jar
│   │   ├── server.properties
│   │   ├── eula.txt
│   │   ├── world/ world_nether/ world_the_end/
│   │   └── plugins/
│   └── creative_flat/                                # another profile
│       └── …
├── minecraft-backups/
│   ├── <profile>/git/           # git repo (backup_use_git=true)
│   └── <profile>/archives/      # *.tar.gz (backup_use_git=false)
├── .bruh_minecraft/             # HA bridge shared dir
│   ├── stats.json state.json players.json
│   ├── requests/
│   └── responses/
└── custom_components/bruh_minecraft/   # auto-deployed companion integration

/data/
├── panel/                       # ingress panel state + logs
│   ├── console.log
│   ├── stats.json state.json players.json
│   ├── rcon.secret (0600)
│   └── *.pid *.log
└── server-cache/                # downloaded jars (content-addressed)
```

## 4.1 Complete service reference

Every HA service the integration exposes, with payload examples. Call from **Developer Tools → Actions** or from an automation.

```yaml
# Broadcast a message to everyone online.
action: bruh_minecraft.say
data:
  message: "Dinner's ready — server going down in 2 minutes."

# Send any Minecraft command over RCON (response comes back in the UI).
action: bruh_minecraft.rcon_command
data:
  command: "weather clear"

# Give an item. Player must be online.
action: bruh_minecraft.give
data:
  player: "Alice"
  item: "minecraft:diamond_pickaxe"
  amount: 1

# Weather: clear / rain / thunder.
action: bruh_minecraft.set_weather
data:
  weather: "clear"

# Time: shortcuts or absolute ticks.
action: bruh_minecraft.set_time
data:
  time: "day"  # or "night", "noon", "midnight", or a number e.g. "12000"

# Take a backup right now (git or archive, per your config).
action: bruh_minecraft.backup_now

# Graceful save + restart. The add-on re-launches the JVM automatically
# unless you also call stop_server.
action: bruh_minecraft.restart_server

# Graceful save + stop. Sets no_restart so the add-on stays at "stopped"
# until you start it again from the UI or call another lifecycle service.
action: bruh_minecraft.stop_server

# Player management (all take `player: "<name>"`):
# bruh_minecraft.op_player, deop_player, kick_player, ban_player,
# whitelist_add, whitelist_remove.
```

## 4.2 More automation examples

**Low-TPS alert** — if the TPS drops below 15 for a minute, notify the admin.

```yaml
automation:
  - alias: Minecraft - lag alert
    trigger:
      - platform: numeric_state
        entity_id: sensor.bruh_minecraft_tps_1m
        below: 15
        for: "00:01:00"
    action:
      - service: notify.mobile_app_pixel
        data:
          title: "Minecraft server lagging"
          message: "TPS 1m is {{ states('sensor.bruh_minecraft_tps_1m') }}"
```

**Auto-stop when idle for 30 min** — saves CPU when the kids are off the server.

```yaml
automation:
  - alias: Minecraft - auto-stop on idle
    trigger:
      - platform: numeric_state
        entity_id: sensor.bruh_minecraft_players_online
        below: 1
        for: "00:30:00"
    action:
      - service: bruh_minecraft.stop_server
```

**Snap a backup right before any destructive command** — use the `rcon_command` service plus the `backup_now` service in sequence.

```yaml
script:
  minecraft_safe_fill:
    sequence:
      - service: bruh_minecraft.backup_now
      - delay: "00:00:05"
      - service: bruh_minecraft.rcon_command
        data:
          command: "fill ~-10 ~ ~-10 ~10 ~ ~10 minecraft:stone"
```

**Assist voice control** — the BRUH Claude Terminal add-on pairs with this to let you say "tell everyone dinner's ready" and have it hit the `say` service. See the Claude Terminal docs for setup; no config change needed on the Minecraft side.

## 4.3 Security considerations

- **RCON is loopback-only** (bound to `127.0.0.1:25575`) with a 32-character random password stored at `/data/panel/rcon.secret` (mode 0600). It's never exposed to the LAN.
- **Ingress auth** — the panel inherits whatever authentication your Home Assistant instance uses; there's no separate login.
- **Offline mode on the internet is dangerous.** If you forward port 25565 publicly with `online-mode: false`, anyone who guesses a username can join as that player — including OPs. Keep offline mode LAN-only, or put the server behind a Velocity/Waterfall proxy that handles auth.
- **Plugin URLs run with full server permissions.** Only add URLs you trust from the `plugins:` option. 1.2.5+ verifies downloads start with the ZIP magic bytes so a rate-limit HTML page can't be saved as a jar, but a malicious signed jar can still compromise the server.
- **World backups live under `/config/minecraft-backups/`** (bind-mounted to your HA host). Git mode keeps a full history with commits; copy the whole dir off-host for true disaster recovery.

## 5. Troubleshooting

### `EULA not accepted yet` in the startup log

The add-on is idling on purpose — open the sidebar **Minecraft** panel and the first-run wizard prompts you to accept the EULA + pick your server type. Alternatively, set `eula: true` in the add-on **Configuration** tab.

### `address already in use: bind: 0.0.0.0:25565`

Something else (another server or a duplicate copy of this add-on) is already listening on the Minecraft port. Stop that process or change `25565/tcp` in the Network tab.

### The panel says "Online" but players can't connect from the internet

Port forwarding is your router's job, not Home Assistant's. Forward `25565/tcp` and `25565/udp` from your public IP to your HA host.

### TPS sensors stay unavailable

TPS is reported by Paper/Purpur/Folia's `/tps` command. If you run `vanilla`/`fabric`/`forge`, the sensor will stay null.

### Backups are slow

If your world is huge, switch to tar-archive mode (`backup_use_git: false`) which is cheaper on CPU but larger on disk. Git mode is best for small-to-medium worlds that change slowly.

### Restore did not restart the server

After a restore, the panel sends `stop` via RCON. If `auto_restart_on_crash` is `false`, the add-on won't restart the JVM — toggle the option back on (the default) or hit the add-on's **Start** button.

### Add-on exits immediately after "Installing configured plugins"

Before 1.2.5 this was a hard crash caused by a single bad plugin URL killing `run.sh` through `set -e`. As of 1.2.5, per-plugin failures are isolated, logged, and counted:

```
[INFO]: Plugin: NickNamer.jar -> https://.../NickNamer.jar
[WARNING]: Plugin install failed for https://.../NickNamer.jar — continuing
[WARNING]: 1 plugin(s) failed; see logs above. Server will start anyway.
```

If you see a failure:

- **Check the `[install-plugin]` line** — the HTTP status / curl exit code tells you whether the URL 404'd, timed out, or served HTML instead of a jar. `--max-time 60` caps each attempt.
- **GitHub `/releases/latest/download/X.jar` URLs only work if an asset is named *exactly* `X.jar`** — many projects version their filenames (`NickNamer-5.15.0.jar`), in which case the `latest/download/` shortcut 404s. Use a pinned versioned URL or the project's own mirror.
- **Rate-limit HTML pages (GitHub anonymous limits) are rejected** — a jar must start with `PK`. The add-on refuses to install a ~10 KB HTML blob masquerading as a jar.

Even on total failure the Minecraft server will launch without the plugin, so you can fix the URL and restart.

### iOS Bedrock hangs on "Connecting multiplayer server…"

Checklist in order of likelihood:

1. **MTU.** Set `geyser_mtu: 1200` in the add-on options and restart — the default 1400 gets fragmented by many home Wi-Fi routers mid-handshake.
2. **Ghost session from a previous hang.** If you get *"You are already connected to this server!"* on the retry, the add-on's auto-kicker should clear it within a second (enabled by default via `auto_kick_ghost_sessions`). Manual fallback: open the panel → Players tab → type the name → action `Kick`. Or type `kick <name>` in the Console tab.
3. **Connection-throttle.** If the iOS client retries rapidly and gets *"Slow down, you're connecting too fast!"*, drop `connection-throttle` to `0` (LAN-safe) on the world via the panel's Server Properties tab. It's 4000 ms by default.
4. **Apple Family Sharing / shared Xbox account.** Two iOS devices signed into the same Microsoft account share a gamertag and the server will only accept one at a time. Give each device its own Microsoft/child account or sign out of Xbox on the second device and set a distinct offline username in Minecraft → Settings → Profile.
5. **Resource-pack URL.** An unreachable `resource_pack` URL makes iOS hang silently. Clear `resource_pack` / `resource_pack_sha1` or set `require_resource_pack: false`.

### `signal only works in main thread of the main interpreter`

Fixed in **1.2.0**. The old RCON client (`mcrcon`) used `signal.SIGALRM` for its timeout, which can't be set from worker threads — so the ingress panel's command bar crashed with this message. The add-on now ships a thread-safe RCON implementation (`scripts/rcon_client.py`) and no longer depends on `mcrcon`.

### Out-of-memory crashes

Increase `memory_mb`. Typical sizing:
- 4 players, vanilla world: 2048 MB
- 10 players, some plugins: 4096 MB
- 20+ players, heavy plugin pack: 6144–8192 MB
