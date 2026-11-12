# BRUH Print: history moved out of docs/notes/bruh-print.md

## There is no CUPS in the container, and that is the design

The first cut left out `ESC c/d/e/g` (density) and `ESC h`/`ESC i` (text-speed / barcodes-and-graphics mode) on the theory that a byte sent to the wrong firmware is a wedged printer rather than a lighter label — and what shipped was every label printing at the printer's own defaults, which is the fast mode at normal density, and on ordinary thermal stock that reads as faint. The complaint was the labels, not the theory, so

A label is mostly white, so replacing each repeated blank line with one byte took a 375-line label from 31,886 bytes to 474 — of which about 370 were `ETB`, the one opcode in `protocol.py` written from memory rather than from something unambiguous. A firmware that does not read `0x17` as "repeat the previous line" gets a valid preamble and then 370 bytes it cannot use, and prints nothing: **there is no error to report, because the bytes were accepted** — the write returns its count, the status read answers, and the panel says `Printed 1 on the left roll`. The saving is real and it is three milliseconds of USB 2.0, which is not worth a guess.

It was called "a no-op by construction — the renderer already knows where the left edge is", which mistakes *our* state for the *printer's*: the manual says

## Read the manual. Three of this file's bytes were written from memory and all three were wrong

We sent binary 1 and 2, so on a Twin Turbo roll select may have been a no-op, which with two different stocks loaded means labels on the wrong-size roll and reads as bad alignment.

- **Four knobs could not answer where the printing starts, and the printer had already written the answer down.** The third report of "they aren't aligned" was the first one measured, and the measurement is why this is a feature rather than a fourth guess: a ruler printed through the real renderer and the real printer came out 672 × 375 dots with its ink inset **exactly 24 dots on all four sides**, and the photograph — deskewed against the printed ruler's own 5mm ticks, the one scale in the picture that cannot be wrong — read 18.26 px/mm across and 18.36 down against a die cut at 18.32 and 18.20. The renderer and the wire bytes were **proved correct before anything was changed**. What was left was one number: top margin 9.9mm where it should have been 5.2, bottom 0.3mm — the printer begins laying ink **4.7mm after the leading edge**, every label, with the last 4.7mm of the raster running off the end into the gap. 0.6.0 answered that with a signed feed and across offset, 0.7.0 added a lateral media position and a die-cut gap beside them, and 0.8.x had four boxes with four signs and four meanings and no way for a person holding a wrong label to tell which one was theirs. The owner printed, measured, typed, printed again, and asked for them to go. **They were right, and `gap_mm` is what proved it**: it was plumbed correctly, it changed the bytes, and it moved nothing — which is an answer and not a null result, because it means the printer *is* finding the sense hole on this roll and positioning every label relative to it. `ESC L` was only ever the maximum search distance the manual says it is. Three primary sources settle the rest: the manual's top of form is "the inter-label gap over the cutter bar", **beyond the head**, and a form feed "places the next label beyond the starting print position. Therefore, a reverse-feed will be automatically invoked when printing on the next label"; DYMO's own CUPS driver sends 156 `ESC` bytes as a reset, `ESC q` once per *document*, `ESC L` as the exact page height, blank rows as `ESC f` skips, `ESC G` per page and `ESC E` per document; and DYMO's PPD for the 2¼″ × 1¼″ label declares 1.5mm unprintable at each feed end. So a 4.7mm band is not firmware behaviour on DYMO stock — it is **this roll's hole sitting where DYMO's does not** (every label starts late, and no command reverses paper) or **the reverse feed after a tear-off not happening** (the first label of a job and nothing after it), and only a two-copy print tells them apart. Nothing typed into a box can.

## So the four knobs are one `Calibration`, and every field on it is measured

A **5mm pre-skip** was added on the theory that it made a negative start measurable and it did the opposite — the skip pushes the ladder's 0 further down a band that is blank either way, so both signs read 0 at the top and the one number that separated them was the one nothing printed; it also lengthened the sheet past one label, which lands copy 1's tail on copy 2's leading edge, where the second copy's top is read.

## The instrument is a label and it was rebuilt once, from its own rendered bitmap

Its first version put the copy number and the across ruler in the top 14mm and started the feed numbers at 15, which is exactly the band the top reading is taken in on the roll it was built for (9.7mm) — so a 4.7mm dead zone would have been typed in as 10, and the across ruler's own "0 5 10" sat where somebody would look for a feed number.

- **The question is where the printable area is, and every release up to 0.9.1 asked it as an OFFSET** (`panel/calibration.py`, `server._calibration_label`). That is the failure under all of them, and it survived two rewrites that were each about the right thing. 0.6.0–0.8.x answered a misaligned label by adding a box to type a millimetre into until there were four with four signs; 0.9.0 replaced them with one measured `Calibration`; 0.9.1 rewrote the instructions for reading it. None of them changed the shape of the question, which was *how far is raster row 0 from the die cut, and which way* — **and a distance-with-a-direction is not a thing drawn on a label**. It has to be inferred, from which end of a ladder got cut and from one copy compared against another, and the sign is exactly the part nobody can see. Hence three hypotheses that are identical from a photograph, six readings, two prints, and two of the six read from the opposite end of the label to the thing they were about. No wording could reach it: the instructions were vague because the question was.

## A rectangle IS drawn on a label, so print a grid over the whole printable area and read the four coordinates of the paper on it

`X1`/`X2` across

## The sheet is ONE label and longer than the label, and the overrun is the instrument

(`gap_mm` was plumbed correctly, changed the bytes and moved nothing, which is the measurement proving this printer *does* find the sense hole)

## Lining a roll up is a LOOP, and 0.10.0 shipped it as a form

The only route from a wrong reading back to a printed label was to close the dialog, find the bay, press a button on the card and re-open the wizard to an EMPTY form — so a millimetre out meant reading all four coordinates again.

## A printable area somebody CHOSE is a different claim from the paper's edges, and one field could not hold both

**0.11.0 shipped ONE of them — the trailing band — and the argument for that was wrong in a way worth writing down**: it said the printer starts where it starts, so the only band worth having is the one that evens out a late start, and asking for more at the top would only push the artwork further from centre. True of the feed axis, and it answers the wrong question — a person setting a border is saying where on the label the printing goes, not compensating for a machine, and the across axis has no dead band to compensate for at all.

## One rectangle, and the designer draws it rather than drawing around it

Four things used to be drawn on the canvas to aim away from — the stock's own `margin_mm` as a tinted band, a dashed rectangle inside it, a hatched strip where a 2.25" label overhangs a 2.24" head, and a hatched band at the leading edge this roll cannot reach — plus the held band beside it. Each was honest and each asked the same thing of a person: lay a label out, then move it off the parts that were never yours. They are

(the margin, the dead band, the head's shortfall, the four holds)

A caption survived that removal for two releases — `Drawing on 34 × 12.4mm of a 50.8 × 25.4mm label` — and it was the same shape of answer one layer up: two measurements with no relationship between them, where what makes them differ is a margin, a lined-up roll and any held edges, none of which is on that tab. So it could only raise the question it could not answer, on a line read every time the designer opens. The picture is the printable area, which is what the caption was there to say.

## The head is 672 dots whatever is loaded, and nothing knew where narrow media sits on it

A solid fill on the 0.56" wrap printed across **49% of the label** — measured off the photograph, 335 inked pixels of a 687-pixel label, ink starting 0.7mm in from one edge and stopping dead — while the 2.25" stock was perfect.

**And the 0.6.0 across offset could not express the fix, which is why the reporter's "I try and try and it doesn't do anything" was exactly right**:

## Printing is a service call, and the card gated it on the sensors

— which is how 0.4.0's "say what is missing" block turned into a card that could not print at all

— driven against the shipped card, the add-on answering `printed: 0` with the note "The printer did not answer." produced **`Printed 1. The printer did not answer.`** in green.

Twenty-one of these were reproduced as failures against the shipped card before anything was changed, which is the only reason to believe the tests hold them.

## A control that needs a tooltip to have a purpose gets a name instead

; Swap became `Swap to 1.25" × 2.25"`, which named the numbers and still explained nothing — a person reading it asked what the whole across/along business was for — so it is now a sentence in the Edit dialog, `These are the wrong way round`, under the two measurements labelled in words, where the thing it exchanges is on screen

## Every URL the panel emits is relative, because ingress mounts it under a prefix

0.1.1 shipped three absolute asset references and twenty-odd absolute `fetch` calls, which reached a real install as unstyled HTML with all five views stacked down the page and every preview a broken image — the CSS, the JS and the whole API 404ing together.

that convention was already in the repo and reading it was the whole job

## Nothing says it is listening above the call that would make it so

— which is BRight's `panel_port` bullet word for word, repeated in a new add-on by writing the obvious line in the obvious place

## A text box is fitted and placed by its INK, and the margin is 2mm

Measured on "Rice" in a 40 × 12mm box: 0.60 of the height before, 0.96 after.

## The designer previews the CANVAS, and everything else previews the sheet

For as long as the designer existed, a turned label put the box being held and the ink it described in two different places; latent while `rotate` was a select nobody touched, and reachable the moment every new label on a wrap stock took 90° from its stock.

## The Lovelace card is registered under a URL that changes with the file

and for two releases that was a fix to the wrong layer

## Nothing had ever executed the card, which is why it shipped broken twice

It was verified against the old behaviour first — reverting the trouble block produced fifteen failures — and it runs in CI's `layout` job.

## The panel was built at 1440px and used at 390px

Measured on the demo panel at 390 x 780 — an iPhone once Home Assistant's own header has taken its share — the top bar was **247px, a third of the viewport, before any content**: a `.wordmark` duplicating the host header one row above it, three status chips totalling 497px in a 362px row (so they wrapped) that **all three called `show('printer')`**, and tabs on a second row. `.design-bar` was another 269px in five rows, putting the canvas at y=590 with 166px of height; on Quick the `.preview-frame` began at **y=899, below the fold**, on the one tab whose whole purpose is type, look, print.

Chrome above content 247 -> 153px, pinned chrome 247 -> 96px, the design bar 269 -> 62px, the canvas top 590 -> 279, the Quick preview 899 -> 362.

## A control that is a mode does not deserve a slot on a phone's primary row, and `⌗ Snap` was both

`⟳ Rotate` moved the other way, into the props pane: it acts on the *selected element*, and every other per-element control already lived there (it sits with Duplicate and Delete — see the bullet on the three named rows).

## A word is what a tab is called, and five glyphs beside five words needed 485px

Measured on the real strip: at 390px the five tabs came out on two rows and at 320px on three — a third of a phone screen spent on navigation, above a tab whose whole job is type, look, print.

## A roll's name is somebody's, and nothing on the screen said so

**Showing the name on the design bar's picker button was tried and measured and reverted**: the bar is one flex line whose base sizes are the controls' own content, so a picker wide enough for a name pushes the add strip onto a row of its own — one row to two at 900px, two to three at 390px, 52px of chrome above the label being designed. 147px is what that row has.

## A picker answers "which of my rolls is this", and it was answering "what size is it"

`designStockFits`' row-count check caught it one release after it was written, which is the only reason that is a paragraph here rather than a shipped regression.

## A service mapped onto a route that only prints when told to is a preview with a green tick

`tests/test_bruh_print_services.py` drives the bridge into a real panel and asks the stand-in printer, not the mapping.
