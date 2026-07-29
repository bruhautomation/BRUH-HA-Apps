# BRain

**Your home's brain.** A Claude Code terminal, an AI insights dashboard, and one shared
memory that learns your house over time — in a single Home Assistant add-on.

BRain replaces **BRUH Terminal** and **BRUH Insights**. Both are deprecated; BRain is a
clean install, not an upgrade.

## What's in it

| | |
| --- | --- |
| **Terminal** | Full Claude Code in your browser, with native Home Assistant access through an MCP server — read states, call services, check history, reload config, edit YAML. |
| **Insights** | Claude analyses your home's data and writes interactive cards you can drop on a dashboard. Ask it anything about your house and get an answer card back. |
| **Memory** | One document of durable facts about your home, learned from voice conversations, insight runs, and anything you tell it directly. Every part of BRain reads and writes the same memory. |

All three live behind one sidebar panel, and share one Claude login.

## Why one add-on

The terminal and the dashboard used to be separate containers. That meant authenticating
Claude twice, two Claude clients, two settings stores, two question ledgers, and two
processes writing the same memory file with no lock between them. Merging them makes the
shared memory actually shared, and lets an Ask card do anything the terminal can.

## The CLI

Two commands, split by what they act on:

```bash
brain memory add "The garage fridge is meant to run 24/7"
brain memory list             # what it knows
brain learn energy            # study a topic and write down what it finds
brain undo                    # review and revert Claude's file edits
brain doctor                  # end-to-end diagnostic

ha log                        # tail the Home Assistant log
ha reload automations
ha entity list light
ha context                    # regenerate /config/CLAUDE.md
```

`brain help` and `ha help` list the rest.

## Backups

BRain does **not** back up your config. Use Home Assistant's own backups (with the
Google Drive add-on or any other backup target) — they're whole-system, restorable, and
already solved.

What BRain does keep is an **edit journal**: before Claude writes to any file under
`/config`, the previous version is snapshotted, and `brain undo` puts it back. That's
scoped to Claude's own edits and stored under `/data`, so it never ends up inside your
Home Assistant backups.

## Configuration

See [DOCS.md](DOCS.md) for every option.

## License

MIT. BRUH Power Tools is adapted from [Spook](https://github.com/frenck/spook) (MIT).
