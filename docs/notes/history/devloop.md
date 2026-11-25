# brAIn: the development loop: history moved out of docs/notes/devloop.md

What each rule in `docs/notes/devloop.md` cost to learn. None of it is needed to follow the rules; it is here for the next person who wonders why a gate, a bound or a redaction rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite; the rules they enforced still hold.

## Switches and filing

- **The autopilot switch's old label.** It was "Development mode: brAIn works on itself", which read as self-improvement and is the opposite of what it does.
- **The held row's old wording.** A `ready` row said "will be sent", which read as brAIn stalling, when Send sends at once and a row still `ready` had been held.
- **The daily issue cap.** The owner called the 10-a-day default, the 50 ceiling and 5 per pass "silly — if there is an issue to send, just send it" (#797). That is why 0 became the default, `MAX_SENDS_PER_PASS` went and autopilot stopped raising the cap.
- **Rolling issues through `fingerprint`.** Folding digits filed every release's scorecard into the first one and never rewrote a body whose only change was a count.
- **A look that was dropped.** Both branches of `server._devloop_stream` (no Claude credential, or the day's cap spent between the press and the run) returned `skipped` before the fallback, so the press answered 202, nothing was filed and the status line said nothing.
- **The pruned queue entry.** The queue prunes the oldest sent entry first, which is exactly a fixed rule whose pre-fix Wrongs the scorecard still holds; the next pass that read its row made a new entry, the marker search (only the newest 300 issues) missed the old issue, and the same fixed report was filed again as a new issue night after night (#1153–#1156, #1197). A rebuilt entry left without its close-time state took a pre-fix row as its last sighting and could never read a new one as back. An open second issue used to erase the first one's verdict.
- **The invalid escape.** A house report's `brain-devloop` block failed the cloud's parse ("Invalid \escape") after an add-on log excerpt carrying terminal colour codes (shown as `^[[33m`) went into it. In Python the block was already `json.dumps` output and parsed in every case driven here, so where the invalid escape came in is not proven; the reader's side is the cloud's.

## Verdicts and follow-ups

- **One wrong decline silenced a report for good.** Before `stand_down_days`, a noise verdict silenced the report on the house for ever. `_refresh_verdicts` restamped `at` every hour, which would have made 90 days never end; a stand-down recorded before the fix had no date.
- **"Back again" after every update.** Every brAIn update reopened every closed report at once with "Back again", because the house reopened on any version change and every update re-stamps every row a window still holds — a 24-hour journal, an all-time scorecard, a restart owed after each install — so each run of the cloud loop spent its first hour re-closing forty issues that carried no news, and the open list was never empty.
- **Morph's rolling Screens issue.** Filing Morph's Screens issue closed brAIn's, before `_rolling_owner` kept a rolling issue to its own add-on.
- **Morph's count.** Morph published `times`, which `IMPACT_KEYS` dropped, so its issue counted passes.
- **The body written once.** A still-happening report's body was written once, and its live count was read off ten-day-old text.
- **The scorecard's pre-fix Wrongs.** Because the scorecard is all-time, a fixed rule kept its pre-fix Wrongs for ever until the producer row was limited to `SCORE_RECENT_S`.

## The closed loop

Four seams were open when the closed-loop work began:

- **The fix version.** The house read nothing off "Fixed in brAIn x.y.z", so a fault still seen on a release OLDER than the fix reopened the issue a day after any unrelated update, and a house with auto-update off was read as a house where every fix held. The first cut compared with the entry's own version and said "Held … on 2.17.0" about a fix in 2.17.2.
- **Answering for the owner.** The settle pass once answered Yes for brAIn (*brAIn checked on brAIn V*) on a report whose stream clears and had not been seen since the install. Admitting clearing streams to the ask would have put a question about every fixed fault on Today for an answer its issue already carries (**Held**), so that branch, `owner_answer`'s `by`, its comment and the install record only it read (`installed_at`) were deleted, and the tests that seeded a fault question the ask pass never files were turned into tests that none is asked and none is answered for the owner.
- **Evidence, the Resident's judgement and the panel's 500s** each had no route to the cloud, which is why the log excerpt, the `outcomes` stream and `crash_middleware` were added together.

## Fix questions

- **The cut card.** A card ended "…(Fix: Findings never" over a detail starting "say who acts:": the text ran past the store's 200-character cap (`findings_store.MAX_TEXT`) and `split_overlong` moved the tail into the detail.
- **Questions about fixes that were not live.** A house had the add-on on a new release while Home Assistant, not yet restarted, still ran the integration from three releases before — and Today held five "Is this fixed now?" cards about fixes that were not live, several about the same part of brAIn (#535).
- **Questions with no context.** "Is this fixed now?" cards asked the owner with nothing saying whether brAIn had looked, and questions carried over from earlier updates sat on Today with no context (#605).

## Redaction and aliases

- **Ordinary words rewritten.** Households name things "Screen", "Inside", "Box", and the whole-word rule rewrote the prose of every report: "the message box sits under the home indicator inside HA's frame; full-screen is off" arrived as "the message Binary sensor 251 sits under the home indicator Light 56 HA's frame; full-Switch 335 is off", and the fixer misread it.
- **The first fix was a privacy regression.** It exempted any one-word name written lower case, and review found that a light called "Dexter" in "dexter's lamp is stuck", an area "Emma", rooms "Nursery", "Sauna", "Office" and any non-Latin name typed lower case left the house, in exactly the fields people and logs write in lower case. Hence the word list (2,942 words when built) and "privacy decides first". The typed-look body once quoted only its first line with `>`.
- **First names in Morph's pictures.** An audit of Morph's pictures found two people tiles as "Person 1"/"Person 2" and two children's first names in plain text, in the tiles, in the brief ("…and <name>'s door is open") and under Doors: the map held only whole friendly names, persons and areas, and those tiles were named by dashboard.yaml (`name:` on a sleep-sensor card) and by parts of names ("<name>'s room", "<name> door").
- **The vendor word aliased.** A house whose sensors were named "BRUH <something>" taught the map the vendor word, and the canary for BRUH Browser arrived as "[canary] Name 13-browser" with `product: "Name 13-browser"`, so the cloud could not match it to the add-on a merged PR bumped and a regression could never be reverted; sibling titles ("[BRUH Minecraft · Log]") were mangled the same way.

## Siblings and the chat's reports

- **No route from breaking to a fix.** GardenRX, BRUH Bambu Studio, BRUH Print, BRight, BRUH Minecraft, BRUH Cooking and BRUH Task Manager had no route from breaking to a fix but the owner opening a cloud session, while brAIn could already read each one's state and logs.
- **The catalog.** BRUH Task Manager was guarded in `.claude/devloop.json` and was nowhere a report could be filed for it.
- **Morph after it left the catalog.** `report_bug(addon="Morph")` was refused by the route with a 400, and the look reply's schema refused a reply naming Morph.
- **`fixed_in` across products.** Comparing a "Fixed in Morph 1.0.5" against brAIn's 3.x read every Morph fix as installed on close, and the same would have been true of every sibling.
- **The sliced report.** A chat that put the owner's words and its diagnosis into `what` filed a 300-character fragment ending mid-word and nothing else, and the look stream cut the owner's words at 500 the same way.
- **Morph's code reports.** A learning pass's `code_reports` used to wait as "Send it as an issue?" suggestions.

## The walkthrough

- **Morph only.** The walkthrough was chartered for Morph only, so brAIn's own panels were never looked at by a model and the owner was the only detector of UI problems; the owner asked for it to cover every app brAIn can reach, each behind its own switch ("I don't want to burn tokens always improving an app I'm not using"). That is the per-app switch set and why autopilot leaves it alone.

## Screens and the harness

- **Other add-ons' pictures refused.** `FILE_PATH_RE` admitted only `screens/brain-…`, so every other add-on's pictures were refused and its Screens issue never filed.
- **Charts with no lines.** A picture taken at once after a room unfolded had charts with no lines. History, statistics and logbook reads were always on `READ_COMMANDS`; the bug was the moment of the picture.
- **A mouse tap on a touch device.** A card built on Home Assistant's action handler listens to touch alone once the device has touch, so a mouse tap or hold never reached it and `press: open|tap` left it folded.
- **The unbounded harness socket.** The page stopped waiting at its own budget, but `h_harness_ws` still awaited Core with no bound. In the suite that made `test_a_question_that_never_comes_back_does_not_hold_the_picture` take ~56 s against the 60 s per-test timeout. Under CI load it went over, and `timeout_method = thread` ends the whole xdist worker ("node down: Not properly terminated"), after which xdist hung the job until it was cancelled — on `main` and every PR.
- **The WebSocket handshake.** The real-browser test proved that Chromium's blocked-URL list does not stop a WebSocket handshake, which is why `WebSocket` is replaced in every frame.
- **One card.** Morph was one screen, scrolled to the top and cut at `MAX_HEIGHT` from there, so a card further down could never be in the picture and none could be opened.
- **The overview tile not found.** Asked for the assistant's overview tile (`c_ov_vesper`), `screenshot_panel` said "no card or section called": the harness served Morph's shipped modules only, never the house's copies in use, drew `<morph-panel>` outside the shell, and a room the salience list folded to a line (`roomStateOf` → `idle`, which a harness with no presence and nothing on makes of most rooms) draws no tiles, so the tile was not in the page and its section matched only its title line. Asked with no screen, the tool listed brAIn's own and the chat concluded cards could not be photographed.
- **Real dashboards never seen.** The harness could draw Morph's classic panel and the BRUH cards, never a real dashboard, because the browser here could not sign in to HA's frontend, so brAIn answered about dashboards it had not seen.
- **The phone's sidebar** (#836). A picture of brAIn's page alone could never show the header and scroll faults a house kept reporting from its iPhone. A first version of `after` took only the first visible field on the page, found none on Ask's classic face, the add-on's default, and photographed an unfocused Ask. Against 5.1.28's page the layout check reports the first row at 11px inside a 59px strip.
- **The opened card cut at the top** (#885). A picture of a card held open started partway down it on a phone (the card was fine on a real screen). The harness scrolled the card to the window's very top, where Morph's sticky room line (68px at 390) lay over the card's title and first row, and the same scroll put the press under that bar too; and it measured the card before Morph's glide to an opened card had finished, so at 1200 the picture held 90px of the card above. The first scroll found no bar, put the card under the one it then made, and the press (taken from that rect) landed on the bar: the card stayed shut and was photographed shut at 182px.
- **"Not captured" read as broken.** A covered picture saying "not captured" alone was filed as eight broken camera tiles (#1125); an opened card that hosts a grid was filed as "shows only a placeholder" (#1128).
- **Hidden controls measured.** Six Restore buttons folded under one day in BRUH Minecraft's Backups were filed as overlapping each other (#1181).
- **Mixed colours read as numbers** (#820). Chromium answers a `color-mix()` colour as `oklab(0.85 0.02 0.09)`, and the check read those numbers as 0–255, so every mixed colour was near black: Morph's group labels (People, Comfort…) measured 1.52:1 on its medium background and 1.07:1 on dark while they were above 7:1.
- **The silent Screens stream.** The Screens stream last filed a panel audit on brAIn 3.0.1 and nothing for 4.x or 5.x, and nobody could tell: a pass with no Chromium, unreadable states, a capture that raised or no redacted picture returned `skipped` or `error` to the press that asked and filed nothing, so a scheduled failure was a silence that read as a clean result.
- **Releases never photographed.** A weekly schedule against several releases a day meant most releases were never photographed.
- **The pass thrown away** (#890). On a house with about fifteen of brAIn's screens, a couple of dozen dashboard tabs, Morph and thirty add-on screens the pass hit its fixed fifteen minutes, `wait_for` threw the whole capture away, and it said "the screens could not be captured: " with nothing after the colon — a timeout's text is empty, and `f"{exc or type(exc).__name__}"` never falls back because an exception is always truthy.
