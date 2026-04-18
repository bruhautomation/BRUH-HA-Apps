# Changelog

All notable changes to the **BRUH Minecraft Server** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
