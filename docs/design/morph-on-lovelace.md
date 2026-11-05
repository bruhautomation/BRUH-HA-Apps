# Morph on Lovelace: a real Home Assistant dashboard, with brAIn on top

The owner's words: *"For mainstream adoption of Morph, it needs to be almost a
direct fork of the standard Home Assistant dashboard. It should behave and
have the exact same features, support all the same default cards, HACS
cards, have the exact same UI elements, but what it gains is the brAIn layer
that allows you to pretty much completely edit and control it in real time
… theme, behavior, dashboard layout, tabs. When building a card in Morph,
brAIn should build a card type; when that card type is updated, it updates
that card type everywhere. HACS cards work completely, but you gain the
ability to edit them directly in place with brAIn. Things like the Morph
scroll rail can be a togglable feature. Themes used elsewhere in Home
Assistant extend into Morph. Even the sidebar should behave the same."*

This is the plan for that refactor (brAIn 5.0), and below its decisions, the record of what shipped. It is written the way
`brain-morph-merge.md` was: the decisions and the reasons first, then the
order of the work. When it ships, the lessons go into `docs/notes/morph.md`
as usual.

## What shipped in 5.0.0, and what is still to do

Shipped: Morph's cards as HA cards with HA's visual editor (§2.3's
first-party cards); card types (template and element) with live updates
and a usage index; HACS cards changed in place through config and card-mod
(the prompt's rule; the automatic fork-and-pause of a copied HACS card is
not built); "Let brAIn change it" and the sync with git per dashboard
(§2.1); the layer with pick-a-card, Tell, Keep/Undo, History/Restore
(§2.2); Morph's view with order, fold and the room rail, the cases and Ask
cards (§2.5); Morph's themes added to HA's (§2.6); the converter and
"Bring over your Morph dashboard" (§3, steps 1 and 3).

Not yet, or done differently:

- **No id sidecar.** Cards are found by their path in the config and by
  identity in the browser; the learning loop's usage log is not kept for
  HA dashboards yet.
- **brAIn's shell is unchanged** (§2.7): Morph's old panel stays the Home
  tab, and the new dashboard is a sidebar entry beside it. Retiring the
  classic panel (§3 step 4, §4 phase 7) is the next release's.
- **No CI job against a real Home Assistant** (§5): the layer is tested on
  stand-ins for HA's page. That job is the most important thing left.
- `cards/*.js` are loaded on HA dashboards as they are; converting them to
  element types (§3 step 2) is not done.
- The layer floats a button and a sheet rather than joining HA's toolbar.

## What changed in 5.1.0 (the owner, 2026-11-05)

The owner, after using 5.0: *"So many of the cards I have seem broken, can't
edit them manually with a GUI, aren't rendering correctly. Certainly aren't
resizing."* And: *"I'm not certain I need dynamic rearranging, but I do want
dynamic resizing… elements of Morph don't work great (e.g., the horizontal
sizing determination) and the Home Assistant engine maybe better or at
least good enough… Be sure Morph can see (literally screenshot) any of the
dashboards and can have full read/write control over everything there."*

- **HA's sections view replaces Morph's view** for every tab (§2.5's table
  is superseded where it says `custom:morph-view`): a custom view never gets
  HA's section editing, badges or columns. Morph's room rail, lifting and
  folding are the view's `morph:` switches on HA's own view
  (`morph-view-layer.js`), off unless set, the rail on for a converted
  dashboard. 5.0's Morph views were migrated once.
- **HA sizes the cards; Morph's cards fill the size** (`SIZES`, `:host([grid])`),
  and an opened card grows its own grid cell. Every key a Morph card reads
  is in HA's visual editor (actions, icon, the opened card).
- **brAIn sees and edits every dashboard**: `screenshot_panel` with addon
  "Home Assistant" (signed in through `morph/eyes`, guarded so the page can
  change nothing), `edit_dashboard` (ops on paths) and
  `brain.update_dashboard_info`.
- **The CI job against a real Home Assistant exists** (§5): `tests/realha`,
  on 2025.1.4 and 2026.11.0. It found the one release-specific break
  (a section's index) before a house did.

Still not done from the plan: the id sidecar, the classic panel's
retirement, converting `cards/*.js` into named types (a house's own card
kinds now come along as Morph cards instead), and the layer joining HA's
toolbar.

## 0. Decisions taken (with the owner, 2026-11-04)

| Question | Decision |
|---|---|
| Fork HA's frontend, or build on it? | **Build on it.** A Morph dashboard is a *real* Lovelace dashboard (storage mode) drawn by Home Assistant's own frontend. brAIn is a **layer** loaded into that frontend, plus a set of custom cards and one custom view type. We do not vendor or rebuild HA's frontend. |
| Which dashboards get the layer? | **Any dashboard, opt-in.** "Morph this dashboard" is a switch on any Lovelace dashboard, including the house's existing default one. Turning it on starts that dashboard's git history. |
| The current Morph dashboard and brAIn's shell | **Convert, and give each its own sidebar entry.** `dashboard.yaml` is converted to a Lovelace dashboard and keeps its git history. brAIn's sidebar entry goes back to being brAIn only. The old Morph panel stays behind a switch for one release, then is removed. |
| How deep do HACS edits go? | **Config and style in place; code by fork, on request.** brAIn edits a HACS card's config and its styles in place, and HACS updates are never blocked. A code-level change turns the card into a Morph card type that wraps or copies it, and that copy is paused automatically when HACS updates the original (`morphcode`'s rule, carried over). |

Why not a literal fork: HA's frontend is a TypeScript/Lit app built with
its own toolchain, and it ships with HA core every month. A fork has to be
re-merged every month or it drifts from the core it talks to. It would also
lose exactly what the owner asked for: "the exact same features" *the day HA
ships them*. Building on the real thing gets every built-in card, every HACS
card, the visual editor, sections/masonry/panel/sidebar views, badges,
headings, the card picker, conditional visibility, per-user views,
themes and the sidebar for free, and keeps them current with no work.

## 1. What Morph becomes

```
Home Assistant frontend (unchanged, HA's own)
 └─ a Lovelace dashboard, storage mode            ← drawn by HA, every card works
     ├─ HA's built-in cards, HACS cards           ← untouched
     ├─ Morph card types   custom:morph-<slug>    ← brAIn-built, defined once, used anywhere
     ├─ Morph feature cards custom:morph-now, -cases, -ask, -coming-up, -story
     ├─ Morph view type     custom:morph-view     ← the salience layout, optional per view
     └─ the brAIn layer     (add_extra_js_url)    ← edit in place, Ask, history, undo, rail
brain integration (Python, in HA)
 └─ writes the dashboard through HA's Lovelace storage; serves the layer, types, themes
morphd (in brAIn's container)
 └─ git history of every Morph dashboard, types and themes; Tells; learning; devloop
```

The rule that makes it calm to depend on: **if the layer fails to load, the
house still has a working Home Assistant dashboard.** Nothing a person needs
on an ordinary day may live only in the layer.

## 2. The pieces

### 2.1 The dashboard is HA's own storage dashboard

- **Storage, not YAML mode.** Only storage-mode dashboards keep HA's visual
  editor, card picker and "Edit dashboard" working. A Morph dashboard is
  stored where HA stores any dashboard (`.storage/lovelace.<url_path>`) and
  is written only through HA's Lovelace API, never by editing `.storage`
  directly.
- **One writer in HA, one history in git.** The integration owns the write
  (`morph/dashboard_save` → the dashboard's `LovelaceStorage.async_save`).
  morphd keeps the history: every save becomes one commit of
  `/config/morph/dashboards/<url_path>.yaml` in the existing git repository,
  authored by who made it (`person`, `brain`, `learning`, `outside`). An edit
  made in HA's own editor arrives as `lovelace_updated`; the integration
  mirrors it and morphd commits it as *Edited in Home Assistant*. That is the
  existing "*Edited outside Morph* before anything else touches the tree"
  rule. Undo and restore write an old version back through the same API, as
  a new commit, so an undo is still undoable.
- **Real time comes from HA itself.** HA's `ha-panel-lovelace` reloads the
  config in place on `lovelace_updated` when the dashboard is not in edit
  mode (checked in the frontend source, `_lovelaceChanged`). So a Tell's save
  appears on every open screen in the house within a second, with no reload
  and no toast. In HA's edit mode, HA shows its own "updated elsewhere,
  Refresh" toast. The layer leaves that toast as it is: two editors at once
  is a real conflict, and HA's own wording is the right one.
- **Card identity without ids in card configs.** Undo, notes, usage and
  learning key on card ids today. Lovelace cards have none, and putting an
  unknown key into a built-in card's config makes HA's visual editor refuse
  it (its config structs reject extra keys). The ids live in a **sidecar**
  instead (`/config/morph/dashboards/<url_path>.ids.json`), reconciled by
  morphd on every commit by matching the old tree to the new: same
  view/section path and type first, then the closest config. A card moved by
  hand keeps its id; a card whose type changed gets a new one. This replaces
  `store._pre`/`normalize`'s id round trip, and it needs its own test, held
  as strictly as the round trip is today.
- **"Morph this dashboard."** A switch in the layer's menu on any dashboard
  (admins) and in ⚙ › Dashboard. Turning it on takes the first commit,
  starts the sidecar and enables the layer for that `url_path`. Turning it
  off stops the history and the layer, and leaves the dashboard exactly as
  it is. brAIn can also create a new dashboard (`lovelace/dashboards/create`),
  which is then Morphed from its first save.

### 2.2 The brAIn layer

One ES module (`brain-layer.js`), registered with
`frontend.add_extra_js_url`, loaded on every HA page and active only on a
Morphed dashboard, for an administrator. It adds things and never replaces
HA's own UI:

- **A brAIn button in the dashboard's toolbar,** next to HA's own icons. It
  opens Ask, History, Undo and "Morph this dashboard". It is drawn from
  `hui-root`'s toolbar slot and falls back to a floating button if that slot
  moved in an HA release.
- **Hold anything, Tell brAIn.** Hold a card, a badge, a heading, a section
  title or a view tab to get a small bar with a **Tell brAIn** line, in the
  same place HA puts its own edit affordances. The layer resolves the held
  element to its config path (view → section → card, through `hui-card`'s
  `config` and its position in its parent) and to its sidecar id. It takes
  the picture with the existing `snap.js`: HA cards are shadow DOM in the same
  document, which `snap` already flattens. The prompt carries the path, the
  card's YAML, the picture and, for a card type, its definition.
- **The Tell box, its steps, Keep and Undo** move into the layer unchanged
  in behaviour (`tell.py`'s read-back, the "where it reached" list, parked
  tells, questions). The diff it reads back is now the Lovelace config
  before and after, so "Nothing on the dashboard changed" still means what
  it says.
- **History.** The commit list for this dashboard, with restore. This is the
  current History page, opened from the brAIn button as an HA-styled dialog.
- **What it does not do.** It does not restyle HA, it does not hide HA's
  header or sidebar (that becomes a dashboard *behaviour* brAIn can set, see
  2.6), and it does not touch dashboards that are not Morphed.
- **Version tolerance is a feature with a test.** The layer reaches HA
  internals (`home-assistant` → `ha-panel-lovelace` → `hui-root` →
  `hui-view` → `hui-card`). Each lookup is one function in `layer/ha-dom.js`
  with a fallback, and a lookup that fails turns that one affordance off and
  files a devloop row ("brAIn layer: toolbar slot not found on HA 2027.1").
  It never throws into HA's page. CI runs the layer against the oldest
  supported HA release and the current one (section 5).
- **Non-administrators** see the plain dashboard, plus whatever Morph cards
  the dashboard holds (Ask is a card, so a family tablet can still ask).

### 2.3 Card types: build once, update everywhere

When brAIn builds a card, it builds a **type**, and a dashboard holds
instances of it.

- **Where types live:** `/config/morph/types/<slug>/`, in git.
  - `type.yaml`: name, description, icon, the variables an instance sets
    (`schema`, an HA `ha-form` schema) and one of the two kinds below.
  - **`kind: template`:** a Lovelace card config, built-in or HACS, with
    `[[var]]` placeholders. Most "cards" brAIn makes are compositions of
    existing cards (a tile grid, a stack with a header, a conditional), and
    a template keeps them inside HA's own cards, so they look and behave
    exactly like everything else.
  - **`kind: element`:** a `card.js` custom element, for something no
    existing card can draw. This is today's `/config/morph/cards/*.js`,
    given a name, a schema and a version.
- **How they appear in HA:** the types module (served by the integration,
  stamped like `boot.js` is today) registers each type as its own element,
  `custom:morph-<slug>`, and adds it to `window.customCards`. So a type
  shows up in **HA's own card picker** with its name and preview. It
  answers `getConfigForm()` from its schema, so **HA's own visual editor**
  edits an instance's variables. A template type builds its inner card with
  HA's `createCardElement` and forwards `hass`, sizing (`getCardSize`,
  `getGridOptions`) and the editor's preview.
- **Update everywhere:** editing the type's file changes every instance on
  every dashboard. Through the stamp, open screens pick up a new definition
  with no reload: the types module re-renders its instances; it does not
  re-`define`, which is the card-loader lesson in `morph.md`.
- **This one, or all of them?** When a Tell is about an instance of a type,
  the layer asks first: *"This is one of 7 Thermostat cards. Change this one,
  or the type?"* "This one" writes the instance's variables, or detaches it
  into a plain copy if the change cannot be said in variables. "The type"
  edits the type, with a preview of each place it is used. A usage index
  (`types/index.json`, rebuilt by morphd on each commit) says where every
  type is used, across every Morphed dashboard.
- **Versioned with the house.** A type change is one commit, and Undo puts
  every instance back at once. The devloop's card-threw row names the type
  and its version, not one dashboard's card.
- Morph's 22 built-in kinds (`cards.js`'s `TYPES`) do not come along as
  "Morph cards". Each one either maps to an HA card (light → `tile` with
  features, climate → `thermostat`, a light group → `tile`s in a `grid`,
  camera → `picture-entity`, …) or, where Morph's version was genuinely
  better (the climate strip with its target band and script buttons,
  readings overlay, Coming up), ships as a **first-party type** in the same
  registry, which a house can then change like any other type.

### 2.4 HACS cards, in place

- **Config and style, in place.** Hold a HACS card and Tell brAIn: brAIn
  edits that card's config, or its styles through a `card_mod` block if
  card-mod is installed. If it is not, it asks to install it rather than
  wrapping the card behind the person's back. HACS updates are never
  blocked, and nothing HACS installed is ever edited.
- **Code, by fork.** If the change needs the card's code, brAIn says so and
  offers **Make it a Morph type**: either a `template` that wraps the HACS
  card, or an `element` type that copies its JS into the type folder. A
  copy records the HACS version it was taken from (`.base.json`, the
  `morphcode` record). When HACS updates the original, the copy **pauses**:
  the original is served, the instance carries a note, and **Make it again**
  runs the three-way merge Tell that `morphcode` already does for Morph's
  own modules.
- **Knowing a HACS card** comes from HACS's own resource list
  (`lovelace/resources` plus `/config/www/community/<repo>/`), so brAIn can
  name the card's repository and version in the Tell prompt and read its
  README for options before guessing.

### 2.5 Morph's own features become cards, a view and toggles

Everything that makes Morph *Morph* survives as something a dashboard opts
into, each one switchable on its own:

| Today (Morph panel) | Becomes | Toggle |
|---|---|---|
| Salience layout (one score, bands, rooms reorder and fold, quiet-moment apply) | `custom:morph-view`, a view type: sections from HA areas, ordered and folded by `salience.js` (moved as is: it is already pure) | per view: pick "Morph" as the view type, alongside Masonry, Sections, Panel and Sidebar |
| Now layer (≤3 lifted cards) | `custom:morph-now` card; inside `morph-view` it is the top band | the card is there or it is not |
| brAIn's cases in their room | `custom:morph-cases` card (`area:` filter, or all); in `morph-view`, drawn in the room | card |
| Ask bar | `custom:morph-ask` card, plus the layer's Ask for admins | card |
| Story / greeting line | `custom:morph-story` card | card |
| Coming up strip | `custom:morph-coming-up` card (`upcoming.js` moved) | card |
| To Do section | HA's own `todo-list` card on brAIn's to-do entity | nothing new |
| Room rail (pull left, notches, room meets the thumb) | a layer feature that works on **any** view with sections (`morph-view`, Sections, Masonry), keyed on section headings | per dashboard: **Room rail** |
| Header switch pills, scene row | HA heading badges / heading entities on a Sections view (native since 2024.10) | nothing new |
| Night dim, room marks | `morph-view` options | per view |
| Morph's three themes | HA themes (2.6) | the theme picker |
| Open in place (springs, make room first) | `morph-view` only; other views open cards the HA way (more-info) | per view |

`engine.js` stays only inside `morph-view`. A Sections or Masonry view is
HA's layout, untouched, which is the point.

### 2.6 Theme and behaviour: HA's, and brAIn edits both

- **Themes are HA themes.** Morph's light, medium and dark ship as one HA
  theme with modes (`Morph`, `modes: light/dark` plus `Morph Medium`),
  written to `/config/themes/morph/` and loaded through `frontend: themes:`.
  The integration checks that include is present, and asks before adding it
  to `configuration.yaml`. Every Morph card and `morph-view` read HA's theme
  variables (`--primary-background-color`, `--card-background-color`,
  `--primary-text-color`, `--ha-card-border-radius`, …) instead of Morph's own
  `--bg`/`--surface`, so **any** HA theme, from HACS or the house's own,
  dresses Morph too.
- **brAIn edits themes in real time.** "Make the cards rounder", "warmer at
  night": brAIn writes the theme file and calls `frontend.reload_themes`, and
  every open screen repaints. A theme can be set per view (`theme:` on the
  view, HA's own), per user (HA's profile), or house-wide
  (`frontend.set_theme`). Theme files are in the same git history and Undo
  works on them.
- **Behaviour is dashboard config,** not layer magic: hide the header or
  sidebar on a wall tablet, a view only one person sees, a card shown only
  at night. These are HA's own `visible`/`visibility` conditions and
  per-view `subview`/`max_columns`, plus a small set of layer behaviours
  stored under the dashboard's Morph settings (`/config/morph/dashboards/
  <url_path>.morph.yaml`: room rail, hold time, kiosk header/sidebar). brAIn
  can change all of them by Tell.

### 2.7 The sidebar and brAIn's shell

- A Morphed dashboard is an ordinary HA dashboard: **its own sidebar
  entry**, its own icon and title, reorderable and hideable like any other,
  default dashboard if the house chooses, and HA's own narrow-screen
  behaviour and ☰. The converted Morph dashboard is registered as
  `morph-home` (title "Home"), and the house can make it the default.
- **brAIn's sidebar entry is brAIn again.** The shell (`shell.js`) stops
  hosting Morph as its Home tab; brAIn's top bar loses Home and the
  `morph-chrome` Edit/Done/YAML bridge. `panel/shell_link.py`'s
  hide-the-ingress-entry logic either goes, or keeps the custom panel only
  for its ingress-session handling (to be decided in phase 6 by measuring
  which is smaller).
- The layer's brAIn button and brAIn's Ask both reach the same brAIn, so
  "open brAIn" from a dashboard is a link to brAIn's panel with the context
  (dashboard, view, held card) carried in the URL.

### 2.8 The service and brAIn's side

- **morphd** keeps git, Tells, conversations, learning, the devloop ledger
  and `morphcode`. `store.py`'s Morph schema (`normalize`, floors, kinds) is
  replaced by: Lovelace config in and out via the integration, the id sidecar,
  the types registry and its index, and the per-dashboard Morph settings.
- **The Tell prompt** (`tell.build_prompt`, `defaults/AGENTS.md`) is
  rewritten. A Morph dashboard *is* Lovelace YAML now, so the long-standing
  "never a Lovelace one" line inverts. brAIn is told: the dashboard's config
  and path; HA's card catalogue for the running version; the HACS cards
  installed and their versions; the types and where they are used; prefer
  an existing HA or HACS card, then a template type, then an element type;
  never write `.storage`. It edits through MCP tools (`morph_dashboard_get`,
  `morph_dashboard_patch` (a JSON-patch on one path),
  `morph_type_write`, `morph_theme_write`), never by writing the files, so
  every change goes through one writer and is one commit.
- **Learning loop.** The layer logs uses from HA's own `hass-action` and
  `hass-more-info` events, bubbling from any card, keyed by sidecar id, in
  the same `USAGE_KINDS`. Suggestions stay brAIn's cases.
- **Devloop.** Rows gain the HA version and the layer's lookup that failed,
  because "the layer broke on a new HA" is the class of fault this design
  adds.
- **What is deleted** once the old panel is gone: `morph-panel.js`,
  `cards.js`'s built-in kinds, `boot.js`'s outline, `styles.js`'s themes,
  `morph-dom.js` (HA does the rendering), `store.normalize`'s schema, and the
  shell's Home tab. About 5,500 of today's 7,900 frontend lines. Moved, not
  deleted: `salience.js`, `engine.js` (inside `morph-view`), `rail.js`,
  `snap.js`, `upcoming.js`, `cases.js`, `history.js`'s charts.

## 3. Migration of an existing house

1. **Convert** (`morphd convert`, run once by 5.0's first start, and again
   on request): `dashboard.yaml` → one Lovelace dashboard `morph-home`.
   - A floor → a view (tab).
   - A room/section → a section of a `custom:morph-view` view, so the house
     sees the layout it knows on day one.
   - Each card kind → its mapped HA card or first-party type (2.3), with
     `options.actions`, `options.detail` and `options.header` carried to
     their HA equivalents.
   - `lovelace` cards are copied as they are.
   - Scenes → heading entities.
   - `theme` → the matching Morph HA theme on the dashboard's views.
   - The old ids become the sidecar, so notes, usage and learning carry
     over.
2. **Convert `/config/morph/cards/*.js`** into element types (a name and a
   schema inferred from the config the dashboard passed them; brAIn fills
   the description). An accepted copy of Morph's own frontend modules has
   nothing to apply to after conversion. It is reported in the conversion
   summary and left in git, never silently deleted.
3. **Report, do not guess.** The conversion writes a summary as a brAIn case
   ("Your Morph dashboard is now a Home Assistant dashboard: 46 cards moved,
   3 need a look"), with the picture of each card that could not be mapped
   cleanly. "Undo the conversion" deletes `morph-home` and turns the old
   panel back on.
4. **One release with both.** ⚙ › Features › **Classic Morph panel** (off
   for new installs, on for an upgraded house until it opens `morph-home`
   once) keeps the old panel and the shell's Home tab for 5.x. Both read the
   same git repository, but only the new dashboard is written, so the
   classic panel turns read-only with a line saying where the dashboard
   moved. Removed in 5.1 or 6.0.

## 4. The order of the work

Each phase ships on its own, behind ⚙ › Features › **Morph on Home Assistant
dashboards (preview)** until phase 6.

| Phase | Work | Done when |
|---|---|---|
| **0. Spikes** (no release) | (a) Layer finds `hui-root`'s toolbar and every `hui-card`'s config path on the oldest supported HA and the current one; (b) an outside `lovelace/config/save` repaints an open dashboard in < 1s (measured, not assumed from the source); (c) `snap` photographs a `tile`, a `thermostat`, a Mushroom and a `picture-entity` card; (d) a `custom:morph-view` renders sections with HA's own cards inside; (e) a template type in HA's card picker with a `getConfigForm` editor | each spike is a script in `tests/manual/` with a pass/fail line |
| **1. Native dashboard + history** | integration write path, `lovelace_updated` mirror, morphd git per dashboard, id sidecar, "Morph this dashboard", Undo/restore, MCP `morph_dashboard_get/patch` | a Tell by chat changes a Morphed default dashboard live on two screens; an HA-editor edit is one *Edited in Home Assistant* commit; Undo of each works |
| **2. The layer** | brAIn button, hold → Tell with picture, Tell box, History, version-tolerant lookups and their devloop rows, usage logging | hold a built-in card, a HACS card and a heading, Tell, see it change, Undo; non-admin sees no layer |
| **3. Card types** | registry, types module, card picker, `getConfigForm`, usage index, "this one or the type", first-party types | brAIn builds a type used on two dashboards; changing the type updates both live; Undo puts both back |
| **4. HACS in place** | card-mod path, Make it a Morph type (wrap/copy), pause on HACS update, three-way merge Tell | a Mushroom card restyled in place; a copied HACS card pauses when HACS updates it, and Make it again merges |
| **5. Morph features** | `morph-view`, `morph-now`, `-cases`, `-ask`, `-story`, `-coming-up`, room rail as a dashboard toggle | `measure-morph`'s night, salience and rail checks pass against `morph-view` inside real HA |
| **6. Themes + migration + shell** | Morph HA themes, HA theme variables everywhere, theme Tells; `convert`; brAIn's shell loses Home; Classic Morph switch | an upgraded test house converts with its ids, and every card is accounted for in the summary |
| **7. Remove the classic panel** (next release) | delete what 2.8 lists; notes and tests follow | `docs/notes/morph.md` rewritten; nothing imports the old modules |

## 5. Testing

- **The layer is tested against real Home Assistant, not a fixture.**
  `measure-morph.mjs` drives a fake `hass`; that cannot catch the risk this
  design adds (HA moving an internal element). A new CI job starts a real
  HA (the cooking job already runs HA core on Python 3.13), onboarded by
  script, with a test house (template entities, one HACS card such as
  Mushroom vendored into `www/`). Playwright drives the dashboard there, on
  two HA versions: the oldest the add-on supports and the newest release.
- `test_morph_vision.py`'s salience tests move with `salience.js`
  unchanged. `test_morph_design_rules.py` is rewritten for what Morph still
  draws (its cards and view: no `title=`, the 16px field floor, 40px
  targets). Theme-number rules are dropped, because the theme is HA's.
- New pure tests: the id sidecar reconcile (move, reorder, retype, a hand
  edit in HA's editor), template expansion, the usage index, the conversion
  of every card kind in `cards.js`'s `TYPES`, and the pause rule for a
  copied HACS card.
- `tests/affected.py` gets rules for `brain/custom_components/brain/morph/
  layer/` and `types/`.

## 6. Risks

| Risk | What this plan does about it |
|---|---|
| HA renames or restructures `hui-root`/`hui-card` | every lookup in one file with fallbacks; a failure turns off one affordance and files a row; CI on two HA versions; the dashboard itself never depends on the layer |
| `lovelace_updated` behaviour changes | phase 0 measures it; the layer can call the frontend's own reload as a fallback |
| HA's visual editor and brAIn editing at once | HA's own "updated elsewhere" toast; morphd commits both, so nothing is lost |
| A house's existing dashboard is precious | Morphing it is opt-in, the first commit is the untouched dashboard, and turning Morph off leaves it as it is |
| Template types inside HA's visual editor (stacks, conditional) | phase 0 spike (e); if the preview misbehaves, the type's editor is our own form, still inside HA's dialog |
| Losing Morph's character | it is all still there as `morph-view` and the cards; the vision's night test and salience tests keep running |

## 7. Still open (smaller, decided in the phase that meets them)

- Whether brAIn's shell keeps a custom panel at all once Morph leaves it
  (phase 6).
- The oldest HA release the layer supports (phase 0 picks it from what the
  lookups need; HA's `getConfigForm` and heading badges set a floor around
  2024.10–2024.12).
- Whether first-party types ship enabled in the card picker, or only appear
  once a house uses one (phase 3).
