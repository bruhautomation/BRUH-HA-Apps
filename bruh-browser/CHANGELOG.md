# Changelog

## 0.1.1

### Added

- When an errand stops to ask you something, the page now gives you a way to answer: a button for each choice (or Yes and No), a box to tell it what to do instead, and **Stop this errand**. When it needs you to sign in, solve a CAPTCHA, type a code or close a pop-up, it points you to the live browser and **I've done it, carry on** picks up where it stopped.
- brAIn can answer those questions too, in the chat or by voice ("it's asking whether to swap the oat milk"). By voice it answers only a choice or a yes/no that doesn't change what you spend.
- A finished cart now has **Buy this** and **Don't buy** right under it. Buy this asks once more with the total ("Buy for 11.30 GBP?") and goes through the same checks as buying through brAIn. Don't buy means that cart can never be bought.
- **Browsers this account has connected**: the page lists every Chrome with the Claude extension on your Claude account, marks this app's own, and lets you pick which one errands use by default.
- A new setup step, **Let it act without asking**, with a button to the extension's site permissions page, and the Test now checks it.

### Changed

- Errands always use this app's own Chrome unless you or brAIn pick another. If this app's Chrome isn't connected, or it can't tell which browser is its own, the errand stops and asks which to use instead of quietly using a Chrome on another computer.
- Errands tell the Claude extension in this app's Chrome to act without asking, so a run no longer stalls on a permission question in the extension's side panel that nobody could see. A Chrome on another computer still asks its own person, and nothing is ever bought there.
- The errand's instructions now say that searching, opening pages and filling the cart are the job: it no longer stops to ask permission for them, and never asks you to "approve" something without giving you the choices.

### Fixed

- An errand could stop with "approve this or don't approve this" and the page had no way to answer it; the only button said you had done something in the browser.
- When the extension was waiting for permission in its own side panel, the errand just hung until it timed out. It now stops and says exactly where the question is and how to open it.

## 0.1.0

### Added

- First release, experimental, amd64 only. BRUH Browser is brAIn's hands on the web: a real Google Chrome with Anthropic's Claude in Chrome extension on a virtual screen in the sidebar, running one errand at a time for brAIn (`claude --chrome -p`), a grocery cart first.
- Setup page with four live steps read from the real state: the extension (force-installed by Chrome policy), its claude.ai sign-in, Claude Code's own sign-in in a terminal window on the same screen, and a harmless Test.
- Errands as jobs: `POST /api/tasks`, `GET /api/tasks/<id>`, `POST /api/tasks/<id>/stop`, with a bearer token in `/config/.bruh_browser/api_token`; one running, three waiting, Continue after a login or CAPTCHA.
- A purchase is always a second errand after a reviewed cart: refused without an approval the panel can check (a finished cart from this add-on, under 30 minutes old, used once, and its exact total), and a spending guard (a Claude Code hook) that refuses order-placing clicks in any errand without that approval.

### Security

- The screen, its websocket and the setup routes answer Home Assistant's ingress only; other add-ons reach the errand routes only with the token. Chrome runs with remote debugging off by policy.
