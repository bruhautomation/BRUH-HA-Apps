# Changelog

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
