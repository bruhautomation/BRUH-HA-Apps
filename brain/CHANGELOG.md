# Changelog

All notable changes to **BRain**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

## 1.1.1

- **Signing in once is now enough.** Signing in through the panel still left the
  terminal asking for a login. Credential sharing was built when Terminal and
  Insights were separate add-ons and only ran one way: the terminal's
  `ha login` published a credential the panel read. Merged into one add-on the
  panel became the primary sign-in surface, so the arrow has to point both ways.
  A single resolver now hands whatever credential exists to the CLI — used by
  both the `claude-run` wrapper and interactive shells.

  If the CLI already holds its own OAuth login it is left strictly alone: it
  refreshes that credential itself, and injecting a token over the top would
  break the refresh.

## 1.1.0

### The panel is finally one product

- **Three tabs: Insights, Terminal, Memory.** The terminal is the same ttyd
  the add-on already ran, reverse-proxied through the panel, so it is a tab
  rather than a second sidebar entry. The frame only connects when you first
  open the tab — no shell session is started for someone who never does.
- **Memory is a tab, not a dialog.** The same pane, promoted out of the modal
  it was hidden in.

### Fixed

- **The panel still said "BRUH Insights" in its header, and drew the Insights
  bar-chart glyph.** The wordmark is split across HTML tags
  (`BRUH <span>Insights</span>`), so the rename never matched it. It now reads
  **BRain** with the neural-mesh mark. A test now strips tags before checking,
  so this class of miss can't come back.
- **Several hints told you to go run a command in "the BRain add-on" — from
  inside BRain.** They were inherited from when Terminal and Insights were
  separate. They now point at the Terminal tab.
- **Retired CLI names in the UI.** `ha-share-login` and `ha-memory` no longer
  exist; the panel referenced both.
- **A new agent defaulted to the name "Claude Agent"** instead of "BRain Agent".

### Branding

- Added `logo.png` / `logo@2x.png` for the home-assistant/brands submission.
  Until that PR merges, Home Assistant has no artwork for the `brain` domain
  and shows the raw domain beside the name — which is why a fresh install
  reads "brain BRain". Nothing in this repo can change that; see
  `brands/README.md`.

## 1.0.1

- **Fixed the panel's login failing with `su-exec: claude: No such file or directory`.**
  The CLI was looked up with the root user's `PATH` and then executed as the
  `claude` user. The binary lives at `/root/.local/bin/claude`, which is on neither
  user's `PATH`, so the lookup fell through to the bare name `claude` and su-exec
  couldn't find it. The panel now prefers the `claude-run` wrapper and otherwise
  resolves an absolute path.
- **BRUH Terminal and BRUH Insights are removed.** BRain replaces both; their test
  suites now cover BRain.
- **Renamed the files that were ours rather than Claude Code's**: `claude_client.py`
  is now `panel/engine.py`, and the session picker and auth helper are
  `brain-menu.sh` and `brain-auth-helper.sh`. `CLAUDE.md`, `CLAUDE_CONFIG_DIR`, the
  `claude` user, and the `claude-run` wrapper keep the name — they *are* Claude
  Code's own file, env var, user, and binary.

## 1.0.0

First release. BRain replaces **BRUH Terminal** and **BRUH Insights**, which are now
deprecated. It is a clean install — there is no migration from either add-on.

### One add-on, one brain

- **The terminal and the insights dashboard now share a process.** They were two
  containers, which meant authenticating Claude twice, two Claude clients, two settings
  stores, and two writers racing on one memory file. Now it's one of each.
- **One ingress panel** serves everything. The panel owns port 8099 and
  reverse-proxies `/terminal/` through to ttyd (HTTP + WebSocket), so the terminal is a
  tab rather than a second sidebar entry. Port 7681 is still published for direct
  access. `enable_terminal` / `enable_insights` turn either face off.
- **The assist worker pool moved to port 8098**, since 8099 now belongs to the panel.
  Nothing hardcodes it — the integration reads the port from the endpoint file the pool
  publishes.

### Renamed

- Integration domain is **`brain`**: services are `brain.send_prompt`,
  `brain.run_task`, and the rest, including all 56 Power Tools.
- Shared state moved from `/config/.bruh_claude/` to **`/config/.brain/`**.
- Environment variables use the `BRAIN_` prefix.
- The conversation agent appears as **BRain** in Settings → Voice Assistants.
- `assist_learning` is now just **`learning`** — it governs everything BRain learns,
  not only the voice channel.

### The CLI is two commands

Fourteen `ha-*` scripts collapse into two dispatchers, split by what they act on:

- **`brain`** — its own faculties: `brain memory`, `brain learn`, `brain ask`,
  `brain undo`, `brain doctor`
- **`ha`** — Home Assistant operations: `ha log`, `ha reload`, `ha entity`,
  `ha service`, `ha addon`, `ha notify`, `ha share`, `ha check`, `ha context`

`brain help` and `ha help` list everything. If a pre-existing `ha` command is ever
found on `PATH`, BRain installs its own as `hass` instead rather than shadowing it.

### Git auto-backup is gone, replaced by something narrower

- **Removed** `auto_backup`, `backup_interval_minutes`, the 30-minute commit watcher,
  and the `.gitignore` management that came with them. Versioning the whole of
  `/config` inside `/config` duplicated what a real Home Assistant backup already does,
  and the repo it grew was then swept into those backups.
- **Added an edit journal instead.** A `PreToolUse` hook snapshots a file's prior
  contents before Claude writes to it, and **`brain undo`** lists those edits in plain
  English and restores one. It records only what Claude touched, lives under `/data`
  so it never pollutes the config directory, and prunes on `edit_journal_days`
  (default 14).
- Existing `/config/.git` directories are left strictly alone. BRain no longer writes
  to them; delete yours if you don't want it.
- The `git` binary is still installed — it's useful in a terminal.
