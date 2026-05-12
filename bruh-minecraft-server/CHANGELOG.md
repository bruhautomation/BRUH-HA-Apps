# Changelog

All notable changes to the **BRUH Minecraft Server** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.5.6

### Fixed: live console drowning in RCON polling noise

`scripts/stats-collector.py` polls the running Paper server via RCON
every 15 seconds for `/list` (and, when supported, `/tps` and
`/version`) so the Dashboard tab and the HA sensors can show live
player counts + TPS. Each round-trip writes **three** lines into
`console.log`:

```
[hh:mm:ss INFO]: Thread RCON Client /127.0.0.1 started
[hh:mm:ss INFO]: [Essentials] Rcon issued server command: /list
[hh:mm:ss INFO]: Thread RCON Client /127.0.0.1 shutting down
```

So every minute the live Console tab pulled in **12 noise lines**,
drowning out actual server events (joins, deaths, chat, plugin
warnings). Backup runs added three more lines per snapshot via
`save-off` / `save-all flush` / `save-on`.

**Fix:** strip these specific patterns at the SSE boundary in
`panel/server.py::api_logs_sse`. The `/data/panel/console.log` file
on disk still contains the full history for offline debugging — only
the live `/api/logs/tail` stream is filtered. The filter covers the
two `Thread RCON Client /127.0.0.1` lifecycle lines and the Essentials
handler's `Rcon issued server command:` lines for `list`, `tps`,
`version`, `save-all`, `save-off`, and `save-on` only. User commands
typed into the panel's Console tab are still echoed normally.

### Fixed: nav bar disappeared on Plugins / Console tabs

After 1.5.5 wrapped the topbar + tabs in a sticky `.page-header`,
users on HA Companion (iOS WKWebView) still reported the nav
vanishing when they scrolled into the Plugins and Console tabs
specifically — these tabs have the longest scrollable content
(plugin list, live console) and the sticky element was collapsing to
zero height inside the flex column body.

**Fix:** harden `.page-header` against the flex-shrink edge case:

- `flex-shrink: 0` so the header keeps its content height regardless
  of how tall the flex container grows.
- `isolation: isolate` so the sticky element gets its own stacking
  context (the horizontally-scrolling tab row's `mask-image` already
  creates one inside the header, which on long pages could otherwise
  paint scrolled content above the header).
- `position: -webkit-sticky` prefix added for older iOS WebKit.
- `z-index` bumped from `10` to `100` so a future overlay can't
  accidentally hide the nav.

### Fixed: misleading "Refusing to overwrite" backup-symlink error every boot

Every 1.5.5 boot logged:

```
ERROR: /config/minecraft-backups is not a symlink but should be after
migration. Refusing to overwrite.
```

`ensure_worlds_layout` tried to make `/config/minecraft-backups` a
symlink pointing at its own `<active>/` subdirectory — but a symlink
that points inside its own tree is a circular loop the kernel won't
follow, so the install-time `ln -s` failed and the error fired on
every restart. More importantly: downstream consumers
(`panel/server.py::api_backups_list`, `scripts/backup.sh`) read
`MC_BACKUP_DIR` from the env, which still pointed at the parent
directory — so the panel's Backups tab came up empty and the auto-
backup watcher re-created a fresh `git/` repo at the *parent* level
instead of writing under the active profile.

**Fix:**

- Stop trying to make `/config/minecraft-backups` a symlink. It is
  the legitimate parent directory of every per-profile backup tree
  (`<name>/git/`, `<name>/archives/`).
- Re-export `MC_BACKUP_DIR=<MC_BACKUPS_ROOT>/<active>` from
  `ensure_worlds_layout` so the panel + backup scripts find the
  active profile's `git/` and `archives/` in the right place.
- `panel/server.py` gained a defensive fallback: if `MC_BACKUP_DIR`
  still points at the parent dir (older deployments that haven't yet
  rebooted onto 1.5.6), it auto-descends into `<ACTIVE_WORLD>/` when
  that subdir contains `git/` or `archives/`.

### Migration

Restart the add-on. No config changes.

**Heads-up for users coming from 1.5.5:** if your auto-backup watcher
ran while the symlink was broken (it almost certainly did), some
snapshots may have been written to the *parent* directory instead of
under the active profile. After restarting onto 1.5.6 you may see:

```
/config/minecraft-backups/git/          ← orphan snapshots from 1.5.5
/config/minecraft-backups/<active>/git/ ← visible in the panel
```

To merge the orphans into the visible history, stop the add-on, copy
`/config/minecraft-backups/git/.git/refs/heads/main`-worth of commits
into the `<active>/git/` repo via `git fetch ../git refs/heads/main`,
then restart. If you don't care about pre-1.5.6 snapshots, just delete
`/config/minecraft-backups/git/` and the matching `archives/` folder.
1.5.6 onwards always writes to the right place.

## 1.5.5

### Fixed: Configuration tab edits never applied via panel's Restart button

Two cooperating bugs meant that changes made in the HA add-on's
**Configuration** tab silently failed to take effect when users clicked
the panel's header **Restart** button. The Server Properties tab in the
panel kept showing the old values, and the running Minecraft server
kept running with the old settings — the only way to actually apply the
change was a full Supervisor-level container restart from the HA add-on
page, which users (reasonably) didn't realise they needed.

**Root cause #1 — `run_server_loop` never re-rendered `server.properties`.**
The panel's Restart button RCON-stops the JVM with `save-all flush; stop`,
which is a clean exit. `run_server_loop` saw `rc=0` and immediately
relaunched the JVM via `server-launcher.sh`. But `setup-server-properties.sh`
only ran *once*, in `main()` before the loop started — so on the second,
third, … JVM start, the server kept reading whatever `server.properties`
was written at original container boot. Likewise the panel's `/api/properties`
endpoint reads that same on-disk file, so the Server Properties tab
mirrored the stale content.

**Root cause #2 — env vars were frozen at container start.**
`load_config` (the `bashio::config` reads) only ran once, in `main()`.
Re-rendering `server.properties` from the same stale env vars wouldn't
have helped — we needed fresh values from `/data/options.json`.

**Fix:** at the top of every iteration of `run_server_loop` *after the first*,
re-run `load_config` + `ensure_rcon_password` + `render_server_properties`.
The first iteration skips the re-run because `main()` already did the work
right before entering the loop (avoiding duplicate boot-time noise). Now
every JVM restart picks up the latest `/data/options.json`, regenerates
`server.properties`, and propagates the new values to both the running
server and the panel's Server Properties tab.

The panel's RCON password file is also refreshed each iteration, so a
user who rotates `rcon_password` via the Configuration tab + panel
Restart now sees the panel and server stay in sync.

### Fixed: panel tabs became dead ends when scrolled

On long tabs (Console, Backups, Worlds) the topbar and tab navigation
scrolled out of view as soon as the user scrolled down into the
content, with no way back to other tabs except scrolling all the way
up. On phones — where the viewport is short and the Console tab is
already 60vh tall — every tab effectively turned into a dead end the
moment the user interacted with anything below the fold.

**Fix:** wrap the topbar + nav in a `.page-header` container with
`position: sticky; top: 0; z-index: 10;` so they stay pinned to the
top of the viewport while the tab content scrolls underneath. The
horizontal-scroll behavior of the tab row on narrow viewports is
preserved.

## 1.5.4

### Added: auto-quarantine for duplicate plugin jars

A new boot step scans `plugins/`, reads each jar's `paper-plugin.yml` /
`plugin.yml` metadata, groups jars by **plugin name**, and moves any
duplicates into `plugins/.quarantine/`. The kept copy is the one with
the highest semver, preferring stable releases over pre-releases /
snapshots / RCs (and using filename mtime as the final tiebreaker).

**Why:** plugin folders accumulate stale jars over time. The most
common cause is that the popular-plugin auto-installer briefly served
a `-pre` build (e.g. `multiverse-core-5.6.2-pre.jar`), then later the
stable `5.6.2.jar`, leaving both files in the folder. Paper logged
`Ambiguous plugin name 'Multiverse-Core'` on every boot and one of
the copies got disabled randomly. The same pattern hit the user
during the Mojang 26.1 transition with `ViaVersion-5.9.2-SNAPSHOT.jar`
sitting next to a stable build.

**Behaviour:**

- Runs **after** all the install steps, so a jar we just downloaded
  is always present and never accidentally quarantined.
- Jars are **never deleted** — only moved into `plugins/.quarantine/`.
  Restore a jar by moving it back to `plugins/` and restarting; free
  the disk by deleting the whole `.quarantine/` folder.
- A `plugins/.quarantine/QUARANTINE.md` log records every move with
  timestamps, the plugin name, the kept version, and the moved
  filename.
- Library jars (no `plugin.yml` inside) and corrupt jars are ignored
  — they never get touched.

**New option:**

```yaml
auto_quarantine_duplicates: true   # default
```

Set to `false` if you intentionally want multiple copies of a plugin
in the folder (rare; Bukkit can only run one at a time anyway).

### Migration

Restart the add-on. On the first boot you'll see one or two
`[plugin-cleanup]` log lines per duplicate, e.g.:

```
[plugin-cleanup] Multiverse-Core: keeping multiverse-core-5.6.2.jar v5.6.2;
                 quarantining multiverse-core-5.6.2-pre.jar v5.6.2-pre
```

`Ambiguous plugin name` errors should disappear from your logs after
this. Stale-but-not-duplicated jars (e.g. a leftover Dynmap from
before it was removed from the curated set) are NOT auto-removed —
delete those manually from the panel's Plugins tab.

## 1.5.3

### Fixed: ViaVersion silently dropped on boot — Bedrock clients still kicked

1.5.2 installed `ViaVersion-5.9.2-SNAPSHOT.jar` into the plugins folder
on every restart, but Paper silently skipped it at load time. Logs
showed only ViaBackwards initialising, followed by:

> [ModernPluginLoadingStrategy] Could not load 'plugins/ViaBackwards-…jar'
> Unknown/missing dependency plugins: [ViaVersion]

…and Geyser:

> Your server software does not support the Java version that Geyser
> requires (26.1). Please install ViaVersion …

**Root cause:** the ViaVersion build that supports MC 26.1 is compiled
against Java 25 (class file version 69). The container shipped Alpine's
`openjdk21-jre-headless`, which can only load class file version up to
65, so the JVM threw `UnsupportedClassVersionError` and Paper dropped
the plugin without surfacing it as an ERROR. The same failure mode
killed the latest VeinMiner build (which logged the exception loudly:
`de/miraculixx/veinminer/VeinminerLoader has been compiled by a more
recent version of the Java Runtime (class file version 69.0)`).

**Fix:** swap Alpine's `openjdk21-jre-headless` for **Eclipse Temurin
JRE 25** (LTS), pulled directly from the Adoptium Alpine-musl release.
Both `amd64` and `aarch64` are covered; the URL is selected at build
time from `uname -m`. Java 25 runs Paper 1.21.11 and every earlier
version unchanged — class files are backwards-compatible — so existing
worlds and plugins keep working.

After this update, ViaVersion loads, ViaBackwards finds its dependency,
Geyser stops complaining, and 26.1 Bedrock/Java clients can join the
1.21.11 server cleanly.

### Migration

Restart the add-on. The container image grows by ~80 MB (full Temurin
JRE vs. Alpine's split package set). No config or world changes.

If you have stale plugin jars sitting in
`/config/minecraft-worlds/<world>/plugins/` from before — for example
the old `Dynmap-3.7-beta-8-spigot.jar` (from when Dynmap was in the
curated list pre-1.5.0) or a duplicate `multiverse-core-5.6.2-pre.jar`
— delete them via the panel's **Plugins** tab. They're harmless on
Java 25 but the duplicate Multiverse-Core jars trigger an "Ambiguous
plugin name" error on every boot.

## 1.5.2

### Fixed: `Outdated server!` / `This server does not support Java Edition 26.1`

Mojang shipped Minecraft **26.1** (the new year-based versioning) and
Paper hasn't published a 26.1 build yet — `LATEST` correctly resolves
to `1.21.11`, but Java *and* Bedrock clients on the new release get
kicked with:

> This server does not support Java Edition 26.1, which is required for
> Geyser to connect. The server needs to update or have the ViaVersion
> plugin installed.
> Original disconnect message: Outdated server! I'm still on 1.21.11

The fix is the **ViaVersion** + **ViaBackwards** protocol bridges,
which let an older Paper server speak the newer client's protocol
(and vice-versa). Two new one-click checkboxes ship enabled:

- `install_viaversion: true` — newer client → older server
- `install_viabackwards: true` — older client → newer server

Both auto-resolve the latest Modrinth build on every restart, so as
soon as ViaVersion publishes support for the next MC release the
server picks it up the next time you restart.

### Migration

Restart the add-on. The two jars install automatically into
`/config/minecraft-worlds/<world>/plugins/`. Bedrock clients on
26.1 should now join the 1.21.11 server cleanly.

If you specifically don't want the bridges (e.g. you're running a
strict-version server for competitive play), flip both toggles off
in the Configuration tab and delete the jars from the **Plugins** tab.

## 1.5.1

### Fixed: `LATEST` resolved to a bogus `26.1.2` jar on Purpur

Purpur's API now appends a non-Minecraft `26.1.2` rebuild marker AFTER the
latest stable release in `versions[]`. The 1.5.0 LATEST resolver took the
last filtered entry, handed back `26.1.2`, and the Purpur download URL
404'd — leaving the server stuck on the previously-cached jar. After your
own Minecraft client auto-updated to the newest stable, joining failed
with **"Outdated server!"** / "server is not up to date" because the
add-on was never actually pulling the new build.

The resolver is now numerically semver-sorted with a `^1\.` prefix
filter, so non-MC rebuild markers can never win — even if the API ever
ships them out of chronological order.

`auto_update_server: true` (the default) was already wired up; together
with this fix it now reliably pulls the newest Paper/Purpur/Folia/Vanilla/
Fabric/Forge build on every add-on restart. Plugins (the `plugins:` URL
list, the `install_*` checkboxes, and Geyser/Floodgate) continue to
re-resolve the latest jar on every boot via Modrinth / GeyserMC's
`versions/latest/builds/latest` endpoints — `If-Modified-Since` keeps
unchanged plugins from re-downloading.

### Added: clearer auto-update logging

`download-server.sh` now logs the previously-installed version on entry
and the resolved version on exit, with a one-liner like
`Updated: 1.21.10 build 145 -> 1.21.11 build 12` whenever an update
actually changes the active jar. Easier to confirm at a glance that a
restart actually pulled the newest build.

### Migration

Restart the add-on. No config changes required. If your client is on
the newest Minecraft release and the server still kicks you with
"Outdated server!", check the add-on log for the
`[download-server] Updated: ... -> ...` line — the version after `->`
is what will be live after the boot completes.

## 1.5.0

### Changed: revised the popular-plugin checkbox set

Tightened the curated set to focus on **in-game-useful, no-extra-port**
plugins. Web-map plugins were removed because their default ports
(Dynmap on `8123`, BlueMap on `8100`) collide with Home Assistant's
defaults often enough to surprise users. Voice Chat was removed because
it requires every player to install a matching client mod and exposes
an extra UDP port — the kind of friction the curated list shouldn't push.

**Removed checkboxes (3):**

- `install_dynmap` — Dynmap (web 2D live map)
- `install_bluemap` — BlueMap (web 3D live map)
- `install_simple_voice_chat` — Simple Voice Chat (proximity voice)

**Added checkboxes (4):**

- `install_griefprevention` — GriefPrevention (golden-shovel claim
  protection — players right-click ground with a golden shovel to
  claim a square; only they can build inside)
- `install_mcmmo` — mcMMO (RPG-style skills — Mining/Woodcutting/
  Swords/etc. level up with use)
- `install_chestsort` — ChestSort (left-click outside an open chest
  with an empty hand → instantly sorted)
- `install_veinminer` — VeinMiner (sneak + break one ore = the whole
  vein breaks)

**Migrating from 1.4.0:**

If you had `install_dynmap`, `install_bluemap`, or `install_simple_voice_chat`
set to `true`, the option will silently drop on update — the corresponding
jars will stay on disk. Delete them from the panel's **Plugins** tab if
you don't want them anymore. Anything else can be installed manually via
the existing `plugins:` URL list (browse [modrinth.com/plugins](https://modrinth.com/plugins),
[hangar.papermc.io](https://hangar.papermc.io), or [SpigotMC](https://www.spigotmc.org/resources/categories/spigot.4/)).

**Heads-up about "in-game biome maps":** these are fundamentally
client-side mods (Xaero's Minimap, JourneyMap, etc.) — a server plugin
can't draw on a player's client. The vanilla `/locate biome <id>`
command (1.18+) does what most server admins actually want: points at
the nearest desert / jungle / mushroom-field.

## 1.4.0

### Added

- **One-click popular plugins.** 11 new `install_<name>` checkboxes in the
  Configuration tab let you tick on a curated set of well-known free
  plugins — the add-on resolves the latest Paper-compatible jar via the
  Modrinth API on every boot and installs it just like the existing
  `plugins:` URL list. Curated set:

    - `install_essentialsx` — EssentialsX (homes, warps, kits, /tpa, /repair)
    - `install_essentialsx_chat` — EssentialsXChat (chat formatting companion)
    - `install_luckperms` — LuckPerms (modern permissions)
    - `install_worldedit` — WorldEdit (in-game block editing)
    - `install_worldguard` — WorldGuard (region protection)
    - `install_coreprotect` — CoreProtect (anti-grief logging / rollback)
    - `install_multiverse_core` — Multiverse-Core (multi-world)
    - `install_dynmap` — Dynmap (web-based 2D live map)
    - `install_bluemap` — BlueMap (3D web live map)
    - `install_spark` — Spark (server profiler)
    - `install_simple_voice_chat` — Simple Voice Chat (proximity voice)

  Bukkit-API only (Paper / Purpur / Folia). All resolution goes through
  `scripts/popular-plugins.sh`, which falls back gracefully when a plugin
  isn't on Modrinth or the lookup fails (logs a warning and continues so
  one bad lookup can't tank the add-on).

  Browse for anything not in this list at <https://modrinth.com/plugins>,
  <https://hangar.papermc.io>, or <https://www.spigotmc.org/resources/categories/spigot.4/>
  and add it to the `plugins:` URL list.

## 1.3.1

### Reverted

- **Reverts the offline-first boot behaviour shipped in 1.3.0.** That change
  caused the add-on to fail to start with an empty log on some installs.
  Behaviour is now identical to 1.2.9. Offline-first boot will return in a
  later release once the regression is understood and fixed.

## 1.3.0

### Reverted

- See 1.3.1. Do not install this version.

## 1.2.9

### Fixed

- **World switcher kept loading the same world.** Clicking **Switch**
  updated the `active_world` add-on option correctly, but the symlink
  that actually points at the active profile (`/config/minecraft ->
  /config/minecraft-worlds/<name>`) is re-created inside
  `ensure_worlds_layout` which only runs when the add-on CONTAINER
  starts. The panel's header **Restart** button merely RCON-stops the
  JVM, letting `run_server_loop` relaunch it inside the same container
  — so the symlink never moved and the server kept loading the old
  profile (users reported "it always goes back to the default
  server"). The Switch button now issues `POST /addons/self/restart`
  against the Supervisor immediately after updating `active_world`, so
  the add-on container restarts, `ensure_worlds_layout` re-points the
  symlink, and the new world loads on first boot — no second click
  required. If the Supervisor restart call fails (e.g. the add-on was
  granted reduced permissions), the panel reports the exact failure
  and falls back to the old "click Restart on the HA add-on page"
  instruction.

## 1.2.8

### Fixed

- **Worlds tab "Switch" button failed with `HTTP 400: Missing option
  'allow_nether'`.** `world-manager.sh switch` posted
  `{"options": {"active_world": "<name>"}}` as the entire payload, but
  the Supervisor's `POST /addons/self/options` endpoint **replaces**
  the options object and re-validates against the full add-on schema —
  so every other required field appeared missing. The script now
  `GET`s `/addons/self/info`, merges the new `active_world` into the
  existing options with `jq`, and POSTs the merged object. All of your
  other settings survive the round-trip unchanged.
- **Panel's Players tab showed nobody online even when players were
  connected.** The ingress panel reads player names from `stats.json`,
  which was populated solely by parsing Paper's `/list` RCON reply
  against a strict regex. Paper rephrases that string between minor
  versions, so the regex silently returned an empty name list and
  (worse) overwrote mcstatus's valid online/max counts with zeros
  during the merge. The collector now:
    - Pulls player names from mcstatus's status-ping `players.sample`
      in addition to RCON — the sample is a structured field that
      doesn't suffer from text-format drift.
    - Uses the sample as a fallback whenever RCON parsing returns no
      names, so the panel stays populated even if Paper changes the
      `/list` wording again.
    - Guards the merge so a regex miss can no longer clobber the
      mcstatus counts — "1/20 online" no longer decays to "0/0".

## 1.2.7

### Fixed

- **"Outdated server! I'm still on X.Y.Z" when connecting from Java
  Edition.** `LATEST` was resolving to whichever version ended up last
  in PaperMC's `versions[]` array — which includes pre-releases
  (`1.21.11-pre5`) and release candidates (`1.21.11-rc3`) mixed in
  chronologically with stable releases. During Paper's rolling
  pre-release window the add-on would download an RC jar whose
  network protocol differs from the stable client, so vanilla clients
  rejected the server with the "Outdated server!" kick even though
  the version string matched. `resolve_paper_version` now filters the
  array to stable-shaped entries (`X.Y` / `X.Y.Z`) before picking
  `[-1]`, so `LATEST` always resolves to the newest *released* Paper
  build. Users who explicitly want pre-release jars can still opt in
  via `minecraft_version: SNAPSHOT`. The same filter is applied to
  Purpur, where the upstream `versions[]` array contains out-of-order
  and non-MC-shaped entries that could likewise produce a bogus
  download.
- **`jq: Cannot index string with string "url"` crash-logged on every
  plugin with a shorthand URL entry.** `install_plugins` assumed every
  element of the `plugins:` list was an object of shape
  `{url: "...", name: "..."}`, but users commonly paste a plain URL
  string (`plugins: ["https://.../NickNamer.jar"]`). The mismatch
  logged a jq type error per entry and the plugin was silently skipped
  with "Skipping plugin entry with empty URL", making it look like the
  add-on had forgotten the plugin. The parser now accepts both shapes:
  a JSON string is treated as `{url: <string>}`, so shorthand works
  out of the box.
- **Startup banner printed `v{{ version }}` instead of the real
  version.** `build.yaml` passes `ADDON_VERSION: "{{ version }}"` as
  a Docker ARG expecting the HA Supervisor to render the Jinja
  template to the actual add-on version, but several Supervisor build
  paths (and every local podman build) skip that rendering and leave
  the literal string in place. The add-on now bakes `config.yaml`
  into the image at build time and `run.sh` parses the authoritative
  version at startup, falling back to the ARG only when the parse
  fails. "Am I actually running the new build?" is answerable again
  from the log banner.

## 1.2.6

### Changed

- **Mobile panel is now first-class.** Multiple users reported tabs
  they couldn't reach on phones and forms that overflowed the HA
  Companion viewport. Full responsive pass on `panel/style.css`:
    - Tab row scrolls horizontally with iOS momentum + a right-edge
      fade so you can tell there's more to the right.
    - 40–44 px touch targets on every `.btn` and `.tab`.
    - Tables collapse to horizontal-scroll on narrow viewports
      instead of forcing the page wider than the screen.
    - Input fields use 16 px font to suppress iOS Safari's auto-zoom
      on focus.
    - Single-column grid + compact padding under 720 px; even
      tighter under 400 px (iPhone SE class).
    - `prefers-reduced-motion` honoured for accessibility.
- **Complete DOCS overhaul.** New feature overview + quick-start +
  mobile-access sections at the top of `DOCS.md`; new
  **Complete service reference** with copy-paste payloads for every
  HA service; new **Automation examples** (low-TPS alert, idle
  auto-stop, safe-fill wrapper); new **Security considerations**
  section covering RCON isolation, offline-mode caveats, and the
  plugin-URL threat model. README gains a feature row for the new
  offline-mode / cheats / mobile-friendly work shipped in 1.2.0
  through 1.2.5.
- `viewport-fit=cover` on the panel `<meta>` so the layout respects
  iOS safe-area insets on notched devices.

## 1.2.5

### Fixed

- **Bad plugin URL would kill the whole add-on mid-startup.** If a
  URL in the `plugins:` list 404'd, timed out, or served an HTML
  rate-limit page (looking at you, GitHub), `install-plugin.sh`
  exited 1 and bashio's implicit `set -e` in `run.sh` killed the
  entire startup sequence. Users saw the add-on exit silently right
  after `Installing configured plugins` with no Minecraft server
  launch and no explanation. Now:
  - `install_plugins` isolates the loop in a subshell with
    `set +o pipefail` and a top-level `|| log.warning`, so per-
    plugin failures can't propagate.
  - Each plugin is announced *before* download (`Plugin: X -> URL`)
    so you can see which one misbehaved.
  - Per-plugin failures are tallied and summarised at the end:
    `N plugin(s) failed; see logs above. Server will start anyway.`
- **`install-plugin.sh` now validates downloads.** `curl` now has
  `--max-time 60` so a dead host can't hang startup, and the
  downloaded file is rejected if it doesn't start with the ZIP magic
  bytes `PK` — GitHub / Spigot rate-limit HTML bodies will no longer
  be written to `plugins/X.jar` as a corrupt jar.
- Empty / `null` / non-http(s) URLs are rejected up front with a
  clear message.

### Tests (6 new, 200 total)

- `test_minecraft_install_plugin.py`:
  - 5 edge-case tests for `install-plugin.sh` (empty URL, literal
    `"null"`, `file://` URLs, HTML-body rate-limit pages served as
    200 OK, and a valid PK-header jar download round-trip against
    an in-process HTTP server).
  - 1 static-analysis test locking in the `install_plugins`
    isolation pattern in `run.sh` (`set +o pipefail`, per-plugin
    warning, and the top-level `|| bashio::log.warning` fallback).

## 1.2.4

### Fixed

- **iOS "Connecting multiplayer server…" hang + "You are already
  connected" ghost-session loop.** After a Bedrock handshake stalls
  mid-login (very common on iOS over Wi-Fi), Paper keeps the stale
  session counted as online for ~60–90 s until Geyser's RakNet
  keepalive fires. Every retry during that window is rejected with
  `You are already connected to this server!`, and the user has no
  obvious way to break out short of waiting.
- New **`auto_kick_ghost_sessions`** option (default `true`). A
  lightweight Python daemon (`scripts/ghost-session-watcher.py`) tails
  the Minecraft console log, detects the duplicate-login rejection
  regex, extracts the player name, and fires `/kick <name>` over RCON
  with a per-name 10 s cooldown. Ghost clears in under a second; the
  next retry succeeds.

### Added

- **`geyser_mtu`** option (default `1400`, range 576–1492). Writes
  `advanced.mtu` into the Geyser config. Lowering to `1200` is the
  canonical fix for iOS handshake hangs on home Wi-Fi that fragments
  UDP at 1400 — the Geyser installer now patches this on every boot
  (fresh install + existing config).
- **`connection_throttle_ms`** option (default `4000`). Directly maps
  to Paper's `connection-throttle` in `server.properties`. Setting to
  `0` lets rapid iOS retries through instead of hitting "Slow down,
  you're connecting too fast!"
- **`player_idle_timeout_minutes`** option (default `0` = disabled).
  Paper's built-in idle-kick; a low value (e.g. `5`) is a belt-and-
  suspenders cleanup for stuck sessions on top of the auto-kick
  watcher.

### Tests (13 new, 194 total)

- `test_minecraft_ghost_watcher.py` — 10 tests on the duplicate-login
  regex (matches both Paper variants incl. Floodgate-prefix names;
  rejects unrelated "lost connection" reasons so we never kick an
  innocent player) plus rate-limit and disabled-flag early-exit.
- `test_minecraft_properties.py` gained 2 tests covering the new
  `connection-throttle` / `player-idle-timeout` pass-through.
- `test_minecraft_validate_bedrock_login.py` gained 1 test locking
  in the `advanced.mtu` patch from `GEYSER_MTU`.

## 1.2.3

### Fixed

- **The real root cause of `Please log into Xbox to join this server.`**
  — different from what 1.2.1 and 1.2.2 chased. Setting
  `remote.auth-type: offline` and removing Floodgate wasn't enough;
  Bedrock clients were **still** kicked. The actual gate is Geyser's
  `advanced.bedrock.validate-bedrock-login` (default `true`), which
  validates the Bedrock client's signed Xbox Live JWT chain in
  `LoginEncryptionUtils.encryptConnectionWithCert()` *before* any
  `auth-type` / Floodgate logic even runs. Unsigned chains (LAN-only
  Bedrock devices, non-Xbox-signed clients) get disconnected with the
  exact message we've been chasing. The installer now flips this key
  based on the resolved Geyser auth-type:
  - `offline` → `validate-bedrock-login: false` (Bedrock joins with no
    Xbox sign-in).
  - `floodgate` / `online` → `validate-bedrock-login: true` (secure
    default; Floodgate provides a trusted chain).
- Added `scripts/patch-geyser-config.py` — a comment-preserving YAML
  patcher that handles the three cases cleanly: flip an existing
  nested key, insert a missing key under an existing section, or
  append a fresh `advanced.bedrock` block when neither exists.
- Fresh-install Geyser config also carries the key at the right value
  from the very first boot.

### Tests (11 new, 174 total)

- `test_minecraft_validate_bedrock_login.py`:
  - 7 unit tests on `patch-geyser-config.py` covering flip-in-place,
    comment preservation, insertion-under-existing-section,
    append-full-section, idempotence, restore-secure-default, and a
    realistic full Geyser config round-trip.
  - 4 installer integration tests locking in offline + floodgate
    fresh installs, real-sized-config patching, and offline → floodgate
    restoration of the secure default.

## 1.2.2

### Fixed

- **`Please log into Xbox to join this server.` still fired in 1.2.1
  even with `geyser_auth_type: offline`.** Root cause: Geyser delegates
  Bedrock authentication to Floodgate whenever Floodgate is loaded,
  regardless of the `auth-type` value in Geyser's own config. So even
  after 1.2.1 correctly wrote `auth-type: offline`, Floodgate was still
  demanding an Xbox XUID from every connecting client and kicking them.
- The installer now treats offline as a first-class mode:
  - **Skips the Floodgate install** when the resolved auth-type is
    `offline` (auto → offline path included).
  - **Removes any existing `floodgate-*.jar`** from `plugins/` on
    boot, so switching from `floodgate`/`auto-online` to `offline`
    stops kicking players on the very next restart instead of
    requiring a manual delete.
- `configure_geyser` (renamed from `configure_geyser_for_floodgate`
  since it's not Floodgate-specific) runs unconditionally, so the
  Geyser config still gets `auth-type: offline` written even when
  we skip Floodgate.

### Tests (5 new, 163 total)

- `TestFloodgateSkipWhenOffline` in `test_minecraft_geyser_auth.py`:
  5 behaviour tests locking in the skip, the stale-jar removal,
  that `floodgate`/`auto-online` still installs Floodgate, and that
  the Geyser config still lands correctly in offline mode.

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
