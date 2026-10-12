# Changelog

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
