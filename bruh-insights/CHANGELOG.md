# Changelog

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
