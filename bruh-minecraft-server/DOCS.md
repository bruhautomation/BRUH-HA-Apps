# BRUH Minecraft Server — Documentation

Complete configuration reference, operational notes, and integration details.

---

## 0. Feature overview (what this add-on does)

A bird's-eye view so you can skim to the sections that matter to you:

- **Rock-solid Paper / Purpur / Folia / Vanilla / Fabric / Forge** server jar management. `LATEST`, `SNAPSHOT`, or any pinned version; auto-resolves, caches to `/data/server-cache`, re-downloads only when upstream changes.
- **Aikar-flagged Java 21 JVM** with configurable memory, extra JVM args, and crash auto-restart (rate-limited so a fatal misconfig can't runaway-restart).
- **Ingress-only panel** at the add-on's sidebar entry with:
  - Live dashboard (status dot, version, uptime, TPS, latency, players).
  - Streaming console over SSE with INFO/WARN/ERROR colouring, clear button, autoscroll toggle, and a command input (no leading slash needed).
  - Players tab with one-click op/deop/kick/ban/pardon/whitelist.
  - Server properties editor for the UI-safe subset of keys; changes apply over RCON where Paper supports it.
  - Plugins tab with install-by-URL, size/mtime listing, one-click delete.
  - Backups tab browsing both git snapshots and tar.gz archives with per-entry restore.
  - Backup / Update / Restart / Stop buttons on every page.
- **Bedrock cross-play** via Geyser (+ Floodgate when applicable). Auto-installed, auto-configured for your auth-type choice, and MTU/auth-type/validate-bedrock-login patched on every boot so iOS, Android, Switch, Xbox, PS and Windows 10/11 can connect.
- **Offline mode done right.** Flip `online_mode: false` and the add-on silently forces `enforce-secure-profile: false`, switches Geyser to `auth-type: offline`, uninstalls Floodgate, and sets `validate-bedrock-login: false` — the full chain of changes Microsoft/Mojang's and GeyserMC's defaults gate behind one flag.
- **Cheats made easy.** `allow_cheats: true` guarantees `/gamemode`, `/give`, `/tp`, `/summon`, `/fill` work for OP'd players; `initial_ops` auto-OPs listed usernames via RCON on startup (works in both online and offline auth).
- **World safety.** Incremental git-backed world snapshots or tar.gz archive backups, on a configurable schedule, with one-click restore from either format.
- **Home Assistant integration** with 12 sensors, 2 binary sensors, 4 buttons, 13 services, a `notify.bruh_minecraft_broadcast` platform, and a Supervisor-registered discovery tile for one-click setup.
- **Self-healing.** Ghost-session auto-kicker clears stuck Bedrock handshakes; RCON client is thread-safe (fixes the `signal only works in main thread` panel crash); bad plugin URLs log a warning instead of tanking startup.
- **Zero-dependency architecture.** Everything runs inside the one add-on container — no separate proxy jars, no VPS, no external broker.

Version 1.2.6 at time of writing; see CHANGELOG.md for the full evolution.

---

## 0.1 Quick start

1. Install the add-on from the BRUH repository in Home Assistant.
2. **Set `eula: true`** in the **Configuration** tab. The add-on will refuse to start otherwise — that's the Minecraft EULA acknowledgement, required by Mojang.
3. (Optional) For kids / LAN / no-Microsoft-account play: set `online_mode: false`. Everything Bedrock + Java needs will auto-adjust.
4. (Optional) Add usernames to `initial_ops` so you're OP'd the first time you join.
5. Start the add-on. Give it ~30 s for the jar to download and Paper to boot, then open the **Minecraft** entry in HA's sidebar — the panel's dashboard tells you when the server is online.
6. Connect to `<your-HA-host>:25565` from Java Edition, or `<your-HA-host>:19132` from Bedrock (UDP, same subnet gets automatic LAN discovery in the Bedrock **Friends** tab).

The rest of this document is optional reading — the defaults are sensible.

---

## 0.2 Switchable server profiles (multi-world)

Since 1.3.0 the add-on can host multiple independent servers and flip between them with one option change. Each **world profile** is a full server root — its own world files, `server.properties`, plugins, and backup history — living at `/config/minecraft-worlds/<name>/`. Only one is active at a time.

Why you might want this:

- A creative-mode sandbox world for kids, plus a survival world for the adults, without any world-file mixing.
- Seasonal events (a "Halloween" profile, a "Summer vanilla" profile).
- A throwaway test server for trying new plugin combos without risking the main save.

How to switch:

- **Panel → Worlds tab** (recommended). Shows every profile, its on-disk size, the active one, and a "Switch" button. The panel writes `active_world` to your add-on options via the Supervisor API, then you click **Restart** in the header to boot into the new world.
- **Add-on Configuration tab.** Set `active_world: <name>` and restart — same effect.
- **CLI.** From the terminal: `world-manager.sh list | create <name> [seed] | switch <name> | delete <name> | active`. Profile names are 1–32 characters, letters/digits/underscore/dash only.

### What's per-world vs shared (important!)

When you switch worlds, these things **travel with the world profile** — each profile has its own copy:

| Per-world | Notes |
|-----------|-------|
| World save files (`world/`, `world_nether/`, `world_the_end/`) | The actual terrain & player data. |
| `server.properties` | Rendered from add-on options on boot; any hand-edits to **non-managed** keys survive (see **Settings precedence** (below)). |
| `plugins/` folder on disk | Jars live under each profile's `plugins/`. |
| Backup history | `/config/minecraft-backups/<profile>/` — the Backups tab only shows the active profile's snapshots. |
| `ops.json`, `whitelist.json`, `banned-players.json` | Each profile has its own op / whitelist / ban list. |

These things **are shared across all profiles** — change them once and every profile sees it:

| Shared | Why |
|--------|-----|
| All **add-on options** (`difficulty`, `gamemode`, `memory_mb`, `motd`, `level_name`, `level_seed`, `online_mode`, …) | They live in the add-on's Configuration tab, not in any profile. |
| `plugins:` list in the add-on options | Jars get copied into the **active** profile's `plugins/` on boot. Switch worlds and the new profile's `plugins/` is populated from the same URL list. |
| RCON password | Single secret per install, stored at `/data/panel/rcon.secret`. |
| Geyser / Floodgate configuration | Regenerated per profile on boot, but from the same add-on options. |

**Implication:** managed settings (`difficulty`, `gamemode`, `level_name`, etc.) are **shared across all worlds** — they live in the add-on options, not in any one profile. You can't currently set `difficulty: peaceful` for one world and `difficulty: hard` for another; switch the shared option when you switch worlds. (Per-world managed settings aren't supported because the add-on re-renders those keys from the options on every boot.)

### Switching — how it works (one click, since 1.2.9)

Panel → **Worlds** tab → click **Switch** on the profile you want. The panel:

1. Writes `active_world: <name>` into your add-on options via the Supervisor API.
2. Immediately triggers a full add-on restart (`POST /addons/self/restart`). The container goes down, `main()` in `run.sh` runs again on startup, `ensure_worlds_layout` re-points the `/config/minecraft` symlink at the new profile, and the server boots with that profile's world / plugins / ops.

The panel is unreachable for ~30 s while the container restarts — refresh after that. If the Supervisor refuses the restart call (rare; only if the add-on was granted reduced permissions), the panel surfaces the exact failure and you can click **Restart** on the HA add-on page manually.

**Why not use the header's Restart button?** That button only RCON-stops the JVM, which `run_server_loop` then relaunches inside the same container. `ensure_worlds_layout` does NOT re-run, so the symlink stays pointed at the old profile. JVM-only restart is faster (~15 s vs ~30 s) and is the right tool for config-tab changes to server-properties keys, but it can't switch worlds.

### Notes

- The legacy `/config/minecraft/` path is migrated to the `default` profile on first boot of 1.3.0, so existing installs keep their world unchanged.
- `delete` refuses to remove the currently-active profile. Switch away first.
- `level_name: <name>` in add-on options is the **level folder name inside the profile directory**. It's shared across profiles, so every profile will look for a subfolder with that name. If you rename `level_name`, existing worlds won't auto-rename their folder — they'll be regenerated from scratch (the old `world/` stays on disk but isn't loaded).

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

Every option can be set from the add-on's **Configuration** tab. All options are validated against the schema in `config.yaml`; invalid values will be rejected by the Supervisor before the add-on starts.

> **Which surface do I change a setting on?** Either works for editable keys — since 1.7.0 the panel's Server-Properties tab writes back to the add-on Configuration options, so panel edits persist across restarts too. Read **Settings precedence** (below) for the full picture.

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

### Gameplay

| Option | Type | Default |
|--------|------|---------|
| `motd` | string | `A BRUH Minecraft Server` |
| `difficulty` | `peaceful \| easy \| normal \| hard` | `normal` |
| `gamemode` | `survival \| creative \| adventure \| spectator` | `survival` |
| `force_gamemode` | bool | `true` | Put every player back into `gamemode` on each join. Default `true` so the configured gamemode is authoritative (this is the fix for "I set creative but it keeps loading survival"). Set `false` to let players keep whatever mode they last switched to. |
| `max_players` | 1–1000 | `20` |
| `view_distance` | 3–32 | `10` |
| `simulation_distance` | 3–32 | `10` |
| `online_mode` | bool | `true` | Validate every login against Microsoft/Mojang. Turn **off** for cracked/offline play (e.g. kids without an Xbox account, LAN-only sessions). |
| `enforce_secure_profile` | bool | `false` | Require Mojang-signed chat profiles (MC 1.19+). Auto-forced to `false` whenever `online_mode` is off so offline clients aren't kicked with "You are not permitted to join due to the enforce-secure-profile setting." |
| `pvp` | bool | `true` |
| `hardcore` | bool | `false` |
| `allow_flight` | bool | `false` |
| `white_list` | bool | `false` |
| `spawn_protection` | 0–10000 | `16` |
| `level_name` | string | `world` |
| `level_seed` | string | `""` (random) |
| `level_type` | string | `minecraft:normal` |
| `initial_enabled_packs` | string | `vanilla` | Comma-separated experimental feature packs to enable at world creation (e.g. `vanilla,minecart_improvements,redstone_experiments`). This is how you turn on **experiments** and the newest experimental **game rules**. Always keep `vanilla` in the list. See note below. |
| `initial_disabled_packs` | string | `""` | Comma-separated feature packs to force-disable at world creation. Usually left blank. |
| `allow_nether` | bool | `true` |
| `generate_structures` | bool | `true` |
| `spawn_monsters` / `spawn_animals` / `spawn_npcs` | bool | `true` |
| `prevent_proxy_connections` | bool | `false` |
| `hide_online_players` | bool | `false` |
| `resource_pack` | URL | `""` |
| `resource_pack_sha1` | string | `""` |
| `require_resource_pack` | bool | `false` |
| `max_world_size` | 1–29999984 | `29999984` |
| `network_compression_threshold` | `-1`–65536 | `256` |
| `entity_broadcast_range_percentage` | 10–1000 | `100` |
| `enable_command_block` | bool | `false` |
| `op_permission_level` | 1–4 | `4` |
| `allow_cheats` | bool | `false` | One-click enables the "cheat" commands (`/gamemode`, `/give`, `/tp`, `/summon`, `/fill`, …). Forces `enable-command-block=true` and ensures `op_permission_level` is at least 2. Players still need to be OP'd to use the commands — add names to `initial_ops` or OP them from the panel's **Players** tab. |
| `initial_ops` | list of player names | `[]` | Auto-OP these names at boot via RCON (handles UUID lookup in both online and offline mode). |

> **Heads-up:** changing `level_name` or `level_seed` only takes effect when a fresh world is being generated. To reset a world, move the world directory aside under `/config/minecraft/` and restart.

> **Enabling experiments:** Mojang gates experimental content — and the newest experimental game rules that ship with it — behind named *feature packs*. Add them to `initial_enabled_packs` (comma-separated, keep `vanilla`). The exact pack names change with each Minecraft version; recent examples are `minecart_improvements`, `redstone_experiments`, and `trade_rebalance` on 1.21.x. Because experiments are baked into a world at **creation** time, turning one on only affects **newly generated** worlds — existing worlds keep whatever packs they were created with. To use an experiment on an existing save, create a fresh world from the **Worlds** tab with the pack enabled.

#### "Please log into Xbox to join this server" / "You are not permitted to join…"

If you — or your kids — want to play **without an Xbox/Microsoft sign-in** on either Java **or** Bedrock:

1. Set `online_mode: false` in the add-on Configuration tab.
2. Leave `enforce_secure_profile: false` (the default; auto-forced off whenever `online_mode` is `false`).
3. Leave `geyser_auth_type: auto` (the default; resolves to `offline` automatically whenever `online_mode` is `false`).
4. Restart the add-on. Any Java username now connects, and Bedrock clients join under whatever username is set on their device — **no Xbox sign-in required**.

Two important subtleties with Geyser:

- `geyser_auth_type: floodgate` **still requires the Bedrock client to be signed in to Xbox Live** (Floodgate uses the XUID to identify the player). It's the right default for public-facing servers, but it's not "no login needed."
- `geyser_auth_type: offline` removes the Xbox requirement entirely. Bedrock usernames are taken verbatim from the player's device, and Floodgate's `.`-prefix no longer applies. This is the correct setting for LAN-only / family servers. Two things the add-on does under the hood for this mode:
    1. **Uninstalls Floodgate** (Geyser delegates auth to it whenever the jar is present, and Floodgate requires a valid Xbox XUID).
    2. **Sets `advanced.bedrock.validate-bedrock-login: false`** in Geyser's config — this is the toggle that actually suppresses Geyser's pre-auth signed-chain check. Without it, Geyser kicks every Bedrock client whose login JWT isn't signed by Mojang's Xbox Live root key, which includes every LAN-only device and every client that isn't currently signed in to Xbox.

Offline mode is **not safe for public/internet-exposed servers** — anyone can spoof any username. Use it only on LAN or when you fully trust the player pool.

#### Cheats / creative commands

Toggle `allow_cheats: true` to guarantee the "cheat" commands work, then OP the player who wants them:

- Drop their Minecraft username into `initial_ops` (the add-on OPs them on startup — no need to wait for a manual `/op`), **or**
- Go to the panel's **Players** tab after you've joined once and click **op**.

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
| `connection_throttle_ms` | 0–60000 | `4000` | Paper's per-IP connection-throttle in milliseconds. `0` disables it, which avoids the "Slow down, you're connecting too fast!" kick on rapid iOS retries. Safe on LAN; keep the default on public servers to slow down connection-flood attacks. |
| `player_idle_timeout_minutes` | 0–1440 | `0` | Auto-kick a player after this many idle minutes. `0` disables. Low values (e.g. `5`) help clean up ghost sessions quickly in addition to `auto_kick_ghost_sessions`. |

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

This is the single-most-confusing thing about the add-on, so here's the exact rule:

1. **Add-on Configuration tab = source of truth.** On every add-on boot, `setup-server-properties.sh` renders `server.properties` from your add-on options. Any **managed key** (MOTD, difficulty, gamemode, max-players, view-distance, pvp, whitelist, etc. — see `scripts/setup-server-properties.sh` for the complete list) is rendered from the options.
2. **Panel → Server Properties tab also writes the options (since 1.7.0).** Editing an editable key in the panel writes the value **back to the add-on Configuration options** via the Supervisor API *and* applies it live via RCON where possible. So a panel edit takes effect immediately **and persists across restarts** — the panel and the Configuration tab can no longer disagree. (Before 1.7.0 the panel only wrote `server.properties`, which step 1 reverted on the next restart — that's the "my panel changes don't stick" bug, now fixed.) Keys that can't be applied live (e.g. `view-distance`, `level-seed`) take effect on the next restart.
3. **Non-managed keys are preserved.** Any key you add to `server.properties` that isn't in the managed set (exotic Paper-only keys, plugin-specific settings, etc.) survives across restarts. The panel also preserves them.
4. **`initial_ops` vs the panel Players tab.** `initial_ops` runs once per boot via RCON. Using the Players tab to op/deop someone applies immediately and persists in `ops.json` — the next restart doesn't un-op them (ops.json is not rewritten from add-on options).
5. **Plugin list (`plugins:`) vs the panel Plugins tab.** The add-on downloads every URL in `plugins:` on boot (with `If-Modified-Since`, so it's cheap). Deleting a plugin from the panel removes the jar from disk, but if the URL is still in `plugins:`, the add-on re-downloads it on next restart. Want it gone? Remove the entry from `plugins:` AND delete the jar.

**Rule of thumb:** editable keys can be changed from either the Configuration tab or the panel's Server Properties tab — both persist now. Use the Configuration tab for keys the panel marks read-only.

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
- Performance metrics: TPS, latency.
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

- Shows all resolved `server.properties` keys.
- Keys marked **editable** (MOTD, difficulty, gamemode, PVP, whitelist, etc.) can be changed from the panel; the change is written **back to the add-on Configuration options** (so it persists across restarts) and applied live via RCON where possible.
- Non-editable keys are rendered read-only — change them via the add-on **Configuration** tab.
- **Build mode / Survival mode** buttons: one-click presets. *Build mode* flips the world to creative + flight + command blocks for free building (the practical stand-in for an editor, which Java Edition doesn't have); *Survival mode* flips back. Both persist like any other setting.

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
- **Switch** button writes `active_world` to the add-on options via the Supervisor API — then hit **Restart** in the header to boot into it.
- **Create** form stages an empty profile (optional fixed seed); name must be 1–32 characters, `[A-Za-z0-9_-]`.
- **Delete** removes both the world directory and its backup history; refuses to delete the active profile (switch away first).

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
- **Offline mode on the internet is dangerous.** If you forward port 25565 publicly with `online_mode: false`, anyone who guesses a username can join as that player — including OPs. Keep offline mode LAN-only, or put the server behind a Velocity/Waterfall proxy that handles auth.
- **Plugin URLs run with full server permissions.** Only add URLs you trust from the `plugins:` option. 1.2.5+ verifies downloads start with the ZIP magic bytes so a rate-limit HTML page can't be saved as a jar, but a malicious signed jar can still compromise the server.
- **World backups live under `/config/minecraft-backups/`** (bind-mounted to your HA host). Git mode keeps a full history with commits; copy the whole dir off-host for true disaster recovery.

## 5. Troubleshooting

### `fatal: The Minecraft EULA has NOT been accepted`

Set `eula: true` in the add-on configuration. That is the one and only way to start the server.

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
3. **Connection-throttle.** If the iOS client retries rapidly and gets *"Slow down, you're connecting too fast!"*, drop `connection_throttle_ms` to `0` (LAN-safe). It's 4000 ms by default.
4. **Apple Family Sharing / shared Xbox account.** Two iOS devices signed into the same Microsoft account share a gamertag and the server will only accept one at a time. Give each device its own Microsoft/child account or sign out of Xbox on the second device and set a distinct offline username in Minecraft → Settings → Profile.
5. **Resource-pack URL.** An unreachable `resource_pack` URL makes iOS hang silently. Clear `resource_pack` / `resource_pack_sha1` or set `require_resource_pack: false`.

### `signal only works in main thread of the main interpreter`

Fixed in **1.2.0**. The old RCON client (`mcrcon`) used `signal.SIGALRM` for its timeout, which can't be set from worker threads — so the ingress panel's command bar crashed with this message. The add-on now ships a thread-safe RCON implementation (`scripts/rcon_client.py`) and no longer depends on `mcrcon`.

### Out-of-memory crashes

Increase `memory_mb`. Typical sizing:
- 4 players, vanilla world: 2048 MB
- 10 players, some plugins: 4096 MB
- 20+ players, heavy plugin pack: 6144–8192 MB
