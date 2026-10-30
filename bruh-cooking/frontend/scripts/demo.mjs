#!/usr/bin/env node
// Builds the panel's demo page and the drawing gallery into dist/ (git-ignored), to open in a
// browser: the real panel on a stand-in hass built from the fixtures, and every drawing.
import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "dist");
mkdirSync(out, { recursive: true });
for (const [entry, file] of [
  ["gallery/panel.ts", "panel.js"],
  ["gallery/main.ts", "gallery.js"],
]) {
  await esbuild.build({
    absWorkingDir: root,
    entryPoints: [entry],
    bundle: true,
    // Classic scripts: Chrome refuses module scripts on file:// pages.
    format: "iife",
    target: "es2021",
    outfile: join(out, file),
    logLevel: "warning",
  });
}
copyFileSync(join(root, "gallery/panel.html"), join(out, "panel.html"));
copyFileSync(join(root, "gallery/index.html"), join(out, "index.html"));
const page = (file, query) => `${pathToFileURL(join(out, file)).href}?${new URLSearchParams(query)}`;
console.log(`Overview:     ${page("panel.html", { fixtures: "oven-cooking,joule-cooking-us", live: "1" })}
Oven, dark:   ${page("panel.html", { fixtures: "oven-preheating,joule-cooking-us", path: "/device-oven", theme: "dark", live: "1" })}
Joule alone:  ${page("panel.html", { fixtures: "joule-ready", live: "1" })}
Drawings:     ${page("index.html", { module: "all", motion: "on" })}

Fixtures: ${["joule-idle", "joule-preheating", "joule-ready", "joule-cooking", "joule-done", "joule-low-water",
  "oven-idle", "oven-press-start", "oven-preheating", "oven-ready", "oven-cooking", "oven-door-open", "oven-keeping-warm",
  "oven-finished"].join(", ")}.
Query: fixtures, path (/device-oven or /device-joule), theme (dark), lang (de, fr, …), admin (0), narrow (1), live (1: the clock runs).`);
