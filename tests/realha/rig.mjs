// The browser half of the real-Home-Assistant rig (ha_rig.py starts HA).
// Signs a page in the way brAIn's screenshots do: the frontend's own token
// store (localStorage "hassTokens") holds a token, so the page opens as the
// owner with no login screen.
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
export const { chromium } = require('playwright');

export function rig(dir) {
  return JSON.parse(fs.readFileSync(`${dir}/rig.json`, 'utf8'));
}

export async function signedIn(browser, r, opts = {}) {
  const ctx = await browser.newContext({ viewport: opts.viewport || { width: 1200, height: 900 }, colorScheme: opts.scheme || 'light', ...(opts.ctx || {}) });
  const base = r.url.replace(/\/$/, '');
  await ctx.addInitScript(([hassUrl, token]) => {
    try {
      localStorage.setItem('hassTokens', JSON.stringify({ hassUrl, clientId: hassUrl + '/', access_token: token, token_type: 'Bearer', expires_in: 1800, refresh_token: '', expires: Date.now() + 25 * 60000 }));
    } catch (e) { /* a page with no storage */ }
  }, [base, r.token]);
  return ctx;
}

// A WebSocket call through the page's own connection.
export async function ws(page, msg) {
  return page.evaluate(async (m) => {
    for (let i = 0; i < 200; i++) {
      const h = document.querySelector('home-assistant');
      if (h && h.hass && h.hass.connection) return h.hass.callWS(m);
      await new Promise((res) => setTimeout(res, 100));
    }
    throw new Error('no connection');
  }, msg);
}

export async function dashboard(page, urlPath, config, title = 'Morph check') {
  const list = await ws(page, { type: 'lovelace/dashboards/list' });
  if (!list.some((d) => d.url_path === urlPath)) {
    await ws(page, { type: 'lovelace/dashboards/create', url_path: urlPath, title, mode: 'storage', show_in_sidebar: true, require_admin: false });
  }
  await ws(page, { type: 'lovelace/config/save', url_path: urlPath, config });
}

// Deep query through open shadow roots.
export const deep = `
window.__deepAll = (sel, root = document) => {
  const out = [];
  const walk = (n) => {
    if (!n) return;
    if (n.querySelectorAll) n.querySelectorAll(sel).forEach((e) => out.push(e));
    const all = n.querySelectorAll ? n.querySelectorAll('*') : [];
    all.forEach((e) => { if (e.shadowRoot) walk(e.shadowRoot); });
  };
  walk(root);
  return out;
};`;
