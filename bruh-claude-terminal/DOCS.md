# BRUH Claude Terminal Documentation

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

## Configuration Reference

Every option from the add-on **Configuration** tab, grouped by what it controls. All defaults match `config.yaml` as shipped; the Supervisor validates each value against the schema before the add-on starts.

### Startup behaviour

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auto_launch_claude` | bool | `true` | Launch Claude Code immediately in the web terminal. Turn off if you'd rather land on the shell and choose a session yourself (`claude-session-picker.sh`). |
| `auto_generate_context` | bool | `true` | Regenerate `/config/CLAUDE.md` on every startup with a fresh snapshot of your HA install — entity counts by domain, automation list + states, installed add-ons and integrations, and a file-tree guide. Claude Code reads this file at the start of each session so it understands your setup without you having to explain it. |
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

## Permissions (dangerously_skip_permissions)

Claude Code has a `--dangerously-skip-permissions` flag that tells it to execute tool calls (file edits, shell commands, MCP tool calls) without asking for interactive confirmation on each action.

### Why the app uses this flag

Inside the Home Assistant app container, Claude Code runs in a sandboxed environment:
- It can only access `/config` (your HA configuration) and `/data` (persistent app storage)
- It runs as a non-root user (UID 1000), not as root — this is required because the flag refuses to work as root
- It cannot access the host OS, other apps, or the HA Core container

### How it applies to different channels

| Channel | Permission flag | Configurable? | Why |
|---------|----------------|---------------|-----|
| **Interactive terminal** | Controlled by config | Yes | You can choose to approve each action manually |
| **Conversation agents** (Assist) | Always on | No | Runs non-interactively — cannot prompt for approval |
| **Automation tasks** | Always on | No | Runs non-interactively — cannot prompt for approval |

**Conversation agents and automation tasks always use `--dangerously-skip-permissions`** regardless of the config setting. Without this flag, non-interactive Claude Code invocations would either silently fail or return permission prompts as text responses instead of executing the requested action.

Additionally, the app writes a `settings.local.json` file that pre-allows all MCP tools (like `control_light`, `call_service`, etc.) as a belt-and-suspenders safeguard.

### Configuration

The `dangerously_skip_permissions` config option **only affects the interactive terminal**:

- **`false` (default):** The terminal will prompt for confirmation before each tool call. This is the safer mode and the right choice while you're still learning what Claude will do to your HA config.
- **`true`:** The terminal runs Claude Code without per-action confirmation prompts. Conversation agents and automation tasks are **not affected** by this toggle — they always skip permissions regardless of the setting.

To change: go to **Settings > Apps > BRUH Claude Terminal > Configuration**.

### OAuth Authentication

After an add-on update, you may need to re-authenticate with Anthropic in the terminal. This does not affect conversation agents that are already configured — they will continue to work as long as the stored OAuth credentials are valid. If conversation agents start returning auth errors, open the terminal and complete the OAuth login.

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

## Debugging & Logs

The app writes detailed debug logs for every conversation agent and automation task request. These help you understand what's being sent to Claude, how long it takes, and what comes back.

### Log locations

| Log file | Contents |
|----------|----------|
| `/config/.bruh_claude/logs/assist-YYYYMMDD.log` | Conversation agent (Assist) requests and responses |
| `/config/.bruh_claude/logs/automation-YYYYMMDD.log` | Automation task requests and results |

### What's logged for each request

- **Channel** — whether the request came from the conversation agent or automation
- **User text** — what the user said
- **Model** — which Claude model was used
- **History turns** — how many prior conversation turns were included
- **Prompt size** — total characters sent to Claude
- **Flags** — what CLI flags were passed (e.g., `--dangerously-skip-permissions`)
- **Duration** — wall-clock time for the Claude invocation
- **Response size** — characters and lines in the response
- **Token/cost info** — extracted from Claude Code's stderr output (when available)
- **Response preview** — first 200 characters of the response
- **Stderr output** — any errors or diagnostics from Claude Code

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

For startup issues and overall add-on health, check the add-on logs in Settings > Apps > BRUH Claude Terminal > Log tab, or:
```bash
ha-log addon bruh_claude_terminal
```

## MCP Server

The built-in MCP server gives Claude Code these capabilities:

| Tool | Description |
|------|-------------|
| `get_entity_state` | Get current state of any entity |
| `get_all_states` | List all entities (filterable by domain) |
| `get_areas` | List all areas (rooms) and the entity_ids in each — resolve "the kitchen lights" to entity_ids |
| `call_service` | Call any HA service (turn on lights, etc.) |
| `get_service_details` | Get the service schema for a domain |
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

> Verify the MCP server and all tools on your install by running **`ha-selftest`** in the terminal — it drives the server end-to-end and reports any tool that errors.

## Automation Integration

To trigger Claude tasks from automations, create a JSON file in `/data/automation-tasks/`:

```yaml
# Example HA automation
automation:
  - alias: "Morning Claude Report"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: shell_command.create_claude_task
        data:
          command: >
            echo '{"prompt": "Check my HA error log and summarize any issues from the last 24 hours", "notify": true, "notify_entity": "notify.mobile_app"}' > /config/claude-tasks/morning_report.json

# In configuration.yaml
shell_command:
  create_claude_task: "cp /config/claude-tasks/{{ task }}.json /data/automation-tasks/"
```

## BRUH Claude Integration

The BRUH Claude integration is automatically discovered when the add-on starts. It provides:

- **Conversation Agent** - Select "BRUH Claude" as a conversation agent in Settings > Voice Assistants
- **`bruh_claude.send_prompt`** service - Send a one-shot prompt to Claude and get a response
- **`bruh_claude.run_task`** service - Run a Claude task with optional completion notification

### Assist Integration

When the integration is set up, "BRUH Claude" appears as a conversation agent in Settings > Voice Assistants. Select it as your default assistant to route voice/text queries through Claude.

New conversation agents default to **Claude Haiku** for snappy voice
responses; pick a different model per agent in the integration's options
(`Default` inherits whatever model the terminal uses).

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
