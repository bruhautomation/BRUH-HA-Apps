# Manual checks

Checks that need a real browser, so they can't run in CI alongside the pytest
suite. Run them by hand when you touch what they measure.

They all need Playwright, resolved from this repo's own `node_modules`:

```bash
npm install playwright        # once, at the repo root
export CHROMIUM_PATH=...      # only if Playwright can't find a browser itself
```

## `measure-topbar.mjs`

Renders the panel's top bar at 32 viewport widths from 320px to 1920px, in
three states each (healthy / paused / failed login), and asserts that every
one lays out as the shape that width is supposed to have.

```bash
node tests/manual/measure-topbar.mjs
```

**The bar has two shapes and no third.** At ≥1240px it is one 56px row. Below
that it is the two-row bar — status and actions on top, the five tabs on a
full-width strip beneath, each name under its icon. No width gets a row of
bare glyphs: nothing in the bar may shrink, so a fit is binary and an overflow
is something this can see.

It fails on a wrong shape, on any overflow, on a missing tab label, and on any
target under 44px (chips 40px). Set `TOPBAR_SHOT_DIR=/some/dir` to also write
PNGs of the bar at representative widths.

**Run this after changing anything in the bar** — a tab, a chip, a button, or
the breakpoints in `style.css`. Adding a control moves the measured widths, so
take the breakpoints from what this reports rather than guessing.

Three states are measured per width because none is a superset of the others:
the trouble states put a second chip beside the usage pill, and that is what
decides whether the phone bar runs to a third row. Measuring only the healthy
one is how the failed-login bar came to overflow a 320px screen with nothing
reporting it.

`tests/test_brain_addon.py::TestTopbarLayout` pins the structure this relies
on, so CI still fails if the no-shrink rule comes back — it just can't measure
pixels.

## `measure-cardhead.mjs`

Measures an insight card's head. Fails on a truncated title, a wrapped
category eyebrow, an overflowing head, or a target under 40px.

```bash
node tests/manual/measure-cardhead.mjs
```

Run it after touching the card head. The title gets the row and wraps to two
lines; the eyebrow is the part that gives way.

## `measure-tooltips.mjs`

Hovers every visible `[data-tip]` control on the Findings tab at five widths
and fails if the bubble lands outside the viewport — or never opens, which
looks the same to whoever wanted to read it.

```bash
node tests/manual/measure-tooltips.mjs
```

Tooltips used to be a `::after` per control, `position: absolute; right: -4px`
with a 240px max-width — so the bubble hung *leftward* from the control's
right edge and ran off the side of the screen for anything in the first
~236px. That was four of the six buttons under a finding at 390px, and still
two of them at 1100px, because the findings list starts at the left margin.

CSS cannot see the viewport edge, so no CSS-only version of this is correct.
The panel places one shared fixed-position element in JS and clamps it, and
this is what measures the clamp. Run it after adding a control with a
tooltip, or after touching `placeTip` / `.tipbox`. Set `TIP_SHOT_DIR=/some/dir`
to also write a PNG per width.

`tests/test_brain_addon.py::TestTooltips` pins the structure it relies on, so
CI still fails if the pseudo-element version comes back — it just can't
measure pixels.

## `demo_panel.py` + `shoot-panel.mjs` — the docs screenshots

The screenshots on bruhautomation.com are the actual product, not mockups.
This is how they are made.

```bash
python3 tests/manual/demo_panel.py /tmp/brain-demo     # serves :8099
SHOT_DIR=shots node tests/manual/shoot-panel.mjs       # writes the PNGs
```

`demo_panel.py` points every path the panel reads at a scratch directory,
fills it with a plausible house (`demo_home.py`), and runs the **real**
`brain/panel/server.py`. `engine.run_claude` and `run_agent` are stubbed, so
no Claude process is ever spawned and no credential is needed — it is safe to
run anywhere.

`shoot-panel.mjs` captures each tab light and dark, plus one phone shot
because the two-row bar only appears under the breakpoint. It parks the
pointer off-canvas before each capture: a tab still under the cursor keeps its
tooltip open, and a tooltip in a docs screenshot reads as chrome.

**Re-run both after a UI change that alters what the docs show**, then convert
to webp at ~1440px for the site (`public/images/brain/`) and copy the three the
add-on README uses into `docs/images/`.

### The house is meant to survive being checked

Every number in `demo_home.py` should hold up to a reader doing the
arithmetic, because the whole pitch is that brAIn's numbers are real. When
editing it:

- **The kWh add up.** The headline claim ("more than the fridge and freezer
  combined") must be true of the bars drawn underneath it.
- **The money divides.** 41 kWh at 28.6p is £11.73, so the card says £11.70
  and not a rounder number that would be wrong.
- **The tool calls are real calls.** `get_automation_trace` takes
  `automation_id`, not `entity_id` — a screenshot of a call that would have
  errored is worse than no screenshot.
- **The house is one house.** It is a 1930s British semi, so it has a loft, a
  garage and a utility room, and does not have a basement. Devices, tariff and
  household in `MEMORY_MD` are what the cards are describing.
