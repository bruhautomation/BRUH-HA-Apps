# brAIn 4.0: Morph becomes part of brAIn

The owner's words: *"I'm annoyed how fragmented the handoff between morph and
brain is"*, and *"in my ideal world brain and morph would merge. We'd have a
features toggle in the settings. It lets you turn on the Morph UI,
Personality, Learning Loop, and Development loop."*

This is the plan that release follows, kept as the record of why the pieces
sit where they do.

## 1. What merges

| Before (two add-ons) | After (brAIn 4.0) |
|---|---|
| `morph/` add-on: its own image, `run.sh`, `/data`, options | `brain/morph/service/` + `brain/morph/defaults/`, run by brAIn's `run.sh` as one more supervised process (`start_morph`), its state in brAIn's `/data/morph` |
| `morph` integration (domain `morph`), its own config entry | `custom_components/brain/morph/`, set up by the `brain` integration. The `morph` domain is gone; brAIn removes a leftover `morph` config entry and `/config/custom_components/morph` |
| Two sidebar entries (brAIn's ingress, Morph's custom panel) | One: the `brain` custom panel, titled by the assistant's name |
| Morph's own Settings page and its bar's brand and ⚙ | ⚙ › **Features** and ⚙ › **Dashboard** in brAIn |
| `learning` and `report_code_issues` (Morph options) | ⚙ › Features › **Learning loop** and **Development loop** |

What does NOT move: `/config/morph` (the dashboard and its git history),
`/config/.morph` (the integration↔service folder), the websocket command
names (`morph/*`), the static paths (`/morph_static`, `/morph_cards`), and
every file contract between brAIn's panel and the service (`cases.json`,
`feed.json`, the request queue, the task folder). A house upgrading keeps its
dashboard, its lessons (LEARNED.md) and every commit. Morph's own `/data`
(its settings: theme, hold time, the learning scorecard) belonged to the
retired add-on and cannot be read from brAIn; those start from their
defaults once.

## 2. One screen

Morph has to run inside Home Assistant's frontend: it hosts Lovelace cards
with the live `hass`, which an ingress iframe cannot do (constructed
stylesheets cannot cross documents). brAIn's panel has to be an ingress page:
its API is the add-on's port. So the one screen is a custom panel,
`<brain-shell>` (`custom_components/brain/morph/frontend/shell.js`), holding
both:

- **brAIn's page in an iframe**, from brAIn's ingress URL with `?shell=1`.
  The shell opens the ingress session itself (`supervisor/api` →
  `/ingress/session`, the cookie Home Assistant's own ingress view sets, and
  `/ingress/validate_session` every minute).
- **Morph, drawn natively** (`<morph-boot>`), over the iframe's content and
  under its bars. The header is brAIn's own top bar, unchanged, with **Home**
  added as its first tab. brAIn reports its bars' heights
  (`{type: "brain-shell", bars}`) and the shell fits Morph between them; a
  press on Home or any other tab is a message to the shell. A popover or
  dialog the header opens while Home is in front raises the iframe above
  Morph until it closes, with brAIn's page transparent behind it.
- **On a phone** the header is brAIn's 56px row and its bottom tab bar; the
  shell passes `narrow`, and brAIn's row gets a ☰ that opens Home
  Assistant's sidebar.
- **A user who is not an administrator** has no ingress session; with the
  dashboard on they see Morph alone, exactly as before. With it off the
  panel is administrators only, as brAIn always was.

brAIn's own ingress sidebar entry is hidden while the shell panel is
registered and fresh (`/config/.brain/shell.json`, rewritten by the
integration every few minutes), and put back the moment it is not, so a
Home Assistant that failed to load the integration never leaves a house
without a way in. brAIn only ever undoes a hide it made itself.

## 3. Features

⚙ › **Features** is the first section of Settings. Four switches, each one
sentence on what it does and one on where its work goes:

| Switch | What it does | Where it goes | Default |
|---|---|---|---|
| **Morph dashboard** | The Home tab: a dashboard laid out by what matters in the house right now, which brAIn designs and edits with you | Stays in this house | On when `/config/morph/dashboard.yaml` exists, else off |
| **Personality** | brAIn takes the name and personality you give it, everywhere: the sidebar, every screen, chat, voice, notifications | Stays in this house | On when a personality is already set, else off |
| **Learning loop** — *self-improvement* | brAIn changes itself here: it watches how its dashboard is used, suggests improvements, keeps this household's lessons, and may propose changes to its own dashboard code. Off, it still does what you ask but never changes itself on its own | Stays in this house | On |
| **Development loop** — *improving brAIn for everyone* | brAIn sends redacted reports of its own faults to your private GitHub repository, where the cloud routine fixes brAIn's code and ships it | Leaves this house, redacted | Off |

The distinction the owner asked for, in one line each:

- **Self-improvement** is a change brAIn makes to *itself, locally*: its
  dashboard, its lessons, its own copy of its dashboard code. Nothing
  leaves the house. (Learning about the *house* — memory, facts — is not
  self-improvement and stays under ⚙ › Memory.)
- **Development** is brAIn *reporting back* to the repository its code
  comes from. It is the only one of the four that sends anything out.

The development switch is the devloop's own `enabled`; its repository,
token, streams and limits stay in ⚙ › Developer, which says to turn it on in
Features when it is off. "Development mode" (the devloop's autopilot) is
renamed **Report everything without asking**, since "brAIn works on itself"
read as self-improvement.

The resolved switches are one file, `/config/.brain/features.json`, written
only by brAIn's panel (`panel/features.py`) and read by the service, the
integration and the CLI. A switch is live: no restart.

## 4. Personality is a name everywhere

With Personality on, the word "brAIn" is the chosen name on every surface a
person reads: the sidebar title, the header (the wordmark gives way to the
name), every screen in brAIn and Morph, notifications, Repairs and the
To-do list. The rule is one helper per side:

- server: `personality.assistant_name()` (now `"brAIn"` whenever the switch
  is off) and `personality.speak(text)` for prose that is about to reach a
  person;
- browser: `speak()` in brAIn's panel, applied to the page's text as it is
  drawn (never inside a text box being edited, `<code>` or `<pre>`), and the
  same in Morph's regions.

With Personality off, the stored personality is kept but nothing reads it:
every prompt is byte for byte what a house with no personality gets.

## 5. Retiring the Morph add-on

`morph/` leaves the repository. On a house that still has it installed,
brAIn's `run.sh` stops it, sets it not to start at boot, deletes
`/config/custom_components/morph` (it would register the same websocket
commands) and says so once in a notification: *Morph is part of brAIn now;
you can uninstall the Morph app.* It never uninstalls it, because that
deletes the add-on's data and cannot be undone.

## 6. Order of work

1. Move the files (`git mv`, so history follows) and point every path at
   the new home: Dockerfile, `run.sh`, tests, CI, `tests/affected.py`.
2. `features.py`, its route and its mirror; the service, Personality and the
   devloop read it.
3. The shell panel, brAIn's embed mode and the ingress sidebar hide.
4. ⚙ › Features and ⚙ › Dashboard; Morph's Settings page and bar controls
   go.
5. Docs, notes, README, CLAUDE.md, CHANGELOG (brAIn 4.0.0), and the suite.
