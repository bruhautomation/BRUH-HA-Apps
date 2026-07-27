# Changelog

All notable changes to **BRUH Claude Terminal**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

> 💡 Prefer a cleaner, categorized view? See the [formatted changelog at bruhautomation.com](https://bruhautomation.com/bruh-claude/changelog/).

## 3.4.0

**New: BRUH Power Tools — 36 registry-management admin services, adapted
from [Spook](https://github.com/frenck/spook) by Franck Nijhof (MIT).**
Claude, automations, and scripts can now reorganize Home Assistant through
safe, supervised service calls instead of hand-editing `/config/.storage`.

- **New `bruh_claude.*` services** (all visible in Developer Tools >
  Actions with field pickers):
  - *Areas*: `create_area`, `delete_area`, `rename_area`,
    `set_area_aliases`, `add_device_to_area`, `remove_device_from_area`,
    `add_entity_to_area`, `remove_entity_from_area`
  - *Floors*: `create_floor`, `delete_floor`, `rename_floor`,
    `add_area_to_floor`, `remove_area_from_floor`
  - *Labels*: `create_label`, `delete_label`, `add_label`, `remove_label`
    (multi-target: entities, devices, and areas in one call)
  - *Entities*: `rename_entity`, `change_entity_id`, `enable_entity`,
    `disable_entity`, `hide_entity`, `unhide_entity`,
    `delete_orphaned_entities` (dry-run by default)
  - *Devices*: `rename_device`, `enable_device`, `disable_device`
    (with Spook's parent-hub cascade)
  - *Integrations*: `enable_integration`, `disable_integration`,
    `reload_integration`
  - *Zones*: `create_zone`, `delete_zone`
  - *Persons*: `add_device_tracker_to_person`,
    `remove_device_tracker_from_person`
  - *Repairs*: `create_repair_issue`, `remove_repair_issue` — surface
    custom, dismissible issues in Settings > System > Repairs
- **Safer than Spook's originals for this use case**: everything is
  admin-gated and namespaced under `bruh_claude.*` (no collision if you
  also run Spook), every referenced id is validated before any change,
  creation services return the new id as response data, and the orphaned
  entity cleanup reports before it deletes. User enable/disable was
  deliberately left out (lockout risk).
- **New MCP tool `get_registry`**: read-only listings of areas, floors,
  labels, devices, entities, and integrations (config entries) with
  exactly the ids the services need — the safe replacement for reading
  `.storage` files.
- **MCP `call_service` gained `return_response`**: routes the call over
  the WebSocket API and returns service response data (works for any HA
  service with a response, e.g. todo lists or calendars, not just the
  new ones).
- The generated `CLAUDE.md` context now teaches Claude the full catalog,
  the `get_registry` → `call_service` workflow, and the cautions
  (dry-run first, `change_entity_id` doesn't rewrite automations,
  confirm before destructive changes).

## 3.3.2

**Fixed: "Failed to authenticate: OAuth session expired and could not be
refreshed" in Assist conversations and insight cards after the 3.3.1
update, while the sidebar terminal kept working.**

- **Root cause.** Before 3.3.1 some launch paths kept a second credential
  file in the container layer (`/home/claude/.claude`). OAuth refresh
  tokens rotate, so only the most recently refreshed copy stays valid.
  3.3.1's credential unification kept the copy already in persistent
  storage — which could be the *dead* lineage — and discarded the fresh
  one, leaving every newly spawned background Claude (Assist worker pool,
  automation/insight tasks) unable to refresh. The long-lived interactive
  terminal session kept working, which made it look random.
- **Salvage now keeps the newer `.credentials.json`** when both a
  container-layer copy and a persistent copy exist (the older one is kept
  next to it as `.credentials.json.stale`, just in case).
- **Auth failures are now detected and actionable.** The Assist worker
  pool and the automation/task listener recognize CLI auth errors,
  recycle pooled workers, and reply with a clear instruction instead of
  the raw error: open BRUH Terminal and run `/login` once — every
  background channel picks the fresh login up automatically on its next
  run. (If you're seeing this error today, that one-time `/login` is the
  fix.)

## 3.3.1

**Fixed: having to log in to Claude again after every add-on update
(#102), and "press c to copy" failing on plain-HTTP setups.**

- **Login now survives add-on updates.** Claude Code's config/credential
  directory is pinned to persistent storage with `CLAUDE_CONFIG_DIR`
  (`/data/home/.claude`) instead of being derived from `HOME` at runtime.
  Any code path that resolved the home directory differently (login
  shells, passwd lookups, tmux respawns) could silently read and write
  credentials in the container layer — which survives plain restarts but
  is wiped by every update, producing the "re-authenticate after each
  update" loop. Belt and suspenders on top:
  - the `claude` user's passwd home entry now points at `/data/home`
    (existing installs are repointed at startup), and any credentials
    found in the old `/home/claude` container-layer home are rescued
    into persistent storage;
  - directory salvage during symlink setup now includes dotfiles —
    previously `.credentials.json` itself was skipped by the glob — and
    never overwrites a newer persistent copy;
  - the last known good `.credentials.json` is kept in
    `/data/.bruh_claude_auth_backup/` and restored automatically if the
    live file vanishes.
- **Startup auth diagnostics fixed**: the health check grepped an empty
  legacy directory for snake_case token keys and warned "OAuth tokens:
  NOT found" even when you were logged in. It now checks the real
  credential file (camelCase keys) and logs its owner/mode/mtime so
  future auth reports are actionable.
- **"Press c to copy" now works over plain HTTP / LAN access.** The
  modern clipboard API only exists in secure contexts (HTTPS), so on
  `http://homeassistant.local:8123` every OSC 52 copy surfaced a
  "Clipboard API unavailable" toast. The terminal now falls back to the
  legacy `document.execCommand('copy')` path (which also covers ingress
  iframe permission denials) before bothering you, keeping the
  "Tap to copy" toast as the last resort.
- **Sidebar naming**: the ingress panel is now titled "BRUH Terminal"
  (was "Terminal") to match the BRUH family branding.

## 3.3.0

**New: long-term home memory & learning, plus one-command login sharing
with other BRUH add-ons.**

- **Memory store** at `/config/.bruh_claude/memory/`: a user-editable
  `memory.md` (preferences, entity nicknames, household patterns, device
  notes), a ≤2 KB `voice.md` distillate spliced into every voice prompt,
  and an append-only `inbox/` of candidate facts. A background
  consolidator merges the inbox into both files with one cheap Haiku pass
  — daily, or early when more than 20 facts are pending.
- **`ha-memory` CLI**: `add`, `list`, `inbox`, `questions`, `answer`,
  `consolidate`, `edit`, and `clear --confirm`.
- **Voice assistants learn**: a new `remember_fact` MCP tool lets agents
  store facts the moment you state them ("actually, we call that lamp the
  beacon"), and finished conversations get a bounded background
  reflection pass that extracts durable facts. Learned knowledge is
  injected into voice prompts, insight jobs (which also see their
  previous report for continuity), and the generated `CLAUDE.md`.
- **New HA services** `bruh_claude.add_memory` and
  `bruh_claude.answer_question` feed the memory store from automations.
- **Kill switches**: new `assist_learning` (reflection + consolidator) and
  `memory_injection` (prompt splicing) options, both on by default, plus
  `memory_max_kb` (default 8) to cap the memory file.
- **`ha-share-login`**: runs `claude setup-token` interactively, captures
  the long-lived token, and writes the shared auth file
  (`/config/.bruh_claude/secrets/claude_auth.json`, 0600) that other BRUH
  add-ons like **BRUH Insights** pick up automatically — one login for
  the whole family. Also `--token`, `--status`, `--revoke`, `--force`.
- **`ha-context-gen` now preserves your notes**: content between
  `<!-- bruh:user-notes:start -->` / `<!-- bruh:user-notes:end -->`
  survives regeneration, and the generated context inlines the learned
  home knowledge.

## 3.2.5

- Renamed the add-on to **BRUH Terminal** (sidebar panel: "Terminal") as part of the
  unified BRUH Apps branding; new "Solid Blocks" icon and logo from the BRUH Automation
  brand system. No functional changes.

## 3.2.4

**Fix: automations calling BRUH Claude fail with an "MCP server unavailable"
error, even though voice/conversation still works.**

Recent Claude Code builds require project-scoped MCP servers (the ones
declared in `/config/.mcp.json`, including this add-on's Home Assistant
server) to be **approved/trusted** before they load. In non-interactive
runs — exactly how the Automation listener invokes Claude for
`bruh_claude.run_task` — an unapproved server is silently skipped, so Claude
has no HA tools and reports the connection as unavailable. Since the add-on
un-pinned Claude Code (3.2.0), updating pulled in a CLI new enough to enforce
this, which is why automations broke after a Home Assistant/add-on update
while the default fast-mode conversation path kept working.

- **The HA MCP server is now explicitly approved for headless runs.** The
  add-on writes `enableAllProjectMcpServers` / `enabledMcpjsonServers` into
  the Claude settings it already manages (`/config/.claude/settings.local.json`
  and the Assist scoping file), the documented way to trust a project
  `.mcp.json` server without the interactive trust dialog. This is separate
  from the existing tool-permission allow-list, which only governs whether an
  already-loaded tool may run unattended.
- **The Automation listener reads Claude's structured result** (`--output-format
  json` → the `.result` field) instead of scraping `--verbose` stdout, so
  diagnostic lines (including any MCP connection notices) can never again be
  returned verbatim as a task result. Non-JSON output still falls back to the
  raw text, so genuine errors keep surfacing.

## 3.2.3

**Fix: thread-safety error logged every time an Insight job completes.**

On HA 2026.7 the log filled with `Detected that custom integration
'bruh_claude' calls async_write_ha_state from a thread other than the event
loop` each time an insight ran. The Insight sensor's dispatcher handler was
an undecorated sync method, so `async_dispatcher_connect` scheduled it as an
executor job — `async_write_ha_state()` then ran off the event loop and
tripped HA's thread-safety guard. The handler is now a `@callback`, so it
runs inline on the loop. Currently an error-level log; upcoming HA releases
turn these off-loop writes into hard failures, so this also prevents a
future break. (No functional change to the sensor's output.)

## 3.2.2

**Compatibility with the latest Home Assistant (Core 2026.7 / Supervisor 2026.04+).**

The app could no longer be **built or updated** on current Home Assistant
installations: Supervisor 2026.04.0 retired the legacy add-on builder, so
`build.yaml` is ignored and the `BUILD_FROM` build argument is no longer
passed. Our Dockerfile started with `FROM ${BUILD_FROM}` and relied on
build.yaml to fill it in — on a current Supervisor that resolves to an
empty base image and the build fails before it starts.

- **The Dockerfile now carries its own default base image**
  (`ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24`, the official
  multi-arch Alpine 3.24 base). Older Supervisors keep overriding it
  per-architecture through `build.yaml`, so nothing changes for them.
- **The volume map uses the current `homeassistant_config` type** instead
  of the legacy `config` alias (dropped from the Supervisor docs), with an
  explicit `path: /config` so every script keeps its long-standing mount
  point. Requires Supervisor 2023.09 or newer — over two years old.
- **Hassio discovery works again on HA 2026.x.** Core removed the old
  `HassioServiceInfo` re-export from `homeassistant.components.hassio`;
  the integration now imports it from its current home
  (`homeassistant.helpers.service_info.hassio`) with a fallback for older
  cores, so the Supervisor discovery payload is parsed instead of being
  silently discarded.
- **`DeviceInfo` is imported from `homeassistant.helpers.device_registry`**
  (its canonical location) across all platforms, ahead of Core removing the
  deprecated `homeassistant.helpers.entity` re-export.
- Everything else was audited against HA Core 2026.7.1 source — the
  conversation entity, chat-log streaming, options flow, repairs flow,
  services, and sensors all use current APIs; no further changes needed.

## 3.2.1

**Branding and documentation polish.**

- **A proper landscape `logo.png`.** The store logo was a byte-identical copy of the square `icon.png`; it's now the BRUH Automation wordmark at Home Assistant's recommended landscape size.
- **A terminal illustration in the README**, so the project leads with a picture of what it does.
- **Documentation overhaul**: a table of contents, a consolidated troubleshooting table, Support / Authors / License sections and a SemVer policy, the `enable_mobile_ui` option documented, and a corrected automation example (the old one pointed at a task path the listener never watched — use the `bruh_claude.run_task` service).

## 3.2.0

**Fix: terminal opens and instantly closes after an update — and Claude Code updates flow again.**

After a Home Assistant or add-on update, the web terminal could open and
vanish in well under a second: the ttyd log showed `process exited with
code 0` the instant you connected, and the startup log read
`Claude Code updated: <ver> -> unknown`.

Root cause: the `@anthropic-ai/claude-code` npm package no longer ships a
pure-JS CLI — it now installs a prebuilt **native** binary (via
`…-linux-*-musl` optional dependencies). Recent builds of that musl binary
need `posix_getdents`, a symbol musl only added in **1.2.6**. The add-on
was built on Alpine 3.19 (musl 1.2.4), so the binary failed to start
(`Error relocating … : posix_getdents: symbol not found`) and the terminal
process died immediately.

The fix:

- **Base image upgraded from Alpine 3.19 to 3.24** (musl 1.2.6), which
  provides the symbol the current Claude Code native binary needs. This
  restores normal Claude Code updates — the add-on tracks the latest
  release again instead of being frozen on an old one.
- **The startup updater now verifies Claude Code actually runs** after
  installing. If a future build ever needs a newer libc than the base image
  provides, the log says so explicitly (with the fix) instead of silently
  leaving a terminal that opens and disappears.
- **You can pin Claude Code** to a specific version with the
  `BRUH_CLAUDE_CODE_VERSION` environment variable (or the Dockerfile's
  `CLAUDE_CODE_VERSION` build arg) if a release ever regresses.

## 3.1.0

**Per-agent service deny-lists — voice agents you can lock down individually.**

Each conversation agent now has a **Blocked services** picker (Add Service
and the agent's Configure dialog). Pick from common high-risk patterns
(lock.unlock, alarm_control_panel.alarm_disarm, homeassistant.restart,
update.install, …) — every service domain on your system is offered as
`domain.*`, and you can type any custom `domain.service` or `domain.*`
pattern. Each agent carries its own list, so a kitchen speaker can be
barred from unlocking doors while your office agent isn't.

Enforcement is real, not just a prompt request: the deny-list is passed to
that agent's MCP server (per-worker env) and checked in `call_service`,
which every device tool (control_light, control_lock, activate_scene,
run_script, reload_config, send_notification, …) routes through — so a
blocked service can't be reached by any tool or phrasing. Empty list =
everything allowed (unchanged default).


**Personalities stop fighting the built-in prompt.**

The voice system prompt used to merge your personality with a base that
asserted its own identity ("You are a Home Assistant voice assistant")
and its own style ("answer in 1-2 short sentences") — two "You are X"
statements average out, which is exactly the watered-down persona effect.

Now identity, tone, and verbosity come from exactly one source: a custom
personality leads with an explicit precedence note, and the operational
block (authorization, tools, area map, timezone, routing rules) is
identity- and style-free. Agents without a personality keep the old
default behavior. The agent config field and DOCS explain the layering,
including the tip to put a length rule inside expansive personas.

Also: the voice deny-list (`assist_tool_access: mcp_only`) now blocks
file READS (Read/Glob/Grep) as well as writes — voice gets HA data
exclusively through MCP tools, so the only thing file access enabled
was reading things like secrets.yaml aloud. Docs updated to state the
boundary precisely.

## 3.0.1

**Fix: blank "Add Service" dialog — plus a much friendlier insight setup.**

- The 3.0.0 config dialog could render completely blank: two translation
  strings contained literal Jinja braces, which break the frontend's
  message-format parser. All translation strings are now brace-free and a
  CI test guards against reintroducing any.
- Menu and dropdown labels are now provided inline (immune to translation
  loading), and template choices describe themselves: "Anomaly watch —
  only problems; says 'All quiet.' otherwise".
- **Template preview**: opening Configure on an insight job pre-fills the
  prompt box with the selected template's full text — read it, tweak it,
  or leave it; what you see is exactly what runs.
- **Run now button** on every insight job's device page for manual firing
  (the `bruh_claude.run_insight` service remains for automations).
- Prompt fields (insight and agent personality) are proper multiline
  editors; step descriptions rewritten to explain the create -> card_yaml
  -> dashboard flow in place.
- **Finding the report**: a job's first successful run now sends a
  one-time notification containing the dashboard card ready to paste;
  the sensor gained a readable `preview` attribute (long blobs sorted
  last), and DOCS explains exactly where the report lives.
- **`get_weather_forecast` MCP tool**: modern HA only exposes forecasts
  via `weather.get_forecasts` with response data (the old `forecast`
  attribute is gone) — fetched over the WebSocket API so "what's the
  weather tomorrow" works reliably by voice.
- **Insight reports to your phone**: each job gets an optional notify
  service; the `bruh_claude_insight_complete` event now carries
  `entity_id` and a `preview` for TTS announcements; `send_prompt` and
  `run_task` accept a `model` override.
- **Local time, not UTC**: the container now adopts HA's configured
  timezone (TZ + tzdata), the voice system prompt names it, and every
  message carries a local-time stamp — agents answer time questions in
  your timezone with zero tool calls. Applies to terminal, voice, and
  automation channels.

## 3.0.0

**The big one: insight jobs, streaming voice, an internal HTTP API with
health monitoring, and voice tool scoping — with the file protocol kept
as a permanent fallback so nothing existing breaks.**

### Insight jobs (proactive Claude)

Add scheduled Claude reports from the integration: **Add Service → Insight
job**. Pick a shipped template (daily briefing, anomaly watch, battery &
maintenance, camera check) or write a custom prompt — custom prompts can
embed HA templating (`{{ states('sensor.x') }}`), rendered before sending.
Schedule by interval and/or daily time, or trigger from automations with
the new `bruh_claude.run_insight` service. Results land on
`sensor.<job>_insight`: state = last successful run, `markdown` attribute =
the report (kept out of the recorder), and a ready-to-paste `card_yaml`
attribute for a dashboard markdown card. Results persist across HA
restarts, errors keep the previous report visible, and a
`bruh_claude_insight_complete` event fires for chaining.

### Streaming voice (HTTP/SSE transport)

The worker pool now serves an internal HTTP API on the hassio network
(token-authenticated via the shared volume). The integration prefers it —
requests arrive instantly (no file polling) and Claude's text **streams
into HA's chat log as it's generated**, so TTS starts speaking at the
first sentence on Assist pipelines that support streaming. Every layer
falls back automatically: no chat-log API → whole-reply; HTTP unreachable
→ file IPC, which both sides keep forever.

### Health monitoring

`binary_sensor.bruh_claude_system_assist_healthy` reports the pool's
health (HTTP `/health` first, heartbeat file fallback) with worker counts
and last-request latency as attributes. `ha-selftest` checks the API, and
run.sh babysits the pool process (auto-restart on exit). The Supervisor
`watchdog` key is deliberately not used — it can't be conditional on the
assist channel being enabled and would restart-loop disabled installs.

### Voice tool scoping (assist_tool_access, default mcp_only)

The assist channel now runs with a deny-list settings file: voice keeps
every MCP device tool but can no longer run shell commands, edit files,
or reach the web. Automations and the terminal keep full access. Set
`assist_tool_access: full` to restore the old behavior.

### Also

- `bruh_claude.run_task` (and insight jobs) accept a `model` override,
  honored by the automation listener.
- Conversation workers stream token-level deltas via
  `--include-partial-messages`, with automatic downgrade on older CLIs.

## 2.5.0

**Claude can now see cameras and answer questions about the past — and
the MCP server got the registry it needed to keep growing safely.**

### New tools

- **`get_camera_snapshot`** — fetches a camera image (downscaled via
  Pillow to keep token cost sane) and returns it as a real MCP image
  block, so Claude can *look*: "what's in the driveway?", "is the garage
  door actually closed?" work by voice, and automations can ask for
  visual checks.
- **`get_history`** — recent state history for an entity (up to 7 days)
  with min/max for numeric sensors, downsampled to stay small. "When did
  the garage last open?", "how warm was it this morning?"
- **`get_statistics`** — long-term statistics (hourly/daily
  mean/min/max) over the WebSocket API, which survives recorder purging:
  "how cold did it get last week?" The assist prompt teaches the voice
  agent when to reach for each.

### MCP server internals: schema-driven dispatch

The hand-written 140-line if/elif router (every tool's arguments
re-listed by hand — a standing drift hazard) is replaced by a registry:
tool name → implementation, with allowed/required arguments derived
from each tool's own inputSchema. Adding a tool is now: function +
schema + one mapping line, and a test enforces that schemas and
implementations never diverge. Implementations are looked up late, so
tests can patch them. `tools/call` responses are built by a single
helper that knows how to emit image content blocks.

## 2.4.1

**Field fixes from the first 2.4.0 logs: oversized area maps lost their
Weather/People sections, and the first request after a restart was cold.**

- 2.4.0 logs showed `AreaMap: 12000 chars` — exactly the truncation cap.
  Large homes overflow it, and Weather/People were appended last, so the
  truncation silently removed exactly the sections voice asks about most.
  **Weather/People now come first** (truncation can only drop areas), the
  cap is raised to 16000, truncation lands on a line boundary instead of
  mid-entity_id, and it's logged to the assist debug log when it happens.
- **The spare worker is now pre-warmed at startup** from the last-used
  agent profile (persisted in `cache/last_profile.json`), so the first
  voice command after an add-on restart no longer pays the cold start
  (~20s observed in the field, since the spare previously only spawned
  after the first request). The area map is refreshed synchronously at
  startup so the pre-warmed spare bakes in the same map the first request
  builds — otherwise the profiles wouldn't match and the spare would
  never be adopted.

## 2.4.0

**Assist fast mode: pre-warmed Claude workers, and a fix for the area map
silently failing.**

Field data from 2.3.0 showed fresh-conversation voice commands taking
14–16s while the identical command on a resumed conversation took 6s —
meaning the model was still spending turns on entity discovery
(`get_areas` / `get_all_states`) instead of acting from the area map, and
weather questions (entities with no area) always paid that tax.

### Area map: version-proof template, weather/people context, visibility

- The map template now uses **pure core Jinja** (namespace + split) instead
  of the `match` select-test, so it renders on any HA version. If the
  render fails, the failure is now **logged** to the assist debug log
  instead of silently falling back to discovery mode.
- The map gains **Weather:** and **People:** sections — weather and person
  entities usually have no area, so "what's the weather" previously always
  needed a discovery turn.
- The system prompt now instructs Claude to act on listed entity_ids in its
  FIRST response and never re-verify them, and to keep spoken replies to
  1–2 short sentences (they're read aloud).
- Every request logs `AreaMap: <n> chars`, and `ha-selftest` gained an
  "Assist area map" section that checks the cache and probes the template
  API so a broken map is impossible to miss.

### Fast mode (assist_fast_mode, default on)

A new worker-pool daemon (`assist-worker-pool.py`) replaces
spawn-per-request for the Assist channel:

- **One live Claude process per active conversation** — follow-up turns
  skip the CLI boot, MCP handshake, and session reload entirely.
- **A pre-warmed spare process** — even brand-new conversations (the
  common voice case) skip the cold start; the spare is respawned in the
  background after being adopted and recycled every 10 minutes so its
  baked-in area map stays fresh.
- Same file IPC, same atomic claim, same response format — the HA
  integration is untouched, and any worker error falls back to a one-shot
  invocation (exactly the classic behavior). Set `assist_fast_mode: false`
  to keep the classic listener.
- Workers are capped (3), idle-reaped (5 min), and age-recycled (30 min);
  Claude session ids are still persisted so context survives pool
  restarts via `--resume`.

## 2.3.0

**Faster conversations, real session memory, and a fix for the
"one answer behind" bug.**

### Fix: stale responses could leave a conversation permanently lagging

Request and response files were both named `{conversation_id}.json` and
reused for every turn. If a response ever landed after the integration
stopped waiting (bridge timeout, or HA cancelling the pipeline when the
Assist dialog closed), the orphaned file was consumed as the answer to the
**next** turn — and from then on every turn received the previous turn's
answer. Concurrent requests for the same conversation collided on the same
files too.

Files are now named by a unique per-request id (the conversation id rides
along inside the payload), listeners discard backlog requests that nobody
is waiting for anymore, claim requests atomically by rename (no
double-processing races), and sweep orphaned files periodically. The
conversation entity also re-raises `asyncio.CancelledError` instead of
swallowing it, and the in-memory history map is bounded (oldest
conversations evicted) instead of growing forever.

### Conversations now resume real Claude Code sessions

The first turn of a conversation starts a Claude session with a generated
`--session-id`; follow-up turns `--resume` it. Claude keeps the full
conversation context server-side — no more replaying the transcript into
every request — which cuts tokens and time-to-first-token and gives the
agent complete (not truncated) memory within a conversation.
`bruh_claude.clear_conversation` clears the session mapping so the next
turn starts fresh. If resume fails or the CLI predates the session flags,
the listener falls back to the old stateless replay automatically.

### Speed: area map in the system prompt, Haiku default, snappier polling

- The assist listener renders an **area → controllable-entities map** via
  the template API, caches it (5-minute stale-while-revalidate), and
  splices it into the system prompt. "Turn off the kitchen lights" no
  longer needs a `get_areas` round-trip — that's a whole model turn
  (several seconds) saved on most voice commands.
- New conversation agents default to **Claude Haiku** (fastest). Existing
  agents keep their configured model; `Default` still inherits the
  terminal's model.
- The bridge polls for responses every **0.1s** instead of 0.5s.
- The deep MCP-config cleanup (greps over `~/.claude.json` and a `find`
  across `~/.claude/projects`) now runs at startup and after detected
  `/api/mcp` errors instead of before **every** request; the hot path keeps
  a single cheap check of `/config/.mcp.json`.
- Fallback history replay is trimmed (6 turns, long messages truncated) so
  long chats don't slow down turn after turn.
- `get_all_states` gained a `name_filter` argument and caps results at 300
  entities — an unfiltered dump of a large install was a huge tool result
  that slowed every turn.

### Fix: automation tasks longer than 120s were lost

The automation listener allows tasks up to 300s, but the integration only
waited 120s — anything longer "timed out" for the user while Claude kept
working, and the result was orphaned. Tasks now default to a 300s wait, and
both listeners derive their claude process limit from the timeout the
integration sends with each request, so results always land inside the
window the bridge is actually polling.

## 2.2.1

**Fix: `ha-selftest` (and other scripts) printed `Permission denied` when
sourcing the env file as the non-root user.**

`/data/.bruh_claude_env` is root-owned `0600` (it holds `SUPERVISOR_TOKEN`).
Scripts guarded the source with `[ -f ]` (exists), so when they ran as the
`claude` user — `ha-selftest`, an interactive shell's `.bashrc` — the file
existed but wasn't readable and `. /data/.bruh_claude_env` printed
`Permission denied`. Harmless (the `claude` user already inherits those vars
from its parent), but noisy.

Changed the guard to `[ -r ]` (readable) everywhere the file is sourced:
`scripts/ha-selftest.sh`, `scripts/claude-session-picker.sh`, the generated
`.bashrc` and `claude-run` wrapper in `run.sh`, and both integration
listeners. For root contexts `-r` behaves exactly like `-f` (root can read
the file, so it still sources); for the `claude` user it cleanly skips the
unreadable file instead of erroring. The file's `0600` perms are left
unchanged — `SUPERVISOR_TOKEN` stays off-limits to other users.

## 2.2.0

**Area-aware MCP, an in-situ self-test, and a round of cleanup.**

### MCP: area/room awareness (`get_areas`)

The MCP server controlled devices well but had no way to answer "what's in
the bedroom?" — the HA REST API doesn't expose the area/entity registry
(it lives behind the WebSocket API), and the old `get_device_registry`
tool just counted entities per domain (its name oversold it).

2.2.0 adds **`get_areas`**, which lists every area and the entity_ids
assigned to it. It's implemented through the template engine (`areas()` /
`area_name()` / `area_entities()`), reusing the proven `/api/template`
path — no new transport, no WebSocket client. This gives the Assist agent
what it needs to turn "turn off the kitchen lights" into concrete
entity_ids; the Assist system prompt now points at it for room requests.

`get_device_registry`'s description was corrected to say what it actually
returns (a per-domain entity tally, not the HA device registry).

### New: `ha-selftest` in-situ diagnostic

A new `ha-selftest` CLI (run it inside the add-on terminal) verifies the
whole chain end-to-end and prints PASS/FAIL with hints:

- `SUPERVISOR_TOKEN` present and the HA REST API reachable,
- `.mcp.json` present and free of stale `/api/mcp` entries, tool allowlist
  present,
- the **MCP server driven over stdio JSON-RPC the same way Claude Code
  drives it** — initialize handshake, `tools/list` (count + `get_areas`
  registered), and live `tools/call` for `get_ha_config`,
  `get_all_states`, and `get_areas`,
- the custom integration deployed (with its version) and whether a restart
  is pending,
- the Assist/automation listeners running,
- Claude login status and whether the usage sensors have data.

This is the fastest way to find what needs fixing on a real install.

### Cleanup

- Removed the orphaned `scripts/token-stats-tracker.py` — it hasn't been
  launched since the token sensors were dropped in 1.9.0 (the usage-limit
  sensors are fed by `usage-limits-tracker.py`).
- `bruh_claude.clear_conversation` now just clears the bridge's in-memory
  history (which is the only place conversation context lives — the
  listeners are stateless). Removed the `clear_sessions/` marker file it
  used to write, which nothing ever consumed, plus the now-unused helper
  and the startup `mkdir`.
- `__init__.py`: the `bruh_claude_restart_required` event listener is now
  wrapped in `entry.async_on_unload`, so it no longer accumulates a new
  listener on every options change/reload; and the domain services are
  torn down when the last config entry is removed (they used to linger and
  raise "not configured" if called).
- Refreshed `CLAUDE.md` and `DOCS.md`, which still described the removed
  token-usage sensors and the orphaned tracker.

### Tests

`tests/test_mcp_server.py` adds a `TestGetAreas` suite (list/string/error/
dispatch paths) and pins `get_areas` into the canonical tool set. Full
non-Minecraft suite green; `ha-selftest.sh` passes `shellcheck` at
error level and `bash -n`.

## 2.1.0

**Mobile swipe-to-scroll + throttled desktop wheel. The scroll saga,
finally answered at the right layer.**

For 15 releases (1.17.1 → 2.0.2) "scroll up to see past chat" was the
white whale. This release fixes it on both PC and mobile by re-using the
one mechanism that was actually proven to work — and never overshooting.

### How scrolling actually works (the model that survived)

Claude Code's TUI draws its conversation in the terminal's **alternate
screen**, which by spec has **no scrollback** — xterm.js never captures
it, and tmux's copy mode only shows the *normal-screen* (pre-Claude)
history. This is now confirmed by Claude Code's own docs ("Claude Code
uses the alternate screen buffer, which bypasses terminal scrollback
entirely"). So the **only** way to see past chat is Claude Code's own
internal pager, bound to **PgUp / PgDn** (it prints "use PgUp/PgDn to
scroll"). Nothing in the `claude-code → tmux → ttyd → xterm.js` stack
can scroll it *except* sending those keys.

1.18.10 used exactly that for the **desktop wheel** (intercept the wheel,
`sendInput('\x1b[5~' / '\x1b[6~')`). That part worked. Two gaps remained:

1. **Mobile had no swipe scroll at all.** Every touch attempt in
   1.18.3–1.18.8 let *xterm* interpret the gesture — a synthetic
   `WheelEvent` (which xterm turned into ↑/↓ arrows → "every swipe moves
   the cursor"), or `tmux set -g mouse on` (which broke drag-to-select /
   OAuth-URL copy), or the `📜 Hist` button (which showed the wrong,
   normal-screen history). 1.18.9 gave up and made swipes a no-op, so
   the only way to scroll on a phone was tapping the PgUp/PgDn toolbar
   buttons one page at a time. That's the "very difficult to scroll up."

2. **The desktop wheel overshot.** It sent one *full page* per raw wheel
   event. A notched mouse is fine (≈1 event/notch), but a trackpad or
   smooth-scroll mouse fires dozens of events per gesture → dozens of
   PgUp → instantly at the top, uncontrollable. That's the "difficult to
   scroll on PC."

### The fix

`ttyd-assets/inject.html`:

- **New touch swipe handler** (`setupTouchScroll`). A one-finger
  vertical swipe inside the terminal is translated **directly** into
  `sendInput(PgUp/PgDn)` — the touch analog of the desktop wheel
  handler. It never dispatches a synthetic `WheelEvent` and never
  enables tmux mouse tracking, which is precisely why it dodges every
  prior failure mode:
  - no arrow-key cursor movement (xterm never sees the gesture),
  - native long-press text selection still works (mouse mode stays off
    — **OAuth-URL copy intact**),
  - the HA ingress panel doesn't scroll away (`body { touch-action:
    none }` still blocks delegation to the parent frame).
  It stays out of the way of taps (focus/keyboard) and selection: a
  gesture only latches after >10 px of *mostly-vertical* travel and
  never while a selection is active, and it defers to native scrolling
  in normal-screen (bash) mode.

- **Shared throttled accumulator** (`pageScroll`). Both wheel and touch
  now feed a pixel accumulator that emits one PgUp/PgDn per
  `SCROLL_PAGE_PX` (120 px) of travel, with deltaMode normalisation for
  Firefox line/page wheels and a per-call cap. A mouse notch still ≈ one
  page (the 1.18.10 feel is preserved), but a trackpad fling or a fast
  swipe pages proportionally instead of teleporting to the top.

This is mode-independent: PgUp/PgDn scroll Claude Code's chat in both the
default and the new `/tui fullscreen` renderer, so the fix holds whatever
mode you run.

### "Update everything" notes

- **Claude Code CLI** is already pinned to *latest* — the image installs
  it via npm and `run.sh`'s `update_claude_code()` re-pulls the newest
  `@anthropic-ai/claude-code` on every startup (with retries). No change
  needed; restart the add-on to pick up the current release.
- **Base image / ttyd / xterm.js** stay on the HA Alpine 3.19 base this
  release. Bumping the base (newer ttyd + xterm.js) is worthwhile but
  CI only *lints* the Dockerfile (hadolint) — it doesn't build the
  image — so a base bump can't be validated here without shipping it
  blind to every user. It's deferred to a separate, build-tested PR.
  Note it would not change the scroll model: alt-screen has no
  scrollback in any xterm.js version, so PgUp/PgDn forwarding is still
  the lever.
- Tip: `/tui fullscreen` (or `CLAUDE_CODE_NO_FLICKER=1`) enables Claude
  Code's flicker-free renderer, which is nicer under tmux and adds
  native mouse scroll/selection on desktop. It's left opt-in because it
  turns on terminal mouse tracking, the same thing that historically
  interfered with touch text-selection.

### Tests

`tests/test_inject_html.py`: reworked the old `setupScrollForwarder`
ban into `test_no_synthetic_wheel_scroll_forwarder` (still forbids the
broken mechanism — the old name and any `new WheelEvent` dispatch — but
allows a touchmove handler), and added `test_touch_scroll_sends_pgup_pgdn`
and `test_scroll_paging_is_throttled`. Full suite green; the inline
script still passes `node --check`.

## 2.0.2

**Revert the 2.0.x custom chat UI. Back to native Claude Code in ttyd.**

The 2.0.0 chat UI experiment failed on the substance: the headless input
format I built against (`{"type":"user","content":"..."}`) is wrong —
claude-code's stream-json input actually requires the full Anthropic
Message shape (`{"type":"user","message":{"role":"user","content":"..."}}`),
which surfaced in production as `$.message.role` errors on the very first
turn and a dead session before the user could even retry. Combined with
the unstyled SPA on first load and the WS lifecycle complexity, the
custom UI was a worse experience than the terminal it tried to replace.

Even if the input format were fixed, the deeper problem is that the
custom UI is a worse fit for what users actually want: the native
Claude Code experience, the way it works on every other terminal. The
ttyd surface (with the 1.18.10 mobile shim) was already that.

### What's removed

- `bruh-claude-terminal/chat-server/` (FastAPI app, claude subprocess
  manager) — deleted in full.
- `bruh-claude-terminal/chat-ui/` (Astro + Preact SPA) — deleted in full.
- Dockerfile: the multi-stage `node:20-alpine` chat-ui builder, the
  `fastapi==0.115.5 uvicorn==0.32.1` pip install, the `/opt/chat-server/`
  + `/opt/chat-ui-dist/` mkdir/COPY steps. Image build no longer depends
  on npm registry availability.
- `config.yaml`: `enable_chat_ui` and `chat_ui_permission_mode` options
  (and their schema entries) — gone.
- `run.sh`: the `start_chat_server` function and the `enable_chat_ui`
  branch in `main()`. `main()` now calls `start_web_terminal` directly,
  same as 1.18.x and earlier.
- `tests/test_chat_server.py` and `fastapi` from
  `tests/requirements-dev.txt`.
- `CLAUDE.md` chat-server/chat-ui references.

### What's kept

- All 1.18.10 ttyd + xterm.js + inject.html mobile UI work — that's the
  surface users get back.
- The HA MCP server, custom integration, Assist/Automation listeners,
  auto-backup, context generation, token-stats tracker — all untouched
  by both the 2.0.x add and this revert.
- **The `version-bump` CI guard introduced in 2.0.1.** That infra is
  unrelated to the chat UI and prevents the exact "fix shipped without
  version bump" failure mode that left users stuck on the broken 2.0.0
  for hours.
- `.github/scripts/check-version-bump.sh` and its 10 unit tests.

### Migration

- Existing config doesn't need changes. `enable_chat_ui` and
  `chat_ui_permission_mode` were defaulted off; removing them is a
  no-op for the 2.0.1 default config.
- Users who flipped `enable_chat_ui: true` and saved it: the option no
  longer exists. HA will warn on schema validation; remove the key from
  the add-on options panel.
- Anyone who authenticated via the chat UI session at
  `~/.claude/projects/<encoded-cwd>/<chat-ui-session-uuid>.jsonl` keeps
  that session JSONL on disk; it's just not reachable through the new
  ingress surface. Use the terminal's `/resume` or the session picker
  to access it.

## 2.0.1

**Chat UI asset URLs + CI version-bump guard.** Two unrelated fixes that
went out together because they were caught in the same release cycle.

### Chat UI: SPA asset URLs now work inside HA ingress (#103)

2.0.0 shipped the chat UI but it loaded as unstyled DOM stuck on
"connecting…" forever. Astro emits absolute asset references in the SPA
HTML:

```html
<link rel="stylesheet" href="/assets/index.HASH.css">
<astro-island component-url="/assets/Chat.HASH.js"
              renderer-url="/assets/client.HASH.js" ...>
```

Inside HA's ingress iframe the browser is at
`/api/hassio_ingress/<token>/` but resolves those absolute paths against
the HA host root, so every asset 404s before reaching the add-on. CSS
doesn't load → unstyled DOM. JS doesn't load → no hydration → WSClient
never starts → stuck "connecting…".

The fix: FastAPI reads HA's `X-Ingress-Path` header on each request and
rewrites `"/assets/` and `"/_astro/` prefixes in the served HTML to
include it. Direct-port access (no ingress) has no header → no rewrite
→ absolute URLs already work because they hit the same FastAPI mount.

Five unit tests pin the rewrite against the actual HTML fragment Astro
emits so a future SPA build change surfaces here instead of as a black
page in production.

### CI: enforce version bumps on addon changes

2.0.0 shipped chat-UI code that 2.0.1 fixes. The fix sat on `main` for
a while invisible to users — Home Assistant only pulls a new add-on
image when the version in `config.yaml` changes, and we'd merged the
fix without bumping it.

New CI job `version-bump`: on every PR, diff the addon directory
against the PR base. If any version-relevant file changed (anything
except `CHANGELOG.md` / `README.md` / `DOCS.md`) and `config.yaml`
version is unchanged from base, fail the build with a clear error
pointing at the file to edit.

The check is factored into `.github/scripts/check-version-bump.sh`
with a Python test suite that spins up tiny temp git repos to verify
each branch of the logic. Runs against both `bruh-claude-terminal`
and `bruh-minecraft-server`.

## 2.0.0

**New chat UI surface (opt-in). The 2.0 milestone reframes the addon from
"Claude Code in a web terminal" to "Claude Code in your home, surface of
your choice."**

The 1.18.x line spent four releases trying to make Claude Code's TUI work
inside a browser: OSC 52 interception, wheel→PgUp/PgDn translation, iOS
dictation diff-fix, keyboard avoidance inside the ingress iframe, mobile
toolbar, body-box shrinkage to drive PTY winsize. Each fix sat on top of
the prior one; the structural problem — Claude Code runs in xterm's
alt-screen, which has no scrollback by spec — could not be solved at the
inject.html layer.

2.0.0 stops fighting that boundary. When `enable_chat_ui: true` is set, the
ingress panel is served by a new FastAPI app (`/opt/chat-server/app.py`)
that spawns `claude` in headless streaming mode and bridges its NDJSON event
stream to a Preact SPA over a single WebSocket. The chat surface is plain
DOM: native scroll, native selection, native clipboard, real `<textarea>`
keyboard avoidance. The bug class the previous releases were chasing
disappears at the layer change.

Default is **off**. Existing users keep ttyd + xterm.js + the 1.18.10
mobile shim. Opt in via the add-on options panel; the legacy terminal stays
available by flipping the flag back off.

### Why 2.0 (not 1.19)

The on-disk runtime is backwards-compatible — flag default off = byte-for-
byte 1.18.10 behaviour, no migration needed. We chose `2.0.0` because the
addon now ships **two distinct UX surfaces** sharing one runtime, and that
identity shift is the headline. Functional compatibility is preserved.

### New components

- `chat-server/` — FastAPI + uvicorn. `app.py` serves the static bundle and
  hosts `/ws/chat`. `claude_session.py` manages one claude subprocess per
  WS connection, launched with
  `claude -p --output-format stream-json --input-format stream-json
  --session-id <uuid> --verbose --include-partial-messages
  --replay-user-messages --permission-mode <mode>`.
- `chat-ui/` — Astro + Preact static bundle. Reducer over NDJSON wire
  events produces a flat `Turn[]` model the renderer maps over. Streaming
  `text_delta` events accumulate into the last text block of the active
  assistant turn; the canonical `assistant` event canonicalises content at
  end of turn; `tool_result` attaches to the matching `tool_use`. Code
  fences get a "Copy" button.
- Multi-stage Dockerfile build: `node:20-alpine` compiles the SPA, the
  runtime stage copies `dist/` into `/opt/chat-ui-dist`.

### New options

- `enable_chat_ui: bool` (default `false`) — flips the ingress surface.
- `chat_ui_permission_mode: default|acceptEdits|plan|bypassPermissions`
  (default `acceptEdits`) — propagated to `--permission-mode` on every
  subprocess launch. Background listeners' pre-grants in
  `/config/.claude/settings.local.json` apply as usual.

### What the chat UI does NOT do in 2.0.0

- No interactive permission-prompt UI yet. Tools are either pre-granted via
  `settings.local.json` + `chat_ui_permission_mode`, or refused by claude.
- No session-history sidebar yet (one session per WS; a new WS starts a
  new session with a fresh UUID).
- No "Shell" tab yet. Power users who want raw terminal access disable the
  flag and get the unchanged ttyd panel.
- No slash-command picker, `@file` mention completion, or voice input in
  the composer. They'll come in 1.19.x once the architecture proves itself
  on real hardware.

### Migration notes

- `version` bumped to 2.0.0 in `config.yaml` and `manifest.json`.
- The mobile inject.html layer is untouched — when `enable_chat_ui: false`
  (the default) the runtime is byte-for-byte the 1.18.10 ttyd experience.
- New Python deps in the runtime image: `fastapi==0.115.5`,
  `uvicorn==0.32.1`. **Soft-failed at install time** — if pip can't fetch
  them the addon still builds; the runtime falls back to ttyd.
- New Node deps (build-time only): `astro@^5.0.5`, `@astrojs/preact@^4.0.1`,
  `preact@^10.25.1`. **Soft-failed at build time** in a multi-stage Docker
  builder — if npm install or `npm run build` fails the addon image still
  ships with an empty `dist/`; `start_chat_server` detects the missing
  bundle and falls back to ttyd. The default-off install is unaffected by
  npm registry availability.

## 1.18.10

Four user-reported issues in one release, plus tests for each:

1. **"Press c to copy" silently dropped the copy** (OSC 52 not wired)
2. **Mouse-wheel scrolled cursor instead of chat** in Claude Code
3. **No way to scroll chat history on mobile** at all
4. **White cutout for the keyboard at page load** (panel shrank before
   the user tapped to focus)

### 1. OSC 52 — Claude Code's "press c to copy" silently dropped the copy

When Claude Code prints a URL or token and prompts the user with
"press c to copy", pressing `c` did nothing visible — the URL was
not in the system clipboard. This came up most painfully during
OAuth, when the URL is the one piece of text you actually need
out of the terminal.

Claude Code copies via OSC 52 — the standard terminal-clipboard
escape sequence:

```
ESC ] 52 ; <targets> ; <base64-encoded-text> BEL
```

The chain looks like:

```
claude-code  →  prints OSC 52
   tmux      →  set -g set-clipboard on (already in tmux.conf)
                forwards OSC 52 to the outer terminal
   ttyd      →  passes the bytes through to the WebSocket
   xterm.js  →  v5 supports OSC 52, BUT only when constructed with
                `allowProposedApi: true`. ttyd doesn't enable that
                option, so xterm silently ignores the sequence and
                nothing reaches `navigator.clipboard`.
```

The fix is in the JS layer; tmux + ttyd were already passing the
bytes correctly.

### Fix

`ttyd-assets/inject.html` now intercepts OSC 52 from the WebSocket
stream itself and calls `navigator.clipboard.writeText()`:

1. The WebSocket constructor wrap (already in place since 1.17.1
   for stdin) now also attaches a `message` listener that watches
   for `ESC ]52;<targets>;<base64> BEL` (or `... ESC \`) framings
   in incoming PTY output.
2. A small rolling buffer stitches sequences that straddle frame
   boundaries (uncommon — OSC 52 payloads are usually short
   enough to fit in one ttyd flush — but cheap insurance).
3. The base64 payload is decoded as UTF-8 and handed to
   `navigator.clipboard.writeText()`.
4. On iOS / WKWebView, `clipboard.writeText` requires "transient
   user activation" — which the keypress that triggered Claude
   Code's `c` handler already provides for ~5 seconds. So the
   write succeeds in the common case (user pressed `c` themselves;
   OSC 52 echoes back within a few ms).
5. On rejection (no transient activation, no Clipboard API,
   permission denied, etc.) we surface a "Tap to copy" toast.
   Tapping the toast retries the write from the tap's own user-
   gesture context — works as a manual escape hatch.
6. Spec-mandated query payloads (`ESC ]52;c;? BEL` — application
   asks the terminal what's on the clipboard) are recognised and
   skipped. Browsers don't allow page → clipboard READS without
   explicit permission and a user gesture, so we can't satisfy
   them, and a `?` payload was previously feeding `atob('?')`
   producing garbage.

The OSC 52 handler doesn't `stopPropagation` — xterm still
receives every PTY output frame and renders normally. We only
*also* peek at the bytes for clipboard sequences.

### What this fixes besides "press c"

Anything that uses OSC 52: the same code path will now work for
`tmux save-buffer`, vim's `+` register clipboard yanks, `printf
'\\033]52;c;%s\\007' "$(echo hi | base64)"` from the shell, etc.
All of them used to silently drop the bytes.

### New tests

`tests/test_inject_html.py` gains 8 new structural assertions:

- The captured WebSocket has a `message` listener (without it,
  no OSC 52 ever gets seen).
- The literal `'\\x1b]52;'` start marker is present (catches a
  refactor that accidentally widens the OSC matching to other
  numeric codes).
- Both BEL (`\\x07`) and ST (`\\x1b\\\\`) terminators are present
  — Claude Code emits BEL but other clients use ST.
- `navigator.clipboard.writeText` is actually called.
- `atob(` is present (base64 decode).
- `OSC_BUFFER_MAX` cap exists (bounded memory under a misbehaving
  PTY stream).
- The `?` query payload is checked for and skipped (`atob('?')`
  produces garbage otherwise).
- A user-facing failure path exists (`pendingClipboardText` +
  `bruh-toast`) so a denied write doesn't fail silently.

### 2. Mouse-wheel scrolls Claude Code chat instead of moving the cursor

xterm.js's default behaviour for mouse-wheel events in alternate-
screen mode is to translate them to `↑ / ↓` arrow key escape
sequences and send those to the application. Claude Code's TUI
interprets arrow keys as "move cursor in input box" and helpfully
prints a banner explaining the mismatch:

```
Scroll wheel is sending arrow keys · use PgUp/PgDn to scroll
```

`PgUp / PgDn` ARE bound to chat-history scrolling in Claude Code,
but xterm never sends those — it sends `↑ / ↓`.

`ttyd-assets/inject.html` now has a document-level **capture-phase**
`wheel` listener that fires *before* xterm.js's own bubble-phase
wheel handler:

```js
function onWheel(e) {
  if (!e.deltaY) return;
  // …only intercept inside the terminal, not the toolbar…
  var vp = document.querySelector('.xterm-viewport');
  if (vp && vp.scrollHeight > vp.clientHeight + 1) {
    // Normal-screen mode has real scrollback — let xterm handle it.
    return;
  }
  // Alt-screen mode: send PgUp / PgDn instead of letting xterm
  // translate to ↑ / ↓.
  sendInput(e.deltaY < 0 ? '\x1b[5~' : '\x1b[6~');
  e.preventDefault();
  e.stopPropagation();
}
document.addEventListener('wheel', onWheel, { passive: false, capture: true });
```

In normal-screen mode (bash prompt with output) we step aside and
let xterm's native wheel handler scroll the real xterm scrollback —
that path is correct there and we don't want to override it.

### 3. Mobile users had no way to scroll chat history

Mobile users can't produce a wheel event from their finger
(`touch-action: none` blocks native scroll-pan, and the
`setupScrollForwarder` that synthesised wheel events from touchmove
was removed in 1.18.9 because it produced the "every swipe moves
the cursor" symptom). With no wheel and no synthetic gesture, there
was no way at all to scroll back through Claude Code chat on touch.

1.18.10 adds **`PgUp` / `PgDn` toolbar buttons** between the arrow
keys and the `^C/^D/^L/^U` group:

```
ESC · ▾ Kbd · Tab · ⇧Tab · ↑ ↓ ← →  ·  PgUp PgDn  ·  ^C ^D ^L ^U  ·  / @ # ! |  ·  Paste  ·  ×
```

Tapping `PgUp` sends `\x1b[5~`, tapping `PgDn` sends `\x1b[6~`.
Same escape sequences Claude Code's "use PgUp/PgDn to scroll" hint
suggests; same code path as the desktop wheel handler above.

### 4. White cutout for the keyboard at first load

When the panel first loaded on mobile (no tap yet, keyboard not
deployed), the bottom of the panel had a white space where the
keyboard would be. Cause: `computeGap()` returned a non-zero gap
based on the parent's `visualViewport` — which on iOS reports a
small offset at page load for the status bar / notch safe-area
inset. Our `MIN_KB_GAP = 40` threshold treated that ~44 px offset
as "keyboard up", body shrank, the area below body was the page
background colour (white).

1.18.10 gates **all** gap detection on the xterm helper-textarea
having focus:

```js
function computeGap() {
  if (viewportShrunkForKeyboard()) return 0;
  // 1.18.10: no focus = no keyboard = no shrink.
  if (!taFocused) return 0;
  // …rest of the parent-VV / own-VV / phone heuristic chain…
}
```

`taFocused` is already set/cleared by the existing
`focusin` / `focusout` listeners on `xterm-helper-textarea`, so
the only thing changed here is the early return. After the user
taps to focus, the keyboard-detection chain runs as before.

### New tests (8 added on top of 1.18.9's 21 + the OSC 52 batch)

`tests/test_inject_html.py` is now **37 tests**, covering:

- All 1.18.9 structural assertions (CSS / JS syntax / canonical
  toolbar / no-Hist / no-setupScrollForwarder etc.).
- The 8 OSC 52 assertions from earlier in this changelog.
- **`test_toolbar_canonical_buttons`** — pins the new
  ESC / ▾ Kbd / Tab / ⇧Tab / ↑↓←→ / **PgUp / PgDn** / ^C^D^L^U /
  `/@#!|` / Paste / × ordering exactly.
- **`test_toolbar_has_pgup_pgdn_buttons`** + **`test_keys_map_has_pgup_pgdn`**
  — `pgup` / `pgdn` are in `spec` AND in `KEYS` with the canonical
  `\x1b[5~` / `\x1b[6~` sequences (catches a typo'd CSI).
- **`test_wheel_handler_attached`** — a document-level `wheel`
  listener exists.
- **`test_wheel_handler_uses_capture_phase`** — registered with
  `capture: true` (otherwise xterm sees the event first and we
  can't preventDefault meaningfully).
- **`test_wheel_handler_sends_pgup_pgdn`** + **`test_wheel_handler_steps_aside_when_xterm_has_scrollback`**
  — the handler dispatches the right escape sequences AND yields
  to xterm in normal-screen mode.
- **`test_compute_gap_gates_on_focus`** — `computeGap()` has the
  `if (!taFocused) return 0;` early-return at the top (regression
  test for the white-cutout-at-load bug).

`node --check` on the extracted script: still clean. Full
`pytest tests/` run: green except for one unrelated network-dependent
Minecraft test that flakes on `api.geysermc.org` SSL timeouts.

## 1.18.9

### Refactor: mobile UI simplification + structural tests

Five releases (1.18.3 → 1.18.8) tried to make swipe gestures and the
`📜 Hist` button scroll through Claude Code's chat history. **None of
them worked**, and each one left a subtly broken UX behind: swipes
sending arrow keys, the keyboard covering the input, drag-to-select
breaking during OAuth, the Hist button entering a copy mode that
showed the wrong content. This release cuts that whole feature back
to what's actually achievable and adds structural tests so the
working parts can't silently regress again.

### What's actually possible (and what isn't)

Claude Code's TUI runs in xterm's **alternate-screen** mode. By
spec:

- xterm.js does NOT add alt-screen content to its scrollback buffer.
  So `xterm-viewport.scrollHeight === xterm-viewport.clientHeight` —
  there is literally nothing for xterm to scroll.
- tmux DOES capture every printed cell into its per-pane history,
  but its copy mode only exposes the *normal-screen* portion of that
  history (pre-Claude-Code bash output) — Claude Code's chat drawn
  in alt-screen is never visible there.

So **no surface anywhere on the** `claude-code → tmux → ttyd →
xterm.js` **stack has Claude Code's past chat preserved in a
scrollable form**. The JS / CSS layer can't conjure scrollback
that doesn't exist downstream. If chat history scrolling is ever
needed, it has to come from claude-code itself (a slash command, a
paged history view) — not from BRUH.

### Removed

- **`📜 Hist` toolbar button** that sent `Ctrl+B [` to enter tmux
  copy mode. tmux does enter copy mode, but the user sees
  pre-Claude-Code bash output, not Claude Code's chat. The toolbar
  ↑↓ buttons in that state scroll bash output rather than what the
  user expected, which they (rightly) reported as confusing.
- **`setupScrollForwarder`** — the document-level touchmove handler
  that dispatched synthetic `WheelEvent`s on `.terminal`. With tmux
  mouse mode off (the 1.18.8 default, see below), those wheel
  events translated to ↑/↓ key escape sequences in alt-screen mode,
  fed straight into Claude Code's input field — the "every swipe
  moves the cursor" symptom.

### What's kept

- The full toolbar (ESC, ▾ Kbd, Tab, ⇧Tab, ↑↓←→, ^C/^D/^L/^U,
  `/`/`@`/`#`/`!`/`|`, Paste, ×) — every button has an unambiguous
  effect, no dependency on hidden mode state.
- The 1.18.6 body-shrink-via-height fix that makes the input row
  visible when the keyboard opens (xterm.fit → ttyd → SIGWINCH →
  tmux → claude-code chain). Confirmed working.
- The 1.18.5 phone-only keyboard-height heuristic with the 1.18.5
  `topVVResponsive` latch for the iOS-keyboard-dismiss-button case.
- The 1.18.0 iOS dictation diff-fix (WebKit bug 261764).
- `body { touch-action: none }` so swipes can't leak to the HA
  panel — but no JS gesture handler. Body's box absorbs the
  gesture, end of story.
- tmux mouse mode stays gated off under ttyd (`set -g mouse on`
  breaks native drag-to-select on touch, broke OAuth in 1.18.7).
  Native iOS text selection works.

### Touch behaviour, summarised

| Gesture                       | Effect                                |
|-------------------------------|---------------------------------------|
| Tap inside the terminal       | Focus textarea, open soft keyboard    |
| Tap toolbar key               | Send key, keep keyboard up            |
| Tap `▾ Kbd`                   | Blur textarea, close keyboard         |
| Long-press + drag             | Native iOS text selection             |
| Two-finger tap / pinch        | Blocked (terminal doesn't pinch-zoom) |
| Swipe up / down in terminal   | Nothing (no scrollback to scroll)     |
| Real keyboard: Shift+PageUp   | xterm normal-screen scrollback        |

### New tests

Two new test modules under `tests/`:

- **`test_inject_html.py`** (21 tests): asserts inject.html's CSS
  contains the required selectors, body shrinks via `height:
  calc(100% - var(...))` (NOT padding-bottom — the 1.18.6 ttyd
  container resize gotcha), `body { touch-action: none }` is
  present (1.18.3 parent-scroll leak block), `html.bruh-is-touch`
  uses `overflow: hidden` instead of `position: fixed` (1.18.2
  WebView consistency), `.bruh-key { touch-action: manipulation }`
  is present (1.18.2 iOS 300 ms tap delay), the JS parses cleanly
  under `node --check`, the WebSocket wrap and iOS dictation diff-
  fix are still in place, the toolbar's `spec` array matches the
  canonical ordered list (and explicitly does NOT contain `hist`
  or `setupScrollForwarder` — regression test for 1.18.9's
  removals), and every toolbar button has either a `KEYS` entry or
  a `handleKey()` branch (so silent no-op buttons fail CI).

- **`test_build_mobile_index.py`** (8 tests): the splice logic in
  `build-mobile-index.py` is extracted into a pure
  `splice_inject_into_html(html, snippet)` function and tested
  directly — happy path, missing `</head>` raises `SpliceError`
  (instead of silently writing a corrupt index), `rfind` is used so
  a stray `</head>` inside an inline string literal in ttyd's
  bundle doesn't divert the splice, casing is preserved, error
  preview is bounded so corrupt input doesn't dump a megabyte into
  the addon log, and a smoke test with the real inject.html merged
  into a plausible ttyd HTML shape verifies our `<script>` ends up
  before ttyd's inline bundle in document order.

Both files are picked up automatically by the existing
`pytest tests/ -q` step in `.github/workflows/ci.yml`. Total: **29
new tests, all green**, plus the existing 600+ project tests still
passing.

## 1.18.8

### Fixed: 1.18.7's `mouse on` broke text selection during OAuth

1.18.7 turned on `set -g mouse on` in tmux to make wheel events
route to copy mode (so the user could scroll Claude Code chat
history). That worked, but it also broke **drag-to-select text**
on iOS HA Companion app — which the user discovered while trying
to copy an OAuth URL out of Claude Code.

### Why mouse mode and text selection are incompatible

Enabling `set -g mouse on` makes tmux ask xterm.js (via DECSET
1000 / 1002 / 1006) to forward every mouse event — including
drags — to the PTY as escape sequences. xterm.js disables its
native text-selection handling whenever mouse tracking is on
(mouse events belong to the application now, not to the user).
On desktop the user can hold **Shift** while dragging to bypass
that and use native selection. On mobile there's no shift key,
so dragging produces a momentary "flash" (tmux enters copy mode
and finishes immediately via the default
`MouseDragEnd1Pane → copy-selection-and-cancel` binding) but
nothing reaches the system clipboard.

The trade-off is fundamental at the xterm.js layer:

- Mouse tracking **on**: wheel-driven copy-mode scrolling works
  on touch, native text selection broken on touch.
- Mouse tracking **off**: native text selection works on touch,
  wheel events fall back to xterm's arrow-key escape sequences
  (which Claude Code interprets as "move cursor in input box",
  not as "scroll chat").

Since users **need to copy OAuth URLs and code snippets out of
Claude Code more often than they need swipe-scroll of chat
history**, 1.18.8 reverts the mouse-on setting and provides
copy-mode scrolling via an explicit toolbar button instead.

### Changes

1. **`scripts/tmux.conf`**: restore the `if-shell '[ -z "$TTYD" ]'`
   gate around `set -g mouse on`. Under ttyd, mouse mode is off
   — selection works, scroll requires the toolbar button.
2. **`ttyd-assets/inject.html`**: new `📜 Hist` toolbar button
   between `▾ Kbd` and `Tab`. Sends the literal
   `Ctrl+B [` (i.e. `\x02[`) sequence which enters tmux copy
   mode. From there the existing `↑ ↓` toolbar buttons scroll
   line-by-line (vi-mode tmux), `ESC` exits, scrolling past the
   live bottom auto-exits via `copy-mode -e`.
3. **`ttyd-assets/inject.html`**: re-introduce the
   `scrollHeight > clientHeight + 1` gate on the touchmove wheel
   dispatch. Without mouse mode on, an ungated dispatch would
   spam arrow keys into Claude Code's input field on every swipe
   in alt-screen — the regression we shipped between 1.18.4 and
   1.18.7 and that the user explicitly didn't want.

### How to scroll Claude Code history now

1. Tap **📜 Hist** on the toolbar → tmux enters copy mode.
2. Tap **↑ / ↓** on the toolbar (or use real keyboard arrows) to
   scroll line-by-line. **PgUp / PgDn** (real keyboard) scroll a
   page at a time.
3. Tap **ESC** on the toolbar to exit copy mode and return to
   typing — or scroll all the way down to the live view and tmux
   auto-exits.

Swipe-to-scroll is gone in alt-screen mode (Claude Code TUI)
for the reasons above. In normal-screen mode (bash prompt with
output) swipe still scrolls xterm's own scrollback — that path
doesn't need mouse mode.

## 1.18.7

### Fixed: scrolling through Claude Code chat history (mobile *and* desktop)

After 1.18.6 the keyboard no longer covered the input row, but
swiping (mobile) or scrolling the mouse wheel (desktop) still did
nothing useful in Claude Code. Most attempts ended up moving the
cursor inside the input box one character at a time instead of
scrolling back through the chat.

### Why this is a tmux configuration issue, not a JS one

Claude Code's TUI runs in **alternate-screen** mode. That has two
consequences that are easy to miss:

1. **xterm.js (browser-side) has no scrollback for alt-screen.** By
   spec, the alt-screen buffer doesn't get added to the terminal
   emulator's scrollback history. So `xterm-viewport.scrollHeight ===
   xterm-viewport.clientHeight` — there is genuinely nothing for
   xterm to scroll. Setting `.scrollTop` does nothing. PgUp / PgDn
   do nothing.
2. **Claude Code itself doesn't implement chat history scrolling**
   on PgUp / PgDn or any other terminal-level key. Once a message
   scrolls off the top of the visible area, the only thing on the
   whole stack that still has it in memory is **tmux's per-pane
   history**, which captures every printed cell regardless of
   normal-vs-alt-screen state.

So "scroll back through Claude Code chat" can only mean **tmux copy
mode** — there is literally no other surface on the system that
has the data.

### The fix: turn on tmux's mouse mode

`scripts/tmux.conf` was already set up correctly for wheel-driven
copy-mode entry —

```tmux
bind -n WheelUpPane if-shell -F -t = "#{mouse_any_flag}" \
    "send-keys -M" \
    "if -Ft= '#{pane_in_mode}' 'send-keys -M' \
       'select-pane -t=; copy-mode -e; send-keys -M'"
bind -n WheelDownPane select-pane -t= \; send-keys -M
```

— but the master switch `set -g mouse on` was gated behind
`if-shell '[ -z "$TTYD" ]'`. Since ttyd's startup exports
`TTYD=1`, that condition was always false, and the WheelUp /
WheelDown bindings never fired. Wheel events fell through to
xterm's default alt-screen behaviour (translate to ↑/↓ arrow
escape sequences fed into the application), which is what produced
the "every swipe moves the cursor" complaint.

This release removes the gate. tmux now requests mouse reporting
from xterm via the standard DECSET 1000 / 1002 / 1006 escape
sequences as soon as it starts, xterm sends mouse events back over
the WebSocket, and tmux's WheelUpPane binding takes over: the
first wheel event auto-enters copy mode (`copy-mode -e`), and
subsequent wheel events scroll through tmux's pane history.

`copy-mode -e` means tmux automatically exits copy mode when the
user scrolls back down to the live view, so scrolling forward
seamlessly returns to typing. Tapping `ESC` on the toolbar also
exits copy mode at any point (in normal mode `ESC` still sends
escape to Claude Code as before).

### Companion JS change in `ttyd-assets/inject.html`

`setupScrollForwarder` previously gated its `WheelEvent` dispatch
on `vp.scrollHeight > vp.clientHeight + 1` to avoid arrow-key spam
in alt-screen mode. With mouse reporting on, xterm sends wheel
events to tmux instead of converting them to arrow keys — so the
gate isn't needed anymore. Removed.

The bash-mode `scrollTop` nudge is kept as a belt-and-suspenders
in case mouse reporting is ever disabled manually.

### What this also fixes

- **Desktop mouse wheel** scrolling through Claude Code chat. The
  user noted this was broken even with a real mouse; same root
  cause, same fix.
- **Touch text selection** in tmux copy mode (long-press +
  drag → selects). `tmux.conf`'s existing
  `MouseDragEnd1Pane → send-keys -X copy-selection-and-cancel`
  binding finally works.
- **Double-tap to select word / triple-tap to select line** —
  also already in `tmux.conf`, also activated by this change.

### Side effects of `set -g mouse on`

A single tap inside the terminal now sends a mouse-press +
release event to tmux in addition to xterm's existing focus-on-
click. tmux's default `MouseDown1Pane`/`MouseUp1Pane` bindings
are "select-pane" — a no-op in our single-pane setup — so taps
remain harmless and the keyboard still opens. If a future change
adds multiple tmux panes, taps would also select the tapped pane
(generally what users expect).

## 1.18.6

### Fixed: keyboard still covered the claude-code input row on iOS HA Companion

1.18.5 detected the keyboard correctly (heuristic + visualViewport
latch), but the input row in Claude Code still ended up *underneath*
the on-screen keyboard. Same symptom as before, different layer.

### Why 1.18.5 wasn't enough

The fix in 1.18.1–1.18.5 widened body's `padding-bottom` whenever the
keyboard came up. The intent was to shrink the area xterm draws into
so claude-code's bottom row would land above the bar + keys. But:

> ttyd's CSS (`html/src/style/index.scss`) does:
>
> ```scss
> html, body { height: 100%; min-height: 100%; ... }
> #terminal-container { width: auto; height: 100%; margin: 0 auto; padding: 0; }
> .terminal { padding: 5px; height: calc(100% - 10px); }
> ```
>
> Both `#terminal-container` and `.terminal` measure `height: 100%`
> against body's **box**, not body's content area. `padding-bottom`
> on body carves out content space *inside* body but leaves body's
> box at the full viewport, so `#terminal-container { height: 100% }`
> stays at full viewport too — every layer below it just kept
> drawing.

The whole chain `body content area → terminal container → .terminal →
xterm.fit()` was broken at the very first link.

### The actual stack (and why this layer matters)

The user kindly reminded us: the rendered terminal is **deeply**
nested. Top to bottom:

```
iOS  →  HA Companion (WKWebView)
              ↓
   HA frontend  →  <iframe>  ingress/<token>/
                              ↓
   ttyd's HTML  →  React  →  #terminal-container
                                    ↓
                  .terminal  →  xterm.js + FitAddon
                                    ↓
                  WebSocket  ↔  ttyd binary  →  PTY winsize
                                                     ↓
                                                  bash → tmux pane
                                                            ↓
                                                       claude-code TUI
```

For "input row stays above keyboard" to work, the size change has to
propagate **all the way down** to the SIGWINCH that reaches claude-
code inside tmux. Anywhere it gets dropped, claude-code keeps drawing
at the unchanged bottom — exactly what the user was seeing.

### Fix (single rule change in `ttyd-assets/inject.html`)

Replace body's `padding-bottom: var(--bruh-bar-h)` with body's
`height: calc(100% - var(--bruh-bar-h, 56px))`. (And drop the
matching `inset: 0` from the lock rule, since `height` + `top` is
now the constraint.)

Now body's *box* shrinks, which means:

| Layer                 | Reads against | Now sees                            |
|-----------------------|---------------|-------------------------------------|
| `#terminal-container` | body's box    | smaller height                      |
| `.terminal`           | container     | smaller height                      |
| xterm.js              | `.terminal`   | smaller `clientHeight`              |
| FitAddon              | xterm element | recomputes `(cols, rows)` smaller   |
| `xterm.resize()`      | —             | emits `onResize`                    |
| ttyd's bundle         | onResize      | sends `{cols, rows}` over WebSocket |
| ttyd binary           | WebSocket     | `ioctl(TIOCSWINSZ, ...)`            |
| PTY                   | kernel        | SIGWINCH → tmux foreground process  |
| tmux                  | SIGWINCH      | reflows pane, re-emits SIGWINCH     |
| claude-code           | SIGWINCH      | redraws TUI, input row at new bot   |

`syncHeight()` also dispatches a synthetic `window.resize` after
flipping the CSS variable. xterm-fit-addon normally fits via
ResizeObserver but older ttyd bundles re-fit on the window
`resize` event — belt-and-suspenders so the chain runs no matter
which path the bundled FitAddon takes.

### What didn't change

The 1.18.5 keyboard-detection logic (parent VV → own VV → phone-
only heuristic → 0, with a "trust VV's gap=0 once it's shown a real
keyboard" latch) is unchanged. The toolbar layout (with `▾ Kbd`),
the `body { touch-action: none }` parent-scroll-leak block, the
wheel-event gate that prevents arrow-key spam in claude-code's
TUI — all unchanged.

The fix here is structural: detection was already producing the
right number, but nothing downstream was actually using it to
shrink xterm.

## 1.18.5

### Fixed: three follow-on regressions from 1.18.2 – 1.18.4 on mobile

After merging 1.18.4 the BRUH terminal in the HA Companion app on
mobile still had three rough edges that the previous fixes hadn't
fully covered:

1. **Keyboard overlapping the bottom of the terminal.** When the
   keyboard opened, the last few rows of output were hidden behind
   the keys. The toolbar usually anchored above the keyboard
   correctly, but the body's `padding-bottom` was too small to
   reserve space for both bar *and* keyboard.
2. **Swipes acting like arrow keys instead of scrolling.** 1.18.4
   forwarded every touchmove to a synthesised `WheelEvent` on
   `.terminal`. That's exactly right in normal-screen mode (it
   scrolls the scrollback), but in Claude Code's TUI (xterm
   alternate-screen mode) xterm's wheel handler translates wheel
   events to ↑/↓ arrow key escape sequences fed straight to the
   application. Every accidental swipe was navigating Claude Code's
   UI a row at a time.
3. **No close-keyboard button.** Once the iOS / Android software
   keyboard is up, the user had no way to dismiss it short of
   tapping outside the textarea (which the body's
   `touch-action: none` happily eats so the keyboard never closes).

### Fix (all in `ttyd-assets/inject.html`)

1. **Phone-only keyboard-gap heuristic.** `computeGap()` previously
   returned `0` whenever neither visualViewport API reported a gap.
   That left the bar buried under the keyboard in HA Companion app
   builds whose keyboard avoidance doesn't update the inner frame's
   visual viewport. The heuristic is back but **only fires when the
   xterm textarea has focus AND we're on a phone-sized viewport**
   (`innerWidth < 500` *or* `innerHeight < 500`). Returns 290 px
   (portrait) / 200 px (landscape) — sized to cover iPhone mini
   through Pro Max. iPads + external keyboards skip the heuristic
   and stay at `bottom: 0`, so the 1.18.2 floating-mid-screen
   regression doesn't come back.
2. **Lowered `MIN_KB_GAP` from 80 → 40 px.** The 80 px floor was
   discarding small-but-real visualViewport gap reports in some HA
   Companion app builds. 40 px clears the iPhone home-indicator
   inset (~34 px) with margin and is still well below the smallest
   plausible mobile keyboard (~135 px landscape iPhone).
3. **Skip wheel-event dispatch in alternate-screen mode.** Touch
   forwarding now checks `vp.scrollHeight > vp.clientHeight` and
   only synthesises a `WheelEvent` when there's actual scrollback.
   In Claude Code's TUI the inequality is false (alt-screen has no
   scrollable area), so swipes no longer turn into arrow-key bursts.
   The body-level `touch-action: none` + `preventDefault` still
   keeps the gesture from leaking to the parent HA frontend.
4. **`▾ Kbd` close-keyboard button** added to the toolbar between
   `ESC` and `Tab` (so it stays visible on narrow screens without
   the user having to scroll the toolbar). Tapping it blurs the
   xterm helper-textarea, which dismisses the on-screen keyboard.
   `onPointerDown` skips its usual focus-restore for this key, so
   the blur isn't immediately undone.

### Also: trust visualViewport's "no keyboard" report once it's proven responsive

The phone-only heuristic from #1 above had its own corner case:
when the user dismisses the iOS keyboard via the **iOS keyboard's
own ▼ button** (rather than tapping our `▾ Kbd` button), iOS
doesn't fire `focusout` on the xterm helper-textarea — so
`taFocused` stays true and the heuristic kept lifting the bar
290 px above an empty bottom edge.

`computeGap()` now latches a `topVVResponsive` / `ownVVResponsive`
flag the first time the corresponding `visualViewport` reports a
real keyboard (`pgap >= MIN_KB_GAP`). After that flag is set,
`computeGap()` *trusts* a subsequent `gap = 0` from the same surface
as authoritative ("the keyboard really did close") and short-
circuits to `return 0` instead of falling through to the heuristic.

The latch matters because:

- HA ingress in mobile Safari → parent VV reports the keyboard →
  flag latches → dismissing the keyboard via iOS's ▼ correctly
  drops the bar.
- HA Companion app builds whose parent VV never sees the keyboard
  → flag never latches → heuristic still kicks in → bar still sits
  above the keys (the failure mode this whole iteration was about).
- iPad with an external keyboard → no VV signal, no heuristic
  (phone-only width gate) → bar at `bottom: 0`. Unchanged.

### Known limitations / future work

- **Context-aware toolbar** (different keys depending on whether
  the user is at a bash prompt vs in Claude Code's TUI) is the
  obvious next step but requires inspecting xterm internals
  (alternate-screen state) that ttyd doesn't expose publicly.
  Punted for now — the current bar covers both cases reasonably.
- **iPhone with an external keyboard** is a corner case the
  heuristic will mis-fire on **on the first focus** (textarea has
  focus, no software keyboard, viewport is phone-sized → bar will
  sit ~290 px above the bottom). After any subsequent VV-reported
  keyboard event the responsiveness latch will fix it.

## 1.18.4

### Fixed: terminal didn't scroll *at all* on mobile after 1.18.3

1.18.3 stopped the HA panel from scrolling when you dragged the
terminal (correctly), but the replacement scroll path — setting
`.xterm-viewport.scrollTop` directly — produced **no visible scroll**
on ttyd's bundled xterm build. From the user's perspective the
panel went from "scrolls the wrong thing" straight to "doesn't
scroll at all". Same gesture, no movement.

Looking at xterm.js's `Viewport.ts`, the wheel handler is registered
on `Terminal._element` (i.e. `.terminal`), not on `.xterm-viewport`:

```ts
register(addDisposableDomListener(this._element, 'wheel',
                                  (ev) => this._onWheel(ev)));
```

That's the same path mouse wheel uses to scroll the buffer, and it's
the most reliable JS-driven scroll API xterm exposes. Driving the
viewport's `scrollTop` directly *should* also work in principle (the
viewport has its own `scroll` listener), but in ttyd's bundle it
doesn't trigger a re-render that the canvas user can actually see —
likely because of how ttyd configures the renderer.

### Fix

`setupScrollForwarder` in `ttyd-assets/inject.html` now forwards each
incremental touchmove delta to a synthesised `WheelEvent` dispatched
on `.terminal`:

```js
target.dispatchEvent(new WheelEvent('wheel', {
  bubbles: true,
  cancelable: true,
  deltaY: increment,           // pixels since the last touchmove
  deltaMode: 0                 // DOM_DELTA_PIXEL
}));
```

This is the exact event shape xterm's `_onWheel` expects from a real
mouse wheel, so the existing wheel-to-scrollback code path runs
unmodified. `.xterm-viewport.scrollTop` is still nudged as a
belt-and-suspenders for any renderer that drives the buffer off the
viewport's `scroll` event rather than wheel.

Everything else from 1.18.3 — the 8 px tap threshold, the
`#bruh-bar` early-return, `touch-action: none` on body / `pan-x` on
the toolbar, `preventDefault` to block parent delegation — is
unchanged.

## 1.18.3

### Fixed: dragging the terminal scrolled the parent HA panel instead of the terminal scrollback

On mobile, swiping up or down inside the terminal didn't move xterm's
scrollback — instead the **entire HA panel** scrolled, sliding the
"BRUH Claude Terminal" header off the top of the screen.

Root cause: xterm.js builds its DOM like this —

```
.terminal
  .xterm-viewport         (overflow-y: auto — the scrollable container
                           behind the visible terminal)
  .xterm-screen           (position: relative — sits ON TOP of
    <canvas>              xterm-viewport, so this is what the user
    <canvas>              actually touches)
  .xterm-helper-textarea
```

`.xterm-viewport` is a **sibling** of `.xterm-screen`, not an
ancestor. When the user drags inside the terminal, iOS walks up the
ancestor chain (`canvas` → `.xterm-screen` → `.terminal` → `body` →
`html`) looking for a scrollable container. Every one of those has
`overflow: hidden` (since we locked the body in 1.18.1 to stop the
auto-scroll-on-focus drift). With no scrollable container found
inside the iframe, iOS delegates the gesture to the parent — HA's
frontend — which has its own scrollable root and dutifully scrolls
the BRUH panel away. The `touch-action: pan-y !important` we set on
`.xterm-viewport` never had a chance: the touch never reached it.

### Fix (all in `ttyd-assets/inject.html`)

1. **`touch-action: none` on `body.bruh-is-touch`.** Blocks the
   native delegation: with no panning gesture allowed on the body
   chrome, iOS doesn't hand the touch up to the parent.
2. **Document-level touchmove handler drives `xterm-viewport.scrollTop`
   directly.** On `touchstart` we record `clientY` and the current
   `scrollTop`; on `touchmove` we set `scrollTop = startScroll -
   deltaY` and `preventDefault()` so the gesture is consumed inside
   the iframe. An 8 px tap threshold means small finger jitter still
   reaches xterm's tap-to-focus listener.
3. **`touch-action: pan-x` on `#bruh-bar`.** The body-level `none`
   would otherwise disable the toolbar's horizontal scroll; the bar
   is its own scrolling container so its `pan-x` value wins for
   touches that start inside it. The forwarder also early-returns on
   touches whose `target.closest('#bruh-bar')` matches, so the two
   gesture handlers never fight.

Toolbar taps, tap-to-focus on the xterm helper-textarea, iOS voice
dictation, the desktop keyboard path, and the bar's keyboard-aware
positioning all keep working — every change is scoped to body-level
panning + the new document-level touchmove listener, neither of
which is reached by click / keyboard / input events.

## 1.18.2

### Fixed: toolbar floating mid-screen in the HA Companion app on mobile

The 1.18.1 fix anchored the `position: fixed` toolbar correctly on iOS
Safari (HA ingress via the browser), but inside the **HA Companion app**
on mobile the bar still floated up into the middle of the screen
whenever the keyboard opened. Same symptom on iPads with an external
keyboard attached: the bar would jump up the moment you tapped the
terminal even though no software keyboard was occluding it.

Root cause: a focus-driven fallback added in 1.17.3 that translated
the bar up by a hard-coded `310 px` (portrait) / `210 px` (landscape)
whenever **none** of the visualViewport-based detectors reported a
gap. That was meant to keep the bar above the iOS keyboard inside
ingress, but it fired far more often than intended:

- HA Companion app on Android (`adjustResize` is default): the
  WebView frame itself shrinks for the keyboard, so `window.innerHeight`
  drops and the bar is **already** above the keys at `bottom: 0`.
  Translating up by 310 px floated it 310 px above the visible bottom.
- HA Companion app on iOS: same pattern when the app's keyboard
  avoidance resizes the WebView frame rather than overlaying.
- iPads with an external keyboard: tapping the terminal focuses the
  textarea but no software keyboard ever appears. The heuristic still
  fired and pushed the bar mid-screen.

### Fix (all in `ttyd-assets/inject.html`)

1. **Drop the 310 / 210 px focus-driven heuristic.** If neither
   visualViewport API reports a meaningful gap, leave the bar at
   `bottom: 0`. Worst case the user has to dismiss the keyboard via
   the device's own affordance to interact with the bar; that's
   strictly better than the bar floating mid-screen.
2. **Detect the "WebView already shrank for the keyboard" case.**
   Capture the stable `window.innerHeight` per orientation at page
   settle. When the current height drops more than 60 px below that
   baseline, treat the gap as `0` — the bar at `bottom: 0` is
   already above the keys. (The baseline is tracked per portrait /
   landscape and only ever grows, so rotating the device or closing
   the keyboard pulls it back up cleanly.)
3. **80 px minimum on visualViewport-reported gaps.** Tiny safe-
   area-inset offsets (e.g. the iOS home-indicator strip) were
   occasionally measured as a non-zero gap and bounced the bar up
   by ~20 px. The keyboard is always taller than 80 px, so anything
   below that threshold is chrome, not keys.
4. **Drop `position: fixed` from `<html>`.** The spec is inconsistent
   on whether root-element `position: fixed` is meaningful (Safari
   honours it, Android WebView sometimes ignores it, and it
   interfered with HA Companion's adjustResize on Android). Replaced
   with `overflow: hidden; height: 100%` which is enough to stop the
   iOS focus-driven auto-scroll and works the same everywhere. The
   body is still locked with `position: fixed; inset: 0` as before.
5. **`preventDefault` on every toolbar `pointerdown`, not just key
   hits.** Tapping a gap between keys (or the bar's own padding)
   was letting iOS treat the tap as "touched outside the focused
   field" and dismiss the keyboard. Bar scrolling is unaffected
   because horizontal scroll is driven by `touchmove` + `touch-action`,
   not pointerdown.
6. **`touch-action: manipulation` on `.bruh-key`.** Opts out of iOS's
   300 ms double-tap-zoom delay and prevents the keyboard from
   blinking shut mid-tap on slow taps.

Desktop behaviour is unchanged — everything is still gated on the
`bruh-is-touch` class which is only added on devices that report
touch support.

## 1.18.1

### Fixed: mobile scroll & toolbar position on iOS

Three related symptoms in HA ingress on iOS Safari / WKWebView traced
back to the same root cause: when the on-screen keyboard opens, iOS
auto-scrolls the iframe document to keep the focused xterm textarea in
view, and `position: fixed` inside an iframe scrolls *with* the
document on iOS. The toolbar got dragged into the middle of the
screen, the terminal slid out from under the user's finger so
scrollback stopped responding to touch, and the whole page rubber-
banded while typing.

The fix in `ttyd-assets/inject.html`:

1. Add `bruh-is-touch` to BOTH `<html>` and `<body>` and lock them
   with `position: fixed; overflow: hidden; overscroll-behavior:
   none`. This blocks iOS's auto-scroll, so the bar stays anchored to
   the visual viewport and touch input keeps landing on
   `.xterm-viewport` where xterm expects it.
2. Reassert touch-scroll on `.xterm-viewport`
   (`-webkit-overflow-scrolling: touch`, `touch-action: pan-y`,
   `overscroll-behavior: contain`) so terminal scrollback is actually
   drag-scrollable.
3. Bump `--bruh-bar-h` to include the keyboard gap, not just the
   bar's own height — otherwise the bar overlaps the last terminal
   line whenever the keyboard is up because body padding-bottom
   only reserved space for the bar itself, not the keys beneath it.

## 1.18.0

### Fixed: every keystroke double-typed in the web terminal

The iOS-dictation `input` listener added in 1.16.x was firing for **every**
keystroke, not just dictation. xterm.js had already converted each keypress
into PTY bytes via its own `keydown` handler, then the BRUH listener saw the
follow-up `input` event, ran the dictation diff-and-send, and wrote the same
character to the PTY a second time. Net effect: typing "hello" produced
"hheelllloo" in any setup that fires both events (most desktops, iPads with
external keyboards, and a handful of HA Companion-app browser builds).

The fix in `ttyd-assets/inject.html` gates the dictation handler on:

1. **No recent keydown** (within 100 ms) — if a real key was just pressed,
   xterm has already handled it; bail.
2. **Not in IME composition** — desktop IMEs (Chinese / Japanese / Korean)
   fire `compositionstart` / `compositionend` and want xterm to handle them
   via `compositionend`; bail.

iOS voice dictation produces input events with neither a paired keydown
nor an active composition, so it still gets the diff-and-send treatment
that fixed WebKit bug 261764. Real keyboard typing is now sent exactly once.

## 1.17.5

### Dedicated one-tap buttons for Claude Code shortcuts

The sticky `Ctrl` modifier approach turned out to be flaky on iOS — even
with the IIFE-scope lift in 1.17.4 the software keyboard kept slipping
past it. Scrapped it entirely in favour of dedicated one-tap buttons
that each send a complete sequence on their own; no modifier state,
nothing to intercept.

New toolbar layout (scrollable horizontally):

`ESC` · `Tab` · `⇧Tab` · `↑` `↓` `←` `→` · `^C` `^D` `^L` `^U` · `/` `@` `#` `!` `|` · `Paste` · `×`

- `⇧Tab` sends `\x1b[Z` — Claude Code's mode-cycle key.
- `^C` / `^D` / `^L` / `^U` send `\x03` / `\x04` / `\x0c` / `\x15` —
  interrupt, EOF, clear screen, clear line.
- `/` `@` `#` `!` are the Claude Code prefix characters (slash-command
  menu, file reference, memory, bash mode) as literal single chars,
  giving one-tap access without fishing for them in the iOS keyboard.

Removed `Ctrl`, `~`, `-` buttons (the two latter were low-value and
freed toolbar width for the new shortcuts). `diffAndSend` is now a
straight diff forwarder — the dictation fix is unchanged, it just
no longer has a Ctrl branch to worry about.

## 1.17.4

### Sticky Ctrl now works with the software keyboard

Tapping the toolbar's `Ctrl` armed the modifier, but typing a letter
on the on-screen keyboard afterwards (e.g. `Ctrl` then `R` to reload)
reached the PTY as a plain `r`. The Ctrl state was scoped inside
`buildToolbar()`, so `handleKey()` could see it but the
document-level input capture path — which is how software-keyboard
characters get forwarded to ttyd — couldn't.

Lifted `ctrlSticky` and `setCtrl` to the IIFE scope so both call
sites share the same state. `diffAndSend()` now applies the Ctrl
transform when the textarea delta is exactly one new character (a
real keypress) and drops it for multi-char deltas (dictation,
autocorrect, paste) so `Ctrl` + spoken "test" doesn't turn into a
burst of control codes. The toolbar's visual Ctrl pill still updates
correctly because it's driven off `setCtrl`, which is now shared.

## 1.17.3

### Lift the toolbar above the keyboard when running behind HA ingress

1.17.2 hooked `visualViewport` but the terminal is almost always loaded
inside Home Assistant's ingress iframe, and on iOS Safari / WKWebView
the keyboard does NOT resize the inner frame's `visualViewport` — only
the top window sees the change. From the iframe's point of view the
viewport height never shrinks, so `gap` came out `0` and the bar
stayed stuck at the layout bottom, covered by the keys.

HA ingress serves us under `/api/hassio_ingress/<token>/` on the same
origin as the frontend, so we can legally walk up via `window.parent`
and read the top frame's `visualViewport`. If that path is unavailable
for any reason (cross-origin parent, standalone browsing), we fall
back to our own viewport, and then finally to a focus-driven heuristic
(assume ~310px keyboard portrait / ~210px landscape while the xterm
helper-textarea has focus). Listeners now attach to both the local and
parent visual viewports plus document-level `focusin`/`focusout`.

## 1.17.2

### Keep the mobile toolbar above the on-screen keyboard

On iOS / iPadOS (and Android configurations that overlay rather than
reflow), the software keyboard slid up and covered the toolbar because
`position: fixed; bottom: 0` is positioned against the *layout* viewport,
not the visual viewport. The bar was still there — just hidden behind the
keys.

Hooked the `VisualViewport` API: when `visualViewport.height` shrinks
(keyboard up), translate the bar up by exactly the keyboard-overlap gap
(`window.innerHeight - vv.height - vv.offsetTop`) and drop the
`safe-area-inset-bottom` padding since the keyboard replaces the home
indicator area. When the keyboard closes, reset back to the stock
position. Listens on `resize` and `scroll` of the visual viewport so the
bar tracks the keyboard's own animation without lag.

## 1.17.1

### Mobile toolbar + iOS dictation fix — third time's the charm

v1.17.0 shipped with the mobile toolbar "working" in theory but not in
practice: the toolbar never appeared, and voice dictation still produced
the classic "ttesttesting, can youtesting, can you hear me..." cumulative
duplication. Two root causes, both fixed here.

**Why 1.17.0 didn't show a toolbar.** ttyd 1.7.4 (Alpine 3.19) doesn't
serve separate `/main.js` / `/index.css` files the way older builds did —
`html/gulpfile.js` runs `inlineSource()` to bake the entire frontend
into a single HTML blob as inline `<script>` and `<style>` tags. The
1.17.0 builder extracted those inline tags and spliced them into our own
template; the result referenced asset paths that don't exist on ttyd's
HTTP server and, more fundamentally, ttyd's bundle renders React into
`document.body` directly (wiping any toolbar DOM we staged in the HTML).

**Why iOS dictation was still broken.** Our "swallow any `input` event
within 60ms of `compositionend`" heuristic can never trigger on iOS.
WebKit bug [261764](https://bugs.webkit.org/show_bug.cgi?id=261764)
confirms that iOS Safari / WKWebView does NOT fire `compositionstart`
or `compositionend` for voice dictation at all — only plain `input`
events, each carrying the whole cumulative transcript. `lastCompositionEnd`
stayed `0` forever, so the guard was a no-op. Any apparent improvement
came from the autocorrect-off attributes alone.

**What's different in 1.17.1.**

- `build-mobile-index.py` now treats ttyd's HTML as opaque and splices a
  snippet of ours into `<head>` without touching a single byte of ttyd's
  payload. Our inline `<script>` runs before ttyd's inline bundle (both
  inline scripts execute in document order), so we wrap `window.WebSocket`
  before ttyd calls `new WebSocket(...)` and can send stdin from the
  toolbar. No asset path assumptions; robust to ttyd bumps.
- The toolbar DOM is created dynamically AFTER xterm mounts, via a
  `MutationObserver` watching for `.xterm-helper-textarea`. Since React
  is already done rendering into `document.body` by that point and our
  toolbar uses `position: fixed`, React's virtual DOM never touches it.
- iOS dictation: we install a capture-phase `input` listener on
  `document`. Per DOM spec, ancestor capture-phase listeners fire before
  target-level capture-phase listeners — and xterm's own listener is
  attached on the textarea in capture phase — so we run first. On each
  event we diff `textarea.value` against `lastValue`, send a backspace
  (`\x7f`) for every retracted character and the new tail, then
  `stopImmediatePropagation` so xterm never sees the event. This is the
  CodeMirror / ProseMirror approach applied to xterm.
- The probe runs with `Accept-Encoding: identity` so ttyd serves
  uncompressed HTML, and `run.sh` now logs the full builder stderr into
  the add-on log when the probe fails — no more silent fallback.

The `enable_mobile_ui: false` kill switch from 1.17.0 is unchanged.
Stock-ttyd fallback still kicks in automatically if the probe fails.

## 1.17.0

### Mobile toolbar + iOS dictation fix (reworked, take two)

Brings back the on-screen toolbar and iOS dictation fix that 1.16.0 tried
to ship, this time on top of whatever frontend bundle ttyd actually serves
— not a hard-coded script name.

**How this differs from 1.16.0**

The earlier attempt shipped a static `index.html` that assumed ttyd's
legacy webpack output (`<div id="terminal">` + `<script src="inline.js">`).
ttyd 1.7.x on Alpine 3.19 ships a different build, the React app never
mounted, and you got a black screen.

1.17.0 adds a startup probe (`scripts/build-mobile-index.py`) that:

1. Boots ttyd locally on a loopback-only port.
2. `GET /` to grab whatever HTML ttyd actually serves today.
3. Extracts its `<link>` / `<style>` / `<script>` tags with BeautifulSoup.
4. Splices them into our mobile template next to the toolbar DOM, the
   WebSocket-capturing wrapper, and the xterm-textarea patcher.
5. Writes the rendered file for ttyd to serve via `--index`.

If the probe fails for any reason, `run.sh` skips `--index` entirely and
ttyd serves its stock working UI. No more silent black screens.

**Mobile toolbar** (touch devices only)

- `ESC`, `Tab`, sticky `Ctrl`, arrows, `|`, `/`, `~`, `-`, `^C`, `Paste`, `×` hide.
- Taps send real key sequences through the ttyd WebSocket so Claude Code's
  menu navigation, tab-complete, and interrupts all work.
- `Ctrl` is a sticky modifier — tap it, then a letter, to send that
  control code.

**iOS dictation fix**

- Turns off `autocorrect` / `autocapitalize` / `autocomplete` / `spellcheck`
  on xterm's helper textarea.
- Swallows the duplicate `input` event iOS fires ~30ms after
  `compositionend` — the root cause of voice dictation doubling words
  (xtermjs/xterm.js#3600).

**Kill switch**

New `enable_mobile_ui` config option (default `true`). Flip to `false` if
the probe or custom UI ever misbehaves on your system; ttyd falls back to
its stock frontend.

## 1.16.1

### Fix black-screen regression from 1.16.0

The custom ttyd `index.html` shipped in 1.16.0 didn't match how ttyd 1.7.x
(the version on Alpine 3.19) bundles its frontend — the React terminal
never mounted, leaving users with a blank black page. Rolled back the
custom HTML and the `--index` flag so ttyd serves its working stock UI
again. The Claude-Code colour theme and reconnect settings are preserved
(those come from `--client-option`, not the HTML override).

The mobile toolbar / iOS dictation fix will return in a follow-up release
once it's reworked to hook into the stock bundle correctly.

## 1.16.0

### Mobile-Friendly Terminal (iOS / Android)

Using the terminal on a phone was painful: iOS has no ESC key, and voice
dictation often repeated words. This release ships a custom ttyd frontend
themed to match Claude Code.

**On-screen toolbar** (shown only on touch devices)
- `ESC`, `Tab`, `Ctrl` (sticky), `↑ ↓ ← →`, `|`, `/`, `~`, `-`, `^C`, `Paste`, and `×` (hide)
- Taps send real key sequences through the ttyd WebSocket, so everything Claude Code expects from a keyboard works (cancel prompts, navigate history, tab-complete, pipe commands).
- Ctrl is a sticky modifier — tap `Ctrl` then a letter to send that control code (e.g. `Ctrl` + `C` → `^C`).
- `Paste` reads from the clipboard via the Web Clipboard API.

**iOS dictation / autocorrect fix**
- Turned off `autocorrect`, `autocapitalize`, `autocomplete`, and `spellcheck` on xterm's helper textarea so the OS stops rewriting commands.
- Added a compositionend → input deduper that swallows the extra `input` event iOS fires a few ms after voice dictation ends, which was the root cause of words appearing twice ([xtermjs/xterm.js#3600](https://github.com/xtermjs/xterm.js/issues/3600)).

**Theme**
- ttyd client colours now match Claude Code: warm dark background (`#1a1613`), Claude orange cursor (`#d97757`), light warm foreground.
- Default font stack set to `SF Mono, Menlo, Consolas, monospace`.

**Viewport**
- Proper `viewport-fit=cover` + safe-area insets so the toolbar sits above the home indicator on modern iPhones.
- `apple-mobile-web-app-capable` so adding the add-on URL to the iOS home screen gives a full-screen PWA-style launcher.

## 1.15.2

### Recursive Ownership for addon_configs & Writable Addons Directory

- Fixed `chown` for `/addon_configs` to use `-R` (recursive) so subdirectories are also owned by the `claude` user, not just the top-level directory
- Changed `/addons` mount from read-only (`addons:ro`) to read-write (`addons:rw`) so Claude can edit add-on files
- Added `access_addons` boolean toggle in the add-on configuration UI (default: on) — controls whether Claude has access to the `/addons` directory
- Added `ADDONS_DIR` environment variable, exported only when `access_addons` is enabled and `/addons` exists
- Context generation now includes `/addons/` in the available directories listing when enabled

## 1.15.1

### Configurable Directory Access & Fix addon_configs Mount

**Configurable Directory Access**
- Added `access_share`, `access_media`, `access_backup`, `access_addon_configs` boolean options in the add-on configuration UI — toggle which directories Claude can access
- Added `additional_directories` list option — specify custom paths for Claude to access (e.g., other mount points or data directories)
- Environment variables (`SHARE_DIR`, `MEDIA_DIR`, `BACKUP_DIR`, `ADDON_CONFIG_DIR`) are only exported when the corresponding access option is enabled and the directory exists
- Ownership (`chown`) for volume mount directories is only set for enabled directories
- Context generation (`ha-context-gen`) now dynamically lists only the directories that are actually available in the container

**Fix addon_configs Mount**
- Changed `map` from `addon_config:rw` to `all_addon_configs:rw` — `addon_config` only mounts this add-on's own config dir at `/addon_configs/<slug>/`, while `all_addon_configs` mounts the full `/addon_configs/` directory so Claude can inspect and manage config for any add-on
- Added `addons:ro` mount for read-only access to installed add-on files
- Fixed `ADDON_CONFIG_DIR` environment variable to point to `/addon_configs` (the actual mount path)

## 1.15.0

### Volume Mounts, Admin Role, Expanded Permissions & New CLI Tools

**New Volume Mounts**
- Added `share:rw` (`/share/`) — shared storage accessible by other add-ons for cross-addon file operations
- Added `media:rw` (`/media/`) — HA media directory for images, audio, video
- Added `backup:ro` (`/backup/`) — read-only access to HA backup snapshots
- Added `addon_config:rw` (`/addon_configs/`) — persistent config directory for the add-on

**Supervisor Role Upgrade**
- Upgraded `hassio_role` from `manager` to `admin`, unlocking full Supervisor API access: managing other add-ons (restart, stop, start, get info), managing HA Core, and managing snapshots

**Expanded Tool Permissions**
- Updated `settings.local.json` allowlist to include all Claude Code tools: Glob, Grep, Agent, Skill, NotebookEdit, TaskCreate/Update/Get/List, TodoWrite/Read, and MCP wildcards for Home Assistant and Vercel

**5 New CLI Tools**
- `ha-addon` — manage add-ons via Supervisor API (list, info, restart, stop, start, logs, options) with confirmation prompts for destructive actions
- `ha-entity` — get/set entity states, list by domain, search by name or ID
- `ha-service` — call any HA service with JSON data, list available service domains
- `ha-notify` — send persistent notifications to the HA UI or mobile push via notify services
- `ha-share` — cross-addon file sync via `/share` (push, pull, ls) with rsync support when available

**Environment & Context Updates**
- Exported `SHARE_DIR`, `MEDIA_DIR`, `BACKUP_DIR`, `ADDON_CONFIG_DIR` environment variables for scripts and background processes
- Added `chown` for `/share` and `/media` so the claude user has write access
- Updated context generation (`ha-context-gen`) to document available directories and all CLI tools

**Dockerfile**
- Added `rsync` and `sqlite` packages to the container image

## 1.14.5

### Fix "Auto-update failed" error in Claude Code UI

**Fixed "Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-code" warning**
- Claude Code's built-in auto-updater fails when running as the non-root `claude` user because it cannot write to npm global directories or `/root/.local/bin`
- Set `DISABLE_AUTOUPDATER=1` environment variable to suppress the auto-updater since the add-on already handles updates at startup via `update_claude_code()` running as root
- Added to the main process environment, the persisted env file, and the `claude-run` wrapper script to guarantee the env var reaches Claude Code through the `ttyd -> tmux -> su-exec` process chain

## 1.14.4

### Fix Claude Code binary removed during startup

**Fixed Claude Code exiting immediately when opened via ingress**
- `setup_claude_user()` deleted `/usr/local/bin/claude` (the npm-installed binary) to suppress a diagnostic warning, but `/root/.local/bin/claude` was a symlink pointing to it — leaving a broken symlink
- Now resolves the real binary path (the `cli.js` inside `node_modules`) before removing the `/usr/local/bin` entry, and re-points the symlink to the resolved path
- Same fix applied to the Dockerfile build and the `update_claude_code()` runtime updater
- Updated health check to treat `/usr/local/bin/claude` as expected (from npm) rather than "stale"

## 1.14.3

### Fix Claude Code Auto-Update musl Compatibility

**Fixed "posix_getdents: symbol not found" crash on update**
- The binary installer (`install.sh`) downloads a native musl build that requires `posix_getdents`, a symbol added in musl 1.2.5 - but Alpine 3.19 ships musl 1.2.4
- Switched both Dockerfile and runtime auto-update from the binary installer to `npm install -g @anthropic-ai/claude-code`, which uses the Node.js package and works on any musl version
- npm-installed binary is symlinked to `/root/.local/bin/claude` so the `claude-run` wrapper and persistent symlinks continue to work unchanged
- Retains retry logic (4 attempts with exponential backoff) for network readiness at startup

## 1.14.2

### Fix Claude Code Auto-Update Failing on Startup

**Fixed Auto-Update Failing with "update check failed"**
- Root cause: `set -o pipefail` caused `curl ... | bash` to fail if `curl` hadn't completed before `bash` exited, or if the network wasn't ready at container startup
- Separated download and execution: installer script is now downloaded first, then executed, avoiding pipeline exit-code issues
- Added retry logic (4 attempts with backoff) for downloading the installer, since the network may not be available immediately at startup
- Stopped suppressing stderr (`2>/dev/null`) from the installer so failures are logged for diagnosis
- On installer failure, the actual error output is now logged via `bashio::log.warning`

## 1.14.1

### Fix Claude Code Auto-Update Installing to Wrong Path

**Fixed Auto-Update Not Working**
- The `update_claude_code()` function was installing the updated binary to `/data/home/.local/bin/claude` instead of `/root/.local/bin/claude` because `HOME` was already set to `/data/home` by `init_environment()`
- The `claude-run` wrapper always executes `/root/.local/bin/claude`, so the stale Docker-image binary was used regardless of the update
- Fixed by overriding `HOME=/root` when running the installer so it updates the correct binary
- Made the persistent symlink refresh unconditional to recover from edge cases

## 1.14.0

### Auto-Update Claude Code on Startup

**Claude Code Auto-Update**
- Added `update_claude_code()` function that runs the official Claude Code installer on every container startup
- Ensures the add-on always uses the latest Claude Code version without requiring a Docker image rebuild
- Logs current and updated version numbers for visibility
- Gracefully falls back to the existing version if the update check fails
- Refreshes persistent binary symlinks after updates

## 1.13.0

### Version Bump, Documentation & Changelog Catch-Up

**Documentation Updates**
- Added missing CHANGELOG entries for v1.11.0 and v1.12.0
- Synced version numbers across all files (config.yaml, manifest.json, run.sh)

## 1.12.0

### Deep MCP Cleanup, Device Separation & Agent Timeout Fix

**Comprehensive MCP Auth Cleanup**
- Replaced `cleanup_broken_plugins()` with `cleanup_all_mcp_references()` that scans all Claude Code config locations with unlimited depth
- Clears ALL persistent conversation sessions on startup (fixes v1.8.0 `--resume` regression where stale MCP state survived config cleanup)
- Cleans ALL `.mcp.json` files across `/data`, `/config`, `/root`, and `~/.claude.json`
- Added MCP watchdog background process that monitors for `/api/mcp` entries being re-created after cleanup, auto-cleans them, and logs the source
- Added `CLAUDE_CODE_DISABLE_MCP_DISCOVERY` and `CLAUDE_MCP_SERVERS_OVERRIDE` env vars to block Claude Code from auto-discovering HA's native `/api/mcp`
- Enhanced `verify_mcp_config()` in both listeners to check and clean Claude Code's project-level configs before each invocation
- Added `/api/mcp` error detection in listeners — auto-cleans configs and retries

**Entity & Device Separation**
- Each conversation agent now gets its own `DeviceInfo`, appearing as a distinct device card in HA
- Agents show as "BRUH Claude" / "BRUH OPUS" devices with model "Claude Conversation Agent"
- Usage sensors remain grouped under "BRUH Claude Usage Limits" device

**Agent Timeout Fix**
- Simplified `assist-listener.sh` to match the proven `automation-listener` pattern (single invocation, plain text output)
- Removed `--output-format json`, `--resume`, session persistence, and nested retry loops from assist-listener
- Added `~/.claude.json` cleanup — the primary hiding spot for stale `/api/mcp` entries that caused Claude Code to hang on MCP connection
- Changed `setup_mcp_server()` from warning about extra configs to actively cleaning them

**Config Flow UX Improvements**
- Improved first_setup, add_agent, and options flow descriptions for clarity
- Updated both `strings.json` and `translations/en.json`

## 1.11.0

### Simplified Onboarding & /api/mcp Auth Fix

**Integration Onboarding Redesign**
- Redesigned config flow with context-aware routing
- First setup shows only a name field and creates a conversation agent + sensors with all defaults (one click)
- "Add Service" shows the full agent personality form (name, model, system prompt, timeout)
- Removed the confusing two-step feature-toggle flow from v1.10.0
- Options flow now only shows the sensor toggle when this is the sole config entry
- Config entry migration v2 → v3

**Fixed /api/mcp Authentication Errors**
- `setup_mcp_server()` now always overwrites `/config/.mcp.json` with a clean config instead of merging (which preserved stale entries)
- `cleanup_broken_plugins()` now stringifies entire MCP entry values for matching (catches URLs in any field, not just `.url`/`.args`)
- Both listeners verify MCP config is clean before each Claude invocation, preventing runtime re-contamination
- Broader cleanup search locations, broken npm package removal, MCP diagnostic logging

## 1.10.0

### Feature Toggles & MCP Cleanup Hardening

**Integration Onboarding Redesign**
- New two-step config flow: first choose which features to enable, then configure agent settings
- Conversation agent and usage limit sensors are now independently toggleable
- Users can enable just sensors, just a conversation agent, or both
- Options flow updated with feature toggles — easily turn features on/off after setup
- Config entry migration (v1 → v2) ensures existing installs keep working seamlessly

**Hardened /api/mcp Cleanup**
- Increased search depth from 2 to 4 levels to catch entries in Claude Code project config files
- Added post-write sanitization to `setup_mcp_server()` — even if cleanup misses a stale entry, the final `.mcp.json` is always verified clean
- Now also checks `.args` fields (not just `.url`) for `/api/mcp` references
- Added `/root/.mcp.json` to the list of checked locations

**Fixed: Conversation Agent Not Responding**
- Added process-level `timeout` to all `claude -p` calls in both assist and automation listeners
- Previously, if Claude Code hung (e.g., broken MCP server connection), the listener blocked forever and no response file was ever written — the user got nothing
- Now Claude Code is killed after 105s (assist) or 300s (automation), and a meaningful error message is returned
- Added timeout-specific error messages so users know what happened
- Added `asyncio.CancelledError` handling in the conversation entity for cases where HA cancels the request

## 1.9.0

### Remove Legacy Token Sensors & Fix /api/mcp Auth Error

**Removed Legacy Token Sensors**
- Removed the old token-counting sensors (session/daily/weekly/all-time token counts)
- The `token-stats-tracker.py` script is no longer started
- Kept the Anthropic usage limit sensors (session/weekly usage %, reset times) which read real API data

**Fixed /api/mcp Authentication Error**
- Added `cleanup_broken_plugins()` to startup that removes stale MCP server entries from the broken `claude-homeassistant-plugins` marketplace plugin
- The plugin registered an SSE MCP server pointing to HA's `/api/mcp` endpoint with invalid auth, causing "invalid authentication" errors and blocking conversation agent responses
- Cleanup removes plugin/extension references and stale `mcpServers` entries from all Claude Code config locations

## 1.8.0

### Anthropic Usage Sensors, Persistent Sessions & Configurable Turns

**Real Anthropic Usage Limit Sensors**
- New sensors that show your actual Claude account usage — the same data shown on claude.ai Settings > Usage
- A background tracker (`usage-limits-tracker.py`) queries the Anthropic OAuth usage API every 2 minutes
- Reads the OAuth token from Claude Code's credentials file automatically
- New sensors:
  - Session Usage (%) — 5-hour rolling window utilization percentage
  - Session Usage Resets At — timestamp when the session window resets
  - Weekly Usage (%) — 7-day utilization percentage
  - Weekly Usage Resets At — timestamp when the weekly limit resets
- Sensors grouped under a "BRUH Claude Usage Limits" device
- Gracefully shows "unavailable" if Claude Code is not authenticated or using an API key

**Persistent Conversation Sessions**
- Each conversation agent now maintains a persistent Claude Code session using `--resume`
- First message creates a new session; subsequent messages resume it with full context
- Claude remembers conversation history natively — no more re-sending history as text
- MCP tool state is preserved across messages (no cold-start MCP discovery)
- Automatic fallback to new session if resume fails (e.g., session deleted)
- New `bruh_claude.clear_conversation` HA service to reset sessions:
  - Pass `conversation_id` to clear one specific agent's session
  - Omit it to clear ALL sessions
- Session IDs stored in `/config/.bruh_claude/sessions/`

**Configurable Max Turns**
- Assist max turns increased from 3 to 5 (default)
- Both `assist_max_turns` and `automation_max_turns` are now configurable via the add-on config UI
- Assist: 1–20 (default 5), Automation: 1–50 (default 10)

**Per-Model Token Tracking**
- Token stats tracker now parses model names from JSONL session files
- Tracks per-model usage (Sonnet, Opus, Haiku) for session and weekly periods
- Adds estimated session reset time based on session activity window
- Per-model data available in `token_stats.json` under `models_week` and `models_session` keys

## 1.6.3

### Fix Duplicate Sensors & Add Reset Time Sensors

**Fixed Duplicate Token Sensors**
- Token usage sensors were being created per conversation config entry, causing duplicates when multiple conversation agents existed
- Sensors now use fixed unique IDs and are only created once (account-wide, not per conversation agent)
- All sensors are grouped under a single "BRUH Claude Token Usage" device for cleaner organization
- If the config entry owning the sensors is removed, sensor ownership automatically migrates to another entry

**Added Reset Time Sensors**
- Session Started — timestamp sensor showing when the current Claude session began
- Today Resets At — timestamp sensor showing when today's token counters reset (midnight UTC)
- Weekly Resets At — timestamp sensor showing when weekly token counters reset (next Monday UTC)

**Note:** After updating, old duplicate sensor entities will show as unavailable and can be removed from the entity registry.

## 1.6.1

### MCP Fixes & Token Usage Sensors

**Fixed MCP Tool 404 Errors**
- Fixed `get_error_log` returning HTTP 404 on HA 2025.11+ — the legacy `/api/error_log` REST endpoint broke when supervised installations removed `home-assistant.log`. Now uses the Supervisor's `/core/logs` journal endpoint with automatic fallback to the legacy endpoint for non-supervised setups.
- Fixed `get_automation_trace` returning HTTP 404 — the `/api/trace/automation/{id}` REST endpoint never existed (traces are WebSocket-only). Replaced with automation entity state lookup via `/api/states` plus stored trace reading from `/config/.storage/trace.saved_traces` when available.

**Token Usage Sensors**
- Added token usage sensors to the BRUH Claude custom integration
- A background tracker (`token-stats-tracker.py`) scans Claude Code session JSONL files every 60 seconds and writes aggregated stats to `/config/.bruh_claude/token_stats.json`
- Token counts are the real values from the Anthropic API `usage` field — not estimated
- Sensors:
  - Session Input Tokens / Output Tokens / Total Tokens (with `started_at`, `last_activity` attributes)
  - Today Total Tokens (with `period_start`, `resets_at` attributes)
  - Weekly Total Tokens (with `period_start`, `resets_at`, `session_count` attributes)
  - Weekly Sessions (distinct session count this week)
  - All Time Total Tokens

## 1.5.6

### Auth & Permission Fixes

**Fixed MCP Server Permission Denied**
- `.mcp.json` was written as root but Claude Code runs as UID 1000 — added chown/chmod after writing

**Fixed Broken Plugin Interference**
- A stale `claude-homeassistant-plugins` marketplace plugin was hitting HA's native MCP endpoint with invalid auth — added `cleanup_broken_plugins()` to remove stale plugin references at startup

**Fixed "Multiple Installations" Warnings**
- Renamed wrapper script from `/usr/local/bin/claude` to `/usr/local/bin/claude-run` to prevent Claude Code diagnostics from detecting a conflicting npm-global install

## 1.5.5

### Syntax Fix
- Fixed missing closing brace in `setup_claude_settings()` that caused "syntax error: unexpected end of file"

## 1.5.4

### Conversation Agent Permissions Rework

**Fixed Conversation Agents Returning Empty Responses**
- Replaced `--dangerously-skip-permissions` in listeners with project-level `settings.local.json` tool allowlist
- Added `--max-turns` (3 for Assist, 10 for Automation) to reduce latency
- Added `--system-prompt` flag for cleaner prompt separation
- Added empty-response detection with stderr-based error diagnostics
- Default `dangerously_skip_permissions` changed to `false` in config.yaml

**Updated Branding**
- Updated all icons to Claude AI branding (`mdi:creation` sparkle)

## 1.5.3

## 1.5.2

## 1.5.1

### Repair Flow Fix, Expanded Device Control & Options Flow

**Fixed Repair Flow Not Triggering**
- Fixed the repair issue never appearing after an add-on update
- Root cause: the version comparison read the already-overwritten manifest.json from disk instead of using the in-memory version, so it always thought the restart had already happened
- The loaded version is now captured at module import time, before the add-on can overwrite it
- Fixed repair flow translation strings to use the correct `fix_flow` structure per HA conventions (was incorrectly using a separate top-level `repairs` key)

**Expanded MCP Service Tools**
- Added dedicated tools for controlling all major device types with fully typed parameters:
  - `control_light` — brightness, RGB/HS/XY color, color temperature (Kelvin), color name, effects, transitions, flash
  - `control_climate` — temperature, HVAC mode, fan mode, preset mode, humidity, swing mode
  - `control_media_player` — play/pause/stop, volume, source selection, play media, seek, shuffle, repeat
  - `control_cover` — open/close/stop, set position, set tilt
  - `control_fan` — speed percentage, preset mode, direction, oscillation
  - `control_switch` — on/off/toggle for switches and input_booleans
  - `control_lock` — lock/unlock/open with optional access code
  - `control_alarm` — arm (away/home/night/vacation), disarm, trigger with code
  - `control_vacuum` — start/stop/pause, return home, locate, spot clean, fan speed
  - `send_notification` — persistent notifications or targeted (mobile app, Slack, etc.)
  - `activate_scene` — activate scenes with optional transition
  - `run_script` — run scripts with optional variables
- Added `get_service_details` tool for dynamic service schema lookup
- Improved `call_service` description with comprehensive examples
- Enhanced assist-listener prompt so Claude knows about all available device control tools

**Options Flow for Conversation Agents**
- Added an options flow so users can edit the system prompt and timeout after initial setup
- Go to Settings > Devices & Services > BRUH Claude > Configure to change settings
- The conversation entity reloads automatically when options are changed

**Integration Icon**
- Note: To see the BRUH Claude icon in Settings > Devices & Services, submit the icon to the [home-assistant/brands](https://github.com/home-assistant/brands) repo under `custom_integrations/bruh_claude/`, or wait for HA 2026.3.0 which supports local custom integration icons

## 1.5.0

### HA Repairs Flow, OAuth Persistence & Conversation Memory

**HA Repairs Integration**
- Replaced persistent notification with HA repairs flow for integration updates
- On update, the integration creates a fixable repair issue in Settings > System > Repairs with a "Restart" button
- First installs still use a persistent notification as fallback since no integration is loaded yet
- Added `repairs.py` with `RestartRequiredRepairFlow` that triggers HA restart

**OAuth Persistence**
- OAuth auth symlinks are now recreated on every add-on startup
- Credentials persist across add-on updates and container rebuilds

**Conversation Memory**
- Added conversation memory to the Assist conversation agent
- The bridge tracks per-session history (up to 20 turns) and sends it with each request
- The assist-listener formats history as context for Claude

## 1.4.0

### Permissions Toggle, Restart Documentation & Version Bump

**Configurable Permissions Flag**
- Added `dangerously_skip_permissions` configuration toggle (default: `true`)
- The `--dangerously-skip-permissions` flag is no longer hardcoded — it's now controlled via the app configuration UI
- Setting this to `false` makes Claude Code prompt for confirmation before each tool call (file edits, shell commands, etc.)
- Flag state is persisted in the shared env file so background integrations (Assist, Automation listeners) respect the setting
- Note: Disabling this will make Assist and Automation integrations non-functional since they run non-interactively

**Restart Requirements Documentation**
- Clarified that an HA Core restart is required after first install and after version upgrades
- Added a detailed restart requirements table to DOCS.md explaining each scenario
- Updated Quick Start guides in DOCS.md and README.md to include the restart step
- Added upgrade note to README.md installation instructions
- Documented that disconnecting/reconnecting the integration does NOT reload updated Python code

**Security Documentation**
- Added comprehensive "Permissions" section to DOCS.md explaining what `--dangerously-skip-permissions` does
- Documented the sandboxing context: non-root user (UID 1000), isolated container, limited to /config and /data
- Added inline code comments in `run.sh` explaining the security model

## 1.3.0

_Skipped — reserved for intermediate builds._

## 1.2.0

### Discovery Fix, Version Updates & App Terminology

**Fixed Integration Auto-Discovery**
- Fixed the integration not being auto-discovered on first install
- The app now triggers an HA Core restart after first-time custom component deployment,
  ensuring the integration is loaded before discovery fires
- Uses bashio::discovery for reliable Supervisor API communication with curl fallback
- Discovery payload now includes add-on metadata (slug, name, version)
- Config flow updated to handle both legacy dict and new HassioServiceInfo discovery formats

**Version Update Detection**
- Bumped version to 1.2.0 across all files (config.yaml, manifest.json, run.sh)
- Versions are now kept in sync so the update button appears correctly in Settings > Apps
- When pulling repository updates, HA will detect the new version and show the update button

**Updated to HA 2026.2 Standards**
- Renamed "Add-On" references to "App" throughout (matching HA 2026.2 terminology)
- Added `integration_type: "service"` to manifest.json per latest HA integration standards
- Updated all user-facing strings (config flow, error messages) to use "app" terminology

## 1.1.0

### Auto-Discovery & Versioning

**Automatic Integration Discovery**
- The BRUH Claude integration is now automatically discovered when the add-on starts
- Home Assistant will show a notification prompting you to set up the integration
- No more manual navigation to Settings > Devices & Services to add it
- Manual setup via Settings > Devices & Services still works as a fallback

**Version Display & Update Support**
- Fixed version number not appearing on the add-on store page
- Fixed update button not showing when a new version is available
- Synced version numbers across add-on config, integration manifest, and startup banner

## 1.0.0

### Initial Release

Built on the foundation of [heytcass/claude-terminal](https://github.com/heytcass/home-assistant-addons), BRUH Claude Terminal adds:

**Native HA API Access**
- Built-in MCP server providing Claude Code with real-time Home Assistant access
- Entity states, service calls, automation traces, logs, template rendering
- Auto-configured on startup - no manual MCP setup needed

**Auto-Generated Project Context**
- Generates CLAUDE.md on startup with full system context
- Entity counts, automations, integrations, add-ons, file structure
- Regenerate anytime with `ha-context-gen`

**Git-Based Config Backup**
- Automatic git versioning of /config directory
- Configurable backup interval (default: 30 minutes)
- Manual backup via `ha-backup` command
- File restore from any previous commit
- Smart .gitignore excludes secrets, databases, logs

**Config Reload Integration**
- `ha-reload` command for reloading HA configs from the terminal
- Supports automations, scripts, scenes, groups, input helpers, core, and all
- Configuration validation via `ha-reload check`

**Log Access**
- `ha-log` command for viewing HA core, supervisor, host, and add-on logs
- Error filtering mode
- Follow mode for real-time log tailing

**Persistent Environment**
- APK and pip packages persist across restarts
- Configurable via add-on settings or `persist-install` command

**Multi-Session & Background Tasks**
- Enhanced session picker with tmux window management
- Background task queue for autonomous Claude operations
- HA Tools quick-access menu

**Home Assistant Assist Integration**
- Optional conversation agent bridge to Claude Code
- Event-based communication for voice/text assistant

**Home Assistant Automation Integration**
- File-based task queue for automation-triggered Claude tasks
- Optional notifications on task completion
- Completion events for automation chaining
