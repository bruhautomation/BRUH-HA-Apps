# Changelog

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
