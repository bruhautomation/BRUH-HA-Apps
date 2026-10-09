// Open a pane by its `data-view`, through the three-tab strip.
//
// A pane lives under a group (Insights / Ask / Memory, and the Guide behind
// ⚙) and reaches the screen by pressing the group's tab and then, where the
// group holds more than one pane, the pane's own button on the segmented
// control under the bar (`#segNav`, a select on a phone). Which group is
// read off the markup's own `data-group` rather than written down here, so a
// pane moved between groups moves the measures with it.
export async function openView(page, view) {
  const sub = page.locator(`.subtab[data-view="${view}"]`);
  const group = (await sub.count()) ? await sub.getAttribute('data-group') : null;
  if (!group) {
    const own = page.locator(`.viewtab[data-view="${view}"]`);
    if (await own.count()) await own.first().click();
    else await page.evaluate((v) => switchView(v), view);
    return;
  }
  const tab = page.locator(`.viewtab[data-group="${group}"]`);
  if (await tab.count()) await tab.first().click();
  const seg = page.locator(`#segNav .segbtn[data-view="${view}"]`);
  if (await seg.count()) {
    if (await seg.isVisible()) {
      await seg.click();
    } else if (await page.locator('#segNavSel').isVisible()) {
      await page.selectOption('#segNavSel', view);
    } else {
      // The control is hidden over the sign-in screens, so switch straight
      // to the pane, the way the control itself would.
      await page.evaluate((v) => switchView(v), view);
    }
    return;
  }
  // Ask shows no sub-strip, and the Guide has no tab at all (⚙ › Guide
  // opens it), so a pane with no visible button is switched to the way its
  // own button would.
  if (await sub.isVisible()) await sub.click();
  else await page.evaluate((v) => switchView(v), view);
}

// Controls whose boxes overlap, read the way the house's own photographs
// audit them (brain/panel/devloop/screens.py's `controls_overlap`): every
// control with a box, not pinned to the window, against every other that
// is neither its ancestor nor its descendant, flagged when the overlap is
// more than a quarter of the smaller one. The audit reads a box straight
// off `getBoundingClientRect`, and Chromium hands one out for the content
// of a CLOSED <details> — at the place it would be drawn — so a closed
// disclosure's button "sits on" the press below it unless its content is
// taken out of the layout. That is the case this exists to catch.
export async function controlOverlaps(page, root = 'body') {
  return page.evaluate((rootSel) => {
    const host = document.querySelector(rootSel);
    if (!host) return [`${rootSel} is not on the page`];
    const shown = (el) => {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return false;
      const cs = getComputedStyle(el);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05;
    };
    const pinned = (el) => {
      for (let p = el; p && p !== document.body; p = p.parentElement) {
        const pos = getComputedStyle(p).position;
        if (pos === 'fixed' || pos === 'sticky') return true;
      }
      return false;
    };
    const name = (el) => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')} "${
      (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40)}"`;
    const controls = [...host.querySelectorAll(
      'button, a[href], [role=button], [role=tab], select, summary, input:not([type=hidden]), textarea')]
      .filter(shown).filter((el) => !pinned(el));
    const out = [];
    for (let i = 0; i < controls.length; i++) {
      const a = controls[i].getBoundingClientRect();
      for (let j = i + 1; j < controls.length; j++) {
        if (controls[i].contains(controls[j]) || controls[j].contains(controls[i])) continue;
        const b = controls[j].getBoundingClientRect();
        const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        const small = Math.min(a.width * a.height, b.width * b.height);
        if (ix > 0 && iy > 0 && small > 0 && ix * iy > 0.25 * small) {
          out.push(`${name(controls[i])} overlaps ${name(controls[j])}`);
        }
      }
    }
    return out;
  }, root);
}
