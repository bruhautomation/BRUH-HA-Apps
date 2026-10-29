#!/usr/bin/env node
// Shoots gallery drawings to PNGs with the installed Google Chrome, for reviewing them.
//
//   node scripts/render.mjs --out <dir> [--module oven] [--filter id-part[,id-part]]
//        [--theme light|dark|both] [--width 480] [--height px] [--scale 2] [--refs <dir>] [--motion]
//
// --module   a gallery/variants/<name>.ts file, or "all" (default)
// --filter   keep variants whose id contains any of the comma-separated parts
// --height   fit each drawing into a stage this tall, as an overview card does (default: its
//            natural height at --width)
// --refs     a folder of reference photos: a variant naming `reference` is shot beside it, at the
//            drawing's height, so the two compare directly. Keep photos out of the repository.
// --motion   leave transitions on (they're off by default so shots are stable)
//
// Each run builds into its own temporary folder, so several runs can go at once.
import * as esbuild from "esbuild";
import { chromium } from "playwright-core";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

function parseArgs(argv) {
  const options = { module: "all", filter: "", theme: "both", width: 480, height: 0, scale: 2, motion: false };
  for (let index = 0; index < argv.length; index++) {
    const name = argv[index].replace(/^--/, "");
    if (name === "motion") options.motion = true;
    else options[name] = argv[++index];
  }
  if (!options.out) throw new Error("--out <dir> is required");
  return options;
}

const options = parseArgs(process.argv.slice(2));
const out = resolve(options.out);
mkdirSync(out, { recursive: true });
const build = mkdtempSync(join(tmpdir(), "bc-gallery-"));

try {
  await esbuild.build({
    absWorkingDir: root,
    entryPoints: ["gallery/main.ts"],
    bundle: true,
    // A classic script: Chrome refuses module scripts on file:// pages.
    format: "iife",
    target: "es2021",
    outfile: join(build, "gallery.js"),
    logLevel: "warning",
  });
  copyFileSync(join(root, "gallery/index.html"), join(build, "index.html"));

  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    deviceScaleFactor: Number(options.scale),
    viewport: { width: 1800, height: 1400 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => message.type() === "error" && errors.push(message.text()));

  const themes = options.theme === "both" ? ["light", "dark"] : [options.theme];
  const shots = [];
  for (const theme of themes) {
    const query = new URLSearchParams({
      module: options.module,
      filter: options.filter,
      theme,
      width: String(options.width),
      height: String(options.height),
      motion: options.motion ? "on" : "off",
    });
    if (options.refs) query.set("refs", pathToFileURL(resolve(options.refs)).href);
    await page.goto(`${pathToFileURL(join(build, "index.html")).href}?${query}`);
    try {
      await page.waitForFunction(() => window.__galleryReady === true, null, { timeout: 30000 });
    } catch (error) {
      throw new Error(`The gallery didn't finish rendering.\n${errors.join("\n")}`, { cause: error });
    }
    const ids = await page.$$eval("[data-variant]", (elements) => elements.map((element) => element.dataset.variant));
    for (const id of ids) {
      const path = join(out, `${id}-${theme}.png`);
      await page.locator(`[data-variant="${id}"]`).screenshot({ path });
      shots.push(path);
    }
  }
  await browser.close();
  if (errors.length) console.error(`Page errors:\n${errors.join("\n")}`);
  console.log(shots.length ? shots.join("\n") : "No variants matched.");
  if (errors.length) process.exitCode = 1;
} finally {
  rmSync(build, { recursive: true, force: true });
}
