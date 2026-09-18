# brAIn, AI-first: analysis and plan

*Grounded in brAIn 1.61.0 (September 2026). Written from a full read of the add-on — the panel, the checks and measurement layer, the prompts, the memory pipeline, the voice/chat/automation channels, the integration, the changelog and the two design pages — and from what Claude Code's headless CLI can do today.*

---

## 0. The verdict in one page

brAIn is a very good **reporter** with a model attached as a **copywriter and a grader**. That is a fair summary of the code, and it is also the design page's own summary of itself ("every one of those is a look backwards").

What the numbers say:

| Measure | Today |
| --- | --- |
| Panel code | ~47,000 lines of Python plus ~10,000 of JS in one `app.js` |
| Deterministic measurement and behaviour-mining layer | ~14,800 lines: 41 checks (~3,400), framework (~1,150), stores/ledgers/writers (~9,400) |
| Places a Claude run is made | 17, of which 7 are pure copywriting over numbers a rule already decided |
| Model tiering | None on any scheduled or pressed path; one global `model` option. The memory consolidator is the one site that picks Haiku |
| Event-driven reasoning | None. Nothing subscribes to Home Assistant's event bus; every model run is a timer, a press, or a rule's predicate |
| Memory | One 32 KB markdown file, injected whole or as a fixed-size head; no retrieval, no structure, no per-person facts |
| Surfaces | 8 tabs, 10 dialogs, 134 routes, 43 add-on options plus ~18 panel settings, 13 distinct verbs on one finding row |
| Where the last fifteen releases went | ~6 on credentials and the usage figure, ~4 on making findings less wrong, the rest on surfaces |

What is genuinely strong and must be kept: the hardening discipline (atomic writes, floors, "I could not look" versus "nothing there", consent before writes, protected entities at one chokepoint), the measurement stores (baselines, the thermal model, appliance profiles, cause attribution) which are real intellectual property, the chat's session registry, the voice worker pool, and the triage and fixer prompts, which are the best writing in the add-on.

What has to change: **the model is at the end of the pipeline and should be at the front of it.** Rules decide what matters, when to look, what to say and what to offer; Claude is handed the answer and asked to phrase it. The result is a house that produces cards nobody asked for, proposals people decline, "findings that aren't actually real", and a UI that grew a verb for every complaint. The fix is not more floors. It is one resident agent that watches the house, decides for itself what deserves attention with a cheap model, investigates with a stronger one only when it is worth it, and talks to the household in one feed — with the deterministic layer demoted from *judge* to *sensors and tools*.

And model discipline is a first-class design rule: **Haiku looks, Sonnet thinks, Opus acts, Fable is a press.** Nothing on a timer may reach Fable.

---

## 1. What brAIn is today, honestly

### 1.1 The shape

Three Claude paths (`run_claude` no tools, `run_analyst` read-only HA tools, `run_agent` everything) are called from seventeen sites. Twelve of them run whatever the global `model` option says. All of them are single-shot: gather, answer once. When a run hits its turn cap it is "landed" (told to finish with what it has), which is a truncation mechanism rather than a deepening one.

Every scheduled thing is a rule. The checks (`panel/checks/`) are pure functions over a snapshot every six hours. The behaviour-mining layer (`routines.py`, `manual_ledger.py`, `override_ledger.py`, `curiosity.py`, `proposals.py`, `trials.py`, `conditions.py`, `playbooks.py`, `scenes.py`, `intents.py`, `milestones.py`, `house.py`) reads the logbook and the recorder, decides deterministically that something is a habit, a fight, a milestone or a question worth one Claude run a day, and then hands the model a paragraph to write.

Triage (1.55–1.57) put a model *between* the rules and the person: a Claude run vets every finding before it is shown. That is the right instinct, applied at the wrong place — it grades the rules' output instead of replacing their judgement.

### 1.2 What the maintainer's own notes say users feel

The tracker is empty (two closed issues, both the maintainer's), so the user voice is in the changelog, quoted:

- *"so many of the things you surface aren't actually real"*
- *"every finding needs to be vetted by Claude, especially the dumb ones… the dumb ones are the ones that are the most annoying that AI can solve on its own"*
- *"only very critical things need to be escalated; otherwise users can see info in a card"*
- *"the activity tab is really worthless… basically zero utility"*
- *"I keep signing in over and over and this message never goes away"*
- *"the usage sensor is really bad… I'm thinking we're hammering the end point too much?"*
- The generic fix text was *"generic and useless"*.

Every one of those maps to a shipped fix, and every fix added a mechanism (a hold status, a mute, a ladder, a tier, a section) rather than removing the cause. The cause is structural: rules cannot know a house, and a model asked to grade rules learns nothing.

### 1.3 The cost picture

On a default home the scheduler spends roughly 50–150k tokens a day, dominated by card refreshes (25–45k per card run) and a first-pass triage burst that can reach several hundred thousand tokens in an hour. The `_CARD_CONTRACT` sent with every card, milestone and onboarding run is ~4 KB of which ~90% is CSS palette, mark radii and animation timing — reasoning guidance is five sentences at the bottom. The one cheap model in the codebase is chosen by a shell default in the consolidator.

---

## 2. Gaps, problems and bugs

### 2.1 Capability gaps (what a model with these tools obviously could do and does not)

1. **No event-driven reasoning.** Nothing hands the live event stream to a model. `auto.conflict`, `climate.window`, `evening.left_open` are all snapshot rules. "Something just happened; does it matter?" has no path. The panel already has a Core WebSocket client (`ha_data._ws_commands_inner`) that a `subscribe_events` listener could reuse.
2. **No way to say what you want the house to do.** "Turn the porch light off at 11 unless someone is outside" has no route to a written automation: `intents.py` refuses standing rules by design and `routines.py` only mines existing habits. The single most-asked-for thing in any HA forum is unreachable by sentence.
3. **No investigation.** Every analyst run is one pass. There is no "form a hypothesis, look further, revise" loop and no entry point for "something looks wrong here, go and find out why" outside the fixer's per-finding plan.
4. **Memory is not used in reasoning.** `memory.md` is a string block. No retrieval by relevance, no structured facts a check or a tool could consult, no provenance or confidence after filing, no per-person facts. A correction ("that fridge cycles all night") lives in prose a model may or may not see and `dev.frozen` can never read.
5. **Voice is deliberately tool-shy and person-blind.** It splices a cached area map to avoid tool calls, cannot do "check the history and tell me", never learns who is speaking (`conversation.py` never reads the request's user id), and cannot speak unprompted.
6. **The conversation entity bypasses Home Assistant.** It does not use `homeassistant.helpers.llm` or the exposed-entity lists, so "Expose to voice assistants" has no effect on what brAIn can see or do. That is a real surprise for a premier HA integration.
7. **No cross-category synthesis.** Nine categories run independently. Nothing ever asks "given everything, what is the one thing that matters this week" — the weekly report picks a finding by severity arithmetic.
8. **Automations get strings back.** `brain.run_task` / `send_prompt` return `{"response": text}` only; no structured response an automation can branch on, no streaming, a 600 s ceiling, and a scattered, undocumented event catalogue (`brain_finding`, `brain_task_complete` with no result, `brain_insight_complete`, `brain_learned`).

### 2.2 Design problems

- **Rules judge, the model phrases.** Brief, weekly, milestones, scenes, playbooks and intents are copywriting sites. `worth_saying`, `worth_asking`, `one_thing`, `ready()` are all arithmetic that decides what a household is told.
- **Three ledgers over one stream.** `override_ledger` (231 lines), `manual_ledger` (527) and `routines` (589) all persist person-caused actions out of `actions.py` and two of them carry independent circular-median pattern detectors (`manual_ledger.py:302-377` vs `routines.py:223-393`). The settle-key ledger is reimplemented three times (`findings_store`, `proposals`, `milestones`).
- **Three inboxes for one job.** Findings, Proposals and To-do are three lists of "brAIn wants a decision", each with its own badge and lifecycle. Hypotheses ride in Findings, curiosity's questions ride in hypotheses.
- **Thirteen verbs on a row.** Fix it, I've fixed it, Got it, Wrong (+note), To-do, Snooze ×4, Discuss, Check again, Elevate, Stop raising these, Advice, Put it back. Each exists for a documented reason. Together they are a card nobody can hold in their head.
- **Sixty-odd knobs in two places.** 43 add-on options (restart required) and ~18 panel settings (live), with the split invisible to the person.
- **Stores that are silent for weeks.** Baselines need 30 days, the thermal model a month and a cold night, weekend rhythm five weeks. The mitigation was to explain the emptiness (`house.py`) rather than have fewer things that can be empty.
- **English name-gates in the checks.** `dev.implausible`'s ~100-word "hot sensor" list and `chore.waiting`'s appliance words are the two places correctness depends on words rather than arithmetic; both are silently defeated on a non-English install.
- **The prompt is 90% stylesheet.** `_CARD_CONTRACT` should be a rendering concern, not a reasoning one.
- **`server.py` is 10,745 lines and 134 routes** in one module with the scheduler, the job queue, chat wiring, memory plumbing and diagnostics all in one import graph.

### 2.3 Concrete bugs found in this read

| # | Where | What |
| --- | --- | --- |
| B1 | `hypotheses.jsonl` | Three uncoordinated writers with unlocked read-modify-write: `brain-learn.sh` appends with `>>`, the consolidator's `retire_stale_hypotheses`, and the panel's `hypotheses.py` (every `list_all()` calls `_expire()` which rewrites). A study session's hypothesis appended inside another writer's window is silently dropped. Same class as the `tmp+rename` bug already fixed for the other stores. |
| B2 | `server._drop_from_inbox` (~9194) | Reads all inbox files, rewrites the one holding the id. If the consolidator archives that file in between, the rewrite recreates it: consumed facts reappear as pending. |
| B3 | `ha-context-gen.sh:188` | `head -c 4096` byte-cuts `memory.md` into the terminal's `CLAUDE.md`, mid-fact and never reaching "Device notes" (the last section). `categories.memory_excerpt` cuts on a line boundary for exactly this reason. |
| B4 | `ha_data.MEMORY_CHARS = 34_000` | Sized for the default 32 KB; `memory_max_kb` allows 64. A raised cap silently truncates every insight prompt, the failure this constant was introduced to prevent. No test binds it to the schema's bound. |
| B5 | `server._design_scenes` (~4979) | `create_task(_name_and_offer)` with no synchronous "starting" flag: two presses on one room spawn two naming runs. The one place the file's own rule is skipped. |
| B6 | `server.JOBS` | `fix:{ts}` / `plan:{ts}` entries are never popped once done. In-memory only, but the one uncapped dict in a file where everything else has a `MAX_`. |
| B7 | `server.py` ~3438 and ~8 handlers | Synchronous `read_text`/`unlink`/`write_text` on the event loop (`h_index` static reads, `h_history_*`, `h_prompts`, `h_card_tags_put`, `h_feedback_delete`, `h_onboarding_reset`). On an SD card under a checks pass this stalls the loop that drives the chat stream and the terminal proxy. |
| B8 | `assist-worker-pool.py` | `PARTIAL_MESSAGES_OK` flips off for the process lifetime on one early worker death; no re-enable path, so a startup blip disables token streaming for voice until restart. |
| B9 | `triage.py`, `intents.py`, `curiosity.py`, `fixer.py` | Four hand-rolled JSON-with-fences parsers; the `hold`/`held` near-miss already bit one. The CLI's `--json-schema` structured output is unused anywhere in the add-on. |
| B10 | `onboarding.py` recommend | Runs `run_claude` (no tools) where every other analytical site moved to `run_analyst` because snapshot lost to search. The one run that most needs to look at a house before proposing cards cannot. |
| B11 | `brain-learn.sh` | Study runs 30 minutes with no turn cap on the global model — the largest uncapped spend in the add-on, with no warning. |
| B12 | `automation-listener.sh` / `brain.run_task` | Inherits the full `settings.local.json` grant (`Bash(*)`, `Write`, `Edit`, all MCP) with no per-call tool scoping; the largest privilege a YAML automation can reach. Voice has `mcp_only`; tasks have nothing equivalent. |
| B13 | `knowledge_store.py`, `feedback_store.py` | Unlocked read-modify-write inside one process's thread pool; an insight run's `add_fact` racing `h_feedback_add` drops a write. |
| B14 | `triage` drain | 10 findings per 60 s tick with 40-turn tool runs: up to ~600 findings/hour, gated only by the usage budget, not a daily ceiling. |
| B15 | `hypotheses` reject | Bookkept in two stores; the CLI fallback and study paths write only `hypotheses.jsonl`, so a rejection given while the panel is down never reaches the card prompt's dead-ends block. |

---

## 3. Principles for the next brAIn

1. **The model is the mind; rules are senses.** A rule may raise a signal. It may not decide what a person is told, what is offered, or what is remembered.
2. **Attention is budgeted, and cheap attention is spent freely.** A Haiku look at a batch of signals costs a few thousand tokens. Spend that every few minutes. Spend Sonnet when Haiku says "worth a look". Spend Opus when Sonnet wants to act or is unsure. Spend Fable only on a press or a named deep review, with the cost on screen.
3. **One object, one feed, three answers.** Everything brAIn wants to say is a *Case* in one stream, and every case ends the same three ways: *Do it*, *Not now*, *Wrong, because…*.
4. **Memory is structured, sourced and retrieved.** A fact has a subject, a source, a confidence and a date, and only the relevant ones ride into a prompt.
5. **Say what you want, in words.** A sentence becomes an automation through draft → simulate → approve → trial → keep.
6. **Keep the hardening.** Consent before writes, protected entities at the chokepoint, undo, "could not look" never read as "nothing there". These are the reasons brAIn can be trusted with a house and none of them go.
7. **Fewer surfaces than habits.** Four tabs, three verbs, about fifteen options. Adding a tab or a verb needs an argument about what it replaces.

---

## 4. Architecture

### 4.1 The Resident (one agent, budgeted and tiered)

The Resident is not one eternal process. It is a **loop in the panel** that owns attention and spawns model runs by tier.

```
HA event bus (WS subscribe_events)  ──┐
Checks pass (6h, unchanged)          ──┤
Baselines / thermal / appliances     ──┤──▶  Signals (deterministic, scored,      
Person / automation / service events ──┤     never a verdict)                     
Notifications & replies (the person) ──┘              │
                                                      ▼
                                   First look  ── Haiku, every N min or on a hot signal,
                                   structured output: ignore | watch | investigate | act
                                                      │
                                          ┌───────────┴────────────┐
                                          ▼                        ▼
                                  Investigate ── Sonnet        Act ── plan (Sonnet, read-only)
                                  with tools, writes a Case    → consent → apply (Opus)
                                          │
                                          ▼
                                   Case in the Home feed; endings teach memory
```

**Signals.** A signal is `{kind, subject, salience, evidence, seen_at}` and comes from: every existing check row (unchanged code, new destination); a baseline deviation past its band; a thermal or appliance event (a cycle ended, a fall past `k`); a `state_changed` on an entity brAIn has a fact about or that is protected; an automation trace error; a service call from a person that undoes an automation (the override detector, reused); a person arriving or leaving; a notification reply. Salience is arithmetic and honest about being arithmetic — it orders, it does not decide.

**First look (Haiku, `effort: low`).** A batch of signals plus the *relevant* memory facts and the open cases, with `--json-schema` output: for each signal `ignore | watch | investigate | act` and one sentence. Cheap enough to run every 5–15 minutes and immediately on a hot signal (a leak sensor, a protected entity moving, a person-level event at an odd hour). Its whole job is the sentence the maintainer asked for — *"the dumb ones are the ones that AI can solve on its own"* — done before anything is filed rather than after.

**Investigate (Sonnet, `effort: medium/high`).** Only for `investigate`. Read-only tools: history, statistics, logbook, traces, the measurement tools (4.3), memory recall. Writes a **Case**: a claim in one sentence, the evidence, what it looked at, a confidence, and zero or more proposed actions, each with a consent shape (a notification, a change to a file, a service call). Escalates to Opus when it reports `confidence < 0.5 and stakes: high`, never on a timer.

**Act.** Exactly today's plan → consent → apply path, kept whole (`fixer.PLAN_SYSTEM`/`FIX_SYSTEM`, `unfix.py`). Apply runs on Opus at `effort: xhigh` because it is the one path that changes a house. Overnight healing's closed playbook stays as-is: a model choosing what to restart at 3 am is still a guess.

**Budget ledger.** One table, per tier per day, read from a single setting (`thinking: light | normal | generous`) and from the usage tracker's real window. The first look never stops (it is the cheap tier); investigations queue when the Sonnet allowance is spent; Opus and Fable never run unattended past their allowance. The ledger rides in `/api/diagnostics` and on the Home feed's foot ("Looked 96 times, investigated 3, changed nothing").

### 4.2 Cases (one object replaces findings, hypotheses, proposals, chores and curiosity)

```
Case
  id, kind: problem | opportunity | question | chore | change
  claim (one sentence), detail, confidence, stakes
  evidence[]  (entity, number, when)
  investigation (view-only transcript link, the run id)
  actions[]   {label, shape: notify|edit_file|call_service|write_automation, consent}
  status: open | watching | acting | done | dismissed | wrong
  memory_hint (what an ending should teach)
```

A **problem** is today's finding. An **opportunity** is a proposal (an automation, a scene set, a playbook). A **question** is a hypothesis or a curiosity ask. A **chore** is a to-do. A **change** is something brAIn did (a fix, a heal) that is news to read. One store, one settled ledger, one undo, one mirror into `todo.brain` and Repairs (both kept), one scorecard.

Three endings and one menu: **Do it** (runs the action or marks the chore done), **Not now** (a snooze with the agent choosing when to bring it back, said on the card), **Wrong, because…** (the correction path, unchanged: verbatim into future prompts, filed to memory as a correction). Discuss, Check again, Elevate, Mute-the-rule and Advice move into an overflow, because they are still real, and rare.

The triage module becomes the first look. The producer scorecard stays and now grades the *Resident's* precision, which is the number the design page always wanted.

### 4.3 Measurements become tools

The stores are the add-on's real knowledge and today only rules read them. They become MCP tools on `ANALYST_TOOLS`, readable by every run and by voice:

| Tool | Answers | Backed by |
| --- | --- | --- |
| `what_is_normal(entity, at?)` | median, spread, deviation now, trend | `baselines.py` |
| `room_physics(area)` | loss rate `k`, gain `h`, time constant, hours to warm to a target | `thermal.py` |
| `appliance_status(entity)` | idle / running / finished-and-waiting, measured thresholds | `appliances.py` |
| `who_changed(entity, window)` | cause chain, proximate and root, person / automation / voice / brAIn / unattributed | `actions.py` (already partly `explain_change`) |
| `habits(entity)` | the days, the band, the share, still-happening | one module replacing the three ledgers |
| `door_habits(entity)` | usual-open share per hour of the week | `closures.py` |
| `house_rhythm()` | wake and settle, weekday and weekend, spread | `rhythm.py` |
| `simulate_automation(config, days)` | when it would have fired, and against the person ledger, agreed/contradicted | `shadow.py` + `trials.py` |
| `recall(query, subject?)` | ranked memory facts with source and date | memory v2 |
| `remember(fact, subject, confidence)` | queues a fact | the inbox, unchanged |

The checks keep running every six hours and produce signals. The behaviour-mining *producers* (routines, proposals, conditions, playbooks, scenes, intents, milestones, curiosity) stop being scheduled and become **skills the Resident invokes** when a signal or a person asks: "design scenes for the lounge", "this automation keeps getting overridden — propose the condition", "a leak sensor was added — draft the playbook". Same code, new caller, no timer.

### 4.4 Memory v2

`memory.md` stays as the human-readable, editable document. Underneath it is a **facts store**:

```
{subject: "sensor.garage_fridge_temp" | "area:lounge" | "person:ben" | "house",
 predicate: "runs continuously" , value: "…", text: "The garage fridge is meant to run 24/7",
 source: "correction|card|study|voice|chat|person|check", confidence: 0.9,
 observed: "2026-09-12", expires?: "…", run_id?: "…"}
```

- **The consolidator (Haiku, unchanged cadence) writes both**: facts in, document rendered out. Editing the document parses back into facts through the same Haiku pass (a fingerprint mismatch already detects a hand edit; it now triggers a re-parse rather than a discard).
- **Retrieval.** Every run gets the *core* facts (preferences, nicknames, standing rules) plus facts whose subject overlaps the run's entities, areas, domains or the person asking; chat and voice get a Haiku-scored top-k over the query. Nothing gets the whole document by default; the fixer may still ask for everything.
- **Checks may consult facts.** `dev.frozen`, `dev.implausible`, `chore.waiting`, `base.unusual` read `recall(subject=entity)` for a standing exception before filing — a correction finally reaches the rule it corrects, which is the loop the Wrong button always promised.
- **Per person.** Facts keyed to `person.*`; voice passes the pipeline's user id (Assist supplies it) so "I like the lounge warm" is Ben's fact, not the house's. This is also the first honest answer to `manual_ledger.EXCLUDED`: a person can be asked about their own late-night presses and nobody else's.
- **Hooks teach memory.** A `Stop` hook on chat and terminal sessions runs a Haiku extraction pass over the turn for durable facts, corrections and stated intents — today only voice reflects (`reflect_on_transcript`). The terminal is where the most knowledgeable person in the house types the most, and it teaches nothing.
- **Provenance stays.** Every fact carries its source and run id, so the House view can answer "why do you think that?" with a link to the run.

### 4.5 Talking to the house

- **Standing automations in words.** From the ask bar, chat or voice: the Resident drafts the automation (Opus, `effort: high`, tools), runs `simulate_automation` over the last two weeks, and shows the case: *"Would have fired 9 times; twice while someone was in the garden"*. **Do it** writes it through `automation_writer` (append, reload, verify, undo — unchanged) and opens a week's trial graded by `trials.py`; the trial's report is a *change* case. `intents.py`'s one-off path becomes a special case of this, not a separate feature.
- **Conversational notifications.** A push carries the case id; replying to it (the companion app's `reply` action, or the To-do/Repairs surfaces already wired) continues that case's conversation with the Resident, so "why?" and "do it but only on weekdays" work from a lock screen.
- **HA-native LLM API.** The conversation entity implements `homeassistant.helpers.llm` so exposed-entity settings apply to voice by default, HA's own intents (turn on, set temperature) are handled natively at zero tokens, and brAIn's MCP tools are added on top for the questions native intents cannot answer. A per-agent option keeps today's full-house mode for the household that wants it.
- **Voice that can look things up.** The pre-warmed worker keeps the area map, gains `recall`, `what_is_normal`, `who_changed` and history, and runs on Sonnet by default; the first-look Haiku model handles the "turn on the kitchen light" class through HA's intents before Claude is ever spawned.
- **Proactive speech, opt-in.** A case with `stakes: high` and a `tts` target announces itself in the room the rhythm says people are in. Off by default, one option.
- **Automations get structure.** `brain.ask` (new) takes a question and an optional JSON schema and returns `structured_output` (the CLI already supports it); `brain.run_task` takes `tools: read_only | house | full` so a YAML automation cannot reach `Bash(*)` unless it asks to; events are one documented catalogue (`brain_case`, `brain_case_ended`, `brain_change`, `brain_learned`) each carrying the case.

### 4.6 Surfaces: four tabs, not eight

| Tab | Holds | Replaces |
| --- | --- | --- |
| **Home** | The feed of cases, newest and highest-stakes first, with the three endings inline and the Resident's foot line ("looked 96 times today, investigated 3"). Insight cards pinned above it, live. | Findings, Proposals, To-do, hypotheses in Findings, the milestone cards |
| **Ask** | Chat (default) and the classic terminal (a face switch, unchanged), with cards and cases rendering inline in the conversation and the Chats rail. The ask bar lives here. | Terminal, the Insights ask bar |
| **House** | What brAIn knows: the memory document with its facts and sources, the measurements with progress, what happened today (episodes, on request), the scorecard. | Knowledge, Activity, the Insights tab's category management |
| **Settings** | ~15 options in one place, the account, the thinking budget, and a Support drawer (diagnostics, doctor, rehearsal, reports, docs). | ⚙, Docs, the 43 options |

The `todo.brain` entity, Repairs and the notification buttons stay: they are the surfaces outside the panel and they already speak the case vocabulary.

---

## 5. Model discipline

The rule the plan is built on: **use the smartest model only where intelligence changes the outcome, and show the cost where it does.**

| Job | Model | Effort | Why |
| --- | --- | --- | --- |
| First look at signals, classification, relevance scoring, memory extraction, consolidation, scene/playbook naming, notification wording, episode summary | **Haiku** | low | Volume work with a closed output vocabulary; wrongness is cheap and corrected next pass |
| Investigations, insight cards, the morning brief, the weekly report, curiosity ("why did you…"), voice, chat default | **Sonnet** | medium (cards) / high (investigations) | Reasoning with tools where a wrong answer costs a card, not a house |
| Fix apply, writing a standing automation, an investigation Sonnet flagged as high-stakes and uncertain, the "one thing this week" synthesis | **Opus** | high / xhigh (apply) | Changes a house or decides what a person acts on |
| **Deep review** — a monthly "state of the house" with capital-scale advice (replace the boiler? which rooms leak heat and what it costs), a root cause Opus could not settle | **Fable** | high | Only by press or by a named, opt-in monthly schedule, with the estimated cost on the button; never on the attention loop |

Mechanics: every call site passes `model=` and `effort=` from one `MODEL_PLAN` table (the three run functions already take `model`); `--json-schema` everywhere JSON is parsed (kills the four parsers, B9); `--max-budget-usd` on API-key installs; the `thinking` setting scales the per-tier daily allowances; the usage tracker's real window is the hard stop for Sonnet and above, never for Haiku. The `model` option becomes an *override* for people who want it, not the plan.

Prompt hygiene that comes with it: `_CARD_CONTRACT` splits into a 600-byte reasoning contract and a rendering spec the panel applies (the design system becomes a stylesheet injected into the card frame, not 3.5 KB of prompt per run); the triage/fixer/curiosity prompts are the templates for the Resident's; every prompt gets the prompt-caching order right (stable system first, volatile last).

---

## 6. What to remove, and why

| Remove | Because | What replaces it |
| --- | --- | --- |
| Proposals tab, To-do tab, Activity tab, Knowledge tab, Docs tab | Four inboxes and two records for one household; tabs already broke the top bar twice | Home, House, Settings |
| The `hypotheses` store and `curiosity.py` as a scheduled producer | A question is a case; the 1/day budget becomes the Resident's | `kind: question` cases |
| `override_ledger.py`, `manual_ledger.py`, `routines.py` as three stores | Same stream, two pattern detectors | one `habits` store and tool |
| Scheduled `proposals`, `conditions`, `playbooks`, `scenes`, `intents`, `milestones` producers | Rules deciding what to offer, then declined | The same modules as skills the Resident calls on demand |
| `sys.update_pending` (shadow), `auto.duplicate` | Technically-true rows; exact-JSON duplicates are rare | none |
| The `reg.*` checks as recurring findings | `info` tidiness every six hours | one onboarding sweep and a House "tidy-up" section |
| The `snapshot` gather mode | Measured worse than search; kept only as a fallback that hides failures | Search only; a failed search is a case saying so |
| Snooze's four sub-choices, Elevate, Advice, Check again, Mute as row buttons | Thirteen verbs | Do it / Not now / Wrong + overflow |
| ~28 of 43 add-on options | Turn caps, history knobs, four `access_*` flags, two package lists, mode flags nobody reads | ~15 options; the rest become defaults or live settings |
| `_CARD_CONTRACT`'s design system in the prompt | 90% of the tokens per card are CSS | a stylesheet in the frame |
| Per-check English name gates | Silent failure off-English | a `recall` of the entity's facts plus the first look's judgement |

Not removed: the checks (they are free sensors), the measurement stores (they become tools), `doctor`/`rehearsal`/`reports` (moved to Support), overnight healing's closed playbook, the chat registry, the voice pool, protected entities, undo, the corpus.

---

## 7. New things that make it the premier HA app

1. **The Resident and the Home feed** — a house that is watched, not polled, with a line at the bottom that says what it did today.
2. **Standing automations in a sentence**, simulated before you say yes and trialled for a week after.
3. **"Why?" on everything** — every case links to the run that produced it and every fact to its source.
4. **Memory that reaches the rules** — a correction stops the rule, not just the wording.
5. **Voice that knows who is talking and can look things up**, and honours HA's exposure settings.
6. **Conversational notifications** — reply to a push, continue the case.
7. **Deep review (Fable, on a press)** — a monthly written assessment of the house: heat loss in money, the devices most likely to fail next, the automations that fight, what to buy and what not to.
8. **Structured `brain.ask` for automations** and one documented event catalogue.
9. **A visible thinking budget** — light / normal / generous, with the ledger on the feed.
10. **A four-tab panel** that fits a phone without a third breakpoint.

---

## 8. Fixes to make regardless (Phase 0)

B1–B15 above, in this order of risk: B1 and B13 (lost writes), B2 (inbox resurrection), B12 (task tool scoping), B7 (event-loop stalls), B9 (structured output), B3/B4 (memory truncation), B14 (triage ceiling), B5, B6, B8, B10, B11, B15. Each needs the test shape this repo already insists on: drive the real writers, reproduce the failure before asserting the fix.

---

## 9. Roadmap

Each phase ships as ordinary releases and is gated by a measurable acceptance test, because "smarter" is not a thing a release note can claim.

### Phase 0 — Discipline (1–2 releases)
Model plan table with tiering and effort at every site; `--json-schema` everywhere; the card prompt split; the budget ledger; B1–B15.
**Accept:** tokens/day on the reference home down ≥40% with cards unchanged in the corpus replay; zero hand-rolled JSON parsers; every run's model and effort in the journal.

### Phase 1 — The Resident and Cases (2–3 releases)
`subscribe_events` listener → signals; first look on Haiku; cases store unifying findings, hypotheses and to-dos (migration keeps every settled key); Home feed with three endings; triage retired into the first look; scorecard grades the Resident.
**Accept:** on the maintainer's house and the corpus, precision of surfaced cases ≥80% confirmed over two weeks (the scorecard); first case with an investigation within an hour of a fresh install; first look cost <10% of the day's tokens.

### Phase 2 — Tools and Memory v2 (2 releases)
Measurement MCP tools; the `habits` store replaces three ledgers; facts store with retrieval, provenance and per-person subjects; checks consult facts; `Stop` hook memory extraction for chat and terminal.
**Accept:** a Wrong correction on a frozen-sensor case suppresses that rule for that entity on the next pass (a driven test); an insight prompt carries <25% of the memory bytes it does today with the corpus cards unchanged; a fact can be traced to its run from the House view.

### Phase 3 — Talk (2 releases)
Standing automations by sentence (draft → simulate → approve → trial); conversational notifications; HA LLM API with exposure respect; per-person voice; `brain.ask` structured; event catalogue; opt-in TTS.
**Accept:** ten scripted sentences produce ten automations that pass simulate and write on the demo house; an entity un-exposed in HA is invisible to voice in default mode; a reply to a push continues the case.

### Phase 4 — Four tabs (1–2 releases)
Home / Ask / House / Settings; ~15 options; producers become skills; `server.py` split into `panel/api/`, `panel/resident/`, `panel/memory/`; the measure scripts re-baselined.
**Accept:** tab count 4 at every width the top bar test measures, no third breakpoint; options ≤15 with `translations/en.yaml` in step; `server.py` under 2,000 lines.

### Phase 5 — Deep review (1 release)
Fable-tier monthly review by press or opt-in schedule, cost shown; Opus escalation from investigations; cross-category "one thing this week".
**Accept:** the review is never spawned by the attention loop (a test); its cost is journaled and rendered on the button before the press.

---

## 10. Cost model, after

| Tier | Runs/day (typical home) | Tokens/run | Tokens/day |
| --- | --- | --- | --- |
| Haiku first look | ~100 (every 15 min + hot signals) | 2–4k | 200–400k, at Haiku's weight against the window |
| Haiku extraction/consolidation/naming | ~5 | 3–8k | ~30k |
| Sonnet investigations | 2–6 | 15–30k | 40–180k |
| Sonnet cards (change-driven, unchanged) | 0–3 | 10–20k (contract split) | 0–60k |
| Opus apply / automation drafting | 0–1 | 30–60k | 0–60k |
| Fable deep review | press / monthly | 100–300k | shown before pressing |

Against today's 50–150k/day of mostly Sonnet-or-Opus card refreshes, the window is spent on looking rather than re-writing, and the expensive tiers are spent only on things that were worth a look.

---

## 11. Open decisions for the maintainer

1. **Subscription vs API key.** Everything here runs on `claude -p` with the subscription OAuth, as today. `--max-budget-usd` and priority tiers only apply on API-key installs; the plan keeps both working.
2. **How long a first-look interval.** Fifteen minutes is the suggested floor; a "hot signal" list (leak, smoke, protected entity, person-level event in quiet hours) bypasses it. This is the one number worth measuring on real houses before it becomes a default.
3. **Whether cases keep the `held` idea.** The first look's `watch` verdict is the honest replacement (it says it is waiting for more evidence), but the "Looked-at" filter people can inspect is worth keeping in the overflow.
4. **Migration of the Findings tab's ledger and the corpus labels** — the settled keys and ending words are one list published in three places today; the case endings map onto them (`done→Do it`, `ignored→Wrong`, `accepted→Do it`) so no label is lost.
5. **The HA LLM API floor.** `homeassistant.helpers.llm` is 2024.6+; the integration's floor is 2023.6 and would move.
