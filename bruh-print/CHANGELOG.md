# Changelog

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
