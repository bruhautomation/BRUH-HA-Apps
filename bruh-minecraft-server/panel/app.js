/* BRUH Minecraft Server — ingress panel frontend */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // Escape anything server-provided before it goes into innerHTML. Player
  // names, MOTD/property values, plugin filenames, etc. are user-controlled
  // and must not be able to inject markup or break out of an attribute.
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));

  // Relative API paths work with HA ingress proxy automatically.
  const api = async (path, opts = {}) => {
    const headers = { 'Accept': 'application/json' };
    if (opts.body && !(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(path, { credentials: 'same-origin', headers, ...opts });
    if (resp.status === 204) return null;
    const text = await resp.text();
    try { return JSON.parse(text); } catch { return { _raw: text }; }
  };

  // ------------------------------------------------------------------
  // What's new (#594): the header's "v1.2.3 · changelog" opens the
  // release notes in the panel (/api/changelog, newest first). After an
  // update the header says "Updated since you last looked" until the notes
  // are opened; which version was last read is this browser's memory
  // (localStorage), and a browser that keeps none simply never says it.
  // ------------------------------------------------------------------
  const CHANGELOG_SEEN = 'bruh-minecraft.changelog.seen';
  const versionLink = $('#version-link');
  const panelVersion = ((versionLink && versionLink.textContent) || '').replace(/^v/, '').split(' ')[0];
  const versionNewer = (a, b) => {
    const pa = String(a || '').split('.').map((n) => parseInt(n, 10) || 0);
    const pb = String(b || '').split('.').map((n) => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pa[i] || 0) - (pb[i] || 0);
      if (d) return d > 0;
    }
    return false;
  };
  const seenGet = () => { try { return localStorage.getItem(CHANGELOG_SEEN) || ''; } catch { return ''; } };
  const seenSet = (v) => { try { localStorage.setItem(CHANGELOG_SEEN, v); } catch { /* private window */ } };
  function markUpdated() {
    const seen = seenGet();
    if (!seen && /^\d/.test(panelVersion)) {
      // The first look in this browser: nothing to compare with yet.
      seenSet(panelVersion);
      return;
    }
    const fresh = /^\d/.test(panelVersion) && versionNewer(panelVersion, seen);
    $('#version-new').hidden = !fresh;
  }
  // The notes are Markdown; this renders only what CHANGELOG.md uses, and
  // escapes everything before it adds a tag.
  function notesHtml(md) {
    const inline = (t) => esc(t)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const out = [];
    let list = false;
    const close = () => { if (list) { out.push('</ul>'); list = false; } };
    for (const raw of String(md || '').split('\n')) {
      const line = raw.trimEnd();
      if (/^###\s+/.test(line)) { close(); out.push(`<h4>${inline(line.replace(/^###\s+/, ''))}</h4>`); continue; }
      if (/^\s*[-*]\s+/.test(line)) {
        if (!list) { out.push('<ul>'); list = true; }
        out.push(`<li>${inline(line.replace(/^\s*[-*]\s+/, ''))}</li>`);
        continue;
      }
      if (/^\s{2,}\S/.test(line) && list) {
        out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, ` ${inline(line.trim())}</li>`);
        continue;
      }
      close();
      if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    close();
    return out.join('');
  }
  async function openChangelog() {
    const dlg = $('#changelog-dialog');
    const body = $('#changelog-body');
    const seen = seenGet();
    body.textContent = 'Loading…';
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    let data;
    try { data = await api('api/changelog'); } catch { data = null; }
    const releases = (data && data.releases) || [];
    if (!releases.length) {
      body.innerHTML = `<p>${esc((data && data.error) || 'The release notes could not be read.')} They are also <a href="${esc(versionLink.href)}" target="_blank" rel="noopener noreferrer">published online</a>.</p>`;
      return;
    }
    body.innerHTML = releases.map((r) => `<section><h3>v${esc(r.version)}${r.date ? ` <span class="muted">${esc(r.date)}</span>` : ''}${seen && versionNewer(r.version, seen) ? ' <span class="changelog-new">New</span>' : ''}</h3>${notesHtml(r.body)}</section>`).join('');
    seenSet(releases[0].version);
    $('#version-new').hidden = true;
  }
  versionLink?.addEventListener('click', (ev) => {
    // A modified press keeps the link's own meaning (a new tab).
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button) return;
    ev.preventDefault();
    openChangelog();
  });
  $('#changelog-close')?.addEventListener('click', () => {
    const dlg = $('#changelog-dialog');
    if (dlg.close) dlg.close(); else dlg.removeAttribute('open');
  });
  markUpdated();

  // ------------------------------------------------------------------
  // The header on a phone (#1457): the server actions fold behind one
  // "Server" button, and the status footer is the end of the page rather
  // than a strip pinned under it. From 640px both are as they were.
  // ------------------------------------------------------------------
  const phone = window.matchMedia('(max-width: 639.98px)');
  const serverMenu = $('#btn-server-menu');
  const serverActions = $('#server-actions');
  const setServerMenu = (open) => {
    serverActions.classList.toggle('open', open);
    serverMenu.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  serverMenu.addEventListener('click', (ev) => {
    ev.stopPropagation();
    setServerMenu(!serverActions.classList.contains('open'));
  });
  // A press on an action, or anywhere else, closes the menu.
  document.addEventListener('click', (ev) => {
    if (serverActions.classList.contains('open') && !serverMenu.contains(ev.target)) setServerMenu(false);
  });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') setServerMenu(false); });
  const pageFooter = document.querySelector('body > footer');
  const placeFooter = () => {
    if (!pageFooter) return;
    if (phone.matches) $('main').appendChild(pageFooter);
    else document.body.insertBefore(pageFooter, document.querySelector('body > script'));
    if (!phone.matches) setServerMenu(false);
  };
  placeFooter();
  phone.addEventListener?.('change', placeFooter);

  // ------------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------------
  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      $$('.tab').forEach((t) => t.classList.remove('active'));
      $$('.tab-panel').forEach((p) => p.classList.remove('active'));
      tab.classList.add('active');
      // The tab row scrolls sideways on a phone; the chosen tab stays in sight.
      tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      $(`#tab-${tab.dataset.tab}`).classList.add('active');
      if (tab.dataset.tab === 'players')    refreshPlayersTab();
      if (tab.dataset.tab === 'properties') loadProperties();
      if (tab.dataset.tab === 'addons')     loadAddons();
      if (tab.dataset.tab === 'backups')    loadBackups();
      if (tab.dataset.tab === 'worlds')     { loadWorlds(); loadCuratedWorlds(); }
      // Reset main's scroll position when switching tabs so the user
      // lands at the top of the new content. main is the page's single
      // scroll container (see style.css for why); a plain
      // window.scrollTo(0) wouldn't do anything because <body> doesn't
      // scroll under this layout.
      const m = document.querySelector('main');
      if (m) m.scrollTop = 0;
    });
  });


  // ------------------------------------------------------------------
  // Dashboard refresh loop
  // ------------------------------------------------------------------
  const fmtDuration = (s) => {
    if (!s && s !== 0) return '—';
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const parts = [];
    if (d) parts.push(`${d}d`);
    if (h || d) parts.push(`${h}h`);
    if (m || h || d) parts.push(`${m}m`);
    parts.push(`${sec}s`);
    return parts.join(' ');
  };

  const fmtSize = (n) => {
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
  };

  async function refreshStatus() {
    try {
      const data = await api('api/status');
      const { running, state, stats, server_meta } = data;

      const statusDot = $('#m-status');
      const statusText = $('#m-status-text');
      statusDot.className = `dot ${running ? 'running' : 'stopped'}`;
      statusText.textContent = running
        ? (stats.reachable ? 'Online' : 'Starting…')
        : 'Stopped';

      // The version once, with the software's name in front when the version
      // does not already carry it ("Paper 1.21.4", never "paper Paper 1.21.4").
      const rawVersion = stats.version || server_meta.version || '';
      const software = typeName(state.server_type || 'paper');
      const versionText = !rawVersion ? software
        : rawVersion.toLowerCase().startsWith(software.toLowerCase()) ? rawVersion : `${software} ${rawVersion}`;
      $('#m-version').textContent = rawVersion ? versionText : '—';
      $('#m-uptime').textContent = stats.uptime_seconds
        ? fmtDuration(stats.uptime_seconds) : '—';
      // Memory in use, of what the server is allowed, when BRUH Sight reports
      // the server's heap (/api/status `memory`); without it only the
      // allowance is known, and that is all the row says.
      const allowed = state.memory_mb || (data.memory && data.memory.max_mb) || 0;
      const used = data.memory && running ? data.memory.used_mb : null;
      const inGb = allowed >= 1024;
      const amount = (mb) => (inGb ? `${Math.round(mb / 102.4) / 10}` : `${Math.round(mb)}`);
      const unit = inGb ? 'GB' : 'MB';
      $('#m-memory').textContent = !allowed ? '—'
        : used != null ? `${amount(used)} of ${amount(allowed)} ${unit} in use`
          : `${amount(allowed)} ${unit} allocated`;
      // TPS health colors. 20 is perfect; under ~17 sustained means the
      // server can't keep up. Apply per-cell so the eye can tell which
      // window slipped first.
      const tpsClass = (v) => {
        if (v == null) return 'tps-unknown';
        if (v >= 19.5) return 'tps-good';
        if (v >= 17.0) return 'tps-warn';
        return 'tps-bad';
      };
      const setTps = (id, v) => {
        const el = $(id);
        el.textContent = v ?? '—';
        el.className = `tps ${tpsClass(v)}`;
      };
      setTps('#m-tps1', stats.tps_1m);
      setTps('#m-tps5', stats.tps_5m);
      setTps('#m-tps15', stats.tps_15m);
      const badge = $('#m-tps-badge');
      const cls = tpsClass(stats.tps_5m);
      badge.className = `tps-badge ${cls}`;
      badge.textContent = ({
        'tps-good': '● healthy',
        'tps-warn': '● degraded',
        'tps-bad': '● struggling',
        'tps-unknown': '',
      })[cls];
      $('#m-latency').textContent = stats.latency_ms != null ? `${stats.latency_ms} ms` : '—';

      // Smart perf hint: when the 5-minute TPS is degraded or worse, the
      // user benefits from a one-liner action. Pick the most impactful one
      // based on what's actually configured.
      const hint = $('#perf-hint');
      if (cls === 'tps-warn' || cls === 'tps-bad') {
        const tip = (cls === 'tps-bad' ? 'TPS is struggling — ' : 'TPS is degraded — ')
          + 'try lowering simulation-distance (the biggest TPS lever) on the Server Properties tab. '
          + 'If you have spare RAM, click Tune for my hardware above for a sized recommendation.';
        hint.textContent = tip;
        hint.hidden = false;
      } else {
        hint.hidden = true;
      }

      // First-run wizard: show the welcome overlay when the add-on is idling
      // for setup (EULA not yet accepted). Hide it as soon as setup is done.
      const wizard = $('#setup-wizard');
      if (wizard) wizard.hidden = !data.setup_required;

      // Crash banner: surface the last few error lines when the JVM exited
      // unexpectedly. Respect a dismissal until the crash signature changes.
      renderCrashBanner(data.crash);
      // memory_mb against the host's memory (checked at add-on start): a hint
      // only - the setting is changed in the add-on's Configuration tab.
      const memHint = $('#memory-hint');
      if (memHint) {
        memHint.textContent = data.memory_warning ? data.memory_warning.message : '';
        memHint.hidden = !data.memory_warning;
      }
      const online = stats.online ?? 0;
      const max = stats.max_players ?? state.max_players;
      $('#m-online-text').textContent = !running ? '—'
        : `${online}${max ? ` of ${max}` : ''} online`;

      const ml = $('#m-players');
      ml.innerHTML = '';
      (stats.players || []).forEach((name) => {
        const li = document.createElement('li');
        li.textContent = name;
        ml.appendChild(li);
      });

      $('#brand-subtitle').textContent = `${versionText} · ${running ? 'online' : 'offline'}`;
      $('#last-refresh').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      console.warn('refresh failed', err);
    }
  }

  setInterval(refreshStatus, 5000);
  refreshStatus();

  // ------------------------------------------------------------------
  // The companion (companion.py): brAIn's, when brAIn is installed. This
  // card shows who it is and what it did (with Undo), and keeps the two
  // things that belong to the world: protected places and a question on
  // the pads. Who is family, bedtime, limits and the model are brAIn's
  // (⚙ › Minecraft). Without brAIn the card is hidden and one line says why.
  // ------------------------------------------------------------------
  const fmtWhen = (t) => (t ? new Date(t * 1000).toLocaleString() : '');
  // The choice pads' pictures. Each is set on a fence post with setblock,
  // so only full blocks that stay put: nothing that falls (sand), decays
  // (leaves), needs ground (flowers) or is an entity (pig). Every id must
  // pass companion.block_id (tests/test_minecraft_companion_card.py checks).
  const PAD_PICTURES = [
    ['', 'Plain colour (the pad\'s own)'],
    ['minecraft:stone_bricks', 'Castle (stone bricks)'],
    ['minecraft:oak_planks', 'House (wood planks)'],
    ['minecraft:hay_block', 'Farm (hay bale)'],
    ['minecraft:oak_log', 'Tree (oak log)'],
    ['minecraft:pumpkin', 'Pumpkin'],
    ['minecraft:melon', 'Melon'],
    ['minecraft:snow_block', 'Snow'],
    ['minecraft:packed_ice', 'Ice'],
    ['minecraft:prismarine', 'Sea (prismarine)'],
    ['minecraft:gold_block', 'Gold'],
    ['minecraft:diamond_block', 'Diamond'],
    ['minecraft:bookshelf', 'Books'],
    ['minecraft:jukebox', 'Music (jukebox)'],
    ['minecraft:crafting_table', 'Making things (crafting table)'],
    ['minecraft:honey_block', 'Sweet (honey)'],
    ['minecraft:slime_block', 'Bouncy (slime)'],
    ['minecraft:glowstone', 'Light (glowstone)'],
    ['minecraft:lime_wool', 'Yes (green wool)'],
    ['minecraft:red_wool', 'No (red wool)'],
  ];
  const Q_STATUS = {
    queued: 'waiting to be asked', open: 'the pads are out now', answered: 'answered',
    expired: 'no answer', cancelled: 'cancelled',
  };
  const cs = { c: null, world: null };

  const cSay = (sel, text, ok) => {
    const el = $(sel);
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('good', ok === true);
    el.classList.toggle('bad', ok === false);
  };
  async function cSend(path, method, body) {
    try {
      const r = await api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      if (r && r._raw !== undefined) return { error: 'The panel did not answer. Try again in a moment.' };
      return r || {};
    } catch {
      return { error: 'The panel could not be reached. Try again in a moment.' };
    }
  }
  const companionName = () => (cs.c && cs.c.identity && cs.c.identity.name) || 'the companion';

  // -- 1. Protected places --------------------------------------------------
  const DIM_NAMES = { 'minecraft:overworld': 'Overworld', 'minecraft:the_nether': 'The Nether', 'minecraft:the_end': 'The End' };
  function renderZones(zones) {
    $('#companion-zones').innerHTML = zones.map((z) => `
      <li><span><strong>${esc(z.name)}</strong> · x ${esc(Math.round(z.x))}, z ${esc(Math.round(z.z))} · within ${esc(z.radius)} blocks · ${esc(DIM_NAMES[z.dimension] || z.dimension)}
        · <span class="muted">${z.protect ? 'nothing is built here' : 'a named place, not protected'}</span></span>
        <button type="button" class="btn btn-ghost" data-zone-del="${esc(z.name)}" aria-label="Remove ${esc(z.name)}">Remove</button></li>`).join('')
      || '<li class="muted">No protected places yet. Add your house, or anything you do not want built near.</li>';
    const here = ((cs.world && cs.world.players) || []).filter((p) => p.x != null && p.z != null);
    $('#companion-here').innerHTML = here.length
      ? `<span class="muted">Fill in where someone is standing:</span>${here.map((p) =>
        `<button type="button" class="chip" data-here="${esc(p.name)}">Use ${esc(p.name)}’s spot (x ${esc(p.x)}, z ${esc(p.z)})</button>`).join('')}`
      : '';
  }
  $('#companion-here')?.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-here]');
    if (!b) return;
    const p = ((cs.world && cs.world.players) || []).find((x) => x.name === b.dataset.here);
    if (!p) return;
    $('#companion-zone-x').value = p.x;
    $('#companion-zone-z').value = p.z;
    const dim = $('#companion-zone-dim');
    if ([...dim.options].some((o) => o.value === p.dimension)) dim.value = p.dimension;
    if (!$('#companion-zone-name').value.trim()) $('#companion-zone-name').focus();
  });
  $('#companion-zones')?.addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-zone-del]');
    if (!b) return;
    if (!confirm(`Remove ${b.dataset.zoneDel}? Things may be built there again.`)) return;
    const r = await cSend(`api/companion/zones/${encodeURIComponent(b.dataset.zoneDel)}`, 'DELETE');
    if (r.error) { cSay('#companion-zone-msg', r.error, false); return; }
    cSay('#companion-zone-msg', `Removed ${b.dataset.zoneDel}.`, true);
    refreshCompanion();
  });
  $('#f-companion-zone')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('#companion-zone-name').value.trim();
    const x = $('#companion-zone-x').value.trim();
    const z = $('#companion-zone-z').value.trim();
    if (!name) { cSay('#companion-zone-msg', 'Give the place a name, like Our house.', false); return; }
    if (x === '' || z === '') { cSay('#companion-zone-msg', 'Fill in x and z (or tap someone’s spot above).', false); return; }
    const r = await cSend('api/companion/zones', 'POST', {
      name, x: Number(x), z: Number(z), radius: Number($('#companion-zone-radius').value || 16),
      dimension: $('#companion-zone-dim').value, protect: true,
    });
    if (r.error) { cSay('#companion-zone-msg', r.error, false); return; }
    cSay('#companion-zone-msg', `Added ${name}. Nothing will be built within ${r.zone ? r.zone.radius : ''} blocks of it.`, true);
    $('#companion-zone-name').value = '';
    refreshCompanion();
  });

  // -- 2. A question on the pads ------------------------------------------------
  $$('.companion-pictures').forEach((sel) => {
    sel.innerHTML = PAD_PICTURES.map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join('');
  });
  [['#companion-ask-a', '#companion-ask-a-pic'], ['#companion-ask-b', '#companion-ask-b-pic']].forEach(([inp, sel]) => {
    $(inp)?.addEventListener('change', () => {
      // An answer that names a picture picks it ("castle" → stone bricks).
      if ($(sel).value) return;
      const word = $(inp).value.trim().toLowerCase();
      const hit = PAD_PICTURES.find(([id, label]) => id && word && label.toLowerCase().split(/[ (]/)[0] === word);
      if (hit) $(sel).value = hit[0];
    });
  });
  function askReason(c) {
    const who = $('#companion-ask-who').value;
    if (!(c.online || []).length) return 'Nobody is in the game right now. You can ask when somebody is playing.';
    if (!who) return 'Pick who to ask.';
    return '';
  }
  function renderAsk(c) {
    const sel = $('#companion-ask-who');
    const online = c.online || [];
    const opts = online.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
    if (sel.dataset.opts !== opts) {
      const keep = sel.value;
      sel.innerHTML = opts || '<option value="">Nobody is playing</option>';
      sel.dataset.opts = opts;
      if (online.includes(keep)) sel.value = keep;
    }
    const why = askReason(c);
    $('#companion-ask-go').disabled = !!why;
    cSay('#companion-ask-why', why);
  }
  $('#companion-ask-who')?.addEventListener('change', () => { if (cs.c) renderAsk(cs.c); });
  $('#f-companion-ask')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (cs.c && askReason(cs.c)) return;
    const text = $('#companion-ask-text').value.trim();
    if (!text) { cSay('#companion-ask-msg', 'Write the question first, so you know what the answer means.', false); return; }
    const opt = (inp, sel) => ({ label: $(inp).value.trim(), ...($(sel).value ? { picture: $(sel).value } : {}) });
    const r = await cSend('api/companion/ask', 'POST', {
      player: $('#companion-ask-who').value, question: text, by: 'a parent',
      options: [opt('#companion-ask-a', '#companion-ask-a-pic'), opt('#companion-ask-b', '#companion-ask-b-pic')],
    });
    if (r.error) { cSay('#companion-ask-msg', r.error, false); return; }
    cSay('#companion-ask-msg', r.note || 'Asked.', true);
    $('#companion-ask-text').value = '';
    refreshCompanion();
  });

  // -- What it did, the answers, and what it said ---------------------------------
  function renderLog(c) {
    $('#companion-actions').innerHTML = (c.actions || []).slice(0, 15).map((a) => `
      <li><span>${esc(fmtWhen(a.t))} · ${esc(a.text || a.kind)} <span class="muted">(${esc(a.status)})</span>
        ${a.undo_note ? `<span class="muted">${esc(a.undo_note)}</span>` : ''}</span>
        ${a.undoable ? `<button type="button" class="btn btn-ghost" data-companion-undo="${esc(a.id)}">Undo</button>` : ''}</li>`).join('')
      || `<li class="muted">Nothing yet — ${esc(companionName())} will say hello here the next time someone from the family joins the game.</li>`;
    $('#companion-questions').innerHTML = (c.questions || []).slice(0, 10).map((q) => `
      <li><span>${esc(q.person || q.player)}: ${esc(q.text)} <span class="muted">(${(q.options || []).map((o) => esc(o.label)).join(' or ')})</span></span>
        <span class="muted">${q.answer ? `answered <strong>${esc(q.answer)}</strong>` : esc(Q_STATUS[q.status] || q.status)}${q.note ? ` · ${esc(q.note)}` : ''}</span></li>`).join('')
      || '<li class="muted">No questions yet. Ask one above; the answer shows up here.</li>';
    $('#companion-said').innerHTML = (c.said || []).slice(0, 12).map((t) => `
      <li><span>${esc(fmtWhen(t.t))} · ${esc(t.name || companionName())} to ${esc((t.to || []).join(', '))}${t.by ? ` <span class="muted">(asked by ${esc(t.by)})</span>` : ''}</span>
        <span class="muted">“${esc(t.text)}”</span></li>`).join('')
      || `<li class="muted">Nothing said yet. A grown-up on brAIn's family list can start a chat message with “${esc(companionName())}” in the game.</li>`;
  }
  $('#companion-actions')?.addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-companion-undo]');
    if (!b) return;
    if (!confirm('Undo this? Blocks that changed since are left alone.')) return;
    b.disabled = true;
    const r = await cSend(`api/companion/actions/${encodeURIComponent(b.dataset.companionUndo)}/undo`, 'POST');
    if (r.error) cSay('#companion-did-msg', r.error, false);
    else cSay('#companion-did-msg', r.note || 'Undone.', true);
    refreshCompanion();
  });

  async function refreshCompanion() {
    const [c, world] = await Promise.all([cSend('api/companion', 'GET'), cSend('api/world', 'GET')]);
    cs.world = world && !world.error ? world : null;
    renderListening(cs.world);
    if (!c || c.error) {
      if (c && c.error) cSay('#companion-status', c.error, false);
      return;
    }
    cs.c = c;
    const head = c.headline || { code: 'no_brain', show: false, text: '' };
    // No brAIn: no companion. The card goes and one line says why.
    $('#companion-card').hidden = !head.show;
    $('#companion-absent').hidden = !!head.show;
    if (!head.show) return;
    const ident = c.identity || {};
    $('#companion-title').textContent = ident.name || 'Companion';
    $$('.companion-name').forEach((el) => { el.textContent = ident.name || 'Companion'; });
    $('#companion-who').textContent = [ident.active ? 'on' : 'off', ident.by ? `run by ${ident.by}` : '',
      ident.model ? `model ${ident.model}` : ''].filter(Boolean).join(' · ');
    const status = $('#companion-status');
    status.textContent = head.text;
    status.dataset.code = head.code;
    status.classList.toggle('bad', !!head.warning);
    renderZones(c.zones || []);
    renderAsk(c);
    renderLog(c);
  }
  setInterval(refreshCompanion, 15000);
  refreshCompanion();

  // The feed's hearing (#588): a script that rewrote the join or chat lines
  // leaves the feed quiet while people play. Said at the top of the page,
  // whether or not a companion is listening.
  function renderListening(world) {
    const el = $('#feed-warning');
    if (!el) return;
    const heard = (world && world.listening) || { ok: true };
    el.hidden = !!heard.ok;
    el.textContent = heard.ok ? '' : heard.why || 'The server\'s log is not being read.';
  }

  // ------------------------------------------------------------------
  // Quick chat / command
  // ------------------------------------------------------------------
  $('#f-say').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('#say-input');
    const msg = input.value.trim();
    if (!msg) return;
    await api('api/say', { method: 'POST', body: JSON.stringify({ message: msg }) });
    input.value = '';
  });

  $('#f-cmd').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('#cmd-input');
    const cmd = input.value.trim();
    if (!cmd) return;
    const data = await api('api/command', {
      method: 'POST', body: JSON.stringify({ command: cmd }),
    });
    $('#cmd-reply').textContent = data.reply ?? data.error ?? '';
    input.value = '';
  });

  // ------------------------------------------------------------------
  // Server lifecycle buttons
  // ------------------------------------------------------------------
  const confirmAction = (msg) => window.confirm(msg);

  $('#btn-backup').addEventListener('click', async () => {
    const data = await api('api/backup', { method: 'POST' });
    alert(data.ok ? 'Backup completed.' : `Backup failed:\n${data.output || data.error}`);
    loadBackups();
  });

  // Update is only offered when the check found something newer, and its
  // label says what it updates (#1293). A new build of this world's
  // Minecraft is downloaded here; a newer Minecraft is a one-way change to
  // the world, so the button opens Add-ons, where that upgrade takes a
  // backup first.
  let headerUpdate = null;
  function showHeaderUpdate(sw) {
    const b = $('#btn-update');
    const ok = !!(sw && !sw.upgrade_pending);
    headerUpdate = !ok ? null
      : sw.build_update_available ? { kind: 'build', name: typeName(sw.server_type), build: sw.newest_build }
        : sw.upgrade_available ? { kind: 'upgrade', version: sw.newest_version } : null;
    b.hidden = !headerUpdate;
    if (!headerUpdate) return;
    b.textContent = headerUpdate.kind === 'build' ? `Update ${headerUpdate.name}` : `Minecraft ${headerUpdate.version}`;
    b.title = headerUpdate.kind === 'build'
      ? `Download ${headerUpdate.name} build ${headerUpdate.build}`
      : `Minecraft ${headerUpdate.version} is out: open Add-ons to upgrade this world`;
  }
  api('api/server/software').then((sw) => { if (!sw.error) showHeaderUpdate(sw); }).catch(() => {});
  setInterval(() => {
    if (!document.hidden) api('api/server/software').then((sw) => { if (!sw.error) showHeaderUpdate(sw); }).catch(() => {});
  }, 600000);

  $('#btn-update').addEventListener('click', async () => {
    if (!headerUpdate) return;
    if (headerUpdate.kind === 'upgrade') {
      $('.tab[data-tab="addons"]').click();
      $('#software-sec')?.scrollIntoView({ block: 'start' });
      return;
    }
    const { name, build } = headerUpdate;
    if (!confirmAction(`Download ${name} build ${build}? The server keeps running the old build until it restarts.`)) return;
    const data = await api('api/server/update', { method: 'POST' });
    alert(data.ok ? `${name} build ${build} is downloaded. Restart the server to load it.` : `Update failed:\n${data.output || data.error}`);
  });

  $('#btn-restart').addEventListener('click', async () => {
    if (!confirmAction('Restart the Minecraft server? Players will be disconnected.')) return;
    await api('api/restart', { method: 'POST' });
  });

  $('#btn-stop').addEventListener('click', async () => {
    if (!confirmAction('Stop the Minecraft server? The add-on will stay running.')) return;
    await api('api/stop', { method: 'POST' });
  });

  // Tune-for-my-hardware. Fetches the recommendation, shows what would be
  // applied + the rationale, then writes memory_mb to the add-on options and
  // view/sim distance to the active world's server.properties on confirm.
  // The dialog now shows BOTH the current effective values and the
  // recommended ones, highlights the delta, and short-circuits with "no
  // changes needed" when everything already matches.
  $('#btn-tune').addEventListener('click', async () => {
    const r = await api('api/recommend');
    if (r._raw || !r.memory_mb) { alert('Could not read recommendation:\n' + (r._raw || 'unknown')); return; }
    const cur = r.current || {};
    if (!r.any_change) {
      alert(
        'Your current settings already match the recommendation for this host:\n' +
        `  memory_mb: ${cur.memory_mb} MB\n` +
        `  view-distance: ${cur.view_distance}\n` +
        `  simulation-distance: ${cur.simulation_distance}\n\n` +
        'Nothing to apply.'
      );
      return;
    }
    const row = (label, c, rec, changed) => {
      const cdisp = (c == null ? 'unset' : String(c));
      return changed
        ? `  ${label}: ${cdisp} → ${rec}    ← CHANGE`
        : `  ${label}: ${rec} (already correct)`;
    };
    const msg =
      `Host: ${r.host_total_mb} MB RAM, ${r.cpu_count} CPU(s).\n\n` +
      'Proposed changes:\n' +
      row('memory_mb (global)',         cur.memory_mb,         r.memory_mb,         r.delta.memory_mb) + '\n' +
      row('view-distance (active world)', cur.view_distance,   r.view_distance,     r.delta.view_distance) + '\n' +
      row('simulation-distance (active)', cur.simulation_distance, r.simulation_distance, r.delta.simulation_distance) + '\n\n' +
      'Why:\n' +
      `  • ${r.rationale.memory}\n` +
      `  • ${r.rationale.distances}\n\n` +
      'Apply the changes? (Takes effect on the next restart.)';
    if (!confirmAction(msg)) return;
    const out = await api('api/recommend/apply', { method: 'POST' });
    if (out.error) { alert('Apply failed: ' + out.error); return; }
    let summary = 'Applied:\n';
    for (const [k, v] of Object.entries(out.applied || {})) summary += `  ${k} = ${v}\n`;
    if (out.warnings && out.warnings.length) {
      summary += '\nWarnings (these did NOT save permanently):\n' + out.warnings.map(w => '  ' + w).join('\n');
    }
    if (out.note) summary += '\n' + out.note;
    alert(summary);
  });

  // ------------------------------------------------------------------
  // Console streaming (SSE)
  // ------------------------------------------------------------------
  const consoleEl = $('#console');
  let autoscroll = true;
  $('#console-autoscroll').addEventListener('change', (e) => {
    autoscroll = e.target.checked;
  });
  $('#console-clear').addEventListener('click', () => { consoleEl.textContent = ''; });

  const classify = (line) => {
    if (/\b(ERROR|SEVERE|Exception)\b/.test(line)) return 'error';
    if (/\bWARN(ING)?\b/.test(line)) return 'warn';
    if (/\bINFO\b/.test(line)) return 'info';
    return '';
  };

  const appendConsole = (line) => {
    const span = document.createElement('span');
    const cls = classify(line);
    if (cls) span.className = cls;
    span.textContent = line + '\n';
    consoleEl.appendChild(span);
    // Keep DOM size bounded (last ~2000 lines)
    while (consoleEl.childNodes.length > 2000) {
      consoleEl.removeChild(consoleEl.firstChild);
    }
    if (autoscroll) consoleEl.scrollTop = consoleEl.scrollHeight;
  };

  const startLogStream = () => {
    try {
      const es = new EventSource('api/logs/tail');
      es.onmessage = (ev) => {
        try {
          const { line } = JSON.parse(ev.data);
          if (line !== undefined) appendConsole(line);
        } catch {}
      };
      es.onerror = () => {
        es.close();
        // Retry after 3s
        setTimeout(startLogStream, 3000);
      };
    } catch (err) {
      console.warn('log stream failed', err);
      setTimeout(startLogStream, 5000);
    }
  };
  startLogStream();

  $('#console-cmd-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('#console-cmd-input');
    const cmd = input.value.trim();
    if (!cmd) return;
    const data = await api('api/command', {
      method: 'POST', body: JSON.stringify({ command: cmd }),
    });
    if (data.reply) appendConsole(`> ${cmd}\n${data.reply}`);
    else if (data.error) appendConsole(`> ${cmd}\n[error] ${data.error}`);
    input.value = '';
  });

  // ------------------------------------------------------------------
  // Players tab
  // ------------------------------------------------------------------
  // Each row's menu offers only what makes sense for that person's roles.
  const PLAYER_CHOICES = (p) => [
    p.op ? ['deop', 'Remove operator'] : ['op', 'Make operator'],
    p.whitelisted ? ['whitelist_remove', 'Remove from whitelist'] : ['whitelist_add', 'Add to whitelist'],
    ...(p.online ? [['kick', 'Kick']] : []),
    p.banned ? ['pardon', 'Pardon (unban)'] : ['ban', 'Ban'],
  ];
  const PLAYER_ASK = {
    op: (n) => `Make ${n} an operator? Operators can run any command.`,
    ban: (n) => `Ban ${n}? They will not be able to join until pardoned.`,
    kick: (n) => `Kick ${n} off the server now?`,
  };

  async function refreshPlayersTab() {
    const data = await api('api/players');
    const list = $('#players-list');
    // Don't rebuild under a finger that has the menu open.
    if (list.contains(document.activeElement) && document.activeElement.tagName === 'SELECT') return;
    const known = data.known || (data.players || []).map((name) => ({ name, online: true }));
    $('#players-empty').hidden = known.length > 0;
    list.hidden = known.length === 0;
    $('#players-bedrock').hidden = !known.some((p) => p.name.startsWith('.'));
    list.innerHTML = known.map((p) => {
      // A name on no list still gets a word: with the whitelist on it cannot
      // join, otherwise it is an ordinary player.
      const role = p.op || p.whitelisted || p.banned ? ''
        : (data.whitelist_on ? '<span class="ptag ptag-bad">Not whitelisted</span>' : '<span class="ptag">Player</span>');
      const tags = [
        p.op ? '<span class="ptag">Operator</span>' : '',
        p.whitelisted ? '<span class="ptag">Whitelisted</span>' : '',
        p.banned ? '<span class="ptag ptag-bad">Banned</span>' : '',
        role,
      ].join('');
      const state = p.online ? 'Online' : 'Offline';
      const opts = PLAYER_CHOICES(p).map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
      return `<li class="player-row"><div class="player-who"><span class="pdot${p.online ? ' on' : ''}" role="img" aria-label="${state}" title="${state}"></span><strong>${esc(p.name)}</strong><span class="pstate${p.online ? ' on' : ''}">${state}</span>${tags}</div>
        <select class="player-pick" data-name="${esc(p.name)}" aria-label="Change ${esc(p.name)}">
          <option value="" selected disabled>Choose…</option>${opts}</select></li>`;
    }).join('');
    list.querySelectorAll('select.player-pick').forEach((sel) => {
      sel.addEventListener('change', async () => {
        const name = sel.dataset.name;
        const action = sel.value;
        const ask = PLAYER_ASK[action];
        if (ask && !confirm(ask(name))) { sel.value = ''; return; }
        await runPlayerAction(name, action);
      });
    });
  }

  async function runPlayerAction(name, action) {
    const data = await api(`api/player/${encodeURIComponent(name)}/${encodeURIComponent(action)}`, {
      method: 'POST',
    });
    $('#player-reply').textContent = data.reply ?? data.error ?? '';
    refreshPlayersTab();
  }

  $('#f-player-action').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('#player-name').value.trim();
    const action = $('#player-action').value;
    if (!name) return;
    if (!action) { $('#player-reply').textContent = 'Choose what to do first.'; return; }
    const ask = PLAYER_ASK[action];
    if (ask && !confirm(ask(name))) return;
    await runPlayerAction(name, action);
  });
  setInterval(() => {
    if ($('#tab-players').classList.contains('active')) refreshPlayersTab();
  }, 5000);

  // ------------------------------------------------------------------
  // Properties tab
  // ------------------------------------------------------------------
  // Render an editor for a server.properties key based on the type metadata
  // the API surfaces in /api/properties. Picking the right widget per key
  // means the user doesn't have to guess "what shape goes here" — enums
  // become dropdowns, bools become true/false selects, ints become number
  // inputs with the schema bounds, and the rest stay as plain text.
  function renderPropEditor(k, v, types, enums, ranges) {
    const t = types[k];
    const safeKey = esc(k);
    const safeVal = esc(v == null ? '' : String(v));
    if (t === 'bool') {
      const isTrue = String(v).toLowerCase() === 'true';
      return `<select data-key="${safeKey}">` +
        `<option value="true"${isTrue ? ' selected' : ''}>true</option>` +
        `<option value="false"${!isTrue ? ' selected' : ''}>false</option>` +
        `</select>`;
    }
    if (t === 'enum' && enums[k]) {
      return `<select data-key="${safeKey}">` +
        enums[k].map((opt) =>
          `<option value="${esc(opt)}"${opt === v ? ' selected' : ''}>${esc(opt)}</option>`
        ).join('') +
        `</select>`;
    }
    if (t === 'int') {
      const r = ranges[k];
      const attrs = r ? `min="${r[0]}" max="${r[1]}"` : '';
      return `<input type="number" ${attrs} value="${safeVal}" data-key="${safeKey}" />`;
    }
    return `<input type="text" value="${safeVal}" data-key="${safeKey}" />`;
  }

  async function loadProperties() {
    const data = await api('api/properties');
    // Surface which world the user is currently configuring. Per-world is
    // the whole point — without this label the table looks the same
    // regardless of which world is active, which has confused users.
    try {
      const w = await api('api/worlds');
      const active = (w && w.active) || 'default';
      const ctx = $('#props-active-world');
      if (ctx) ctx.textContent = active;
    } catch { /* non-fatal cosmetic */ }
    const tbody = $('#props-table tbody');
    tbody.innerHTML = '';
    const editable = new Set(data.editable);
    const types = data.types || {};
    const enums = data.enums || {};
    const ranges = data.int_ranges || {};
    // Pull the headline gameplay settings to the top so the user sees them
    // without scrolling — `level-name` (the world's save-folder name) first,
    // then the everyday gameplay knobs. Everything else stays in alphabetical
    // order below this priority list.
    const PROP_PRIORITY = [
      'level-name', 'motd', 'gamemode', 'force-gamemode', 'difficulty',
      'max-players', 'pvp', 'hardcore', 'online-mode', 'white-list',
      'view-distance', 'simulation-distance', 'level-type', 'level-seed',
    ];
    const priorityIndex = new Map(PROP_PRIORITY.map((k, i) => [k, i]));
    const sortedEntries = Object.entries(data.properties).sort(([a], [b]) => {
      const ai = priorityIndex.has(a) ? priorityIndex.get(a) : Infinity;
      const bi = priorityIndex.has(b) ? priorityIndex.get(b) : Infinity;
      if (ai !== bi) return ai - bi;
      return a.localeCompare(b);
    });
    const worldGenOnly = new Set(data.world_gen_only || []);
    const live = new Set(data.live || []);
    const labels = data.labels || {};
    // A plain name over the key; a key the server names nothing is said as
    // its words ("server-port" reads "Server port").
    const labelOf = (k) => labels[k] || (k.charAt(0).toUpperCase() + k.slice(1)).replace(/[-_.]/g, ' ');
    // When a change takes effect, in words on the row (#1455). A key read
    // only when a world is generated does nothing to this one.
    const whenOf = (k) => (worldGenOnly.has(k)
      ? 'Used only when a new world is created; changing it does not change this world.'
      : live.has(k) ? '' : 'Takes effect after a restart.');
    sortedEntries.forEach(([k, v]) => {
      const isEditable = editable.has(k);
      const tr = document.createElement('tr');
      const when = isEditable ? whenOf(k) : 'Set by the add-on.';
      const valCell = isEditable
        ? renderPropEditor(k, v, types, enums, ranges)
        : `<code>${esc(v)}</code>`;
      // Save is there only while the row holds a change.
      const actionCell = isEditable
        ? `<button class="btn btn-primary" data-save-key="${esc(k)}" hidden>Save</button>`
        : '';
      tr.innerHTML = `<td><span class="prop-label">${esc(labelOf(k))}</span><code class="prop-key">${esc(k)}</code>${when ? `<span class="prop-when">${esc(when)}</span>` : ''}</td><td>${valCell}</td><td>${actionCell}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('[data-key]').forEach((input) => {
      input.dataset.saved = input.value;
      const show = () => {
        const b = tbody.querySelector(`button[data-save-key="${CSS.escape(input.dataset.key)}"]`);
        if (b && !b.disabled) {
          b.hidden = input.value === input.dataset.saved;
          b.textContent = 'Save';
        }
      };
      input.addEventListener('input', show);
      input.addEventListener('change', show);
    });
    tbody.querySelectorAll('button[data-save-key]').forEach((b) => {
      b.addEventListener('click', async () => {
        const key = b.dataset.saveKey;
        // input OR select — both expose .value
        const input = tbody.querySelector(`[data-key="${CSS.escape(key)}"]`);
        if (!input) return;
        b.disabled = true;
        b.textContent = 'Saving…';
        const resp = await api('api/properties', {
          method: 'POST',
          body: JSON.stringify({ key, value: input.value }),
        });
        b.disabled = false;
        if (resp.error) {
          alert(resp.error);
          b.textContent = 'Save';
        } else {
          // Saved to this world's server.properties (the source of truth).
          // Some keys apply live via RCON; the rest take effect on restart.
          input.dataset.saved = input.value;
          b.textContent = resp.live ? 'Saved ✓' : 'Saved — restart to apply';
          setTimeout(() => { if (input.value === input.dataset.saved) b.hidden = true; b.textContent = 'Save'; }, 2500);
        }
      });
    });
  }

  // ------------------------------------------------------------------
  // Backups tab
  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
  // Worlds (switchable server profiles, new in 1.3.0)
  // ------------------------------------------------------------------
  async function loadWorlds() {
    const data = await api('api/worlds');
    const tbody = document.querySelector('#worlds-table tbody');
    tbody.innerHTML = '';
    (data.worlds || []).forEach((w) => {
      const tr = document.createElement('tr');
      const activeBadge = w.active
        ? '<span class="world-active">● active</span>'
        : '';
      // Surface each world's per-world gameplay settings so the user can see
      // at a glance that switching loads THAT world's mode — not whatever
      // they last edited on a different world. This is the "settings don't
      // appear to move with me" UX hint.
      // Each value says what it is: the game mode, the difficulty and the
      // world type are all "normal"-ish words, and bare they read as a stutter.
      const s = w.settings || {};
      const cap = (v) => { const t = String(v).replace(/^minecraft:/, '').replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
      const meta = [
        s.gamemode ? cap(s.gamemode) : '',
        s.difficulty ? `${cap(s.difficulty)} difficulty` : '',
        s['level-type'] ? `${cap(s['level-type'])} world` : '',
        s['white-list'] === 'true' ? 'Whitelist on' : '',
        s['online-mode'] === 'false' ? 'Offline mode' : '',
      ].filter(Boolean);
      const settingsCell = meta.length
        ? `<span class="world-settings">${esc(meta.join(' · '))}</span>`
        : '<span class="muted">(no settings yet)</span>';
      // Export (download .zip) is available for every world — including the
      // active one. Switching/deleting is only meaningful for non-active.
      // The everyday buttons sit in one even grid; Delete is apart, under a rule.
      const exportBtn = `<a class="btn btn-ghost" href="api/worlds/${encodeURIComponent(w.name)}/export" download title="Download this world's save as a .zip for sharing or off-host backup">Download</a>`;
      const renameBtn = `<button class="btn btn-ghost" data-rename="${esc(w.name)}" data-active="${w.active ? '1' : ''}" title="Give this world a new name">Rename</button>`;
      const actions = w.active
        ? `<div class="world-actions">${renameBtn}${exportBtn}</div>`
        : `<div class="world-actions"><button class="btn btn-primary" data-switch="${esc(w.name)}">Switch</button>${renameBtn}${exportBtn}</div>
          <div class="world-danger"><button class="btn btn-danger" data-delete="${esc(w.name)}">Delete</button></div>`;
      const curatedBadge = w.curated
        ? ` <span class="curated-badge" title="Installed from the Featured Worlds catalog">${esc(w.curated.name || w.curated.id)}${w.curated.version ? ' v' + esc(w.curated.version) : ''}</span>`
        : '';
      tr.innerHTML = `
        <td><code>${esc(w.name)}</code>${curatedBadge}</td>
        <td>${fmtSize(w.size_bytes)}</td>
        <td>${settingsCell}</td>
        <td>${activeBadge}</td>
        <td>${actions}</td>
      `;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-switch]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.switch;
        if (!confirm(`Switch active world to "${name}"? The add-on will restart itself to load it — this panel is unreachable for ~30s while it comes back.`)) return;
        // The switch endpoint already restarts the whole add-on via the
        // Supervisor (which re-points the world symlink). Do NOT also fire an
        // RCON restart here — that races against the container teardown and
        // was part of why switching felt broken.
        const resp = await api(`api/worlds/${encodeURIComponent(name)}/switch`, { method: 'POST' });
        alert(resp.message || resp.warning || resp.error || 'unknown error');
        loadWorlds();
      });
    });
    tbody.querySelectorAll('button[data-rename]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.rename;
        const next = (prompt(`New name for "${name}" (letters, digits, _ and -, up to 32):`, name) || '').trim();
        if (!next || next === name) return;
        if (b.dataset.active && !confirm(`"${name}" is the running world. The server will stop, the world will be renamed to "${next}" and the add-on will restart (the panel is unreachable for ~30s). Continue?`)) return;
        const resp = await api(`api/worlds/${encodeURIComponent(name)}/rename`, {
          method: 'POST', body: JSON.stringify({ new_name: next }),
        });
        alert(resp.message || resp.warning || resp.error || 'unknown error');
        loadWorlds();
      });
    });
    tbody.querySelectorAll('button[data-delete]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.delete;
        if (!confirm(`DELETE the world "${name}" permanently? This removes its world files, plugins, and backup history. This cannot be undone.`)) return;
        const resp = await api(`api/worlds/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (resp.error) alert(resp.error);
        loadWorlds();
      });
    });
  }

  // ------------------------------------------------------------------
  // Featured worlds (curated one-click installs, e.g. Drehmal) — new in 1.14.0
  // ------------------------------------------------------------------
  let curatedPollTimer = null;

  async function loadCuratedWorlds() {
    const root = $('#curated-list');
    if (!root) return;
    let data;
    try {
      data = await api('api/curated-worlds');
    } catch (e) {
      root.innerHTML = '<p class="muted">Could not load the featured-worlds catalog.</p>';
      return;
    }
    const inst = data.install || {};
    const running = inst.status === 'running';
    root.innerHTML = '';
    (data.worlds || []).forEach((w) => {
      const card = document.createElement('div');
      card.className = 'curated-card';
      const installed = w.installed_as;
      const busyThis = running && inst.id === w.id;
      const btn = installed
        ? `<span class="curated-installed">✓ Installed as <code>${esc(installed)}</code> — switch to it in the table above</span>`
        : `<button class="btn btn-primary" data-curated-install="${esc(w.id)}" ${running ? 'disabled' : ''}>${busyThis ? 'Installing…' : 'Install'}</button>`;
      card.innerHTML = `
        <div class="curated-head">
          <strong>${esc(w.name)}</strong>
          ${w.version ? `<span class="muted">v${esc(w.version)}</span>` : ''}
          ${w.minecraft_version ? `<span class="curated-pill">${esc(w.server_type)} ${esc(w.minecraft_version)}</span>` : ''}
          ${w.size_estimate_mb ? `<span class="curated-pill">~${Math.round(w.size_estimate_mb / 1024 * 10) / 10} GB</span>` : ''}
        </div>
        ${w.tagline ? `<div class="curated-tagline">${esc(w.tagline)}</div>` : ''}
        ${w.description ? `<p class="muted">${esc(w.description)}</p>` : ''}
        ${w.notes ? `<p class="muted curated-notes">${esc(w.notes)}</p>` : ''}
        ${w.homepage ? `<p class="muted"><a href="${esc(w.homepage)}" target="_blank" rel="noopener">${esc(w.homepage)}</a></p>` : ''}
        <div class="curated-actions">${btn}</div>
      `;
      root.appendChild(card);
    });

    // Progress / log box while an install is running (or just finished).
    const box = $('#curated-progress');
    if (box) {
      if (inst.status === 'idle') {
        box.hidden = true;
      } else {
        box.hidden = false;
        const tail = (inst.log || []).slice(-12).map(esc).join('\n');
        box.innerHTML =
          `<div class="curated-status curated-status-${esc(inst.status)}">` +
          (inst.status === 'running' ? '⏳ ' : inst.status === 'done' ? '✓ ' : '✗ ') +
          esc(inst.message || inst.status) + '</div>' +
          (tail ? `<pre class="reply">${tail}</pre>` : '') +
          (inst.error ? `<div class="curated-status curated-status-error">${esc(inst.error)}</div>` : '');
      }
    }

    root.querySelectorAll('button[data-curated-install]').forEach((b) => {
      b.addEventListener('click', async () => {
        const id = b.dataset.curatedInstall;
        if (!confirm(`Install "${id}"? This downloads the full world and resource pack (can take several minutes and a lot of disk). It will be staged as a new world you can switch to — your current world is untouched.`)) return;
        const resp = await api(`api/curated-worlds/${encodeURIComponent(id)}/install`, { method: 'POST', body: JSON.stringify({}) });
        if (resp.error) { alert(resp.error); }
        loadCuratedWorlds();
        startCuratedPolling();
      });
    });

    // Keep polling while an install is in flight; stop once it settles.
    if (running) {
      startCuratedPolling();
    } else if (curatedPollTimer) {
      clearInterval(curatedPollTimer);
      curatedPollTimer = null;
      if (inst.status === 'done') loadWorlds();  // surface the new world above
    }
  }

  function startCuratedPolling() {
    if (curatedPollTimer) return;
    curatedPollTimer = setInterval(loadCuratedWorlds, 2500);
  }

  // ------------------------------------------------------------------
  // New-world wizard (1.13.0) — opened from the Worlds-tab Create button.
  // Same shape as the first-run wizard but only covers per-world settings
  // (no EULA / server type / plugins / memory). 5 steps: name+seed,
  // gameplay, rules, players & access, review.
  // ------------------------------------------------------------------
  const newworldRoot = $('#newworld-wizard');
  if (newworldRoot) {
    const steps = Array.from(document.querySelectorAll('.setup-step[data-newworld-step]'));
    const total = steps.length;
    $('#newworld-step-total').textContent = String(total);
    let current = 1;

    const nwBtn = {
      back: $('#newworld-back'),
      next: $('#newworld-next'),
      submit: $('#newworld-submit'),
      cancel: $('#newworld-cancel'),
      status: $('#newworld-status'),
    };
    const nwRadio = (name, fallback) =>
      document.querySelector(`input[name="${name}"]:checked`)?.value || fallback;

    function nwShow(n) {
      current = Math.max(1, Math.min(total, n));
      steps.forEach((el) => { el.hidden = Number(el.dataset.newworldStep) !== current; });
      $('#newworld-step-num').textContent = String(current);
      $('#newworld-progress-fill').style.width = `${(current / total) * 100}%`;
      nwBtn.back.disabled = current === 1;
      nwBtn.next.hidden = current === total;
      nwBtn.submit.hidden = current !== total;
      nwBtn.status.textContent = '';
      if (current === total) nwRenderReview();
    }

    function nwValidate() {
      if (current === 1) {
        const name = $('#newworld-name').value.trim();
        if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) {
          return 'World name must be 1-32 letters, digits, _ or -.';
        }
      }
      if (current === 4) {
        const mp = Number($('#newworld-max-players').value);
        if (!Number.isInteger(mp) || mp < 1 || mp > 1000) return 'Max players must be between 1 and 1000.';
        const sp = Number($('#newworld-spawn-protection').value);
        if (!Number.isInteger(sp) || sp < 0 || sp > 10000) return 'Spawn protection must be between 0 and 10000.';
      }
      return null;
    }

    function nwCollect() {
      return {
        name: $('#newworld-name').value.trim(),
        seed: $('#newworld-seed').value.trim(),
        gamemode: nwRadio('newworld-gamemode', 'survival'),
        force_gamemode: $('#newworld-force-gamemode').checked,
        difficulty: nwRadio('newworld-difficulty', 'normal'),
        level_type: nwRadio('newworld-level-type', 'minecraft:normal'),
        pvp: $('#newworld-pvp').checked,
        hardcore: $('#newworld-hardcore').checked,
        max_players: Number($('#newworld-max-players').value) || 20,
        white_list: $('#newworld-whitelist').checked,
        spawn_protection: Number($('#newworld-spawn-protection').value) || 16,
      };
    }

    function nwRenderReview() {
      const b = nwCollect();
      const rows = [
        ['Name', b.name],
        ['Seed', b.seed || '(random)'],
        ['Gamemode', `${b.gamemode}${b.force_gamemode ? ' (forced on every join)' : ''}${b.hardcore ? ' — HARDCORE' : ''}`],
        ['Difficulty', b.difficulty],
        ['Terrain', b.level_type.replace(/^minecraft:/, '')],
        ['PvP', b.pvp ? 'enabled' : 'disabled'],
        ['Max players', String(b.max_players)],
        ['Whitelist', b.white_list ? 'on — only listed players may join' : 'off (open)'],
        ['Spawn protection', `${b.spawn_protection} blocks`],
      ];
      $('#newworld-review').innerHTML = rows
        .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(String(v))}</dd>`).join('');
    }

    function nwClose() {
      newworldRoot.hidden = true;
      // Reset fields for next open.
      $('#newworld-name').value = '';
      $('#newworld-seed').value = '';
      $('#newworld-force-gamemode').checked = true;
      $('#newworld-pvp').checked = true;
      $('#newworld-hardcore').checked = false;
      $('#newworld-whitelist').checked = false;
      $('#newworld-max-players').value = '20';
      $('#newworld-spawn-protection').value = '16';
      document.querySelector('input[name="newworld-gamemode"][value="survival"]').checked = true;
      document.querySelector('input[name="newworld-difficulty"][value="normal"]').checked = true;
      document.querySelector('input[name="newworld-level-type"][value="minecraft:normal"]').checked = true;
      nwShow(1);
    }

    nwBtn.next.addEventListener('click', () => {
      const err = nwValidate();
      if (err) { nwBtn.status.textContent = err; return; }
      nwShow(current + 1);
    });
    nwBtn.back.addEventListener('click', () => nwShow(current - 1));
    nwBtn.cancel.addEventListener('click', nwClose);

    nwBtn.submit.addEventListener('click', async () => {
      const err = nwValidate();
      if (err) { nwBtn.status.textContent = err; return; }
      nwBtn.submit.disabled = true;
      nwBtn.back.disabled = true;
      nwBtn.status.textContent = 'Staging the world…';
      const body = nwCollect();
      const resp = await api('api/worlds', { method: 'POST', body: JSON.stringify(body) });
      nwBtn.submit.disabled = false;
      nwBtn.back.disabled = false;
      if (resp.error) {
        nwBtn.status.textContent = `Error: ${resp.error}`;
        return;
      }
      $('#world-reply').textContent =
        `Staged "${body.name}". Switch to it from the table above and the add-on will restart to boot it.`;
      nwClose();
      loadWorlds();
      // Offer to switch right away so the user doesn't end up editing the
      // OLD active world's settings under the impression they're tuning
      // the world they just created.
      if (confirm(`Switch to "${body.name}" now? The add-on will restart and the new world will boot.`)) {
        const sw = await api(`api/worlds/${encodeURIComponent(body.name)}/switch`, { method: 'POST' });
        alert(sw.message || sw.warning || sw.error || 'unknown error');
        loadWorlds();
      }
    });

    $('#btn-newworld').addEventListener('click', () => {
      newworldRoot.hidden = false;
      nwShow(1);
      // Focus the name field for keyboard-first users.
      setTimeout(() => $('#newworld-name').focus(), 50);
    });
  }

  async function loadBackups() {
    const data = await api('api/backups');
    const host = $('#backups-panel');
    const git = data.git || [];
    const arc = data.archives || [];

    // One short row per snapshot: when (local time) and what it is. The
    // commit's subject is "backup <UTC stamp>", which only repeats the time in
    // another zone; what it is comes from the kind the add-on writes beside it.
    const when = (ts) => new Date(ts * 1000).toLocaleString([], {
      weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
    const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const dayOf = (ts) => new Date(ts * 1000).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    // Every row is the same two parts: the time over what it is, and on the
    // right the one thing to do with it (Restore, or open a folded run).
    const snapText = (head, sub) => `<div class="snap-text"><strong>${esc(head)}</strong><span class="muted">${esc(sub)}</span></div>`;
    const chevron = '<svg class="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
    // Every Restore names the time it goes back to (#1459), so a button is
    // never read as belonging to the row above or below it.
    const row = (ts, label, ref, short, extra) => `
      <li class="snap">
        ${snapText(short ? clock(ts) : when(ts), [label, extra].filter(Boolean).join(' · '))}
        <button class="btn btn-ghost snap-restore" data-restore="${esc(ref)}" data-when="${esc(when(ts))}">Restore ${esc(clock(ts))}</button>
      </li>`;
    const KINDS = { scheduled: 'Scheduled backup', manual: 'Manual backup', 'before a world change': 'Before a world change' };
    const gitLabel = (c) => KINDS[c.kind] || 'Backup';
    // A snapshot is only kept when the world changed since the one before it.
    const gitExtra = (c) => ['world changed', c.players == null ? '' : (c.players === 0 ? 'nobody online' : `${c.players} online`)].filter(Boolean).join(' · ');
    // Within a day, a run of snapshots that read the same (same kind, same
    // players) folds into one line (#1292) that says how many it holds and
    // the newest one's time (#1459); opening it lists every one with its
    // time and its own Restore. Nothing is dropped.
    const sameRun = (a, b) => a.kind === b.kind && gitExtra(a) === gitExtra(b);
    const clump = (items) => {
      const out = [];
      items.forEach((c) => {
        const last = out[out.length - 1];
        if (last && sameRun(last[0], c)) last.push(c);
        else out.push([c]);
      });
      return out;
    };
    const rows = (items) => clump(items).map((g) => {
      if (g.length === 1) return row(g[0].ts, gitLabel(g[0]), g[0].sha, true, gitExtra(g[0]));
      const head = `${g.length} similar snapshots, latest ${clock(g[0].ts)}`;
      const sub = [`earliest ${clock(g[g.length - 1].ts)}`, gitLabel(g[0]), gitExtra(g[0])].filter(Boolean).join(' · ');
      // The rows inside share the group's description, so each says only its time.
      return `<li class="snap-clump"><details><summary class="snap">${snapText(head, sub)}
        <span class="btn btn-ghost snap-open">${chevron}<span class="snap-show">Show</span><span class="snap-hide">Hide</span></span></summary>
        <ul class="snap-list snap-inner">${g.map((c) => row(c.ts, '', c.sha, true, '')).join('')}</ul></details></li>`;
    }).join('');
    const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    const shortDay = (ts) => new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    // How many there are and how far back they go, above the list.
    const countLine = (items, word, capped) => (items.length
      ? `<p class="muted snap-count">${esc(`${capped ? `The newest ${plural(items.length, word)}` : plural(items.length, word)} · oldest ${shortDay(items[items.length - 1].ts)}`)}</p>`
      : '');
    const renderGit = () => {
      if (!git.length) return '<p class="muted">No git snapshots yet.</p>';
      // Grouped by day, newest first: the newest day is open, older days are folded.
      const days = new Map();
      git.forEach((c) => {
        const d = dayOf(c.ts);
        if (!days.has(d)) days.set(d, []);
        days.get(d).push(c);
      });
      return countLine(git, 'snapshot', git.length >= 100)
        + [...days].map(([d, items], i) => `<details class="snap-day"${i === 0 ? ' open' : ''}><summary>${chevron}${esc(d)} <span class="muted">· ${plural(items.length, 'snapshot')}</span></summary><ul class="snap-list">${rows(items)}</ul></details>`).join('');
    };

    const renderArchives = () => {
      if (!arc.length) return '<p class="muted">No archive backups yet.</p>';
      return `${countLine(arc, 'archive', false)}<ul class="snap-list">${arc.map((a) => row(a.ts, `Archive · ${fmtSize(a.size)}`, a.name)).join('')}</ul>`;
    };

    host.innerHTML = `
      <p class="muted snap-note">Restore puts the whole world (and its nether and end) back as it was at that time and restarts the server. Anything built or changed since is lost.</p>
      <section class="sec"><h2>Git snapshots</h2>${renderGit()}</section>
      <section class="sec"><h2>Archives</h2>${renderArchives()}</section>
    `;
    host.querySelectorAll('button[data-restore]').forEach((b) => {
      b.addEventListener('click', async () => {
        const ref = b.dataset.restore;
        if (!confirm(`Roll the world back to ${b.dataset.when}?\n\nEverything that changed after that time will be lost. The server stops and starts again on that snapshot.`)) return;
        const data = await api(`api/restore/${encodeURIComponent(ref)}`, { method: 'POST' });
        alert(data.ok ? 'Restore staged; server restarting.' : `Restore failed:\n${data.output || data.error}`);
      });
    });
  }

  // ------------------------------------------------------------------
  // First-run setup wizard (1.11.0 — multi-step)
  // ------------------------------------------------------------------
  // The wizard is a stateful 9-step walkthrough. Each step is a
  // `<section class="setup-step" data-step="N">` element; we toggle the
  // `hidden` attribute to swap between them. Step 6 fetches a hardware
  // recommendation + draws the perf preview, step 7 hides the plugin
  // list for non-Bukkit server types, and step 9 renders a review
  // summary built from the same body
  // that gets POSTed to /api/setup.
  const wizardRoot = $('#setup-wizard');
  if (wizardRoot) {
    const steps = Array.from(document.querySelectorAll('.setup-step'));
    const totalSteps = steps.length;
    $('#setup-step-total').textContent = String(totalSteps);
    let current = 1;
    let recommendation = null;

    const $$btn = {
      back: $('#setup-back'),
      next: $('#setup-next'),
      submit: $('#setup-submit'),
      status: $('#setup-status'),
    };

    const isBukkit = () => ['paper', 'purpur', 'folia'].includes(serverType());
    const serverType = () => document.querySelector('input[name="setup-server-type"]:checked')?.value || 'paper';
    const audience = () => document.querySelector('input[name="setup-audience"]:checked')?.value || 'online';
    const radio = (name, fallback) => document.querySelector(`input[name="${name}"]:checked`)?.value || fallback;

    function showStep(n) {
      current = Math.max(1, Math.min(totalSteps, n));
      steps.forEach((el) => {
        el.hidden = Number(el.dataset.step) !== current;
      });
      $('#setup-step-num').textContent = String(current);
      $('#setup-progress-fill').style.width = `${(current / totalSteps) * 100}%`;
      $$btn.back.disabled = current === 1;
      $$btn.next.hidden = current === totalSteps;
      $$btn.submit.hidden = current !== totalSteps;
      $$btn.status.textContent = '';

      // Step-entry hooks. Step numbers track the data-step values in
      // index.html: 1 EULA, 2 server software, 3 connectivity, 4 world
      // basics, 5 players & access, 6 performance, 7 plugins,
      // 8 maintenance, 9 review.
      if (current === 6 && !recommendation) loadRecommendation();
      if (current === 6) renderPerfPreview();
      if (current === 7) updatePluginsVisibility();
      if (current === totalSteps) renderReview();
    }

    function validateStep() {
      if (current === 1 && !$('#setup-eula').checked) {
        return 'Please tick the EULA box to continue.';
      }
      if (current === 4) {
        const name = $('#setup-world-name').value.trim();
        if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) {
          return 'World name must be 1-32 letters, digits, _ or -.';
        }
      }
      if (current === 5) {
        const maxP = Number($('#setup-max-players').value);
        if (!Number.isInteger(maxP) || maxP < 1 || maxP > 1000) {
          return 'Max players must be between 1 and 1000.';
        }
        const sp = Number($('#setup-spawn-protection').value);
        if (!Number.isInteger(sp) || sp < 0 || sp > 10000) {
          return 'Spawn protection must be between 0 and 10000.';
        }
      }
      if (current === 6 && radio('setup-perf') === 'manual') {
        const mem = Number($('#setup-memory').value);
        if (!Number.isInteger(mem) || mem < 512 || mem > 65536) {
          return 'Memory must be a whole number between 512 and 65536.';
        }
      }
      if (current === 8) {
        const iv = Number($('#setup-backup-interval').value);
        if (!Number.isInteger(iv) || iv < 5 || iv > 1440) {
          return 'Backup interval must be 5-1440 minutes.';
        }
        const keep = Number($('#setup-backup-keep').value);
        if (!Number.isInteger(keep) || keep < 1 || keep > 500) {
          return 'Backup keep count must be 1-500.';
        }
      }
      return null;
    }

    // Performance preview: capacity estimate + sanity warnings, recomputed
    // every time step 6 is shown or the perf inputs change. Heuristic but
    // grounded — the numbers come from running real Paper servers and
    // observing where TPS starts dropping.
    function renderPerfPreview() {
      const host = document.querySelector('input[name="setup-perf"]:checked')?.value || 'auto';
      let mem, view, sim;
      if (host === 'auto' && recommendation) {
        mem = recommendation.memory_mb;
        view = recommendation.view_distance;
        sim = recommendation.simulation_distance;
      } else {
        mem = Number($('#setup-memory').value) || 2048;
        view = Number($('#setup-view').value) || 10;
        sim = Number($('#setup-sim').value) || 10;
      }
      // Heuristic capacity range. Players-per-MB scales linearly; sim
      // distance squared-ish penalty because tick cost grows with the
      // number of ticked chunks per player.
      const base = mem / 480;
      const simPenalty = Math.max(1, Math.pow(sim / 10, 1.6));
      const center = Math.max(1, Math.round(base / simPenalty));
      const low = Math.max(1, Math.round(center * 0.6));
      const high = Math.round(center * 1.4);

      const warnings = [];
      if (sim > view) warnings.push(
        `Your simulation-distance (${sim}) exceeds view-distance (${view}). ` +
        `Minecraft caps the effective sim-distance at the view-distance, so the higher value is wasted CPU. Lower sim-distance or raise view-distance.`
      );
      if (recommendation && mem > Math.max(1024, recommendation.host_total_mb - 1024)) warnings.push(
        `Heap ${mem} MB leaves little room for Home Assistant + the OS on a ${recommendation.host_total_mb} MB host. ` +
        `HA may be starved during peak Minecraft load. Drop memory below ${Math.max(1024, recommendation.host_total_mb - 2048)} MB.`
      );
      if (sim >= 16) warnings.push(
        `simulation-distance ≥ 16 is heavy — expect TPS dips on anything but a top-tier host with few players.`
      );
      if (mem < 1024) warnings.push(
        `Heap under 1 GB is uncomfortable for modern Paper; expect frequent GC pauses. Bump to at least 1024 MB.`
      );

      const html =
        `<div class="setup-preview-row"><strong>Expected capacity</strong>: <span class="setup-preview-emph">${low}–${high} players</span> ` +
        `<span class="muted">(comfortable; assumes mostly-survival gameplay with a few plugins)</span></div>` +
        (warnings.length
          ? '<ul class="setup-preview-warn">' + warnings.map((w) => `<li>${esc(w)}</li>`).join('') + '</ul>'
          : '<p class="setup-preview-ok">No warnings — this looks like a healthy combination.</p>');
      $('#setup-perf-preview').innerHTML = html;
    }
    // Keep the preview live as the user edits manual values.
    ['#setup-memory', '#setup-view', '#setup-sim'].forEach((sel) => {
      const el = $(sel); if (el) el.addEventListener('input', renderPerfPreview);
    });

    async function loadRecommendation() {
      const summary = $('#setup-rec-summary');
      summary.textContent = 'Detecting host hardware…';
      try {
        recommendation = await api('api/recommend');
        if (!recommendation || !recommendation.memory_mb) throw new Error('no recommendation');
        summary.innerHTML =
          `<strong>Detected:</strong> ${recommendation.host_total_mb} MB RAM, ${recommendation.cpu_count} CPU(s). ` +
          `<strong>Recommended:</strong> memory ${recommendation.memory_mb} MB, view-distance ${recommendation.view_distance}, ` +
          `simulation-distance ${recommendation.simulation_distance}. ${esc(recommendation.rationale.memory)}`;
        $('#setup-memory').value = recommendation.memory_mb;
        $('#setup-view').value = recommendation.view_distance;
        $('#setup-sim').value = recommendation.simulation_distance;
      } catch {
        summary.textContent = 'Could not detect host hardware; defaulting to 2048 MB heap. You can adjust manually.';
      }
    }

    function updatePluginsVisibility() {
      const note = $('#setup-plugins-note');
      const grid = $('#setup-plugins-grid');
      if (isBukkit()) {
        note.textContent = `Plugins install into the active world's plugins/ folder on every boot.`;
        grid.hidden = false;
      } else {
        note.textContent = `Your chosen server (${serverType()}) doesn't load Bukkit plugins — this step is a no-op for you.`;
        grid.hidden = true;
      }
    }

    document.querySelectorAll('input[name="setup-perf"]').forEach((el) => {
      el.addEventListener('change', () => {
        $('#setup-perf-manual').hidden = radio('setup-perf') !== 'manual';
      });
    });

    function collect() {
      const body = {
        eula: true,
        server_type: serverType(),
        online_mode: audience() === 'online',
        enable_bedrock_support: radio('setup-bedrock', 'on') === 'on',
        active_world: $('#setup-world-name').value.trim(),
        gamemode: radio('setup-gamemode', 'survival'),
        force_gamemode: $('#setup-force-gamemode').checked,
        difficulty: radio('setup-difficulty', 'normal'),
        level_type: radio('setup-level-type', 'minecraft:normal'),
        level_seed: $('#setup-seed').value.trim(),
        pvp: $('#setup-pvp').checked,
        hardcore: $('#setup-hardcore').checked,
        max_players: Number($('#setup-max-players').value) || 20,
        white_list: $('#setup-whitelist').checked,
        spawn_protection: Number($('#setup-spawn-protection').value) || 16,
        backup_interval_minutes: Number($('#setup-backup-interval').value) || 60,
        backup_keep_count: Number($('#setup-backup-keep').value) || 48,
      };
      if ($('#setup-nightly-restart').checked) {
        // Cron expression — 4 AM daily. Documented in config.yaml.
        body.auto_restart_schedule = '0 4 * * *';
      }
      const perf = radio('setup-perf', 'auto');
      if (perf === 'auto' && recommendation) {
        body.memory_mb = recommendation.memory_mb;
        body.view_distance = recommendation.view_distance;
        body.simulation_distance = recommendation.simulation_distance;
      } else if (perf === 'manual') {
        body.memory_mb = Number($('#setup-memory').value);
        body.view_distance = Number($('#setup-view').value);
        body.simulation_distance = Number($('#setup-sim').value);
      }
      if (isBukkit()) {
        document.querySelectorAll('#setup-plugins-grid input[data-plugin]').forEach((cb) => {
          body[cb.dataset.plugin] = cb.checked;
        });
      }
      return body;
    }

    function renderReview() {
      const b = collect();
      const dl = $('#setup-review');
      const rows = [
        ['Server software', b.server_type],
        ['Mode', b.online_mode ? 'Online (Mojang auth)' : 'Offline / LAN'],
        ['Bedrock cross-play', b.enable_bedrock_support ? 'enabled (Geyser + Floodgate)' : 'disabled'],
        ['World name', b.active_world],
        ['Gamemode', `${b.gamemode}${b.force_gamemode ? ' (forced on every join)' : ''}${b.hardcore ? ' — HARDCORE' : ''}`],
        ['Difficulty', b.difficulty],
        ['Terrain', b.level_type.replace(/^minecraft:/, '')],
        ['Seed', b.level_seed || '(random)'],
        ['PVP', b.pvp ? 'enabled' : 'disabled'],
        ['Max players', String(b.max_players)],
        ['Whitelist', b.white_list ? 'on — only listed players may join' : 'off (open)'],
        ['Spawn protection', `${b.spawn_protection} blocks`],
      ];
      if (b.memory_mb) {
        rows.push(['Memory', `${b.memory_mb} MB`]);
        rows.push(['View / sim distance', `${b.view_distance} / ${b.simulation_distance}`]);
      }
      rows.push(['Backups', `every ${b.backup_interval_minutes} min, keep ${b.backup_keep_count}`]);
      if (b.auto_restart_schedule) rows.push(['Nightly restart', `${b.auto_restart_schedule} (4 AM)`]);
      if (isBukkit()) {
        const plugins = Object.entries(b)
          .filter(([k, v]) => k.startsWith('install_') && v)
          .map(([k]) => k.replace(/^install_/, ''));
        rows.push(['Plugins', plugins.length ? plugins.join(', ') : '(none)']);
      }
      dl.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(String(v))}</dd>`).join('');
    }

    $$btn.next.addEventListener('click', () => {
      const err = validateStep();
      if (err) { $$btn.status.textContent = err; return; }
      showStep(current + 1);
    });
    $$btn.back.addEventListener('click', () => showStep(current - 1));

    $$btn.submit.addEventListener('click', async () => {
      const err = validateStep();
      if (err) { $$btn.status.textContent = err; return; }
      $$btn.submit.disabled = true;
      $$btn.back.disabled = true;
      $$btn.status.textContent = 'Saving and restarting the add-on…';
      const resp = await api('api/setup', {
        method: 'POST',
        body: JSON.stringify(collect()),
      });
      if (resp.error) {
        $$btn.status.textContent = `Error: ${resp.error}`;
        $$btn.submit.disabled = false;
        $$btn.back.disabled = current === 1;
        return;
      }
      $$btn.status.textContent = resp.message || 'Restarting — the panel will be unreachable for ~30s.';
      // The Supervisor tears us down on restart; nothing more to do here.
    });

    showStep(1);
  }

  // ------------------------------------------------------------------
  // Crash banner — surfaces the last few error lines when the JVM
  // exited unexpectedly. Dismissal is "until the signature changes" so
  // a fresh crash brings the banner back.
  // ------------------------------------------------------------------
  let lastCrashSig = null;
  let crashDismissed = false;
  $('#crash-dismiss')?.addEventListener('click', () => {
    crashDismissed = true;
    $('#crash-banner').hidden = true;
  });
  function renderCrashBanner(crash) {
    const banner = $('#crash-banner');
    if (!banner) return;
    if (!crash || !crash.excerpt || !crash.excerpt.length) {
      banner.hidden = true;
      lastCrashSig = null;
      crashDismissed = false;
      return;
    }
    const sig = `${crash.log_size}:${crash.excerpt[crash.excerpt.length - 1]}`;
    if (sig !== lastCrashSig) {
      crashDismissed = false;
      lastCrashSig = sig;
    }
    if (crashDismissed) return;
    $('#crash-excerpt').textContent = crash.excerpt.join('\n');
    $('#crash-summary').textContent =
      `Showing the last ${crash.excerpt.length} interesting log lines.`;
    banner.hidden = false;
  }

  // ------------------------------------------------------------------
  // World import
  // ------------------------------------------------------------------
  $('#f-world-import')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('#world-import-name').value.trim();
    const file = $('#world-import-file').files[0];
    if (!name || !file) return;
    const reply = $('#world-import-reply');
    reply.textContent = `Uploading ${file.name} (${fmtSize(file.size)})…`;
    const fd = new FormData();
    fd.append('name', name);
    fd.append('file', file);
    const resp = await fetch('api/worlds/import', { method: 'POST', body: fd, credentials: 'same-origin' });
    let out; try { out = await resp.json(); } catch { out = { error: await resp.text() }; }
    if (out.ok) {
      reply.textContent = out.message || `Imported '${name}'.`;
      $('#world-import-name').value = '';
      $('#world-import-file').value = '';
      loadWorlds();
    } else {
      reply.textContent = `Import failed: ${out.error || resp.status}`;
    }
  });

  // ------------------------------------------------------------------
  // Add-ons: one screen for everything in this world. The list at the top
  // is read off the world's folders (plugins, mods, data packs, resource
  // packs) so it holds what was added by hand too; every row says whether
  // it is working or waiting on a restart, and the banner above it says
  // what a restart would finish. The browser below adds more.
  // ------------------------------------------------------------------
  // updates: per project id, whether Modrinth has a newer build (null until
  // asked; asked when the pane opens, never on the 5-second refresh).
  const addonState = { kind: 'all', q: '', offset: 0, info: null, world: null, restarting: false, updates: null, updatesError: '' };
  // What has been picked for "Add all to world", across searches and kinds:
  // key `${kind}:${id}` -> { id, kind, title }.
  const addonPicked = new Map();
  const pickKey = (item) => `${item.kind}:${item.id}`;
  const KIND_HEADINGS = { plugin: 'Plugins', mod: 'Server mods', datapack: 'Data packs', resourcepack: 'Resource packs' };
  const SOURCE_TEXT = {
    browser: 'Added from the browser',
    manual: 'Added by hand',
  };

  const fmtCount = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));

  // A compact mark for the kind, for the items that have no art of their own.
  const svg = (d) => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const KIND_ICON = {
    plugin: svg('<path d="M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3"/>'),
    mod: svg('<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>'),
    datapack: svg('<path d="M12 3l8 4-8 4-8-4zM4 12l8 4 8-4M4 16.5l8 4 8-4"/>'),
    resourcepack: svg('<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M4 17l5-4 4 3 3-2 4 3"/>'),
  };

  function iconHtml(item) {
    return item.icon
      ? `<img class="addon-icon" src="${esc(item.icon)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
      : `<div class="addon-icon addon-icon-kind" aria-hidden="true">${KIND_ICON[item.kind] || KIND_ICON.plugin}</div>`;
  }

  // --- the world list ---------------------------------------------------
  function worldRow(item) {
    const row = document.createElement('div');
    row.className = 'addon-row';
    const meta = [item.version, SOURCE_TEXT[item.source]];
    if (item.required_by) meta.push(`needed by ${item.required_by}`);
    const actions = [];
    if (item.status === 'unused') {
      actions.push(`<button class="btn btn-primary" data-world-use="${esc(item.file)}">Use in this world</button>`);
    }
    // The row says when Modrinth has a newer build than this one; the
    // updates themselves are one "Update N" above the list (#1456).
    let updateLine = '';
    if (item.updatable) {
      const u = addonState.updates && addonState.updates[item.id];
      if (u && u.state === 'available') {
        updateLine = `<span class="addon-update is-new">Update to ${esc(u.version || 'a newer version')} available</span>`;
      } else if (u && u.state === 'current') {
        updateLine = '';
      } else if (u && u.state === 'none') {
        updateLine = '<span class="addon-update">No build for this server version on Modrinth</span>';
      } else if (u || addonState.updatesError) {
        updateLine = '<span class="addon-update">Could not check for updates</span>';
      } else if (addonState.updates) {
        updateLine = ''; // added after the check: it is the newest build
      } else {
        updateLine = '<span class="addon-update">Checking for updates…</span>';
      }
    }
    // The one of a conflicting pair to remove carries the pair's notice and
    // the one emphasised Remove, inside it; its ordinary Remove goes.
    const removeThis = !!(item.conflict && item.conflict.remove_this);
    if (item.removable && !removeThis) {
      actions.push(`<button class="btn btn-ghost addon-remove" data-world-remove="${esc(item.file)}" data-kind="${esc(item.kind)}" data-title="${esc(item.title)}">Remove</button>`);
    }
    row.innerHTML = `
      ${iconHtml(item)}
      <div class="addon-row-main">
        <strong>${esc(item.title)}</strong>
        <span class="muted">${meta.filter(Boolean).map(esc).join(' · ')}</span>
        ${updateLine}
      </div>
      <span class="addon-status addon-status-${esc(item.status)}">${esc(item.status_text)}</span>
      <div class="addon-row-actions">${actions.join('')}</div>
      ${conflictHtml(item)}
      <div class="addon-note" aria-live="polite"></div>`;
    return row;
  }

  // A known-conflicting pair (addons.CONFLICTS) gets one notice, on the row
  // addons.py marks to remove (remove_this: the other already does its
  // job): it names both and holds the recommended Remove. The kept row says
  // nothing about it. Nothing is removed for the owner.
  function conflictHtml(item) {
    const c = item.conflict;
    if (!c || !c.remove_this) return '';
    const remove = item.removable
      ? `<button class="btn btn-danger addon-remove" data-world-remove="${esc(item.file)}" data-kind="${esc(item.kind)}" data-title="${esc(item.title)}">Remove ${esc(item.title)}</button>`
      : '';
    return `<div class="addon-conflict" role="note"><p>${esc(`${c.remove} and ${c.keep} conflict: ${c.keep} already does everything ${c.remove} does. Keep ${c.keep} and remove ${c.remove}.`)}</p>${remove}</div>`;
  }

  // Every update Modrinth has for this world, as one action (#1456).
  function pendingUpdates(world) {
    const ups = addonState.updates || {};
    return (world.items || []).filter((it) => it.updatable && ups[it.id] && ups[it.id].state === 'available');
  }

  function describeChanges(world) {
    const parts = (world.changes || []).map((c) => (c.action === 'switched to'
      ? `switched the resource pack to ${c.title}`
      : `${c.action} ${c.title}`));
    // Something newer than the launch that the panel did not do (a jar
    // dropped in by hand) still needs the restart; name it too.
    const named = new Set((world.changes || []).map((c) => c.title));
    (world.items || []).forEach((it) => {
      if (it.status === 'restart' && !named.has(it.title)) parts.push(`added ${it.title}`);
    });
    if (!parts.length) return '';
    const text = parts.join(', ');
    return text.charAt(0).toUpperCase() + text.slice(1) + '.';
  }

  function renderRestartBanner(world) {
    const box = $('#addon-restart');
    const btn = $('#addon-restart-btn');
    if (addonState.restarting) {
      box.hidden = false;
      box.className = 'addon-restart is-busy';
      $('#addon-restart-title').textContent = 'Restarting…';
      $('#addon-restart-detail').textContent = 'Players are disconnected for about 30 seconds. This list updates when the server is back.';
      btn.hidden = true;
      return;
    }
    if (world.restart_needed) {
      box.hidden = false;
      box.className = 'addon-restart';
      $('#addon-restart-title').textContent = 'Restart the server to finish';
      $('#addon-restart-detail').textContent = describeChanges(world);
      btn.hidden = false;
      btn.disabled = false;
      return;
    }
    if (!world.running && (world.items || []).length) {
      box.hidden = false;
      box.className = 'addon-restart is-info';
      $('#addon-restart-title').textContent = 'The server is stopped';
      $('#addon-restart-detail').textContent = 'Everything below turns on when it starts.';
      btn.hidden = true;
      return;
    }
    box.hidden = true;
  }

  function renderWorld(world) {
    addonState.world = world;
    if (addonState.restarting && world.running && !world.restart_needed) addonState.restarting = false;
    renderRestartBanner(world);
    const box = $('#addon-world');
    box.innerHTML = '';
    const items = world.items || [];
    const pending = pendingUpdates(world);
    if (pending.length) {
      const bar = document.createElement('div');
      bar.className = 'addon-updates';
      bar.innerHTML = `<span>${esc(pending.length === 1 ? `An update is available for ${pending[0].title}.` : `Updates are available for ${pending.length} add-ons.`)}</span>
        <button class="btn btn-primary" id="addon-update-all" type="button">Update ${pending.length}</button>
        <p class="addon-note" aria-live="polite"></p>`;
      box.appendChild(bar);
    }
    const groups = {};
    items.forEach((it) => { (groups[it.kind] = groups[it.kind] || []).push(it); });
    Object.keys(KIND_HEADINGS).forEach((kind) => {
      const rows = groups[kind];
      if (!rows) return;
      const group = document.createElement('div');
      group.className = 'addon-group';
      group.innerHTML = `<h3>${KIND_HEADINGS[kind]} <span class="muted">${rows.length}</span></h3>`;
      rows.forEach((it) => group.appendChild(worldRow(it)));
      box.appendChild(group);
    });
    $('#addon-world-empty').hidden = items.length > 0;
    bindWorldButtons(box);
  }

  function rowNote(btn, text, bad) {
    const note = btn.closest('.addon-row').querySelector('.addon-note');
    note.textContent = text;
    note.classList.toggle('bad', !!bad);
  }

  function bindWorldButtons(root) {
    root.querySelectorAll('button[data-world-remove]').forEach((b) => {
      b.addEventListener('click', async () => {
        const title = b.dataset.title;
        if (!confirm(`Remove ${title} from this world?`)) return;
        b.disabled = true;
        let resp = await api('api/addons/remove-file', {
          method: 'POST', body: JSON.stringify({ kind: b.dataset.kind, file: b.dataset.worldRemove }),
        });
        if (resp.error && /needed by/.test(resp.error) && confirm(`${resp.error}\n\nRemove it anyway?`)) {
          resp = await api('api/addons/remove-file', {
            method: 'POST', body: JSON.stringify({ kind: b.dataset.kind, file: b.dataset.worldRemove, force: true }),
          });
        }
        if (resp.ok) {
          renderWorld(resp.world);
          searchAddons(false);
        } else {
          rowNote(b, resp.error || 'That did not remove.', true);
          b.disabled = false;
        }
      });
    });
    root.querySelectorAll('button[data-world-use]').forEach((b) => {
      b.addEventListener('click', async () => {
        b.disabled = true;
        const resp = await api('api/addons/use-pack', {
          method: 'POST', body: JSON.stringify({ file: b.dataset.worldUse }),
        });
        if (resp.ok) renderWorld(resp.world);
        else { rowNote(b, resp.error || 'That did not apply.', true); b.disabled = false; }
      });
    });
    root.querySelector('#addon-update-all')?.addEventListener('click', async (ev) => {
      const b = ev.currentTarget;
      const note = b.parentElement.querySelector('.addon-note');
      const todo = pendingUpdates(addonState.world || {});
      b.disabled = true;
      const failed = [];
      let world = null;
      for (let i = 0; i < todo.length; i++) {
        b.textContent = `Updating ${i + 1} of ${todo.length}…`;
        // One at a time, through the same install (and its checks) as before.
        // eslint-disable-next-line no-await-in-loop
        const resp = await api('api/addons/install', {
          method: 'POST', body: JSON.stringify({ id: todo[i].id, kind: todo[i].kind }),
        });
        if (resp.ok) {
          // What was just installed is the newest build, so it is up to date.
          (resp.installed || []).forEach((r) => {
            if (addonState.updates && r.id) addonState.updates[r.id] = { state: 'current', version: r.version };
          });
          world = resp.world || world;
        } else {
          failed.push(`${todo[i].title}: ${resp.error || 'that did not update'}`);
        }
      }
      renderWorld(world || addonState.world || {});
      if (failed.length) {
        // The list was drawn again; the note goes under the new bar (or the
        // old one, when nothing updated and there is no new bar).
        const n = $('#addon-update-all')?.parentElement.querySelector('.addon-note') || note;
        n.textContent = failed.join(' · ');
        n.classList.add('bad');
      }
    });
  }

  $('#addon-restart-btn')?.addEventListener('click', async () => {
    const online = (addonState.info && addonState.info.players_online) || 0;
    if (!confirm(online
      ? `Restart now? ${online} player(s) online will be disconnected for about 30 seconds.`
      : 'Restart the server now? It takes about 30 seconds.')) return;
    $('#addon-restart-btn').disabled = true;
    const resp = await api('api/restart', { method: 'POST' });
    if (resp.error) {
      $('#addon-restart-detail').textContent = `The restart did not start: ${resp.error}`;
      $('#addon-restart-btn').disabled = false;
      return;
    }
    addonState.restarting = true;
    renderRestartBanner(addonState.world || {});
  });

  // --- the browser ------------------------------------------------------
  function resultStatus(item) {
    // What happened to a result, read off the world list rather than
    // guessed: "added" alone does not say whether it is working yet.
    const w = addonState.world;
    if (!w) return null;
    return (w.items || []).find((it) => it.id === item.id && it.kind === item.kind) || null;
  }

  function addonCard(item) {
    const card = document.createElement('article');
    card.className = 'addon-card';
    const meta = `${esc(item.author || '')}${item.downloads ? ` · ${fmtCount(item.downloads)} downloads` : ''}`;
    let action;
    const there = resultStatus(item);
    if (item.installed || there) {
      action = `<span class="addon-added">In this world ✓</span>${there ? `<span class="addon-status addon-status-${esc(there.status)}">${esc(there.status_text)}</span>` : ''}`;
    } else {
      const picked = addonPicked.has(pickKey(item));
      action = `<button class="btn btn-primary" data-addon-add="${esc(item.id)}" data-kind="${esc(item.kind)}">Add to world</button>
        <button class="btn${picked ? ' is-selected' : ''}" type="button" aria-pressed="${picked}" data-addon-pick="${esc(item.id)}" data-kind="${esc(item.kind)}" data-title="${esc(item.title)}">${picked ? 'Selected ✓' : 'Select'}</button>`;
      if (picked) card.classList.add('selected');
    }
    card.innerHTML = `
      <div class="addon-head">${iconHtml(item)}
        <div class="addon-title"><strong>${esc(item.title)}</strong>
          <span class="muted"><span class="addon-kind">${esc(item.kind_label || '')}</span> ${meta}</span></div></div>
      ${item.description ? `<p class="addon-desc">${esc(item.description)}</p>` : ''}
      <div class="addon-actions">${action}</div>
      <div class="addon-note" aria-live="polite"></div>`;
    return card;
  }

  function outcomeSentence(titles, world) {
    const items = (world && world.items) || [];
    const pending = titles.filter((t) => items.some((it) => it.title === t && it.status === 'restart'));
    if (pending.length) return 'Restart the server to turn it on — the button is at the top of this tab.';
    if (world && !world.running) return 'It turns on when the server starts.';
    return 'It is working now.';
  }

  async function addonInstall(btn) {
    const card = btn.closest('.addon-card');
    const note = card.querySelector('.addon-note');
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'Adding…';
    note.textContent = '';
    const resp = await api('api/addons/install', {
      method: 'POST', body: JSON.stringify({ id: btn.dataset.addonAdd, kind: btn.dataset.kind }),
    });
    if (resp.ok) {
      const titles = (resp.installed || []).map((r) => r.title);
      const names = (resp.installed || []).map((r) => `${r.title} ${r.version || ''}`.trim()).join(', ');
      if (resp.world) renderWorld(resp.world);
      note.textContent = `Added ${names}. ${outcomeSentence(titles, resp.world)}`;
      const pick = card.querySelector('button[data-addon-pick]');
      if (pick) pick.remove();
      btn.replaceWith(Object.assign(document.createElement('span'), { className: 'addon-added', textContent: 'In this world ✓' }));
      card.classList.remove('selected');
      if (addonPicked.delete(`${btn.dataset.kind}:${btn.dataset.addonAdd}`)) renderAddonTray();
    } else {
      note.textContent = resp.error || 'That did not install.';
      note.classList.add('bad');
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  function renderAddonTray() {
    const tray = $('#addon-tray');
    const n = addonPicked.size;
    tray.hidden = n === 0 && !$('#addon-tray-note').textContent;
    const names = [...addonPicked.values()].map((p) => p.title);
    $('#addon-tray-text').textContent = n
      ? `${n} selected: ${names.slice(0, 4).join(', ')}${n > 4 ? ` and ${n - 4} more` : ''}`
      : '';
    $('#addon-tray-add').hidden = n === 0;
    $('#addon-tray-clear').hidden = n === 0;
    $('#addon-tray-add').textContent = n > 1 ? `Add all ${n} to world` : 'Add to world';
  }

  function addonPick(btn) {
    const item = { id: btn.dataset.addonPick, kind: btn.dataset.kind, title: btn.dataset.title };
    const key = pickKey(item);
    const card = btn.closest('.addon-card');
    if (addonPicked.has(key)) addonPicked.delete(key); else addonPicked.set(key, item);
    const on = addonPicked.has(key);
    btn.classList.toggle('is-selected', on);
    btn.setAttribute('aria-pressed', String(on));
    btn.textContent = on ? 'Selected ✓' : 'Select';
    card.classList.toggle('selected', on);
    $('#addon-tray-note').textContent = '';
    $('#addon-tray-note').classList.remove('bad');
    renderAddonTray();
  }

  async function addonInstallPicked() {
    const btn = $('#addon-tray-add');
    const note = $('#addon-tray-note');
    const items = [...addonPicked.values()];
    if (!items.length) return;
    btn.disabled = true;
    $('#addon-tray-clear').disabled = true;
    btn.textContent = `Adding ${items.length}…`;
    note.textContent = '';
    note.classList.remove('bad');
    const resp = await api('api/addons/install', {
      method: 'POST', body: JSON.stringify({ items: items.map(({ id, kind }) => ({ id, kind })) }),
    });
    btn.disabled = false;
    $('#addon-tray-clear').disabled = false;
    if (!resp.results) {
      note.textContent = resp.error || 'Those did not install.';
      note.classList.add('bad');
      renderAddonTray();
      return;
    }
    const added = [];
    const failed = [];
    resp.results.forEach((r) => {
      const picked = addonPicked.get(`${r.kind}:${r.id}`);
      const title = picked ? picked.title : r.id;
      if (r.ok) {
        added.push(title);
        addonPicked.delete(`${r.kind}:${r.id}`);
      } else {
        failed.push(`${title}: ${r.error}`);
      }
    });
    if (resp.world) renderWorld(resp.world);
    const parts = [];
    if (added.length) parts.push(`Added ${added.join(', ')}. ${outcomeSentence(added, resp.world)}`);
    if (failed.length) parts.push(`Not added — ${failed.join(' ')}`);
    note.textContent = parts.join(' ');
    note.classList.toggle('bad', failed.length > 0 && !added.length);
    renderAddonTray();
    searchAddons(false);
  }

  function bindAddonButtons(root) {
    root.querySelectorAll('button[data-addon-pick]').forEach((b) => {
      b.addEventListener('click', () => addonPick(b));
    });
    root.querySelectorAll('button[data-addon-add]').forEach((b) => {
      b.addEventListener('click', () => addonInstall(b));
    });
  }

  function renderAddonKinds() {
    const bar = $('#addon-kinds');
    bar.innerHTML = '';
    const kinds = [{ kind: 'all', label: 'Everything', reach: '' }, ...((addonState.info && addonState.info.kinds) || [])];
    kinds.forEach((k) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `chip${k.kind === addonState.kind ? ' active' : ''}`;
      b.textContent = k.label;
      b.setAttribute('aria-pressed', k.kind === addonState.kind ? 'true' : 'false');
      b.addEventListener('click', () => { addonState.kind = k.kind; addonState.offset = 0; renderAddonKinds(); searchAddons(false); });
      bar.appendChild(b);
    });
    const k = kinds.find((x) => x.kind === addonState.kind);
    $('#addon-reach').textContent = k ? k.reach : '';
  }

  async function loadAddonsInstalled() {
    const info = await api('api/addons');
    if (info.error) return;
    addonState.info = info;
    if (info.world) renderWorld(info.world);
  }

  async function searchAddons(append) {
    const box = $('#addon-results');
    if (!append) { addonState.offset = 0; box.innerHTML = '<p class="muted">Searching…</p>'; }
    const q = encodeURIComponent(addonState.q);
    const data = await api(`api/addons/search?kind=${encodeURIComponent(addonState.kind)}&q=${q}&offset=${addonState.offset}`);
    if (!append) box.innerHTML = '';
    if (data.error) {
      box.innerHTML = `<p class="muted bad">${esc(data.error)}</p>`;
      $('#addon-more').hidden = true;
      return;
    }
    (data.hits || []).forEach((h) => box.appendChild(addonCard(h)));
    if (!box.children.length) box.innerHTML = '<p class="muted">Nothing matches for this server’s version.</p>';
    bindAddonButtons(box);
    if (data.kind === 'all') {
      addonState.offset = data.next_offset;
      $('#addon-more').hidden = !data.has_more;
    } else {
      addonState.offset = (data.offset || 0) + (data.hits || []).length;
      $('#addon-more').hidden = addonState.offset >= (data.total || 0);
    }
  }

  // One Modrinth question per browser-added add-on, asked when the pane opens.
  async function loadAddonUpdates() {
    addonState.updatesError = '';
    let data;
    try { data = await api('api/addons/updates'); } catch { data = { error: 'offline' }; }
    if (data && data.updates) addonState.updates = data.updates;
    else addonState.updatesError = (data && data.error) || 'unknown';
    if (addonState.world) renderWorld(addonState.world);
  }

  async function loadAddons() {
    addonState.updates = null;
    await loadAddonsInstalled();
    loadAddonUpdates();
    if (!addonState.info) return;
    const kinds = addonState.info.kinds || [];
    if (addonState.kind !== 'all' && !kinds.find((k) => k.kind === addonState.kind)) addonState.kind = 'all';
    const v = addonState.info.game_version;
    $('#addons-lede').textContent = `Everything here runs on the server, so every player gets it — iPads, phones and consoles through Geyser included. This is the active world on ${addonState.info.server_type}${v ? ` ${v}` : ''}.`;
    renderAddonKinds();
    searchAddons(false);
    loadSoftware(false);
  }

  // Keep the list honest while the tab is open: a restart finishing, or a
  // jar dropped in by hand, changes what it should say.
  setInterval(() => {
    const panel = $('#tab-addons');
    if (panel && panel.classList.contains('active') && !document.hidden) loadAddonsInstalled();
  }, 5000);

  $('#f-addon-search')?.addEventListener('submit', (e) => {
    e.preventDefault();
    addonState.q = $('#addon-q').value.trim();
    searchAddons(false);
  });
  $('#addon-more')?.addEventListener('click', () => searchAddons(true));
  $('#addon-tray-add')?.addEventListener('click', addonInstallPicked);
  $('#addon-tray-clear')?.addEventListener('click', () => {
    addonPicked.clear();
    $('#addon-tray-note').textContent = '';
    document.querySelectorAll('#addon-results button[data-addon-pick]').forEach((b) => {
      b.classList.remove('is-selected');
      b.setAttribute('aria-pressed', 'false');
      b.textContent = 'Select';
      b.closest('.addon-card').classList.remove('selected');
    });
    renderAddonTray();
  });

  // --- server software --------------------------------------------------
  // The server itself and the crossplay plugins under it. They update by
  // restarting the add-on (that is when they are downloaded); moving a
  // world to a newer Minecraft is a separate, one-way press with a backup.
  const fmtDate = (t) => (t ? new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '');
  const typeName = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Server');

  function renderSoftware(sw) {
    const rows = [];
    const server = [`Minecraft ${sw.version || '?'}`];
    if (sw.build) server.push(`build ${sw.build}`);
    let status = '<span class="addon-status addon-status-active">Up to date</span>';
    let action = '';
    if (sw.upgrade_pending) {
      status = `<span class="addon-status addon-status-restart">Upgrading to ${esc(sw.upgrade_pending)} on the next add-on start</span>`;
    } else if (sw.upgrade_available) {
      status = `<span class="addon-status addon-status-restart">Minecraft ${esc(sw.newest_version)} is out</span>`;
      action = `<button class="btn btn-primary" id="software-upgrade" data-version="${esc(sw.newest_version)}">Upgrade this world to ${esc(sw.newest_version)}</button>`;
    } else if (sw.build_update_available) {
      // Says what to do, not only what exists (#1294).
      status = `<span class="addon-status addon-status-restart">${esc(typeName(sw.server_type))} build ${esc(sw.newest_build)} is ready — press Update everything now; the add-on restarts</span>`;
    } else if (!sw.checked) {
      status = `<span class="addon-status addon-status-next_start">${esc(sw.check_error || 'Not checked for this server type')}</span>`;
    }
    rows.push(`<div class="software-row">
      <div class="addon-row-main"><strong>${esc(typeName(sw.server_type))}</strong>
        <span class="muted">${esc(server.join(' · '))}${sw.version_option && sw.version_option.toUpperCase() !== 'LATEST' ? ` · pinned to ${esc(sw.version_option)} in Configuration` : ''}</span></div>
      ${status}
      ${action ? `<div class="addon-row-actions">${action}</div>` : ''}
    </div>`);
    (sw.components || []).forEach((c) => {
      rows.push(`<div class="software-row">
        <div class="addon-row-main"><strong>${esc(c.title)}</strong>
          <span class="muted">${esc([c.version, c.note].filter(Boolean).join(' · '))}</span></div>
        <span class="muted software-when">Fetched ${esc(fmtDate(c.updated_at))}</span>
      </div>`);
    });
    $('#software-rows').innerHTML = rows.join('');
    $('#software-update').classList.toggle('btn-primary', !!sw.build_update_available && !sw.upgrade_pending);
    $('#software-foot').textContent = sw.bedrock_support
      ? 'Geyser, Floodgate and ViaVersion download their newest build every time the add-on starts. "Update everything now" restarts the add-on to do that now — players are disconnected for about a minute.'
      : 'Bedrock support is off in Configuration. "Update everything now" restarts the add-on to fetch the newest server build.';
    $('#software-upgrade')?.addEventListener('click', (e) => softwareUpdate(e.currentTarget.dataset.version));
  }

  async function loadSoftware(force) {
    const sw = await api(`api/server/software${force ? '?refresh=1' : ''}`);
    if (sw.error) { $('#software-rows').innerHTML = `<p class="muted bad">${esc(sw.error)}</p>`; return; }
    renderSoftware(sw);
    showHeaderUpdate(sw);
  }

  async function softwareUpdate(version) {
    const note = $('#software-note');
    const ask = version
      ? `Upgrade this world to Minecraft ${version}?\n\nA backup is taken first. Worlds cannot be moved back to an older version, and a plugin made only for the old version may stop loading. Players are disconnected for a minute or two.`
      : 'Restart the add-on now to download the newest server build, Geyser, Floodgate and ViaVersion? Players are disconnected for about a minute.';
    if (!confirm(ask)) return;
    note.classList.remove('bad');
    note.textContent = version ? 'Taking a backup…' : 'Restarting the add-on…';
    $$('#software button').forEach((b) => { b.disabled = true; });
    const resp = await api('api/server/software/update', {
      method: 'POST', body: JSON.stringify(version ? { upgrade_to: version } : {}),
    });
    if (resp.ok) {
      note.textContent = `${(resp.notes || []).join(' ')} The add-on is restarting — this panel comes back in a minute or two.`.trim();
    } else {
      note.textContent = resp.error || 'That did not start.';
      note.classList.add('bad');
      $$('#software button').forEach((b) => { b.disabled = false; });
    }
  }

  $('#software-check')?.addEventListener('click', () => { $('#software-rows').innerHTML = '<p class="muted">Checking…</p>'; loadSoftware(true); });
  $('#software-update')?.addEventListener('click', () => softwareUpdate(''));

  // --- your own file or link -------------------------------------------
  $('#f-plugin-install')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('#plugin-url').value.trim();
    const name = $('#plugin-name').value.trim();
    $('#plugin-reply').textContent = 'Downloading…';
    const data = await api('api/plugins', { method: 'POST', body: JSON.stringify({ url, name }) });
    $('#plugin-reply').textContent = data.ok
      ? 'Added. It is in the list above — restart the server to turn it on.'
      : (data.output || data.error || 'That did not install.');
    if (data.ok) { $('#plugin-url').value = ''; $('#plugin-name').value = ''; loadAddonsInstalled(); }
  });

  $('#f-pack-upload')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('#pack-file').files[0];
    const name = $('#pack-name').value.trim();
    if (!file) return;
    const reply = $('#pack-upload-reply');
    reply.textContent = `Uploading ${file.name} (${fmtSize(file.size)})…`;
    const fd = new FormData();
    if (name) fd.append('name', name);
    fd.append('file', file);
    const resp = await fetch('api/resource-packs', { method: 'POST', body: fd, credentials: 'same-origin' });
    let out; try { out = await resp.json(); } catch { out = { error: await resp.text() }; }
    if (out.ok) {
      reply.textContent = `Uploaded ${out.name}. It is in the list above — press Use in this world to offer it to players.`;
      $('#pack-file').value = '';
      $('#pack-name').value = '';
      loadAddonsInstalled();
    } else {
      reply.textContent = `Upload failed: ${out.error || resp.status}`;
    }
  });
})();
