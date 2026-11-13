# Changelog

## 0.1.0

### Added

- First release, experimental, amd64 only. BRUH Browser is brAIn's hands on the web: a real Google Chrome with Anthropic's Claude in Chrome extension on a virtual screen in the sidebar, running one errand at a time for brAIn (`claude --chrome -p`), a grocery cart first.
- Setup page with four live steps read from the real state: the extension (force-installed by Chrome policy), its claude.ai sign-in, Claude Code's own sign-in in a terminal window on the same screen, and a harmless Test.
- Errands as jobs: `POST /api/tasks`, `GET /api/tasks/<id>`, `POST /api/tasks/<id>/stop`, with a bearer token in `/config/.bruh_browser/api_token`; one running, three waiting, Continue after a login or CAPTCHA.
- A purchase is always a second errand after a reviewed cart: refused without an approval the panel can check (a finished cart from this add-on, under 30 minutes old, used once, and its exact total), and a spending guard (a Claude Code hook) that refuses order-placing clicks in any errand without that approval.

### Security

- The screen, its websocket and the setup routes answer Home Assistant's ingress only; other add-ons reach the errand routes only with the token. Chrome runs with remote debugging off by policy.
