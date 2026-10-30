# Repository structure

The file tree with one line per file.

Part of the project notes (see `CLAUDE.md` › *Where the notes are*). Read this file before changing what it covers; add a note here, not in `CLAUDE.md`.

## Repository Structure

```
BRUH-HA-Apps/
├── repository.yaml              # HA add-on repository metadata
├── SECURITY.md                  # Disclosure policy + what each add-on can reach
├── ruff.toml                    # Python lint rules (E+F; style exceptions explained)
├── brain/                       # Main add-on
│   ├── config.yaml              # HA add-on configuration manifest
│   ├── apparmor.txt             # AppArmor profile (profile name must equal the slug)
│   ├── translations/en.yaml     # Option labels + help text for the config UI
│   ├── build.yaml               # Multi-arch build config
│   ├── Dockerfile               # Container build definition
│   ├── run.sh                   # Main startup/entrypoint script (start_morph, retire_morph_addon)
│   ├── morph/                   # Morph's service (part of brAIn since 4.0; the add-on is retired)
│   │   ├── service/             # morphd.py (requests, watcher, ticks), store, gitrepo,
│   │   │                        #   generator, tell, converse, learning, devloop, brain, settings, ha
│   │   └── defaults/            # AGENTS.md, CLAUDE.md, cards/README.md for /config/morph
│   ├── panel/                   # The ingress panel: aiohttp server + the UI
│   │   ├── server.py            # Routes, scheduler, the chat terminal's API
│   │   ├── actions.py           # The action miner: who or what changed something
│   │   ├── baselines.py         # What is normal here, per entity per hour of the week
│   │   ├── weekly.py            # The week's report: gathered and capped before a model runs
│   │   ├── synthesis.py         # The week's one thing, chosen across the week, the rank kept beside it
│   │   ├── deep_review.py       # A press that reads the whole house and files nothing
│   │   ├── energy.py            # What the house used, from HA's own energy sources
│   │   ├── appliances.py        # A machine's own power shape: idle, running, finished
│   │   ├── thermal.py           # How fast each room loses heat, and how fast it gains it
│   │   ├── shadow.py            # What an automation WOULD have done, calling nothing
│   │   ├── trials.py            # A trial: the replayed week, graded against what you did
│   │   ├── automation_writer.py # An accepted proposal, appended to automations.yaml
│   │   ├── healing.py           # Three things brAIn may fix overnight, and six refusals
│   │   ├── playbooks.py         # The automation brAIn would write for a bad night
│   │   ├── proposals.py         # What could be better, and how a trial ends it
│   │   ├── routines.py          # What you do by hand, often enough to be a habit
│   │   ├── manual_ledger.py     # What somebody did by hand, and the shape of it
│   │   ├── curiosity.py         # Why they did it — one question a day, at most
│   │   ├── habits.py            # One arithmetic for "the shape of when", behind three ledgers
│   │   ├── habit_lookup.py      # The join over the three ledgers for one entity (never inside habits: the ledgers import it)
│   │   ├── circular.py          # Clock arithmetic around midnight — a leaf, re-exported by rhythm
│   │   ├── facts_store.py       # Facts with provenance under memory.md: subjects, source, run, exceptions
│   │   ├── ideas.py             # Cards brAIn thinks this house is missing, before you agree
│   ├── episodes.py          # What HAPPENED, rather than every value that changed
│   │   ├── esphome.py           # ESPHome: the device files here, the builds on the dashboard
│   │   ├── music_assistant.py   # Music Assistant: players, providers, queues, settings, over its API
│   │   ├── signals.py           # Everything worth a look, as one shape with a salience that orders
│   │   ├── eventbus.py          # Home Assistant's own event stream, ceilinged and counted
│   │   ├── resident.py          # The first look and the investigation: prompts, schemas, the ledger
│   │   ├── cases.py             # Four stores read as one list with three endings
│   │   ├── morph_bridge.py      # What Morph reads (feed.json, cases.json) and the Ask line's files
│   │   ├── morph_service.py     # ⚙ › Dashboard's wire to Morph's service (its request folder)
│   │   ├── features.py          # ⚙ › Features: the four switches, published to features.json
│   │   ├── shell_link.py        # The shell's address for this page, and which sidebar entry shows
│   │   ├── authoring.py         # A rule in a sentence: drafted, simulated over the recorder, then offered
│   │   ├── dispatch.py          # The notify tier's timing and words, from the household's own sentence
│   │   ├── deliveries.py        # What was sent to a phone, and what happened to it
│   │   ├── notify_learn.py      # A pattern in what somebody swipes, asked as a question
│   │   ├── household.py         # Speak first: the room somebody is in, and the refusals
│   │   ├── presence.py          # The presence loop: nightly growth notes, small touches per person, a hard budget
│   │   ├── interpret.py         # What somebody's words mean on the surface they were typed into
│   │   ├── corrections.py       # How far a correction reaches, and for how long
│   │   ├── decision_trail.py    # Why brAIn said nothing, written by the code that chose
│   │   ├── answers.py           # A card's buttons, decided once from the case (a leaf: cases and findings read it)
│   │   ├── run_queue.py         # Every Claude run takes a seat: safety, then a press, then the timers
│   │   ├── outcomes.py          # Every Resident verdict, joined to what the household did next
│   │   ├── world_model.py       # What each device is, read once per fingerprint and checked in code
│   │   ├── situation.py         # What the house is doing right now, in one line every look reads
│   │   ├── occasions.py         # The next three days of weather and calendar, as facts that expire
│   │   ├── tidy.py              # Names, rooms and aliases, proposed as one table and undone by field
│   │   ├── memory_cleanup.py    # What brAIn remembers that is wrong or useless, proposed for removal
│   │   ├── upgrades.py          # Should I update tonight — two quotes checked as substrings
│   │   ├── sre.py               # The overnight check: root causes that cite the records they rest on
│   │   ├── house_book.py        # How this house works, every sentence cited, shared by its own token
│   │   ├── triage.py            # The one door every producer files through, mutes included
│   │   ├── urgency.py           # How soon a row wants reading, and which are Urgent (a leaf: notify_router re-exports it)
│   │   ├── today.py             # Today's own half: Snooze/Ignore for the tidy and update cards, and History
│   │   ├── schedule_store.py    # When brAIn last spoke, across a restart
│   │   ├── finding_requests.py  # An answer given in HA, on its way to the one store
│   │   ├── extract_requests.py  # The memory passes the Stop hook could not sign in, run by the panel
│   │   ├── unfix.py             # A fix put back: the journal reverted, the calls listed
│   │   ├── voice_mic.py         # The phone's mic for Claude Code's /voice: page in, arecord stand-in out
│   │   ├── ownership.py         # Hand config files (every mapped tree) to the claude user — loopback route, checks, the sweep
│   │   ├── permission_mode.py   # "Let brAIn act without asking": the word the terminal reads, and the sessions that kept an old one
│   │   ├── plan_ops.py          # A fix as typed steps: six ops, checked in code, written out for the card
│   │   ├── typed_fix.py         # The steps the panel makes itself, with no model and no shell
│   │   ├── interventions.py     # Every fix looked at again after a day, a week and a month
│   │   ├── consequence.py       # What an action would reach, worked out from the registries
│   │   ├── gate.py              # Allow, ask or deny, from the person's words and nothing brAIn read
│   │   ├── security.py          # The tripwire: an entity nothing should touch, and the card when something does
│   │   ├── house_rules.py       # A person's standing limits, compiled once, only ever tighter
│   │   ├── camera_policy.py     # Which cameras, how often, and only for a trip
│   │   ├── health.py            # Is brAIn working — one verdict, and the sentence for it
│   │   ├── doctor.py            # `--deep`: every face, one real round trip each
│   │   ├── rehearsal.py         # `--rehearse`: planted defects, on the house this is
│   │   ├── capture.py           # What the analyst was sent, and the ending that grades it
│   │   ├── shadow_findings.py   # A check that runs and reaches nobody, until its numbers say
│   │   ├── scoring.py           # Precision and recall against labels — one implementation
│   │   ├── devloop/             # Opt-in: streams of evidence as issues in a private repo (DEVLOOP.md)
│   │   ├── checks/              # House checks: findings that cost nothing (snapshot → rules)
│   │   │                        #   automations, devices, registry, system, dashboards,
│   │                        #   forecasts, baseline, thermal
│   │   ├── journal.py           # One line per Claude run / checks pass, with a fixed outcome vocabulary
│   │   ├── chat_session.py      # Live `claude` stream-json sessions, as events; the registry
│   │   ├── engine.py            # How Claude is invoked (argv, env, credential, job → model/effort/schema)
│   │   ├── model_plan.py        # Which model does which job: Haiku looks, Sonnet thinks, Opus acts, Fable is a press
│   │   ├── app.js / style.css / index.html / docs.js  # The whole UI
│   │   ├── house_ui.py / house-layer.js  # The house's own layer over the page (/config/.brain/ui)
│   │   ├── run_sources.py       # Which face started a conversation (session-id ledger)
│   │   ├── chat_session.py      # …and the endings a discussion can offer as buttons
│   │   ├── todo_store.py        # Work you accepted — a list that outlives the card
│   │   ├── undo_store.py        # Short-lived, in-memory: what the toast's Undo reverses
│   │   └── *_store.py           # settings, findings, knowledge, prompts, usage
│   ├── ha-mcp-server/           # MCP server for HA API access
│   │   └── ha_mcp_server.py     # Python MCP server (stdio-based)
│   ├── scripts/                 # Shell scripts and tools
│   │   ├── ha-reload.sh         # Config reload CLI tool
│   │   ├── ha-log.sh            # Log viewer CLI tool
│   │   ├── ha-context-gen.sh    # CLAUDE.md context generator
│   │   ├── brain.sh / ha.sh     # The two CLI dispatchers everything else hangs off
│   │   ├── brain-memory.sh / brain-ask.sh / brain-undo.sh  # brain subcommands
│   │   ├── brain-edit-snapshot.py    # PreToolUse hook: hand back an unwritable file, then snapshot before Claude edits
│   │   ├── brain-arecord.py     # `arecord` for Claude Code's /voice: the phone's mic, via the panel
│   │   ├── brain_own.py         # `brain own` and both hooks' ask: make a config file writable, no sudo
│   │   ├── brain-action-gate.py      # PreToolUse hook: an acting call, asked of the gate
│   │   ├── brain-memory-extract.py   # Stop hook: what a person taught the terminal or chat, into the inbox
│   │   ├── brain_exposed.py     # What HA exposes to Assist, for the voice map and the MCP gate
│   │   ├── brain-memory-consolidate.sh / brain-study-watcher.sh  # background passes
│   │   ├── brain-run-source.sh  # Sourced, not run: claim a session id for a face
│   │   ├── brain-permissions.sh # Sourced, not run: whether a terminal session starting now may act without asking
│   │   ├── brain-memory-lock.sh # Sourced, not run: the one flock the hypothesis queue's writers share
│   │   ├── ha-addon.sh / ha-entity.sh / ha-service.sh / ha-notify.sh / ha-share.sh  # HA helper CLIs
│   │   ├── ha-yaml-check.sh     # YAML validation CLI
│   │   ├── brain-learn.sh       # Study session: facts → memory inbox, problems → findings inbox
│   │   ├── ha-selftest.sh       # In-situ end-to-end diagnostic (MCP, auth, listeners); --json
│   │   ├── brain-check.sh       # `brain check`: run the house checks through the panel API
│   │   ├── brain-doctor-deep.sh # `brain doctor --deep` / `--rehearse`: the costed checks
│   │   ├── brain-weekly.sh      # `brain weekly`: the week's numbers, and send one now
│   │   ├── brain-report.sh      # `brain report`: redacted diagnostics bundle for a bug report
│   │   ├── usage-limits-tracker.py   # Background Anthropic usage-limits daemon
│   │   ├── build-mobile-index.py     # Splices mobile UI into ttyd's HTML at startup
│   │   ├── claude-session-picker.sh  # Enhanced session picker
│   │   ├── claude-auth-helper.sh     # Auth workaround helper
│   │   ├── health-check.sh      # Startup diagnostics
│   │   ├── persist-install.sh   # Persistent package manager
│   │   ├── ha-api-examples.sh   # API usage examples
│   │   └── tmux.conf            # tmux configuration
│   ├── ttyd-assets/             # Mobile toolbar + iOS fixes injected into ttyd
│   │   └── inject.html          # Toolbar, swipe-scroll, OSC-52 copy, dictation fix
│   ├── integrations/            # HA integrations (add-on side)
│   │   ├── assist-worker-pool.py  # Fast mode: pre-warmed persistent Claude workers (default)
│   │   ├── assist-listener.sh   # Classic conversation listener (assist_fast_mode: false)
│   │   └── automation-listener.sh # Task request file watcher
│   └── custom_components/       # HA custom integration (deployed at runtime)
│       └── brain/morph/         # Morph's panel half: the shell panel (frontend/shell.js), the
│                                #   websocket API (morph/*, brain/shell), static views, frontend/
│       └── brain/
│           ├── __init__.py      # Integration setup + service registration
│           ├── manifest.json    # HA integration metadata
│           ├── config_flow.py   # UI config flow
│           ├── conversation.py  # ConversationEntity for Assist
│           ├── power_tools.py   # BRUH Power Tools: 90 registry admin services (from Spook, MIT)
│           ├── sensor.py        # Anthropic usage-limit sensors
│           ├── bridge.py        # File-based IPC with the add-on
│           ├── repairs.py       # "Restart required" repair flow
│           ├── fingerprint.py   # The code's fingerprint: a restart only when it moved (every integration's copy)
│           ├── todo.py          # todo.brain: the open findings, as HA's own to-do items
│           ├── ai_task.py       # brAIn as HA's AI Task entity, read-only and validated twice
│           ├── llm_api.py       # brAIn's measurements, for other agents, through HA's LLM API
│           ├── requests.py      # An ending given in HA, dropped for the add-on to apply
│           ├── diagnostics.py   # Download-diagnostics: the add-on's published bundle
│           ├── const.py         # Constants
│           ├── services.yaml    # Service definitions
│           ├── strings.json     # UI strings
│           ├── icons.json       # Entity/service icons
│           └── translations/en.json
├── bruh-print/                  # DYMO LabelWriter add-on
│   ├── config.yaml              # `usb: true` is the permission this add-on exists for
│   ├── apparmor.txt             # Names /dev/bus/usb explicitly, not just via `file,`
│   ├── run.sh                   # Panel as root (USB nodes), bridge as UID 1000
│   ├── panel/
│   │   ├── server.py            # Routes; one refusal (stock vs roll), everything else a note
│   │   ├── calibration.py       # Four coordinates off one printed grid -> the printable rectangle,
│   │   │                        #   plus the four bands a person asks to keep clear
│   │   ├── dymo/                # protocol.py (the bytes), printers.py (what a model can do),
│   │   │                        #   usb_link.py (getting them there, and saying why when not)
│   │   ├── render/              # label.py (the document), image.py (the one renderer),
│   │   │                        #   barcode.py (Code 128 + QR as modules), quick.py (autofit),
│   │   │                        #   fonts.py
│   │   ├── stores/              # stock (the catalog), loaded (what is in the printer),
│   │   │                        #   templates, history, settings
│   │   └── index.html / app.js / style.css
│   ├── integrations/ha-bridge.py
│   ├── custom_components/bruh_print/
│   └── lovelace/bruh-print-card.js
├── bruh-task-manager/           # CPU and memory per app (Level 1) and per process (Level 2)
│   ├── config.yaml              # host_pid (only with Protection mode off), manager role
│   ├── apparmor.txt             # /proc read, signals sent, other processes' secrets denied
│   ├── panel/                   # procs (the /proc reader), apps (Supervisor stats + actions),
│   │                            #   policy + ending (End process), settings (Level 2 status),
│   │                            #   runaway, machine, server, and the page
│   └── custom_components/bruh_task_manager/  # sensors + the runaway binary sensor
├── bruh-cooking/                # Breville+/Sage cooking appliances; requires brAIn (GPL-3.0)
│   ├── run.sh                   # require brAIn, deploy bruh_cooking, discovery, watch
│   ├── custom_components/bruh_cooking/  # from kedube/ha-breville-cooking, renamed; services.py
│   │                            #   is what brAIn calls (get_status, start, stop, …)
│   ├── frontend/                # the sidebar panel's Lit/TypeScript source (built bundle is
│   │                            #   committed under custom_components/bruh_cooking/frontend/)
│   ├── tests/                   # the integration's own suite, against a real Home Assistant
│   └── docs/api.md              # the Breville cloud protocol
├── tests/
│   └── corpus/                  # Houses and what was true of them — the frozen entries,
│                                #   the schema, the one scorer's corpus shape, and replay.py
├── docs/design/                 # The roadmap pages the checks and capabilities are built against
├── .gitignore
├── LICENSE
└── CLAUDE.md                    # This file
```
