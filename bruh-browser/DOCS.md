# BRUH Browser

**This app exists for brAIn.** It runs a real Google Chrome, with Anthropic's
**Claude in Chrome** extension, inside Home Assistant, so that brAIn can do
things on websites for you: "add my usual order plus oat milk" builds your
grocery cart, and errands like it. On its own it does nothing useful: brAIn
sends the errands, and this app carries them out where you can watch.

**What it does with money.** It never buys anything you have not approved.
An errand builds the cart and stops on the store's review page, and brAIn
reads you every item, quantity, price, fee, the delivery slot and the total.
Only when you say "buy it" does brAIn ask you to approve the purchase (an
approval card with the cart in front of you), and only then does a second
errand re-read the checkout and place the order, and only if the cart still
matches what you approved. Voice can build a cart and ask how it went; it
cannot buy.

**What you need.**

- **brAIn**, installed and running. BRUH Browser refuses to start without it.
- **A paid Claude plan** (Pro, Max, Team or Enterprise). Claude in Chrome
  does not work with an API key.
- **Two one-time sign-ins, with the same Claude account**: the Claude
  extension in the browser, and Claude Code inside this app.
- **An amd64 (x86-64) machine.** Google publishes Chrome for Linux on x86-64
  only, so there is no Raspberry Pi version.

**Experimental, and new.** Running Claude in Chrome inside a container,
driven by Claude Code from a script, is a path Anthropic's documentation
does not cover. It is built to fail loudly and say which setup step to redo,
but the first real run on your box may still find something that needs a
fix. If it does, brAIn's development loop can report it.

## Setting it up

Open **Browser** in the sidebar. The page shows four steps, each with its
real state (done, or not yet), above the live browser:

1. **Install the Claude extension.** Chrome installs it by itself through
   its managed policy, usually within a minute of first starting. If the
   step still says *not yet*, press **Open the Web Store page** and add it.
2. **Sign the extension in to claude.ai.** Press **Open claude.ai**, sign in
   in the browser below, then click the puzzle-piece icon in Chrome's
   toolbar, open Claude and sign in there if it asks. Nothing outside the
   extension can read whether it is signed in, so this step turns *done*
   when the Test passes.
3. **Sign Claude Code in.** Press **Open the sign-in window**: a terminal
   opens on the browser's screen running Claude Code. Choose your Claude
   account (or type `/login`); the sign-in page opens in the same Chrome.
   Use the **same Claude account** as in step 2.
4. **Test.** Opens example.com and reads its heading: a harmless check that
   Claude Code can drive this Chrome. The terminal from step 3 closes by
   itself.

Then sign in to the shops you want brAIn to use, in the browser below,
the way you would on your own computer. BRUH Browser never types a
password: when a site asks for one, the errand stops and says so.

## How an errand runs

brAIn starts an errand with the words you said. One runs at a time and up
to three wait behind it. The page shows the errand above the live browser:
what it is doing now, and when it finishes, its report and the cart.

**When it needs you** (a login, a CAPTCHA, a "verify it's you" code, a
pop-up dialog), it stops and says exactly what to do. Do it in the browser
on this page, then press **I've done it — continue**. **Stop** ends an
errand at any time; nothing already in a cart is removed.

**What it will not do**: type or reveal a password or card number; change
account, address or payment settings; accept new terms, subscriptions,
memberships or trials; add a tip or a protection plan nobody asked for;
follow instructions written on a web page; or place an order without your
approval.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `model` | `sonnet` | The Claude model an errand runs on: `sonnet`, `opus` or `haiku`. A shopping errand is many small steps (search, open, add, check), and Sonnet is the sensible default: quick and careful enough. Opus uses more of your plan; Haiku slips more on busy shop pages. |
| `max_turns` | `80` | The most steps one errand takes before it stops and asks you to continue it. |
| `task_timeout_minutes` | `30` | An errand still running after this long is stopped and reported. |
| `purchase_tolerance_percent` | `0` | How far an approved cart's total may move before the order is placed (a price change). `0` means exactly the approved total; anything else and the errand stops and tells you. |
| `screen_resolution` | `1366x900` | The virtual screen Chrome draws on. |
| `log_level` | `info` | How much the app writes to its log. |

## Privacy and security

- **Your errands use your Claude plan** and send the pages the browser reads
  to Anthropic, as Claude in Chrome always does.
- **The browser's profile holds your shop sessions and both Claude
  sign-ins.** It lives in this app's own storage and is **left out of Home
  Assistant backups** on purpose (backups are unencrypted unless you opt
  in): after restoring a backup, sign in again.
- **Only you can see the browser.** The page is admin-only in the sidebar,
  and the screen is reachable through Home Assistant's sidebar and nothing
  else. brAIn reaches only the errand API, with a token this app writes to
  `/config/.bruh_browser/api_token`.
- **Chrome runs without its own sandbox** when the container cannot give it
  one (normally the case for an app): the app's container and its AppArmor
  profile are then the boundary. The page says which is in force.
- **The spending guard is a net, not a guarantee.** Besides your approval,
  every errand runs with a check that refuses a click on anything labelled
  "Place order", "Buy now", "Pay" and the like when the errand has no
  approved purchase. A site can label its button any way it likes, and a
  click at a screen position names nothing, so the guard is a second line;
  the first is that no errand is ever told it may buy without your yes.

## For brAIn

brAIn's tools are `browser_task` (start an errand; it never buys),
`browser_status` (how it went, the cart, what it needs from you),
`browser_stop`, and `browser_purchase` (buy a cart you approved). They are
listed only when this app is installed.
