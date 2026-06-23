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
  // Tabs
  // ------------------------------------------------------------------
  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      $$('.tab').forEach((t) => t.classList.remove('active'));
      $$('.tab-panel').forEach((p) => p.classList.remove('active'));
      tab.classList.add('active');
      $(`#tab-${tab.dataset.tab}`).classList.add('active');
      if (tab.dataset.tab === 'properties') loadProperties();
      if (tab.dataset.tab === 'plugins')    loadPlugins();
      if (tab.dataset.tab === 'backups')    loadBackups();
      if (tab.dataset.tab === 'worlds')     { loadWorlds(); loadCuratedWorlds(); }
      if (tab.dataset.tab === 'resource-packs') loadPacks();
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

      $('#m-version').textContent = stats.version || server_meta.version || '—';
      $('#m-type').textContent = state.server_type || '—';
      $('#m-uptime').textContent = stats.uptime_seconds
        ? fmtDuration(stats.uptime_seconds) : '—';
      $('#m-memory').textContent = state.memory_mb ? `${state.memory_mb} MB` : '—';
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
      $('#m-online').textContent = stats.online ?? 0;
      $('#m-max').textContent = stats.max_players ?? state.max_players ?? 0;

      const ml = $('#m-players');
      ml.innerHTML = '';
      (stats.players || []).forEach((name) => {
        const li = document.createElement('li');
        li.textContent = name;
        ml.appendChild(li);
      });

      $('#brand-subtitle').textContent =
        `${state.server_type || 'paper'} ${stats.version || ''} · ${running ? 'online' : 'offline'}`;
      $('#last-refresh').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      console.warn('refresh failed', err);
    }
  }

  setInterval(refreshStatus, 5000);
  refreshStatus();

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

  $('#btn-update').addEventListener('click', async () => {
    if (!confirmAction('Download the latest server jar for the configured type/version? Requires a restart to take effect.')) return;
    const data = await api('api/server/update', { method: 'POST' });
    alert(data.ok ? 'Server jar updated. Restart to load.' : `Update failed:\n${data.output || data.error}`);
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
  async function refreshPlayersTab() {
    const data = await api('api/players');
    const tbody = $('#players-table tbody');
    tbody.innerHTML = '';
    (data.players || []).forEach((name) => {
      const tr = document.createElement('tr');
      const actions = ['op', 'kick', 'ban', 'whitelist_add']
        .map((a) => `<button class="btn btn-ghost" data-name="${esc(name)}" data-action="${a}">${a}</button>`)
        .join('');
      tr.innerHTML = `<td>${esc(name)}</td><td class="actions">${actions}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button').forEach((b) => {
      b.addEventListener('click', () => runPlayerAction(b.dataset.name, b.dataset.action));
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
    sortedEntries.forEach(([k, v]) => {
      const isEditable = editable.has(k);
      const tr = document.createElement('tr');
      // Flag keys that are baked into the world at GENERATION time —
      // editing them on an existing world has NO effect (Minecraft only
      // reads them once when it generates the world). Without this badge
      // users edit level-seed expecting their world to change.
      const wgoBadge = worldGenOnly.has(k)
        ? `<span class="wgo-badge" title="World-generation only — has no effect on this already-generated world. To use this, create a new world from the Worlds tab.">world-gen only</span>`
        : '';
      const valCell = isEditable
        ? renderPropEditor(k, v, types, enums, ranges)
        : `<code>${esc(v)}</code>`;
      const actionCell = isEditable
        ? `<button class="btn btn-primary" data-save-key="${esc(k)}">Save</button>`
        : '<span class="muted">config.yaml</span>';
      tr.innerHTML = `<td><code>${esc(k)}</code>${wgoBadge}</td><td>${valCell}</td><td>${actionCell}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-save-key]').forEach((b) => {
      b.addEventListener('click', async () => {
        const key = b.dataset.saveKey;
        // input OR select — both expose .value
        const input = tbody.querySelector(`[data-key="${key}"]`);
        if (!input) return;
        b.disabled = true;
        const original = b.textContent;
        b.textContent = 'Saving…';
        const resp = await api('api/properties', {
          method: 'POST',
          body: JSON.stringify({ key, value: input.value }),
        });
        b.disabled = false;
        if (resp.error) {
          alert(resp.error);
          b.textContent = original;
        } else {
          // Saved to this world's server.properties (the source of truth).
          // Some keys apply live via RCON; the rest take effect on restart.
          b.textContent = resp.live ? 'Saved ✓' : 'Saved — restart to apply';
          setTimeout(() => { b.textContent = original; }, 2500);
        }
      });
    });
  }

  // ------------------------------------------------------------------
  // Plugins tab
  // ------------------------------------------------------------------
  async function loadPlugins() {
    const data = await api('api/plugins');
    const tbody = $('#plugins-table tbody');
    tbody.innerHTML = '';
    (data.plugins || []).forEach((p) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code>${esc(p.name)}</code></td>
        <td>${fmtSize(p.size)}</td>
        <td>${new Date(p.mtime * 1000).toLocaleString()}</td>
        <td><button class="btn btn-danger" data-plugin-del="${esc(p.name)}">Delete</button></td>
      `;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-plugin-del]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.pluginDel;
        if (!confirm(`Delete plugin ${name}? Requires restart to unload.`)) return;
        await api(`api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadPlugins();
      });
    });
  }

  $('#f-plugin-install').addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('#plugin-url').value.trim();
    const name = $('#plugin-name').value.trim();
    const data = await api('api/plugins', {
      method: 'POST', body: JSON.stringify({ url, name }),
    });
    $('#plugin-reply').textContent = data.output || data.error || '';
    if (data.ok) loadPlugins();
  });

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
        ? '<span style="color: var(--accent); font-weight: 600;">● active</span>'
        : '—';
      // Surface each world's per-world gameplay settings so the user can see
      // at a glance that switching loads THAT world's mode — not whatever
      // they last edited on a different world. This is the "settings don't
      // appear to move with me" UX hint.
      const s = w.settings || {};
      const settingsCell = s.gamemode || s.difficulty || s['level-type']
        ? `<span class="world-settings">` +
          (s.gamemode ? `<code>${esc(s.gamemode)}</code>` : '') +
          (s.difficulty ? ` · ${esc(s.difficulty)}` : '') +
          (s['level-type'] ? ` · ${esc(String(s['level-type']).replace(/^minecraft:/, ''))}` : '') +
          (s['white-list'] === 'true' ? ' · <span class="muted">whitelist</span>' : '') +
          (s['online-mode'] === 'false' ? ' · <span class="muted">offline</span>' : '') +
          `</span>`
        : '<span class="muted">(no settings yet)</span>';
      // Export (download .zip) is available for every world — including the
      // active one. Switching/deleting is only meaningful for non-active.
      const exportBtn = `<a class="btn btn-ghost" href="api/worlds/${encodeURIComponent(w.name)}/export" download title="Download this world's save as a .zip for sharing or off-host backup">Download</a>`;
      const actions = w.active
        ? exportBtn
        : `
          <button class="btn btn-primary" data-switch="${esc(w.name)}">Switch</button>
          ${exportBtn}
          <button class="btn btn-danger" data-delete="${esc(w.name)}">Delete</button>
        `;
      const curatedBadge = w.curated
        ? ` <span class="curated-badge" title="Installed from the Featured Worlds catalog">${esc(w.curated.name || w.curated.id)}${w.curated.version ? ' v' + esc(w.curated.version) : ''}</span>`
        : '';
      tr.innerHTML = `
        <td><code>${esc(w.name)}</code>${curatedBadge}</td>
        <td>${fmtSize(w.size_bytes)}</td>
        <td>${settingsCell}</td>
        <td>${activeBadge}</td>
        <td class="actions">${actions}</td>
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

    const renderGit = () => {
      if (!git.length) return '<p class="muted">No git snapshots yet.</p>';
      const rows = git.map((c) => `
        <tr>
          <td><code>${esc(c.sha.substring(0, 8))}</code></td>
          <td>${new Date(c.ts * 1000).toLocaleString()}</td>
          <td>${esc(c.subject)}</td>
          <td><button class="btn btn-warn" data-restore="${esc(c.sha)}">Restore</button></td>
        </tr>
      `).join('');
      return `<table class="table">
        <thead><tr><th>SHA</th><th>When</th><th>Subject</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    };

    const renderArchives = () => {
      if (!arc.length) return '<p class="muted">No archive backups yet.</p>';
      const rows = arc.map((a) => `
        <tr>
          <td><code>${esc(a.name)}</code></td>
          <td>${fmtSize(a.size)}</td>
          <td>${new Date(a.ts * 1000).toLocaleString()}</td>
          <td><button class="btn btn-warn" data-restore="${esc(a.name)}">Restore</button></td>
        </tr>
      `).join('');
      return `<table class="table">
        <thead><tr><th>File</th><th>Size</th><th>When</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    };

    host.innerHTML = `
      <h3>Git snapshots</h3>${renderGit()}
      <h3>Archives</h3>${renderArchives()}
    `;
    host.querySelectorAll('button[data-restore]').forEach((b) => {
      b.addEventListener('click', async () => {
        const ref = b.dataset.restore;
        if (!confirm(`Restore worlds from ${ref}? The server will be stopped; run.sh will start it back up.`)) return;
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
  // Resource Packs tab
  // ------------------------------------------------------------------
  async function loadPacks() {
    const data = await api('api/resource-packs');
    const tbody = $('#packs-table tbody');
    tbody.innerHTML = '';
    (data.packs || []).forEach((p) => {
      const url = `${location.protocol}//${location.hostname}:8099/pack/${encodeURIComponent(p.name)}`;
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code>${esc(p.name)}</code><br /><span class="muted" style="font-size: 0.8em;">${esc(url)}</span></td>
        <td>${fmtSize(p.size)}</td>
        <td><code style="font-size: 0.75em;">${esc(p.sha1)}</code></td>
        <td>${new Date(p.mtime * 1000).toLocaleString()}</td>
        <td>
          <button class="btn btn-primary" data-pack-apply="${esc(p.name)}">Apply to active world</button>
          <button class="btn btn-danger" data-pack-del="${esc(p.name)}">Delete</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-pack-apply]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.packApply;
        if (!confirm(`Apply ${name} to the active world's server.properties? The server needs a restart for clients to pick up the new pack.`)) return;
        const resp = await api(`api/resource-packs/${encodeURIComponent(name)}/apply`, { method: 'POST' });
        alert(resp.ok ? `Done.\nURL: ${resp.url}\nSHA-1: ${resp.sha1}` : `Failed: ${resp.error}`);
      });
    });
    tbody.querySelectorAll('button[data-pack-del]').forEach((b) => {
      b.addEventListener('click', async () => {
        const name = b.dataset.packDel;
        if (!confirm(`Delete resource pack ${name}? Worlds using it will fall back to no pack.`)) return;
        await api(`api/resource-packs/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadPacks();
      });
    });
  }

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
      reply.textContent = `Uploaded ${out.name} — SHA-1: ${out.sha1}`;
      $('#pack-file').value = '';
      $('#pack-name').value = '';
      loadPacks();
    } else {
      reply.textContent = `Upload failed: ${out.error || resp.status}`;
    }
  });
})();
