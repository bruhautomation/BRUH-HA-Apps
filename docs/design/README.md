# Design notes

Self-contained HTML pages (open them in a browser; nothing to build). They
are the roadmap the code is built against, written before the code, and
kept here so a future change can be checked against the reasoning rather
than reconstructed from it.

| Page | What it covers |
| --- | --- |
| [brain-checks-and-self-tests.html](brain-checks-and-self-tests.html) | Deterministic house checks (findings that cost nothing), the in-situ self-test, and the feedback loop: run journal, diagnostics bundle, producer scorecard, corpus and replay. |
| [brain-capability-map.html](brain-capability-map.html) | About a hundred capabilities in sixteen themes that would make brAIn proactive rather than a reporter, with the platform enablers most of them stand on and a ranked top twelve. |

**The pages are the design as intended; the tables below are what shipped.**
Where the two disagree, the code is what shipped and the page is what was
meant — check ids, thresholds and tier contents in the pages are proposals to
be edited, not a record. **Status is maintained by hand here**, which means it
is only as current as the last person to write a release note: nothing derives
it, and nothing fails when it drifts. Grounded in **brAIn 1.48.0**.

`Since` is the release the row first shipped in. A `renamed →` row is the id
the page proposed and the id the code actually uses; a rename is worth keeping
visible, because the page's id is the one somebody will grep for.

## The checks page

Every check id the page names, and every surface it proposes.

| Check / surface | Status | Since |
| --- | --- | --- |
| `auto.dead_ref` | shipped | 1.29.0 |
| `auto.dead_service` | shipped | 1.29.0 |
| `auto.trace_error` | shipped | 1.29.0 |
| `auto.condition_never_passes` | shipped | 1.29.0 |
| `auto.already_running` | shipped | 1.29.0 |
| `auto.never_fired` | shipped | 1.29.0 |
| `auto.forgotten_off` | shipped | 1.29.0 |
| `auto.duplicate` | shipped | 1.29.0 |
| `auto.blueprint_missing` | shipped | 1.29.0 |
| `auto.trigger_on_dead_entity` | renamed → `auto.trigger_unavailable` | 1.30.0 |
| `auto.fighting` | renamed → `auto.conflict` | 1.34.0 |
| `dev.unavailable` | shipped | 1.29.0 |
| `dev.battery_low` | shipped | 1.29.0 |
| `dev.frozen` | shipped | 1.29.0 |
| `dev.implausible` | shipped | 1.29.0 |
| `dev.restored` | shipped | 1.29.0 |
| `dev.mesh_dead` | renamed → `dev.zwave_dead` **and** `dev.zha_unseen` — two radios, two questions, and a sleepy Zigbee sensor is `available` between check-ins, so availability says nothing and silence says everything | 1.30.0 |
| `dev.orphan_device` | renamed → `reg.orphan_device` | 1.30.0 |
| `dev.energy_stalled` | proposed | — |
| `org.dashboard_dead_ref` | shipped, and the one id that **kept** its `org.` prefix — it is about a dashboard, not a registry | 1.29.0 |
| `org.no_area` | renamed → `reg.no_area` | 1.30.0 |
| `org.unused_helper` | renamed → `reg.unused_helper` | 1.30.0 |
| `org.default_name` | renamed → `reg.hardware_name` | 1.30.0 |
| `sys.addon_down` | shipped | 1.30.0 |
| `sys.backup_stale` | shipped | 1.30.0 |
| `sys.disk` | renamed → `sys.disk_space` | 1.30.0 |
| `sys.log_storm` | proposed | — |
| `sys.after_update` | proposed — with the `brain.changes` diff it stands on | — |
| Run journal (`panel/journal.py`) | shipped | 1.29.0 |
| Diagnostics bundle (`/api/diagnostics`, the mirror, HA's Download diagnostics) | shipped | 1.29.0 |
| Producer scorecard | shipped | 1.29.0 |
| `protected_entities` | shipped | 1.29.0 |
| `brain check`, `brain doctor --json`, `brain report` | shipped | 1.29.0 |
| ⚙ → Diagnostics | shipped | 1.30.0 |
| `sensor.brain_health` | shipped | 1.31.0 |
| Notification router (quiet hours, urgency per producer, a hold queue) | shipped | 1.33.0 |
| `brain doctor --deep` (`panel/doctor.py`) | shipped | 1.47.0 |
| `brain doctor --rehearse` (`panel/rehearsal.py`) | shipped | 1.47.0 |
| Capture (`panel/capture.py`, off by default) | shipped | 1.47.0 |
| Corpus and replay (`tests/corpus/`) | shipped | 1.47.0 |
| Shadow mode (`panel/shadow_findings.py`, `checks.SHADOW` ships empty) | shipped | 1.47.0 |
| One report per problem, written when it happens (`panel/reports.py`) | shipped — not on the page: everything it proposed was pull-shaped, and the failure that matters is the one nobody went looking for | 1.48.0 |
| `health_degraded` in HA's Repairs | shipped | 1.48.0 |
| `brain.check` as a Home Assistant **service** | proposed — the CLI `brain check` and the Findings tab's button both exist | — |
| `button.brain_run_checks` | proposed | — |
| Repairs mirroring (`findings_to_repairs`) | proposed — 1.48.0 raises one Repairs entry for the health verdict, which is not the same thing as mirroring the findings list | — |
| Daily canary automation | proposed | — |
| `brain.why` as a service | proposed — the context-chain walk exists as the `explain_change` tool and as the Activity tab | — |
| `evaluate_condition` read tool ("rehearse an automation") | proposed — the shadow runner replays *triggers* over history, which is a different question | — |

**Checks that shipped and are not on this page**, because they were designed
elsewhere: `auto.overridden` (1.31.0), `base.unusual` and `base.stale`
(1.32.0), `forecast.decline` (1.33.0), `evening.left_open` (1.36.0),
`chore.waiting` (1.39.0), `climate.underheated` and `climate.heat_loss`
(1.40.0), `climate.preheat`, `climate.window` and `climate.freeze` (1.41.0),
`sys.entry_failed` (1.45.0), `sys.recorder_size` (1.30.0), and
`forecast.battery` (1.29.0, which the page does propose).

## The capability map

The ranked twelve is **complete**. Each row below is what closed it.

| Capability | Status | Since | Notes |
| --- | --- | --- | --- |
| #1 One-off intents | shipped | 1.46.0 | `panel/intents.py`. A sentence through the ask bar or the `brain.intent` service; Claude writes the config with reading tools only, it is checked against the replayable trigger set and the protected list, and it disarms itself with an `automation.turn_off` the code adds rather than the model. |
| #2 Habits worth automating | shipped | 1.42.0 → 1.44.0 | `panel/routines.py` mines the habit (1.42.0); `panel/trials.py` grades the trial as a replay of the week against the ledger of person-caused presses and `panel/automation_writer.py` makes Accept append a real automation (1.44.0). |
| #3 Emergency playbooks | shipped | 1.45.0 | `panel/playbooks.py` — smoke or CO, a water leak, a freeze with the heating stopped, composed deterministically from the registries, offered as a proposal with every entity named and the protected ones shown as skipped. **Against what the page says: nothing unlocks anything, ever.** |
| #4 Battery runway and decline forecasts | shipped | 1.29.0 → 1.33.0 | `forecast.battery` fits a line through sixty days of a battery's statistics (1.29.0); `forecast.decline` reads the baseline trend, which is the drift the band is structurally unable to see (1.33.0). |
| #5 Anomaly alerts that are not noise | shipped | 1.32.0 → 1.33.0 | The baseline engine (1.32.0), then the drift `base.unusual` is structurally unable to see and the router that keeps alerts from becoming noise (1.33.0). |
| #6 Overnight self-healing | shipped | 1.45.0 | `panel/healing.py`: a closed playbook of three remediations, off by default, once a night inside quiet hours, three at most, never on a protected entity, never on a row a person has touched, and **no Claude run on that path at all**. |
| #7 HA-native surfaces and chores | shipped | 1.38.0 → 1.39.0 | `todo.brain` and notification buttons, both answering through one request path (1.38.0); `panel/appliances.py` and `chore.waiting` (1.39.0). |
| #8 History replay | shipped | 1.42.0 | `panel/shadow.py` — four trigger kinds replayed over recorded history, anything else refused whole. |
| #9 Override learning | shipped | 1.31.0 → 1.46.0 | The action miner and the first override finding (1.31.0), the denominator and the override ledger (1.34.0), and the condition an automation you keep undoing is missing (`panel/conditions.py`, 1.46.0). |
| #10 The house's own clock | shipped | 1.35.0 → 1.37.0 | `panel/rhythm.py` and the morning brief (1.35.0); the weekly report and `panel/energy.py` (1.37.0). |
| #11 Climate model and scenes | shipped | 1.40.0 → 1.46.0 | `panel/thermal.py` and its two findings (1.40.0), the three live checks it exists for (1.41.0), and `panel/scenes.py` — four moods per room, swatches instead of a replay (1.46.0). |
| #12 Protected entities | shipped | 1.29.0 | Enforced at the MCP chokepoint, and re-asked wherever the panel writes YAML or acts unattended. |

### The platform enablers

| Enabler | Status | Since | Notes |
| --- | --- | --- | --- |
| Baseline engine | shipped | 1.32.0 → 1.36.0 | Numeric in 1.32.0; the page's "numeric **and binary**" closed in 1.36.0 with `panel/closures.py`. |
| Action miner | shipped | 1.31.0 | `panel/actions.py` — every change filed under a cause out of a closed vocabulary. Persists nothing; the override ledger (1.34.0) and the routines ledger (1.42.0) are the two deliberate, narrower exceptions. |
| House model | **partial** | 1.48.0 | `panel/house.py` is a **progress-and-summary surface over the stores that already exist** — every measurement answers `progress()` in one shape, aggregated behind `GET /api/knowledge/house`, drilled down per store, and read by Claude through `get_house_model`. It is **not** the page's `/config/.brain/house.json`: nothing writes a house document, and the seven measurements remain the record. |
| Shadow runner | **partial** | 1.42.0 | The history half only: `shadow.replay` answers "when would this have fired over a window the recorder holds". There is no live-event shadow, and none is needed for a trial — but "what would it do next" is still unanswered. |
| Policy engine | **partial** | 1.29.0 | `protected_entities` is the whole of it. There is no rule language, no per-face policy beyond `assist_tool_access`, and no policy surface. |
| Notification router | **partial** | 1.33.0 → 1.48.0 | Quiet hours, urgency per producer, a hold queue, and buttons on a message about exactly one finding. 1.48.0 adds the **report** router beside it (`panel/reports.py`): a failure writes one file rather than a message. Still no per-person routing, no escalation, and no digest across producers. |
| HA-native surfaces | **partial** | 1.38.0 | `todo.brain`, the notification buttons, `sensor.brain_health`, Download diagnostics, and one Repairs entry. No `brain.check` service, no `button.brain_run_checks`, no findings mirrored as repairs. |
| Vision | **not building** | — | Camera snapshots are a read tool; nothing interprets an image, and nothing on the roadmap should. |

### Also shipped, and not from the ranked twelve

| Capability | Status | Since | Notes |
| --- | --- | --- | --- |
| Knowledge tab, and every measurement saying how far along it is | shipped | 1.48.0 | The cost of a floor is silence, and silence is indistinguishable from broken. `panel/house.py` plus five states per store. |
| Milestone cards | shipped | 1.48.0 | `panel/milestones.py` — one card the day a measurement first has an answer, fired once, on the Knowledge tab and never on Insights. |
| Change-driven card refresh | shipped | 1.48.0 | A card spends a run when its inputs moved, not when a timer expired, and records why it was made or why it held. |
| Seven conversation states in the chat | shipped | 1.48.0 | One derivation, persisted in the transcript's own metadata. |
