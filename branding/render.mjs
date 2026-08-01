// Rasterise the BRUH Apps brand SVGs into every PNG this repo ships.
//
// The SVGs in branding/brain/ and branding/minecraft/ are the source of truth;
// every PNG below is derived, so regenerate rather than hand-edit. Run after
// changing any of them:
//
//   npm install playwright        # once
//   node branding/render.mjs
//
// Home Assistant wants PNGs in three places and they are not the same thing:
//
//   <addon>/icon.png, <addon>/logo.png     the add-on store entry
//   <addon>/custom_components/*/icon.png   the integration, shipped in the addon
//   brands/custom_integrations/*/          the integration page, via the
//                                          home-assistant/brands repo
//
// Every square here comes from a *tile*, never from the bare gable. The gable
// alone is the family mark: it says BRUH and says nothing about which app you
// are looking at. Two add-ons shipping the same roof into the same sidebar are
// two add-ons nobody can tell apart — which is what the square lockups (roof,
// BR ligature, and the app's own caps) exist to prevent.
//
// The wide lockups sit on a dark plate rather than shipping transparent. The
// plain caps are ink on light grounds and paper on dark, and a PNG cannot switch
// with the theme — so it carries its own ground and reads the same in both.
import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const BRANDING = path.join(ROOT, 'branding');

const INK = '#0B1016';

const read = (file) => fs.readFileSync(path.join(BRANDING, file), 'utf8');

const APPS = [
	{
		name: 'brAIn',
		tile: 'brain/brain-tile-dark.svg',
		logo: 'brain/brain-logo-ondark.svg',
		squares: [
			['brain/icon.png', 256],
			['brain/custom_components/brain/icon.png', 256],
			['brands/custom_integrations/brain/icon.png', 256],
			['brands/custom_integrations/brain/icon@2x.png', 512],
		],
		lockups: [
			['brain/logo.png', 512, 384],
			['brands/custom_integrations/brain/logo.png', 512, 384],
			['brands/custom_integrations/brain/logo@2x.png', 1024, 768],
		],
	},
	{
		name: 'BRUH Minecraft',
		tile: 'minecraft/bruh-minecraft-tile-dark.svg',
		logo: 'minecraft/bruh-minecraft-logo-ondark.svg',
		squares: [
			['bruh-minecraft-server/icon.png', 256],
			['brands/custom_integrations/bruh_minecraft/icon.png', 256],
			['brands/custom_integrations/bruh_minecraft/icon@2x.png', 512],
		],
		lockups: [
			['bruh-minecraft-server/logo.png', 512, 384],
			['brands/custom_integrations/bruh_minecraft/logo.png', 512, 384],
			['brands/custom_integrations/bruh_minecraft/logo@2x.png', 1024, 768],
		],
	},
];

const browser = await chromium.launch(
	process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage({ deviceScaleFactor: 1 });

const shoot = async (html, w, h, out) => {
	await page.setViewportSize({ width: w, height: h });
	await page.setContent(
		`<!doctype html><meta charset="utf-8">
     <style>html,body{margin:0;padding:0;background:transparent}
       #s{width:${w}px;height:${h}px;display:flex;align-items:center;justify-content:center}
       svg{display:block}</style>
     <div id="s">${html}</div>`,
		{ waitUntil: 'load' }
	);
	const file = path.join(ROOT, out);
	fs.mkdirSync(path.dirname(file), { recursive: true });
	await page.locator('#s').screenshot({ path: file, omitBackground: true });
	console.log(`  ${out.padEnd(52)} ${w}x${h}`);
};

for (const app of APPS) {
	console.log(`\n${app.name}`);

	// Tiles rasterise as-is: they already carry their own ground and radius.
	for (const [out, size] of app.squares) {
		const svg = read(app.tile).replace('<svg ', `<svg width="${size}" height="${size}" `);
		await shoot(svg, size, size, out);
	}

	// Lockups: the on-dark mark centred on a plate, with the brand's own
	// clear-space rule (68u at master width, ≈13.7% a side).
	//
	// The plate is 4:3, not the old family's 640×200. These marks are near
	// enough square that a 3.2:1 banner would sit one in a puddle of empty
	// plate, or crop it if fitted by width. The SVG keeps its viewBox and fills
	// the padded box; preserveAspectRatio defaults to "meet", so it scales to
	// fit and can never crop.
	for (const [out, w, h] of app.lockups) {
		const svg = read(app.logo).replace('<svg ', '<svg style="width:100%;height:100%" ');
		const pad = Math.round(w * 0.137);
		const plate = `<div style="width:${w}px;height:${h}px;background:${INK};
      border-radius:${Math.round(h * 0.1)}px;box-sizing:border-box;
      padding:${pad}px;display:flex;align-items:center;
      justify-content:center">${svg}</div>`;
		await shoot(plate, w, h, out);
	}
}

await browser.close();
console.log('\ndone — all PNGs regenerated from branding/');
