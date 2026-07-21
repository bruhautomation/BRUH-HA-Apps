# BRUH Insights

**AI-powered insights for your Home Assistant — beautiful, interactive, right in your sidebar.**

BRUH Insights puts Claude to work as your home's personal analyst. It reads your Home Assistant
data (states, history, long-term statistics, areas) and generates gorgeous, animated, interactive
visualizations with sharp written analysis — served through Ingress as an **Insights** panel in
your sidebar.

## What you get

- 🏠 **Home Overview** — the whole house at a glance
- ⚡ **Energy** — consumption trends, top loads, anomalies
- 🌡️ **Climate** — room temps vs outdoors, HVAC behavior, comfort
- 💡 **Lighting** — what's on, usage rhythms, lights left burning
- 🔒 **Security** — open doors/windows, locks, motion timeline
- 🧭 **Presence** — who's home, arrival patterns, activity rhythm
- 🎵 **Media** — what's playing and where
- 🩺 **Device Health** — dead devices, weak batteries, pending updates
- 🤖 **Automations** — what runs, what never does, what to improve
- ✨ **Ask anything** — type a question, get a bespoke insight card
- 🧠 **Memory** — the analyst learns your home over time: findings, your answers, and
  feedback are stored, viewable (and editable) in the Memory panel, and fed back into
  every future analysis — questions are never asked twice, and each run builds on the
  last instead of repeating it

Every card is a self-contained interactive visualization (hover tooltips, tasteful animations,
light & dark mode, colorblind-safe palette) designed by Claude specifically for *your* data.
Presence analysis digs into the *context* on each person's phone — WiFi SSID, geocoded
address, activity, charging state — to say where people actually are, with evidence, instead
of a flat "home/away".

## Works with your Claude subscription

No API key required. Connect once with your Claude **Pro or Max** account using the guided
sign-in in the panel (or paste a token from `claude setup-token`). An Anthropic API key works
too if you prefer pay-as-you-go.

## Install

1. Add this repository to your Home Assistant add-on store:
   `https://github.com/bruhautomation/BRUH-HA-Apps`
2. Install **BRUH Insights** and start it.
3. Click **Insights** in the sidebar and connect your Claude account.
4. Hit **Refresh all** — enjoy the show.

See [DOCS.md](DOCS.md) for configuration options and details.
