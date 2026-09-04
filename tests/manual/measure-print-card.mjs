/* Playwright measure for the BRUH Print Lovelace card.
 *
 *   node tests/manual/measure-print-card.mjs
 *
 * Playwright resolves from the repo root's node_modules, the way CI installs
 * it; in this repo's sandbox the browser is not where it expects, so:
 *
 *   CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \
 *   node tests/manual/measure-print-card.mjs
 *
 * Why this exists: nothing in this repository had ever EXECUTED the card.
 * Every test of it read the file — that it defines a custom element, that it
 * imports nothing, that it calls no service the integration lacks — and a
 * grep for a line is not a test of what the line does. So the card shipped a
 * release in which the only thing it could say about a house with no
 * integration was a sentence inside the rolls block, which `show_rolls:
 * false` deletes; and the one rule the card exists to hold — the label names
 * the bay, so it never sends a `side` — was asserted by a regular expression
 * over the source rather than by watching a Print land.
 *
 * So this loads the real file into a real browser against a stubbed `hass`
 * and drives it. `ha-card` is stubbed because it is Home Assistant's element,
 * not ours; everything else on screen is the card's own.
 */
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CARD = readFileSync(fileURLToPath(
  new URL('../../bruh-print/lovelace/bruh-print-card.js', import.meta.url)), 'utf8');

const problems = [];

/* A house with a Twin Turbo, both rolls loaded, nothing wrong. The
 * attributes are the ones sensor.py publishes — a fixture that invents its
 * own shape would only ever agree with itself. */
const HOUSE = {
  'sensor.bruh_print_printer': {
    entity_id: 'sensor.bruh_print_printer',
    state: 'LabelWriter 450 Twin Turbo',
    attributes: {
      reason: '', connected: true, printers_found: 1, two_rolls: true,
      dots_across: 672, printable_inches: 2.24, serial: 'S1',
      recognised: true, error: '', friendly_name: 'BRUH Print Printer',
    },
  },
  'sensor.bruh_print_left_roll': {
    entity_id: 'sensor.bruh_print_left_roll',
    state: '1000',
    attributes: {
      loaded: true, stock: 'edcc-082wh',
      stock_name: 'Chemical-Resistant Cryo Labels',
      size: '2.25" × 1.25"', friendly_name: 'BRUH Print Left roll',
    },
  },
  'sensor.bruh_print_right_roll': {
    entity_id: 'sensor.bruh_print_right_roll',
    state: '350',
    attributes: {
      loaded: true, stock: 'ed1f-060wh', stock_name: 'Cryogenic Labels',
      size: '0.56" × 3.44"', friendly_name: 'BRUH Print Right roll',
    },
  },
  'binary_sensor.bruh_print_problem': {
    entity_id: 'binary_sensor.bruh_print_problem',
    state: 'off',
    attributes: { reason: '', friendly_name: 'BRUH Print Problem' },
  },
};

const b = await chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] }
    : { args: ['--no-sandbox'] });

/* One page per case: a card that threw once has a shadow root full of
 * whatever it managed to build, and the next case would be measuring that. */
const open = async (name, { width = 400, touch = false } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height: 900 },
    deviceScaleFactor: 2, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push(`${name}: page error — ${e.message}`));
  page.on('console', (m) => {
    /* The card prints its own version banner at info; an error is not
     * something it does on purpose. */
    if (m.type() === 'error') problems.push(`${name}: console error — ${m.text()}`);
  });
  /* The viewport meta is not decoration: without it Chromium's mobile
   * emulation lays a page out at 980px and scales it down, so a card that
   * overflowed a phone would measure as fitting one. Every Home Assistant
   * dashboard has this tag. */
  await page.setContent('<!doctype html><html><head>'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '</head><body><div id="host"></div></body></html>');
  await page.evaluate(() => {
    /* Home Assistant's own card shell, to the extent the card uses it: a
     * box that slots its children. Stubbing more would be measuring the
     * stub. */
    customElements.define('ha-card', class extends HTMLElement {
      connectedCallback() {
        if (!this.shadowRoot)
          this.attachShadow({ mode: 'open' }).innerHTML =
            '<style>:host{display:block}</style><slot></slot>';
      }
    });
    window.__calls = [];
    window.__hass = (states) => ({
      states,
      callService(domain, service, data) {
        window.__calls.push({ domain, service, data });
        return Promise.resolve({ response: { printed: 1, side: 'left', notes: [] } });
      },
    });
  });
  await page.addScriptTag({ content: CARD });
  return { page, ctx };
};

/* Build the card, hand it a config and a house, put it on the page. Returns
 * the same handle every check below reads, so a case that fails to set up
 * fails once rather than in every assertion after it. */
const build = async (page, config, states) => page.evaluate(
  async ([cfg, house]) => {
    const card = document.createElement('bruh-print-card');
    window.__card = card;
    try {
      card.setConfig(cfg);
    } catch (error) {
      return { threw: `setConfig: ${error.message}` };
    }
    if (house) card.hass = window.__hass(house);
    document.getElementById('host').append(card);
    await new Promise((r) => setTimeout(r, 150));
    return { threw: null };
  }, [config, states ?? null]);

/* Every target in the card, measured where it is drawn rather than read off
 * the stylesheet: a 44px rule loses to a later block of equal specificity,
 * and only the layout knows which won. */
const targets = (page) => page.evaluate(() => {
  const root = window.__card.shadowRoot;
  const out = [];
  for (const node of root.querySelectorAll('button, input, select, textarea')) {
    const rect = node.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    out.push({
      name: node.className || node.tagName.toLowerCase(),
      height: rect.height,
      font: parseFloat(getComputedStyle(node).fontSize),
      type: node.type || '',
    });
  }
  return out;
});

const measureTargets = async (page, name, { coarse }) => {
  for (const t of await targets(page)) {
    if (t.type !== 'checkbox' && t.height < 44)
      problems.push(`${name}: ${t.name} is ${t.height.toFixed(0)}px tall — `
        + 'under the 44px this card sets for itself');
    if (coarse && t.font < 16 && ['textarea', 'input'].includes(t.name))
      problems.push(`${name}: ${t.name} is ${t.font}px on touch — iOS zooms in `
        + 'and stays there');
  }
};

/* ── The happy path ──────────────────────────────────────────────────── */
{
  const name = 'happy';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' }, HOUSE);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);

  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    return {
      card: !!root.querySelector('ha-card'),
      rolls: root.querySelectorAll('.roll').length,
      trouble: !!root.querySelector('.trouble'),
      names: [...root.querySelectorAll('.roll .what')].map((n) => n.textContent),
      print: !!root.querySelector('button.primary'),
      disabled: root.querySelector('button.primary')?.disabled,
    };
  });
  if (!seen.card) problems.push(`${name}: no ha-card was rendered`);
  if (seen.rolls !== 2)
    problems.push(`${name}: ${seen.rolls} roll boxes for a Twin Turbo with `
      + 'both rolls loaded, expected 2');
  if (!seen.names.includes('Chemical-Resistant Cryo Labels')
      || !seen.names.includes('Cryogenic Labels'))
    problems.push(`${name}: the roll boxes do not name what is loaded `
      + `(${JSON.stringify(seen.names)})`);
  if (seen.trouble)
    problems.push(`${name}: the "cannot find" block is shown on a house that `
      + 'has every sensor');
  if (!seen.print) problems.push(`${name}: there is no Print button`);
  if (seen.disabled)
    problems.push(`${name}: Print is disabled on a working house`);

  /* Type something, press Print, and read what went out. `stock` names the
   * label; the add-on knows which bay it is in, so a `side` here is the one
   * thing able to contradict it. */
  const call = await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const box = root.querySelector('textarea');
    box.value = 'Spare keys';
    box.dispatchEvent(new Event('input'));
    root.querySelector('button.primary').click();
    await new Promise((r) => setTimeout(r, 250));
    return { calls: window.__calls, text: root.textContent.replace(/\s+/g, ' ') };
  });
  if (call.calls.length !== 1)
    problems.push(`${name}: Print made ${call.calls.length} service calls, expected 1`);
  const sent = call.calls[0];
  if (sent) {
    if (sent.domain !== 'bruh_print' || sent.service !== 'print_text')
      problems.push(`${name}: Print called ${sent.domain}.${sent.service}`);
    if (sent.data.text !== 'Spare keys')
      problems.push(`${name}: Print sent ${JSON.stringify(sent.data.text)} as the text`);
    if (!sent.data.stock)
      problems.push(`${name}: Print sent no stock — the label is what names the bay`);
    if ('side' in sent.data)
      problems.push(`${name}: Print sent side=${sent.data.side}. The card may `
        + 'never name a bay: the add-on knows which roll holds which label, '
        + 'and a card that sends a side is the one place able to contradict it');
  }
  if (!/Printed 1/.test(call.text))
    problems.push(`${name}: nothing said the label printed`);

  await measureTargets(page, name, { coarse: false });
  await ctx.close();
}

/* ── A phone, and the quick buttons ──────────────────────────────────── */
{
  const name = 'phone';
  const { page, ctx } = await open(name, { width: 390, touch: true });
  const setup = await build(page, {
    type: 'custom:bruh-print-card',
    quick: [{ label: 'Leftovers', text: 'Leftovers' }],
  }, HOUSE);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const wide = await page.evaluate(() =>
    window.__card.shadowRoot.querySelector('ha-card').scrollWidth);
  if (wide > 390 + 1)
    problems.push(`${name}: the card lays out ${wide}px wide in a 390px window`);
  await measureTargets(page, name, { coarse: true });
  await ctx.close();
}

/* ── No integration, no add-on: the case the card could not describe ─── */
for (const rolls of [true, false]) {
  const name = `nothing-found${rolls ? '' : '-rolls-off'}`;
  const { page, ctx } = await open(name);
  const setup = await build(page, {
    type: 'custom:bruh-print-card', show_rolls: rolls, show_status: rolls,
  }, {});
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);

  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    const buttons = [...root.querySelectorAll('button')];
    return {
      text: root.textContent.replace(/\s+/g, ' ').trim(),
      trouble: root.querySelector('.trouble')?.textContent.replace(/\s+/g, ' ') || '',
      pill: root.querySelector('.pill')?.textContent.trim() ?? null,
      enabled: buttons.filter((n) => !n.disabled).map((n) => n.textContent.trim()),
    };
  });
  if (!seen.trouble)
    problems.push(`${name}: nothing on the card says what is missing`);
  for (const owed of ['printer sensor', 'roll sensors', 'add-on', 'Devices'])
    if (!seen.trouble.includes(owed))
      problems.push(`${name}: the block does not mention ${owed} — `
        + `it says "${seen.trouble}"`);
  if (!/card \d+\.\d+\.\d+/.test(seen.trouble))
    problems.push(`${name}: the block does not carry the card's version, so a `
      + 'screenshot of it cannot say which card this is');
  if (seen.pill !== null && /ready/.test(seen.pill))
    problems.push(`${name}: the status pill says "${seen.pill}" on a card that `
      + 'cannot find a printer sensor — an absent sensor falls back to the '
      + 'word for a working one');
  if (seen.enabled.length)
    problems.push(`${name}: ${JSON.stringify(seen.enabled)} still pressable with `
      + 'no integration — a button that cannot work is worse than no button');

  /* And pressing it anyway (the keyboard route into printing does not go
   * through the button) may not call a service. */
  const calls = await page.evaluate(async () => {
    const box = window.__card.shadowRoot.querySelector('textarea');
    if (box) {
      box.value = 'Spare keys';
      box.dispatchEvent(new Event('input'));
      box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    }
    await new Promise((r) => setTimeout(r, 200));
    return window.__calls.length;
  });
  if (calls)
    problems.push(`${name}: Enter printed anyway (${calls} service calls)`);
  await ctx.close();
}

/* ── Template mode, on a working house and on an empty one ───────────── */
for (const [name, states] of [['template', HOUSE], ['template-empty', {}]]) {
  const { page, ctx } = await open(name);
  const setup = await build(page, {
    type: 'custom:bruh-print-card',
    mode: 'template',
    template: 'Freezer bag',
    fields: [{ key: 'date', label: 'Date', hint: '3 Sep' }],
  }, states);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    const print = root.querySelector('button.primary');
    return {
      print: !!print,
      disabled: print?.disabled,
      fields: root.querySelectorAll('input[type="text"], .field input').length,
    };
  });
  if (!seen.print)
    problems.push(`${name}: a template card with no Print button reads as one `
      + 'still loading');
  if (!seen.fields)
    problems.push(`${name}: the template's fields are not on the form`);
  if (name === 'template' && seen.disabled)
    problems.push(`${name}: Print is disabled on a working house`);
  if (name === 'template-empty' && !seen.disabled)
    problems.push(`${name}: Print is offered with no integration behind it`);

  if (name === 'template') {
    const sent = await page.evaluate(async () => {
      const root = window.__card.shadowRoot;
      const box = root.querySelector('.field input');
      box.value = '3 Sep';
      box.dispatchEvent(new Event('input'));
      root.querySelector('button.primary').click();
      await new Promise((r) => setTimeout(r, 250));
      return window.__calls[0];
    });
    if (!sent || sent.service !== 'print_template')
      problems.push(`${name}: Print called ${sent ? sent.service : 'nothing'}`);
    else {
      if (sent.data.fields?.date !== '3 Sep')
        problems.push(`${name}: the field did not reach the service `
          + `(${JSON.stringify(sent.data.fields)})`);
      if ('side' in sent.data)
        problems.push(`${name}: Print sent side=${sent.data.side}`);
      if (!sent.data.stock)
        problems.push(`${name}: Print sent no stock`);
    }
  }
  await ctx.close();
}

/* ── The editor, which is the other custom element in the file ───────── */
{
  const name = 'editor';
  const { page, ctx } = await open(name);
  const threw = await page.evaluate(async () => {
    const editor = document.createElement('bruh-print-card-editor');
    try {
      editor.setConfig({ type: 'custom:bruh-print-card', mode: 'template',
                         template: 'Freezer bag' });
    } catch (error) { return error.message; }
    document.getElementById('host').append(editor);
    await new Promise((r) => setTimeout(r, 100));
    window.__card = editor;
    return editor.shadowRoot.querySelectorAll('.field').length ? null
      : 'the editor rendered no fields';
  });
  if (threw) problems.push(`${name}: ${threw}`);
  await measureTargets(page, name, { coarse: false });
  await ctx.close();
}

await b.close();
if (problems.length) {
  console.error('FAILED:\n- ' + problems.join('\n- '));
  process.exit(1);
}
console.log('measure-print-card: the card renders, prints, and says what is missing');
