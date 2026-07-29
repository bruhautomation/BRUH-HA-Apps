# Manual checks

Checks that need a real browser, so they can't run in CI alongside the pytest
suite. Run them by hand when you touch what they measure.

## `measure-topbar.mjs`

Renders the panel's top bar at 24 viewport widths from 320px to 1440px and
asserts that at every one it is a single 48px row with nothing overflowing.

```bash
npm install playwright        # once
node tests/manual/measure-topbar.mjs
```

Exits non-zero and names the offending widths if any of them wrap, grow past
48px, or overflow. Set `TOPBAR_SHOT_DIR=/some/dir` to also write PNGs of the
bar at a few representative widths, and `CHROMIUM_PATH` if Playwright can't
find a browser on its own.

**Run this after changing anything in the bar** — a tab, a chip, a button, or
the breakpoints in `style.css`. The bar sheds text in three measured steps
(chip sentences below 1024px, tab labels and wordmark below 780px, tighter
padding below 400px), and those numbers come from what the content actually
needs. Adding a control changes the numbers.

This is what caught the two bugs fixed in 1.5.1: a leftover `flex-wrap: wrap`
from the old two-bar chrome, and a single breakpoint at 780px that left the
781–1023px band overflowing by up to 212px. Both were invisible at desktop
width, which is the only width anyone develops at.

`tests/test_brain_addon.py::TestTopbarFitsOneRow` pins the structure this
relies on, so CI still fails if the wrap rule or the split chip markup comes
back — it just can't measure pixels.
