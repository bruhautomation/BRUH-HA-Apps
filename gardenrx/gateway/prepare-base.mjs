#!/usr/bin/env node
/**
 * Write this install's ingress path into the built app.
 *
 * Home Assistant mounts an add-on's panel at /api/hassio_ingress/<token>/,
 * and Next.js needs that prefix at BUILD time (`basePath`): it is in every
 * asset URL, every route manifest and the client router. The token belongs to
 * this install, so the image is built with a placeholder in its place and this
 * script copies the pristine build somewhere writable and replaces the
 * placeholder, byte for byte, in every text file of it.
 *
 *   node prepare-base.mjs <pristine build> <run dir> <base path>
 *
 * The base path is checked before it is written anywhere: it is the
 * Supervisor's answer, and a string spliced into JavaScript is a string that
 * had better be a path. A run dir already prepared for the same build and the
 * same path is left alone, so an ordinary restart copies nothing.
 */

import fs from 'node:fs';
import path from 'node:path';

export const PLACEHOLDER = '/__gardenrx_base_path__';
export const BASE_RE = /^(\/[A-Za-z0-9_.-]+)*$/;
const TEXT = new Set(['.js', '.mjs', '.cjs', '.json', '.html', '.rsc', '.css', '.txt', '.map', '.meta', '.body']);

function walk(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name !== 'node_modules' || dir.endsWith('.next')) walk(p, out);
    } else if (ent.isFile() && TEXT.has(path.extname(ent.name))) out.push(p);
  }
  return out;
}

export function prepare(src, dst, base) {
  if (!BASE_RE.test(base) || base.includes('..')) {
    throw new Error(`refusing base path ${JSON.stringify(base)}: not a plain path`);
  }
  const buildId = fs.readFileSync(path.join(src, '.next', 'BUILD_ID'), 'utf8').trim();
  const stamp = JSON.stringify({ buildId, base });
  const marker = path.join(dst, '.gardenrx-base');
  try {
    if (fs.readFileSync(marker, 'utf8') === stamp) return { copied: false, files: 0 };
  } catch {
    /* not prepared yet */
  }
  fs.rmSync(dst, { recursive: true, force: true });
  fs.cpSync(src, dst, { recursive: true });
  let files = 0;
  for (const file of walk(dst)) {
    const text = fs.readFileSync(file, 'utf8');
    if (!text.includes(PLACEHOLDER)) continue;
    fs.writeFileSync(file, text.split(PLACEHOLDER).join(base));
    files += 1;
  }
  fs.writeFileSync(marker, stamp);
  return { copied: true, files };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [src, dst, base = ''] = process.argv.slice(2);
  if (!src || !dst) {
    console.error('usage: prepare-base.mjs <pristine build> <run dir> <base path>');
    process.exit(2);
  }
  try {
    const r = prepare(src, dst, base);
    console.log(r.copied ? `GardenRX mounted at ${base || '/'} (${r.files} files)` : `GardenRX already mounted at ${base || '/'}`);
  } catch (e) {
    console.error(String(e instanceof Error ? e.message : e));
    process.exit(1);
  }
}
