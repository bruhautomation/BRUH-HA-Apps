# Changelog

All notable changes to the **BRUH Minecraft Server** add-on are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.15.3

### Changed

- **The add-on installs from a prebuilt image instead of building on your
  machine.** `config.yaml` now carries an `image:` key pointing at
  `ghcr.io/bruhautomation/{arch}-bruh-minecraft-server`, published for both
  architectures by CI. Installs and updates become a download rather than a
  container build, which on a Raspberry Pi is the difference between minutes
  of SD-card writes and a pull. No action needed.

## 1.15.2

### Security

- **The LAN-refusal log line took a percent-decoded request path.** aiohttp
  hands `request.path` over already decoded, so `%0a` in a URL arrived as a real
  newline and anything on the LAN could write its own lines into the add-on log
  — under a message about being refused. The method, path and peer are flattened
  to one line and capped before they are formatted in.
- **Path containment is now proved where the path is built.** World names, pack
  names and backup refs were already behind anchored allowlists that cannot
  express a separator, so nothing was reachable. `_under()` makes containment a
  property of the path being used rather than of a pattern four hundred lines
  away — worth having in a panel that runs with `host_network: true` and hands
  out world delete, restore and upload.
- **The restore-ref pattern is bounded.** `world-[\w-]+\.tar\.gz` on a URL
  segment a caller picks is an unbounded run of word characters in front of a
  literal suffix, which is what makes a failed match cost more than the string
  is long. No archive this writes comes near 64 characters.

### Changed

- Every deliberately silent exception handler now says what is lost when the
  exception is ignored.

## 1.15.1

### Fixed

- **The integration page showed no logo.** Home Assistant had no artwork for the
  `bruh_minecraft` domain and fell back to printing the raw domain beside the
  name. The artwork was staged for a submission to home-assistant/brands that
  can no longer be made — since Home Assistant 2026.3.0 that repository closes
  any pull request adding a new custom integration automatically.

  The integration now ships a `brand/` folder beside its manifest, which Home
  Assistant serves itself and prefers over the CDN. The icon and wide lockup
  appear with nothing to submit and nobody to wait for.

## 1.15.0

### The management panel answered your whole network

This add-on sets `host_network: true` so Bedrock clients can discover the
server on the LAN, and the panel binds `0.0.0.0:8099`. Together that put the
management API on your network with nothing in front of it. Ingress is a
proxy, not a gate: it authenticates the people who arrive through Home
Assistant and has no say over anyone who types the IP.

So `http://homeassistant.local:8099` reached, without any login,
`POST /api/command` (arbitrary RCON — `/op`, `/ban`, `/stop`), world delete,
backup restore, plugin install and the server.properties editor. This is the
exposure Home Assistant documented in
[GHSA-gh5m-4m97-c95h](https://github.com/home-assistant/core/security/advisories/GHSA-gh5m-4m97-c95h).

The panel now refuses any request that did not arrive through the
Supervisor, judged by the connection's own peer address — not by
`X-Forwarded-For`, which a direct caller sets themselves. Two paths stay
public because they have to be: `/pack/{name}`, which Minecraft clients
fetch the resource pack from, and `/api/health`, which reports liveness and
nothing else. Refusals are logged, so "the panel does nothing when I open it
by IP" has an answer in the add-on log.

**Nothing changes if you open the panel from Home Assistant**, which is how
the sidebar, the Worlds tab and every button already work.

### AppArmor is on

`apparmor: false` was set in `config.yaml`, which disabled the Supervisor's
sandbox and cost a point of security rating. It matters more here than on
most add-ons: this one loads third-party plugin jars that run with the
server's full authority. The profile that replaced it lets the JVM do JVM
things — fork and exec, executable memory for the JIT, the four game ports —
and denies the host-escape set: mounting, kernel modules, raw sockets,
kernel tunables, the Docker socket. **The add-on now rates 6/6 in the
store.**

### Added

- **Every option has a name and an explanation in the UI.** All ~50 of them
  were documented in `config.yaml` comments and none of it reached the
  configuration page, which showed raw keys like `geyser_mtu` with no
  description. `translations/en.yaml` moves that writing to where it is read.
- **A watchdog** on the new `/api/health`, so a hung panel restarts instead
  of sitting there reading as "started".
- A minimum `homeassistant` version, declared rather than assumed.

### Changed

- The generated RCON password and the console log are excluded from Home
  Assistant backups. Your worlds and world backups are still included —
  those are the point of backing this add-on up.

## 1.14.6

### Changed

- **The roof is blocky now too.** The mark had `MC` on a 16u block grid sitting
  under the parent's smooth gable — two drawings in one lockup. The roof is
  stepped onto the same grid, keeping the apex, the 45° slopes and the knockout
  window, so the whole mark is built to one rule. brAIn keeps the smooth roof;
  a test now fails if either app is caught wearing the other's.

## 1.14.5

### Changed

- **A real BRUH mark, at last.** The add-on's icon, its panel favicon and its
  panel header were a gradient plate with an isometric cube on it — no `BR`
  ligature, no gable, not even the brand palette. It now carries the same lockup
  as brAIn and the parent logo, with `MC` set on a 16u block grid as the thing
  that tells the two apps apart. The header's pickaxe emoji on a green gradient
  square goes with it.
- **The full set of store artwork.** `logo.png` is rendered at the right ratio
  instead of being a stretched leftover, and the home-assistant/brands submission
  gains the `icon@2x`, `logo` and `logo@2x` files it never had.

## 1.14.4

### Fixed

- **Plugin auto-install is now version-aware.** The Modrinth resolver
  picked the newest Paper-family build regardless of the server's
  Minecraft version, so e.g. a 1.20.1 server got WorldEdit built for
  1.21.4 — which Paper refuses to load ("Unsupported API version") on
  every boot. Resolution now filters by the installed server version
  (from `.server-meta.json`), prefers release-channel builds over
  alpha/beta, and skips with a clear warning when a plugin has no build
  for your server version instead of installing a jar that can't load.
- **`install_essentialsx_chat` works again.** The resolver looked up the
  Modrinth slug `essentialsxchat`, which does not exist (HTTP 404 on
  every boot). The correct slug is `essentialsx-chat-module`.
- **Plugins built for a newer Minecraft are quarantined.** The boot-time
  plugin cleanup now also moves jars whose `api-version` targets a newer
  MC than the server runs into `plugins/.quarantine/` — they can never
  load, and the quarantine manifest tells you to install a build for
  your server version (or upgrade the server) instead of Paper printing
  a stack trace every start. Restore by moving the jar back, as with
  duplicate quarantines. Disabled together with
  `auto_quarantine_duplicates: false`.
- **Console log noise cut sharply.** The stats collector now polls with
  `minecraft:list` instead of `/list`, so Essentials no longer logs
  "Rcon issued server command" every 15 seconds into console.log; and
  the server brand (`/version`) is fetched once per server run instead
  of every poll — each `/version` made Paper re-run its update check,
  which now dumps a `FileNotFoundException` stack trace every few
  minutes for MC versions the retired `api.papermc.io` v2 API no longer
  serves.

## 1.14.3

- **Sidebar naming**: the ingress panel is now titled "BRUH Minecraft"
  (was "Minecraft") to match the BRUH family branding.

## 1.14.2

- Renamed the add-on to **BRUH Minecraft** as part of the unified BRUH Apps branding;
  new "Solid Blocks" icon, logo, and panel favicon from the BRUH Automation brand
  system. No functional changes.

## 1.14.1

Compatibility with the latest Home Assistant (Supervisor 2026.04+).

### Fixed

- **The add-on can be built and updated again on current Home Assistant.**
  Supervisor 2026.04.0 retired the legacy add-on builder: `build.yaml` is
  ignored and the `BUILD_FROM` build argument is no longer passed, so the
  Dockerfile's `FROM ${BUILD_FROM}` resolved to an empty base image and the
  build failed before it started. The Dockerfile now carries its own default
  (`ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24`, the official
  multi-arch base); older Supervisors keep overriding it per-architecture
  through `build.yaml`. The startup banner's version fallback already
  covered `ADDON_VERSION` no longer arriving from build.yaml args.

### Changed

- **Base image: Alpine 3.19 → 3.24.** Java still comes bundled from Eclipse
  Temurin, so the server runtime is unchanged.
- **The volume map uses the current `homeassistant_config` type** instead of
  the legacy `config` alias (dropped from the Supervisor docs), with an
  explicit `path: /config` so worlds, backups, and the panel keep their
  long-standing mount point. Requires Supervisor 2023.09 or newer.

## 1.14.0

Featured worlds — one-click, fully server-side installs of big community
worlds, starting with **Drehmal: APOTHEOSIS**.

### Added: Featured worlds (Drehmal: APOTHEOSIS)

The Worlds tab now has a **Featured worlds** section. Click **Install** and
the add-on downloads a complete community world (the save plus its bundled
datapacks) straight onto the server and stages it as a new switchable world —
your current world is untouched until you **Switch** to it. Switching pins the
server to the software + Minecraft version the world needs (Drehmal needs
**Paper 1.20.1**) and turns Bedrock support on automatically.

Because the world and its datapacks live entirely **server-side**, anyone can
join and explore with **zero local installs** — including **iPad / iPhone
players over Geyser**. Notes for Bedrock:

* The world is fully playable/explorable on Bedrock through Geyser.
* Drehmal's optional Fabric mods are **client-side only** (shaders, ambience,
  performance) and aren't required to play. Bedrock can't load Java/Fabric
  mods at all, so they're simply skipped.
* The Java resource pack is hosted for Java players, and **auto-converted to a
  Bedrock pack** that Geyser pushes to phones/tablets on join — so iPads get
  the custom textures with no manual step (best-effort: custom 3D models and
  animated textures don't convert).

New pieces: `scripts/curated-worlds.json` (catalog), `install-curated-world.sh`
(downloader/stager, Google-Drive-aware), `convert-java-pack-to-bedrock.py`
(best-effort pack converter), and panel endpoints under `/api/curated-worlds`.

## 1.13.0

A round of "the panel says X but the server is doing Y" fixes plus a
new-world wizard.

### Added: new-world setup wizard

The Worlds tab's "Create a new world" form is now a multi-step wizard
(name + seed → gameplay → rules → players & access → review) that
stages every per-world setting in one go — gamemode, force-gamemode,
difficulty, terrain, PVP, hardcore, max-players, whitelist, spawn
protection. On submit, asks "Switch to it now?" so you don't end up
editing the OLD active world's settings under the impression you're
tuning the new one.

### Fixed: "creative doesn't stick" trap for returning players

Editing `gamemode` in the panel now also auto-sets `force-gamemode=true`
so the change applies to returning players, not just brand-new ones.
Pre-1.13.0 the panel would update the file and live-apply via RCON, but
the next time a player reconnected they'd be back in their saved mode
(usually survival) because `force-gamemode` was false on older worlds.
The auto-set is surfaced in the save response and you can flip
force-gamemode back off explicitly if you want.

### Fixed: world name ≠ level-name confusion

When you created a world named "WORLD_3", its save folder was actually
called `world` (the vanilla default level-name), so the on-disk path
was `WORLD_3/world/`. The Worlds tab showed "WORLD_3" but Server
Properties showed level-name=world. The wizards now set
`level-name=<profile name>` on creation so you see ONE name everywhere
(Worlds tab, Server Properties, Minecraft's F3 debug). Existing worlds
aren't changed — only new ones created via either wizard.

### Fixed: Tune dialog said "memory: unset" when memory was set

HA Supervisor only stores user-overridden values in `options.json` —
default values come from the schema, not the file. So `memory_mb: 2048`
(the default) wasn't in the file and we reported "unset" in the Tune
dialog even though the server was running fine on the default. Now
falls back to the schema default when the key is absent.

### Added: "world-generation only" badge for keys that don't migrate

`level-seed`, `level-type`, `level-name`, `initial-enabled-packs`, and
`initial-disabled-packs` are baked into a world at generation time —
editing them on an existing world has no effect. The Server Properties
tab now shows an inline `world-gen only` badge on those rows with a
hover explanation pointing users at the Worlds tab to create a fresh
world.

### Added: "Editing world X" context above Server Properties

The Server Properties tab now shows which world you're configuring, so
edits never feel like they applied to "the wrong world." Per-world
settings are clearly per-world.

### Added: headline gameplay keys pulled to the top

`level-name`, `motd`, `gamemode`, `force-gamemode`, `difficulty`,
`max-players`, `pvp`, `hardcore`, `online-mode`, `white-list`, view /
sim distance, `level-type`, `level-seed` now appear in a priority block
at the top of the Server Properties table — no more scrolling past
infra keys to find the headline gameplay settings.

### Tests

+8 new (auto force-gamemode, no-op on already-true, explicit edit
respected; extended worlds-create body; memory default fallback; world-
gen-only metadata; level-name sync; priority-order metadata). 687 pass.

## 1.12.0

A wizard expansion + a sweep of UX bugs the previous wizard exposed.

### Added: 9-step setup wizard, properly comprehensive

Previously 7 steps focused on EULA / server software / world basics.
Expanded to 9 with two new steps and a proper performance preview:

1. EULA
2. Server software (with TPS-vs-vanilla details — ~30-40% perf gap)
3. **Connectivity** (audience + Bedrock cross-play question — was implicit)
4. First world — basics (now includes `force-gamemode`, the "creative
   actually stays creative" toggle)
5. **Players & access** (max-players, whitelist, spawn protection)
6. **Performance** with live capacity preview + sanity warnings (heap-vs-host,
   sim>view, etc.)
7. Plugins
8. **Maintenance** (backup interval, keep count, optional nightly restart)
9. Review

### Added: world export (download as zip)

`GET /api/worlds/{name}/export` streams a zip of any world's save data
plus its `server.properties`. *Download* button on every row of the
Worlds tab. Works on the active world too (point-in-time read of region
files; for a fully consistent snapshot use the Backups tab).

### Added: Worlds tab shows each world's gameplay settings inline

Helps with the "my settings don't appear to move when I switch worlds"
confusion — each row now lists that world's gamemode / difficulty /
terrain / online-mode / whitelist so you can see at a glance which
world is which.

### Added: Tune for my hardware now shows the delta

Reads your current `memory_mb` / view-distance / simulation-distance and
compares to the recommendation. Shows only what would change, marked
clearly with arrows; short-circuits with "already optimal" when nothing
needs to change.

### Fixed: OP / kick / ban rejected Bedrock players (`.Ben13765`)

Floodgate prefixes Bedrock usernames with `.` by default. The Players-
tab regex was `^[A-Za-z0-9_]{1,16}$` and rejected the leading dot — so
every action on a Bedrock player returned 400 and the operator had to
fall back to the console. Now accepts `.`, `*`, and `_` anywhere; still
tightly bounded against quoting/injection.

### Fixed: Server Properties showed `minecraft\:normal` literally

Minecraft re-saves `server.properties` with Java's `Properties.store()`
which escapes `:` as `\:`. The panel was rendering the raw escaped form
and users didn't know what to put in the field. `_read_properties` now
unescapes Java values (handles `\:`, `\=`, `\#`, `\!`, `\\`, `\n`, `\t`,
`\r`, and `\uXXXX`).

### Fixed: Server Properties text fields were guess-the-shape

Editable keys all rendered as plain text inputs — including enums like
`gamemode` where the user had to type the value. `/api/properties` now
surfaces type metadata; the panel renders `<select>` for enums and
bools, `<input type="number">` with schema bounds for ints, plain text
for strings. No more guessing.

### Internal

- 15 new tests covering Floodgate-prefix names, Java unescape, properties
  metadata, recommend delta, worlds-list settings, world export, and the
  expanded wizard body. 721 deterministic tests pass.

## 1.11.0

### Fixed: the wizard's CSS overrode `[hidden]`, so it appeared on every page load

The setup overlay's `display: flex` rule beat the browser's default
`[hidden] { display: none }` (without `!important`), so flipping the
`hidden` attribute didn't actually hide it. The wizard showed up after
every update even when the server was already running and there was no
"Dismiss" path. Added explicit `.setup-overlay[hidden] { display: none
!important; }` (and matching rules for the inner steps).

### Fixed: dark-text-on-dark wizard in light mode

The previous wizard CSS referenced a non-existent `--bg-elev` variable and
several fallback literals that didn't match the panel's theme tokens —
so in light mode the card was a dark literal background, and headings /
selects / inputs inherited dark `--fg` (`#16202a`) for an invisible result.
Every rule now uses the real theme tokens (`--bg-card`, `--bg`,
`--bg-raise`, `--fg`, `--muted`, `--accent`, `--border`) and explicitly
sets `color` on text-bearing elements (cards, picks, fields, code spans,
the review block). Tested across the dark and light prefers-color-scheme
breakpoints.

### Changed: the wizard is now a real 7-step walkthrough

Previously a single screen with three controls. Now:

1. **EULA** — with a link and a one-line explanation.
2. **Server software** — Paper / Purpur / Folia / Vanilla / Fabric / Forge,
   each as a radio card with a real explanation of *what* and *why*: TPS
   performance vs vanilla (Paper is ~30–40% faster on busy worlds), plugin
   support, Bedrock-cross-play compatibility, and the niche cases
   (Folia / Fabric / Forge).
3. **Audience** — Internet/public (online mode) vs LAN/family (offline
   mode), with the implications spelled out.
4. **First world** — name, gamemode (each described), difficulty (each
   described), terrain (normal/flat/large-biomes/amplified), optional
   seed, PVP toggle, hardcore toggle.
5. **Performance** — auto-detects host RAM and CPU count (via
   `/api/recommend`), proposes memory + view-distance + simulation-
   distance with rationale, or lets the user enter values manually.
6. **Plugins** — checkboxes for every curated popular plugin
   (EssentialsX, EssentialsX Chat, LuckPerms, WorldEdit, CoreProtect,
   GriefPrevention, mcMMO, ChestSort, VeinMiner, Spark), each with a
   one-line explanation. Auto-hides on non-Bukkit server types.
7. **Review & start** — a summary of every choice; *Start the server*
   writes everything and restarts.

The wizard now drives the whole first-run shape from one place — gameplay
settings, plugins, memory — instead of leaving most of it for the user to
hunt down post-install.

### Changed: `/api/setup` accepts the full wizard body

Now writes: `eula`, `server_type`, `active_world`, `memory_mb`, and any
`install_*` toggles via the Supervisor (global); `gamemode`, `difficulty`,
`level-type`, `level-seed`, `pvp`, `hardcore`, `online-mode`, `view-
distance`, `simulation-distance` into the *named* world's
`server.properties` (per-world). Stages the world's skeleton (`plugins/`,
`mods/`, backup dir) if the directory doesn't exist yet, so the wizard
can name a world that didn't previously exist on disk.

### Hardened: how "is this a first run?" is detected

Previously the wizard appeared whenever `options.json`'s `eula` field was
`false` — which is correct for upgrades (the file persists across them)
but fragile against a manually-edited config, a half-failed Supervisor
write, or an upgrade from a pre-wizard release where the user accepted
EULA via YAML. The wizard now gates on **two** signals:

1. A `/data/panel/.setup-completed` marker file. Lives under `/data/`, so
   it persists across add-on updates and is cleared only on uninstall —
   exactly the lifecycle we want.
2. The EULA being unset in `options.json`.

The wizard shows only when **both** "no marker" and "EULA false" are true.
On wizard submit we drop the marker, so any subsequent state weirdness
can't make the wizard reappear. We also drop the marker opportunistically
the first time the panel sees `eula: true` without a marker (covers the
upgrade-from-pre-wizard case so existing users don't suddenly get
prompted).

### Tests

+8 new (4 wizard-validation paths, 1 world-skeleton creation, 3 marker
behaviour: marker dominates, eula-true writes the marker, submit writes
the marker). 707 pass.

## 1.10.0

A polish release focused on the new-user experience and the
"something went wrong, what do I do" moments.

### Added: first-run wizard

Install, start, open the panel — a welcome overlay walks you through:

1. Accept the Minecraft EULA.
2. Choose **Internet / public** (online-mode on, Mojang auth) or
   **LAN / family / kids without Xbox accounts** (online-mode off; Geyser
   auto-switches to offline auth so Bedrock kids can join too).
3. Pick a server type (Paper is the default for ~99% of users).

Click *Start the server* and that's it — no more "edit the YAML, accept the
EULA, restart the add-on, hunt for the right server type" first-time fuss.
The add-on now idles cleanly when EULA is unset (instead of hard-exiting),
so the panel can run the wizard.

### Added: crash banner on the dashboard

When the JVM exits unexpectedly the dashboard surfaces the last few error /
exception lines from the console log in a red banner — so you can see
*what* broke without leaving the panel for the Console tab. Suppresses
itself when you click *Stop* (that's not a crash) and reappears for any
new crash signature.

### Added: import an existing world

The **Worlds** tab now takes a `.zip` of a Minecraft world (up to 2 GB) and
stages it as a new switchable world. Finds the directory containing
`level.dat` automatically — works whether it's at the zip root, one level
deep, or a re-zipped backup. Switch to the imported world and it boots
exactly as if you'd had it the whole time.

### Added: resource-pack hosting

New **Resource Packs** tab. Upload a `.zip` (≤ 250 MB), the add-on stores
it under `/config/resource-packs/` and serves it at
`http://<HA-host>:8099/pack/<filename>` on your LAN. *Apply to active
world* writes the URL + SHA-1 directly into the active world's
`server.properties` — no copy-pasting hashes.

### Added: smart performance hints

When the 5-minute TPS slips, the Performance card now suggests the most
useful knob to turn first (drop `simulation-distance`, or use *Tune for
my hardware* to size memory). Reach-for-the-fix in one line instead of
"figure it out yourself."

### Internal

- Documentation refreshed across `README.md`, `DOCS.md`, and `config.yaml`
  comments for the per-world model and the new features. Java version
  reference updated to Temurin 25 (was stale at 21).
- `run.sh`: the panel now starts BEFORE the EULA gate, so the wizard can
  accept the EULA from the UI. `check_eula()` removed (dead code).
- Resource packs and world imports are covered by 14 new tests; 700 pass
  overall.

## 1.9.0

### Added: "Tune for my hardware" + TPS health badge

The Dashboard's **Performance** card now does two new things:

- **Health badge.** Each TPS value (1m/5m/15m) is colored — green at 19.5+,
  yellow at 17–19.5, red below 17 — and the card header shows an at-a-glance
  *healthy / degraded / struggling* badge driven by the 5-minute average. No
  more squinting at the numbers to tell if something's off.
- **Tune for my hardware button.** Inspects the host's RAM (via
  `/proc/meminfo`) and CPU count, then proposes sensible values for
  `memory_mb` (global add-on option), `view-distance`, and
  `simulation-distance` (per-world `server.properties`). One click applies
  them — `memory_mb` writes back to the add-on Configuration via the
  Supervisor API (since it's global, one JVM at a time); the distances
  write to the **active world's** `server.properties`. A confirm dialog
  shows the proposed values and the rationale before anything is changed.

New endpoints: `GET /api/recommend` (preview) and
`POST /api/recommend/apply` (apply).

### Changed: popular-plugin tidy-up

- **Removed `install_worldguard` and `install_multiverse_core`.** WorldGuard
  overlapped confusingly with GriefPrevention (both protect land, different
  models); Multiverse-Core overlapped with the add-on's built-in Worlds
  feature in ways that confused most users. Both still installable by hand
  via the `plugins:` URL list if you specifically want them. Their sections
  in `PLUGINS.md` are gone too.
- **Auto-enable plugin dependencies.** Enabling EssentialsX Chat now also
  enables EssentialsX (it's dead without it); enabling ViaBackwards now also
  enables ViaVersion. Logged so it's not silent.
- **Proactive de-dupe.** If a popular toggle's plugin is *also* in your
  `plugins:` URL list, the popular installer detects the matching jar on
  disk and skips the download — no more two-copy waste cleaned up after the
  fact by the quarantine.
- **Visible quarantine.** The duplicate-jar quarantine now names which
  plugins it cleaned up in the boot log (`Quarantined N duplicate jar(s)
  for: <names>`), so you can see what's happening instead of just a count.
- **Better in-config docs.** Each popular-plugin toggle's inline comment
  now explains what the plugin actually does, and a section header notes
  that the toggles are global (applied to whichever world is active on
  boot) with a pointer to `PLUGINS.md` for the full command reference.

## 1.8.0

### Changed: per-world settings — every world is now independent

The biggest simplification yet. **Gameplay settings are no longer global
add-on options** — each world owns its own `server.properties`, so you can
have a creative world and a survival world side by side and switching
between them loads each world's real settings. No more "I set creative but
it loads survival because the global option overrides the world."

- The HA **Configuration tab now holds only install/container-level
  options**: EULA, active world, server type/version, RAM + JVM flags,
  RCON password, auto-update, backups, crash-restart, HA integration,
  Bedrock/Geyser, the ghost-session kicker, duplicate-plugin quarantine,
  the plugin list, and log level. That's it.
- **Everything gameplay/world** — gamemode, force-gamemode, difficulty,
  PVP, hardcore, allow-flight, whitelist, spawn protection, view/sim
  distance, world-gen (level name/seed/type, packs, structures, mobs),
  online-mode, secure-profile, resource pack, command blocks, op level,
  connection throttle, idle timeout — is edited from the ingress panel's
  **Server Properties** tab and saved into that world's
  `server.properties`. It persists and is per-world.
- On boot the add-on only enforces the infra keys (RCON/query/ports) and
  **seeds gameplay defaults once**; it never overwrites a world's existing
  values again.
- **Migration is seamless:** your current world keeps its exact settings —
  they're already in its `server.properties`, which the add-on now
  preserves instead of overwriting.

### Removed

- The `allow_cheats` and `initial_ops` options (and the per-boot OP helper).
  Toggle command blocks / op level per-world in the panel, and op players
  from the panel's Players tab — ops persist per-world in `ops.json`.
- The panel's short-lived "write settings back to add-on options" path
  (1.7.0) — no longer needed now that `server.properties` is the per-world
  source of truth.

### Internal

- Geyser "auto" auth-type and the bedrock MOTD now read the active world's
  `server.properties` (not a global env var); backup/restore read its
  `level-name` the same way.
- Tests reworked for the per-world model.

## 1.7.0

A reliability + simplification release focused on the three things that
felt broken: settings that didn't stick, the panel's non-persistent
options, and world switching.

### Fixed: creative (and other gamemodes) finally stick

Setting `gamemode: creative` used to keep loading as survival for anyone
who had already joined — you had to run `/gamemode creative <name>` by
hand every time. Minecraft only applies the `gamemode` property to
*brand-new* players; returning players keep the mode saved in their
player data. The add-on now writes **`force-gamemode`** (new
`force_gamemode` option, default `true`), which puts every player into
the configured gamemode on join. Set `force_gamemode: false` if you want
players to keep whatever mode they last switched to. The panel's live
gamemode change also now runs `gamemode <mode> @a` so everyone online
flips immediately, not just future joiners.

### Fixed: the panel's Server Properties tab is now permanent

Previously every edit in the panel's **Server Properties** tab wrote only
to `server.properties`, which the add-on re-rendered from your
Configuration options on the next restart — so **every panel edit
silently reverted**. Edits now write straight back to the add-on
Configuration options (the single source of truth) via the Supervisor
API, so they persist across restarts *and* apply live. The tab's copy
was updated to say so.

### Fixed: world switching

- **One restart, not three.** Clicking *Switch* used to fire an options
  write, a Supervisor add-on restart, *and* a racing RCON stop — the
  extra restart fought the container teardown and made switching feel
  flaky. It now does exactly one clean Supervisor restart.
- **Correct active-world detection.** `world-manager.sh active` now reads
  the add-on option (what the server actually boots from) before falling
  back to the symlink, fixing a legacy-install case where it always
  reported `default` even after you switched.
- **Per-world create seed honoured.** The seed you type into *Create a
  new world* is no longer discarded on first boot when the global
  `level_seed` option is blank.

### Changed: PaperMC downloads use the new v3 API

PaperMC deprecated its v2 download API in favour of the v3 "fill" API.
Paper/Folia now resolve through `fill.papermc.io/v3` (with sha256
verification and a descriptive User-Agent), falling back to v2 only if v3
is unreachable so downloads can't break during the transition.

### Fixed: clean save on add-on stop

The graceful-shutdown handler looked for a PID file the JVM launcher
never wrote (`server.pid` vs `launcher.pid`), so stopping the add-on
never RCON-saved the world. It now finds the JVM and saves + stops it
cleanly before exit.

### Internal

- CI now shellchecks the `scripts/` directory (previously excluded).
- New tests cover force-gamemode, seed preservation, panel option
  persistence, v3 download resolution, and option-based active-world
  detection.

## 1.6.0

### Added: enable experiments for the latest game rule options

Mojang gates experimental content — and the newest experimental game
rules that come with it — behind named *feature packs* the server has to
enable when a world is first generated. The add-on now exposes this via
two new options that map straight onto the vanilla
`initial-enabled-packs` / `initial-disabled-packs` server properties:

- **`initial_enabled_packs`** (default `vanilla`): comma-separated list of
  feature packs to enable at world creation, e.g.
  `vanilla,minecart_improvements,redstone_experiments`. Always keep
  `vanilla` in the list or the base game pack is disabled.
- **`initial_disabled_packs`** (default empty): packs to force-disable.

Both keys are also editable from the panel's **Server Properties** tab.

> Experiments are baked into a world at **creation** time, so enabling one
> only affects newly generated worlds. To use an experiment on an existing
> save, create a fresh world from the **Worlds** tab with the pack enabled.

## 1.5.8

### Fixed: 1.5.7's nav fix was invisible to users with cached CSS

1.5.7 landed the correct inner-scroll-wrapper layout that solves the
nav-bar-disappears-on-scroll bug — but in the field, users reported
the fix didn't work even after updating. Root cause: `panel/index.html`
referenced `style.css` and `app.js` without any cache-busting query
string, so HA's ingress proxy + the browser's default heuristic kept
serving the **1.5.6** stylesheet (with the still-broken sticky
positioning) until a manual hard refresh.

**Fix:** template the running add-on version into the asset links
on every request:

```html
<link rel="stylesheet" href="style.css?v=1.5.8" />
<script src="app.js?v=1.5.8"></script>
```

`panel/server.py::index` reads `index.html` per request and substitutes
`__VERSION__` placeholders for the live `ADDON_VERSION`. The index
itself is served with `Cache-Control: no-store` so the page can never
be cached with last release's version string baked in. Every future
release now bursts the browser cache automatically — users no longer
need to know to hard-refresh.

### Added: version badge in the footer

The footer now shows `v<version>` (e.g. `v1.5.8`) so users can confirm
at a glance which build they're actually running. If the badge says
1.5.6 after updating to 1.5.8, hit Ctrl/Cmd-Shift-R to force a refresh
(should only be needed once — the cache-buster handles future
upgrades).

### Migration

Restart the add-on. If the footer doesn't show **v1.5.8** after the
restart, hard-refresh the panel once:

- **Desktop:** Ctrl-Shift-R (Win/Linux) or Cmd-Shift-R (Mac).
- **HA Companion (iOS / Android):** pull down to refresh inside the
  panel; if that doesn't help, force-quit the app and reopen.

After this single refresh the cache-buster takes over and every
future update is picked up automatically.

## 1.5.7

### Fixed: nav bar STILL disappeared on Plugins / Server Properties tabs

1.5.6 reinforced `position: sticky` with `flex-shrink: 0` /
`isolation: isolate` / `-webkit-sticky` / `z-index: 100`. Users on HA
Companion **still** reported the nav vanishing when they scrolled into
the **Plugins** and **Server Properties** tabs specifically. After
research into HA's ingress iframe + WKWebView behaviour, the root cause
is a combination of three browser bugs:

- **WebKit bug 154399** — `position: sticky` gets confused when a
  descendant has its own scroll container (`overflow: auto`). Plugins
  and Server Properties have tables that on mobile become
  `display: block; overflow-x: auto`; Console has a `<pre>` with
  `overflow: auto`. The tabs without inner scrollers (Dashboard,
  Players, Backups, Worlds) didn't trigger the bug — that's why this
  was tab-specific.
- **WebKit bug 297779** — iOS 26 broke `position: fixed` inside iframes;
  Safari 26.1 fixed it but **WKWebView (which HA Companion uses) is
  still affected**. Switching to `position: fixed` would have made
  things actively worse.
- **WKWebView's `vh` resolution against the outer window**, not the
  iframe — `body { min-height: 100vh }` desynchronises on tab switches
  / orientation changes, leaving sticky elements computing stale
  thresholds.

**Fix:** abandon both `sticky` and `fixed`. Adopt the "inner scroll
wrapper" pattern instead — `<body>` itself never scrolls, and `<main>`
becomes the single vertical scroll container. The header is then
**statically** placed at the top of a non-scrolling body and literally
cannot scroll off-screen. This side-steps every WebKit positioning bug
class at once.

```css
html, body { height: 100%; overflow: hidden; }
body { display: flex; flex-direction: column; }
.page-header { flex: 0 0 auto; /* static */ }
main {
  flex: 1 1 auto;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  min-height: 0;  /* required so the flex child can shrink */
}
footer { flex: 0 0 auto; }
```

Additional defensive changes:

- `.console` `max-height` now uses `min(70vh, 600px)` instead of `70vh`
  alone — defends against WKWebView's stale-`vh` resolution after
  orientation / URL-bar animations.
- `panel/app.js` resets `main.scrollTop = 0` when switching tabs so
  users land at the top of new tab content (a plain `window.scrollTo`
  wouldn't work under this layout because `<body>` doesn't scroll).

### Migration

Restart the add-on. No config changes. The nav bar stays pinned at
the top regardless of which tab is open or how far it's scrolled —
including on iOS HA Companion and the iOS 26 / WKWebView family of
bugs the previous two attempts couldn't work around.

### References

- [WebKit Bug 154399](https://bugs.webkit.org/show_bug.cgi?id=154399)
  — `position: fixed`/`sticky` buggy with `overflow: auto` inside iframes.
- [WebKit Bug 297779](https://bugs.webkit.org/show_bug.cgi?id=297779)
  — iOS 26 fixed-positioning regression (WKWebView still affected).
- [PierBover/ios-iframe-fix](https://github.com/PierBover/ios-iframe-fix)
  — the wrapper-scrolls pattern this layout adopts.
- [HA frontend #779](https://github.com/home-assistant/frontend/issues/779) /
  [HA core #10772](https://github.com/home-assistant/core/issues/10772)
  — historic context on `panel_iframe` scrolling on iOS.

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

(See 1.5.7 — this didn't fully fix it on Plugins / Server Properties;
the whole sticky-vs-fixed approach was wrong and was replaced with
the inner-scroll-wrapper pattern.)

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
