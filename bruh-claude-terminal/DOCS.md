# BRUH Terminal Documentation

> **Prefer the web?** This same documentation, with diagrams and a polished layout, lives at
> [bruhautomation.com/bruh-claude](https://bruhautomation.com/bruh-claude/) —
> [Quick Start](https://bruhautomation.com/bruh-claude/quickstart/) ·
> [Reference](https://bruhautomation.com/bruh-claude/reference/) ·
> [Changelog](https://bruhautomation.com/bruh-claude/changelog/).

## Contents

- [Quick start](#quick-start)
- [Restart requirements](#restart-requirements)
- [Configuration reference](#configuration-reference)
- [Permissions](#permissions)
- [Sharing your login with other BRUH add-ons](#sharing-your-login-with-other-bruh-add-ons)
- [Memory & learning](#memory--learning)
- [CLI tools](#cli-tools-reference)
- [Insight jobs](#insight-jobs-scheduled-claude-reports)
- [MCP server](#mcp-server)
- [Voice & automation integration](#bruh-claude-integration)
- [Power Tools (registry services)](#power-tools-registry-management-services)
- [Transport & health](#transport--health)
- [Using the terminal on mobile](#using-the-terminal-on-ios--android)
- [Troubleshooting](#troubleshooting)
- [Debugging & logs](#debugging--logs)
- [Changelog & releases](#changelog--releases)
- [Support](#support) · [License](#license)

## Quick Start

1. Install the app from the BRUH HA Apps repository
2. Start the app — it will open a web terminal
3. **Restart Home Assistant** (Settings > System > Restart) so HA loads the BRUH Claude integration
4. Home Assistant will automatically discover the BRUH Claude integration and prompt you to set it up via a notification in Settings > Devices & Services
5. Authenticate with your Anthropic account
6. Claude Code now has full access to your HA config and live API

> **Note:** The BRUH Claude integration is discovered automatically when the app starts. If you prefer manual setup, go to Settings > Devices & Services > Add Integration > BRUH Claude.

## Restart Requirements

The BRUH Claude app deploys a custom Home Assistant integration (`custom_components/bruh_claude/`) that provides the conversation agent and services. Because HA Core only loads custom component Python code at startup, **a restart is required** in the following situations:

| Scenario | Restart Required? | Why |
|----------|-------------------|-----|
| **First install** | **Yes** | HA Core must load the new `bruh_claude` custom component before the integration can be discovered or configured. |
| **App upgrade** (version change) | **Yes** | Updated Python files are deployed to `custom_components/`, but HA Core won't pick up the new code until it restarts. |
| **App restart** (same version) | No | The integration files haven't changed, and HA Core already has the current code loaded. |
| **Disconnect & reconnect integration** | No (but doesn't reload code) | Removing and re-adding the integration in Devices & Services re-runs the config flow but does **not** reload the Python module from disk. If the underlying code changed, you still need a full HA restart. |

**How you'll know:** The app sends a persistent notification to the HA UI when a restart is needed. You'll also see a prominent banner in the app logs.

**To restart:** Go to **Settings > System > Restart**, then check **Settings > Devices & Services** for BRUH Claude.

## Update Not Showing Up?

The Supervisor only re-pulls add-on repositories periodically, so a freshly
released version (what you see in this repo's CHANGELOG on GitHub) can take a
while to appear as an update in your instance — the store page keeps showing
the version from its last refresh until then.

To pick it up immediately: **Settings > Add-ons > Add-on Store > ⋮ (top
right) > Check for updates**, then go back to the add-on page. (`ha store
reload` from the SSH add-on does the same.)

## "Icon Not Available" on Device Pages?

Cosmetic only: Home Assistant loads integration branding from its central
[brands repository](https://github.com/home-assistant/brands), never from
the integration's own files. Ready-to-submit assets and the 3-step,
one-time submission guide live in [`brands/`](../brands/README.md) at the
repo root; icons appear for everyone once that PR merges.

## Configuration Reference

Every option from the add-on **Configuration** tab, grouped by what it controls. All defaults match `config.yaml` as shipped; the Supervisor validates each value against the schema before the add-on starts.

### Startup behaviour

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_launch_claude` | bool | `true` | Launch Claude Code immediately in the web terminal. Turn off if you'd rather land on the shell and choose a session yourself (`claude-session-picker.sh`). |
| `auto_generate_context` | bool | `true` | Regenerate `/config/CLAUDE.md` on every startup with a fresh snapshot of your HA install — entity counts by domain, automation list + states, installed add-ons and integrations, and a file-tree guide. Claude Code reads this file at the start of each session so it understands your setup without you having to explain it. |
| `enable_mobile_ui` | bool | `true` | Splice the mobile touch toolbar and iOS fixes into the web terminal. Set `false` to fall back to ttyd's stock UI (the add-on also falls back automatically if the startup probe that builds the custom UI fails). |
| `log_level` | `trace \| debug \| info \| notice \| warning \| error \| fatal` | `info` | Verbosity of the add-on's own startup log (the orange text in the add-on **Log** tab). Set to `debug` or `trace` when filing a bug report. |

### Config backup

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_backup` | bool | `true` | Enable the git-based backup of `/config`. The add-on initialises a git repo on first boot, writes a sensible `.gitignore` (excludes secrets, DBs, logs), and a background watcher commits changes on the configured interval. |
| `backup_interval_minutes` | 5–1440 | `30` | Minutes between auto-commits by the background watcher. Lower = more history, more churn in the repo; higher = lighter but less granular. `ha-backup` triggers an on-demand commit any time. |

### Native HA integrations

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_ha_mcp_server` | bool | `true` | Start the built-in MCP server that gives Claude entity states, service calls, automation traces, template rendering, logs, and config reloads. See the **MCP Server** section for the full tool list. |
| `enable_assist_integration` | bool | `true` | Run the Assist listener. When the Voice Assistants pipeline routes a message to **BRUH Claude** (or a service call hits `bruh_claude.send_prompt`), the add-on picks it up from `/config/.bruh_claude/` and runs Claude Code to generate the response. |
| `assist_fast_mode` | bool | `true` | Keep pre-warmed Claude worker processes alive for the Assist channel (one per active conversation plus a hot spare), so voice turns skip the CLI boot and MCP handshake. Costs ~150–300 MB RAM per warm worker (max 3). Set to `false` to use the classic spawn-per-request listener. |
| `enable_automation_integration` | bool | `true` | Run the Automation listener. Drop a JSON task into `/data/automation-tasks/` (or call `bruh_claude.run_task`) and the add-on executes it with Claude Code in the background, optionally notifying you when it's done. |

### Non-interactive turn budgets

These cap how many agentic loops Claude runs before returning. Lower values are cheaper and faster but may truncate complex tasks; higher values give Claude more room to chain tool calls.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `assist_max_turns` | 1–20 | `5` | Per-request turn cap for the Assist conversation agent. Passed as `--max-turns` to Claude Code. 5 is enough for the common "check/toggle/summarise" flows; bump it if you see replies getting cut off mid-thought. |
| `automation_max_turns` | 1–50 | `10` | Per-request turn cap for the Automation listener. Automation tasks typically need more turns than Assist because they're doing multi-step work unattended (read log → analyse → write report → notify). |

### Memory & learning options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `assist_learning` | bool | `true` | Master switch for the learning loop: the background memory consolidator and the end-of-conversation reflection pass that extracts durable facts from voice conversations. Turn off to stop Claude from learning anything new (existing memory is untouched). |
| `memory_injection` | bool | `true` | Splice the learned home knowledge (the `voice.md` distillate, ≤2 KB) into voice system prompts. Turn off to keep memory out of prompts entirely. |
| `memory_max_kb` | 1–64 | `8` | Size cap for `memory.md`. The consolidator drops the lowest-value/oldest facts first to stay under it. |

See [Memory & learning](#memory--learning) for how the system works and how to view, edit, or clear what Claude knows.

### Assist tool scoping

Two layers, from coarse to fine:

1. **`assist_tool_access`** (add-on option, below) — the coarse switch:
   `mcp_only` (default) lets voice use every HA MCP tool but blocks shell,
   file read/write, and web for ALL voice agents.
2. **Per-agent Blocked services** (in each agent's config) — a picker of
   service patterns that specific agent may never call, e.g. `lock.unlock`
   or `alarm_control_panel.*`. Enforced in the MCP server's `call_service`
   chokepoint, so it covers every device tool and phrasing — not just the
   generic call. Pick common risky ones, choose a whole `domain.*`, or type
   your own. Each agent has its own list; empty allows everything.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `assist_tool_access` | `mcp_only` / `full` | `mcp_only` | What the voice channel may do. `mcp_only` allows every Home Assistant MCP tool (full device control, cameras, history, any service call) but denies shell commands and ALL file access (read and write) plus web access — so voice cannot author automations or read secrets.yaml. Automations and the terminal keep full access. Set `full` to lift the restriction for voice too. |

### Terminal permissions

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dangerously_skip_permissions` | bool | `false` | Interactive-terminal only. When `true`, Claude Code skips the per-action confirmation prompt. Conversation agents and automation tasks always skip permissions regardless of this setting (they have no way to prompt). See the **Permissions** section below for the full story. |

### Volume access

The add-on manifest bind-mounts `/share`, `/media`, `/backup`, `/addon_configs`, and `/addons` into the container. The toggles below decide whether Claude Code actually sees them (the env vars `SHARE_DIR`, `MEDIA_DIR`, etc. are only exported when the corresponding toggle is on). Turning one off is a defence-in-depth measure — it does not physically unmount the path, but Claude's tools won't be pointed at it.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `access_share` | bool | `true` | Expose `/share` (HA's shared folder). |
| `access_media` | bool | `true` | Expose `/media` (HA's media library). |
| `access_backup` | bool | `true` | Expose `/backup` (HA's snapshot folder, read-only). |
| `access_addon_configs` | bool | `true` | Expose `/addon_configs/` (every other add-on's config folder). Useful for asking Claude to diagnose a neighbour add-on. |
| `access_addons` | bool | `true` | Expose `/addons` (the HA local add-ons folder). Useful when you're developing an add-on alongside this one. |
| `additional_directories` | list of absolute paths | `[]` | Extra container paths to hand to Claude Code. Each entry must resolve to an existing directory inside the container — missing paths are logged and skipped. The add-on also `chown`s them to the non-root `claude` user so edits work. |

### Persistent packages

These let you keep packages installed across container restarts (the add-on container is otherwise rebuilt fresh on every update).

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `persistent_apk_packages` | list of strings | `[]` | Alpine `apk` packages to install on startup. Example: `["vim", "htop", "ripgrep"]`. Managed identically to running `persist-install apk <name>` from the terminal. |
| `persistent_pip_packages` | list of strings | `[]` | Python `pip` packages to install on startup. Example: `["pandas", "numpy"]`. Managed identically to `persist-install pip <name>`. |

## Permissions

Claude Code normally asks before each tool call. The add-on handles this differently per channel:

| Channel | Mechanism | Default access |
|---------|-----------|----------------|
| **Interactive terminal** | Prompts, unless `dangerously_skip_permissions: true` | Everything (you approve actions) |
| **Voice / conversation agents** | Pre-approved allowlist + `assist_tool_access` deny-list | All HA MCP tools; **no** shell, file read/write, or web (`mcp_only`) |
| **Automation tasks & insight jobs** | Pre-approved allowlist | All tools (MCP, shell, file edits, web) |

Background channels never use `--dangerously-skip-permissions` — they can't prompt, so the add-on writes `/config/.claude/settings.local.json` pre-approving the tools they need. The voice channel additionally loads a deny-list (see `assist_tool_access` above) so a voice request can control the whole house but can't run shell commands or edit files.

Everything runs sandboxed: non-root (UID 1000), access limited to `/config`, `/data`, and the volume toggles above — never the host OS or other containers.

### Configuration

The `dangerously_skip_permissions` config option **only affects the interactive terminal**:

- **`false` (default):** The terminal will prompt for confirmation before each tool call. This is the safer mode and the right choice while you're still learning what Claude will do to your HA config.
- **`true`:** The terminal runs Claude Code without per-action confirmation prompts. Conversation agents and automation tasks are **not affected** by this toggle — they always skip permissions regardless of the setting.

To change: go to **Settings > Apps > BRUH Terminal > Configuration**.

### OAuth Authentication

After an add-on update, you may need to re-authenticate with Anthropic in the terminal. This does not affect conversation agents that are already configured — they will continue to work as long as the stored OAuth credentials are valid. If conversation agents start returning auth errors, open the terminal and complete the OAuth login.

## Sharing your login with other BRUH add-ons

Log in once, use everywhere: `ha-share-login` runs the Claude OAuth
token flow (`claude setup-token`) right in the terminal, captures the
generated long-lived token, and writes it to a shared file that other
BRUH add-ons — like **BRUH Insights** — pick up automatically:

```bash
ha-share-login              # interactive OAuth flow, then share the token
ha-share-login --status     # is a shared login present, and since when?
ha-share-login --revoke     # delete the shared file (revoke the token at Anthropic)
ha-share-login --token sk-ant-oat...   # paste a token you already have
```

The shared file lives at `/config/.bruh_claude/secrets/claude_auth.json`
(mode 0600, directory 0700, owned by the non-root `claude` user) and
contains only the token and a `saved_at` timestamp. Deleting the file
(`--revoke`) stops other add-ons from using it, but the token itself
stays valid until you revoke it in your Anthropic account settings.

If you're already logged in but haven't shared the login, the add-on
logs a one-line reminder at startup.

## Memory & Learning

The add-on maintains a small long-term memory about your home at
`/config/.bruh_claude/memory/`:

| File | What it is |
|------|------------|
| `memory.md` | The canonical knowledge file — preferences, entity nicknames, household patterns, device notes. **User-editable**; capped at `memory_max_kb` (default 8 KB). |
| `voice.md` | A ≤2 KB distillate generated by the consolidator — the part spliced into every voice prompt. |
| `inbox/` | Append-only candidate facts (JSONL) waiting to be consolidated. |
| `questions.jsonl` | Open questions Claude wants answered, plus their answers. |

### How it learns

- **You tell it**: say "remember that..." to a voice assistant (the
  `remember_fact` MCP tool stores it instantly), run
  `ha-memory add "..."` in the terminal, or call the
  `bruh_claude.add_memory` service from an automation.
- **It notices**: when a voice conversation ends, a bounded background
  reflection pass (cheap Haiku, no tools, ~60 s budget) extracts up to 3
  durable facts — preferences, corrections, nicknames — and queues them.
  Transient states, one-off commands, and secrets are excluded.
- **Other add-ons contribute**: BRUH add-ons without the integration drop
  facts into `/share/bruh_claude/memory-inbox/`, which the consolidator
  sweeps in.

A background **consolidator** merges the inbox into `memory.md` +
`voice.md` once a day, or early when more than 20 facts are pending —
deduping, resolving contradictions newest-wins, and enforcing the size
cap. Questions unanswered for 21 days are retired automatically.

Learned knowledge is used in three places: voice system prompts
(`voice.md`), insight jobs (which also receive their previous report for
continuity), and the generated `/config/CLAUDE.md` context.

### Viewing, editing, clearing

```bash
ha-memory list                        # what Claude knows
ha-memory inbox                       # facts awaiting consolidation
ha-memory add "Guests use the loft"   # queue a fact yourself
ha-memory questions                   # open questions Claude has
ha-memory answer "<question>" "<answer>"
ha-memory consolidate                 # run a consolidation pass now
ha-memory edit                        # open memory.md in $EDITOR
ha-memory clear --confirm             # reset (old file kept as memory.md.bak)
```

`memory.md` is plain markdown — edit it freely; your edits are the
canonical content the consolidator merges into.

### Kill switches

- `assist_learning: false` — stop learning (no reflection, no consolidator).
- `memory_injection: false` — stop using memory in voice prompts.
- `ha-memory clear --confirm` — forget everything learned so far.

### Services

```yaml
# Queue a fact from an automation
service: bruh_claude.add_memory
data:
  fact: "The dog gets fed at 7 and 17 — kitchen lights on at those times means feeding time"
  confidence: high     # high | medium | low (default medium)

# Answer an open memory question
service: bruh_claude.answer_question
data:
  question: "Which thermostat schedule applies on holidays?"
  answer: "Treat holidays like weekends"
```

## CLI Tools Reference

### ha-reload

Reload Home Assistant configurations after editing YAML files.

```bash
ha-reload automations     # Reload automations
ha-reload scripts         # Reload scripts
ha-reload scenes          # Reload scenes
ha-reload groups          # Reload groups
ha-reload core            # Reload core configuration
ha-reload all             # Reload everything
ha-reload check           # Validate configuration (no reload)
```

### ha-log

View Home Assistant logs.

```bash
ha-log core               # Core logs (last 100 lines)
ha-log supervisor         # Supervisor logs
ha-log host               # Host system logs
ha-log addon mosquitto    # Specific add-on logs
ha-log errors             # Filter for errors/warnings only
ha-log all                # Core + supervisor + errors
ha-log core -f            # Follow mode (real-time)
ha-log core -n 50         # Last 50 lines
```

### ha-backup

Git-based configuration backup.

```bash
ha-backup                           # Backup with default message
ha-backup "Updated automations"     # Backup with custom message
ha-backup history                   # View backup history
ha-backup diff                      # Show changes since last backup
ha-backup diff HEAD~3               # Show changes since 3 backups ago
ha-backup restore automations.yaml  # Restore a file from previous backup
```

### ha-context-gen

Regenerate the CLAUDE.md context file with current HA system information.

```bash
ha-context-gen
```

### persist-install

Install packages that survive container restarts.

```bash
persist-install apk vim htop        # Install Alpine packages
persist-install pip pandas numpy    # Install Python packages
persist-install list                # List persistent packages
persist-install remove apk vim      # Remove from persistence
```

### ha-memory

Inspect and manage Claude's long-term home memory (see
[Memory & learning](#memory--learning)).

```bash
ha-memory add "We call the office lamp 'the beacon'"
ha-memory list
ha-memory inbox
ha-memory questions
ha-memory answer "<question>" "<answer>"
ha-memory consolidate
ha-memory edit
ha-memory clear --confirm
```

### ha-share-login

Share your Claude login with other BRUH add-ons (see
[Sharing your login](#sharing-your-login-with-other-bruh-add-ons)).

```bash
ha-share-login             # interactive OAuth flow + share
ha-share-login --status
ha-share-login --revoke
```

### ha-selftest

Run a full in-situ diagnostic of the add-on. It checks HA API auth, drives
the MCP server end-to-end (initialize, tool list, and live `get_ha_config`
/ `get_all_states` / `get_areas` calls), and verifies the deployed
integration, the background listeners, your Claude login, and the usage
sensors — printing PASS/FAIL with a fix hint for anything wrong.

```bash
ha-selftest
```

Use it after first install, after an update, or any time Assist /
automations / sensors aren't behaving — it's the quickest way to localize
the problem.

## Using the Terminal on iOS / Android

The web terminal auto-detects touch devices and shows an on-screen toolbar above the software keyboard with the keys iOS doesn't give you.

### Mobile toolbar

Every button sends a complete action on its own — no sticky modifiers.
The row scrolls horizontally if it overflows.

| Key | Sends | Notes |
|-----|-------|-------|
| `ESC` | `␛` | Claude Code's interrupt / close-menu key. Highlighted in orange. |
| `▾ Kbd` | (blur) | Closes the on-screen keyboard. Tap the terminal to reopen it. |
| `Tab` / `⇧Tab` | `\t` / `Shift+Tab` | Tab-complete / menu nav; `⇧Tab` toggles Claude Code's mode. |
| `↑ ↓ ← →` | arrow keys | Shell history / cursor movement within the input. |
| `PgUp` / `PgDn` | `PageUp` / `PageDown` | **Scroll Claude Code's chat history** one page at a time. |
| `^C` `^D` `^L` `^U` | control codes | Interrupt / EOF / clear screen / clear line. |
| `/` `@` `#` `!` <code>&#124;</code> | literal | Claude Code prefixes (slash-command, file ref, memory, bash, pipe). |
| `Paste` | clipboard | Pastes via the Web Clipboard API (iOS will ask for permission the first time). |
| `×` | hide toolbar | Reconnect to the session to bring it back. |

### Scrolling chat history

Claude Code draws its conversation in the terminal's *alternate screen*,
which has no native scrollback — so to look back at earlier messages you
drive Claude Code's own pager:

- **On mobile:** **swipe up/down with one finger** inside the terminal.
  Swipe down to go back through history, up to return to the latest. (The
  `PgUp`/`PgDn` toolbar buttons do the same thing, one page per tap.)
- **On desktop:** use the **mouse wheel / trackpad** over the terminal,
  or `PgUp`/`PgDn` on a real keyboard. Wheel scrolling is throttled so a
  trackpad doesn't fly straight to the top.

Both swipe and wheel are translated to `PgUp`/`PgDn` and sent straight to
Claude Code — they never enable terminal mouse tracking, so **long-press
text selection still works** (handy for copying an OAuth URL). A quick
tap still just focuses the terminal and opens the keyboard.

> **Tip:** running `/tui fullscreen` inside Claude Code switches on its
> flicker-free renderer, which is smoother under tmux and adds native
> mouse scroll/selection on desktop. It's optional because it turns on
> terminal mouse tracking. Run `/tui default` to switch back.

### Voice dictation

iOS voice dictation used to duplicate words in the terminal. This release turns off autocorrect/autocapitalize/spellcheck on xterm's hidden textarea and swallows the extra `input` event iOS fires right after `compositionend`, which was the root cause.

If you still see doubled words:

1. **Settings > Accessibility > Voice Control** — make sure it's **off**. Having Voice Control and keyboard Dictation on at the same time causes iOS itself to submit speech twice.
2. **Settings > General > Keyboard** — turn off **Auto-Correction**, **Check Spelling**, and **Predictive**.

### Tips

- **Add to Home Screen** on iOS gives a full-screen launcher without Safari's browser chrome. The toolbar sits right above the home-indicator safe area.
- **Bluetooth keyboard**: all real keys work — ESC, Ctrl, Option, arrows. Tap `×` to hide the on-screen toolbar if you don't need it.
- **Disable the feature**: flip `enable_mobile_ui` to `false` in the add-on config to fall back to ttyd's stock UI. The add-on also falls back automatically if the startup probe that builds the custom UI fails.

## Troubleshooting

Start with **`ha-selftest`** in the terminal — it drives the whole stack end-to-end (HA API auth, the MCP server over stdio, the deployed integration, the listeners, your Claude login, and the usage sensors) and prints PASS/FAIL with a fix hint for each part.

| Symptom | Fix |
|---------|-----|
| Add-on won't start | Check the **Log** tab. Almost always an architecture mismatch (only `amd64`/`aarch64`) or a port 7681 conflict. |
| Terminal opens then immediately closes | Update to **3.2.0 or later** — older builds broke on a Claude Code native-binary/libc mismatch. |
| Integration not discovered | Restart Home Assistant after the first add-on start, then check **Settings > Devices & Services** (or add **BRUH Claude** manually). |
| OAuth fails / "auth error" in voice | Re-authenticate in the terminal. Existing agents keep working while the stored credentials are valid. |
| Claude can't see your entities | Confirm `enable_ha_mcp_server: true`, then run `ha-selftest` — it reports any MCP tool that errors. |
| Voice replies get cut off | Raise `assist_max_turns`. |
| Voice acts on the wrong room | Run `ha-selftest` — the "Assist area map" check confirms the room map built. |
| Usage-limit sensors stay *unavailable* | They need an OAuth/subscription login, not an `ANTHROPIC_API_KEY` (see [Usage Limit Sensors](#usage-limit-sensors)). |

## Debugging & Logs

The app writes detailed debug logs for every conversation agent and automation task request. These help you understand what's being sent to Claude, how long it takes, and what comes back.

### Log locations

| Log file | Contents |
|----------|----------|
| `/config/.bruh_claude/logs/assist-YYYYMMDD.log` | Conversation agent (Assist) requests and responses |
| `/config/.bruh_claude/logs/automation-YYYYMMDD.log` | Automation task requests and results |

### What's logged for each request

- **Channel** — conversation agent (classic or fast mode) or automation
- **Text / Model / Prompt size** — what was asked, with which model, how big
- **AreaMap** — size of the area map spliced into the system prompt (0 = map missing, expect discovery turns)
- **Session / Worker** — `new`/`resume` (classic) or `warm`/`spare`/`cold`/`…+fallback` (fast mode) — tells you which speed path the request took
- **Duration** — wall-clock time for the Claude invocation
- **Response size + preview** — and stderr/token info when available

### Viewing logs

From the terminal:
```bash
# Today's conversation agent logs
cat /config/.bruh_claude/logs/assist-$(date +%Y%m%d).log

# Follow logs in real-time
tail -f /config/.bruh_claude/logs/assist-$(date +%Y%m%d).log

# Today's automation logs
cat /config/.bruh_claude/logs/automation-$(date +%Y%m%d).log

# List all log files
ls -la /config/.bruh_claude/logs/
```

### Add-on system logs

For startup issues and overall add-on health, check the add-on logs in Settings > Apps > BRUH Terminal > Log tab, or:
```bash
ha-log addon bruh_claude_terminal
```

## Insight Jobs (scheduled Claude reports)

Create them from the integration: **Settings > Devices & Services > BRUH
Claude > Add Service > Insight job**. Pick a shipped template — daily
briefing, anomaly watch, battery & maintenance, camera check — or write a
custom prompt. Custom prompts may embed HA templating
(`{{ states('sensor.outdoor_temp') }}`), rendered just before each run.

Scheduling: an interval (every N minutes), a daily time (HH:MM), both, or
neither (manual only). Each job also gets a **Run now button** on its device
page; from automations, trigger on demand with:

```yaml
service: bruh_claude.run_insight
data:
  name: "Morning Briefing"   # omit to run all jobs
```

**Viewing the report:** the sensor's *state* is just the last-run
timestamp — the report itself lives in its attributes. After a job's first
successful run you'll get a notification containing the dashboard card
ready to paste. To see it any time: Developer Tools > States > select
`sensor.<job>_insight` — `preview` shows the first lines, `markdown` the
full report, `card_yaml` the card. For a permanent view, add a Manual card
to any dashboard with:

```yaml
type: markdown
title: Morning Briefing
content: >-
  {{ state_attr('sensor.morning_briefing_insight', 'markdown')
     or 'No insight yet — run the bruh_claude.run_insight service.' }}
```

Results persist across HA restarts; failed runs keep the previous report
visible and expose the failure in the `error` attribute. Set the job's
**notify service** to push each report to a phone. A
`bruh_claude_insight_complete` event fires after every run with `name`,
`entity_id`, `success`, and a `preview` of the report — ideal for TTS
announcements.

## Transport & Health

In fast mode the worker pool serves an internal HTTP API (port 8099 on
the hassio network, token-authenticated via the shared `/config` volume).
The integration prefers it — no file polling, and voice replies stream
into the chat log so TTS starts speaking at the first sentence on
pipelines that support streaming. If the API is unreachable for any
reason, both sides fall back to the original file protocol automatically.

`binary_sensor.bruh_claude_system_assist_healthy` reports pool health
(worker count, pre-warmed spare, last request latency as attributes), and
`ha-selftest` probes the API end-to-end.

## MCP Server

The built-in MCP server gives Claude Code these capabilities:

| Tool | Description |
|------|-------------|
| `get_entity_state` | Get current state of any entity |
| `get_all_states` | List all entities (filterable by domain and name) |
| `get_areas` | List all areas (rooms) and the entity_ids in each — resolve "the kitchen lights" to entity_ids |
| `get_camera_snapshot` | **See** a camera: returns the current image so Claude can describe what's visible |
| `get_history` | Recent state history for an entity (up to 7 days), with min/max for numeric sensors |
| `get_statistics` | Long-term statistics (hourly/daily mean/min/max) — answers "how cold did it get last week" |
| `get_weather_forecast` | Daily/hourly forecast via weather.get_forecasts — "what's the weather tomorrow?" |
| `call_service` | Call any HA service (turn on lights, etc.); `return_response: true` returns service response data |
| `get_service_details` | Get the service schema for a domain |
| `get_registry` | List a registry — areas, floors, labels, devices, entities, integrations, users — with the ids the [Power Tools services](#power-tools-registry-management-services) need |
| `list_dashboards` / `get_dashboard` | Enumerate Lovelace dashboards and fetch a dashboard's full config — the read half of the `update_dashboard` edit flow |
| `control_light` | Lights: on/off/toggle, brightness, color, color-temp |
| `control_climate` | Thermostats: temperature, HVAC/preset/fan modes |
| `control_media_player` | Media players: play/pause/volume/source |
| `control_cover` | Covers/blinds/garage: open/close/position |
| `control_fan` | Fans: on/off, speed, oscillation |
| `control_switch` | Switches: on/off/toggle |
| `control_lock` | Locks: lock/unlock |
| `control_alarm` | Alarm panels: arm/disarm |
| `control_vacuum` | Vacuums: start/stop/return/clean |
| `activate_scene` | Activate a scene |
| `run_script` | Run a script (with variables) |
| `send_notification` | Send a notification |
| `get_automations` | List all automations with status |
| `get_automation_trace` | Get automation state and stored execution traces |
| `get_ha_config` | Get HA configuration details |
| `get_services` | List all available services |
| `get_device_registry` | Per-domain entity count summary (not the HA device registry — use `get_areas` for rooms) |
| `get_logbook` | Get recent logbook entries |
| `get_error_log` | Get HA logs from Supervisor journal |
| `render_template` | Render Jinja2 templates |
| `fire_event` | Fire custom events |
| `get_supervisor_info` | Get system information |
| `reload_config` | Reload configurations |
| `remember_fact` | Store a durable household fact (preference, nickname, pattern) in the memory inbox |

> Verify the MCP server and all tools on your install by running **`ha-selftest`** in the terminal — it drives the server end-to-end and reports any tool that errors.

## Automation Integration

Trigger Claude from your automations with the **`bruh_claude.run_task`** service — it runs Claude Code in the background and (optionally) notifies you when it's done. This is the supported entry point; you don't manage any files yourself.

```yaml
# Example: a morning error-log digest
automation:
  - alias: "Morning Claude Report"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: bruh_claude.run_task
        data:
          prompt: "Check my HA error log and summarize any issues from the last 24 hours"
          notify: true
          timeout: 300
```

See [Services](#services) for the full `run_task` / `send_prompt` / `run_insight` contracts. (Under the hood the listener watches `/config/.bruh_claude/tasks/`, but the service is the only interface you need.)

## BRUH Claude Integration

The BRUH Claude integration is automatically discovered when the add-on starts. It provides:

- **Conversation Agent** - Select "BRUH Claude" as a conversation agent in Settings > Voice Assistants
- **`bruh_claude.send_prompt`** service - Send a one-shot prompt to Claude and get a response
- **`bruh_claude.run_task`** service - Run a Claude task with optional completion notification
- **[Power Tools](#power-tools-registry-management-services)** - 56 registry-management admin services (areas, floors, labels, entities, devices, integrations, helpers, zones, persons, blueprints, statistics, users, diagnostics, dashboards, repairs)

### Assist Integration

When the integration is set up, "BRUH Claude" appears as a conversation agent in Settings > Voice Assistants. Select it as your default assistant to route voice/text queries through Claude.

New conversation agents default to **Claude Haiku** for snappy voice
responses; pick a different model per agent in the integration's options
(`Default` inherits whatever model the terminal uses).

#### Personalities & prompt layering

Each voice request sends Claude one system prompt built from layers:

1. **Your personality** (the agent's system prompt) — leads, with an explicit
   note that it owns identity, tone, and verbosity.
2. **Operational block** — HA capabilities: tools, the area map, timezone,
   and tool-routing rules. Deliberately identity-free so it can't fight
   your persona.

Without a personality, a built-in default applies ("helpful, efficient,
1-2 short sentences"). With one, that default is dropped entirely — so if
your persona should still be brief for TTS, say so in the persona itself,
e.g. *"…no matter how excited you get, keep spoken replies under two
sentences."*

#### Conversation memory

Follow-up prompts work within a conversation: while the same Assist chat
dialog or voice session stays open, Home Assistant keeps the same
`conversation_id`, and the add-on resumes the same Claude Code session for
each turn — Claude remembers the full conversation server-side. Starting a
new conversation (closing and reopening the Assist dialog, a new voice
session, restarting HA) gets a fresh `conversation_id` and therefore a
clean slate. Call `bruh_claude.clear_conversation` to reset a conversation
manually (omit `conversation_id` to reset all of them).

If session resume isn't possible (e.g. an older Claude CLI), the
integration falls back to replaying the last few turns of the transcript
into each request, so follow-ups still work — just with shorter memory.

### Services

```yaml
# Send a prompt and get a response
service: bruh_claude.send_prompt
data:
  prompt: "What entities are offline?"
  timeout: 120

# Run a background task with notification
service: bruh_claude.run_task
data:
  prompt: "Check my error log and summarize issues"
  notify: true
  timeout: 300
```

### Usage Limit Sensors

The integration exposes account-wide **usage limit** sensors — the same
session/weekly utilization shown on **claude.ai → Settings → Usage**.

| Sensor | Description | Key attributes |
|--------|-------------|----------------|
| Session Usage | Percent of the current 5-hour session window used | `resets_at`, `data_source`, `last_updated` |
| Session Usage Resets At | Timestamp the 5-hour window resets | `utilization` |
| Weekly Usage | Percent of the 7-day window used | `resets_at`, `data_source`, `last_updated` |
| Weekly Usage Resets At | Timestamp the 7-day window resets | `utilization` |

A background tracker (`usage-limits-tracker.py`) reads your Claude Code
OAuth token and queries the Anthropic usage endpoint every ~2 minutes,
writing `/config/.bruh_claude/usage_limits.json`; the sensors poll it every
30 seconds.

> **These sensors need an OAuth / subscription login** (the one you do in
> the terminal), **not** an `ANTHROPIC_API_KEY`. If you authenticate with an
> API key, or before you've logged in, the sensors stay **unavailable** and
> expose the reason in their `error` attribute. `ha-selftest` reports this.

## Power Tools (registry management services)

The BRUH Claude integration registers **56 admin services** that manage the
parts of Home Assistant that normally require clicking through Settings:
areas, floors, labels, entities, devices, integrations, zones, persons, and
repair issues. They give Claude (and your automations and scripts) a
**safe, supervised way** to reorganize your home — every call is validated,
runs through Home Assistant's own registry APIs, and requires admin rights.
No more hand-editing `/config/.storage` files.

Adapted from the excellent [Spook](https://github.com/frenck/spook) custom
integration by Franck Nijhof (MIT licensed), rebranded and reworked for
BRUH Claude: all services live under the `bruh_claude.*` domain (so they
never collide with Spook itself if you also run it), ids are validated
before anything changes, creation services return the new id as response
data, and destructive cleanup defaults to a dry run.

Every service appears in **Developer Tools > Actions** with full field
descriptions and pickers. The complete catalog:

| Group | Services | What they do |
|-------|----------|--------------|
| **Areas** | `create_area`, `delete_area`, `rename_area`, `set_area_aliases`, `add_device_to_area`, `remove_device_from_area`, `add_entity_to_area`, `remove_entity_from_area` | Create and organize areas, including the voice-assistant aliases |
| **Floors** | `create_floor`, `delete_floor`, `rename_floor`, `add_area_to_floor`, `remove_area_from_floor` | Group areas into floors |
| **Labels** | `create_label`, `delete_label`, `add_label`, `remove_label` | Create labels and apply/remove them on entities, devices, and areas in one call |
| **Entities** | `rename_entity`, `change_entity_id`, `enable_entity`, `disable_entity`, `hide_entity`, `unhide_entity`, `set_entity_aliases`, `set_entity_icon`, `delete_orphaned_entities` | Rename, re-ID, enable/disable, hide/unhide entities, set voice aliases and icon overrides; clean up registry entries whose integration is gone (dry-run by default, optionally scoped to an `entity_id` list with each entity re-verified as orphaned) |
| **Devices** | `rename_device`, `enable_device`, `disable_device` | Rename and enable/disable devices (disable cascades to a parent hub once no children remain enabled) |
| **Integrations** | `enable_integration`, `disable_integration`, `reload_integration` | Enable, disable, or reload integration config entries |
| **Helpers** | `create_helper`, `delete_helper` | Create and delete any storage-backed helper — `input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `counter`, `timer`, `schedule` — with the type's own options validated by its own schema |
| **Zones** | `create_zone`, `update_zone`, `delete_zone` | Create, move/resize, and delete location zones |
| **Persons** | `create_person`, `delete_person`, `add_device_tracker_to_person`, `remove_device_tracker_from_person` | Create/delete persons and attach/detach device trackers for presence detection |
| **Blueprints** | `import_blueprint` | Import an automation/script blueprint straight from a community forum, GitHub, or Gist URL |
| **Statistics** | `import_statistics` | Import or backfill long-term statistics — repair broken energy history, migrate meters, feed external data |
| **Users** | `create_user`, `delete_user`, `enable_user`, `disable_user` | Full account lifecycle, including optional local username/password logins (owner and system accounts are protected and can never be deleted or disabled) |
| **Diagnostics** | `find_orphaned_references` | Scan automations, scripts, and scenes for references to entities that no longer exist; optionally raise a repair issue |
| **Dashboards** | `create_dashboard`, `delete_dashboard`, `update_dashboard`, `restore_dashboard`, `add_dashboard_resource`, `remove_dashboard_resource` | Full dashboard lifecycle: every update (and deletion) automatically backs up the previous config, restore undoes a bad edit, and resources register custom-card modules — pair with the MCP `get_dashboard` / `list_dashboards` tools to read them |
| **Repairs** | `create_repair_issue`, `remove_repair_issue` | Surface custom issues in Settings > System > Repairs — Claude's way to flag something that needs your attention |

Examples:

```yaml
# Create an area on a floor, with voice aliases
service: bruh_claude.create_area
data:
  name: Guest Room
  icon: mdi:bed
  aliases: ["spare room"]
  floor_id: upstairs

# Label every battery-powered sensor in one call
service: bruh_claude.add_label
data:
  label_id: [battery_powered]
  entity_id: [sensor.door_battery, sensor.motion_battery]

# See what a registry cleanup would remove (nothing is deleted)
service: bruh_claude.delete_orphaned_entities
data:
  dry_run: true

# Then delete only the ones you reviewed — each is re-verified as
# orphaned; anything still alive is skipped, never deleted
service: bruh_claude.delete_orphaned_entities
data:
  dry_run: false
  entity_id:
    - sensor.old_hub_battery
    - sensor.old_hub_signal

# Let an automation flag a problem persistently
service: bruh_claude.create_repair_issue
data:
  title: "Low battery: front door lock"
  description: "The front door lock reported 8% battery. Replace soon."
  severity: warning
```

Safety notes:

- **Admin only.** Calls made by a non-admin Home Assistant user are
  rejected (calls from Claude, automations, and scripts run as admin).
- **Validated.** Unknown area/floor/label/device/entity/config-entry ids
  fail with a clear error before any change is applied.
- **Dry-run first.** `delete_orphaned_entities` only reports unless you
  explicitly pass `dry_run: false`, and `find_orphaned_references` never
  changes anything — it only reports.
- **Lockout-proof.** Unlike Spook, `disable_user` refuses to touch owner
  accounts and system-generated users — you can never lock yourself out.
- **Deliberately excluded:** a custom restart service — core
  `homeassistant.restart` already exists and accepts `safe_mode: true` on
  modern Home Assistant.

In the terminal, Claude discovers the ids these services need through the
MCP `get_registry` tool (areas, floors, labels, devices, entities,
integrations) and calls the services via `call_service` — with
`return_response` for the ones that answer back. The generated `CLAUDE.md`
context tells Claude to prefer these services over editing `.storage`
files, so "move the office lamp to the bedroom and label everything
battery-powered" just works — safely.

## Changelog & releases

This add-on follows [Semantic Versioning](https://semver.org): the version in `config.yaml` moves **MAJOR** for breaking changes, **MINOR** for new backwards-compatible features, and **PATCH** for fixes. Home Assistant only offers an update when that version changes.

- **Curated, formatted release notes:** [bruhautomation.com/bruh-claude/changelog](https://bruhautomation.com/bruh-claude/changelog/)
- **Full history:** [`CHANGELOG.md`](CHANGELOG.md) in this repository, which follows [Keep a Changelog](https://keepachangelog.com).

## Support

Got a problem or an idea?

1. Run **`ha-selftest`** in the terminal — it pinpoints most issues with a fix hint.
2. Set `log_level: debug`, reproduce, then check the add-on **Log** tab and `/config/.bruh_claude/logs/`.
3. Open an issue at [github.com/bruhautomation/BRUH-HA-Apps](https://github.com/bruhautomation/BRUH-HA-Apps/issues) with that log output.

## Authors & contributors

Built and maintained by **BRUH Automation**. Based on the excellent [Claude Terminal](https://github.com/heytcass/home-assistant-addons) add-on by Tom Cassady.

## License

MIT — see [`LICENSE`](../LICENSE) at the repository root.
