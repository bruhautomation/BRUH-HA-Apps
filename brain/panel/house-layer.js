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
//     once, so nobody has to notice, find the file or press anything.
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
    // The terminal's immersive mode hides the header on purpose.
    const immersive = document.body.classList.contains('term-immersive');
    const needed = immersive ? ['main.wrap'] : ['header.topbar', 'nav.viewtabs', 'main.wrap'];
    for (const sel of needed) {
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

  if (!safe && !deviceOff && fresh.length) {
    if (document.readyState === 'complete') whenSettled();
    else window.addEventListener('load', whenSettled, { once: true });
  }

  paint();
})();
