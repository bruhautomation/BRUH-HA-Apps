# brAIn: panel UI rules: history moved out of docs/notes/panel.md

What each rule in `docs/notes/panel.md` cost to learn: the shapes the page had before, measurements, the owner's words, issue numbers and pointers to tests. None of it is needed to follow the rules; it is here for the next person who wonders why a rule exists. Pointers to tests under `tests/` name files that were removed in November 2026 with the old suite, and the CI `layout` job that once ran the measure scripts is gone with it; the rules they enforced still hold. Each entry is the text as it stood in the note, cut out of the bullet named in its heading.

## A press whose only record is a toast is a press that reads as nothing

- "Check again" left the card looking exactly as it did before, so the button read as doing nothing, which is what was reported.

## A tooltip that opens off the screen is a tooltip that is not there, and CSS cannot see the edge.

- `[data-tip]::after` was `position: absolute; right: -4px`, max-width 240px, so the bubble hung *leftward* from the control's right edge: anything whose right edge sat under ~236px from the viewport's left lost its text off the side. Four of the six buttons under a finding at 390px; still two at 1100px, because the findings list starts at the left margin.
- The `.tipbox`'s flip above is what the old `.card .foot` override was patching one case of.
- Cancelling a tooltip still inside its open delay on `scroll` is what made a tooltip vanish for good whenever the page settled a scroll just after the pointer arrived.
- Tapping a bottom tab left a dark bubble repeating *Insights* pinned above the bar over the content, because the tap fired `pointerover` and then focused the button, and both opened it.

## A toast is `left: 12px; right: 12px; margin: 0 auto`, never `left: 50%` with a translate.

- Invisible until something sat beside the text, which is what Undo is.

## A popover whose anchor has gone is dismissed, not relocated.

- The next reposition put the popover at (8, 6) — the top-left corner of the screen.

## The top bar has two shapes and no third, and three tabs rather than eight.

- The version moved out of the header since the owner asked for a header that is *"subtle"*: the header carries only the name, `#brandMark`. It was one link: to this release's changelog entry, in a new tab; a plain press now opens What's new in the page.
- Stacked rather than side by side, so the bar is no wider than the logo was and every measured breakpoint stood (`measure-topbar` reported the same 129 shapes).
- **On a phone the tabs leave the top** came with design doc PR 10.
- There was briefly a third band (960–1239px: one row, labels deleted, tabs shrunk to glyphs) and it was the worst possible one to have, because it is what a laptop with the HA sidebar open renders at — the compromise shape was the one most people saw, and widening the window made the tabs grow.
- **Adding a tab moves both numbers, and removing four moved them back** — the breakpoint was 1240 until Proposals arrived, 1340 until To-do did and 1430 for the eighth, a tab being ~90px of row, and it came down to **920** with four (903px paused and 915px on a failed login, measured, which is where the number comes from), to 850 with three, and went back up to **870** when Today · House became the longer Insights · Memory (859px on a failed login).
- All the measure scripts also run in CI as the `layout` job, so a regression fails the PR — running them locally is about reading the failure next to your editor, not about being the only enforcement. (No longer true: the layout job went with the old suite.)

## No text control may be under 16px on touch.

- The docs search box at 14.4px is how it was found.

## Every control in the bar does its own job, and nothing is in it twice.

- Three controls used to open Settings, so a bar reporting three different things answered all of them with one dialog.
- "Usage budget reached" had a chip of its own beside a pill already showing the number it was about, and saying it twice is what wrapped a phone bar onto a third row. A reached budget is now the pill's own warning dot plus a line in its popover.

## The top bar's mark is the household's choice, and the version sits beside it only on a wide screen

- The owner wanted the brAIn logo by default, the assistant's name, or their own text or picture.

## The header clock is the date and the time, AM/PM included

- The shell's clock was h:mm only; the date gave way to Morph's own clock before it came back beside the time.
- **⚙ › Dashboard › Header tabs points at ⚙ › Personality › Header** because the owner looked for the mark's choice under Header tabs (`tests/test_header_clock_and_mark_link.py`).

## brAIn's page is usually inside the shell, and the bar is the one header

- **One header, one theme (the owner: *"there are two headers … merge them"*, the tabs *"pulled into the header (subtle and useful)"*, *"the rest of brAIn's menus must follow Morph's theming"*).**
- The quiet ✎ Edit under the header: the owner said Edit "should be more subtle and under the [header]".
- The status dot shows only when signed out because the owner: *"I also don't need the health indicator icon next to the gear"*; a house layer hid the rest for weeks.
- **On the owner's iPhone the header is two rows and gets out of the way** (the owner: it *"clashes with the Dynamic Island"*, *"I don't like those menu buttons up there all the time; maybe collapsible and goes away when you're not at the top"*, and *"the shell takes about 170px before any content … Make it subtle, collapsible"*).
- **nothing is drawn in the safe-area strip** (#839, the owner: with the app's full screen OFF *"the Vesper button and the time is behind my Apple header bar"*). Padding the strip twice where Home Assistant already starts the panel below it was #838.
- **The shell measures again whenever its place can have changed, without polling**: a house layer looked every 1.5 s from inside the frame to catch exactly this.
- The phone's sections row: the owner asked for a row; the menu under the tab is gone.
- Only the tab row slides away: the owner, "the collapsing menu was supposed to be just for the home insights ask memory buttons".
- The bounce at the end of a scroll and Home's pane growing as the row hides read as "up" and the row flickered in and out (#834).
- `measure-shell`'s "in the island strip" and "more than 60px of chrome under it" checks are the superseded design and fail now: the first row belongs below the strip.

## The home indicator reaches the framed page the way the top inset does, and Ask's two message boxes are padded for it once

- #876. The transcript's `env()` padding did nothing in the frame and the list page's box had none at all: both sat on the indicator.
- **The bar's height is observed on its border box**: before that, `--bar-h` kept the frame's own env() and every view sized by it stopped that much short of the foot — with the app's full screen off, Ask's box floated a whole inset above the bottom.

## The shell is as tall as the space Home Assistant gives it, and Home Assistant's page never scrolls under it

- #689, `tests/test_shell_fits_its_space.py`. The host was `100dvh`, so anything above it in the companion app (the safe-area strip, a toolbar) made Home Assistant's scroller overflow by that much, and a drag on the header scrolled Home Assistant's page with nothing inside the panel able to scroll it back.
- **Morph's room rail keeps the place and height it has with the tab row shown** (#690): a rail sized by `--morph-h` grew with Home, so `Rail.layout` re-spaced every notch and the floor names drifted.
- **The keyboard is the other way Home Assistant's page moves** (#834): the scroll guard never heard the visual viewport's shift and the header stayed under the island.

## ⚙ is a list of sections, each saying what it is set to, and nothing in a section folds away

- ⚙ has failed three ways. It was a 640px dialog that was one flat scroll — **5,910px at 390 and 3,837 at 1,200**, a paragraph under nearly every control — so the commonest visit (change the model, read the budget, see whether the login works) meant scrolling past corpus capture and the rehearsal. Then eight disclosures, with each section's rarer half in a nested `.setsub`. Then a page of eight panes on Insights' segmented control, which on a phone was a `<select>` hiding seven of its eight names, with the model picker inside Usage's *Advanced* fold, the Ask tab's settings inside Permissions' *Advanced* and the deep check inside Diagnostics' *Developer* — the owner's words were *"really bulky, hard to navigate sections, stuff is buried under collapsible sections"*.
- It was **ten sections on a list** (Account, Model & usage, Permissions, Notifications, Cameras & calendars, Personality, Instructions, Diagnostics, Developer, Guide) before Features became the first section and Dashboard joined while the dashboard is on.
- A phone opens on the list every visit because remembering a section there puts every other one two presses away, which is what the select did.
- `loadDeveloper` was split from `loadAdvanced` so opening Diagnostics no longer reads Developer's.
- Every dropdown in ⚙ once zoomed an iPhone into the ingress iframe.
- **One visual system and a search** (the 2.18.6 pass, after *"the settings page still is really ugly… the toggles under help develop brAIn aren't using space well"*): the switches under Help develop brAIn had been 700px from their own names.

## Each thing in ⚙ is said once, in plain words

- #555–#557.
- Permissions: the second switch was **No restrictions** (its key is still `yolo_mode`), with no heading over it repeating it, and its line said how it goes further than acting without asking. It became the No limits step of one scale (#1045–#1050).

## A page that opens on a pile of controls hides the one answer the owner came for

- #1045-#1050. #665 nudged the same panes and the house still saw the problems, so these were redesigned.
- **A test screen opens with one sentence, and its numbers sit behind one Details fold** was its own bullet (#881) before this one said the same for Diagnostics and Developer; it is folded in here.

## ⚙ › Features is the first section and holds the four switches; nothing is switched in two places

- `tests/test_learning_switch.py`. The add-on option `learning` was a second gate over half of the learners before the switch folded it in.
- `identity()` used to carry the voice with Personality off, so card prompts and `self_said` kept quoting it.
- `#setDevloop` moved here from Developer with its handlers. ⚙ › Dashboard is Morph's old Settings page.

## Every prompt brAIn sends Claude is readable and replaceable in place

- `tests/test_instructions.py`.

## Who brAIn is in this house is brAIn's, and the file is the wire

- **The persona reached only Ask and voice, and growth could not change anything** (the owner: brAIn *"is not improving its personality, really doesn't feel alive or real"*): everything said unprompted was written by analyst prompts with `speak` pasting the name over "brAIn", and a prompt was handed the newest ONE self note cut to 200 characters.
- The household's chosen personality lived in Morph's own code (a copy of `frontend/personality.js` holding `PERSONA` and `GROWTH`) and was shown only in Morph's Settings — *"not every person who uses these apps are going to use Morph, but they have to use brAIn"*.
- **It never raises out of startup**: a persona holding an emoji written as JavaScript's pair of `\u` escapes was read as two lone surrogates that UTF-8 cannot hold, so the write raised `UnicodeEncodeError` and the rest of that boot (`features.ensure`, the terminal prompt, the mirrors) was skipped.
- **A name in a comment is not the assignment**: `// GROWTH: entries below` failed the whole import.
- **A PERSONA object is read whole**: it kept only the top-level strings, so traits, voice rules and a nested description (lists and objects) were dropped and a house's persona came out two lines long.
- `repair_from_morph`: `tests/test_personality_rich_import.py`. **Being a subset of a fresh read is not proof that nobody edited it**: a deleted section came back on every restart, with the voice and each growth entry's `at`/`by` wiped by the replacement.
- `prompt_block`: a second cap on the persona showed up as a cut-off persona.
- **`/config/CLAUDE.md` follows a save** (`tests/test_personality.py::TestClaudeMdFollowsASave`): its personality section kept the old words until a restart or the next memory filing, because the routes rewrote only the terminal's appended prompt.
- **The page draws the persona as the outline it is**: it was shown as one raw box and listed as *"Juniper · line: The evening star…"* — the owner: *"still looks clipped … bring back the rich formatting / sections"*. A 60% floor showed a persona cut at 2,100 characters as whole.
- Tests: `tests/test_personality.py`, `tests/test_personality_sections.py`.

## With Personality on, the page says the name and never "brAIn"

- The word match was a plain split/join.
- **A new name is said over brAIn's own words, never over a person's** (`tests/test_personality_page_words.py`): `applyName` used to re-speak the page by replacing the OLD name with the new one, so a member of the household who shares the old name had their own words rewritten.

## A box's placeholder, label and tooltip are the page's words even where its value never is

- #884. `speakAll` returned at a `textarea`/`input` before it read the element's attributes, so every placeholder present when the name changed (Ask's, Knowledge's) kept saying brAIn; only a later write to the attribute reached the observer. Morph's `speak` skipped a whole `<textarea …>…</textarea>` including its opening tag.

## The house changes brAIn's own page by adding to it, never by editing what ships

- The owner was promised that YOLO lets brAIn change its own header, and it could not: the chat and the terminal run as `claude`, the page is `/opt/panel`, and Morph's house copy has no twin here. Making `/opt/panel` writable or adding an option was ruled out.
- `tests/test_house_ui_overlay.py`. **A bad house change is undone by the page, with nobody pressing anything**: `tests/test_house_auto_undo.py`. "Nothing hides the header on purpose any more."
- **A house copy of something brAIn now ships is hidden and said once** (#835, four times in one house: an update brought what house.js had already added and the page showed both until the owner complained).

## Ask's first screen on a phone has a message box

- #796. The list page was only chats, and the box lived inside an open transcript, so a person who opened Ask to ask something found nothing to type in.

## What brAIn remembers has one home, and ⚙ is not it

- ⚙ › Memory held the memory document and its filing queue while Memory › Knowledge held the facts, and the owner: *"I see memory in the brain settings, but then there is all the stuff in the knowledge tab… no idea what the difference is."* The document and the queue first became a fold at the top of Knowledge, and then moved inside the Tools fold (#883).
- Moved, not dropped: `measure-knowledge`'s list of things cut from Knowledge lost *Memory document*, *Waiting to be filed* and *Export* (they are back).

## Knowledge opens on the facts; upkeep is one Tools fold

- #883.
