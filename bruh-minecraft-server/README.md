<h1 align="center">BRUH Minecraft Server</h1>

<p align="center">
  A complete Minecraft server add-on for Home Assistant — ingress panel,
  cross-play, per-world settings, git backups, deep HA integration.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-blue" alt="Architectures" />
  <img src="https://img.shields.io/badge/Java-25-orange" alt="Java 25" />
  <img src="https://img.shields.io/badge/status-stable-brightgreen" alt="Status" />
  <img src="https://img.shields.io/badge/Bedrock-cross--play-9cf" alt="Bedrock cross-play" />
</p>

> 📖 **Full reference** — [DOCS.md](DOCS.md)  ·  **Plugin commands** — [PLUGINS.md](PLUGINS.md)  ·  **Changelog** — [CHANGELOG.md](CHANGELOG.md)

---

## Why this add-on

| You want… | This add-on gives you… |
|-----------|-----------------------|
| **A Paper server in one click** | Auto-resolves the latest stable build, caches the jar, applies Aikar's JVM flags. |
| **Bedrock kids on the same world** | Geyser + Floodgate auto-installed; LAN discovery via host networking. |
| **Multiple independent worlds** | Per-world `server.properties`; one click switches active world. |
| **Backups you can actually trust** | Incremental git snapshots every hour, restore any commit from the UI. |
| **No "I broke it" terror** | Crash auto-restart (rate-limited), graceful saves on shutdown, one-shot in-UI rollback. |
| **It just works on Home Assistant** | Native ingress panel + auto-discovered HA integration with sensors and services. |

---

## Quick start

1. **Add the repository** in Home Assistant → **Settings → Add-ons → ⋮ → Repositories**:
   ```
   https://github.com/bruhautomation/BRUH-HA-Apps
   ```
2. Install **BRUH Minecraft Server** and **Start** it.
3. Open the sidebar **Minecraft** entry. The **Welcome wizard** walks you through the EULA, online/offline mode, and server type. Click *Start the server* — that's it.

> The wizard is the only setup step. After it finishes the server boots and the panel takes over.

---

## What you get

### 🎮 Cross-play out of the box
Bedrock clients (iOS, Android, Xbox, Switch, PlayStation, Win10/11) join the
same world as Java players. Geyser + Floodgate install automatically, with
sensible auth defaults that match your world's `online-mode`. Devices on the
LAN auto-discover the server in Minecraft's **Friends** tab — no IP entry.

### 🌍 Independent worlds
Every world has its own `server.properties`. A creative sandbox and a hard
survival can coexist; switching loads each world's own gamemode, difficulty,
world-gen, whitelist, view distance, and so on. The **Worlds** tab handles
create / switch / delete / **import-from-zip** in one click.

### 🛠️ A real management panel
The ingress panel is the heart of it:

- **Dashboard** — live status, TPS, player list, latency, *Tune for my hardware* recommender, health badge (`● healthy / degraded / struggling`).
- **Console** — live JVM log with colour-coded levels and a command input.
- **Players** — op/deop/kick/ban/whitelist by click.
- **Server Properties** — every editable per-world key; difficulty, gamemode, and whitelist apply live via RCON.
- **Plugins** — one-click curated installers (EssentialsX, LuckPerms, WorldEdit, CoreProtect, …) + URL installer + duplicate quarantine.
- **Backups** — browse git snapshots and tar archives; restore by SHA.
- **Worlds** — switch / create / **import** worlds.
- **Resource Packs** — drop a `.zip`, get a URL + SHA-1, *Apply* writes them into the active world for you.

### 🔌 Home Assistant integration
An auto-discovered `bruh_minecraft` integration ships sensors and services:

| Surface | What you get |
|---------|--------------|
| **Sensors** | online players, max players, TPS (1m/5m/15m), latency, uptime, version, MOTD, difficulty, gamemode, server type |
| **Binary sensors** | server online, RCON reachable |
| **Buttons** | Backup, Restart, Stop, Save |
| **Services** | `rcon_command`, `say`, `give`, `set_weather`, `set_time`, `backup_now`, `restart_server`, `stop_server`, `op_player`, `deop_player`, `kick_player`, `ban_player`, `pardon_player`, `whitelist_add`, `whitelist_remove` |

### ♻️ Safety & operations
- Crash auto-restart with rate limiting (5 restarts per 5 minutes before bailing).
- Graceful shutdown — `save-all flush` + RCON `stop` + 60s grace before SIGTERM.
- JVM runs as a dedicated unprivileged user (UID 1000).
- RCON is bound to `127.0.0.1` only; password auto-generated, mode 0600.
- Works offline: once a jar is cached, restarts don't need internet.
- The duplicate-plugin quarantine catches stale jars on boot before Paper complains.

---

## Ports

| Port | Direction | What |
|------|-----------|------|
| `25565/tcp + udp` | inbound | Minecraft Java Edition clients |
| `19132/udp` | inbound | Minecraft Bedrock / Geyser |
| `24454/udp` | inbound | Simple Voice Chat (optional plugin) |
| `8099/tcp` | inbound (LAN) | Ingress panel + hosted resource packs |
| `25575/tcp` | loopback | RCON (panel + HA integration only) |

The add-on uses `host_network: true` so Bedrock LAN discovery works.

---

## Where things live

```
/config/
├── minecraft           → symlink to the active world
├── minecraft-worlds/   ← each world's full server root
│   ├── default/
│   │   ├── world/                       Save files
│   │   ├── server.properties            Per-world gameplay settings
│   │   ├── plugins/                     Plugin jars
│   │   └── ops.json, whitelist.json, …
│   ├── creative/                        A second world; switch in the Worlds tab
│   └── …
├── minecraft-backups/  ← per-world backup history
│   ├── default/
│   │   ├── git/        Incremental git snapshots
│   │   └── archives/   tar.gz archives
│   └── …
├── resource-packs/     ← shared resource packs (served at /pack/<name>)
└── .bruh_minecraft/    ← HA integration IPC (sensors / services)

/data/
├── server-cache/       ← Cached server jars (keyed by version + build)
└── panel/              ← Panel state, RCON secret, logs
```

---

## Example configuration

The HA Configuration tab now holds only **install/container-level** options.
Gameplay settings (gamemode, difficulty, etc.) are per-world — edit them in
the panel's **Server Properties** tab.

```yaml
eula: true
active_world: default
server_type: paper          # paper | purpur | folia | vanilla | fabric | forge
minecraft_version: LATEST   # LATEST | SNAPSHOT | "1.21.4"
memory_mb: 4096
use_aikar_flags: true

auto_update_server: true
auto_backup: true
backup_interval_minutes: 60
backup_keep_count: 48
backup_use_git: true

enable_bedrock_support: true
geyser_auth_type: auto      # auto | floodgate | online | offline

plugins:
  - url: https://example.com/plugins/CustomThing.jar
install_essentialsx: true   # curated one-click installers
install_luckperms: true
install_coreprotect: true
```

Full option reference with rationale for every default: [`config.yaml`](config.yaml) (the comments are the docs) · [DOCS.md § Configuration reference](DOCS.md#1-configuration-reference).

---

## What's new in 1.10.0

- **First-run wizard.** Install → start → answer 3 questions → done.
- **Crash banner.** When the JVM exits unexpectedly the dashboard shows the last lines of error context. No more "where do I look?"
- **World import.** Drop a `.zip` of an existing world into the **Worlds** tab → it becomes a switchable world.
- **Resource-pack hosting.** Upload a pack, get a URL and SHA-1, click *Apply* to wire it into the active world automatically.
- **Smart performance hints.** When TPS slips, the Performance card suggests the most useful knob to turn first.

See [CHANGELOG.md](CHANGELOG.md) for everything, including 1.9.0's popular-plugin tidy-up and the *Tune for my hardware* recommender.

---

## License & support

MIT — see [LICENSE](../LICENSE).

Issues and feature requests: <https://github.com/bruhautomation/BRUH-HA-Apps/issues>.
