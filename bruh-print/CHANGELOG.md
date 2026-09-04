# Changelog

## 0.6.0

**The renderer was right, the wire bytes were right, and the labels were
still landing 4.7mm too far down the roll.** That was measured before
anything was changed, which is the only reason this release is a new feature
and not a fourth guess.

The same ruler label was printed through the real renderer locally and
through the real printer. The rendered bitmap is 672 × 375 dots with its ink
inset **exactly 24 dots — 2.03mm — on all four sides**: symmetric, correct,
nothing to fix. The photograph of the printed label was then deskewed and
measured against the printed ruler's own 5mm ticks, which is the one scale in
the picture that cannot be wrong:

- **Scale is right and isotropic.** 18.26 px/mm across the ticks and 18.36
  px/mm down them, against 18.32 and 18.20 px/mm on the label's own die cut.
  300 dpi across the head and the graphics-mode line doubling down the feed
  are both landing. Nothing is stretched, squashed, doubled or halved.
- **Nothing is clipped.** The printed box measures 46.6 × 21.4mm and carries
  exactly ten across ticks and five down ones, which is what the ruler emits
  for a drawable area of about 46.8 × 21.4mm. The whole artwork is on the
  label.
- **One defect, and it is vertical placement.** Left margin 5.2mm, right
  5.5mm — horizontal registration is fine. Top 9.9mm, bottom 0.3mm — both
  should have been 5.2mm. The printer begins laying ink **4.7mm (0.185",
  about 55 dot lines at 300 dpi) after the leading edge**, and the bottom
  4.7mm of the raster runs off the end of the label into the gap. It happens
  to be blank margin there, which is why nothing looked cut off.

That is top-of-form registration: a physical property of one printer and one
roll, which this add-on has never had any way to express.

**So a stock now carries a print offset**, signed, in millimetres, on both
axes, defaulting to 0.0 so nothing changes for anyone who has not measured
theirs. It is applied to the rendered sheet on its way to the printer and
nowhere else: the label, the preview and the design canvas are untouched,
because the offset is a correction to where the machine puts the paper and
not a change to anybody's layout. A shift that slides blank margin off one
edge costs nothing and says nothing; a shift that would push real **ink** off
the label prints anyway and comes back with a note saying how much, past
which edge, and which control to change — this add-on refuses a print for
exactly one reason and this is not it.

**The manual documents a feed-direction print-position command, and it is
deliberately not what this uses.** `<esc> f 1 n` Skip "n" Lines is real,
unambiguous and in the printer's own steps — and it only ever moves paper
*forward*. The fault measured above is a printer starting **late**, whose
correction is a negative skip, which is not a thing. Using `ESC f` for one
sign and a raster shift for the other would also give one control two
behaviours at the sheet's edge: a skip pushes the tail of the raster past the
die cut into the gap, where the manual is explicit that the printer does not
check, while a raster shift keeps the sheet exactly one label long — which is
what lets the add-on see the ink it is about to lose and say so. The across
axis had the same choice and the same answer: `ESC B n` moves in whole bytes
of eight dots (0.68mm a step, against a fault measured in tenths), is
likewise one-directional, and is already sent as `ESC B 0` in every preamble
to clear whatever another driver left in the printer — which it could no
longer do if it were also carrying a per-roll correction. One mechanism, both
axes, both signs, rounded to whole dots exactly once.

**And a number you have to guess is a number you guess wrong, so there is
something to measure with.** The ruler could not do this job: it is drawn
inside the stock's margin, so on the roll in question there was nothing
within 5mm of the die cut to measure against. The new **calibration label**
is drawn to the full sheet with the margin ignored, with two thick rules
meeting at the exact corner where the raster begins and 1mm ticks running
along each of them. You hold it up, read the gap between the label's own edge
and the thick line, and type it in with a minus in front. The sign is spelled
out in words on the label, in the dialog and under each box, because nobody
knows which way "+" goes on a label printer. Saved offsets are applied to the
calibration label too, so printing it again is how you check a correction
worked. It lives beside **Print the ruler** on the Printer tab, as **Where
the printing starts** — two questions, two labels, neither of them merged
into one that answers both badly.

**The margin is on screen now.** The roll in this report carried a 5.2mm
border where the shipped default is 2.0 — almost certainly typed in by hand
to compensate for the misregistration above, since the panel offered nothing
else — and it was visible nowhere: the artwork simply came out small and
floating in white. It rides on the stock row beside the two measurements, and
the Edit dialog asks for it in words as *the blank border kept clear of the
edge*, next to the two measurements rather than as a bare "Margin (mm)" at
the bottom, and says how much of the label the artwork actually gets. Nobody's
saved value was changed.

## 0.5.0

**Three of the bytes this add-on sends a printer were written from memory
rather than from the manual, and all three were wrong.** DYMO publishes a
LabelWriter 450 Series Technical Reference. It was read properly this time,
and it contradicts what the code believed in three places — two of which
produce exactly the reported symptom: labels printing out of alignment.

**`ESC L` is not the length of the label.** The manual: *"nl, n2 = number of
dot lines **from sense hole to sense hole**"*, and *"this command indicates
the **maximum distance the printer should travel while searching for the
top-of-form hole or mark**. **Print lines and lines fed both count towards
this total**."* It is a search budget, hole to hole — not a length. BRUH Print
sent the height of its own raster, which is wrong twice over: hole-to-hole is
the label *pitch*, which includes the inter-label gap, and because printed
lines are charged against the budget, printing a full label exhausted the
entire allowance at exactly the moment the artwork ended, before the sense
hole it was supposed to reach. The search gave up short on every label and the
error accumulated down the roll. It is a real budget with headroom now, and
**continuous stock finally gets the mechanism the manual gives it** — a
negative length selects continuous-form mode, where the form feed advances far
enough to clear the tear bar, which this add-on had never sent.

**The dot tab is state inside the printer, and we never set it.** The manual:
*"Both the dot tab variable and the bytes-per-line variable are **held by the
control electronics until they are changed by a new command sequence or are
reset to default values by a power-on reset or a software reset**."* BRUH Print
deliberately did not send `ESC B 0`, on the reasoning — written in this
repository, in as many words — that it was "a no-op by construction". It is
not: the dot tab is not something our renderer controls, it is a value the
printer keeps. Anything that ever set it, DYMO's own software included, leaves
it set, and every label after that starts that many bytes to the right. The
preamble states where the line begins now instead of inheriting a stranger's
answer.

**And roll select was sending the wrong kind of number.** The manual is
explicit, and deliberately so — every other parameter it documents is plainly
binary (`ESC D n`, *"1 <= n <= 84"*), while this one spells the encoding out:
*"30 (ASCII '0') = Automatic selection, 31 (ASCII '1') = Left roll, 32
(ASCII '2') = Right roll"*. BRUH Print sent binary 1 and 2. On a Twin Turbo
with two different stocks loaded, a roll select the printer does not recognise
means every label goes to whichever bay was last used — which is a label
printed on the wrong-size stock, and looks from the outside exactly like bad
alignment.

> **Worth checking after this update:** the roll byte is the one change here
> that could *regress* a Twin Turbo whose bays work today. It is what the
> manual says and it has not been tested on hardware. Print the ruler from the
> Printer tab and check which bay it comes out of.

What the manual **confirmed correct** and is unchanged: the 300 x 600 graphics
mode really does step half as far per dot line, so sending each raster line
twice is right; 84 bytes per line is 672 dots, the width of the head; and the
density commands are what made labels dark.

**The Lovelace card could not print, and 0.4.0 is what broke it.** The card
gates Print on finding its sensors — but printing is a *service call*, and the
service exists whenever the integration is loaded, whatever the entities are
named. A renamed device, a renamed entity or a second BRUH Print gave a card
that could not print at all, on a printer that was working. Those are two
different questions and they are asked separately now: the service decides
whether Print works, the sensors decide only whether the card can show what is
loaded — and when it cannot, it says which of the two is missing and names the
`printer_entity` / `left_roll_entity` / `right_roll_entity` options that point
it at renamed ones. Those options existed and were documented nowhere.

**And the card announced prints it was never told about.** It reported
`printed || copies || 1`, so a service call that came back with nothing to say
rendered as *"Printed 1"*. Driven against the shipped code, the worst case was
the add-on answering `printed: 0` with the note "The printer did not answer."
and the card rendering **"Printed 1. The printer did not answer."** as a green
success. It reports what actually came back now, and an unconfirmed print says
so.

Twenty-one of these were reproduced as failures against the shipped card
before anything was changed, in a real browser.

## 0.4.0

**The card was not being served at all, and nothing could have said so.**
Home Assistant registers the `/local` folder only if `/config/www` already
existed when Home Assistant *started* — it is one `os.path.isdir` in core's
frontend setup. The add-on creates `/config/www/bruh_print` when the **add-on**
starts, which on any ordinary install is afterwards. So on a house that never
had a `/config/www` — and you only have one if you already installed a custom
card or HACS — `/local` is not a route on that run, **every** request for the
card is a 404, and the dashboard shows Home Assistant's own "Custom element
doesn't exist: bruh-print-card". Restarting the add-on cannot fix it. Only
restarting Home Assistant can, and only once.

Hashing the card's URL in 0.3.0 could not have helped: the whole prefix was
missing. And the integration checked that the *file* existed — which passes
happily — so it registered a URL it had no reason to believe was reachable,
the one thing that function's own comment claimed to prevent.

BRUH Print now asks the running server whether `/local` is served and raises
a **repair** naming the single restart that ends it, clearing itself once the
check passes. It fails open everywhere: a diagnosis may never become a gate
that stops a working card from registering.

**And the card can now say when it has nothing to work with.** With no
integration, or the add-on stopped, it drew a text box, a Print button that
failed with a service-call error, and a status pill reading *ready* — the one
sentence it had lived inside the rolls block, so turning the rolls off turned
off the only explanation. It names what it went looking for whatever
`show_rolls` says, carries its own version so a screenshot answers "which card
is this", and stops offering a button that cannot work.

**Nothing in this repository had ever executed the card**, which is why that
shipped twice. `measure-print-card.mjs` loads the real card into a browser and
fails on a missing explanation, an enabled Print with nothing behind it, a
`side` reaching a service call, or a target under 44px. It runs in CI.

**The panel was built for a laptop and used on a phone.** Measured at
390 x 780 — an iPhone once Home Assistant's own header has taken its share —
the top bar was **247px, a third of the screen, before any content**: a
wordmark duplicating the header directly above it, three status chips totalling
497px in a 362px row so they wrapped, and tabs on a second row. The design bar
was another 269px in five rows, so the canvas began at y=590 and got 166px. On
the Quick tab the preview began at **y=899 — entirely below the fold**, on the
one screen whose whole purpose is type, look, print.

Now: the wordmark goes on a phone (the host header already says it), the three
chips become the one control they always were — all three opened the Printer
tab — the status row scrolls away while the **tabs stay pinned**, and the
design bar is a single row. Chrome above content **247 -> 153px**, pinned
chrome **247 -> 96px**, the design bar **269 -> 62px**, the canvas top
**590 -> 279**, and the Quick preview **899 -> 362**, with Print on the same
screen. The Printer tab also stopped scrolling sideways at 390px: a `<select>`
sized to its widest option was setting a 413px floor for a 390px window.

**"What is snap?" was a fair question.** A `#` glyph and a verb with no object.
It is a mode you set once, not an action, so it has left the phone's primary
row for the label-setup sheet as **"Line boxes up as I drag"**, with a sentence
saying what it does. **Rotate** moved into the properties pane beside align and
nudge, where every other per-element control already lives.

**And the prose that cost a row every time you looked at it is gone.** Each
lede was judged on its own: deleted where the control beside it already said
the same thing, shortened where it carried one fact, and kept where the fact is
available nowhere else — the Printer tab still says a LabelWriter cannot tell
what stock is in it, because that is why the feature exists.

## 0.3.0

**The Lovelace card never updated, and the card you were looking at was the
0.1.0 one.** Home Assistant serves `/local` with a 31-day cache header, and
the integration registered the card at a fixed URL — so the add-on rewrote
the file on every start and no browser ever fetched it again. Two releases
on, dashboards were still running the first card, with its roll dropdown and
its lab placeholders; and that card's `side` is exactly what the current
panel refuses when the stock is loaded in the other bay, which is why it
"could not print". The card is registered under a URL carrying a hash of the
file's own bytes now, so an update reaches the dashboard on the next page
load. One refresh is needed the first time, because the *old* URL is the one
your browser cached — after that, never again. The integration also keeps
looking for a card that is not there yet rather than giving up until the
next Core restart, and the card's own version string is tested against the
add-on's.

**Labels print dark now, and slowly by default.** The driver deliberately
sent no density or print-quality command, leaving the printer at its fast,
normal default — which on ordinary thermal stock comes out faint. Standard
and compact modes send `ESC g` (dark) and `ESC i` (the printer's
"barcodes and graphics" mode, 300×600) in the order cups-filters has sent
them for twenty years. The slow mode steps the paper at 600 lines an inch, so
every raster line goes twice and the label length doubles with it — sent
as-is the label would come out half its length. **Darkness** and **Print
speed** are on the Printer tab under Settings; **Bare minimum** still sends
neither, for a firmware that will not take them.

**One setting for which way the text runs.** It used to be asked in three
places — a Turn picker per stock, a Turn on the Quick tab, a Turn in the
designer — plus a `Swap to 1.25" × 2.25"` button nobody could parse. Now each
stock has one **Text direction** (automatic reads the shape, and the closed
picker says what it decided), the Quick tab and the designer both follow it
and say so in a sentence, and nothing asks per print. The measurements moved
into an **Edit** dialog per stock with the two numbers labelled in words,
**"These are the wrong way round"** where Swap was, a **Margin** and the
labels-per-roll count. The designer gained **⟳ Rotate** for turning a text
or barcode box a quarter at a time.

**Text is fitted and placed by its ink, inside a 2mm margin.** The autofit
measured advance widths and the font's line box — neither is where the ink
is — so a word could touch the edge and fill barely half its box at the same
time. Measured: "Rice" in a 40 × 12mm box filled 0.60 of the height before
and 0.96 after, centred within half a dot where it was eight off. The margin
was 1mm, which on a LabelWriter whose registration wanders and whose head is
three columns short of a 2.25" label meant text at the die cut. It is 2mm by
default (a stock you corrected keeps its own), the designer draws the
printable area with the margin tinted and the clipped columns hatched, and
every text box keeps a little breathing room inside itself.

**The designer is a tool you can aim with.** Boxes snap to the printable
area's edges and centres, to each other and to a 1mm grid, with a guide line
drawn at whatever they caught; text re-fits *while* you drag a corner rather
than after you let go; nothing can be dragged, typed or nudged off the label;
a box that cannot be drawn — a barcode too narrow for its data — is outlined
in red; and there are align, fill and nudge tools for a thumb. **The font
picker shows the fonts**, each row drawn by the label renderer itself. Two
bugs found by driving it: selecting a box rebuilt the overlay under the
finger holding it, so a drag never worked from the first press; and a 90°
label was previewed as the printed sheet under an overlay laid out for the
design canvas, so on a tube wrap the box you held and the words it described
were in two different places. The designer previews the canvas now.


## 0.2.2

**"Ask the printer" could only ever say it had nothing to report**, and the
reason was on this side of the cable.

`config[(0, 0)]` — interface 0, altsetting 0 — is the interface this add-on
printed through, hardcoded. The USB printer class defines two protocols and
devices routinely expose both as *altsettings* of one interface: `01`
unidirectional (bulk OUT only) and `02` bidirectional (OUT and IN).
Altsetting 0 is very often the unidirectional one — so there was no endpoint
to read from, no question was ever sent, and the panel reported the printer
as silent. The printer was fine.

BRUH Print now walks every interface and altsetting and prefers one with both
directions, falling back to one that can at least print. **Which one it
chose is reported rather than decided silently**, because a choice nobody can
check is a choice nobody can correct — and this one was wrong for two
releases with no way to see it.

**The two silences no longer share a sentence.** "No status reported" meant
both *the printer did not answer* and *there is no channel to ask on*, so a
person read it and went to check hardware that was working. They are now
"asked, but the printer did not answer" and "no read-back channel on this
printer, so it cannot be asked — printing is unaffected". Neither is ever
rendered as ready.

**And the lab vocabulary is gone.** This prints labels for a house, and it
was written as though it printed them for a bench: `Buffer A pH 7.4` in every
placeholder, a "Cryo vial" template, a "Sample id" field, a "reagent name" in
the docs. The examples are a chest freezer, a freezer bag, spare keys and a
pantry jar now. The two stock *names* stay as they are — "Chemical-Resistant
Cryo Labels" is what is printed on the roll and what you would reorder by.

**And a USB details button**, beside Print the ruler. Interfaces,
altsettings, endpoints, and which one is in use. This add-on has now been
debugged twice by somebody standing at a printer reading a panel that could
not say what it had found — and USB descriptors are always readable, even
from a device that answers nothing. Worth copying into a bug report.

Note what this does **not** claim to fix: printing. A unidirectional
altsetting prints perfectly well, so if labels are still not coming out, the
0.2.1 note below is the live one and the **If nothing comes out** setting is
still the thing to work through.

## 0.2.1

**It said it printed and nothing came out.** Every layer reported success —
the bulk write returned its byte count, the status read came back, the panel
said "Printed 1 on the left roll" — and the printer produced nothing.

A 375-line label went down the wire as **474 bytes**. About 370 of those were
`ETB` (0x17), which this add-on assumed means "repeat the previous line". A
label is mostly blank, so nearly the whole job was that one opcode — and it
is the one opcode in `protocol.py` written from memory rather than from
something unambiguous. A printer that does not read 0x17 that way receives a
valid preamble followed by 370 bytes it cannot use, and prints nothing. There
is no error for it to report: the bytes were accepted.

**Compression is off by default now.** Every row is sent as its own `SYN`
line, which is what cups-filters' DYMO path has printed with for twenty
years. The same label is 31,886 bytes — under three milliseconds of USB 2.0.
That is not a saving worth a guess.

`ESC B 0` (dot tab) is gone from the preamble too. It was a no-op by
construction — the renderer already knows where the left edge is — and a
no-op in a preamble is pure risk: a firmware that does not take the command
may swallow the byte after it and desync everything that follows.

**And a setting for the part that cannot be tested from here.** Whether a
given LabelWriter firmware accepts every command in the preamble is not
something an add-on in a container can find out, and a printer that takes a
job and prints nothing is otherwise a guessing game played one release at a
time. **If nothing comes out** (Printer tab → Settings) offers three shapes:

- **Standard** — the new default; what everything is tested against.
- **Compact** — adds the `ETB` compression, for a printer that understands it.
- **Bare minimum** — also drops roll select, which costs a Twin Turbo its
  second bay. The last thing to try.

Change it, press **Print the ruler**, and tell us which one worked.

The tests that were supposed to hold this asserted the compression *happens*
— they pinned the bug in place. What replaces them walks a finished job the
way a printer would, knowing only `SYN` and the escape commands, and fails on
any byte such a reader cannot use. Against 0.2.0 it reports
`byte 98 is 0x17, which a printer that knows only SYN and the escape commands
cannot read`.

## 0.2.0

**You pick the label. BRUH Print remembers where it is.**

A roll is not a thing anybody wants to choose — it is where a label happens
to be, which the add-on already knows. Every roll picker outside the Printer
tab is gone: from the Quick tab, the designer, the templates, the Lovelace
card and the four print services. Naming the stock has already named the bay,
and two ways to say where a label goes is one way to contradict the other.

The services still *accept* `side`, quietly and undocumented, so an
automation written against 0.1.2 does not start failing validation. Nothing
offers it. `set_roll` keeps it, because saying what is loaded is a statement
about a bay by definition.

**Only what is in the printer can be picked.** The full catalog is fourteen
rows of which two are real; offering it on the Quick tab made the commonest
first action a choice between twelve wrong answers and then a refusal for
picking one. The catalog lives on the Printer tab, where the question is
"what did I just load". Everywhere else the picker can only be right. A
printer with nothing recorded still offers everything — an empty picker is a
panel that looks broken.

**Each stock remembers which way its labels read.** A 0.56 × 3.44 cryo wrap
reads along the roll and a 2.25 × 1.25 label reads across it — always, for
that stock. That is a property of the label, not of the job, so it is stored
per stock and switching labels switches the turn with it. Set from the
Printer tab, where "automatic" says what it decided rather than leaving you
to print one to find out. Swapping a stock's dimensions re-derives it, since
the shape is what the guess reads.

The old global "turn text along the roll on tall, narrow stock" switch is
gone: one setting cannot answer for stocks that disagree with each other.

**The remaining count is a control, not a readout.** Press the bar and type
what is really left — the number is an estimate that drifts the moment
somebody prints from another machine, and a number you can see and cannot
correct is a number you stop reading. Or turn it off: **Keep an estimate of
how many labels are left** hides every bar and stops the count. Hidden and
still counting would be worse than not counting, because turning it back on
would reveal a number that has been quietly wrong for a month — so the gate
is one method every print path goes through rather than five call sites
remembering to ask.

**On the card, the rolls are the selector.** Tap one and that is what prints,
with the chosen one outlined. A single-roll printer draws the same box as a
readout, because a selector offering one choice is not a selection.

**Two buttons that did not say what they were for** now do, on hover and on
focus: **In use / Use this one** (which printer everything prints to, only
meaningful with more than one plugged in) and **Ask the printer**, renamed
from "Check it" — it asks how the printer is right now and prints nothing.
**Swap** names the two numbers it exchanges (`Swap to 1.25" × 2.25"`), so it
is readable without the tooltip; the tooltip explains what the pair means.

## 0.1.2

**The panel rendered as unstyled HTML.** Every view stacked down the page,
the previews broken images, the tabs plain buttons — because `style.css` and
`app.js` 404'd, and so did every API call.

Ingress mounts an add-on panel under `/api/hassio_ingress/<token>/`, so an
absolute `/static/style.css` is a request to Home Assistant's own root. The
page's three asset references and all twenty-odd `fetch` calls were absolute.
They are relative now, and `api()` strips a leading slash the way brAIn's
does — which is where the convention already was, and where this should have
been read from in the first place.

**Serving at `/` is the one arrangement in which that bug is invisible**, and
it is the arrangement the demo panel and the layout measure used. Both now
serve and drive the panel under a prefix, so CI exercises it where ingress
actually puts it. The measure also checks that the CSS and the JS *arrived*
before it drives anything: a page whose stylesheet 404s still lays out, and
every click then times out on a control that was never built — which reads as
a flaky selector rather than as "the panel did not load". Against 0.1.1 it
now says exactly that.

**And the panel was serving its own source tree.** `add_static("/static/",
PANEL_DIR)` meant `GET /static/server.py` answered 200 with the file, as did
every module under `stores/` and `dymo/`. There is no credential in this
add-on and the panel is admin-only behind ingress, so nothing leaked that
matters — but an add-on serving its own source is a mistake waiting to become
one. Four named routes now serve the four files that are actually assets.

## 0.1.1

**0.1.0 could not start.** The panel bound its port, logged "listening on
0.0.0.0:8097", and died on the next line:

    TypeError: access_log_class must be subclass of
    aiohttp.abc.AbstractAccessLogger

`QuietAccessLogger` was a plain class with a duck-typed `log` method, and
`run_app` type-checks the class it is handed. Nothing caught it because
nothing ever handed it to aiohttp: every test constructed it directly, and
the demo panel CI boots called `run_app` without an access logger at all. So
the demo now serves exactly the way `server.main()` does, and there is a test
that runs aiohttp's own check rather than a restatement of it — it fails
against 0.1.0 with the same TypeError, word for word.

**And it said it was listening before it was.** The "listening on
0.0.0.0:8097" line sat above the `run_app` call, so it printed whether or not
the server came up — directly above the traceback proving it had not. That is
BRight's own `panel_port` lesson repeated in a new add-on. The line is now the
callback `run_app` invokes once the site is actually serving; what comes
before it says "starting".

**And the docs were wrong about USB.** They told people to "turn USB access
on in the add-on's configuration", which is not a thing that exists: `usb:
true` is a manifest permission the Supervisor applies when it builds the
container, so the Configuration tab has no switch for it and never did. The
README, DOCS, the startup warning and the panel's own "cannot open the
printer" message all said some version of it. They now say what is actually
worth checking — the power brick, the cable, and whether another add-on has
claimed the printer.

## 0.1.0

First release.

- **A label designer in the sidebar.** Text, Code 128, QR, boxes, rules and
  uploaded images, dragged and resized on the label itself, in millimetres.
  Every preview is the printer's own render — the picture on screen is the
  bitmap that goes to the head, because a preview drawn a second way is a
  preview of the second way.
- **Type a word, get a label.** Every arrangement of the words across lines
  is rendered and the largest wins, so `Buffer A` comes out on two lines and
  `9912` on one.
- **Templates.** `{{field}}` in any text, barcode or QR becomes a box to fill
  in — in the panel, in the card, and in `bruh_print.print_template`.
  `{{date}}` and `{{time}}` fill themselves in.
- **It knows what is in the printer.** Stock per roll, checked before every
  print. A LabelWriter cannot report its own media, so the alternative to
  remembering is a 2.25″ raster printed across a 0.56″ roll's liner, once per
  copy.
- **Twin Turbo roll selection**, gated on the printer's own capability so a
  single-roll model never shows a control that does nothing.
- **The DYMO raster protocol, directly over USB.** No CUPS, no PPD, no
  spooler. `ETB` run-compression takes a typical label from 32 KB to 7 KB.
- **Six services and six entities**, including a `problem` binary sensor
  whose `reason` attribute says what is wrong in words.
- **A Lovelace card** with a text mode, a template mode and one-press quick
  buttons. It reads the sensors and calls the services, so it works through
  Nabu Casa exactly as it does on the LAN.
- **The ruler.** One label with millimetre ticks on both axes — the only way
  to check a stock's measurements are the way round the catalog thinks, since
  the printer never reports what it printed on.
