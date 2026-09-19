// Open a pane by its `data-view`, through the four-tab strip.
//
// A pane lives under a group (Home / Ask / House / Help) and reaches the
// screen by pressing the group's tab and then, where the group holds more
// than one pane, the pane's own button on the sub-strip. Which group is read
// off the markup's own `data-group` rather than written down here, so a pane
// moved between groups moves the measures with it.
export async function openView(page, view) {
  const sub = page.locator(`.subtab[data-view="${view}"]`);
  const group = (await sub.count()) ? await sub.getAttribute('data-group') : null;
  if (!group) {
    await page.click(`.viewtab[data-view="${view}"]`);
    return;
  }
  await page.click(`.viewtab[data-group="${group}"]`);
  if (await sub.isVisible()) await sub.click();
}
