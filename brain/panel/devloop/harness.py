"""The page brAIn draws the BRUH cards and Morph in, so they can be photographed.

Lovelace cards and Morph's dashboard live inside Home Assistant's frontend,
and a browser on this box cannot sign into that: it has no person's login,
and minting one is what `esphome.py` says a current Supervisor refuses an
add-on. What the cards actually need is small — the object Home Assistant
hands every card, `hass`, with the house's states in it, a way to ask the
WebSocket a question, and an `<ha-card>` to sit in — so this page builds
that object out of the house's real data and nothing else.

**It only reads.** `callService` and `callApi` refuse; every WebSocket
question goes to `/devloop/harness/ws`, which asks Core only what
`screen_targets.READ_COMMANDS` names and refuses everything else, so a card
that would write on load (Morph logs what is used) meets the same answer
a press would. A custom card Morph hosts (`loadCardHelpers`) is drawn by
its own code — a house's card from /config/morph/cards, served by name under
`/devloop/harness/morph_cards/` and `/morph_cards/` (the path a card's own
absolute import names) — and a card that throws on its config or on `hass`
is a labelled box saying why. A built-in Lovelace card (a tile, an entities
card) is Home Assistant's own code and is drawn as a labelled box rather than
a guess at what Home Assistant would draw.

The page is served on loopback only and is pure text here: `page(name)`.
"""
from __future__ import annotations

import json

BASE = "/devloop/harness"

# Home Assistant's default theme, the variables cards read, in both
# schemes. Not exact: what is measured here is the card's own layout, and
# a card that reads a variable this does not set falls back the way it
# would on a theme that does not set it either.
_THEME = """
:root{--primary-color:#03a9f4;--accent-color:#ff9800;--primary-background-color:#fafafa;
--secondary-background-color:#e5e5e5;--card-background-color:#fff;--ha-card-background:#fff;
--primary-text-color:#212121;--secondary-text-color:#727272;--disabled-text-color:#bdbdbd;
--divider-color:rgba(0,0,0,.12);--error-color:#db4437;--warning-color:#ffa600;
--success-color:#43a047;--info-color:#039be5;--state-icon-color:#44739e;
--ha-card-border-radius:12px;--rgb-primary-text-color:33,33,33;--mdc-theme-primary:#03a9f4}
@media (prefers-color-scheme: dark){:root{--primary-background-color:#111111;
--secondary-background-color:#282828;--card-background-color:#1c1c1c;--ha-card-background:#1c1c1c;
--primary-text-color:#e1e1e1;--secondary-text-color:#9b9b9b;--disabled-text-color:#6f6f6f;
--divider-color:rgba(225,225,225,.12);--state-icon-color:#8fb6d8;--rgb-primary-text-color:225,225,225}}
html,body{margin:0;background:var(--primary-background-color);color:var(--primary-text-color);
font-family:Roboto,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{box-sizing:border-box;padding:16px;display:grid;gap:16px;max-width:560px;margin:0 auto}
.wrap.full{max-width:none;padding:0;display:block;min-height:100vh}
.missing{padding:16px;border:1px dashed var(--divider-color);border-radius:12px}
"""

# (element, the file it is defined in) per harness page. Morph's is its
# panel module; the rest are the cards' files under /js/.
PAGES: dict[str, list[tuple[str, str]]] = {
    "print-card": [("bruh-print-card", "bruh-print-card.js")],
    "bambu-card": [("bruh-bambu-card", "bruh-bambu-card.js")],
    "gardenrx-cards": [("gardenrx-spray-card", "gardenrx-cards.js"),
                       ("gardenrx-harvest-card", "gardenrx-cards.js"),
                       ("gardenrx-inventory-card", "gardenrx-cards.js")],
    "morph": [("morph-panel", "morph-panel.js")],
}

_SCRIPT = r"""
const H = __BASE__, CARDS = __CARDS__, MORPH = __MORPH__;
const root = document.getElementById('root');
async function ws(msg) {
  const r = await fetch(H + '/ws?msg=' + encodeURIComponent(JSON.stringify(msg)));
  let b = {};
  try { b = await r.json(); } catch (e) { /* the status says it */ }
  if (!r.ok || b.error) throw new Error(b.error || ('HTTP ' + r.status));
  return b.result;
}
const refuse = () => Promise.reject(new Error("brAIn's preview is read-only"));
if (!customElements.get('ha-card')) customElements.define('ha-card', class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' }).innerHTML = '<style>:host{display:block;'
      + 'background:var(--ha-card-background,var(--card-background-color));'
      + 'border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);'
      + 'color:var(--primary-text-color)}.h{padding:16px 16px 0;font-size:20px}.h:empty{display:none}'
      + '</style><div class="h"></div><slot></slot>';
  }
  static get observedAttributes() { return ['header']; }
  attributeChangedCallback(_n, _o, v) { this.header = v; }
  set header(v) { this.shadowRoot.querySelector('.h').textContent = v || ''; }
});
const box = (text) => {
  const el = document.createElement('div');
  el.className = 'missing';
  el.textContent = text;
  return el;
};
// A custom card is drawn by its own code (Morph's cards in /config/morph/
// cards are served from this page's morph_cards route), inside a wrapper
// that turns a card that throws — on its config or on being handed hass —
// into a labelled box. A built-in Lovelace card is Home Assistant's to draw.
function customCard(cfg) {
  const type = String((cfg && cfg.type) || '');
  const tag = type.slice(7);
  const wrap = document.createElement('div');
  wrap.style.display = 'contents';
  const fail = (why) => {
    wrap.textContent = '';
    wrap.appendChild(box(type + ' could not be drawn: ' + why));
  };
  let card = null;
  try {
    if (!customElements.get(tag)) throw new Error('its code did not define ' + tag);
    card = document.createElement(tag);
    if (card.setConfig) card.setConfig(cfg);
    wrap.appendChild(card);
  } catch (e) {
    card = null;
    fail((e && e.message) || String(e));
  }
  let current = null;
  Object.defineProperty(wrap, 'hass', {
    get: () => current,
    set: (v) => {
      current = v;
      if (!card) return;
      try { card.hass = v; } catch (e) { card = null; fail((e && e.message) || String(e)); }
    },
  });
  wrap.getCardSize = () => (card && card.getCardSize ? card.getCardSize() : 1);
  return wrap;
}
window.loadCardHelpers = async () => ({ async createCardElement(cfg) {
  const type = String((cfg && cfg.type) || '');
  if (!type.startsWith('custom:')) {
    return box('Lovelace ' + (type || 'card') + ' — drawn by Home Assistant, not in this preview');
  }
  const tag = type.slice(7);
  if (!customElements.get(tag)) {
    await Promise.race([customElements.whenDefined(tag), new Promise((r) => setTimeout(r, 1500))]);
  }
  return customCard(cfg);
} });
// Morph is drawn once every card it hosts has something in its slot (its
// own code, or a box saying why not), or after a bound.
async function morphSettled(el) {
  const until = Date.now() + 7000;
  await new Promise((r) => setTimeout(r, 1500));
  while (Date.now() < until) {
    const root = el.shadowRoot;
    const slots = root ? [...root.querySelectorAll('[data-ll]')] : [];
    if (root && slots.every((s) => s.firstElementChild)) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  await new Promise((r) => setTimeout(r, 400));
}
window.__harnessReady = (async () => {
  const list = await ws({ type: 'get_states' });
  const states = {};
  for (const s of list || []) states[s.entity_id] = s;
  let config = {};
  try { config = await ws({ type: 'get_config' }); } catch (e) { /* defaults */ }
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const hass = {
    states, config, themes: { darkMode: dark, themes: {} }, selectedTheme: null,
    user: { id: 'brain-preview', name: 'Preview', is_admin: true, is_owner: false },
    language: 'en', locale: { language: 'en', number_format: 'language', time_format: 'language' },
    entities: {}, devices: {}, areas: {}, panels: {},
    callService: refuse, callApi: refuse, callWS: ws, hassUrl: (p) => p || '',
    localize: (k) => k, formatEntityState: (s) => (s && s.state) || '',
    connection: { subscribeMessage: async () => () => {}, subscribeEvents: async () => () => {},
                  sendMessagePromise: ws },
  };
  if (MORPH) {
    root.className = 'wrap full';
    await import(H + '/morph/morph-panel.js');
    const el = document.createElement('morph-panel');
    // No version: Morph offers a Reload when the page's version and the
    // integration's differ, and this page has none of its own to compare.
    el.panel = { config: { version: '', cards_url: H + '/morph_cards' } };
    el.narrow = innerWidth < 870;
    el.hass = hass;
    root.appendChild(el);
    await morphSettled(el);
    return;
  }
  for (const [tag, file] of CARDS) {
    try {
      if (!customElements.get(tag)) await import(H + '/js/' + file);
      const Ctor = customElements.get(tag);
      const el = document.createElement(tag);
      const cfg = (Ctor && Ctor.getStubConfig) ? (Ctor.getStubConfig(hass) || {}) : {};
      if (el.setConfig) el.setConfig({ type: 'custom:' + tag, ...cfg });
      el.hass = hass;
      root.appendChild(el);
    } catch (e) {
      const box = document.createElement('div');
      box.className = 'missing';
      box.textContent = tag + ' could not be drawn: ' + ((e && e.message) || e);
      root.appendChild(box);
    }
  }
  await new Promise((r) => setTimeout(r, 800));
})();
"""


def page(name: str) -> str | None:
    """The harness page for ``name``, or None for a name it has none for."""
    entries = PAGES.get(str(name or ""))
    if entries is None:
        return None
    # Nothing off the URL is written into the page: only which catalog
    # entry it named, read back from the catalog.
    morph = entries == PAGES["morph"]
    script = (_SCRIPT.replace("__BASE__", json.dumps(BASE))
              .replace("__CARDS__", json.dumps([] if morph else entries))
              .replace("__MORPH__", "true" if morph else "false"))
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>brAIn preview</title><style>{_THEME}</style></head>"
            "<body><div class=\"wrap\" id=\"root\"></div>"
            f"<script type=\"module\">{script}</script></body></html>")


__all__ = ["BASE", "PAGES", "page"]
