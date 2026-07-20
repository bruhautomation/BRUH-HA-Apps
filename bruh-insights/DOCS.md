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

| Option | Default | Description |
|---|---|---|
| `auto_refresh_hours` | `6` | Regenerate each category every N hours (categories can override this individually — see prompt editing). `0` disables scheduled refresh (manual only). |
| `history_days` | `7` | How many days of history/statistics to analyze. |
| `history_keep_runs` | `40` | Past runs kept per category for the date selector. `0` disables insight history. |
| `history_keep_days` | `30` | Past runs older than this are pruned. `0` disables insight history. |
| `model` | *(empty)* | Claude model override (e.g. `claude-sonnet-4-5`). Empty = the CLI default. |
| `generation_timeout_minutes` | `8` | Hard per-insight generation timeout. |
| `log_level` | `info` | Add-on log verbosity. |

Generation runs **one insight at a time** through a queue, which keeps things friendly to
subscription rate limits. A full "Refresh all" therefore takes several minutes — cards fill
in one by one.

## Insight history

Every category run is stored as a dated copy (free-form question cards are not kept).
Each card's footer has a run selector and ‹/› step buttons: pick a past run to view it in
place — the card pins to that run (a "Viewing … — Back to latest" pill appears and
regeneration is disabled) until you return to the latest. Highlight stats show a small
"prev: …" line comparing against the immediately-previous run when one exists. Retention
is governed by `history_keep_runs` / `history_keep_days`; individual runs can be deleted
via `DELETE /api/insight/{id}/history/{timestamp}`.

## Editing category prompts

The ✎ button on every category card opens the prompt editor:

- **Analysis focus** — the instruction the analyst gets for that category. Cards using a
  custom focus show a "custom prompt" badge; **Restore default** brings the shipped prompt
  back. Note: the analyst only sees the collected data snapshot — prompts can steer the
  analysis, not fetch new data.
- **Enabled** — disabled categories are dimmed, drop out of auto-refresh and "Refresh all",
  and can be re-enabled from the card.
- **Refresh every N hours** — a per-category interval overriding `auto_refresh_hours`
  (`0` = manual only for that category, empty = use the add-on default).

Each stored insight records the focus it was generated with (`focus_used`).

## Your own insights

**＋ New insight** (top bar) creates a fully custom recurring insight: give it a name, an
icon, an analysis prompt, and an optional refresh interval (empty = the add-on's
`auto_refresh_hours` default, `0` = manual only). Custom insights behave exactly like the
shipped categories — auto-refreshed on their own clock, included in "Refresh all", with
run history and feedback — and the ✎ button edits or deletes them.

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

Every generated insight can be embedded on a Home Assistant dashboard:

1. **One-time setup**: the add-on serves insight HTML on port **8100** (token-protected),
   but the port is *unmapped by default*. Map it under **Settings → Add-ons →
   BRUH Insights → Configuration → Network** and restart the add-on.
2. Press **▦** on a card — the dialog shows ready-to-paste YAML for a **Webpage** card,
   e.g.:

   ```yaml
   type: iframe
   url: http://homeassistant.local:8100/card/energy?token=<your-card-token>
   title: Energy
   aspect_ratio: 90%
   ```

The card always shows the **latest run** of that insight and reloads itself every
15 minutes. The `token` query parameter is a per-install random secret (stored in
`/data/secrets/card_token`); the card server serves *only* stored insight HTML — no API,
no credentials, no controls. Anyone with the exact URL on your network can view that
insight, so treat the token like any other dashboard-level secret.

## Questions, findings, and memory

The analyst may attach up to two **clarifying questions** to an insight ("Is the garage
fridge meant to run overnight?"). They appear on the card with an inline answer box —
answering forwards the answer to the **bruh_claude** integration
(`bruh_claude.answer_question`) so the home remembers it, and removes the question from
the card. Open questions across all insights are listed at `GET /api/questions`.

Durable **findings** (sensor reliability issues, recurring patterns) are recorded with
each insight and submitted automatically via `bruh_claude.add_memory`. When the
integration isn't installed (it ships with the BRUH Terminal add-on), both fall back to
JSONL drop-files in `/share/bruh_claude/memory-inbox/` for BRUH Terminal to ingest.

If BRUH Terminal maintains a memory file at `/config/.bruh_claude/memory/memory.md`, its
contents are folded into every data snapshot ahead of the CLAUDE.md excerpt, so learned
facts inform every future insight.

## Privacy & security

- Home data is sent to Anthropic's API only when an insight is generated — that's the whole
  point — but nothing else leaves your machine. Nothing is sent on a schedule unless
  `auto_refresh_hours` is enabled and you've connected an account.
- Person **GPS coordinates are not** included in snapshots; only zone/state (`home`,
  `not_home`, zone names) and areas are.
- Generated visualizations render in **sandboxed iframes** (`sandbox="allow-scripts"`) — they
  cannot touch your Home Assistant session, cookies, or the panel itself.
- The panel is only reachable through HA Ingress (admin users), never exposed on a host
  port. The optional dashboard-card server (port 8100, unmapped by default) is a separate
  mini server that serves only stored insight HTML and requires the per-install card
  token on every request.
- The add-on's `/config` mount is **read-only**; it only reads `CLAUDE.md`, the shared
  memory file, and the shared login credential (all maintained by BRUH Terminal, if
  present). The `/share` mount is writable solely for the memory-inbox drop-files
  described above.

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
