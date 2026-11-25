# brAIn: measurements: history moved out of docs/notes/measurements.md

What each rule in `docs/notes/measurements.md` cost to learn. None of it is needed to follow the rules; it is here for the next person who wonders why a floor or a gate exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold.

## Baselines, history and the nightly pass

- **The baselines run button.** `POST /api/baselines/run` had existed since the loop did and had **no caller in the panel, the CLI or the integration** — the "a button that exists only in prose is a button nobody can press" rule with the prose missing too. It is why the doors-and-windows fix took a day to become visible and could not be verified at all: the store went on reading `0 of 18` because the pass had not come round, which is indistinguishable from the fix not working. Awaiting the pass in the route would have been BRight's `_claude_job` failure with a different clock.
- **`end_time` has no default, and the argument that is NOT there cost two features.** `closures.fetch_history` asked for 28 days without `end_time` and got a single day four weeks back, outside the recorder's 10-day retention on any default install: `[]` for every door in the house, every night. And `[]` is a list, so the fetch counted the batch as answered and returned `{}` — "this house's history holds nothing for these ids" rather than "I could not look" — so `build` wrote an empty store with no error, `snapshot` marked the key unavailable, and **`evening.left_open` was skipped for the life of the feature** while diagnostics read `measured: 0, asked: 18` and nothing anywhere said why. `get_history` omitted it too, which is the same bug where it is much harder to see: every insight card on the snapshot path got one day of history from `history_days` ago and presented it as current. `baselines`/`appliances`/`thermal` were untouched because they go over the WebSocket to `recorder/statistics_during_period`, which has no one-day default — the same omission with the opposite consequence, which is why one nightly pass measured 258 of 299 and 0 of 18 in the same breath. The shipped closures test used a fake that accepted `params` and discarded them, which is why it could not see the defect.
- **The cap spent before eligibility.** **The bug.** `candidates` sorted every `state_class` entity and kept 400 before asking whether a baseline could be built or read; the slots went alphabetically to rows that could never be measured, and the cut was invisible.
- **The Timeline window select.** On a phone it was a full-width row of its own above a label saying "Last 24 hours", one fact twice.

## Drifts

- **A drift is invisible to the band, measured.** On a real-shaped month the freezer example is **2.3 spreads to the band and 16 to the trend**, and the band needs six, so it is not badly tuned, it *cannot* see this however far it goes. A line through a `total_increasing` meter found a slope every time (measured at 11 spreads). The `state_class` gate also caught `base.unusual` being quiet on those meters **by accident rather than on purpose**.
- **Outside causes.** `forecast.decline` was 0 confirmed against 3 Wrong: the grid's carbon intensity, a car's charge level and soil drying in a dry spell — real drifts about things the house does not control.
- **The season.** A month of steady drift in November is the cellar cooling, and `forecast.decline` was marked Wrong for saying so; that is what brought in last year's weeks.
- **Two least-squares fits.** `checks/forecasts.py` had its own copy for the battery runway before `baselines.least_squares` became the one fit.

## Appliances and chores

- **The job-status path.** A 3D printer publishing a print status (or a washer an operation state) and no power sensor was invisible to a check that reads power, on the one house that asked for exactly this.
- **"Still full".** "The washing machine has finished and is still full" was marked Wrong every time, because a plug sees a machine stop and nothing run since, never what is inside it.
- **The busy level.** The 95th percentile of ten days of five-minute buckets is the idle level for anything that ran under ~145 buckets. Measured: nothing up to eight 90-minute cycles at 1 W / 500 W got a profile, which is an ordinary washer.
- **Unloaded.** The person pressing something is what 1.38's To-do list and notification buttons were added for.

## The thermal model

- **The dew point reference.** A weather integration publishes several derived temperatures with **no area**, which is exactly the branch `pick_outdoor` fell through to when nothing was named "outside". So the reference was settled by whichever sorted first, and `dewpoint` sorts before `temperature`: a real house had every `k` in it measured against `sensor.astroweather_2m_dewpoint`, a number that tracks humidity and sits well above the night air, and the visible cost was `climate.window` reporting an irrigation pump manifold as a room with a window open.
- **The sun, measured.** An all-day fit on a sunny room is refused outright while the night fit lands on the physics.
- **`climate.window`'s guard test.** The test that pins the below-the-reference refusal needs an outdoor reference **above `FREEZE_FLOOR_C`** or `climate.freeze` claims the room first and the case passes for somebody else's reason — which is exactly what the first cut of that test did, and the mutation is what caught it. `test_the_allowance_is_read_where_the_fall_STARTED` was added because nothing else pinned where the allowance is read.
- **The coil probe.** One area's only "room" was a heat pump's coil probe that jumps about 25 °C at the same hour every morning, and `climate.heat_loss` filed it as a room losing heat fast.
- **The unheated room.** `climate.heat_loss` ranked every room with a thermometer against the rest, so an uninsulated space with no thermostat was the leakiest room of every house that had one, and the household marked it Wrong ("expected, mostly uninsulated").
- **The outdoor ranking.** `pick_outdoor` took the alphabetically first name with any outdoor word, whatever its area. "Ambient" and "garden" counted, so a heat pump's coil, a pool and an indoor ambient reading could each become the reference every room's `k` is fitted against.

## Rhythm and habits

- **The night filed under the wrong day.** **The bug.** `record` filed each action under its calendar date. Anything after midnight became the next date's *first* action and could never be a settle. A house up until 00:40 was measured waking at 00:40 and settling at 22:00: inverted, not imprecise. **Who inherited it.** `brief.due`, `signals.night_window`, `healing`'s settle+60, `evening.left_open` and `climate.preheat` all inherited it.
- **Three copies of the habits arithmetic.** `routines.py`, `override_ledger.py` and `manual_ledger.py` each had a private copy, and the three had already drifted in what counted as a weekday.
- **The borrow closed an import ring, and CodeQL was the one that saw it**: `habits` read the circular median off `rhythm`, `rhythm` reads `house` for its progress sentence, `house` reads `routines` for the same, and `routines` delegates to `habits`; a ring is not a crash but a module whose answer depends on which neighbour was imported first, which nobody reproduces on purpose. `tests/test_habits.py` ran the old arithmetic beside the new, grepped that the old copies were gone, and imported each of the eight modules alone in its own interpreter.

## Measurement tools

- **Guessed payload keys.** `tests/test_measurement_tools.py` drove each tool with `_panel_get` answering the shape its route really sends (copied off `_thermal_payload`, `_appliance_detail`, `_closure_rows`, `_facts_payload`) because a payload key guessed in the tool and guessed the same way in its test is the `_error_code` envelope failure again — and the first cut had two of them wrong.

## Activity and episodes

- **The Activity tab's measuring script.** `tests/manual/measure-activity.mjs` drives the real `renderActivity` behind a stubbed fetch (a copy of the renderer in the test would only ever agree with itself) and fails on a cause hidden rather than moved, a row repeating "no cause recorded" (14,000 rows each saying it was the list), and an evidence block shown over a window with nothing in it.
- **The sixth tab needed no new breakpoint** — `measure-topbar` reports all 96 cases at the same two shapes — but it found two tests measuring the wrong thing: that script asserted *five* tab labels by number, which says nothing about whether a sixth kept its name, and `test_brain_addon`'s band scan ran to the end of the stylesheet, so it was really testing where the last `@media` in the file happened to sit.
- **House › What happened, before.** The mode alone was a bold heading over nothing; the cause chips were a row that scrolled sideways on a phone.
- **Episodes.** The Activity tab was reported as *"the activity tab is really worthless… basically zero utility in its current form"*: one row per state change, newest first, filtered by who did it, is Home Assistant's own logbook with a column added — and on a real house it is hundreds of rows an hour of a sensor reporting a number. Without the active-episode rule an `off` three hours later was filed as a fresh episode of *off* and the row read `Lounge TV, off, 0 seconds`; the test demonstrated the gap-only arithmetic on the same fixture before asserting the fix. A renderer reading a momentary sensor's span as a duration reported a hall sensor as *on for 83 minutes*. `measure-activity.mjs` found that one `nowrap` cause made the whole implicit `auto` column 1.45px wider than the page.
- **The live state.** "heat_cool for 17 h" about a thermostat unavailable since 11:11 is the reading nothing could correct before `from_live`.
- **The heading (#1303).** The heading was the mode word ("Someone's home") over a sentence from an earlier reading ("Earlier: the house is empty"), and a problem sensor going on and off every twenty minutes was a row a flip at the top of Locks & safety.
- **Restarts (#1121, #1140).** Device returns were left as a row per light. `_mass_changes` joins an "unavailable" burst to a return burst over only half the same devices, so 110 of 113 returning read as all of them. Membership read off the capped `entities` list once left every return past the fortieth device as its own row. `measure-activity`'s /Nobody home/ check predates the empty-house sentence.
- **The empty-house box.** "the house was empty" under "Sam and Alex are home" read as a contradiction.
