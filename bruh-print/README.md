# BRUH Print

Design and print labels on a USB DYMO LabelWriter, from Home Assistant.

A full label designer in the sidebar, fill-in-the-blank templates, a
one-word "type it and print it" path that sizes the text for you, roll
selection for the 450 Twin Turbo, and a Lovelace card so you can print from
a dashboard.

## What it does

**Type a word, get a label.** The Quick tab takes what you typed and finds
the largest arrangement that fits — every way of breaking the words across
lines is rendered and the biggest wins. `Spare keys` comes out on two
lines because that is bigger than one; `Attic` comes out on one because
that is. The tab reads in that order too: what to say, the picture, then
**Print** — on a phone the preview is on the same screen you are typing on,
and the label, copies, font and the rest sit under one line that says what
they are currently set to.

**A real designer.** Text, Code 128 barcodes, QR codes, boxes and rules,
dragged and resized on the label itself. Everything is in millimetres and
every preview is the printer's own render — the picture you
see is the bitmap that goes to the head. Boxes snap to the label's edges and
centre lines, to each other and to a 1mm grid, with a line drawn at whatever
they caught; the printable area and the printer's own margin are drawn on the
canvas, so you can see what you are aiming at; nothing can be dragged, typed
or nudged off the label; and text re-fits as you resize its box rather than
after you let go. The bar above the label is the add strip and one **⋯ Label
setup** button — which stock, what it is called, which way its text runs and
whether boxes line up as you drag are all one press away, so the label itself
gets the screen. The font picker shows each font *drawn by the label
renderer*, because a list of family names shows the one thing a font choice
is not about.

**Templates.** Write `{{sample}}` anywhere in a text, a barcode or a QR code
and it becomes a box to fill in — in the panel, in the Lovelace card, and in
`bruh_print.print_template`. `{{date}}` and `{{time}}` fill themselves in.

**It knows which labels are in the printer.** A LabelWriter cannot tell you
what stock is loaded, so BRUH Print remembers — per roll, on a Twin Turbo —
and refuses to print a 2.25″ label onto a 0.56″ roll. That refusal is the
single most useful thing in here: without it, a run of fifty prints across
the backing paper fifty times.

**No CUPS, no drivers.** It speaks the LabelWriter's raster protocol
directly over USB. There is no spooler to get stuck and no PPD to install.

## Supported printers

Every DYMO LabelWriter that enumerates over USB. The models it knows by
name: LabelWriter 400, 450, 450 Turbo, **450 Twin Turbo**, 450 DUO, 4XL,
Wireless, 550, 550 Turbo and 5XL.

An unrecognised DYMO is still driven — as a 450, with the geometry read from
what the device reports — rather than refused. Twin Turbo roll selection is
enabled from the model, so a printer with one roll never shows a control
that does nothing.

> **The 550 generation checks its media.** LabelWriter 550, 550 Turbo and
> 5XL read an RFID tag on the roll and will not feed stock that does not
> carry one. Nothing in software can work around that, and the panel says so
> on the printer's card rather than reporting a silent no-op as a print.

## Getting started

1. Install the add-on and start it. **There is no USB setting to turn on** —
   the add-on's manifest declares `usb: true`, so the Supervisor maps the
   printer in for you. The log's first lines say what it found:

   ```
   INFO: USB printers: LabelWriter 450 Twin Turbo (0022:21040321401861)
   ```
2. Open the panel. The Printer tab should show your LabelWriter.
3. Tell it what is loaded. Pick the stock for each roll — the two cryo
   stocks are already in the list, along with the common DYMO part numbers.
4. Press **Print the ruler** once per roll. It prints a label with
   millimetre ticks along both edges; hold it against a real label to check
   the measurements are the way round BRUH Print thinks they are. If they
   are not, press **Edit** on that row and then **"These are the wrong way
   round"**.
5. Check **Text direction** on the same row. A label much longer than it is
   wide reads along the roll automatically and the picker says so; anything
   else is one press, once, for that stock. Nothing asks again per print.
6. If everything comes out shifted by the same amount every time — a wide
   band at one edge and nothing at the other — press **Where the printing
   starts**. It prints a calibration label drawn to the very edges of the
   sheet with a 1mm scale at its own corner, you read off how far in the
   printing really begins, and BRUH Print moves it. Once per roll, and
   nothing to do at all unless a label looks wrong.
7. If a **narrow** roll prints across only part of its width, that is a
   different number in the same dialog. The head is 672 dots however small
   the label is, and a raster starts at its first dot — so a roll that does
   not sit at that end of the head is only partly printed on, and no offset
   can move it, because an offset shifts artwork inside the label rather
   than moving the label along the head. Tick **Print a scale across the
   whole head**, print the calibration label, and read the distance off it.
8. Type something on the Quick tab and print it.

## From Home Assistant

Six services, all of which return what happened so a script can branch on it:

| Service | What it does |
| --- | --- |
| `bruh_print.print_text` | Fit a word or a line to a label and print it |
| `bruh_print.print_template` | Fill in a saved template and print it |
| `bruh_print.print_label` | Print a complete label document |
| `bruh_print.reprint` | Print something from the history again |
| `bruh_print.set_roll` | Say which labels are in a roll |
| `bruh_print.print_test` | Print the measuring ruler |

```yaml
action: bruh_print.print_template
data:
  template: Freezer bag
  fields:
    contents: "{{ states('input_text.leftovers') }}"
    date: "{{ now().strftime('%-d %b') }}"
  copies: 2
```

And six entities: the printer, one per roll (an estimated count, with the
stock in its attributes), the last label, a count for today, and a single
`problem` binary sensor whose `reason` attribute says what is wrong in
words.

## The Lovelace card

Installed and registered automatically. Add **BRUH Print** from the card
picker.

```yaml
type: custom:bruh-print-card
title: Label the freezer
mode: text
quick:
  - label: "Leftovers"
    text: "Leftovers"
  - label: "Dated freezer bag"
    template: Freezer bag
    fields: { date: "{{date}}" }
```

`mode: template` turns it into a form for one saved template. The card reads
the integration's sensors and calls its services — it never talks to the
add-on directly, so it works from a phone on mobile data through Nabu Casa
exactly as it does on the LAN.

Printing is a service call, so it works whatever your entities are named.
The status pill and the roll boxes are the sensors, which the card finds by
the end of their entity id — if yours are named something else (a renamed
device, or a second BRUH Print) it says so and keeps printing, and
`printer_entity`, `left_roll_entity`, `right_roll_entity` and
`problem_entity` are how you point it at them. [DOCS.md](DOCS.md#what-the-card-needs-and-what-it-only-shows)
has the whole of it.

Home Assistant serves the card with a month-long cache header, so it is
registered under a URL that changes whenever the file does. An update reaches
your dashboard on the next page load, with nothing to clear. If a dashboard
still shows the old card straight after this update, refresh it once (or
close and reopen the app) — the *old* URL is the one your browser cached, and
that is the last time it will need doing.

**The card shows "Custom element doesn't exist":** restart Home Assistant
once. Home Assistant only serves the `/config/www` folder if that folder was
already there when it started, and BRUH Print has just created it — so on a
house that never had one (most houses, unless you already run a custom card
or HACS) the card cannot be fetched until Home Assistant restarts. BRUH Print
raises a repair in **Settings > System > Repairs** that says so, and it clears
itself afterwards. You will not have to do it again.

## Documentation

[DOCS.md](DOCS.md) has the full reference: the label document format, the
stock catalog, how the raster protocol works, and what to do when a label
comes out wrong.
