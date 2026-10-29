#!/usr/bin/env node
// Shoots the panel itself, running on a stand-in hass built from the fixtures, with Chrome.
//
//   node scripts/shoot-panel.mjs --out <dir> --name <file> [--fixtures a,b] [--path /device-oven]
//        [--theme light|dark] [--width 1280] [--height 900] [--narrow] [--full] [--lang de]
//        [--units metric|us_customary] [--user] [--seconds 0] [--click <selector>]
//
// Each run builds into its own temporary folder, so several runs can go at once.
import * as esbuild from "esbuild";
import { chromium } from "playwright-core";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const flags = new Set(["narrow", "full", "user"]);

function parseArgs(argv) {
  const options = { theme: "light", width: 1280, height: 900, scale: 2, fixtures: "oven-cooking,joule-cooking-us", path: "" };
  for (let index = 0; index < argv.length; index++) {
    const name = argv[index].replace(/^--/, "");
    if (flags.has(name)) options[name] = true;
    else options[name] = argv[++index];
  }
  if (!options.out || !options.name) throw new Error("--out <dir> and --name <file> are required");
  return options;
}

const options = parseArgs(process.argv.slice(2));
const out = resolve(options.out);
mkdirSync(out, { recursive: true });
const build = mkdtempSync(join(tmpdir(), "bc-panel-"));

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
  const page = await browser.newPage({
    deviceScaleFactor: Number(options.scale),
    viewport: { width: Number(options.width), height: Number(options.height) },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
  const query = new URLSearchParams({
    fixtures: options.fixtures,
    path: options.path,
    theme: options.theme,
    lang: options.lang ?? "en",
    ...(options.units ? { units: options.units } : {}),
    ...(options.narrow ? { narrow: "1" } : {}),
    ...(options.user ? { admin: "0" } : {}),
    ...(options.seconds ? { seconds: options.seconds } : {}),
  });
  await page.goto(`${pathToFileURL(join(build, "panel.html")).href}?${query}`);
  await page.waitForFunction(() => window.__panelReady === true, null, { timeout: 30000 });
  if (options.click) {
    await page.locator(options.click).first().click();
    await page.waitForTimeout(300);
  }
  await page.waitForTimeout(300);
  const path = join(out, `${options.name}.png`);
  await page.screenshot({ path, fullPage: Boolean(options.full) });
  await browser.close();
  if (errors.length) console.error(`Page errors:\n${errors.join("\n")}`);
  console.log(path);
  if (errors.length) process.exitCode = 1;
} finally {
  rmSync(build, { recursive: true, force: true });
}
