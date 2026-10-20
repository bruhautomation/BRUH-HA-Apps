# Design rules for FDM parts (read before writing geometry)

- **Print orientation.** +Z up, lowest point exactly on Z = 0, the largest
  flat face on the bed. A part that only stands up on a point needs a flat.
- **Overhangs.** Faces steeper than 45° from vertical need support. Chamfer
  downward-facing edges at 45° instead of filleting them; fillet top edges.
  Bridges up to ~15 mm are fine.
- **Walls.** At least 1.2 mm (3 lines at 0.4 mm), 2 mm or more where it
  carries load or screws. Minimum feature 0.8 mm. Text: 0.6 mm deep, 5 mm+ tall.
- **Holes.** Print ~0.2 mm undersize on the diameter; add 0.2–0.3 mm for a
  sliding fit. Horizontal holes over 8 mm: make the top a 45° teardrop.
- **Fits (on the diameter).** Press 0.1, snug 0.2, sliding 0.3–0.4,
  print-in-place moving parts 0.3–0.5 mm gap between bodies everywhere.
- **Threads.** Use `cadkit.thread_spec` values only; anything else must be
  looked up from a standards table first. Fit 0.3 mm diametral for FDM.
  Under M6, use a heat-set insert or a nut trap instead of a printed thread.
- **Captive spinning nut / print-in-place.** Separate bodies, never touching:
  0.3 mm minimum gap, and no coincident surfaces between bodies.
- **Coincident faces.** Never let two features share a face exactly when
  unioning or cutting; overlap by 0.01–0.1 mm or the mesh seams.
- **Strength.** Layers are weakest in Z. Orient so loads run along layers.
  Fillet inside corners under load (r ≥ 1 mm).
- **Size.** Fit the printer's build volume with ~5 mm to spare (PRINTERS lists
  it: a 256 mm cube for X1, P1, A1 and P2S, 180 mm for the A1 mini, about
  325 mm for the H2 series). Bigger parts are split into pieces that join.
- **Colour.** Every colour change purges filament; keep a second colour to a
  few layers (a logo on the top or bottom face) unless asked otherwise.
