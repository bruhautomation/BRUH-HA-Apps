# Changelog

All notable changes to **BRUH Insights**, newest first. This project adheres to [Semantic Versioning](https://semver.org).

> 💡 Prefer a cleaner, categorized view? See the [formatted changelog at bruhautomation.com](https://bruhautomation.com/bruh-insights/changelog/).

## 1.3.0

A depth release: the analyst now remembers, builds on what it knows, and reasons
across sensors instead of reading them one at a time.

- **Viewable memory**: the new 🧠 **Memory** button opens everything Insights has
  learned about your home — discovered facts, your answers, standing feedback — plus
  the shared memory file BRUH Terminal maintains. Remove anything that's wrong, or
  teach it a fact directly; the whole store is injected into every future analysis
- **No more repeated questions**: every clarifying question the analyst asks is
  tracked with a lifecycle (open → answered/dismissed). Asked and answered questions
  are shown to the model with a hard "never re-ask" rule, and a server-side backstop
  drops any repeat that slips through. Open questions are answerable (or dismissable)
  from the Memory panel
- **Learning that actually loops**: findings now land in Insights' own local
  knowledge base (deduplicated by content) *and* are handed to the home's shared
  memory — previously they only went to a memory inbox that required BRUH Terminal
  to be running. Known facts are fed back into every run so they're built upon, never
  rediscovered
- **Runs build on each other**: each category's previous analysis (title, summary,
  highlights, findings) is included in the next run's prompt with instructions to
  lead with what *changed* and dig deeper on what didn't — instead of regenerating
  the same surface story every refresh
- **Presence that's actually smart**: a new device-context pass walks the device
  registry and pulls in the sibling sensors living on each presence tracker's
  physical device — phone WiFi SSID, geocoded address, detected activity,
  battery/charging state — with their recent history. The analyst is instructed to
  reason like a detective ("phone on 'OfficeNet' near 5th & Main, stationary → at
  work") instead of parroting `person.state`, and to cite the evidence chain.
  Overview and Presence use it out of the box; Ask questions get it too

## 1.2.0

- **Create your own insights**: a new "＋ New insight" button lets you define custom
  recurring insights — name, icon, an analysis prompt, and an optional per-insight
  refresh interval (empty = add-on default, 0 = manual only). They live alongside the
  built-in categories: auto-refreshed on their own schedule, included in "Refresh all",
  with full run history, and editable or deletable any time via ✎
- **Turn a question into a recurring insight**: every Ask card now has a
  "＋ Make recurring" button that promotes the question into a scheduled insight,
  prefilled and ready to tweak
- **Insights as dashboard cards**: the new ▦ button on each card produces ready-to-paste
  YAML for a Home Assistant **Webpage** dashboard card that embeds the live
  visualization (always the latest run, auto-reloading). Served by a token-protected
  card server on port 8100 — unmapped by default; map it once under the add-on's
  Network settings
- **Feedback that sticks**: the new 💬 button lets you tell Claude what to change
  ("ignore the guest room sensor", "show costs in dollars"). Feedback is stored as a
  standing instruction injected into every future generation of that card, forwarded to
  the home's memory, and manageable (view/remove) from the same dialog. "Send &
  regenerate" applies it immediately
- **Real tag filtering**: filter chips are now content tags. The analyst tags each card
  by what it actually found (e.g. `#anomaly`, `#batteries`, `#left-on`), and one chip
  surfaces every matching card across categories — instead of the old one-card-per-chip
  table of contents. Card counts show on each chip; `#asked` collects your Ask cards
- **Fixed: background scroll bleed** — opening an expanded view (or any dialog) no
  longer scrolls the dashboard behind it while the popup scrolls too; the page freezes
  in place and picks up exactly where it was on close

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
