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
//     layer: what is in it, and the switch that turns it off here.
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
    const big = files.filter((f) => f.state === 'too_big').map((f) => f.name);
    if (big.length) return `${big.join(' and ')} ${big.length > 1 ? 'are' : 'is'} over ${cap}, so ${big.length > 1 ? 'they are' : 'it is'} not loaded.`;
    const odd = files.filter((f) => f.state === 'refused').map((f) => f.name);
    if (odd.length) return `${odd.join(' and ')} ${odd.length > 1 ? 'are' : 'is'} not a plain file, so ${odd.length > 1 ? 'they are' : 'it is'} not loaded.`;
    return `${files.map((f) => `${f.name} (${kb(f.bytes)})`).join(' and ')}, from ${facts.dir || '/config/.brain/ui'}.`;
  }

  function paint() {
    if (!files.length && !deviceOff) return;
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

  paint();
})();
