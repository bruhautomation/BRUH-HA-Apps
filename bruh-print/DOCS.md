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

- **across** — the dimension that lies across the print head
- **feed** — the dimension that travels past it

Nothing can work this out for you. A LabelWriter feeds to the next die-cut
gap and has no idea what shape the label it just printed was, so if a label
comes out rotated with the text running off the edge, the two numbers are the
wrong way round. Press **Swap** on the Printer tab, or press **Print the
ruler** and hold the result against a real label.

The two stocks this add-on ships knowing, read off the roll cores:

| SKU | Name | across × feed | per roll |
| --- | --- | --- | --- |
| `EDCC-082WH` | Chemical-Resistant Cryo Labels | 2.25″ × 1.25″ | 1000 |
| `ED1F-060WH` | Cryogenic Labels (tube wrap) | 0.56″ × 3.44″ | 350 |

...plus the common DYMO part numbers (30252 address, 30256 shipping, 30336
multipurpose, 30330 return address, 30323 large shipping, 30346 library,
30299 jewellery) and a continuous 2.25″ entry whose length comes from the
artwork.

Adding your own takes a name and the two measurements. Editing a built-in
saves an override — a future release correcting one cannot undo your
measurement.

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
  "name": "Sample vial",
  "elements": [
    {
      "type": "text",
      "x_mm": 1, "y_mm": 1, "w_mm": 38, "h_mm": 11,
      "props": {"text": "Buffer A pH 7.4", "font": "sans-bold", "size_mm": 0,
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

Each **stock** carries the turn its labels take, so you do not set this per
print — switching from an address label to a tube wrap switches the turn with
it. BRUH Print derives it from the shape (a stock much longer than it is wide
is a wrap-around label and reads along the roll) and the Printer tab is where
you correct it for good; the closed picker says what "automatic" decided.

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
  text: Buffer A pH 7.4
  copies: 2

# Fill in a template. No roll to name — the template's label says which
# stock it is for, and BRUH Print knows which bay holds it.
action: bruh_print.print_template
data:
  template: Cryo vial
  fields: {sample: "9912", owner: MS}

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

## How the printing works

There is no CUPS in this container and no DYMO driver. `panel/dymo/` speaks
the LabelWriter's own raster protocol:

```
ESC B 0        dot tab
ESC D 84       bytes per line (672 dots / 8)
ESC L hi lo    label length in dots
ESC q 1|2      roll select — the Twin Turbo's whole reason for existing
SYN <84 bytes> one raster line
ETB            repeat the previous line
ESC G          short form feed, between copies
ESC E          form feed, after the last one
```

`ETB` matters more than it looks: a label is mostly white, and a run of
identical blank lines costs one byte each instead of 85. A typical 2.25″ ×
1.25″ label is 7 KB on the wire against 32 KB uncompressed.

The density and print-mode opcodes are deliberately **not** sent. Their
encodings differ across the 400/450/550 generations, thermal label stock
prints correctly at the printer's default, and a byte sent to the wrong
firmware is a wedged printer rather than a lighter label.

## When something goes wrong

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

**The label comes out sideways.** The stock's two measurements are the wrong
way round. Press **Swap** on the Printer tab.

**The label comes out blank, or half of it does.** Print the ruler. If the
ruler is right, the artwork is outside the drawable area — the designer
clamps boxes to the label, so this usually means the stock is wrong rather
than the label.

**Nothing prints and there is no error.** Check the roll is seated and the
lid is closed, then press **Check it** on the printer's card — a LabelWriter
reports an open lid and an empty roll, and "no status reported" is itself an
answer (it is what a printer mid-feed says).

## Backups

`/data/assets` is excluded from Home Assistant backups — uploaded images are
bulk, and everything that defines a label (stocks, rolls, templates, history)
is small and *is* backed up.
