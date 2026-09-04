# BRUH Print — reference

## Installation

1. Add this repository to Home Assistant, install **BRUH Print**.
2. Start it, and open its panel from the sidebar.

**There is nothing to enable for USB.** The add-on's `config.yaml` declares
`usb: true`, which is a manifest permission rather than a user setting — the
Supervisor maps the host's USB devices in when it creates the container, and
the Configuration tab has no switch for it because there is nothing to
switch. Protection mode does not need turning off either; this add-on does
not ask for the Docker API.

The add-on log's first few lines say what it found on the USB bus, which is
the quickest way to tell the three "no printer" causes apart:

```
[16:04:11] INFO: USB printers: LabelWriter 450 Twin Turbo (0022:01010112345600)
```

## Options

| Option | Default | What it is |
| --- | --- | --- |
| `enable_ha_integration` | `true` | Deploy the `bruh_print` integration and run the bridge |
| `install_lovelace_card` | `true` | Copy the card into `/config/www` and register it |
| `default_stock` | `edcc-082wh` | Which label a new design and a bare `print_text` assume |
| `enforce_stock` | `true` | Refuse a label whose stock is not in the target roll |
| `log_level` | `info` | `debug` also logs successful status polls |

`default_stock` and `enforce_stock` only seed the panel's own settings on the
first run. After that the panel owns them, so changing one there is not
undone by the next restart.

## Label stock

A stock is two measurements and they are not interchangeable:

- **across the print head** — the width the head covers in one pass
- **along the roll** — how far the paper travels for one label

Nothing can work this out for you. A LabelWriter feeds to the next die-cut
gap and has no idea what shape the label it just printed was, so if a label
comes out rotated with the text running off the edge, the two numbers are the
wrong way round. Press **Edit** on the Printer tab and then **"These are the
wrong way round"** — or press **Print the ruler** and hold the result against
a real label, which is the only way to be sure and costs one label.

**Text direction** is one setting, on the Printer tab, per stock. A label
much longer than it is wide is a wrap-around label, so its text runs *along
the roll* automatically; the picker says which way "automatic" decided, and
picking **Across the label** or **Along the roll** corrects it for good. The
Quick tab and the designer both follow it and neither asks again — a
direction that could be set in three places is three controls that can
disagree about a property of the roll.

**Edit** opens the rest: the two measurements, the swap, **Margin (mm)** and
how many labels are on a full roll.

### The margin

BRUH Print keeps **2mm** clear of every edge by default. That is not a style
choice: the head does not start at the edge of the liner, thermal stock curls
at the die cut, and a LabelWriter's registration wanders a fraction of a
millimetre either way as the roll unwinds. The designer draws the band, so
you can see what you are aiming at, and text is fitted and centred by its own
**ink** — not by the font's line box, which reserves room for ascenders and
descenders a given word may not have, and not by the advance width, which is
where the next letter would start rather than where this one ends.

A stock you have added or corrected keeps whatever margin it was saved with,
so raising the default does not undo your measurement. Change one roll's
margin under **Edit**.

The two stocks this add-on ships knowing, read off the roll cores:

| SKU | Name | across × feed | per roll |
| --- | --- | --- | --- |
| `EDCC-082WH` | Chemical-Resistant Cryo Labels | 2.25″ × 1.25″ | 1000 |
| `ED1F-060WH` | Cryogenic Labels (tube wrap) | 0.56″ × 3.44″ | 350 |

...plus the common DYMO part numbers (30252 address, 30256 shipping, 30336
multipurpose, 30330 return address, 30323 large shipping, 30346 library,
30299 jewellery) and a continuous 2.25″ entry whose length comes from the
artwork.

Adding your own takes a name and the two measurements; the margin and the
labels-per-roll count are optional. Editing a built-in saves an override — a
future release correcting one cannot undo your measurement.

### The 2.25″ note

The LabelWriter 450's print head is 672 dots at 300 dpi, which is 2.24″. A
2.25″ label is three dot columns wider than the printer can reach. BRUH Print
clips rather than scaling, and says so in a note: scaling every element down
by half a percent to hide it would make a barcode's module width fractional,
and a barcode whose bars are 1.4 dots wide does not scan.

## What is loaded

Tell BRUH Print which stock is in which roll and it will refuse a label that
does not match. That refusal is the point of the feature. Without it, sending
a 2.25″-wide raster to the 0.56″ roll prints across the liner — once per copy,
so a run of fifty ruins fifty labels and there is no error anywhere.

**Nothing asks you which roll.** You pick the label; BRUH Print knows which
bay it is in, because you told it on the Printer tab. There is no roll picker
on the Quick tab, in the designer, on a template, on the card, or in the print
services — a roll is where a label happens to be, not a decision. The bay
holding that stock wins; a printer with nothing recorded prints on the left,
which on a single-roll model is the only bay.

(The services still accept a `side` if one is passed, so an automation
written before 0.2.0 keeps working. Nothing offers it. `set_roll` keeps it,
because saying what is loaded is a statement about a bay.)

**Only what is loaded can be picked.** Every stock picker outside the Printer
tab lists the rolls that are actually in the printer. The Printer tab is
where the whole catalog lives, because that is where the question is "what
did I just load".

The remaining count is an **estimate**, counted down from prints — nothing on
a LabelWriter reports a real level, so it is only as good as the last time
you set it. Press the bar on the Printer tab to correct it, or turn
**Keep an estimate of how many labels are left** off under Settings and BRUH
Print stops counting entirely.

## The label document

The format the designer produces, `print_label` takes, and templates store.
All measurements are in millimetres from the top-left of the *drawable* area
(the label minus its margin).

```json
{
  "stock": "edcc-082wh",
  "rotate": 0,
  "name": "Pantry jar",
  "elements": [
    {
      "type": "text",
      "x_mm": 1, "y_mm": 1, "w_mm": 38, "h_mm": 11,
      "props": {"text": "Chest freezer — chili", "font": "sans-bold", "size_mm": 0,
                "align": "center", "valign": "middle", "wrap": true}
    },
    {
      "type": "barcode",
      "x_mm": 1, "y_mm": 13, "w_mm": 53, "h_mm": 14,
      "props": {"data": "LOT-2026-0093", "hri": true}
    }
  ]
}
```

`rotate` turns the *design canvas*: at 90 or 270 you lay the label out on its
side, which is how a 0.56″ × 3.44″ tube wrap is designed as a long strip and
printed as a narrow one.

You do not set it per print. A **new** label takes the stock's own **Text
direction**, and changing the stock in the designer changes it with them; a
**saved** label keeps whatever it was drawn at, because that is a layout
somebody made rather than a property of the roll. The one place the direction
is decided is the Printer tab.

An element's own `rotate` is a different thing — it turns that box's contents
within the label, and the designer's **⟳ Rotate** button is what sets it. Text
and barcodes have one; a QR code, a box and a rule look the same whichever way
up they are, so the button says so instead of doing nothing.

`size_mm: 0` on a text element means "as large as fits its box". A non-zero
size that does not fit is reported as a note and clipped — never silently
shrunk, because you set it on purpose, probably to match another element.

### Element types

| Type | Notes |
| --- | --- |
| `text` | Auto-fits at `size_mm: 0`. Wraps on spaces, then mid-word. |
| `barcode` | Code 128, sets B and C. Human-readable text underneath by default. |
| `qr` | Error correction L/M/Q/H, default M. Always square. |
| `box` | Outline or filled, optional corner radius. |
| `line` | A rule; orientation follows whichever dimension is larger. |
| `image` | PNG/JPEG/GIF/BMP/WebP you uploaded. Thresholded or dithered. |

Every module of a barcode and every module of a QR code is a whole number of
printer dots. That is not tidiness — a fractional module width rounds each
bar independently, so five 1.4-dot bars come out 1, 1, 2, 1, 2 and a scanner
reads the wrong widths. If a symbol cannot fit at one dot per module you get
a note saying so rather than a barcode that does not scan.

## The designer

Everything under the canvas is the server's own render — the same renderer
that packs the printer's bytes — so what is on screen is what comes out.

**The printable area is drawn.** A dashed rectangle with the margin tinted
outside it, and, on a stock wider than the head (2.25″ on a 672-dot head), a
hatched strip marking the columns the printer cannot reach. It is drawn wide
enough to see; it is really about a hundredth of an inch.

**Boxes line up as you drag.** Edges and centres catch on the printable
area's edges and centre lines, on the other boxes' edges and centres, and on
a 1mm grid — and a thin line is drawn at whatever it caught, because a box
that jumps with no line reads as the editor moving things on its own. The
grid never wins over a real alignment one millimetre away. **Line boxes up
as I drag** under **⋯ Label setup** turns it off; the choice is remembered.

**Text re-fits while you drag.** The size of the glyphs is the thing being
chosen when you drag a text box's corner, so the preview re-renders during
the drag rather than after you let go.

**Nothing can be placed off the label.** Dragging, resizing, typing an X, Y,
W or H, nudging and turning all clamp to the printable area.

**A box that cannot be drawn is outlined in red** — a barcode too narrow for
its data, a QR code with nowhere to go, a fixed text size that clips. The
notes under the label say what is wrong and the label still prints: the rule
here is that a print is refused only when it cannot be right.

**The font picker shows the fonts.** Each row is a sample drawn by the label
renderer, because a list of family names shows the one thing a font choice is
not about — and a CSS preview would show your browser's idea of "Monospace"
beside a label that prints in DejaVu Sans Mono.

**Align, nudge and rotate.** The buttons under the geometry fields put a box
against an edge, centre it, or fill the width or the height of the printable
area; the arrows move it half a millimetre, which is a thumb-sized way to do
something a number field asks for a keyboard; and **⟳ Rotate** turns the box
a quarter at a time, taking the box with it so the words still have room.
Text and barcodes only — a QR code, a box and a rule look the same whichever
way up they are, so the button is there and greyed out rather than missing.

**The bar is the add strip and one button.** Everything about the label
rather than about a box on it — which stock it is on, what it is called,
which way its text runs, and whether boxes line up as you drag — is behind
**⋯ Label setup**. On a phone the bar used to be five rows and the label
being designed started below the fold.

## Templates

Write `{{field}}` in a text, a barcode's data or a QR code's data. Saving
takes the fields from the label itself, not from what the form declared, so a
placeholder you deleted stops being asked for.

`{{date}}`, `{{time}}` and `{{datetime}}` fill themselves in.

Substitution is plain string replacement with no expression language, on
purpose: a template that can evaluate is a template that can be made to
evaluate something else by whoever sends the automation payload, and the
value of a label expression language is nearly zero against that.

Printing a template through the API refuses when a field is empty; the panel
warns instead. The difference is deliberate — the panel has somebody looking
at the preview, and the API call is usually an automation about to print
fifty labels with a hole in them.

## Services

See `services.yaml`, or the Developer Tools service picker, for every field.
All six return response data (`printed`, `side`, `notes`, `status`).

```yaml
# One word, biggest that fits
action: bruh_print.print_text
data:
  text: Chest freezer — chili
  copies: 2

# Fill in a template. No roll to name — the template's label says which
# stock it is for, and BRUH Print knows which bay holds it.
action: bruh_print.print_template
data:
  template: Freezer bag
  fields: {contents: Chili, date: 3 Sep}

# Tell it a new roll went in
action: bruh_print.set_roll
data: {side: left, stock: edcc-082wh, remaining: 1000}
```

## Entities

| Entity | State | Worth knowing |
| --- | --- | --- |
| `sensor.bruh_print_printer` | Model name | `two_rolls`, `dots_across`, `serial` |
| `sensor.bruh_print_left_roll` | Estimated labels left | `stock_name`, `size`, `loaded` |
| `sensor.bruh_print_right_roll` | Estimated labels left | Unavailable on a one-roll printer |
| `sensor.bruh_print_last_label` | What came out last | `entry_id` — pass it to `reprint` |
| `sensor.bruh_print_printed_today` | Count | |
| `binary_sensor.bruh_print_problem` | `on` = trouble | `reason` says what, in words |

None of them goes unavailable when the add-on is stopped. They report it and
keep their attributes — Home Assistant hides the attributes of an unavailable
entity, so the reason would go with them.

## The Lovelace card

`install_lovelace_card` copies `bruh-print-card.js` into `/config/www` on
every start and the integration registers it, so there is nothing to add to
your dashboard resources by hand — **BRUH Print** is in the card picker.

Core serves everything under `/local` with `Cache-Control: max-age=2678400`,
which is 31 days. Updating the file in place therefore reaches nobody: the
browser keeps what it has. So the card is registered under a URL carrying a
hash of the file's own bytes — change the card and the URL changes with it,
leave it alone and the cached copy is still used. That is a hash of the
*content* rather than of the card's version string, because the version is
what somebody remembers to bump and the hash is what changed.

One refresh may still be needed on the update that introduces this, on each
browser: the URL your browser cached is the old one, and only a reload asks
Home Assistant for the page that names the new one.

If the integration is set up before the add-on has finished copying the card
in — a first install, or an add-on update while Home Assistant was already
running — it keeps looking for about twenty minutes rather than waiting for
the next Core restart.

### The card shows "Custom element doesn't exist"

Restart Home Assistant once. This happens on a house that had no
`/config/www` folder before installing BRUH Print, which is most houses —
you only have one already if you have installed a custom card or HACS.

Home Assistant decides whether to serve `/local` **while it is starting**,
and only if `/config/www` is already there. BRUH Print creates it when the
**add-on** starts, which is after Home Assistant started, so on that first
run `/local` is not being served at all: every request for the card is a 404,
and what the dashboard shows in its place is Home Assistant's own message
about the card's element. Restarting the add-on cannot change it — the
decision was made before the add-on existed on that boot — and after one
restart of Home Assistant it never happens again.

The integration checks this itself and raises a repair in **Settings >
System > Repairs** saying exactly that, so it is not something you have to
work out from an empty dashboard. The repair clears itself once Home
Assistant is serving the folder. The card is registered either way: the URL
it is registered at starts working the moment Home Assistant restarts.

## How the printing works

There is no CUPS in this container and no DYMO driver. `panel/dymo/` speaks
the LabelWriter's own raster protocol:

```
ESC q 1|2      roll select — the Twin Turbo's whole reason for existing
ESC c|d|e|g    print density: light, medium, normal, dark
ESC h|i        300 x 300 (fast) or 300 x 600 ("barcodes and graphics", slow)
ESC L hi lo    label length in dots
ESC D 84       bytes per line (672 dots / 8)
SYN <84 bytes> one raster line, one per row
ESC G          short form feed, between copies
ESC E          form feed, after the last one
```

That is the **Standard** mode and the default: one `SYN` and one full line
for every row, which is the shape cups-filters' DYMO path has printed with
for twenty years. A 2.25″ × 1.25″ label is 31,886 bytes, or under three
milliseconds of USB 2.0.

**Compact** mode adds `ETB` — repeat the previous line — which takes that
same label to about 7 KB. It is not the default because it *was*, and it did
not print: a label is mostly blank, so nearly the whole job became that one
opcode, and a firmware that does not read `0x17` that way takes the job and
produces nothing. There is no error to report; the bytes were accepted.

**Bare minimum** drops roll select as well, for a firmware that will not take
`ESC q`, along with the darkness and speed commands below. On a Twin Turbo
that means the printer uses whichever bay it used last, which is why it is
the last thing to try rather than a safe default.

`ESC B 0` (dot tab) is not sent at all. It was a no-op by construction — the
renderer already knows where the left edge is — and a no-op in a preamble is
pure risk: a firmware that does not take the command may swallow the byte
after it.

### How dark, and how slowly

A LabelWriter that is told nothing prints at its own defaults — normal
density, text speed — and on ordinary thermal stock that comes out light.
Two commands change it, and both are on the Printer tab under Settings:

| Setting | Default | What it does |
| --- | --- | --- |
| **Darkness** | Dark | `ESC c/d/e/g` — how much heat the head puts into each dot. Turn it down if labels smudge or the paper curls. |
| **Print speed** | Slow & dark | `ESC h` (fast, 300 x 300) or `ESC i` (the printer's "barcodes and graphics" mode, 300 x 600). The slow one steps the paper at 600 lines to the inch, so the head dwells twice as long over every line: darker, and more accurate for barcodes and QR codes. |

In the slow mode BRUH Print sends each raster line **twice** and doubles the
`ESC L` length with it, because both are counted in those 600-per-inch steps
— a 300 dpi raster sent as-is would come out half its length with everything
on it squashed. A long run takes roughly twice as long to print; that is the
whole of the cost, and Fast is one menu item away.

These are the 400/450 generation's encodings — the same bytes, in the same
order, that cups-filters' DYMO path has sent for twenty years. The caution
that used to keep them out of the preamble has not gone away: the 550
generation's command set differs (and it refuses third-party stock in any
case), and a byte a firmware reads as something else is a wedged printer
rather than a lighter label. **Bare minimum** is the escape route — it sends
neither command, leaving the printer exactly where it was before any of this.

## When something goes wrong

**"Ask the printer" says it cannot be asked.** That is about the add-on, not
the printer: this LabelWriter's interface exposes no bulk IN endpoint, so
there is nothing to read a reply from. Printing is unaffected — a
unidirectional printer prints perfectly well. Press **USB details** to see
which interfaces and endpoints it does expose.

**"Ask the printer" says it did not answer.** That one is about the printer,
and it is ordinary: a LabelWriter mid-feed does not reply, and neither does
one whose firmware predates the status command.

**It says it printed and nothing came out.** The bytes were accepted and the
printer did not use them — which produces no error anywhere, because from
the add-on's side the job succeeded. Printer tab → Settings → **If nothing
comes out**: change it, press **Print the ruler**, repeat. Standard is what
everything is tested against; Compact adds a compression opcode not every
firmware reads; Bare minimum also drops roll select — which costs a Twin
Turbo its second bay — along with the darkness and speed commands, and is
the last thing to try. Whether a given
LabelWriter takes every command in the preamble is not something this add-on
can ask it, so please say which one worked.

**"No DYMO printer is on the USB bus."** In order of likelihood: the printer
has no power (a LabelWriter with no power does not enumerate at all); the
cable is a charge-only one; it is plugged into a hub the host has not
enumerated. There is no setting to check — see the note under Installation.
If the log says `/dev/bus/usb is not mapped into this container`, the
Supervisor did not map the device tree, which is a host or Supervisor
problem rather than a configuration one.

**"...is connected but this add-on may not open it."** The kernel refused the
device node. Restart the add-on. If it persists, something else on the
machine has claimed the printer — a CUPS or print-server add-on will do that
on sight.

**"...is claimed by something else on this machine."** As above: two drivers
cannot own one LabelWriter.

**The label comes out sideways.** Two different things wear that sentence.
If the *whole* label is turned — the text running off the long edge — the
stock's two measurements are the wrong way round: press **Edit** on the
Printer tab and then **"These are the wrong way round"**. If the label is the
right shape and the words are simply lying the wrong way along it, that is
**Text direction** on the same row, and it is one press.

**The label comes out blank, or half of it does.** Print the ruler. If the
ruler is right, the artwork is outside the drawable area — the designer draws
that area as a dashed rectangle with the margin tinted, and clamps boxes to
it, so this usually means the stock is wrong rather than the label.

**The words sit too close to the edge.** They should not: text is fitted and
placed by its ink, inside a 2mm margin and a little breathing room inside its
own box. If a particular roll needs more, raise **Margin (mm)** under **Edit**
on the Printer tab — it is per stock, so nothing else changes.

**Nothing prints and there is no error.** Check the roll is seated and the
lid is closed, then press **Check it** on the printer's card — a LabelWriter
reports an open lid and an empty roll, and "no status reported" is itself an
answer (it is what a printer mid-feed says).

## Backups

`/data/assets` is excluded from Home Assistant backups — uploaded images are
bulk, and everything that defines a label (stocks, rolls, templates, history)
is small and *is* backed up.
