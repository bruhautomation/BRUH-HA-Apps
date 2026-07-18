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

- **Guided sign-in** (recommended): the panel starts `claude setup-token` for you, shows the
  Anthropic sign-in link, and you paste back the one-time code. The resulting long-lived
  token is stored inside the add-on (`/data/secrets`, mode 0600) and never leaves it.
- **Paste a token**: run `claude setup-token` anywhere you use Claude Code — for example the
  **BRUH Claude Terminal** add-on — and paste the `sk-ant-oat…` token into the panel.
- **API key**: an Anthropic API key (`sk-ant-api…`) from console.anthropic.com also works;
  usage is then billed to your API account instead of the subscription.

Use **Sign out** (the auth chip → logout, or POST `/api/auth/logout`) to forget the
credential.

## Options

| Option | Default | Description |
|---|---|---|
| `auto_refresh_hours` | `6` | Regenerate all categories every N hours. `0` disables scheduled refresh (manual only). |
| `history_days` | `7` | How many days of history/statistics to analyze. |
| `model` | *(empty)* | Claude model override (e.g. `claude-sonnet-4-5`). Empty = the CLI default. |
| `generation_timeout_minutes` | `8` | Hard per-insight generation timeout. |
| `log_level` | `info` | Add-on log verbosity. |

Generation runs **one insight at a time** through a queue, which keeps things friendly to
subscription rate limits. A full "Refresh all" therefore takes several minutes — cards fill
in one by one.

## Privacy & security

- Home data is sent to Anthropic's API only when an insight is generated — that's the whole
  point — but nothing else leaves your machine. Nothing is sent on a schedule unless
  `auto_refresh_hours` is enabled and you've connected an account.
- Person **GPS coordinates are not** included in snapshots; only zone/state (`home`,
  `not_home`, zone names) and areas are.
- Generated visualizations render in **sandboxed iframes** (`sandbox="allow-scripts"`) — they
  cannot touch your Home Assistant session, cookies, or the panel itself.
- The panel is only reachable through HA Ingress (admin users), never exposed on a host port.
- The add-on's `/config` mount is **read-only**; it only reads `CLAUDE.md` (context generated
  by BRUH Claude Terminal, if present) to understand your naming conventions.

## Troubleshooting

- **"Claude auth failed"** on the chip: the stored token is invalid/expired. Sign out and
  reconnect. Subscription tokens can be revoked from your Anthropic account settings.
- **Generation failed: timed out** — raise `generation_timeout_minutes`, or set a faster
  `model`.
- **Cards look thin** ("data for this angle is thin"): the category found few matching
  entities. That's honest — check the entity list in HA (areas assigned? sensors enabled?).
- **Guided sign-in never shows a link**: use the *Paste a token* tab instead (run
  `claude setup-token` in any terminal with Claude Code installed) — same result.
- Logs: **Settings → Add-ons → BRUH Insights → Log**.
