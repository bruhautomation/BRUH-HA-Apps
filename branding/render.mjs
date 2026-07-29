// Rasterise the BRain brand SVGs into every PNG this repo ships.
//
// The SVGs in branding/icons/ are the source of truth; every PNG below is
// derived, so regenerate rather than hand-edit. Run after changing any of
// them:
//
//   npm install playwright        # once
//   node branding/render.mjs
//
// Home Assistant wants PNGs in two places and they are not the same thing:
//
//   brain/icon.png, brain/logo.png        the add-on store entry
//   brands/custom_integrations/brain/     the integration page, via the
//                                         home-assistant/brands repo
//
// The wide lockups sit on a dark plate rather than shipping transparent.
// The wordmark's B, R and N are ink on light grounds and paper on dark, and
// a PNG cannot switch with the theme — so it carries its own ground and
// reads the same in both.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const ICONS = path.join(ROOT, 'branding', 'icons');

const INK = '#0B1016';

const read = (name) => fs.readFileSync(path.join(ICONS, name), 'utf8');

// Square tiles rasterise as-is: they already carry their own ground.
const tiles = [
  { svg: 'brain-app-tile-dark.svg', out: 'brain/icon.png', size: 256 },
  { svg: 'brain-app-tile-dark.svg', out: 'brands/custom_integrations/brain/icon.png', size: 256 },
  { svg: 'brain-app-tile-dark.svg', out: 'brands/custom_integrations/brain/icon@2x.png', size: 512 },
];

// Lockups: the on-dark wordmark centred on a plate, with the brand's own
// clear-space rule (68u at a 496u master width ≈ 13.7% a side).
//
// The plate is 4:3, not the old family's 640×200. This mark is 496×342 —
// near enough square that a 3.2:1 banner would sit it in a puddle of empty
// plate, or crop it if fitted by width. The old lockups were wide because
// the old wordmark was; this one isn't.
const lockups = [
  { out: 'brain/logo.png', w: 512, h: 384 },
  { out: 'brands/custom_integrations/brain/logo.png', w: 512, h: 384 },
  { out: 'brands/custom_integrations/brain/logo@2x.png', w: 1024, h: 768 },
];

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ deviceScaleFactor: 1 });

const shoot = async (html, w, h, out) => {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(
    `<!doctype html><meta charset="utf-8">
     <style>html,body{margin:0;padding:0;background:transparent}
       #s{width:${w}px;height:${h}px;display:flex;align-items:center;justify-content:center}
       svg{display:block}</style>
     <div id="s">${html}</div>`,
    { waitUntil: 'load' });
  const file = path.join(ROOT, out);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await page.locator('#s').screenshot({ path: file, omitBackground: true });
  console.log(`  ${out.padEnd(48)} ${w}x${h}`);
};

console.log('tiles');
for (const t of tiles) {
  const svg = read(t.svg).replace('<svg ', `<svg width="${t.size}" height="${t.size}" `);
  await shoot(svg, t.size, t.size, t.out);
}

console.log('lockups');
for (const l of lockups) {
  // The SVG keeps its viewBox and fills the padded box; preserveAspectRatio
  // defaults to "meet", so it scales to fit and can never crop — which is
  // what fitting by width alone did.
  const svg = read('brain-logo-ondark.svg')
    .replace('<svg ', '<svg style="width:100%;height:100%" ');
  const pad = Math.round(l.w * 0.137);
  const plate = `<div style="width:${l.w}px;height:${l.h}px;background:${INK};
      border-radius:${Math.round(l.h * 0.1)}px;box-sizing:border-box;
      padding:${pad}px;display:flex;align-items:center;
      justify-content:center">${svg}</div>`;
  await shoot(plate, l.w, l.h, l.out);
}

await browser.close();
console.log('\ndone — all PNGs regenerated from branding/icons/');
