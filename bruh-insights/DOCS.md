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
- The panel is only reachable through HA Ingress (admin users), never exposed on a host port.
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
