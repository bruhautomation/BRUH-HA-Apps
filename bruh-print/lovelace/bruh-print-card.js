/* BRUH Print — a Lovelace card that prints.
 *
 * Three decisions are worth knowing.
 *
 * It reads the SENSORS, never the panel. A custom card runs in whoever's
 * browser is looking at the dashboard, which may be a phone on mobile data
 * through Nabu Casa — it has no route to the add-on's ingress port and no
 * business having one. Everything it shows comes from the entities the
 * integration publishes, and everything it does goes out as a service call
 * over the connection the dashboard already has.
 *
 * It is written in plain custom elements with no build step and no imports.
 * A card that needs a bundler is a card that cannot ship inside an add-on
 * image, and one that imports LitElement off a CDN is a card that breaks the
 * day the CDN is unreachable — which, on a Home Assistant box, is a fairly
 * ordinary Tuesday.
 *
 * And it re-renders from `hass` rather than keeping its own copy of the
 * state. Home Assistant sets that property on every state change; a card
 * that caches is a card showing an empty roll five minutes after somebody
 * reloaded it.
 */

const CARD_VERSION = '0.4.0';

/* eslint-disable no-console */
console.info(
  `%c BRUH PRINT CARD %c ${CARD_VERSION} `,
  'background:#0b6bcb;color:#fff;font-weight:700;border-radius:3px 0 0 3px',
  'background:#16181d;color:#fff;border-radius:0 3px 3px 0',
);

const DEFAULTS = {
  title: 'BRUH Print',
  mode: 'text',          // 'text' | 'template'
  template: '',
  stock: '',
  copies: 1,
  show_status: true,
  show_rolls: true,
  quick: [],             // one-press buttons: [{label, text} | {label, template, fields}]
};

const css = `
  :host { display: block; }
  ha-card { padding: 16px; }
  .head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .head h2 { margin: 0; font-size: 18px; font-weight: 600; flex: 1 1 auto;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill { display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px; font-size: 12px;
    background: var(--secondary-background-color);
    color: var(--secondary-text-color); white-space: nowrap; }
  .pill .dot { width: 8px; height: 8px; border-radius: 50%;
    background: var(--success-color, #1f9254); }
  .pill.bad { background: color-mix(in srgb, var(--error-color, #c0392b) 16%, transparent);
    color: var(--error-color, #c0392b); }
  .pill.bad .dot { background: var(--error-color, #c0392b); }

  .rolls { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    margin-bottom: 14px; }
  .roll { padding: 9px 11px; border-radius: 10px;
    background: var(--secondary-background-color); }
  .roll .who { font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--secondary-text-color); }
  .roll .what { font-size: 14px; font-weight: 550; margin: 2px 0 5px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .roll .bar { height: 5px; border-radius: 999px; overflow: hidden;
    background: var(--divider-color); }
  .roll .bar > i { display: block; height: 100%;
    background: var(--primary-color); }
  .roll .est { font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
  /* A roll box is a button when there is a choice to make, and a readout
     when there is not — one loaded roll is not a selection. Both draw the
     same, so the card does not change shape when a second roll is set. */
  button.roll { width: 100%; text-align: left; font: inherit; cursor: pointer;
    min-height: 44px; border: 1px solid var(--divider-color, #0002);
    background: var(--card-background-color, #fff); }
  button.roll.on { border-color: var(--primary-color);
    box-shadow: 0 0 0 1px var(--primary-color) inset; }
  button.roll.on .who { color: var(--primary-color); font-weight: 700; }
  button.roll:focus-visible { outline: 2px solid var(--primary-color);
    outline-offset: 2px; }

  .field { display: block; margin-bottom: 10px; }
  .field > span { display: block; font-size: 12px; font-weight: 600;
    color: var(--secondary-text-color); margin-bottom: 4px; }
  input, select, textarea {
    width: 100%; box-sizing: border-box; padding: 10px 11px; min-height: 44px;
    font: inherit; font-size: 16px; border-radius: 9px;
    border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color);
  }
  textarea { resize: vertical; min-height: 60px; }
  .row { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
  .row .field { flex: 1 1 120px; margin-bottom: 0; }
  .row .field.narrow { flex: 0 0 96px; }

  .quick { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  button {
    font: inherit; font-size: 15px; font-weight: 550; cursor: pointer;
    min-height: 44px; padding: 0 16px; border-radius: 9px;
    border: 1px solid var(--divider-color);
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
  }
  button.primary { background: var(--primary-color);
    border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  button[disabled] { opacity: .5; cursor: progress; }
  .actions { display: flex; gap: 10px; align-items: center; margin-top: 14px;
    flex-wrap: wrap; }
  .msg { margin-top: 12px; padding: 10px 12px; border-radius: 9px;
    font-size: 13.5px; line-height: 1.45; }
  .msg.ok { background: color-mix(in srgb, var(--success-color, #1f9254) 14%, transparent); }
  .msg.err { background: color-mix(in srgb, var(--error-color, #c0392b) 14%, transparent);
    color: var(--error-color, #c0392b); }
  .empty { color: var(--secondary-text-color); font-size: 14px; }

  /* The card cannot work. Not styled as an error — nothing has gone
     wrong at the printer — but it has to be read before the form under
     it, which is why it sits directly under the title. */
  .trouble { margin-bottom: 14px; padding: 11px 13px; border-radius: 10px;
    background: var(--secondary-background-color);
    border-left: 4px solid var(--warning-color, #e0a30c); }
  .trouble p { margin: 0 0 6px; font-size: 13.5px; line-height: 1.45; }
  .trouble p:last-child { margin-bottom: 0; }
  .trouble .what { font-weight: 600; }
  .trouble .who { font-size: 11.5px; color: var(--secondary-text-color); }
`;

class BruhPrintCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = { ...DEFAULTS };
    this._busy = false;
    this._message = null;
    /* The form's own values live here, not in the DOM, because `hass` is set
     * on every state change in the house — several times a second on a busy
     * install — and a re-render that read the inputs back would fight
     * whoever is typing. So the DOM is rebuilt only when something the card
     * actually shows has changed, and the fields are restored from here. */
    this._form = { text: '', fields: {}, copies: null, stock: '' };
    this._signature = '';
  }

  static getConfigElement() { return document.createElement('bruh-print-card-editor'); }

  static getStubConfig(hass) {
    const found = Object.keys(hass?.states || {})
      .find((id) => id.startsWith('sensor.') && id.includes('bruh_print') && id.includes('printer'));
    return { type: 'custom:bruh-print-card', title: 'BRUH Print', mode: 'text',
             show_status: !!found };
  }

  setConfig(config) {
    if (config.mode && !['text', 'template'].includes(config.mode))
      throw new Error('mode must be "text" or "template"');
    if (config.mode === 'template' && !config.template)
      throw new Error('a template card needs a template name');
    this._config = { ...DEFAULTS, ...config };
    this._form.copies = null;
    this._form.stock = '';
    this._signature = '';
    this._render();
  }

  getCardSize() {
    return 3 + (this._config.show_rolls ? 1 : 0) + (this._config.quick.length ? 1 : 0);
  }

  set hass(hass) {
    this._hass = hass;
    /* Re-render only when what the card displays has moved. Without this the
     * card rebuilds its DOM on every state change in the house and the
     * cursor jumps out of the text box mid-word. */
    const next = JSON.stringify([this._state('printer'), this._state('problem'),
      this._rollState('left'), this._rollState('right'), this._busy, this._message]);
    if (next !== this._signature) {
      this._signature = next;
      this._render();
    }
  }

  /* ── Entity lookup ──────────────────────────────────────────────────
   * By suffix rather than by a configured entity id. The integration is
   * single-instance and names its entities itself, so asking a person to
   * paste five entity ids into a card config is five chances to paste the
   * wrong one — and a card that silently shows nothing because one is a typo
   * is worse than one that finds them. An explicit id in the config still
   * wins, for the house that has renamed them. */
  _find(suffix) {
    const configured = this._config[`${suffix}_entity`];
    if (configured) return this._hass?.states?.[configured] || null;
    const states = this._hass?.states || {};
    const id = Object.keys(states).find((key) =>
      /^(sensor|binary_sensor)\./.test(key)
      && key.includes('bruh_print')
      && key.endsWith(suffix));
    return id ? states[id] : null;
  }

  _state(suffix) { return this._find(suffix)?.state ?? null; }

  _rollState(side) {
    const entity = this._find(`${side}_roll`);
    if (!entity) return null;
    return `${entity.state}|${entity.attributes.stock_name || ''}|${entity.attributes.loaded}`;
  }

  /* ── Render ─────────────────────────────────────────────────────────── */
  _render() {
    if (!this.shadowRoot) return;
    const config = this._config;
    const problem = this._find('problem');
    const printer = this._find('printer');

    /* Worked out once per render and read by every Print button: a
     * button that cannot work is worse than no button, because pressing
     * it produces a failure about a service call rather than the sentence
     * above it. */
    const missing = this._missing();
    this._blocked = missing.length > 0;

    const root = document.createElement('div');
    const style = document.createElement('style');
    style.textContent = css;

    const card = document.createElement('ha-card');

    const head = document.createElement('div');
    head.className = 'head';
    const title = document.createElement('h2');
    title.textContent = config.title;
    head.append(title);

    if (config.show_status) {
      const pill = document.createElement('span');
      /* `ready` is what an absent printer sensor falls back to, so a card
       * that found nothing at all used to say ready in the same breath as
       * the block below it says it cannot find anything. The pill reports
       * the missing setup first, because that is what is wrong. */
      const trouble = this._blocked || problem?.state === 'on';
      pill.className = 'pill' + (trouble ? ' bad' : '');
      const dot = document.createElement('span');
      dot.className = 'dot';
      const text = document.createElement('span');
      if (this._blocked) text.textContent = 'not set up';
      else text.textContent = trouble
        ? (problem?.attributes?.reason || 'not ready')
        : (printer?.state || 'ready');
      pill.append(dot, text);
      pill.title = trouble ? (problem?.attributes?.reason || '') : '';
      head.append(pill);
    }
    card.append(head);

    /* Shown whatever `show_rolls` and `show_status` say. The one line
     * the card used to have about this lived inside the rolls block, so
     * turning the rolls off turned off the only thing that could explain
     * an empty card. */
    if (this._blocked) card.append(this._trouble(missing));

    if (config.show_rolls) card.append(this._rolls());
    if (config.quick.length) card.append(this._quickRow());
    card.append(config.mode === 'template' ? this._templateForm() : this._textForm());

    if (this._message) {
      const message = document.createElement('div');
      message.className = 'msg ' + (this._message.bad ? 'err' : 'ok');
      message.textContent = this._message.text;
      card.append(message);
    }

    root.append(style, card);
    this.shadowRoot.replaceChildren(root);
  }

  /* ── When there is nothing to print with ────────────────────────────
   * Two things reach this card as an empty screen and neither is about
   * the printer: the integration is not set up, or the add-on is stopped
   * and has never published a sensor. A text box and a Print button
   * cannot say either, and pressing Print says only that a service call
   * failed — so the card names what it went looking for and what to do
   * about it, and stops offering the button.
   *
   * The version rides along because a screenshot of a broken dashboard
   * should answer "which card is this" without anybody having to ask —
   * and a browser holding a month-old cached copy is one of the answers.
   */
  _missing() {
    const out = [];
    if (!this._find('printer')) out.push('the printer sensor');
    if (!this._find('left_roll') && !this._find('right_roll'))
      out.push('the roll sensors');
    return out;
  }

  _trouble(missing) {
    const box = document.createElement('div');
    box.className = 'trouble';
    const what = document.createElement('p');
    what.className = 'what';
    what.textContent = `This card cannot find ${missing.join(' or ')}.`;
    const todo = document.createElement('p');
    todo.textContent = 'Check that the BRUH Print add-on is running, and that '
      + 'BRUH Print is set up under Settings \u2192 Devices & services. The '
      + 'add-on is what talks to the printer; the integration is what puts it '
      + 'in here.';
    const who = document.createElement('p');
    who.className = 'who';
    who.textContent = `BRUH Print card ${CARD_VERSION}`;
    box.append(what, todo, who);
    return box;
  }

  /* The loaded rolls ARE the label picker.
   *
   * A roll is not a thing anybody wants to choose — it is where the label
   * happens to be, which the add-on already knows. What a person wants to
   * choose is which label they are printing, and on a Twin Turbo that is
   * exactly a choice between the two things on this card. So the boxes are
   * the selector: press one, and that is what prints. A separate "Roll"
   * dropdown under them was the same decision asked twice, in the harder
   * of the two vocabularies.
   *
   * A single-roll printer draws one box and it is simply what is loaded —
   * a selector offering one choice is a readout, and it is styled as one. */
  _selectedStock() {
    /* The config's stock wins until somebody presses a box, so a dashboard
     * pinned to one label keeps printing that label. */
    if (this._form.stock) return this._form.stock;
    if (this._config.stock) return this._config.stock;
    const first = this._loadedRolls()[0];
    return first ? first.stock : '';
  }

  _loadedRolls() {
    const printer = this._find('printer');
    const sides = printer?.attributes?.two_rolls === false ? ['left'] : ['left', 'right'];
    const out = [];
    for (const side of sides) {
      const entity = this._find(`${side}_roll`);
      if (!entity || !entity.attributes.loaded) continue;
      out.push({ side, entity, stock: entity.attributes.stock || '' });
    }
    return out;
  }

  _rolls() {
    const wrap = document.createElement('div');
    wrap.className = 'rolls';
    const printer = this._find('printer');
    const sides = printer?.attributes?.two_rolls === false ? ['left'] : ['left', 'right'];
    const choosable = this._loadedRolls().length > 1;
    const chosen = this._selectedStock();
    for (const side of sides) {
      const entity = this._find(`${side}_roll`);
      if (!entity) continue;
      const loaded = !!entity.attributes.loaded;
      const box = document.createElement(choosable && loaded ? 'button' : 'div');
      box.className = 'roll';
      if (choosable && loaded) {
        box.classList.add('pick');
        if (entity.attributes.stock === chosen) box.classList.add('on');
        box.setAttribute('aria-pressed',
          entity.attributes.stock === chosen ? 'true' : 'false');
        box.addEventListener('click', () => {
          this._form.stock = entity.attributes.stock;
          this._signature = '';
          this._render();
        });
      }
      const who = document.createElement('div');
      who.className = 'who';
      who.textContent = loaded && choosable
        ? (entity.attributes.stock === chosen ? 'printing on this' : 'tap to use')
        : (side === 'left' ? 'left roll' : 'right roll');
      const what = document.createElement('div');
      what.className = 'what';
      what.textContent = loaded
        ? (entity.attributes.stock_name || entity.attributes.stock)
        : 'not set';
      box.append(who, what);
      if (entity.attributes.loaded) {
        const remaining = Number(entity.state) || 0;
        const bar = document.createElement('div');
        bar.className = 'bar';
        const fill = document.createElement('i');
        /* No per-roll capacity reaches the card, so the bar is scaled
         * against the highest count this roll has been set to since the
         * dashboard loaded. It is a shape, not a measurement — which is why
         * the number underneath says "about". */
        this._peak = this._peak || {};
        this._peak[side] = Math.max(this._peak[side] || 0, remaining);
        fill.style.width = `${Math.min(100, remaining / (this._peak[side] || 1) * 100)}%`;
        bar.append(fill);
        const est = document.createElement('div');
        est.className = 'est';
        est.textContent = `about ${remaining} left · ${entity.attributes.size || ''}`;
        box.append(bar, est);
      }
      wrap.append(box);
    }
    /* Nothing to draw is not explained here: `_trouble` above has
     * already said what is missing, and it says it whether or not the
     * rolls are switched on. */
    return wrap;
  }

  _quickRow() {
    const wrap = document.createElement('div');
    wrap.className = 'quick';
    for (const item of this._config.quick) {
      const button = document.createElement('button');
      button.textContent = item.label || item.text || item.template || 'Print';
      button.disabled = this._busy || this._blocked;
      button.addEventListener('click', () => this._quickPrint(item));
      wrap.append(button);
    }
    return wrap;
  }

  _textForm() {
    const wrap = document.createElement('div');

    const field = document.createElement('label');
    field.className = 'field';
    const label = document.createElement('span');
    label.textContent = 'What should it say?';
    const input = document.createElement('textarea');
    input.rows = 2;
    input.placeholder = 'Chest freezer — chili';
    input.value = this._form.text;
    input.addEventListener('input', () => { this._form.text = input.value; });
    input.addEventListener('keydown', (event) => {
      /* Enter prints; shift+enter is a line break. This card exists to be
       * one gesture at a bench, and reaching for a button after typing is
       * the gesture it is meant to remove. */
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        this._print();
      }
    });
    field.append(label, input);
    wrap.append(field, this._commonRow());

    const actions = document.createElement('div');
    actions.className = 'actions';
    const print = document.createElement('button');
    print.className = 'primary';
    print.textContent = this._busy ? 'Printing…' : 'Print';
    print.disabled = this._busy || this._blocked;
    print.addEventListener('click', () => this._print());
    actions.append(print);
    wrap.append(actions);
    return wrap;
  }

  _templateForm() {
    const wrap = document.createElement('div');
    const template = this._config.template;

    const fields = this._config.fields || [];
    if (!fields.length) {
      const note = document.createElement('p');
      note.className = 'empty';
      note.textContent =
        `Printing "${template}" with whatever it fills in for itself. `
        + `Add a "fields:" list to this card to ask for values.`;
      wrap.append(note);
    }
    for (const field of fields) {
      const key = typeof field === 'string' ? field : field.key;
      if (!key) continue;
      const holder = document.createElement('label');
      holder.className = 'field';
      const label = document.createElement('span');
      label.textContent = (typeof field === 'object' && field.label)
        || key.replace(/_/g, ' ');
      const input = document.createElement('input');
      input.value = this._form.fields[key] ?? (field.default || '');
      if (typeof field === 'object' && field.hint) input.placeholder = field.hint;
      input.addEventListener('input', () => { this._form.fields[key] = input.value; });
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') { event.preventDefault(); this._print(); }
      });
      holder.append(label, input);
      wrap.append(holder);
    }

    wrap.append(this._commonRow());

    const actions = document.createElement('div');
    actions.className = 'actions';
    const print = document.createElement('button');
    print.className = 'primary';
    print.textContent = this._busy ? 'Printing…' : `Print ${template}`;
    print.disabled = this._busy || this._blocked;
    print.addEventListener('click', () => this._print());
    actions.append(print);
    /* Appended whether or not the sensors are there, disabled when they
     * are not: a form that loses its button reads as a card still
     * loading, and `_trouble` above has already said which it is. */
    wrap.append(actions);
    return wrap;
  }

  _commonRow() {
    const row = document.createElement('div');
    row.className = 'row';

    const copiesField = document.createElement('label');
    copiesField.className = 'field narrow';
    const copiesLabel = document.createElement('span');
    copiesLabel.textContent = 'Copies';
    const copies = document.createElement('input');
    copies.type = 'number';
    copies.min = '1';
    copies.max = '500';
    copies.value = String(this._form.copies ?? this._config.copies ?? 1);
    copies.addEventListener('input', () => { this._form.copies = Number(copies.value) || 1; });
    copiesField.append(copiesLabel, copies);
    row.append(copiesField);

    /* No roll picker. The rolls above are the selector — pressing one is
     * how you say which label this prints on, in the vocabulary of the
     * thing you are actually choosing. */
    return row;
  }

  /* ── Printing ───────────────────────────────────────────────────────── */
  async _call(service, data) {
    this._busy = true;
    this._message = null;
    this._signature = '';
    this._render();
    try {
      /* return_response, so the card can say which roll it landed on. A
       * "printed" toast that cannot name the roll is a toast that does not
       * answer the one thing a Twin Turbo user is checking. */
      const result = await this._hass.callService('bruh_print', service, data,
        undefined, false, true);
      const answer = result?.response || {};
      const side = answer.side ? ` on the ${answer.side} roll` : '';
      this._message = {
        text: `Printed ${answer.printed || data.copies || 1}${side}.`,
        bad: false,
      };
      if (Array.isArray(answer.notes) && answer.notes.length)
        this._message.text += ` ${answer.notes[0]}`;
    } catch (error) {
      /* The add-on's own sentence — "the left roll holds Cryogenic Labels
       * and this label is for Chemical-Resistant Cryo Labels" — arrives as
       * the error's message. Replacing it with "print failed" is how a
       * fixable mistake becomes a mystery. */
      this._message = {
        text: error?.message || error?.error || 'BRUH Print could not print that.',
        bad: true,
      };
    } finally {
      this._busy = false;
      this._signature = '';
      this._render();
      clearTimeout(this._messageTimer);
      this._messageTimer = setTimeout(() => {
        this._message = null;
        this._signature = '';
        this._render();
      }, 8000);
    }
  }

  _common() {
    const data = {};
    const copies = this._form.copies ?? this._config.copies;
    if (copies && copies > 1) data.copies = copies;
    /* `stock`, never `side`: the add-on remembers which bay holds which
     * label, so naming the label has already named the bay — and a card
     * that sent a side would be the one place able to contradict it. */
    const stock = this._selectedStock();
    if (stock) data.stock = stock;
    return data;
  }

  _print() {
    /* Enter in the text box prints, so the guard cannot live on the
     * button alone. */
    if (this._busy || this._blocked) return;
    if (this._config.mode === 'template') {
      const fields = { ...this._form.fields };
      for (const field of this._config.fields || []) {
        const key = typeof field === 'string' ? field : field.key;
        if (key && !fields[key] && field.default) fields[key] = field.default;
      }
      this._call('print_template', {
        template: this._config.template, fields, ...this._common(),
      });
      return;
    }
    const text = (this._form.text || '').trim();
    if (!text) {
      this._message = { text: 'Type something first.', bad: true };
      this._signature = '';
      this._render();
      return;
    }
    this._call('print_text', { text, ...this._common() });
  }

  _quickPrint(item) {
    if (this._busy || this._blocked) return;
    if (item.template) {
      this._call('print_template', {
        template: item.template, fields: item.fields || {},
        ...(item.copies ? { copies: item.copies } : {}),
        ...(item.stock ? { stock: item.stock } : { stock: this._selectedStock() }),
      });
      return;
    }
    this._call('print_text', {
      text: item.text || item.label,
      ...(item.copies ? { copies: item.copies } : {}),
      stock: item.stock || this._selectedStock(),
    });
  }
}

/* ── Visual editor ───────────────────────────────────────────────────── */
/* Deliberately small: the fields anybody sets from the UI, and YAML for the
 * rest. An editor that tries to render every option ends up being the place
 * bugs live, and this card's interesting options (quick buttons, per-field
 * hints) are lists that a YAML editor already handles better than a form. */
class BruhPrintCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = { ...DEFAULTS };
  }

  setConfig(config) { this._config = { ...DEFAULTS, ...config }; this._render(); }
  set hass(hass) { this._hass = hass; }

  _emit(patch) {
    this._config = { ...this._config, ...patch };
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  _render() {
    const style = document.createElement('style');
    style.textContent = css + '.wrap{padding:8px 0}';
    const wrap = document.createElement('div');
    wrap.className = 'wrap';

    const add = (label, key, kind = 'text', options = null) => {
      const field = document.createElement('label');
      field.className = 'field';
      const name = document.createElement('span');
      name.textContent = label;
      let input;
      if (options) {
        input = document.createElement('select');
        for (const [value, text] of options) {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = text;
          input.append(option);
        }
        input.value = String(this._config[key] ?? '');
        input.addEventListener('change', () => this._emit({ [key]: input.value }));
      } else if (kind === 'boolean') {
        input = document.createElement('input');
        input.type = 'checkbox';
        input.style.width = '22px';
        input.style.minHeight = '22px';
        input.checked = !!this._config[key];
        input.addEventListener('change', () => this._emit({ [key]: input.checked }));
      } else {
        input = document.createElement('input');
        if (kind === 'number') input.type = 'number';
        input.value = this._config[key] ?? '';
        input.addEventListener('input', () => this._emit({
          [key]: kind === 'number' ? Number(input.value) || 1 : input.value,
        }));
      }
      field.append(name, input);
      wrap.append(field);
    };

    add('Title', 'title');
    add('Mode', 'mode', 'text', [['text', 'Type any text'], ['template', 'Fill in a template']]);
    if (this._config.mode === 'template') add('Template name', 'template');
    else add('Label stock (optional)', 'stock');
    add('Copies', 'copies', 'number');
    add('Show the status pill', 'show_status', 'boolean');
    add('Show the rolls', 'show_rolls', 'boolean');

    this.shadowRoot.replaceChildren(style, wrap);
  }
}

customElements.define('bruh-print-card', BruhPrintCard);
customElements.define('bruh-print-card-editor', BruhPrintCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'bruh-print-card',
  name: 'BRUH Print',
  preview: true,
  description: 'Type a word and print it on a DYMO LabelWriter, or fill in a saved template.',
  documentationURL: 'https://github.com/bruhautomation/BRUH-HA-Apps/tree/main/bruh-print',
});
