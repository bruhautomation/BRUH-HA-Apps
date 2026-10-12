# Changelog

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
