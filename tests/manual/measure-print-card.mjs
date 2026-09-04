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
    /* `hass.services` is the frontend's domain -> service map, and it is
     * the only thing that answers "can this card print". A real dashboard
     * always has several domains in it, so a fixture of one domain would
     * make "the map is populated" and "bruh_print is in it" the same
     * fact. */
    window.__services = (has) => {
      const map = {
        homeassistant: { restart: {}, reload_all: {} },
        persistent_notification: { create: {}, dismiss: {} },
        light: { turn_on: {}, turn_off: {} },
      };
      if (has) {
        map.bruh_print = {
          print_text: {}, print_template: {}, print_label: {},
          reprint: {}, set_roll: {}, print_test: {},
        };
      }
      return map;
    };
    window.__hass = (states, options) => {
      const opts = options || {};
      return {
        states,
        /* `bruhPrint: false` is a house where the integration is not set
         * up; `services` outright is for the shapes a real `hass` never
         * has and this card must survive anyway. */
        services: opts.services === undefined
          ? window.__services(opts.bruhPrint !== false) : opts.services,
        callService(domain, service, data) {
          window.__calls.push({ domain, service, data });
          if (opts.reject) return Promise.reject(opts.reject);
          /* `undefined` means "answer the way the integration does";
           * anything else, including null, is sent back verbatim, which is
           * how a frontend that never asked for response data looks. */
          return Promise.resolve(opts.result === undefined
            ? { response: { printed: 1, side: 'left', notes: [] } }
            : opts.result);
        },
      };
    };
  });
  await page.addScriptTag({ content: CARD });
  return { page, ctx };
};

/* Build the card, hand it a config and a house, put it on the page. Returns
 * the same handle every check below reads, so a case that fails to set up
 * fails once rather than in every assertion after it. */
const build = async (page, config, states, options) => page.evaluate(
  async ([cfg, house, opts]) => {
    const card = document.createElement('bruh-print-card');
    window.__card = card;
    try {
      card.setConfig(cfg);
    } catch (error) {
      return { threw: `setConfig: ${error.message}` };
    }
    if (house) card.hass = window.__hass(house, opts);
    document.getElementById('host').append(card);
    await new Promise((r) => setTimeout(r, 150));
    return { threw: null };
  }, [config, states ?? null, options ?? {}]);

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
  /* No integration means no service and no entities — the service is what
   * this case is really about, since it is the only thing that decides
   * whether Print can work. */
  const setup = await build(page, {
    type: 'custom:bruh-print-card', show_rolls: rolls, show_status: rolls,
  }, {}, { bruhPrint: false });
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
for (const [name, states, options] of [
  ['template', HOUSE, {}],
  /* "empty" here means no integration — no service and no entities. It has
   * to be the service that is gone, because that is the half a missing
   * Print button is about. */
  ['template-empty', {}, { bruhPrint: false }],
]) {
  const { page, ctx } = await open(name);
  const setup = await build(page, {
    type: 'custom:bruh-print-card',
    mode: 'template',
    template: 'Freezer bag',
    fields: [{ key: 'date', label: 'Date', hint: '3 Sep' }],
  }, states, options);
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

/* ── Sensors, but no service: the half that really cannot print ─────── */
/* Every entity this card knows how to read, and no `bruh_print` in
 * `hass.services`. That is a house where the integration is not set up (or
 * has not finished loading), and it is the ONLY thing that may take Print
 * away. */
{
  const name = 'no-service';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' },
    HOUSE, { bruhPrint: false });
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);

  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    return {
      trouble: root.querySelector('.trouble')?.textContent.replace(/\s+/g, ' ') || '',
      enabled: [...root.querySelectorAll('button')]
        .filter((n) => !n.disabled).map((n) => n.textContent.trim()),
    };
  });
  if (!seen.trouble)
    problems.push(`${name}: the card says nothing about a missing service — `
      + 'the rolls render, so from the screen it looks like a working card');
  for (const owed of ['bruh_print.print_text', 'Devices & services'])
    if (!seen.trouble.includes(owed))
      problems.push(`${name}: the block does not mention ${owed} — `
        + `it says "${seen.trouble}"`);
  if (/cannot find the printer sensor/.test(seen.trouble))
    problems.push(`${name}: the block blames the sensors, which are all here`);
  if (seen.enabled.length)
    problems.push(`${name}: ${JSON.stringify(seen.enabled)} still pressable `
      + 'with no service to call');

  const calls = await page.evaluate(async () => {
    const box = window.__card.shadowRoot.querySelector('textarea');
    box.value = 'Spare keys';
    box.dispatchEvent(new Event('input'));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await new Promise((r) => setTimeout(r, 200));
    return window.__calls.length;
  });
  if (calls) problems.push(`${name}: Enter printed anyway (${calls} service calls)`);
  await ctx.close();
}

/* ── The regression: a service, and entities this card cannot name ───── */
/* A renamed device, a renamed entity, a second config entry — any id that
 * does not end in exactly `printer`/`left_roll`/`right_roll` — and 0.4.0
 * disabled every Print button on a card that had printed for months.
 * Printing does not go through the sensors at all. */
const RENAMED = {
  'sensor.label_maker_printer': {
    entity_id: 'sensor.label_maker_printer',
    state: 'LabelWriter 450 Twin Turbo',
    attributes: { ...HOUSE['sensor.bruh_print_printer'].attributes },
  },
  'sensor.label_maker_left_roll': {
    entity_id: 'sensor.label_maker_left_roll',
    state: '1000',
    attributes: { ...HOUSE['sensor.bruh_print_left_roll'].attributes },
  },
};

{
  const name = 'renamed';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' }, RENAMED);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);

  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    const print = root.querySelector('button.primary');
    return {
      trouble: root.querySelector('.trouble')?.textContent.replace(/\s+/g, ' ') || '',
      disabled: print?.disabled,
      pill: root.querySelector('.pill')?.textContent.trim() ?? null,
    };
  });
  if (seen.disabled)
    problems.push(`${name}: Print is disabled on a house whose service is `
      + 'there. Printing is a service call; the sensors are a readout, and '
      + 'gating the action on the readout is what stopped the card printing');
  if (!seen.trouble)
    problems.push(`${name}: nothing says the status entities were not found`);
  for (const owed of ['printer_entity', 'left_roll_entity'])
    if (!seen.trouble.includes(owed))
      problems.push(`${name}: the block does not name ${owed}, which is the `
        + `way out of this — it says "${seen.trouble}"`);
  if (/not set up|Devices & services/.test(seen.trouble))
    problems.push(`${name}: the block sends somebody to set up an integration `
      + 'that is already set up');
  if (seen.pill !== null && /ready/.test(seen.pill))
    problems.push(`${name}: the status pill says "${seen.pill}" with no `
      + 'printer sensor to read it from');

  /* And it really prints. */
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
  else {
    const sent = call.calls[0];
    if (sent.domain !== 'bruh_print' || sent.service !== 'print_text')
      problems.push(`${name}: Print called ${sent.domain}.${sent.service}`);
    if (sent.data.text !== 'Spare keys')
      problems.push(`${name}: Print sent ${JSON.stringify(sent.data.text)}`);
    if ('side' in sent.data)
      problems.push(`${name}: Print sent side=${sent.data.side}`);
  }
  if (!/Printed 1/.test(call.text))
    problems.push(`${name}: nothing said the label printed`);
  await ctx.close();
}

/* ── The named-entity escape hatch the block points at ───────────────── */
{
  const name = 'configured';
  const { page, ctx } = await open(name);
  const setup = await build(page, {
    type: 'custom:bruh-print-card',
    printer_entity: 'sensor.label_maker_printer',
    left_roll_entity: 'sensor.label_maker_left_roll',
  }, RENAMED);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    return {
      trouble: root.querySelector('.trouble')?.textContent.trim() || '',
      names: [...root.querySelectorAll('.roll .what')].map((n) => n.textContent),
      disabled: root.querySelector('button.primary')?.disabled,
    };
  });
  if (seen.trouble)
    problems.push(`${name}: the card still says something is missing after `
      + `being told where to look — "${seen.trouble}"`);
  if (!seen.names.includes('Chemical-Resistant Cryo Labels'))
    problems.push(`${name}: the named roll entity is not on the card `
      + `(${JSON.stringify(seen.names)})`);
  if (seen.disabled) problems.push(`${name}: Print is disabled`);
  await ctx.close();
}

/* ── A second BRUH Print, whose entity ids carry a _2 ────────────────── */
{
  const name = 'second-entry';
  const { page, ctx } = await open(name);
  const house = {};
  for (const [id, entity] of Object.entries(HOUSE))
    house[`${id}_2`] = { ...entity, entity_id: `${id}_2` };
  const setup = await build(page, { type: 'custom:bruh-print-card' }, house);
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    return {
      rolls: root.querySelectorAll('.roll').length,
      trouble: root.querySelector('.trouble')?.textContent.trim() || '',
      disabled: root.querySelector('button.primary')?.disabled,
    };
  });
  if (seen.disabled)
    problems.push(`${name}: Print is disabled because the ids end in _2`);
  if (seen.rolls !== 2)
    problems.push(`${name}: ${seen.rolls} roll boxes — a second config entry `
      + 'suffixes every id, and there is nothing else different about it');
  if (seen.trouble)
    problems.push(`${name}: "${seen.trouble}" about entities that are here`);
  await ctx.close();
}

/* ── `hass.services` in a shape this card cannot read ────────────────── */
/* Fails open, always. A card that refuses to print because it could not
 * answer a question about itself is worse than one that tries and reports
 * what came back. */
{
  const name = 'services-unknown';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' },
    HOUSE, { services: null });
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(() => {
    const root = window.__card.shadowRoot;
    return {
      disabled: root.querySelector('button.primary')?.disabled,
      trouble: root.querySelector('.trouble')?.textContent.trim() || '',
    };
  });
  if (seen.disabled)
    problems.push(`${name}: Print is disabled because hass.services could not `
      + 'be read — an unanswerable question became a refusal');
  if (seen.trouble)
    problems.push(`${name}: "${seen.trouble}" — nothing is known to be wrong`);
  await ctx.close();
}

/* ── A call that resolves with nothing to confirm it ─────────────────── */
/* `return_response` unsupported by the frontend, a service registered
 * without it, an add-on that answered `{}` — the card is told the call was
 * accepted and nothing else, and "Printed 1" is a number it made up. */
for (const [name, result] of [
  ['no-response', { context: { id: 'abc' } }],
  ['null-response', null],
  ['empty-response', { response: {} }],
]) {
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' },
    HOUSE, { result });
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const box = root.querySelector('textarea');
    box.value = 'Spare keys';
    box.dispatchEvent(new Event('input'));
    root.querySelector('button.primary').click();
    await new Promise((r) => setTimeout(r, 250));
    return {
      calls: window.__calls.length,
      message: root.querySelector('.msg')?.textContent.replace(/\s+/g, ' ').trim() || '',
    };
  });
  if (seen.calls !== 1)
    problems.push(`${name}: ${seen.calls} service calls, expected 1`);
  if (/Printed \d/.test(seen.message))
    problems.push(`${name}: the card says "${seen.message}" having been told `
      + 'nothing about a label. A print it cannot confirm is exactly what '
      + '"the card does not print anything" looks like from the other side');
  if (!seen.message)
    problems.push(`${name}: the card said nothing at all after a print`);
  if (!/did not say|nothing back|could not confirm/i.test(seen.message))
    problems.push(`${name}: "${seen.message}" does not say that nothing came `
      + 'back to confirm it');
  await ctx.close();
}

/* ── An answer that says no label came out ───────────────────────────── */
{
  const name = 'printed-nothing';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' }, HOUSE,
    { result: { response: { printed: 0, side: '', notes: ['The printer did not answer.'] } } });
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const message = await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const box = root.querySelector('textarea');
    box.value = 'Spare keys';
    box.dispatchEvent(new Event('input'));
    root.querySelector('button.primary').click();
    await new Promise((r) => setTimeout(r, 250));
    const msg = root.querySelector('.msg');
    return { text: msg?.textContent.replace(/\s+/g, ' ').trim() || '',
             bad: msg?.classList.contains('err') };
  });
  if (/^Printed 0/.test(message.text))
    problems.push(`${name}: "${message.text}" reads as a working card that `
      + 'printed a zero');
  if (!message.bad)
    problems.push(`${name}: "${message.text}" is rendered as a success, and `
      + 'the add-on has just said no label came out');
  if (!message.text.includes('The printer did not answer.'))
    problems.push(`${name}: the add-on's note is not shown — it is the only `
      + `thing that says why. The card says "${message.text}"`);
  await ctx.close();
}

/* ── A refusal, which is the useful half ─────────────────────────────── */
{
  const name = 'refused';
  const sentence = 'The left roll holds Cryogenic Labels and this label is '
    + 'for Chemical-Resistant Cryo Labels.';
  const { page, ctx } = await open(name);
  const setup = await build(page, { type: 'custom:bruh-print-card' },
    HOUSE, { reject: { message: sentence, code: 'unknown_error' } });
  if (setup.threw) problems.push(`${name}: ${setup.threw}`);
  const seen = await page.evaluate(async () => {
    const root = window.__card.shadowRoot;
    const box = root.querySelector('textarea');
    box.value = 'Spare keys';
    box.dispatchEvent(new Event('input'));
    root.querySelector('button.primary').click();
    await new Promise((r) => setTimeout(r, 250));
    const msg = root.querySelector('.msg');
    return {
      text: msg?.textContent.replace(/\s+/g, ' ').trim() || '',
      bad: msg?.classList.contains('err'),
      busy: root.querySelector('button.primary')?.disabled,
    };
  });
  if (!seen.text.includes('Cryogenic Labels'))
    problems.push(`${name}: the add-on's own sentence is not what is shown — `
      + `the card says "${seen.text}". Replacing it with "print failed" is `
      + 'how a fixable mistake becomes a mystery');
  if (!seen.bad) problems.push(`${name}: a refusal is not rendered as one`);
  if (seen.busy)
    problems.push(`${name}: Print is still disabled after a failed call — `
      + 'the card is stuck on "Printing…"');
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
