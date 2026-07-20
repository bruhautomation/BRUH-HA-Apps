# Changelog

## 1.1.1

- **Sidebar naming**: the ingress panel is now titled "BRUH Insights"
  (was "Insights") to match the BRUH family branding.

## 1.1.0

- **Shared login with BRUH Terminal**: if the BRUH Terminal add-on has shared its Claude
  credential (`ha-share-login` there), Insights picks it up automatically — no more
  copying tokens between add-ons. A locally connected credential always wins, and
  signing out of Insights never touches the shared login. The auth chip shows
  "Claude · shared login" when the shared credential is in use
- **Insight history with a date selector**: every category run is kept as a dated copy
  (custom question cards excluded). Each card's footer grows a run selector plus ‹/›
  step buttons — pick a past run to view it in place, with a "Back to latest" pill and
  small "prev:" comparisons on the highlight stats. Retention is configurable via the
  new `history_keep_runs` (default 40) and `history_keep_days` (default 30) options;
  set either to 0 to disable history
- **Editable per-category prompts**: the new ✎ button on each card opens an editor for
  that category's analysis focus, an enable/disable toggle, and an optional per-category
  refresh interval. Overridden cards show a "custom prompt" badge; disabled categories
  are dimmed and skipped by auto-refresh and "Refresh all". The scheduler now refreshes
  each category on its own clock instead of re-queueing everything at once
- **Questions, findings, and memory**: the analyst can now ask up to two clarifying
  questions per insight (answer them inline on the card) and record durable findings
  about your home. Both are handed to the `bruh_claude` integration
  (`add_memory` / `answer_question`) when it's installed, with a `/share` inbox fallback
  for the BRUH Terminal add-on to ingest; learned facts in
  `/config/.bruh_claude/memory/memory.md` are folded into every data snapshot (context
  budget raised to ~4000 chars, and learned context now outlives raw entity rows when
  the bundle is trimmed)

## 1.0.4

- Fix insight generation failing with "max number of turns": tools are now disallowed
  outright for generation runs (insights are pure generation over the data snapshot),
  so the model can no longer burn its turn limit attempting tool calls; turn margin
  raised as well, and the error message is friendlier if it ever recurs
- Smoother guided sign-in: the status poll now survives transient connection drops
  (mobile apps suspend the webview in the background — previously the UI could stay
  frozen on "Exchanging code…" after sign-in had already succeeded), returning to the
  tab refreshes state immediately, elapsed time is shown during the exchange, and the
  silent-exchange nudges fire earlier (10s/30s/75s)
- Unified BRUH Apps branding: new "Solid Blocks" icon, logo, and favicon from the
  BRUH Automation brand system; panel restyled with the brand palette (azure/sky on
  navy) in dark and light mode

## 1.0.3

- Fix the "Exchanging code…" watchdog never firing on a *silent* hang: it only ran
  when the CLI produced output, and a hung exchange produces none. It now runs on
  every tick, so a dead exchange errors out after 2 minutes with a clear message
- Treat the CLI's saved credential file (`~/.claude/.credentials.json`) as sign-in
  success — some CLI versions save the credential without printing a token to the
  terminal, which previously looked like a hang even though sign-in had worked
- Recognize an existing CLI login as a valid connection (auth type `cli_login`);
  sign-out now clears it too
- Press Enter into a silent exchange at 45s/90s in case an unknown confirmation
  screen is blocking the CLI
- Log the guided sign-in's CLI output (token-masked) to the add-on log so stuck
  flows are actually diagnosable

## 1.0.2

- Fix guided sign-in hanging forever on "Exchanging code…": when the code exchange
  fails, the Claude CLI prints "OAuth error … Press Enter to retry." and blocks —
  the flow now detects this, presses Enter for you, surfaces the error, and offers
  the **fresh** sign-in link the CLI mints on retry (the old page's code is dead
  after a failed attempt, so re-pasting it can never work)
- Add a 2-minute watchdog on the code exchange so the panel errors out with the
  CLI's output instead of hanging silently
- "Start sign-in" now tears down a dead or wedged previous flow instead of
  silently re-attaching to it; reloading the page mid-flow still reattaches to a
  healthy one
- Show live CLI status under the phase chip while exchanging, keep the Cancel
  button reachable during the exchange, and clear the stale code box when a fresh
  link arrives
- Accept future token prefixes (`sk-ant-oatNN-…`)

## 1.0.1

- Fix guided Claude sign-in showing a truncated OAuth link ("Invalid OAuth Request:
  Missing redirect_uri parameter"): the pty terminal hard-wrapped the very long
  authorize URL and only the first line was captured. The setup flow now runs the
  CLI in an ultra-wide pseudo-terminal, stitches wrapped URL lines back together as
  a fallback, and never surfaces a link that lost its OAuth query parameters.

## 1.0.0

Initial release 🎉

- Ingress **Insights** panel in the Home Assistant sidebar
- Nine insight categories: Overview, Energy, Climate, Lighting, Security, Presence, Media,
  Device Health, Automations — plus free-form "ask anything" cards
- Claude-generated interactive visualizations: self-contained HTML with animations, hover
  tooltips, light/dark mode, and a colorblind-safe chart palette, rendered in sandboxed
  iframes
- Works with a Claude subscription (Pro/Max) via guided `claude setup-token` sign-in or a
  pasted token; Anthropic API keys also supported
- Data collection via Supervisor REST + WebSocket APIs: states with areas/friendly names,
  downsampled history, long-term energy statistics — size-capped for prompt budget
- Single-worker generation queue, scheduled auto-refresh (`auto_refresh_hours`), persistent
  insights across restarts
