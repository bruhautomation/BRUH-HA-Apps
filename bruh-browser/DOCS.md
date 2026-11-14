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
approval card with the cart in front of you), or you press **Buy this**
under the cart on this app's page, and only then does a second errand
re-read the checkout and place the order, and only if the cart still matches
what you approved. Voice can build a cart and ask how it went; it cannot buy.

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

Open **Browser** in the sidebar. The page shows five steps, each with its
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
4. **Let it act without asking.** Every errand tells the Claude extension in
   this Chrome to act without asking first, because nobody is there to answer
   it. If the extension still asks (an errand stops with "The Claude extension
   … is waiting for someone to allow it"), open its side panel in the live
   browser: click the Claude icon in Chrome's toolbar (or the puzzle-piece
   icon, then Claude), answer its question with Allow, and choose the answer
   that keeps allowing the site if it offers one. **Open the extension's site
   permissions** shows the sites it may act on. The Test proves this step.
5. **Test.** Opens example.com and reads its heading: a harmless check that
   Claude Code can drive this Chrome and that the extension acts without
   asking. The terminal from step 3 closes by itself.

Then sign in to the shops you want brAIn to use, in the browser below,
the way you would on your own computer. BRUH Browser never types a
password: when a site asks for one, the errand stops and says so.

## How an errand runs

brAIn starts an errand with the words you said. One runs at a time and up
to three wait behind it. The page shows the errand above the live browser:
what it is doing now, and when it finishes, its report and the cart.

**When it needs you**, it stops and says what it needs, with a way to answer:

- **It asks you to choose** (two products that both fit, a substitute, a
  delivery slot): press the answer you want, or type what it should do
  instead. A yes-or-no question has Yes and No.
- **It needs you in the browser** (a login, a CAPTCHA, a "verify it's you"
  code, a pop-up dialog): do it in the live browser on this page, then press
  **I've done it, carry on**.
- **The Claude extension is asking** for permission in its own side panel:
  the page says so and how to open the panel (see setup step 4).

You can also answer brAIn in the chat ("tell it to use the Alpro one"), or
by voice for a choice that doesn't change what you spend. **Stop this
errand** ends it at any time; nothing already in a cart is removed. It never
asks you to approve ordinary steps (searching, opening pages, filling the
cart): that is the errand you gave it.

**When the cart is ready**, the page shows the store, every item with its
quantity and price, the fees, the delivery slot and the total, with **Buy
this** and **Don't buy**. Buy this asks once more with the total ("Buy for
…?"); the order is placed by a second errand, only if the checkout still
matches, and only within 30 minutes of the cart being built. **Don't buy**
means that cart can never be bought, here or through brAIn.

## Which browser

Your Claude account may have the Claude extension in more than one Chrome:
this app's, and perhaps the one on your laptop. The page lists them under
**Browsers this account has connected**, marks this app's own, and lets you
choose the default.

- **Errands use this app's own Chrome** unless you pick another, or you tell
  brAIn to use another for an errand. It never quietly falls back to another
  computer: if this app's Chrome isn't connected, or the page can't tell which
  browser is its own, the errand stops and asks which to use. If the page says
  it can't tell, press **This is the BRUH Browser** on the right one.
- **brAIn asks** which browser to use when more than one is connected and you
  haven't said, can remember your answer as the default, and says which
  browser it used.
- **On another computer**, the extension keeps asking its own person before it
  acts, and **nothing is ever bought there**: purchases happen only in this
  app's own Chrome.

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
  `/config/.bruh_browser/api_token`; Buy this, Don't buy, "I've done it" and
  "This is the BRUH Browser" are pressed only on this page.
- **Chrome runs without its own sandbox** when the container cannot give it
  one (normally the case for an app): the app's container and its AppArmor
  profile are then the boundary. The page says which is in force.
- **The spending guard is a net, not a guarantee.** Besides your approval,
  every errand runs with a check that refuses a click on anything labelled
  "Place order", "Buy now", "Pay" and the like when the errand has no
  approved purchase. A site can label its button any way it likes, and a
  click at a screen position names nothing, so the guard is a second line;
  the first is that no errand is ever told it may buy without your yes.

## Your shopping profile

Ask brAIn to look at your old orders at a store ("look at my old Walmart
orders and learn what I usually buy"). The errand reads what the store's
order history shows and saves a profile for that store (only an errand
brAIn starts for that purpose saves one; an ordinary shopping errand never
changes it): the items you buy
(name as the store shows it, size, usual quantity, how often, when last
bought), brands you prefer, and things to avoid when your history shows
them. It is never guessed. Running the same kind of errand again adds to it
and updates what changed.

- **Where it lives:** in this app's own storage (`/data`), on this app only.
  It **is included in Home Assistant backups** (like your errand history),
  so a restore keeps it; it holds what you buy, not passwords, and backups
  are unencrypted unless you opt in. It is sent nowhere but into the message
  of a later errand for that store, and to brAIn when it asks.
- **How it is used:** a later cart errand for that store starts from it, so
  "add my usual" means your profile first and the store's own buy-again list
  second. An errand gets a store's profile when it names that store ("add my
  usual Walmart order"). When you don't name a store ("add my usual order
  plus oat milk"), brAIn asks first ("your usual Walmart order?") and uses
  the profile only if you say yes; "my usual from Costco" never gets your
  Walmart one. brAIn tells you what it knows and asks what changes before it
  starts.
- **You are in charge:** the page shows every store's profile. Press
  **Remove** beside an item, a brand or a thing to avoid and it stays out,
  even when the next order-history errand sees it again. **Clear profile**
  forgets the whole store (press twice to confirm). Only you can do this, on
  this page.
- **It is not an approval.** A profile never lets an errand buy anything;
  buying still takes your yes on a finished cart. Everything in it came from
  a web page, so it is kept as plain data (each product name, size, count,
  how often and date, tidied and shortened) and handed to an errand only as a
  list of things you have bought before. Nothing is left out for what its
  name says, and nothing in a product name can read as permission to buy.

## For brAIn

brAIn's tools are `browser_task` (start an errand, optionally in a named
browser; it never buys), `browser_status` (how it went, the cart, the
question it is waiting on, and with `browsers` the connected browsers; a
long report comes back whole, or in parts with an `offset` to read on, and
with `profiles` your shopping profile),
`browser_answer` (pass on your answer to its question), `browser_stop`, and
`browser_purchase` (buy a cart you approved). They are listed only when this
app is installed.
