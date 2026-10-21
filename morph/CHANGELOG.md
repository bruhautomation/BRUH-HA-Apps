# Changelog

## 1.1.0

### Changed

- **A Tell does the whole thing.** Asking for a card that needs a template sensor, an automation or a helper now gets all of it made, checked and listed so Undo can put it back, instead of the dashboard half and a note saying what you would have to do by hand. A number a card works out from other sensors becomes a template sensor rather than a question. Ask can change the dashboard too. With brAIn's "Let brAIn act without asking" on, both run with the chat's reach. Needs brAIn 3.5.0.

## 1.0.5

### Fixed

- **A custom card no longer shows an error after a redraw, a reload or an update.** A card file that runs a second time on the same page (because its file changed, or because Morph's own code was served again after an update) asked the browser to define its element again, which the browser refuses; Morph now skips that second define, so the card already on the page goes on drawing, and offers a reload when there is a newer version to see. A card file that is already loading is not loaded twice. When card files fail for one reason, that is reported once with the reason, not once per card. (#319)

## 1.0.4

### Fixed

- **Morph's own service faults reach the development loop.** An error inside the request loop, the watcher or the tick was logged and nowhere else; each is now a row in Morph's fault ledger with the exception, the line and the traceback, published to brAIn's loop with everything else under *Report Morph's own problems*.

## 1.0.3

### Added

- **Thermostat routines on the climate card.** A climate card's `options.actions` lists up to four scripts, buttons or scenes (a "drop humidity" script, a boost) that sit on the card's face; a running script reads as pressed. A house no longer has to copy Morph's own card code to add one. (#247)
- **A card's deeper view opens with the card.** `options.detail` holds a Lovelace card that is shown only while the card is open, such as a performance chart under a thermostat. (#242)

### Fixed

- **Debug traces are not filed as Morph faults**, and each fault Morph publishes says when it last happened, so brAIn's development loop no longer reports a two-week-old row as still happening. (#261–#264)

## 1.0.2

### Fixed

- **A hosted card draws when Morph is opened before Home Assistant's dashboard code has loaded.** Morph waits briefly for Home Assistant's card helpers and loads them the way Home Assistant's own panels do; a house's own custom card is drawn directly without them. A card that still cannot be drawn says so in plain words instead of showing a script error. (#281)

## 1.0.1

From an audit of a real house against the 3.0 vision.

### Fixed

- **A house armed for bed gets its night page.** `armed_home` is night inside the measured settle-to-wake window, and — until brAIn has measured the house's rhythm — between 7 PM and 9 AM, rather than never. `armed_night` is night at any hour. The house's alarm is the alarm panel on the dashboard, not whichever panel Home Assistant lists first (a camera system's panel was being read instead).
- **A fan named for sleep no longer puts the house into its evening.** A room is asleep when a sleep mode, sleep switch or sleep sensor says so; a switch whose name also names a device (*Sleeping headphones fan*) is a control used at night. A room's sleep sensors are read from its area too, so the ones that are not on the page count. Every room that can sleep being asleep is night.
- **Something urgent no longer rearranges the page under a finger or an open card.** A serious case only skips the 8-second spacing (§4.4); a safety trip or a door opening at night is the one change that goes at once.
- **Occupied rooms no longer jump to the top on every device.** Rooms are ordered by the room score through the bands and keep their place unless they lead or need attention; on a family device an occupied room rises one place.
- **brAIn's cases land in the room they are about.** A room's entities include those inside hosted Lovelace and custom cards, a section with no `area` matches its area by name, and a case is placed by its own subject, then brAIn's area, then the room most of its evidence is in.
- **A card at the top of its room with a "because" line is a row of its own**, not a row of two heights beside plain strips.

### Added

- **Predictions arrive.** A habit's control lifts into Now on a personal device (to the top of its room on a family one) when its window opens, after anything with a reason of its own; it gets a dashed violet dot on Coming up; a prediction that leaves untouched is reported as ignored, and two ignored windows stop it until it is used again.
- **Anchors and scroll compensation** (§4.4): a card used on four of the last seven days keeps its slot in its room, and a rearrangement above where you are scrolled moves the scroll with it.
- `AGENTS.md`: a change to Morph's own code that changes the design's numbers or adds a second Now, a second list of cases or tooltips needs a `(you)` line in `LEARNED.md`; re-merging a paused copy drops what no household rule asked for.

## 1.0.0

Morph becomes brAIn's face (docs/design/morph-vision.md). Needs brAIn 3.0.0.

### Added

- **The page is laid out by what matters now, and says why.** A verdict leads the page, its first clause in the colour of what it means. Up to three cards (two on a phone) are lifted into **Now** — moved, not copied — when something is unusual for this hour, finished, a habit about to happen, or something brAIn is asking about. Each says why in one line (*open at this hour on 1 night in 20*, *you usually do this now*); hold the line for **Keep it here** or **Not this**. Rooms are ranked and quiet ones fold to one line; tap a room's name to open it. Morph reads what is normal from brAIn's measurements (`/config/.brain/morph/feed.json`) and works from the house's state alone without them.
- **Night, away and still forms.** With the alarm armed for the night the page dims to the one thing that is wrong (an unlocked door, an open garage) or *Everything is at rest*; with everyone away it says so; a family tablet left alone settles into a page readable across the room.
- **brAIn's cases, in the room they are about**, with a reply line: answer in your own words and brAIn ends the case the way the words say, or asks back in the card. **Fix**, **Dismiss** and **To Do** are there too. A reply that also asks for a page change (*and add it to the kitchen card*) is carried out as a Tell.
- **To Do**, brAIn's list (the one Home Assistant's To-do app shows), as a section: tap to tick off, slide to snooze a week, hold for Delete.
- **Ask is brAIn's chat.** brAIn reads what is typed: a question is answered under the line and can be continued (one conversation, also in brAIn's Ask tab), a fact or a rule is done, and a change to the dashboard or to Morph is a Tell.
- **Then.** Slide Coming up into the past and every card shows the house at that moment, with what happened as dots behind the line.
- `pin:` on a card (`true`, or `active` for "only while it is on") and `heading: false` on a floor.
- **Settings → This device**: somebody's own screen or the family's, whose habits lead, and **Fold quiet rooms**.
- Keyboard: `/` focuses Ask, arrows move between cards, Enter or Space taps, Shift+Enter holds, Escape folds back.

### Changed

- **Learning suggestions are brAIn's cases**, answered on the page like any other, and the answer comes back to Morph. Morph keeps no list of its own.
- **The page updates in place** (`morph-dom.js`): nothing you are touching is rebuilt, an open detail stays open, and a moved card travels instead of fading.
- Card faces: an action word on every strip (*Lock?*/*Unlock?*, *Open?* on a garage), fans that cannot set a speed show on and off, climate coloured by its mode, list cards in two tones (rose for what needs a look, amber for activity), buttons say when they last ran, media shows its progress, cameras stream when opened.
- History: unavailable stretches are hatched, a day strip ends at midnight with a mark at now, chart labels are text, readings detect their kind, and only temperatures draw a target band.
- Coming up shows a day back, moonrise and moonset, and an all-day event today.

### Removed

- Morph's marks: on a hovered card, an opened card and a section title. Ask is the one door to a Tell outside Edit.
- **What do you want to fix in Morph?** in Settings: say it in Ask, which routes it as a change to Morph.
- Morph's own notes and suggestion cards: brAIn's cases replace them.

### Fixed

- A loaded page whose first `morph/load` failed stayed blank; it retries with backoff and says so.
- Tiles measured their height before fonts settled and could overlap by a pixel; heights are measured with `getBoundingClientRect` and watched.
- An all-day calendar event for today was dropped from Coming up.

## 0.5.10

### Added

- **Update merges every paused change in one press.** When an update pauses several of your changes to Morph's own code, one note offers **Update** (merge your changes into the new version: one request to brAIn and one change you can undo) or **Not now** (keep Morph's own version running; your changes stay paused for later). Where the update rewrote the code a change was in, brAIn asks how to bring them together and merges everything else; only that file stays paused until you pick, and your answer carries the merge on. Settings has **Update all** beside each file's own **Update**, and **Remove my change** in place of "Use Morph's own".
- Every request Morph hands brAIn carries the words the person actually asked (`person_words`), so brAIn can judge a change against those rather than against Morph's whole prompt.
- A card file of your own in `cards/` that will not load is offered back as a suggestion, **Fix the card code …**, instead of being reported as a fault in Morph's code.

### Changed

- **A Tell's request to brAIn follows one procedure**: the picture first, then the request, where the thing lives (the story and Coming up are drawn by Morph's code, not by `dashboard.yaml`), the scope, the household's rules, how to make the change and what to answer. Each rule is said once; the details live in `AGENTS.md`.
- **`AGENTS.md` is complete**: the whole schema (`hidden`, `unit`, `options`, the `lovelace` wrapper and the shorthands), every module of Morph's own code, all eleven design rules, what custom card code has to do, how to check a change and when to ask instead of act. It is split into how Morph works and the Tell answer as reference.
- **`LEARNED.md` says who wrote each line**: `(you)`, `(tell)` or `(learned)`; a line with no mark is yours. A learning pass can no longer drop or reword a line you wrote, adds a new lesson only with two pieces of evidence or a reason you typed, and is shown what an undone change had changed. A reason given for No is evidence for the next pass rather than a lesson written at once, and the list's limit drops the oldest line Morph wrote, never yours.
- The learning pass is shown Morph's card types, and long lists in it are cut by whole items with a count rather than mid-word.
- A suggestion's Do it names the section or card it is about, and says it came from a suggestion; Undo's follow-up, a question's answer and a redo each say where they came from.
- brAIn's answer lists the files it changed apart from the changes in Home Assistant, and Undo hands back only the second list. A fact brAIn files says how sure it is, and may be about a person.
- The Ask bar tells the house's assistant that it cannot change the dashboard, and a command such as "turn on the card table lamp" is no longer taken for a dashboard change.
- A report sent from **What do you want to fix in Morph?** about how Morph looks is marked as one, and a code suggestion sent as an issue carries the evidence for it.

### Fixed

- The part of the dashboard shown to brAIn is cut on a whole line with a note of how much is left, where it used to stop mid-line with nothing said.
- Earlier turns of a conversation showed Morph's own closing sentence as what brAIn had answered; they now show what brAIn said and what Morph read back, apart, and say how many older turns are left out.
- A learning pass that had seen 30 changes or answers stopped noticing new ones; it now runs when there is anything new.
- A lesson from a Tell that failed is no longer written down.
- Making a paused change again no longer asks to send it as an issue a second time.

- brAIn is no longer told that custom cards must be registered in `dashboard.yaml`: Morph loads every file in `cards/` itself.
- A problem Morph sends to brAIn's development loop points at files that exist.

## 0.5.9

### Changed

- **The learning pass runs when there is something to learn.** A pass was keyed on the exact number of uses, so a single tap re-ran it every interval. Uses now count in steps of 25; new answers, changes and unavailable cards still count at once.
- **The pass is told what is already waiting or done**, and leaves out cards nobody touched (the dashboard it is given already lists them), so it spends fewer tokens and stops proposing what is on the list.

### Fixed

- A suggestion reworded from one still open, snoozed or declined is no longer added as a new one, so copies stop taking the open slots.
- The use log is pruned once a day. The pruning existed but was never called, so the file grew for ever and every pass read all of it.

## 0.5.8

### Added

- **Morph's mark on a section's title.** Outside Edit, an admin can press the mark beside a room's title to tell brAIn about that section; a second press closes the box. (reports #236)

### Fixed

- A readings card no longer breaks when a thermostat's history cannot be read; it draws without the target band. (reports #217)
- Custom card code that fails to download once is fetched again before it is reported as a fault. (reports #239, #241)
- A card type added by the house's own copy of `cards.js` is drawn by that copy instead of showing "Configuration error". (reports #240)

## 0.5.7

### Changed

- **Coming up is one short strip you scrub.** It used to be a 12-hour track
  with every event's name written along it, which crowded and cut names
  off. Now a thin line stays still a little left of centre and the next day
  slides behind it: drag or swipe it, scroll sideways on a trackpad, or use
  the arrow keys. Whatever is at the line is read out beside it, when on the
  left and what on the right, with the full name. Dots swell as they come
  near the line; let go mid-swipe and it settles on the nearest event; tap a
  dot to jump to it; tap the name to show that device's card. **Now** brings
  it back, and left alone it drifts back by itself after a minute.
- **Coming up shows how long things take.** A timer that knows its length
  and a calendar event with an end are bars, filled up to now while they
  run, and night is a faint band. It looks a day ahead instead of 12 hours,
  and also reads date-and-time helpers and "next" timestamp sensors.

## 0.5.6

### Changed

- **Morph paints at once while it opens.** Home Assistant used to show a
  blank page until every one of Morph's modules had downloaded. Now the
  dashboard's outline appears immediately, in Morph's own colours, and the
  dashboard replaces it as soon as it has loaded.
- **Opening Morph again is fast.** Morph's code is now cached by the browser
  under a name for exactly that version of the code, so later visits download
  nothing. Every module also starts downloading at once rather than one
  level of imports at a time. A change to Morph's code (an update, or brAIn
  changing your copy) gets a new name, so a stale file is never served.

### Added

- **Morph says when a reload is needed.** A bar at the top of the dashboard
  appears when what is on screen is no longer what Home Assistant would
  serve. It reads *Morph's code has changed since this page opened* or
  *Morph x.y.z is ready*, with a **Reload** button. When the add-on is newer
  than the integration Home Assistant has loaded, it asks you to restart
  Home Assistant, because a reload alone would not finish the update.

## 0.5.5

### Changed

- **"Make it again" asks when an update rewrote the code your change was
  in.** brAIn used to pick a merge on its own and put your change back in
  use. Now, when there is more than one reasonable way to bring the two
  together, it does not guess: the note asks what the update did and offers
  one button per way to resolve it, plus **Use Morph's own**. Your change
  stays paused and Morph's own keeps running until you pick, and the button
  you press is the merge brAIn makes.

## 0.5.4

### Added

- **A Tell's result says where every change landed.** One line each for the
  dashboard, Home Assistant, Morph's own code, brAIn's memory and GitHub,
  shown whether or not anything happened there. A Home Assistant change is
  listed with the note that Undo asks brAIn to put it back, and GitHub reads
  *Nothing sent* unless you say yes to an issue. Before you send, the box
  says what a request may touch.
- **brAIn asks when the choice is yours.** A card that works a number out
  from other sensors has no history, because Home Assistant records only
  entities. brAIn now builds the card with the number worked out in it and
  asks whether to keep it that way or make a Home Assistant template sensor
  so it is recorded. The answers are buttons, the one that changes Home
  Assistant says so, and pressing it is your next request.
- **Details and Device page on an opened card.** Details opens Home
  Assistant's own dialog for the card's entity (or the row you tapped);
  Device page goes to its device in Home Assistant's settings.

### Fixed

- **An update to any of Morph's modules pauses your changes to Morph's code.**
  A copy was paused only when its own file changed, so a changed
  `morph-panel.js` kept running beside an updated `engine.js` it imports.
  The note names the modules that moved, and **Make it again** asks brAIn to
  check the copy still fits them. A redo brAIn answered puts the copy back in
  use whether or not it had to edit it, and **Undo** pauses it again.

## 0.5.3

### Fixed

- **"Make it again" shows it is working from the moment you press it.** 0.5.2
  wrote "Handing it to brAIn…" onto the button itself. Morph redraws on every
  state change in the house, so that text was gone at once, and the button
  read as doing nothing until Morph's service answered. The press is now
  remembered by the panel: the note shows "Handing it to brAIn…" with a timer
  until brAIn's box opens. If brAIn cannot start, the note says why and offers
  **Try again**, instead of a toast that vanished after nine seconds.

### Added

- **Settings says which Morph is running.** When Home Assistant is still
  running an older Morph integration than the add-on, it says to restart Home
  Assistant to finish the update.

## 0.5.2

### Fixed

- **"Make it again" on a paused change now shows brAIn at work.** The press
  started brAIn, but the only sign was a line in the header, the note stayed
  exactly as it was, and the result was never shown. It now opens brAIn's box
  inside the note, with the steps as brAIn takes them, then the result with
  **Reload to see it** and **Undo**. The note stays until you close the box,
  and a second press shows the same request instead of starting another.
- **A change made again is a real merge.** Morph now keeps its own file as it
  was when your change was made (`/config/morph/frontend/.base/`, committed with
  the change). brAIn is given all three versions: that original, your copy and
  the new release. It also gets the commits that describe the change. A change
  made before 0.5.2 has no kept original, so brAIn is told to start from the new
  file and never copy the old one over it.
- **What a request teaches brAIn about the house is saved again.** brAIn's
  action gate refuses `remember_fact` in a request from Morph, because that is
  a task run and nobody asked to remember anything. Facts now come back in the
  answer and Morph queues them in brAIn's memory inbox, where the consolidator
  decides what to keep. The request's steps say how many were queued.

## 0.5.1

### Fixed

- **Asking for a dashboard change outside Edit now changes the dashboard.**
  The Ask bar sent everything to the house's assistant, which has no way to
  edit Morph's files and could still answer that it was making the change.
  Words that ask to add, remove, hide, move, rename or bring back a card,
  section, the greeting, Coming up or the layout now go to brAIn as a change,
  exactly as they do in Edit. Every answer to an ordinary question also offers
  **Change the dashboard instead**.
- With brAIn 2.18.29, brAIn can rewrite dashboard.yaml when `protected_entities`
  is set. Before, every rewrite of a dashboard that showed a protected lock
  was refused.

### Changed

- **Morph's mark shows in the top-right corner of a card while you hover it**
  (on a computer). Press it to tell brAIn what to change about that card,
  without Edit. On a phone it is among an opened card's options, as before.


### Added

- **A new mark for Morph.** A tile with three square corners and one rounded
  all the way into the arc of a circle, with a dot at that circle's centre — a
  card becoming something else in place. It is Morph's icon in the add-on
  store, in the sidebar's integration page and beside MORPH in the bar.
- **Change a card without going through Edit.** An opened card carries a light
  version of the mark; press it and the Tell box opens in the card. Say what
  should change and Send. Cancel goes back to the opened card.
- **Settings → Improving Morph itself → What do you want to fix in Morph?**
  Type what is wrong, tick *It is about how Morph looks* if it is, and Send.
  Your words go as they are to brAIn's development loop, which files them in
  your private reports repository so Morph's code gets fixed. What you sent is
  listed, with **Take back** until brAIn picks it up.
- `greeting: false` in dashboard.yaml hides "Good evening." at the top.

### Fixed

- **A Tell no longer says it changed the dashboard when it did not.** When
  brAIn finishes, Morph reads the dashboard back and says what is different
  on screen, worked out from the file rather than from brAIn's words (*On the
  dashboard now: The greeting is hidden.*). If nothing changed it says
  *Nothing on the dashboard changed* and quotes what brAIn said. If brAIn left
  dashboard.yaml unreadable it says *Not applied*, and Undo puts the file
  back. The dashboard is republished the moment brAIn finishes, the open page
  reloads it, and a page that has not caught up offers **Refresh**.
- A Tell's Undo no longer sends brAIn to put back a Home Assistant change when
  the only thing changed was dashboard.yaml.
- Leaving Edit no longer reports "Sections overlap at rest": the "Add section"
  places left behind invisible markers that were measured against the rooms.
- A custom card file that changes no longer reports *failed to load* (a page
  can define a card only once). Morph offers **Reload** instead, and
  AGENTS.md's example card guards its `define`.

## 0.4.0

### Added

- **Morph can change itself.** Ask in Edit for a switch in the header, or for a
  built-in card that does something new, and brAIn changes Morph's own code.
  It no longer answers that the header is out of reach.
  - brAIn copies the module from Morph's own panel into
    `/config/morph/frontend/` and edits the copy, and Morph serves your copy
    in place of its own. It is one change in History, and Undo puts Morph's
    own back.
  - The Tell box then offers **Reload to see it**, and asks **Would you like
    to open an issue to update Morph's code?** The change goes with the issue
    as a patch, so everybody can have it.
  - A copy that does not load is not a blank page: Morph runs its own copy for
    that page load and says what went wrong.
  - If an update changes a file you changed, your change is paused (Morph's
    own runs) until brAIn makes it again on the new file. A note says so, with
    **Make it again** and **Use Morph's own**.
  - **Settings → Improving Morph itself** lists every change, in use or
    paused.
- A suggestion to change Morph itself now offers **Do it** (brAIn makes the
  change here) as well as **Send as issue**.

## 0.3.0

### Changed

- **Morph looks like its design again.** Several things had drifted from the
  prototype in the move to Home Assistant, and are back:
  - A strip's status line is quiet text, and its colour lives in the fill and
    the icon. A light says its level and its colour (*40% · Warm*), a group
    says how many are on (*All 6 · 35%*, *2 of 4 · mixed*), a fan says how
    fast (*Medium · 40%*).
  - Fills run strong at the left and fade toward the thumb, and a light's
    strip is no longer tinted behind the fill.
  - A light group is twice the width of a strip, and opens downward.
  - Closed blinds are plain. The slats are drawn only over the part that is
    open.
  - The bulb, group, fan and blinds icons are the prototype's. A bulb's rays
    show only while it is on.
  - A camera is a title, a line of state and a picture with a LIVE mark.
  - brAIn's notes and Morph's suggestions come after a room's tiles. They read
    as a sentence with a row of words under it, and the yes is first, in ink.
  - A room's line says whether it is asleep (and since when), how warm it is
    and whether anyone is there. What is on was already on its tiles.
  - A floor's line says what the thermostat is doing (*73.2° · cooling to
    72°*) and which rooms are asleep.
  - Coming up spans the whole width, clear of the Now marker.
  - The Ask suggestions show only while you are asking.
  - The overlay chart is the prototype's:
    - beside the plot, a column of labels that follow the line ends (or your
      finger) and pick a line out;
    - under the lines, the thermostats' target through the day as a band, and
      when the system ran (*Cooling · 4 h 12 m*);
    - then a time axis, and the extremes on their own line with sparklines.
- **New dashboards group fans and blinds under "Comfort"**, after the lights.
- On a phone, a strip's name has a little more room before it is cut off.
## 0.2.1

### Fixed

- **What you use is recorded again.** Home Assistant takes a hidden panel off the page and later puts the same one back, and Morph stopped sending what you tapped after the first time that happened. A send that failed also threw its taps away. Morph now restarts when it comes back, sends what it has when you switch away, and keeps taps whose send failed until the next one. Buttons and light-group members now count towards their card.
- **Two cards in one room no longer get the same name.** When shortening would make two names the same (two speakers both "Mini"), Morph keeps their full names, and adds a number when even those match.
- **Removing the room name takes the separator with it.** "Kitchen - Bread Stretch" in the Kitchen shows as "Bread Stretch", not "- Bread Stretch". A name that only starts with the room's letters ("Kitchenette Lamp") is left whole.

## 0.2.0

### Added

- **brAIn looks before it changes anything.** Holding a card, a section or
  a floor in Edit takes a picture of it on the spot, shown in the Tell box
  as *What brAIn will see*. brAIn is told to read that picture first, so
  "this is cut off" means what is on your screen rather than what the YAML
  says. When a picture cannot be taken the box says why and brAIn gets the
  card's text instead.
- **You can see brAIn working.** Its own steps (looking at the picture,
  reading `dashboard.yaml`, checking an entity, editing a file) appear in
  the box as it takes them, with how long it has been at it. Closing the
  box no longer hides the work: a strip at the top of the dashboard says
  what brAIn is doing, with **Show**. Needs brAIn 2.18.27, which reports
  those steps.
- **The Tell box is a conversation.** The answer shows what brAIn saw and
  the card before and after the change; **Tell it more** keeps the earlier
  turns above, photographs the card again as it looks now, and continues.
- **"Would you like to send this as an issue?"** When a request needs
  Morph's own code changed (a built-in card type that cannot do it), brAIn
  says so and the box asks. Nothing is filed until somebody presses
  **Send as issue**.

### Changed

- **A Tell changes the dashboard, not the house.** brAIn edits
  `/config/morph` and changes Home Assistant itself (entity ids, names,
  automations, helpers) only when the request asks for that in words. When
  a request would need a house change nobody asked for, it does the
  dashboard part and says what would have to change. Facts about the house
  it learns along the way go to brAIn's memory, not to Morph's lessons.
- **The learning loop is about the dashboard only.** A pass no longer
  suggests changes to Home Assistant, and its lessons are rules about the
  dashboard. A problem it thinks needs Morph's code changed is a **Morph
  needs a fix** note with **Send as issue**, not a report filed on the
  model's say-so.
- **Only Morph's faults are reported as Morph's.** A Tell or learning pass
  that failed because brAIn was slow, signed out or paused is no longer
  filed as a fault in Morph's code; an answer Morph could not read still is.

### Fixed

- The learning pass was told to "read AGENTS.md" but runs with no file
  access; the design rules are now in its prompt.
- A learning pass that failed recorded the evidence as read, so every later
  scheduled pass skipped as "nothing new" until the dashboard was used
  again. Only a pass that answered records it now.
- On a phone, a message in the top bar while editing pushed **Done** off
  the screen; the message now takes the date's place.

## 0.1.1

### Changed

- **Labelled experimental.** Morph is not finished and not recommended for
  general use yet: the README, the documentation, the add-on store
  description and Morph's own Settings page say so, the way BRight does.
- **Getting Morph into the sidebar is spelled out.** Morph is a panel the
  `morph` integration registers inside Home Assistant's own frontend, not an
  ingress add-on, so there is no "Show in sidebar" switch on the add-on's
  page. The option that looked like one is now called *Install the Morph
  integration*, and the README, the documentation and the add-on log name
  the two steps: accept **Morph** under Settings → Devices & services, then
  restart Home Assistant once.

## 0.1.0

### Added

- **Morph, a dashboard in the sidebar.** The add-on installs the `morph`
  integration, which registers a full-page panel inside Home Assistant's own
  frontend — so it has the live `hass` object and can host any Lovelace card.
- **The layout engine from the MORPH UI prototype**: sections in columns that
  never overlap, rows that only hold things of one height, cards that open in
  place (their neighbours make room first, then the card grows), springs for
  every move, and tap-outside to fold back.
- **Cards per domain**: lights and light groups (one strip per member), fans,
  covers (a garage door asks for a second tap), locks (unlock asks for a second
  tap), switches, buttons, vacuums, climate, sensors with a sparkline, many
  readings overlaid on one chart, meters, media, cameras, lists, people,
  weather, alarms, scenes as words, notes — and any Lovelace card, pasted as
  YAML or JSON, hosted inside a section.
- **History that belongs to its device**: holding a card opens its day (or its
  week) as a strip or bars, which drill into hours, with who or what changed it
  read from the logbook.
- **The dashboard is a file, and its history is git.** `/config/morph` holds
  `dashboard.yaml`, `AGENTS.md`, `LEARNED.md` and `cards/`; every change —
  yours in Edit, brAIn's from a Tell, a lesson the learning loop wrote, or an
  edit made by hand — is one commit, and Settings → History can undo or
  restore any of them.
- **Edit mode**: tap a section or card to edit it, drag sections between
  floors, add cards from the entities nearby or any entity, or paste any
  Lovelace card.
- **Tell brAIn**: in Edit, hold anything and say what should change. brAIn
  acts at once — on the dashboard, on Morph's card code, or on the house
  behind it — and Morph commits the dashboard half as one change you can keep
  or undo in the same place. Undo also asks brAIn to put back any house
  change it made.
- **What brAIn adds when it is installed**: the story at the top (what the
  house is doing, from brAIn's situation and the dashboard's own state), Ask
  the house, Coming up, and brAIn's findings as notes in place on the section
  they are about.
- **A learning loop that asks first**: Morph keeps a log of what is used and
  when, and a scheduled brAIn pass (read-only) turns it into suggestions shown
  in place with Do it, Not now and No. A No with a reason becomes a lesson in
  `LEARNED.md`, which every Tell and every pass reads.
- **A loop for Morph's own code**: a card that fails to draw, a layout that
  overlaps at rest, or a request Morph could not carry out is handed to
  brAIn's development loop, which files it in your private reports repository
  for the cloud routine to fix.
- **Settings** in the panel: brAIn's model and the hold time, learning (on/off,
  how often, which model, Learn now, the scorecard, the lessons — editable),
  reporting Morph's own problems, appearance (theme, reduced motion), history,
  and rebuilding the dashboard from the house.
- **Security rating 6/6**: no ingress, no published port, an AppArmor profile;
  the service answers only loopback, for its own health check.
