// Open a pane by its `data-view`, through the four-tab strip.
//
// A pane lives under a group (Home / Ask / House / Help) and reaches the
// screen by pressing the group's tab and then, where the group holds more
// than one pane, the pane's own button on the sub-strip. Which group is read
// off the markup's own `data-group` rather than written down here, so a pane
// moved between groups moves the measures with it.
//
// House's panes are reached through its own segmented control (`#houseSeg`,
// a select on a phone), which stands in for the sub-strip on those panes —
// so a pane the control names is opened through the control.
export async function openView(page, view) {
  const seg = page.locator(`#houseSeg .segbtn[data-view="${view}"]`);
  const house = (await seg.count()) > 0;
  const sub = page.locator(`.subtab[data-view="${view}"]`);
  const group = (await sub.count()) ? await sub.getAttribute('data-group')
    : (house ? 'house' : null);
  if (!group) {
    await page.click(`.viewtab[data-view="${view}"]`);
    return;
  }
  const tab = page.locator(`.viewtab[data-group="${group}"]`);
  if (await tab.count()) await tab.first().click();
  if (house) {
    if (await seg.isVisible()) {
      await seg.click();
    } else if (await page.locator('#houseSegSel').isVisible()) {
      await page.selectOption('#houseSegSel', view);
    } else {
      // The control is hidden off House (and over the sign-in screens), so
      // switch straight to the pane, the way the control itself would.
      await page.evaluate((v) => switchView(v), view);
    }
    return;
  }
  if (await sub.isVisible()) await sub.click();
}
