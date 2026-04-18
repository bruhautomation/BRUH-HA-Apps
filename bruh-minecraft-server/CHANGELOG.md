# Changelog

All notable changes to the **BRUH Minecraft Server** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.2.1

### Fixed

- **Bedrock still hit "Please log into Xbox to join this server." after
  setting `online_mode: false`.** The Java side was correct (offline
  mode accepted the first join), but the Geyser config was pinned to
  `auth-type: floodgate`, which *still* requires the Bedrock client to
  be signed in to Xbox Live (Floodgate uses the XUID). Subsequent
  connections without a live Xbox session were kicked by Geyser.
- Added a new `geyser_auth_type` option with values
  `auto | floodgate | online | offline`. The default `auto` resolves to
  **`offline` whenever `online_mode` is `false`** (so Bedrock clients
  can join with zero sign-in alongside cracked Java clients) and
  `floodgate` when `online_mode` is on (preserves GeyserMC's
  recommended default for public servers).

### Tests (4 new, 158 total)

- `TestGeyserAuthPatch` gained 4 tests covering auto → offline in
  offline-mode, auto → floodgate in online-mode, explicit `offline`
  winning over online-mode, and explicit `online` patching over a
  floodgate config.

## 1.2.0

### Fixed

- **`signal only works in main thread of the main interpreter`** when
  sending console commands from the ingress panel's sidebar or via
  `bruh_minecraft.rcon_command`. The `mcrcon` PyPI package uses
  `signal.SIGALRM` for its handshake timeout, which isn't allowed in
  aiohttp / `asyncio.to_thread` worker threads. The add-on now ships
  a thread-safe RCON client at `scripts/rcon_client.py` that uses only
  `socket.settimeout()`, and the `mcrcon` dependency has been dropped
  from the Dockerfile. Panel, HA bridge, stats collector, and the
  `rcon.py` CLI all switch over.
- **"Please log into Xbox to join this server" even after setting
  `online_mode: false`.** MC 1.19+ requires a Mojang-signed chat profile
  unless `enforce-secure-profile=false`, and there was no way to turn
  that off from the add-on UI. Added a new `enforce_secure_profile`
  option (default `false`), exposed as an editable property in the
  panel's Server Properties tab, and auto-forced to `false` whenever
  `online_mode` is off so offline clients can't be bounced by this.

### Added

- **Offline / cracked-login mode just works.** Set `online_mode: false`
  in the add-on options and the server now accepts any Java username
  without an Xbox / Microsoft account — Bedrock clients keep working
  via Floodgate as before. Safe for LAN-only / family servers.
- **`allow_cheats` convenience toggle.** One click flips on
  `enable-command-block` and ensures `op-permission-level >= 2` so
  `/gamemode`, `/give`, `/tp`, `/summon`, `/fill` etc. all work once a
  player is OP'd.
- **`initial_ops` list.** Auto-OP the listed Minecraft usernames on
  startup via RCON (handles UUID lookup in both online and offline
  mode) — no more "how do I OP myself after a fresh install?"
- **Many more server.properties toggles exposed as add-on options:**
  `allow_nether`, `generate_structures`, `spawn_monsters`,
  `spawn_animals`, `spawn_npcs`, `prevent_proxy_connections`,
  `hide_online_players`, `resource_pack`, `resource_pack_sha1`,
  `require_resource_pack`, `max_world_size`,
  `network_compression_threshold`, `entity_broadcast_range_percentage`.
- **More editable keys in the panel's Server Properties tab,**
  including everything added above, `op-permission-level`, and the
  world-gen keys (`level-name`, `level-seed`, `level-type`).

### Tests (14 new, 154 total)

- `test_minecraft_rcon_client.py` — 4 tests: auth round-trip,
  multi-packet reply reassembly, bad-password ``RconAuthError``, and
  the key **regression guard** that the RCON client still works when
  invoked from a worker thread (the exact path that used to trip
  `signal only works in main thread`).
- `test_minecraft_properties.py` — 6 new tests covering
  `enforce-secure-profile` defaults / opt-in / offline-mode auto-force,
  `allow_cheats` coercion of command block + op level, the
  `resource-pack` triplet pass-through, and that all new managed keys
  actually render.

## 1.1.0

### Added

- **Bedrock MOTD matches your add-on MOTD.** No more "Another Geyser
  server." — Geyser's `motd1` / `motd2` are now rewritten to your add-on
  `motd` option (plus a "Powered by BRUH HA Apps" subtitle) every boot.
- **One-click HA integration setup.** The add-on now POSTs to the
  Supervisor's `/discovery` endpoint on startup, so a "Discovered: BRUH
  Minecraft" tile appears on Settings → Devices & Services. A single
  click adds all the sensors, buttons, and services.
- **Notify platform.** New `notify.bruh_minecraft_broadcast` entity that
  works with HA's standard `notify.send_message` service:
    - Plain message -> `/say` broadcast.
    - `message` + `title` -> `/tellraw @a <json>` with a bold gold title.
    - Newlines stripped, 256-char safety cap.
  Drop it into any automation like any other notify target.
- **Version stamp in the log.** `ADDON_VERSION` is baked into the image
  at build time and printed in the startup banner, so "am I running the
  latest build?" is answerable in one line.
- **Louder Geyser-patch logs.** The install-bedrock-support.sh now prints
  the config file's size/owner/mode, the before/after auth-type values,
  and a loud warning if the patch didn't produce `auth-type: floodgate`.

### Tests (12 new, 140 total)

- `TestHaDiscoveryAnnouncement` — 4 tests for the `/discovery` POST.
- `test_minecraft_notify.py` — 6 tests covering plain/say, title/tellraw,
  newline stripping, 256-char cap, empty-message no-op, TITLE feature.
- `TestGeyserAuthPatch` gained 2 tests covering motd1/motd2 patching.

## 1.0.6

### Fixed

- **"Please log into Xbox to join this server."** Geyser's default
  `auth-type` is `online`, which forces every Bedrock client to
  authenticate against Xbox Live — defeating the whole point of bundling
  Floodgate. The installer now patches `plugins/Geyser-Spigot/config.yml`
  to `auth-type: floodgate` on every boot:
    - Fresh install → stages a minimal config so Geyser uses Floodgate
      the first time it starts.
    - Existing `auth-type: online` / `auth-type: offline` → patched in
      place (indentation preserved, other keys untouched).
    - Already `floodgate` → no-op (idempotent).
- This is the final missing piece for painless iOS / iPadOS / Switch /
  Xbox / PS / Android LAN play.

### Added

- `tests/test_minecraft_geyser_auth.py` — 5 behaviour tests covering
  fresh install, default online config, already-patched config,
  missing-auth-type append, and indent preservation.

## 1.0.5

### Fixed

- **Bedrock LAN discovery now works.** The server started and Geyser bound
  to UDP 19132 correctly, but the world didn't appear in the **Friends**
  tab of Minecraft Bedrock (iOS, Android, Switch, Xbox, PS, Win10/11).
  Bedrock clients find local servers by listening for UDP multicast /
  broadcast pings on 19132, and Docker's bridge network drops those
  packets. Flipped `host_network: true` so the container shares the HA
  host's network stack directly and the pings reach LAN devices.
- This matches the upstream convention for Bedrock HA add-ons (e.g.
  `ha-spawn-point-bedrock`) and is the "obvious thing" I missed in 1.0.3 /
  1.0.4.

### Unchanged

- Ingress (management panel) still works because the Supervisor proxies
  it over a unix socket, not TCP.
- Manual "Add Server" connect-by-IP always worked, but now LAN auto-
  discovery does too.

### Added

- `test_host_network_enabled` regression guard.

## 1.0.4

### Fixed

- **Geyser + Floodgate downloads were 404ing** in 1.0.3 because the
  GeyserMC v2 API calls the Paper/Purpur/Folia build `spigot`, not
  `paper`. The installer now uses the correct slug and the downloads
  succeed. Bedrock clients (iOS, Android, consoles, Win10/11) can finally
  connect to the Java server on UDP:19132.
- **Fabric:** Floodgate has no `fabric` variant (Geyser-Fabric bundles
  Floodgate support natively), so we now install Geyser only on Fabric
  and log a clear "Floodgate skipped" message.

### Added

- New `test_installer_uses_spigot_not_paper_slug` keyword test.
- New `test_geyser_download_urls_resolve` live HEAD test that probes
  `download.geysermc.org` and fails loudly if a URL slug changes. Skipped
  automatically when the test host has no internet.

## 1.0.3

### Added

- **Bedrock cross-play is on by default.** New `enable_bedrock_support`
  option (default `true`) auto-installs Geyser + Floodgate so iOS, Android,
  Windows 10/11, Xbox, Switch and PlayStation players can join the same
  Java Edition world on UDP:19132 — no manual plugin install needed.
- Geyser + Floodgate are downloaded from GeyserMC's v2 API on every start;
  `If-Modified-Since` prevents needless re-downloads.
- Supported on Paper / Purpur / Folia (plugin mode) and Fabric (mod mode).
  Vanilla / Forge log a friendly warning and skip (use Geyser-Standalone
  separately, or set `enable_bedrock_support: false`).
- Six new tests in `tests/test_minecraft_scripts.py::TestBedrockSupport`
  lock in the default, the toggle behaviour, and per-server-type dispatch.

### Docs

- README and DOCS updated with a dedicated "Bedrock cross-play" section.

## 1.0.2

### Fixed

- **Crash-loop on first start.** `bashio` sources `set -e` + `set -u` +
  `pipefail`, and `load_config()` was attempting to write the RCON password
  to `/data/panel/rcon.secret` before `prepare_filesystem()` created that
  directory. The redirection failed silently, `set -e` killed the script,
  and s6 restarted the add-on over and over with nothing after
  `Loading add-on configuration` in the logs.
- Moved all RCON password IO into a new `ensure_rcon_password()` step that
  runs after `prepare_filesystem()` so the target dir is guaranteed to exist.
- Added `${SUPERVISOR_TOKEN:-}` so `set -u` can't abort if the Supervisor
  token isn't injected for some reason.

### Added

- `log_level` option now actually controls bashio verbosity: `load_config()`
  exports `BASHIO_LOG_LEVEL` based on the option, so `debug`/`trace` really
  produce extra output.
- Four regression tests in `tests/test_minecraft_scripts.py` that would
  have caught this:
    - `test_load_config_does_not_write_to_panel_state`
    - `test_ensure_rcon_password_runs_after_prepare_filesystem`
    - `test_supervisor_token_has_default`
    - `test_log_level_propagated_to_bashio`

## 1.0.1

### Fixed

- **Add-on would not start** with `s6-envdir: fatal: unable to envdir
  /run/s6/container_environment: No such file or directory`. The Dockerfile
  set a custom `ENTRYPOINT` (tini), which bypassed the HA base image's
  s6-overlay init. Without s6-overlay, the `#!/usr/bin/with-contenv bashio`
  shebang on `run.sh` had nothing to read, so the script exited before
  executing a single line.
- Drop the custom `ENTRYPOINT` so s6-overlay runs as PID 1 and signals +
  zombie reaping continue to work correctly.
- Remove the now-unused `tini` package from the image.

### Added

- 110-test suite under `tests/test_minecraft_*.py` covering config /
  Dockerfile / script quality, server.properties rendering, RCON parsers,
  the ingress panel API (aiohttp test client), the file-IPC bridge
  (round-trip + timeout cleanup), and the HA custom integration.
- Regression guard: `test_no_entrypoint_override` will fail loudly if a
  future Dockerfile edit reintroduces the s6 bypass.

### Changed

- Replaced two lambda GET handlers in `panel/server.py` with async
  functions to silence the aiohttp 3.13 `DeprecationWarning`.

## 1.0.0 — Initial release

### Added

- **Server types:** Paper, Purpur, Folia, Vanilla, Fabric, Forge — all resolved
  from upstream APIs, with `LATEST` / `SNAPSHOT` / explicit version support.
- **Jar caching** under `/data/server-cache` so repeat starts don't re-download.
- **Aikar-flagged JVM** tuning (toggleable), Java 21 runtime.
- **Ingress panel** with dashboard, live console (SSE), player management,
  editable server properties, plugin install/delete, and a backup browser.
- **Git-based world version control** with rsync-backed snapshots and UI restore.
- **tar.gz archive backups** as an alternative mode.
- **Crash auto-restart** with rolling rate-limit (5 restarts / 5 minutes).
- **Graceful shutdown** — RCON `save-all flush` + `stop`, 60 s grace, then SIGTERM.
- **HA custom integration** auto-deployed to `/config/custom_components/`:
    - 12 sensors (players, TPS, latency, uptime, version, MOTD, …)
    - 2 binary sensors (reachable, RCON reachable)
    - 4 buttons (Backup, Restart, Stop, Save)
    - 13 services (rcon_command, say, give, set_weather, set_time, backup_now,
      restart_server, stop_server, op_player, deop_player, kick_player,
      ban_player, whitelist_add, whitelist_remove)
- **Supervisor discovery** registers `bruh_minecraft` so HA auto-prompts setup.
- **RCON hardened:** loopback-only binding, auto-generated 32-char password.
- **Ingress auth awareness:** all panel paths are relative so HA's ingress
  proxy works seamlessly.
