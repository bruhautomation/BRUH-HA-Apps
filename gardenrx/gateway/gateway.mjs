#!/usr/bin/env node
/**
 * The ingress port: everything Home Assistant reaches this add-on through.
 *
 * The Supervisor's ingress proxy strips `/api/hassio_ingress/<token>` before
 * forwarding, and the app was built to live under exactly that prefix (see
 * prepare-base.mjs), so each request has the prefix put back before it is
 * handed to Next on loopback. A request that already carries it (a redirect
 * Next issued itself) is passed through unchanged.
 *
 * The same port answers the `gardenrx` integration in Home Assistant Core,
 * which calls `/api/ha/*` with a bearer token the app checks. Nothing here is
 * published to the LAN: `ports:` in config.yaml is empty.
 *
 * Plain node:http, no dependencies: a proxy is the one part of an add-on that
 * must keep working when everything above it is wrong.
 */

import http from 'node:http';

const LISTEN = Number(process.env.GARDENRX_PORT || 8101);
const UPSTREAM = Number(process.env.GARDENRX_APP_PORT || 3000);
export const BASE = process.env.GARDENRX_BASE_PATH || '';

const HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade',
]);

/** The path Next expects for the one the Supervisor forwarded. */
export function upstreamPath(url, base = BASE) {
  const raw = url || '/';
  if (!raw.startsWith('/') || raw.startsWith('//')) return null;
  if (!base) return raw;
  if (raw === base || raw.startsWith(base + '/') || raw.startsWith(base + '?')) return raw;
  return raw === '/' ? base : base + raw;
}

export function createGateway({ base = BASE, upstream = UPSTREAM } = {}) {
  return http.createServer((req, res) => {
    const target = upstreamPath(req.url, base);
    if (target === null) {
      res.writeHead(400, { 'content-type': 'text/plain' });
      res.end('bad request path');
      return;
    }
    const headers = {};
    for (const [k, v] of Object.entries(req.headers)) {
      if (!HOP.has(k.toLowerCase())) headers[k] = v;
    }
    headers.host = `127.0.0.1:${upstream}`;
    const up = http.request(
      { host: '127.0.0.1', port: upstream, method: req.method, path: target, headers },
      (upRes) => {
        const out = {};
        for (const [k, v] of Object.entries(upRes.headers)) {
          if (!HOP.has(k.toLowerCase())) out[k] = v;
        }
        res.writeHead(upRes.statusCode || 502, out);
        upRes.pipe(res);
      }
    );
    up.on('error', (e) => {
      if (res.headersSent) {
        res.destroy(e);
        return;
      }
      res.writeHead(502, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: `GardenRX is not answering: ${e.message}` }));
    });
    req.pipe(up);
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const server = createGateway();
  server.listen(LISTEN, '0.0.0.0', () => {
    console.log(`GardenRX gateway listening on 0.0.0.0:${LISTEN}, app at ${BASE || '/'}`);
  });
  server.on('error', (e) => {
    console.error(`GardenRX gateway could not listen on ${LISTEN}: ${e.message}`);
    process.exit(1);
  });
}
