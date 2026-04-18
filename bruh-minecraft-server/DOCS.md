# BRUH Minecraft Server — Documentation

Complete configuration reference, operational notes, and integration details.

---

## 1. Configuration reference

Every option can be set from the add-on's **Configuration** tab. All options are validated against the schema in `config.yaml`; invalid values will be rejected by the Supervisor before the add-on starts.

### Required

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `eula` | bool | `false` | **You must set this to `true` to start the server.** Accepts the Minecraft EULA at <https://www.minecraft.net/eula>. |

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
| `max_players` | 1–1000 | `20` |
| `view_distance` | 3–32 | `10` |
| `simulation_distance` | 3–32 | `10` |
| `online_mode` | bool | `true` |
| `pvp` | bool | `true` |
| `hardcore` | bool | `false` |
| `allow_flight` | bool | `false` |
| `white_list` | bool | `false` |
| `spawn_protection` | 0–10000 | `16` |
| `level_name` | string | `world` |
| `level_seed` | string | `""` (random) |
| `level_type` | string | `minecraft:normal` |
| `enable_command_block` | bool | `false` |
| `op_permission_level` | 1–4 | `4` |

> **Heads-up:** changing `level_name` or `level_seed` only takes effect when a fresh world is being generated. To reset a world, move the world directory aside under `/config/minecraft/` and restart.

### JVM / performance

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `memory_mb` | 512–65536 | `2048` | Applied as both `-Xms` and `-Xmx` (recommended for steady GC behaviour). |
| `use_aikar_flags` | bool | `true` | Use the widely-recommended Aikar G1GC tuning for Minecraft. |
| `extra_jvm_args` | string | `""` | Append-your-own extra JVM flags. |

### RCON

RCON is always enabled on port `25575` and bound to `127.0.0.1`. The add-on auto-generates a secure password on first boot (stored at `/data/panel/rcon.secret`) unless you set `rcon_password`. The password never leaves the HA host — only the ingress panel and HA bridge use it.

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

| Option | Type | Default |
|--------|------|---------|
| `auto_restart_on_crash` | bool | `true` |

Rate-limited: a maximum of 5 restarts per 5-minute rolling window before the add-on gives up and reports the crash. The **Stop** button in the panel (and the `bruh_minecraft.stop_server` service) writes a `no_restart` flag so the JVM stays down until you start it again.

### Plugins (Paper / Purpur / Folia)

```yaml
plugins:
  - url: https://example.com/Essentials.jar
    name: Essentials.jar          # optional rename
  - url: https://example.com/ViaVersion.jar
```

Plugins are fetched with `If-Modified-Since`, so re-starts don't re-download unchanged files.

### HA integration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_ha_integration` | bool | `true` | Deploy the `bruh_minecraft` custom integration and start the file-IPC bridge. |
| `announce_ha_events` | bool | `true` | Announce HA-triggered events (restarts, backups) in chat with `/say`. |

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
- Keys marked **editable** (MOTD, difficulty, gamemode, PVP, whitelist, etc.) can be changed from the panel; the change is written to `server.properties` and (where possible) applied live via RCON.
- Non-editable keys are rendered read-only — change them via the add-on **Configuration** tab, which is the canonical source of truth for those settings.

### Plugins

- Lists every `.jar` under `/config/minecraft/plugins/` with size and last-modified time.
- Delete button per plugin.
- Install-by-URL form that uses the same engine as the `plugins:` config option.

### Backups

- Git snapshots with short SHA, timestamp, and subject.
- Archive backups with filename, size, and timestamp.
- One-click **Restore** on any row — the server is stopped, worlds are restored, and the add-on restarts the JVM automatically.

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
├── minecraft/                   # server root (persisted)
│   ├── server.jar
│   ├── server.properties
│   ├── eula.txt
│   ├── world/ world_nether/ world_the_end/
│   └── plugins/
├── minecraft-backups/
│   ├── git/                     # git repo (backup_use_git=true)
│   └── archives/                # *.tar.gz (backup_use_git=false)
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

### Out-of-memory crashes

Increase `memory_mb`. Typical sizing:
- 4 players, vanilla world: 2048 MB
- 10 players, some plugins: 4096 MB
- 20+ players, heavy plugin pack: 6144–8192 MB
