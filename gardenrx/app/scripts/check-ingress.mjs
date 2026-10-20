#!/usr/bin/env node
/**
 * Every link in the panel has to work through Home Assistant's ingress.
 *
 * Core routes an ingress panel as `/api/hassio_ingress/<token>/{path}`, so the
 * path with nothing after the token (no slash) is a 404 from Core before the
 * add-on hears about it. The Today link once pointed at exactly that path,
 * which no check could see: served at `/`, or behind a proxy that accepts the
 * bare prefix, it worked.
 *
 * So this takes a production build, mounts it the way run.sh does
 * (prepare-base, then the gateway), puts a proxy in front that answers only
 * what Core answers, and follows every link on every page. Run it after
 * `next build` with the base-path placeholder, from gardenrx/app:
 *
 *   node scripts/check-ingress.mjs
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const GATEWAY = path.resolve(APP, '..', 'gateway');
const BASE = '/api/hassio_ingress/Ch3ck_ingress-token';
const PORTS = { app: 38400, gateway: 38401, ingress: 38402 };

function fail(message) {
  console.error(`check-ingress: ${message}`);
  process.exitCode = 1;
}

/** Answers only what Core's ingress route answers, and strips the prefix. */
function ingress() {
  return http.createServer((req, res) => {
    if (!req.url.startsWith(BASE + '/')) {
      res.writeHead(404, { 'content-type': 'text/plain' });
      res.end('404: Not Found (Home Assistant has no ingress route for this path)');
      return;
    }
    const up = http.request(
      {
        host: '127.0.0.1',
        port: PORTS.gateway,
        method: req.method,
        path: req.url.slice(BASE.length),
        headers: { ...req.headers, 'x-ingress-path': BASE },
      },
      (r) => {
        res.writeHead(r.statusCode || 502, r.headers);
        r.pipe(res);
      }
    );
    up.on('error', (e) => {
      res.writeHead(502);
      res.end(String(e));
    });
    req.pipe(up);
  });
}

async function waitFor(url, ms = 30000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`nothing answered at ${url}`);
}

/** Page links under the base path, as the browser would resolve them. */
function pageLinks(html) {
  const out = new Set();
  for (const m of html.matchAll(/href="([^"]+)"/g)) {
    const href = m[1].replace(/&amp;/g, '&');
    if (!href.startsWith(BASE)) continue;
    if (/\/_next\/|\.[a-z0-9]+(\?|$)/i.test(href)) continue; // assets, not pages
    out.add(href);
  }
  return out;
}

async function main() {
  const standalone = path.join(APP, '.next', 'standalone');
  if (!fs.existsSync(path.join(standalone, 'server.js'))) {
    throw new Error('no standalone build: run `next build` first');
  }
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'gardenrx-ingress-'));
  const built = path.join(work, 'build');
  fs.cpSync(standalone, built, { recursive: true });
  fs.cpSync(path.join(APP, '.next', 'static'), path.join(built, '.next', 'static'), {
    recursive: true,
  });
  fs.cpSync(path.join(APP, 'public'), path.join(built, 'public'), { recursive: true });
  fs.mkdirSync(path.join(built, 'seed'), { recursive: true });
  fs.copyFileSync(path.join(APP, 'seed', 'catalog.json'), path.join(built, 'seed', 'catalog.json'));

  const mounted = path.join(work, 'app');
  const prep = spawn(process.execPath, [path.join(GATEWAY, 'prepare-base.mjs'), built, mounted, BASE], {
    stdio: 'inherit',
  });
  const code = await new Promise((r) => prep.on('exit', r));
  if (code !== 0) throw new Error('prepare-base failed');

  const env = {
    ...process.env,
    HOSTNAME: '127.0.0.1',
    PORT: String(PORTS.app),
    GARDENRX_DB_PATH: path.join(work, 'gardenrx.db'),
    GARDENRX_HA_TOKEN_FILE: path.join(work, 'token'),
    GARDENRX_PORT: String(PORTS.gateway),
    GARDENRX_APP_PORT: String(PORTS.app),
    GARDENRX_BASE_PATH: BASE,
  };
  const children = [
    spawn(process.execPath, ['server.js'], { cwd: mounted, env, stdio: 'ignore' }),
    spawn(process.execPath, [path.join(GATEWAY, 'gateway.mjs')], { env, stdio: 'ignore' }),
  ];
  const proxy = ingress().listen(PORTS.ingress, '127.0.0.1');
  const origin = `http://127.0.0.1:${PORTS.ingress}`;
  try {
    // Where the Home Assistant sidebar opens the panel.
    await waitFor(`${origin}${BASE}/`);
    const seen = new Set();
    let queue = [`${BASE}/`];
    while (queue.length) {
      const next = [];
      for (const href of queue) {
        if (seen.has(href)) continue;
        seen.add(href);
        const r = await fetch(origin + href, { redirect: 'manual' });
        if (r.status !== 200) {
          fail(`${href} answered ${r.status} through ingress`);
          continue;
        }
        for (const link of pageLinks(await r.text())) {
          // Pages one level down are enough: every page shares the shell.
          if (!seen.has(link) && seen.size < 60) next.push(link);
        }
      }
      queue = next;
    }
    if (!seen.has(`${BASE}/`)) fail('the panel root was never fetched');
    console.log(`check-ingress: ${seen.size} page links answered through ingress`);
  } finally {
    proxy.close();
    for (const c of children) c.kill();
    fs.rmSync(work, { recursive: true, force: true });
  }
}

main().catch((e) => fail(e.message));
