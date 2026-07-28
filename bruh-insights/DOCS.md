# BRUH Insights — Documentation

## What it does

BRUH Insights runs a small dashboard server behind Home Assistant **Ingress** (the "Insights"
entry in your sidebar). For each insight category it:

1. Collects a slimmed snapshot of your Home Assistant data through the Supervisor API —
   entity states with areas and friendly names, recent history for relevant sensors, and
   long-term statistics for energy.
2. Sends that snapshot to **Claude** (headless Claude Code CLI) with a strict design system:
   a colorblind-safe palette, proper chart rules, dark & light mode, animations, and hover
   interactivity.
3. Stores the returned insight — title, summary, highlight stats, and a fully self-contained
   HTML visualization — and renders it in a sandboxed card in the panel.

Generated insights persist across restarts and refresh automatically on a schedule (see
options). You can also ask free-form questions ("Which rooms are coldest at night?") and get
a bespoke card back.

## Connecting your Claude account

The add-on works with a **Claude subscription (Pro / Max)** — no API key needed:

- **Shared login from BRUH Terminal** (easiest if you have it): run `ha-share-login` in the
  **BRUH Terminal** add-on once. It shares the terminal's Claude credential at
  `/config/.bruh_claude/secrets/claude_auth.json`, and Insights picks it up automatically —
  nothing to paste. The auth chip shows **"Claude · shared login"** while it's in use.
  A credential connected directly in Insights always takes precedence, and signing out of
  Insights never touches the shared login (stop sharing from BRUH Terminal instead).
- **Guided sign-in**: the panel starts `claude setup-token` for you, shows the
  Anthropic sign-in link, and you paste back the one-time code. The resulting long-lived
  token is stored inside the add-on (`/data/secrets`, mode 0600) and never leaves it.
- **Paste a token** (manual fallback): run `claude setup-token` anywhere you use Claude Code
  and paste the `sk-ant-oat…` token into the panel.
- **API key**: an Anthropic API key (`sk-ant-api…`) from console.anthropic.com also works;
  usage is then billed to your API account instead of the subscription.

Use **Sign out** (the auth chip → logout, or POST `/api/auth/logout`) to forget the
locally stored credential. If a shared BRUH Terminal login exists, Insights falls back to
it automatically.

## Options

Everything except `log_level` is **also editable from the panel's ⚙ Settings dialog**
(see below), and the two screens are the same setting: the panel reads these values live
and writes changes back to the add-on's own options, so whichever one you edit, both show
the new value and it takes effect immediately — no restart.

| Option | Default | Description |
|---|---|---|
| `auto_refresh_hours` | `24` | Fallback interval: regenerate each category every N hours when it has no schedule or interval of its own (see prompt editing and the ⚙ Settings dialog). `0` disables scheduled refresh (manual only). |
| `history_days` | `7` | How many days of history/statistics to analyze. |
| `history_keep_runs` | `40` | Past runs kept per category for the date selector. `0` disables insight history. |
| `history_keep_days` | `30` | Past runs older than this are pruned. `0` disables insight history. |
| `model` | *(empty)* | Claude model to generate with (e.g. `claude-sonnet-5`, or a tier alias like `haiku`). Empty = the CLI default. The ⚙ dialog offers this as a dropdown. |
| `generation_timeout_minutes` | `8` | Hard per-insight generation timeout. |
| `log_level` | `info` | Add-on log verbosity. |

Generation runs **one insight at a time** through a queue, which keeps things friendly to
subscription rate limits. A full "Refresh all" therefore takes several minutes — cards fill
in one by one.

## Settings (⚙) — token budget & master switch

The **⚙ Settings** button in the panel controls how much of your Claude subscription
Insights may spend — no add-on restart needed:

- **Automatic insights** — the master switch. Off pauses every scheduled run (nothing
  spends tokens) while manual **Generate**, **Refresh all**, and **Ask** still work. A
  topbar chip reminds you it's off.
- **Your Claude subscription** — Pro, Max 5×, or Max 20×. Used to estimate the size of
  your 5-hour session window.
- **Session usage budget** — a slider: *let Insights use up to N% of each 5-hour session.*
  Claude subscriptions refill a usage window every 5 hours; once the window's usage
  reaches your budget, Insights pauses automatic runs until it rolls over (a topbar chip
  says so). Manual clicks are never blocked.

Below the budget, a **Generation defaults** section edits the add-on's own
Configuration-tab options — the same values, from either screen, in sync both ways and
applied immediately: the **default refresh interval** every card without its own
schedule/interval uses (this is the "default" the ✎ editor refers to), **days of history
analyzed** per run (fewer days = fewer tokens), the **Claude model** (a dropdown of the
current models and tier aliases, plus *Custom model id…* for anything newer than the
add-on), the **generation timeout**, and **run-history retention**. Only `log_level`
remains Configuration-tab-only, since it takes effect at startup.

Sync works through the Supervisor (`/addons/self/options`), so a value changed in the
panel appears on the Configuration tab and vice versa — no restart either way. Panel edits
land instantly; a Configuration-tab edit is picked up on the next poll (~15 s for
generation, up to about half a minute for an open ⚙ dialog to redraw). In the unusual case
that the Supervisor API isn't reachable, the dialog says so and falls back to storing the
values in the panel alone.

The dialog shows a live usage meter, and a **topbar chip** keeps the current session's
usage and reset time in view at all times (e.g. "34% used · resets 3:15 PM" — tap it to
open Settings; it turns warning-colored once the budget is reached). When the
**BRUH Terminal** add-on is installed, the meter, chip, and budget use your **real
Anthropic account utilization** (its usage-limits tracker at
`/config/.bruh_claude/usage_limits.json` — all Claude use on the account counts, which
is what you want: Insights backs off when *you* are using Claude). Without it, Insights
counts the tokens of its own runs against a rough per-plan session estimate, and the
reset time reflects when the oldest counted run ages out of the 5-hour window.

## Insight history

Every category run is stored as a dated copy (free-form question cards are not kept).
Each card's footer has a run selector and ‹/› step buttons: pick a past run to view it in
place — the card pins to that run (a "Viewing … — Back to latest" pill appears and
regeneration is disabled) until you return to the latest. Highlight stats show a small
"prev: …" line comparing against the immediately-previous run when one exists. Retention
is governed by `history_keep_runs` / `history_keep_days`; individual runs can be deleted
via `DELETE /api/insight/{id}/history/{timestamp}`.

## Editing and removing cards

Every card — shipped, custom, or an ad-hoc Ask answer — has a ✎ and a ✕.

**✎ opens the editor.** For a shipped or custom card that's the full editor below; for an
Ask answer, which has no recurring prompt behind it, it's just the name and icon.

- **Name and icon** — what the card calls itself on the dashboard. Renaming a shipped card
  is purely cosmetic: its analysis, id, and stored history are unchanged, and the new name
  is what the analyst is told the card is about on the next run. Empty the field to get the
  shipped name back (the placeholder shows what that is).
- **Analysis focus** — the instruction the analyst gets for that category. Cards using a
  custom focus show a "custom prompt" badge; **Restore default** brings the shipped name,
  icon and prompt back. Note: the analyst only sees the collected data snapshot — prompts
  can steer the analysis, not fetch new data.
- **Enabled** — disabled categories are dimmed, drop out of auto-refresh and "Refresh all",
  and can be re-enabled from the card.
- **Refresh every N hours** — a per-category interval overriding `auto_refresh_hours`
  (`0` = manual only for that category, empty = use the add-on default).
- **Run at fixed times daily** — e.g. `07:00, 19:00` (24h clock, up to 6 times). When set,
  it takes precedence over the interval: the card regenerates right after each listed time
  and spends nothing in between — the cheapest way to keep a card fresh exactly when you
  read it.

Each stored insight records the focus it was generated with (`focus_used`).

**✕ deletes the card**, whichever kind it is. A custom insight or an Ask answer is gone for
good — definition, stored run, past runs and feedback. A shipped card can't be deleted
outright (its definition ships inside the add-on), so ✕ *removes* it instead: it disappears
from the dashboard, auto-refresh and "Refresh all", and its stored data is erased just the
same, but the card itself is listed under **Removed cards** in ⚙ Settings and one click
brings it back (empty — the deleted runs don't come back with it). An Ask card that failed
before producing anything can be cleared away with ✕ too.

If you'd rather keep a shipped card's history and just stop it running, uncheck **Enabled**
in its ✎ editor instead of removing it.

## Your own insights

**＋ New insight** (top bar) creates a fully custom recurring insight: give it a name, an
icon, an analysis prompt, and an optional refresh interval (empty = the add-on's
`auto_refresh_hours` default, `0` = manual only) or fixed daily run times (e.g.
`07:00, 19:00`). Custom insights behave exactly like the
shipped categories — auto-refreshed on their own clock, included in "Refresh all", with
run history and feedback — and the ✎ button edits them (✕ deletes).

Ad-hoc Ask cards can be promoted too: **＋ Make recurring** in an answer card's footer
prefills a new insight from that question, so a one-off "which rooms are coldest at
night?" becomes a card that stays fresh.

Up to 24 custom insights are supported. Because they're prompt-driven rather than
domain-filtered, the analyst sees the whole (slimmed) home snapshot plus recent history —
write the prompt to steer what it looks at.

## Feedback

The 💬 button on any recurring card records feedback for the analyst ("ignore the guest
room sensor", "show costs in dollars", "less text, bigger chart"). Feedback entries are
**standing instructions**: they're injected into every future generation of that card
until you remove them (same dialog), and each one is also handed to the home's memory via
the bruh_claude integration (with the `/share` inbox fallback). "Send & regenerate"
applies the feedback immediately.

## Filtering by tags

The analyst tags every card by what it actually found (`#anomaly`, `#batteries`,
`#left-on`, …). The chip row above the grid is the live union of those tags — one chip
can match several cards across categories, and the count on the chip tells you how many.
`#asked` collects your ad-hoc question cards. Cards that haven't generated yet only
appear under "All".

## Dashboard cards

Every generated insight can be embedded on a Home Assistant dashboard: press **▦** on a
card — the dialog shows ready-to-paste YAML for a **Webpage** card, e.g.:

```yaml
type: iframe
url: /local/bruh_insights/energy-<your-card-token>.html
title: Energy
aspect_ratio: 90%
```

That URL is served by **Home Assistant itself**: the first time you open the ▦ dialog,
the add-on starts mirroring each insight's HTML into `/config/www/bruh_insights/`
(refreshed on every regeneration, removed when an insight is deleted). Because the card
is same-origin with your dashboard, it works everywhere — plain HTTP on the LAN, local
SSL, and **Nabu Casa remote access** — with no port mapping and no mixed-content
blocking. One edge case: if the `www` folder didn't exist before, Home Assistant needs a
single restart to start serving `/local/…`; the dialog checks the URL live and tells you
when that's the case.

The card always shows the **latest run** of that insight and reloads itself every
15 minutes. The card token is a per-install random secret (stored in
`/data/secrets/card_token`) embedded in the `/local` file name; the mirror holds *only*
stored insight HTML — no API, no credentials, no controls. Anyone with the exact URL can
view that insight, so treat the token like any other dashboard-level secret.

> Upgrading from ≤ 1.4.x: the plain-HTTP card server on port 8100 has been removed —
> cards made with the old `http://<host>:8100/card/…` YAML should be re-added from the
> ▦ dialog to get the new `/local/…` URL.

## Questions, findings, and memory

The analyst may attach up to two **clarifying questions** to an insight ("Is the garage
fridge meant to run overnight?") — but only when it hits a genuine blocker whose answer
would materially change future analyses; most runs ask none.
They appear on the card with an inline answer box, and
every question is tracked in the add-on's own knowledge base with a lifecycle —
**open → answered/dismissed**. Asked and answered questions are shown to the analyst on
every run with a hard never-re-ask rule (plus a server-side filter as backstop), so you
answer a question once and it stays answered.

Durable **findings** (sensor reliability issues, recurring patterns, quirks) land in the
same local knowledge base, deduplicated by content, and are fed back into every future
analysis as known facts the analyst must build on rather than rediscover. Each category
also sees its own **previous run** (title, summary, highlights, findings) and is
instructed to lead with what changed and dig deeper — not to regenerate the same story.

The 🧠 **Memory** button in the top bar shows all of it — on desktop as a wide
two-column dialog: open questions and the analyst's learned facts on the left (answer,
dismiss, or remove anything wrong right there — deleting a fact also scrubs it from the
memory file, so it's gone everywhere), and the **home memory file** at
`/config/.bruh_claude/memory/memory.md` on the right at full height, whose contents are
folded into every data snapshot.

The memory file is shown as **formatted markdown** and is directly editable: press
**✎ Edit markdown** to switch to the raw document, then Save. The "Teach it something"
box sits right above the document, and the document is a taught fact's **only home**:
Claude merges it straight into the file — filed under the right section, deduplicated,
newest-wins on contradictions — rather than also keeping a duplicate row in the facts
list (that list is purely what the analyst discovered on its own). When Claude isn't
reachable the fact is parked under a "Recently added" heading instead, so nothing is
ever lost, and teaching something that's already in the document just says "already
known". If you have unsaved manual edits when you add a fact, the panel warns you
before the rewrite so they can't be silently lost. The same file is shared with BRUH
Terminal's `ha-memory` when that add-on is installed — but it works standalone too.

Every question on an insight card also has an ✕ **"not relevant"** button: one click
retires the question permanently and records that the analyst was on the wrong track,
so future runs stop building analysis around that line of inquiry.

Findings and answers are additionally handed to the **bruh_claude** integration
(`bruh_claude.add_memory` / `bruh_claude.answer_question`) so the whole home shares
them. When the integration isn't installed (it ships with the BRUH Terminal add-on),
they fall back to JSONL drop-files in `/share/bruh_claude/memory-inbox/` for BRUH
Terminal to ingest — but Insights' own memory works either way.

## Device context (deep presence)

Presence analysis goes beyond `person` states. For the Overview and Presence categories
(and every Ask question), the add-on walks the device registry and includes the sibling
entities that live on the same physical device as each presence tracker — typically the
companion-app phone: WiFi SSID, geocoded address, detected activity, battery and
charging state — along with their recent history. The analyst is instructed to
cross-reference these signals and cite its evidence ("phone on home WiFi and charging
since 10:41 PM") instead of parroting `home`/`not_home`.

## Privacy & security

- Home data is sent to Anthropic's API only when an insight is generated — that's the whole
  point — but nothing else leaves your machine. Nothing is sent on a schedule unless
  `auto_refresh_hours` is enabled and you've connected an account.
- Person **GPS coordinates are not** included in snapshots; only zone/state (`home`,
  `not_home`, zone names) and areas are. Device-context expansion does include the
  *states* of phone sensors such as the geocoded-address sensor (that's what makes
  presence analysis smart) — if you don't want that, disable those sensors in the
  companion app or hide the entities in HA and they'll be excluded.
- Generated visualizations render in **sandboxed iframes** (`sandbox="allow-scripts"`) — they
  cannot touch your Home Assistant session, cookies, or the panel itself.
- The panel is only reachable through HA Ingress (admin users) — the add-on exposes no
  host ports at all. The `/local` card mirror serves only insight HTML, from file names
  that embed the per-install card token (HA serves `/local/…` without authentication, so
  the unguessable name is the lock).
- The add-on's `/config` mount is writable for **two things only**: the home memory
  document at `/config/.bruh_claude/memory/memory.md`, maintained by the panel's Memory
  editor, and — only after you first use the ▦ dashboard-card dialog — the card mirror
  under `/config/www/bruh_insights/`. Everything else under `/config` (`CLAUDE.md`, the
  shared login credential) is only ever read. The `/share` mount is writable solely for
  the memory-inbox drop-files described above.

## Troubleshooting

- **"Claude auth failed"** on the chip: the stored token is invalid/expired. Sign out and
  reconnect. Subscription tokens can be revoked from your Anthropic account settings.
- **Generation failed: timed out** — raise `generation_timeout_minutes`, or set a faster
  `model`.
- **Cards look thin** ("data for this angle is thin"): the category found few matching
  entities. That's honest — check the entity list in HA (areas assigned? sensors enabled?).
- **"OAuth error … status code 400" during guided sign-in**: the one-time code
  didn't match this sign-in attempt — codes are tied to the exact link that produced
  them and expire quickly. The panel automatically fetches a **fresh link** after a
  failed attempt: open the new link (not an old tab!), sign in again, and paste the
  new code. Always copy the entire code shown on the callback page.
- **Guided sign-in never shows a link**: use the *Paste a token* tab instead (run
  `claude setup-token` in any terminal with Claude Code installed) — same result.
- Logs: **Settings → Add-ons → BRUH Insights → Log**.
