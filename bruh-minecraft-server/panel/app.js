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

  // ------------------------------------------------------------------
  // First-run setup wizard (1.11.0 — multi-step)
  // ------------------------------------------------------------------
  // The wizard is a stateful 7-step walkthrough. Each step is a
  // `<section class="setup-step" data-step="N">` element; we toggle the
  // `hidden` attribute to swap between them. Step 5 fetches a hardware
  // recommendation, step 6 hides the plugin list for non-Bukkit server
  // types, and step 7 renders a review summary built from the same body
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

      // Step-entry hooks.
      if (current === 5 && !recommendation) loadRecommendation();
      if (current === 6) updatePluginsVisibility();
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
      if (current === 5 && radio('setup-perf') === 'manual') {
        const mem = Number($('#setup-memory').value);
        if (!Number.isInteger(mem) || mem < 512 || mem > 65536) {
          return 'Memory must be a whole number between 512 and 65536.';
        }
      }
      return null;
    }

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
        active_world: $('#setup-world-name').value.trim(),
        gamemode: radio('setup-gamemode', 'survival'),
        difficulty: radio('setup-difficulty', 'normal'),
        level_type: radio('setup-level-type', 'minecraft:normal'),
        level_seed: $('#setup-seed').value.trim(),
        pvp: $('#setup-pvp').checked,
        hardcore: $('#setup-hardcore').checked,
      };
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
        ['World name', b.active_world],
        ['Gamemode', b.gamemode + (b.hardcore ? ' (hardcore)' : '')],
        ['Difficulty', b.difficulty],
        ['Terrain', b.level_type.replace(/^minecraft:/, '')],
        ['Seed', b.level_seed || '(random)'],
        ['PVP', b.pvp ? 'enabled' : 'disabled'],
      ];
      if (b.memory_mb) {
        rows.push(['Memory', `${b.memory_mb} MB`]);
        rows.push(['View / sim distance', `${b.view_distance} / ${b.simulation_distance}`]);
      }
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
