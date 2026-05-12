# Changelog

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
