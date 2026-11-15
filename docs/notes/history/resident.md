# brAIn: the Resident: history moved out of docs/notes/resident.md

What each rule in `docs/notes/resident.md` cost to learn: the reports and houses that showed the failure, the fixes that were tried first, owner quotes and pointers to tests. None of it is needed to follow the rules; it is here for the next person who wonders why a rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold. Each entry is the text as it stood in the note, cut out of the bullet named in its heading.

## History is a pane

- It was a closed `<details>` under Today whose rows carried only Restore, so it read as a pile nobody could prune, with no sentence saying what it was. It is Insights › History now.
- One line says what the filter holds because a paragraph under the heading said what History and Restore were, and the filter's line said it again.

## How many findings are waiting for a look is a fault row once it is old

- Failed looks leave rows on `triaging` or showing "Nothing finished looking at this one" and nothing said how many.
- `test_resident_unjudged` drives a row left by a failed look back into the pending list.
- **And the row says why, in its own words**: it sent a reader to "the usage limit above", and the usage-limit row stands down under 10% of the day's runs — twelve refused looks is two hours of a look every ten minutes, exactly this row's threshold, and the row pointed at nothing.
- A day of looks over a house whose rows flap was driven end to end and every row was judged within a look or two; that is why a wait past two hours is read as looks refused or held.

## A row's wait runs from when it was sent to the look

- Every clock read the filing `ts`: `stale_triaging` called a re-sent row "left mid-look past the hour" on the next minute sweep, before any look was due, and showed it under `triage.UNJUDGED`; and `unjudged_open` re-offered silence-surfaced rows only within a day of the FILING, so it was never offered again. The fault sweep read "18 findings are still waiting for a look, oldest 328 h" on a day the first look ran 120 times (reports #82).

## A row's look is reached in bounded time

- Test: `tests/test_resident_waiting.py`. Three ways a filed row went on "waiting for a look" for days on a house whose looks all succeeded.
- **The pending cap dropped filed rows to keep live copies**: a chatty protected entity is one hot signal per change, held raw until a look folds them, so between two timer looks (the hot quota spent) it put hundreds of copies of ONE signal on the list, and past `RESIDENT_QUEUE_MAX` the cap's only non-hot victims were the rows a rule filed — re-offered every minute and dropped by the same tick, least salient (the oldest) first, for ever.
- **The reserve was filled by salience**, whose recency weight favours the newest row, so a row that missed one look missed every later one.
- A `watch`/`investigate` row stays `triaging` while its investigation runs and was counted by `_waiting_rows`.

## A held verdict a later report contradicts is looked at again

- Four copies of "this window is wrong" stayed held as "zero cooling in late September is normal" while their own details showed hours of cooling the sensor missed; a later copy proved it and nothing went back to the verdicts.
- `refresh_details` was the one mutator without the store lock (it is locked now).

## Every producer files through `triage.gate`

- The separate triage drain is gone: it had no caller but its own tests once the Resident's first look took the queue, and keeping a second judge with a second vocabulary (`elevated`/`held` against `ignore`/`watch`/`investigate`/`act`) was two answers to one question.
- An AST sweep in `tests/test_triage.py` asserted no `findings_store.add_many` call in the panel is missing its `triage.gate`. What the drain's tests pinned that the Resident's did not — two ticks at once spend one look, memory reaches the look, a skipped or unreadable reply holds nothing — was driven on the Resident path in `tests/test_triage_retired.py`.

## "What you'd need to do" is written by the run that LOOKED

- A check wrote *check its power and its connection (batteries, Wi-Fi, the hub it pairs through), then reload its integration* under eleven different devices in one pass, and a person holding the device called it generic and useless, which it is.
- The retired triage drain wrote the specific answer first; `record_triage` writes no `fix` now.
- Two rows in the same report were the add-on about itself — `dev.unavailable` filing *brAIn Usage Limits has been unavailable for more than a day* with battery advice, on the day the tracker was stuck. That is why `checks/devices.SELF_PLATFORMS` exists.
- Seven rows about a September too warm to fit a heat-loss model to were one fact; that is why `reports.faults` folds the checks a missing snapshot key took down into that key's row.

## The first look is cheap by contract

- The sweeps run on a 60s cadence because two full store loads twelve times a minute on an SD card is not what the 5s tick is for.
- A failed run surfacing every filed row with `RUN_FAILED` is silence surfacing one step earlier than the retired triage did.

## An investigation reads and a case is what it writes

- `test_resident_loop` asserted the analyst stub was never reached on the hot safety `act` path, because "nothing on this path calls a service" is a claim about the process and not about the prompt.

## A filed row the first look thinks is worth more than nothing is looked into BEFORE anybody is asked

- *"Claude is turning up a ton of findings it can answer itself"*: a `watch` or `investigate` (or a non-hot `act`) on a check's row elevated it to the person first and investigated it second, if the day's allowance reached it at all, so the card was read in its rule's generic words and the answer arrived after the question.
- A `fix` telling somebody to read the Supervisor log about brAIn's own error was the case that added "never a log, a trace or a file brAIn can read".
- `SONNET_PER_DAY` was doubled (6/16/32) with this change.
- The outcome log carries the investigation's verdict beside each watched row's look, which is why `test_outcomes` counted eight rows for four looks.

## "Nothing finished looking at this one" is a state a look can still end

- A real house had twelve of fourteen open findings carrying `triage.UNJUDGED`. Silence surfacing is right and stays; what was wrong is that it was permanent and reached in steady state. Four causes, each reproduced in `tests/test_resident_unjudged.py` before the fix.
- **A late verdict was dropped**: `record_triage` touched `triaging` rows only, so a row the stale sweep (or a failed look, `RUN_FAILED`) had shown kept "nothing looked" for life even when a look answered about it minutes later.
- **The batch was hot-first**, and every change to a protected entity is hot, so a busy house filled every slot.
- **The queue cap could drop a filed row**; it takes a live one first.
- **Hot looks a minute apart could spend `MAX_PER_DAY` by mid-morning**, and the share meant to stop it did not: 150 hot looks plus a look every ten minutes is past 200 by late morning, so every row filed after that waited until midnight with every look that ran succeeding (reports #82, five fixes that each moved a symptom).
- `tests/test_resident_two_days.py` drove two simulated days (150 chatty entities, a pass every 6 h, real caps, the stores on the simulated clock) and asserted every filed row a verdict within two looks.

## A tripped safety detector is filed by code, not by a verdict

- The only route from a leak to a phone used to be a Haiku look that ran (credential, `auto_enabled`, budget, day cap), parsed and answered exactly `act` — and the never-ignore floor matched words in the signal's KIND, which for a bus signal is `state`, so the real floor was `watch`; the case it filed sat under `resident`, which had no urgency entry, so quiet hours held it until morning; and its text was a fixed sentence, so the second leak on a sensor deduped against the first for ever.
- `tests/test_safety_lane.py` drove `_note_safety` inside a running loop into the REAL `_announce_findings` during quiet hours with every gate closed.

## The deeper look corrects the cheaper one

- The investigation was told the row it was investigating was "already in front of the homeowner, do not claim it", so it abstained (a paid run with no trace) or filed a differently worded sibling.

## A finding is judged on its claim

- A real house had "this sensor reads 0" rows held as "zero cooling in late September is normal for the season" while each row's own detail said the air conditioning ran for hours that day — a reason about one number, answering a claim about the pair. Two causes: the prompts never said what was being judged, and the first look could not SEE the detail (a filed row's title and sentence already filled `ROW_CHARS`, so the detail was cut on exactly the rows a rule filed).

## An open card never carries a look's argument for not showing it

- A shown reason about the list took the card's what-to-do with it (#448).
- "the speaker has been switched off since the evening" and "all the plugs are connected again" were `watch` reasons beside cards that stayed on the list asking somebody to act (#537). Test: `tests/test_resident_already_recovered.py`.
- The investigation's `answered` word: `tests/test_already_known_is_not_asked.py`, #697.
- The first fix for "already known" was a regex over sentences with "already" in them, and it held "the automation already locks the door at night, so the lock motor needs replacing" and "you already said it is fine, but the battery is now at 4%" — every such sentence is a test that must still file.

## A look's count may not disagree with its detail

- #443: "49 drops" beside a detail saying 36.

## A look's reason that only repeats the row is not a conclusion

- `refine` wrote the investigation's claim as the triage reason, so a Resident card read "brAIn checked: <its own title>" with no conclusion ever written. `add_case`'s own stamp was pinned by `test_cases`.

## Grounding reads the tool traffic, never the answer

- `parse_case`'s invented-evidence guard compared evidence against entity ids in the CLI's final reply — on a CLI that echoes its JSON every cited id was "read", and on one answering with `structured_output` and a sentence no neighbour ever was, so real cases were refused and logged as "made no claim".

## "It did not run" is grounded in the automation that runs it

- A case said the basement dehumidifier "hasn't run" while the house was damp, from its state history and whichever humidity reading the run found, while the automation that drives it triggers on one other sensor. The controlled-by lines in the prompt (`_CONTROLLED_BY`) already named that automation and a run skipped them, so the check became a gate.
- #558: a dehumidifier was called idle or broken from its plug's power while the one sensor its automation starts it on sat under the threshold. Test: `tests/test_not_running_waits_on_its_trigger.py`.

## How long a door has been open is read off its history

- #580, `tests/test_claims_read_the_history.py`: a case said a garage door had been open 70 minutes; it had opened and closed eight minutes apart.
- The hall motion sensor listed ahead of the patio door in a case's evidence was read as the door and refused "open for 40 minutes" from its own six; that is why only door-classed sensors count.

## An escalation is a second opinion

- It used to re-run the identical prompt and fall back to the unsure case on any no-claim, so the one answer an escalation exists to give was the one it could not.

## A stepped-up look whose allowance is spent goes on at its planned tier

- `tests/test_resident_falling_behind.py`. `generous` steps the first look up to Sonnet, and the ledger then held it on the Sonnet allowance: a look every ten minutes is 144 a day against 32, so from early morning nothing looked at the house, health said so for the rest of the day, and the pending list grew toward its cap behind the hold (#661, #665). A typed model the ledger bounds did the same.
- The pending list folded only past the cap: a subject that changed every ten minutes through a held day was one row per change.
- Neither health row was changed by the fix: both are now rarely true of a healthy house.

## A look only the owner's model option promoted to Sonnet

- #630, `tests/test_resident_look_owner_model.py`: with the add-on's model option on Sonnet every look ran on Sonnet and was charged there; with the half reserve the looks and the investigations still shared one allowance, which was spent by the small hours and parked investigations for the rest of the day.

## Investigations the ledger cannot pay for are PARKED

- Back on the pending list they were re-judged by a fresh paid look every minute while hot, with no memory of the verdict — a hot one could spend the day's 200 looks asking a question already answered "investigate".

## A watch counts what it withholds

- The re-admission test compared one burst's `repeats` (almost always 1) with the stored one, so three nights of a door at 03:00 never added up and a watch was a fourteen-day mute. A withheld filed row was surfaced an hour later as `UNJUDGED`, which was false.

## The never-ignore floors were unreachable, and are now real

- No producer set `safety`/`protected` and `make` refused the keys, so the tests passed on dicts `make` would not build.

## A case's kind is not its store

- Routing endings by kind sent the Resident's questions and opportunities to the hypothesis and proposal hooks with a finding's ts.

## Not every producer is a rule

- "Stop raising these" on a Resident card deleted every open Resident row (safety included) and muted nothing anything read.

## A Resident case is filed under the entity it is about

- Cases were stored with `entity_id: ""`, so "the front lock has been offline since 10:20" stayed on the list a day after the lock read locked, while the brief said it was back.
- #441: a "four Wi-Fi devices are not reachable" card from the overnight check and an "offline since Thursday" card stayed open a day after every device had reported again, because the sweep read only the Resident's. Tests: `tests/test_resident_case_entity.py`, `tests/test_network_findings_one_card.py`.

## Every Resident verdict is written down

- The join keyed a row by id alone in the first cut, which folded four distinct cards into two on a fast test.
- Counting verdicts rather than things is how "4 of 4" becomes "8 of 8".

## The graded log is read, graded and folded once per change

- `tests/test_outcomes_graded_once.py`. Every look asked for the graded log (`server._graded_items`) and every ask re-read the whole of `resident-verdicts.jsonl`, parsed every line, graded every row and folded every item — and every look appends to it, so a cache keyed on the file alone would never hit: `test_resident_two_days` spent ~48 s alone (59 s under xdist, against the 60 s timeout) doing it 400 times over a log growing to 3,400 rows.

## A row set aside as ANOTHER open card's problem is agreement

- `tests/test_outcomes_already_covered.py`. The nightly reflect told the look to be louder about two network checks and a light, "3 of 3 it passed over turned out to matter" — and every one of those rows had been passed over *because* an open connectivity card already carried it, and was answered "rolled into that card".

## The model only says what a pattern MEANS

- `model_plan.JOBS["reflect"]` had no caller before this.
- The test for the first guardrail put the judgement in the prompt, had the model obey it, and found `act` on record.

## A subject the household keeps overruling is floored

- `tests/test_resident_passed_over.py`. A house's outcome stream counted a freezer compressor's switch passed over twenty times as "switched off as designed" while its probe read 47 °F, and two Bluetooth sensors passed over as "only a signal-strength note" although an auto-lock reads one — every call overruled. The record existed (the worked examples even said `[wrong call]`) and the louder judgement needed a nightly model run, the `learning` option and room in the retrieval.

## brAIn's own reports stand down on their record

- #577, #824, #853. The Resident was marked Wrong 6 of 9 times and filed as before: `rule_record` holds a RULE three Wrongs deep, but `quietable` refuses `resident` (it is not a rule, and stays unmutable), so the scorecard's `resident` row reached nothing but the fault list; and a Wrong about one entity folded the next case about it away only in `add_many`, after the investigation was paid for and with no line on the trail.

## A first look is captured as its INPUTS

- A capture of the finished prompt could only replay this release's prompt.

## A reading may ADD safety and never remove it

- Before `important_ids`, only ids typed into memory.md counted, so a water main nobody had written about was filtered as noise.

## A sensor the owner called broken is not evidence

- Tests: `tests/test_resident_known_faulty.py`, `tests/test_look_reason_dashboard.py`.
- One helper (#701, #692, `tests/test_broken_sensor_answer.py`): two attempts failed review. A drop in `triage.gate` skipped the floor `answered_off` keeps (a leak row or a "front door unlocked" row about an entity answered "no longer used" vanished with no trail entry), and new "ignore this sensor" wording read "Ignore this sensor. For a week." as broken for good. The first look's override is after the reply rather than out of the batch because the look reading the household's words was held by `test_resident_ignore_chips`.
- The overnight check (#788, `tests/test_broken_sensor_overnight.py`): the Resident stood down and the overnight pass went on filing "the pump pressure sensor reads below zero" from the sensor the owner called broken.

## A first look that runs out of time

- #721, `tests/test_resident_look_timeout.py`. A look stopped at `resident.TIMEOUT_S` already handed its batch back; what was missing was any sign of it.

## "Cosmetic" and "already known" are words

- #790, `tests/test_look_verdict_holds.py`. A look concluding a row is cosmetic, long-standing or already on To Do left it on the list; two earlier fixes read that out of the reason's prose and held a wet leak sensor ("not log noise: the leak sensor has read wet for 20 minutes") and a smoke alarm ("can wait, but … needs replacing today").
- The allow-list: three reviews running found a real problem a deny-list let these two words hold — a freezer reading, a water row no class names, a sensor of unknown kind, then a siren, a camera, a sump-pump switch, a row with no entity and a sump level sensor of class `distance`.
