# Changelog

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
