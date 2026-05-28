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
      if (tab.dataset.tab === 'worlds')     loadWorlds();
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
  $('#btn-tune').addEventListener('click', async () => {
    const r = await api('api/recommend');
    if (r._raw || !r.memory_mb) { alert('Could not read recommendation:\n' + (r._raw || 'unknown')); return; }
    const msg =
      'Detected:\n' +
      `  host RAM: ${r.host_total_mb} MB\n` +
      `  CPUs: ${r.cpu_count}\n\n` +
      'Recommended:\n' +
      `  memory_mb (global): ${r.memory_mb}\n` +
      `  view-distance (active world): ${r.view_distance}\n` +
      `  simulation-distance (active world): ${r.simulation_distance}\n\n` +
      'Why:\n' +
      `  • ${r.rationale.memory}\n` +
      `  • ${r.rationale.distances}\n\n` +
      'Apply now? (Takes effect on the next restart.)';
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
  async function loadProperties() {
    const data = await api('api/properties');
    const tbody = $('#props-table tbody');
    tbody.innerHTML = '';
    const editable = new Set(data.editable);
    Object.entries(data.properties).sort().forEach(([k, v]) => {
      const isEditable = editable.has(k);
      const tr = document.createElement('tr');
      const valCell = isEditable
        ? `<input type="text" value="${esc(v)}" data-key="${esc(k)}" />`
        : `<code>${esc(v)}</code>`;
      const actionCell = isEditable
        ? `<button class="btn btn-primary" data-save-key="${esc(k)}">Save</button>`
        : '<span class="muted">config.yaml</span>';
      tr.innerHTML = `<td><code>${esc(k)}</code></td><td>${valCell}</td><td>${actionCell}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-save-key]').forEach((b) => {
      b.addEventListener('click', async () => {
        const key = b.dataset.saveKey;
        const input = tbody.querySelector(`input[data-key="${key}"]`);
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
      const actions = w.active
        ? '<span class="muted">—</span>'
        : `
          <button class="btn btn-primary" data-switch="${esc(w.name)}">Switch</button>
          <button class="btn btn-danger" data-delete="${esc(w.name)}">Delete</button>
        `;
      tr.innerHTML = `
        <td><code>${esc(w.name)}</code></td>
        <td>${fmtSize(w.size_bytes)}</td>
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

  document.querySelector('#f-world-create').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.querySelector('#world-name').value.trim();
    const seed = document.querySelector('#world-seed').value.trim();
    const resp = await api('api/worlds', {
      method: 'POST',
      body: JSON.stringify({ name, seed }),
    });
    document.querySelector('#world-reply').textContent =
      resp.ok ? `Created "${name}". Switch to it and restart to boot into it.` : (resp.error || 'failed');
    if (resp.ok) {
      document.querySelector('#world-name').value = '';
      document.querySelector('#world-seed').value = '';
      loadWorlds();
    }
  });

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
})();
