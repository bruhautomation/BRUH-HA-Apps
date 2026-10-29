#!/usr/bin/env node
// A keyboard-only run of the full view, in Chrome, on a stand-in hass built from the fixtures:
// Tab reaches every control with a visible focus ring; Enter on Start asks first, with focus on
// the safe choice; Escape cancels and focus returns to Start; nothing is called. Fails otherwise.
import * as esbuild from "esbuild";
import { chromium } from "playwright-core";
import { copyFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const build = mkdtempSync(join(tmpdir(), "bc-keys-"));
const problems = [];

/** The focused element, through shadow roots: its name and whether focus shows. */
function focused() {
  let active = document.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  if (!active || active === document.body) return null;
  const style = getComputedStyle(active);
  const visible = (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) || style.boxShadow !== "none";
  const label =
    active.getAttribute("aria-label") ||
    (active.getAttribute("aria-labelledby") && active.getRootNode().getElementById?.(active.getAttribute("aria-labelledby").split(" ")[0])?.textContent) ||
    active.textContent;
  return { tag: active.tagName.toLowerCase(), role: active.getAttribute("role"), label: (label ?? "").trim().replace(/\s+/g, " ").slice(0, 60), visible };
}

try {
  await esbuild.build({
    absWorkingDir: root,
    entryPoints: ["gallery/panel.ts"],
    bundle: true,
    format: "iife",
    target: "es2021",
    outfile: join(build, "panel.js"),
    logLevel: "warning",
  });
  copyFileSync(join(root, "gallery/panel.html"), join(build, "panel.html"));
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const query = new URLSearchParams({ fixtures: "oven-idle,joule-idle", path: "/device-oven" });
  await page.goto(`${pathToFileURL(join(build, "panel.html")).href}?${query}`);
  await page.waitForFunction(() => window.__panelReady === true, null, { timeout: 30000 });

  const stops = [];
  for (let index = 0; index < 80; index++) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(focused);
    if (!stop) break;
    stops.push(stop);
    if (!stop.visible) problems.push(`No visible focus on ${stop.tag} "${stop.label}"`);
  }
  const labels = stops.map((stop) => stop.label);
  for (const expected of ["Back", "Start", "Decrease", "Increase", "Keep warm", "Save the current settings as a preset", "Details"]) {
    if (!labels.some((label) => label.startsWith(expected))) problems.push(`Tab never reached "${expected}"`);
  }
  // The mode tiles take one stop, on the chosen mode: the arrows move inside them.
  const tiles = stops.filter((stop) => stop.role === "option");
  if (tiles.length !== 1 || tiles[0].label !== "Bake") problems.push(`The mode tiles took ${tiles.length} tab stops, not 1 on Bake`);

  // Back to Start, then Enter: the question, with focus on "Not now".
  await page.keyboard.press("Shift+Tab");
  for (let index = 0; index < 120; index++) {
    const stop = await page.evaluate(focused);
    if (stop?.label === "Start") break;
    await page.keyboard.press("Shift+Tab");
  }
  if ((await page.evaluate(focused))?.label !== "Start") problems.push("Couldn't get back to Start");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  const asked = await page.evaluate(focused);
  if (asked?.label !== "Not now") problems.push(`Enter on Start focused "${asked?.label}", not "Not now"`);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(100);
  const back = await page.evaluate(focused);
  if (back?.label !== "Start") problems.push(`Escape left focus on "${back?.label}", not Start`);
  const calls = await page.evaluate(() => window.__hass.calls.filter((call) => call.kind === "service"));
  if (calls.length) problems.push(`Something was called: ${JSON.stringify(calls)}`);

  console.log(`${stops.length} tab stops: ${labels.join(" | ")}`);
  await browser.close();
} finally {
  rmSync(build, { recursive: true, force: true });
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exitCode = 1;
} else {
  console.log("ok");
}
