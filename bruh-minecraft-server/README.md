# BRUH Minecraft Server

A rock-solid Minecraft **Java Edition** server add-on for Home Assistant with a full ingress management panel, git-based world version control, RCON, multi-server-type support, plugin management, and a first-class HA integration (sensors, buttons, services).

![Supported architectures](https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-blue)
![Java](https://img.shields.io/badge/Java-21-orange)
![Status](https://img.shields.io/badge/status-stable-brightgreen)

## Features

- **Cross-play with Bedrock (iOS, Android, Xbox, Switch, PS, Win10/11).** `enable_bedrock_support: true` is on by default and auto-installs Geyser + Floodgate so iPhone / iPad / console players can join the same world on UDP:19132 — no extra setup. `host_network: true` means the server shows up automatically in Minecraft's **Friends** tab on any device on the same LAN (no manual IP entry needed).
- **Latest Minecraft, any flavour.** Pick Paper, Purpur, Folia, Vanilla, Fabric, or Forge — the add-on resolves `LATEST`/`SNAPSHOT`/specific versions against upstream APIs on every boot and caches jars to `/data/server-cache`.
- **Offline-mode / no-Xbox play done right.** Flip `online_mode: false` and the add-on silently fixes every downstream setting (`enforce_secure_profile`, Geyser `auth-type`, Floodgate removal, `validate-bedrock-login`) so LAN / family / kids-without-Xbox setups just work.
- **Cheats + OPs in one click.** `allow_cheats: true` enables `/gamemode`, `/give`, `/tp`, `/summon`, `/fill`; `initial_ops` auto-OPs usernames on startup over RCON (works in both online and offline auth).
- **Mobile-friendly panel.** Fully responsive layout with horizontal-scroll tab row, stacked forms, 44 px touch targets, and iOS-zoom-proof input fields — the HA Companion app experience matches desktop.
- **Ingress management panel.** Dashboard, live console with colour-coded log levels, RCON command input, chat broadcast, player management, editable `server.properties`, plugin installer, and a full backup/restore browser — all inside Home Assistant's sidebar.
- **Git-based world version control.** Every world snapshot is committed to a git repo at `/config/minecraft-backups/git`; restore any previous snapshot from the UI or service. (tar.gz archive mode is also available.)
- **Deep HA integration.** Auto-discovered `bruh_minecraft` integration adds:
    - sensors — online players, TPS (1m/5m/15m), latency, uptime, version, MOTD, difficulty…
    - binary sensors — server online, RCON reachable
    - buttons — Backup, Restart, Stop, Save
    - services — `bruh_minecraft.rcon_command`, `say`, `give`, `set_weather`, `set_time`, `backup_now`, `restart_server`, `stop_server`, `op_player`, `kick_player`, `ban_player`, `whitelist_add`, `whitelist_remove`
- **Aikar-style JVM tuning by default** for the best TPS on Paper/Purpur/Folia.
- **Crash auto-restart** with rate limiting (5 restarts per 5 minutes before bailing).
- **Plugin management.** Drop plugin jars in the UI or declare them in the add-on config (`plugins` list) — they're fetched with `If-Modified-Since` to avoid unnecessary re-downloads.
- **Graceful shutdown.** `save-all flush` + RCON `stop`, then a 60s grace period before SIGTERM.
- **Works offline too.** Once a jar is cached, subsequent starts don't need internet.
- **Rock-solid safety.** JVM runs as an unprivileged user (UID 1000), RCON is bound to 127.0.0.1 only and auto-generates a random password, and the EULA must be explicitly accepted before the server will start.

## Quick start

1. Add the **BRUH HA Apps** repository:
   ```
   https://github.com/bruhautomation/BRUH-HA-Apps
   ```
2. Install the **BRUH Minecraft Server** add-on.
3. Open the **Configuration** tab and set `eula: true` (you must accept https://www.minecraft.net/eula).
4. (Optional) change `server_type`, `minecraft_version`, `memory_mb`, and any gameplay options.
5. Start the add-on. Open the sidebar **Minecraft** panel once it's running.
6. When prompted by HA, finish setup of the auto-discovered **BRUH Minecraft** integration.

## Ports

| Port                | Purpose                                       |
|---------------------|-----------------------------------------------|
| 25565/tcp+udp       | Minecraft Java Edition clients                |
| 19132/udp           | Minecraft Bedrock / Geyser (if you add it)    |
| 24454/udp           | Simple Voice Chat (optional plugin)           |
| 8099/tcp (internal) | Ingress panel (proxied by Home Assistant)     |
| 25575/tcp (loopback)| RCON — bound to 127.0.0.1 only                |

## Configuration highlights

See [DOCS.md](DOCS.md) for the complete reference.

```yaml
eula: true
server_type: paper          # paper | purpur | folia | vanilla | fabric | forge
minecraft_version: LATEST   # LATEST | SNAPSHOT | "1.21.3"
memory_mb: 4096
use_aikar_flags: true
auto_update_server: true
auto_backup: true
backup_interval_minutes: 60
backup_use_git: true
plugins:
  - url: https://example.com/plugins/ViaVersion.jar
  - url: https://example.com/plugins/Geyser-Spigot.jar
    name: Geyser.jar
```

## Where your data lives

- **Worlds / server files:** `/config/minecraft/`
- **Backups (git + archives):** `/config/minecraft-backups/`
- **Cached server jars:** `/data/server-cache/`
- **Panel state (logs, stats):** `/data/panel/`
- **HA bridge requests:** `/config/.bruh_minecraft/`

## License

MIT — see [LICENSE](../LICENSE).

## Support

Issues and feature requests: https://github.com/bruhautomation/BRUH-HA-Apps/issues
