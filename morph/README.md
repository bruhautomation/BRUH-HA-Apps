# Morph

> ## ⚠️ Experimental — not recommended for general use yet
> **Morph is being built in the open and is not finished.** Expect missing
> cards, rough edges and changes between updates that move things around
> without warning. Install it to try it out alongside your normal
> dashboards, not to replace them. Morph only writes its own folder
> (`/config/morph`) — every change there is a version you can undo — but a
> Tell lets brAIn change the house too, so keep an eye on what it does.

A dashboard for Home Assistant that moves to make room for whatever you are
looking at — and that you change by saying what you want.

Morph lives in the sidebar. Rooms are sections, scenes sit above lights as
words, and a card opens in place: its neighbours step aside first, then it
grows, and tapping anywhere else folds it back. Nothing floats over anything.

## What it does

**One grammar.** Tap does the main thing (toggle, play, lock). Slide sets a
level (brightness, fan speed, blind position). Hold opens the card in place,
with its options and its history — the day as a strip or the week as bars,
drilling into hours, with who or what changed it.

**Any Lovelace card.** Paste a card's YAML or JSON into a section and Morph
hosts it, with the live `hass` it needs — Mushroom, mini-graph, anything you
already use.

**brAIn designs it with you.** In Edit, hold anything — a card, a section, a
floor, the whole dashboard — and say what should change: *"add a Pets section
with Cece's feeder"*, *"make the kitchen lights one strip"*, *"turn the porch
light off at sunrise"*. brAIn acts at once, on the dashboard, on Morph's card
code, or on the house behind it, and the change lands in the same place you
asked with **Keep** and **Undo** beside it.

**Everything is undoable.** The dashboard is a folder, `/config/morph`, and
its history is git: every change — yours, brAIn's, a lesson Morph learned,
or an edit you made by hand — is one commit, and **Settings → History** can
undo or restore any of them.

**It learns, and it asks first.** Morph notices what you open, when, and what
you change back. A scheduled brAIn pass turns that into suggestions shown in
place on the dashboard — *Do it*, *Not now*, *No* — and nothing changes until
you press Do it. Saying No with a reason teaches it; the lessons are a file
you can read and edit.

**It fixes itself.** When Morph's own code fails — a card that will not draw,
a layout that overlaps — it hands the fault to brAIn's development loop, which
files it in your private reports repository so the fix arrives as an update.

**What brAIn adds.** With brAIn installed, the top of the page is a sentence
about what the house is doing, you can ask the house a question, *Coming up*
shows what is due, and brAIn's findings appear as notes on the section they
are about. Without brAIn, Morph is still a complete dashboard; Tell and
learning say plainly that they need it.

## Install

1. Add this repository to the add-on store and install **Morph**.
2. Start it. Under **Settings → Devices & services**, accept the **Morph**
   tile.
3. Restart Home Assistant once (**Settings → System → Restart**).
4. Morph appears in the sidebar, with a first dashboard built from your
   floors, areas and devices.

There is no *Show in sidebar* switch on the add-on's page, and that is on
purpose: Morph is a panel inside Home Assistant's own frontend rather than an
ingress page, which is what lets it host any Lovelace card and use your
theme. The integration is what puts it in the sidebar.

For Tell and learning, install **brAIn** and switch on its *Automation
integration*.

📖 [Full documentation](DOCS.md)
