// The house's own layer over brAIn's page (panel/house_ui.py).
//
// The server tells this script what is in /config/.brain/ui through
// <meta name="brain-house">, and has already linked house.css after
// style.css when there is one to use. This script, loaded after app.js:
//   * loads house.js in a script of its own, so a house.js that throws (or
//     will not load) is one line in Settings › Instructions, never a broken
//     page;
//   * honours "off on this device" (localStorage) by taking house.css away
//     and not loading house.js;
//   * in the safe mode (?nohouse=1) says, once, that the layer is off;
//   * draws one switch row in Settings › Instructions while the house has a
//     layer: what is in it, and the switch that turns it off here;
//   * undoes a bad change by itself (house_ui.revert): a version of either
//     file the page has not yet seen work (`good: false`) gets the page's
//     health check once the page has settled — house.js did not throw, and
//     the header, the tabs and the main pane are drawn and visible. Passed,
//     the server keeps it as the last good copy; failed, the server puts the
//     last good copy back (or takes the file away) and the page reloads
//     once, so nobody has to notice, find the file or press anything;
//   * hides a control house.js added that brAIn's page now ships itself, and
//     says so once: an update that brings what the house had already
//     added (a clock, a button) showed both until somebody complained.
// It does nothing at all on a page with no meta (the page opened as a file).
(function () {
  'use strict';
  const meta = document.querySelector('meta[name="brain-house"]');
  if (!meta) return;
  let facts;
  try { facts = JSON.parse(meta.getAttribute('content') || '{}'); } catch (e) { return; }
  const files = Array.isArray(facts.files) ? facts.files : [];
  const KEY = 'brain.house.off';
  let deviceOff = false;
  try { deviceOff = localStorage.getItem(KEY) === '1'; } catch (e) { /* storage refused */ }
  const safe = !!facts.off;
  const both = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}` : xs[0] || '');
  const kb = (n) => (n < 1024 ? `${n} bytes` : `${Math.round(n / 1024)} KB`);
  const cap = kb(facts.max || 0);
  let jsError = '';
  let jsLoaded = false;
  let jsThrew = false;
  let judged = false;
  const reverted = facts.reverted && typeof facts.reverted === 'object' ? facts.reverted : null;

  if (deviceOff) {
    const link = document.getElementById('brainHouseCss');
    if (link) link.remove();
  }

  const js = files.find((f) => f.name === 'house.js');
  // Everything on the page before house.js runs is brAIn's own: the header
  // is static, so whatever is in it afterwards that is not here was added.
  const shipped = new WeakSet(document.querySelectorAll('*'));
  let doubled = [];
  let noted = [];
  if (js && js.state === 'ok' && !safe && !deviceOff) {
    const src = new URL(`house.js?v=${encodeURIComponent(js.v || '')}`, document.baseURI).href;
    let running = false;
    // A throw inside house.js reaches window, never app.js. Same-origin, so
    // the error names its file; "Script error." while it is the one script
    // running is the same throw with its details withheld.
    window.addEventListener('error', (ev) => {
      const fromHouse = (ev.filename && ev.filename.split('?')[0] === src.split('?')[0])
        || (running && !ev.filename);
      if (!fromHouse) return;
      jsError = String(ev.message || 'an error').replace(/^Uncaught\s+/, '').slice(0, 160);
      console.warn('house.js stopped with an error; the shipped page is unaffected:', ev.message);
      ev.preventDefault();
      paint();
      jsThrew = true;
      if (running && !js.good) judge(`house.js threw while loading: ${jsError}`);
    });
    const tag = document.createElement('script');
    tag.src = src;
    tag.async = false;
    tag.dataset.house = '1';
    tag.addEventListener('load', () => { running = false; });
    tag.addEventListener('error', () => {
      running = false;
      jsError = 'it could not be loaded';
      paint();
    });
    tag.addEventListener('load', () => { jsLoaded = true; });
    running = true;
    document.body.appendChild(tag);
  }

  if (safe) {
    const say = 'House changes to this page are off for this visit.';
    if (typeof window.toast === 'function') {
      try { window.toast(say); } catch (e) { console.info(say); }
    } else {
      console.info(say);
    }
  }

  // The one line in Settings › Instructions. Only while the house has a
  // layer (or has switched it off here), so a house without one sees nothing.
  function line() {
    const names = files.map((f) => f.name).join(', ');
    if (safe) return `${names || 'None'}. Off for this visit, because the address has nohouse=1.`;
    if (deviceOff) return `${names}. Off on this device.`;
    if (jsError) return `house.js stopped with an error: ${jsError}. The rest of the page is unaffected.`;
    if (doubled.length || noted.length) {
      const parts = [];
      if (doubled.length) parts.push(`brAIn now ships ${both(doubled)}, which house.js also adds beside it, so the house's copy is hidden. Take it out of house.js.`);
      if (noted.length) parts.push(`house.js also adds something named like brAIn's own ${both(noted)}; it is left as it is, in case it does something else.`);
      return parts.join(' ');
    }
    if (reverted && reverted.name) {
      const back = reverted.restored === 'previous' ? 'the last version that worked was put back' : 'it was taken away';
      return `${reverted.name} broke the page (${reverted.why || 'it failed the check'}), so ${back} automatically.`;
    }
    const big = files.filter((f) => f.state === 'too_big').map((f) => f.name);
    if (big.length) return `${big.join(' and ')} ${big.length > 1 ? 'are' : 'is'} over ${cap}, so ${big.length > 1 ? 'they are' : 'it is'} not loaded.`;
    const odd = files.filter((f) => f.state === 'refused').map((f) => f.name);
    if (odd.length) return `${odd.join(' and ')} ${odd.length > 1 ? 'are' : 'is'} not a plain file, so ${odd.length > 1 ? 'they are' : 'it is'} not loaded.`;
    return `${files.map((f) => `${f.name} (${kb(f.bytes)})`).join(' and ')}, from ${facts.dir || '/config/.brain/ui'}.`;
  }

  function paint() {
    if (!files.length && !deviceOff && !reverted) return;
    const body = document.querySelector('#setsecInstructions .setsecbody');
    if (!body) return;
    let row = document.getElementById('houseLayer');
    if (!row) {
      row = document.createElement('div');
      row.className = 'setgroup';
      row.id = 'houseLayer';
      row.innerHTML = '<div class="setrow top"><label class="check bigcheck">'
        + '<input id="setHouseLayer" class="tog" type="checkbox">'
        + '<span><b>House changes to this page</b>'
        + '<span class="subtext" id="houseLayerLine"></span></span></label></div>';
      const hint = body.querySelector(':scope > .hint');
      if (hint) hint.after(row); else body.prepend(row);
      row.querySelector('#setHouseLayer').addEventListener('change', (ev) => {
        try {
          if (ev.target.checked) localStorage.removeItem(KEY);
          else localStorage.setItem(KEY, '1');
        } catch (e) { /* storage refused: nothing to remember it in */ }
        location.reload();
      });
    }
    const box = row.querySelector('#setHouseLayer');
    box.checked = !deviceOff && !safe;
    box.disabled = safe;
    row.querySelector('#houseLayerLine').textContent = line();
  }

  // ---- automatic undo -------------------------------------------------
  //
  // Only a version the page has not seen work is judged, only while it is
  // actually in use here (not the safe mode, not off on this device), and
  // only once per page. The verdict names the version the page loaded, so
  // the server never takes back a newer edit than the one that failed.
  const SETTLE_MS = 3000;
  const WAIT_VISIBLE_MS = 60000;
  const RELOAD_KEY = 'brain.house.reverted';
  const fresh = files.filter((f) => f.state === 'ok' && !f.good);
  // house.js is in use once it ran (loaded, or threw while loading); one
  // that could not be fetched is a network fault, never a verdict.
  const inUse = (f) => f.name !== 'house.js' || jsLoaded || jsThrew;

  function shown(sel) {
    const el = document.querySelector(sel);
    if (!el) return `${sel} is missing`;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return `${sel} is hidden`;
    if (parseFloat(cs.opacity || '1') < 0.1) return `${sel} is transparent`;
    if (r.width < 2 || r.height < 2) return `${sel} has no size`;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return `${sel} is off the screen`;
    return '';
  }

  // The page's health check: what a person needs to use the page at all.
  function check() {
    const bodyStyle = getComputedStyle(document.body);
    if (bodyStyle.display === 'none' || bodyStyle.visibility === 'hidden'
      || parseFloat(bodyStyle.opacity || '1') < 0.1) return 'the page is hidden';
    // Nothing on the page hides the header on purpose (the terminal's fold
    // is gone), so a house change that hides it has broken the page.
    for (const sel of ['header.topbar', 'nav.viewtabs', 'main.wrap']) {
      const why = shown(sel);
      if (why) return why;
    }
    return '';
  }

  function post(body) {
    return fetch(new URL('api/house/outcome', document.baseURI).href, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  }

  function judge(failure) {
    if (judged) return;
    judged = true;
    // A house.js that threw is house.js's fault alone, whatever else the
    // page shows; one that could not be fetched is a network, not a verdict.
    if (!failure && jsThrew) failure = `house.js stopped with an error: ${jsError}`;
    const why = failure || check();
    const named = fresh.filter(inUse);
    if (!why) {
      named.forEach((f) => post({ name: f.name, v: f.v, outcome: 'confirm' }));
      return;
    }
    // A page that fails the check takes back every version it had not yet
    // seen work; a throw is house.js's alone.
    const blamed = failure && jsThrew ? named.filter((f) => f.name === 'house.js') : named;
    if (!blamed.length) return;
    console.warn('brAIn: a house change broke the page, so it is being undone:', why);
    Promise.all(blamed.map((f) => post({ name: f.name, v: f.v, outcome: 'revert', why }))).then((outs) => {
      if (!outs.some((o) => o && o.reverted)) return;
      let again = true;
      try {
        // One reload per broken version: a page that is still broken after
        // it says so rather than reloading for ever.
        const stamp = blamed.map((f) => f.v).join(',');
        again = sessionStorage.getItem(RELOAD_KEY) !== stamp;
        sessionStorage.setItem(RELOAD_KEY, stamp);
      } catch (e) { /* storage refused: reload once all the same */ }
      if (again) location.reload();
    });
  }

  function whenSettled() {
    const started = Date.now();
    const go = () => {
      // A frame drawn at no size (the shell showing another tab) cannot be
      // judged on what it shows; wait until it is on screen, or give up.
      if (document.visibilityState !== 'visible' || innerWidth < 2 || innerHeight < 2) {
        if (Date.now() - started < WAIT_VISIBLE_MS) setTimeout(go, 2000);
        return;
      }
      if (js && js.state === 'ok' && !jsLoaded && !jsError) {
        // still loading
        if (Date.now() - started < WAIT_VISIBLE_MS) setTimeout(go, 1000);
        return;
      }
      judge('');
    };
    setTimeout(go, SETTLE_MS);
  }

  // ---- a house copy of something brAIn now ships -----------------------
  //
  // Hidden only when it is surely a second copy: house.js added it to the
  // header, it is the same kind of thing as one of brAIn's own in the header
  // (a button or link with exactly the same name, or a clock: a <time> or
  // text that is a time and nothing else — "Sunset 18:42" is not a clock),
  // brAIn's is showing, and the two sit on the same row. Anything less sure
  // (the same name elsewhere on the page, or on another row) is never
  // hidden: the Instructions row names it once. brAIn's own copy is never
  // touched, and an owner's own addition is never hidden on a guess.
  const BARE_TIME = /^\d{1,2}:\d{2}(?::\d{2})?(?:\s?[ap]\.?m\.?)?$/i;
  const PRESS = 'button, a[href], [role="button"], [role="tab"]';
  function kindOf(el) {
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (el.localName === 'time' || BARE_TIME.test(text)) return 'clock';
    if (el.matches(PRESS)) return 'press';
    return '';
  }
  function nameOf(el) {
    if (kindOf(el) === 'clock') return 'clock';
    const n = el.getAttribute('aria-label') || el.dataset.tip || el.getAttribute('title') || el.textContent;
    return String(n || '').replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 60);
  }
  function visible(el) {
    if (!el.isConnected || !el.getClientRects().length) return false;
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') >= 0.1;
  }
  const sameRow = (a, b) => {
    const x = a.getBoundingClientRect(); const y = b.getBoundingClientRect();
    return Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > Math.min(x.height, y.height) / 2;
  };
  function findDoubles() {
    const bar = document.querySelector('header.topbar');
    // brAIn's own, showing, by kind and exact name: in the header, and on
    // the whole page (only ever named, never a reason to hide).
    const ours = (root) => {
      const out = new Map();
      (root ? root.querySelectorAll(PRESS + ', time') : []).forEach((el) => {
        if (!shipped.has(el) || !visible(el)) return;
        const k = kindOf(el); const n = nameOf(el);
        if (k && n.length >= 2 && !out.has(k + ':' + n)) out.set(k + ':' + n, el);
      });
      return out;
    };
    const head = ours(bar);
    const page = ours(document);
    const fresh = (el) => !shipped.has(el) && !el.dataset.houseDouble && visible(el)
      && !el.closest('#houseLayer, #toast, .tipbox, .modal, #chipPop');
    const word = (own, n) => (n === 'clock' ? 'the clock'
      : (own.getAttribute('aria-label') || own.dataset.tip || own.textContent || n).replace(/\s+/g, ' ').trim().slice(0, 40));
    const hid = []; const named = [];
    // In the header: hidden when it is the same thing beside brAIn's own.
    [...(bar ? bar.querySelectorAll('*') : [])].filter(fresh).forEach((el) => {
      const k = kindOf(el); if (!k) return;
      const key = k + ':' + nameOf(el);
      const own = head.get(key);
      if (!own || own.contains(el) || el.contains(own)) return;
      // A clock inside a house element that is itself a clock is hidden with it.
      if (el.parentElement && el.parentElement.dataset.houseDouble) return;
      if (sameRow(el, own)) {
        el.dataset.houseDouble = '1';
        el.style.setProperty('display', 'none', 'important');
        hid.push(word(own, nameOf(el)));
      } else {
        named.push(word(own, nameOf(el)));
      }
    });
    // Anywhere else on the page's top level: named, never hidden.
    [...document.body.children].filter((el) => fresh(el) && kindOf(el)).forEach((el) => {
      const own = page.get(kindOf(el) + ':' + nameOf(el));
      if (own && own !== el) named.push(word(own, nameOf(el)));
    });
    const newNamed = named.filter((n) => !noted.includes(n) && !hid.includes(n));
    if (!hid.length && !newNamed.length) return;
    doubled = [...new Set([...doubled, ...hid])];
    noted = [...new Set([...noted, ...newNamed])];
    if (hid.length) console.warn('brAIn: house.js adds what brAIn now ships, so the house copy is hidden:', hid.join(', '));
    if (newNamed.length) console.info('brAIn: house.js adds something named like brAIn\'s own, left as it is:', newNamed.join(', '));
    paint();
    if (!hid.length) return;
    const key = `brain.house.doubled.${js && js.v}`;
    let said = false;
    try { said = localStorage.getItem(key) === doubled.join('|'); localStorage.setItem(key, doubled.join('|')); } catch (e) { /* say it this time */ }
    if (!said && typeof window.toast === 'function') {
      try { window.toast(`brAIn now has ${both(doubled)} itself, so the copy from this house's own changes is hidden.`); } catch (e) { /* the row says it */ }
    }
  }
  if (js && js.state === 'ok' && !safe && !deviceOff) {
    const look = () => { try { findDoubles(); } catch (e) { /* never the page's problem */ } };
    const later = () => { setTimeout(look, SETTLE_MS); setTimeout(look, SETTLE_MS * 4); };
    if (document.readyState === 'complete') later();
    else window.addEventListener('load', later, { once: true });
  }

  if (!safe && !deviceOff && fresh.length) {
    if (document.readyState === 'complete') whenSettled();
    else window.addEventListener('load', whenSettled, { once: true });
  }

  paint();
})();
