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
