# brAIn — a Claude Code add-on that learns your house (WIP, feedback very welcome)

Hey all, Ben here. I've been building an add-on called **brAIn** and it's finally at the
point where it's worth other people poking at it. It's still very much a work in progress,
so I'd rather share it early and get told what's broken than polish it alone for another
six months.

## What it is

brAIn runs [Claude Code](https://claude.com/claude-code) inside Home Assistant, gives it a
proper set of Home Assistant tools, and keeps a memory of your house between conversations.

It can see the whole system — entities, devices, areas, floors, dashboards, helpers,
automations — and it can change any of it. Ask why an automation didn't fire, have it read
the trace, fix the YAML, validate it and reload. Next time, it already knows the answer.

The memory isn't a black box: it's one document you can open, read, edit and correct in the
panel.

One install, one sidebar panel, one login.

## What it does today

- **Runs Home Assistant** — 36 native tools for reading and controlling, 65 registry
  services for the parts that normally live behind the Settings UI, plus a real shell in
  `/config` for everything that's still YAML.
- **Finds what's broken** — dead batteries, sensors that quietly stopped reporting, devices
  stuck unavailable, automations that can never fire. Press **Fix it** and it makes the
  change; press **Not a problem** and it never raises that one again.
- **Explains your house** — ask a question in the panel and get an insight card back, with
  a real chart. Keep the useful ones as recurring, or drop them on a dashboard.
- **Talks** — it's a conversation agent, so you can use it in Assist with your memory and an
  area map already in the prompt.
- **Has a terminal** — the real Claude Code CLI in your browser, as a chat that works on a
  phone or as a classic terminal. Same session behind both.

A few things to try in the ask bar:

```
why is the upstairs cold in the morning?
which of my sensors have stopped reporting?
build me a dashboard for the garage with the door, the freezer and the lights
rename every "Sonoff Switch 3" to what it actually is
```

## Installing

Add the repository to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**:

```
https://github.com/bruhautomation/BRUH-HA-Apps
```

Then install **brAIn** and sign in to Claude from the panel.

You'll need Home Assistant OS or Supervised (it's an add-on), amd64 or aarch64, and either
a **Claude Pro or Max subscription** or your own Anthropic API key. The subscription is
usually the cheaper way to run it.

Full docs: [bruhautomation.com/brain](https://bruhautomation.com/brain/)

## Please back up first

brAIn edits your real configuration. It snapshots files before it changes them and `brain
undo` puts them back, but that is not a backup. Take a Home Assistant backup and copy it off
the device before you install — **Settings → System → Backups**.

## The honest part

This is a WIP. It's early, it's opinionated, and some of it will be wrong for your setup.
Language models make mistakes, and this one has write access to your config — that's the
trade, and it's why the undo and the backup warning exist. Cost depends on how much you use
it; the panel shows your usage against your plan's limits.

I'd really appreciate feedback of any kind — what's confusing, what broke, what you expected
it to do and it didn't:

- **Bugs** → [open an issue](https://github.com/bruhautomation/BRUH-HA-Apps/issues) (a repro
  and the add-on log go a long way)
- **Questions, ideas, setups** →
  [Discussions](https://github.com/bruhautomation/BRUH-HA-Apps/discussions) — Q&A, Ideas, and
  Show and tell

Or just reply here. Thanks for taking a look.

---

*Not affiliated with or endorsed by Anthropic or the Open Home Foundation. brAIn runs the
official Claude Code CLI under your own Anthropic account.*
