/* BRUH Minecraft Server — ingress panel frontend */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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
      $('#m-tps1').textContent = stats.tps_1m ?? '—';
      $('#m-tps5').textContent = stats.tps_5m ?? '—';
      $('#m-tps15').textContent = stats.tps_15m ?? '—';
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
        .map((a) => `<button class="btn btn-ghost" data-name="${name}" data-action="${a}">${a}</button>`)
        .join('');
      tr.innerHTML = `<td>${name}</td><td class="actions">${actions}</td>`;
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
        ? `<input type="text" value="${String(v).replace(/"/g, '&quot;')}" data-key="${k}" />`
        : `<code>${v}</code>`;
      const actionCell = isEditable
        ? `<button class="btn btn-primary" data-save-key="${k}">Save</button>`
        : '<span class="muted">config.yaml</span>';
      tr.innerHTML = `<td><code>${k}</code></td><td>${valCell}</td><td>${actionCell}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-save-key]').forEach((b) => {
      b.addEventListener('click', async () => {
        const key = b.dataset.saveKey;
        const input = tbody.querySelector(`input[data-key="${key}"]`);
        if (!input) return;
        const resp = await api('api/properties', {
          method: 'POST',
          body: JSON.stringify({ key, value: input.value }),
        });
        if (resp.error) alert(resp.error);
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
        <td><code>${p.name}</code></td>
        <td>${fmtSize(p.size)}</td>
        <td>${new Date(p.mtime * 1000).toLocaleString()}</td>
        <td><button class="btn btn-danger" data-plugin-del="${p.name}">Delete</button></td>
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
  async function loadBackups() {
    const data = await api('api/backups');
    const host = $('#backups-panel');
    const git = data.git || [];
    const arc = data.archives || [];

    const renderGit = () => {
      if (!git.length) return '<p class="muted">No git snapshots yet.</p>';
      const rows = git.map((c) => `
        <tr>
          <td><code>${c.sha.substring(0, 8)}</code></td>
          <td>${new Date(c.ts * 1000).toLocaleString()}</td>
          <td>${c.subject}</td>
          <td><button class="btn btn-warn" data-restore="${c.sha}">Restore</button></td>
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
          <td><code>${a.name}</code></td>
          <td>${fmtSize(a.size)}</td>
          <td>${new Date(a.ts * 1000).toLocaleString()}</td>
          <td><button class="btn btn-warn" data-restore="${a.name}">Restore</button></td>
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
