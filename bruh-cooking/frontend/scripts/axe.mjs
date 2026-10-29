#!/usr/bin/env node
// Checks the panel with axe-core in Chrome: the overview and each full view, light and dark,
// running on a stand-in hass built from the fixtures. Fails on any serious or critical violation.
//
//   node scripts/axe.mjs [--all]   (--all also prints minor and moderate ones)
import * as esbuild from "esbuild";
import { chromium } from "playwright-core";
import { copyFileSync, mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");
const all = process.argv.includes("--all");
const PAGES = [
  { name: "overview", fixtures: "oven-cooking,joule-cooking-us", path: "" },
  { name: "oven", fixtures: "oven-cooking,joule-cooking-us", path: "/device-oven" },
  { name: "oven-idle", fixtures: "oven-idle,joule-idle", path: "/device-oven" },
  { name: "joule", fixtures: "joule-ready", path: "" },
  { name: "joule-user", fixtures: "joule-cooking", path: "", user: true },
];

const build = mkdtempSync(join(tmpdir(), "bc-axe-"));
let failures = 0;
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
  for (const theme of ["light", "dark"]) {
    for (const page of PAGES) {
      const tab = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
      const query = new URLSearchParams({ fixtures: page.fixtures, path: page.path, theme, ...(page.user ? { admin: "0" } : {}) });
      await tab.goto(`${pathToFileURL(join(build, "panel.html")).href}?${query}`);
      await tab.waitForFunction(() => window.__panelReady === true, null, { timeout: 30000 });
      await tab.addScriptTag({ path: axePath });
      const violations = await tab.evaluate(async () => {
        const result = await window.axe.run(document, { resultTypes: ["violations"] });
        return result.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          targets: violation.nodes.slice(0, 4).map((node) => JSON.stringify(node.target)),
        }));
      });
      const shown = violations.filter((violation) => all || violation.impact === "serious" || violation.impact === "critical");
      const label = `${page.name} (${theme})`;
      if (!shown.length) console.log(`ok  ${label}`);
      for (const violation of shown) {
        if (violation.impact === "serious" || violation.impact === "critical") failures++;
        console.log(`${violation.impact.padEnd(8)} ${label}: ${violation.id} — ${violation.help}\n         ${violation.targets.join("\n         ")}`);
      }
      await tab.close();
    }
  }
  await browser.close();
} finally {
  rmSync(build, { recursive: true, force: true });
}
if (failures) {
  console.error(`${failures} serious or critical violations`);
  process.exitCode = 1;
}
