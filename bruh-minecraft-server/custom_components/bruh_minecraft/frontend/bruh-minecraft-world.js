/* BRUH Minecraft — the world, as a Morph card.
 *
 *   custom:morph-minecraft-world
 *
 * The owner (#573): "make this card as great as possible. I don't care
 * about TPS or latency. I want to know what's going on in the world. I
 * don't need buttons. I want to know what [the companion] is building as
 * part of the sentience engine." So this card says, and does nothing else:
 *
 *   - the world's day, time of day and weather;
 *   - who is on and where (dimension, "near <place>" or rounded
 *     coordinates), their game mode and health; when nobody is, who was
 *     on last;
 *   - what is being built now (title, part of the build, progress)
 *     and what it finished lately, with the picture drawn from the world;
 *   - the feed: joins, leaves, deaths, advancements, chat;
 *   - when the world was last saved and backed up.
 *
 * Everything is read off the bruh_minecraft integration's sensors (panel/
 * mcworld.py → world.json → worldview.py): `world_time`, `world_day`,
 * `world_weather`, `players_online` (its `details`), `world_feed`,
 * `building`, `last_save`, `last_backup`. No TPS, no latency, no
 * buttons, nothing floats, no hover text: Morph's rules (docs/design/
 * morph-vision.md §15). Plain custom element, no imports.
 *
 * run.sh copies this file to /config/morph/cards/bruh-minecraft-world.js
 * when Morph is there. Options: `title` (a heading over the card) and
 * `prefix` (the sensors' entity id prefix, if they were renamed;
 * default `sensor.bruh_minecraft_server_`).
 */

const CARD_VERSION = '1.1.0';

const KEYS = ['world_time', 'world_day', 'world_weather', 'players_online', 'world_feed',
  'building', 'last_save', 'last_backup'];
const PHASE = { day: 'Day', sunset: 'Sunset', night: 'Night', sunrise: 'Sunrise' };
const WEATHER = { clear: 'Clear', rain: 'Raining', thunder: 'Thunderstorm' };
const KIND_MARK = { join: '→', leave: '←', death: '✝', advancement: '★', chat: '“', build: '▣',
  server: '•', save: '•' };

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function ago(iso, now = Date.now()) {
  if (!iso) return '';
  const t = typeof iso === 'number' ? iso * 1000 : Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

const usable = (s) => s && !['unknown', 'unavailable', ''].includes(s.state);

const css = `
  :host { display: block; color: var(--text, #14202b); font-family: inherit; }
  .wrap { padding: 4px 2px; display: grid; gap: 14px; min-width: 0; }
  .title { font-family: 'Bricolage Grotesque', sans-serif; font-size: 22px; font-weight: 400; }
  .sky { display: flex; align-items: baseline; gap: 6px 12px; flex-wrap: wrap; }
  .sky .big { font-family: 'Bricolage Grotesque', sans-serif; font-size: 28px; font-weight: 300;
    font-variant-numeric: tabular-nums; line-height: 1.1; }
  .sky .what { font-size: 15px; color: var(--muted, #5b6b79); }
  .sky .phase { color: var(--text, #14202b); }
  .lab { font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
    color: var(--muted, #5b6b79); margin-bottom: 6px; }
  .rows { display: grid; gap: 8px; }
  .who { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; align-items: baseline; }
  .who .name { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
  .who .where { grid-column: 1; font-size: 13px; color: var(--muted, #5b6b79); overflow-wrap: anywhere; }
  .who .life { font-size: 13px; color: var(--muted, #5b6b79); font-variant-numeric: tabular-nums;
    white-space: nowrap; }
  .who .life.low { color: var(--rose, #c33); }
  .quiet { font-size: 13px; color: var(--muted, #5b6b79); }
  .job .jt { font-size: 15px; overflow-wrap: anywhere; }
  .job .jp { font-size: 13px; color: var(--muted, #5b6b79); }
  .bar { height: 4px; border-radius: 2px; background: var(--sunk, #eee); overflow: hidden; margin-top: 6px; }
  .bar i { display: block; height: 100%; background: var(--amber, #d89a2b); }
  .shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 10px; }
  .shot { display: grid; gap: 4px; min-width: 0; }
  .shot img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px;
    background: var(--sunk, #eee); image-rendering: pixelated; display: block; }
  .shot .st { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .shot .sw { font-size: 11px; color: var(--muted, #5b6b79); }
  .shot.text { align-content: start; }
  .feed { display: grid; gap: 6px; }
  .ev { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 8px; font-size: 13px;
    align-items: baseline; }
  .ev .m { color: var(--muted, #5b6b79); text-align: center; }
  .ev .t { overflow-wrap: anywhere; }
  .ev .w { color: var(--muted, #5b6b79); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .ev.death .m { color: var(--rose, #c33); }
  .ev.advancement .m, .ev.build .m { color: var(--violet, #7a5cd6); }
  .foot { font-size: 13px; color: var(--muted, #5b6b79); }
`;

class MorphMinecraftWorld extends HTMLElement {
  setConfig(config) {
    this._config = { prefix: 'sensor.bruh_minecraft_server_', feed: 8, ...(config || {}) };
    this._key = '';
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
  }

  static getStubConfig() { return {}; }

  getCardSize() { return 6; }

  set hass(hass) {
    this._hass = hass;
    const s = this._states();
    const key = JSON.stringify(KEYS.map((k) => s[k] && [s[k].state, s[k].attributes]));
    // Redraw at least once a minute too, so "5 min ago" stays true.
    const minute = Math.floor(Date.now() / 60000);
    if (key === this._key && minute === this._minute) return;
    this._key = key;
    this._minute = minute;
    this._render(s);
  }

  // The integration's sensors, found by their entity id; with the entity
  // registry at hand, only ones the bruh_minecraft platform made.
  _states() {
    const hass = this._hass;
    const out = {};
    if (!hass) return out;
    const reg = hass.entities || {};
    const ids = Object.keys(hass.states).filter((id) => id.startsWith('sensor.'));
    for (const k of KEYS) {
      let id = `${this._config.prefix}${k}`;
      if (!hass.states[id]) {
        id = ids.find((e) => e.endsWith(`_${k}`) && (!reg[e] || !reg[e].platform || reg[e].platform === 'bruh_minecraft'));
      }
      if (id && hass.states[id]) out[k] = hass.states[id];
    }
    return out;
  }

  _skyHtml(s) {
    const t = s.world_time;
    const day = s.world_day;
    const w = s.world_weather;
    if (!usable(t)) {
      return `<div class="sky"><span class="what">The world is not running right now.</span></div>`;
    }
    const clock = t.attributes.clock || '';
    const bits = [`<span class="phase">${esc(PHASE[t.state] || t.state)}</span>`];
    if (usable(day)) bits.unshift(`Day ${esc(day.state)}`);
    if (usable(w)) bits.push(esc(WEATHER[w.state] || w.state));
    return `<div class="sky"><span class="big">${esc(clock)}</span><span class="what">${bits.join(' · ')}</span></div>`;
  }

  _whoHtml(s) {
    const p = s.players_online;
    const details = (p && p.attributes && p.attributes.details) || [];
    const names = (p && p.attributes && p.attributes.players) || [];
    let rows;
    if (details.length) {
      rows = details.map((d) => {
        const hp = typeof d.health === 'number' ? d.health : null;
        const life = [d.gamemode && d.gamemode !== 'survival' ? d.gamemode : '',
          hp != null && (!d.gamemode || ['survival', 'adventure'].includes(d.gamemode)) ? `♥ ${Math.round(hp)}/20` : '']
          .filter(Boolean).join(' · ');
        return `<div class="who"><span class="name">${esc(d.name)}</span>
          <span class="life${hp != null && hp <= 6 ? ' low' : ''}">${esc(life)}</span>
          <span class="where">${esc(d.where || '')}</span></div>`;
      }).join('');
    } else if (names.length) {
      rows = names.map((n) => `<div class="who"><span class="name">${esc(n)}</span></div>`).join('');
    } else {
      const seen = (s.world_feed && s.world_feed.attributes && s.world_feed.attributes.last_seen) || {};
      const last = Object.entries(seen).slice(0, 3)
        .map(([n, at]) => `${esc(n)} ${esc(ago(at))}`).join(', ');
      rows = `<div class="quiet">Nobody is on.${last ? ` Last on: ${last}.` : ''}</div>`;
    }
    const count = details.length || names.length;
    return `<section><div class="lab">${count ? `On now · ${count}` : 'On now'}</div><div class="rows">${rows}</div></section>`;
  }

  _buildingHtml(s) {
    const v = s.building;
    if (!v) return '';
    const a = v.attributes || {};
    const cur = a.current;
    const recent = (a.recent || []).filter((j) => j && j.status === 'done').slice(0, 6);
    const failed = (a.recent || []).filter((j) => j && j.status === 'failed').slice(0, 1);
    let now = '';
    if (cur) {
      const pct = typeof cur.progress === 'number' ? Math.max(0, Math.min(100, cur.progress)) : null;
      const meta = [cur.part, pct != null ? `${pct}%` : '', cur.started ? `started ${ago(cur.started)}` : '']
        .filter(Boolean).join(' · ');
      now = `<div class="job"><div class="jt">${esc(cur.title)}</div>
        ${meta ? `<div class="jp">${esc(meta)}</div>` : ''}
        ${pct != null ? `<div class="bar" role="img" aria-label="${pct}% built"><i style="width:${pct}%"></i></div>` : ''}</div>`;
    } else {
      now = `<div class="quiet">Not building anything right now${a.queued ? ` · ${a.queued} planned` : ''}.</div>`;
    }
    const shots = recent.length ? `<div class="shots">${recent.map((j) => j.image
      ? `<div class="shot"><img src="${esc(j.image)}" alt="${esc(j.title)} from above" loading="lazy"><span class="st">${esc(j.title)}</span><span class="sw">${esc(ago(j.finished))}</span></div>`
      : `<div class="shot text"><span class="st">${esc(j.title)}</span><span class="sw">${esc([j.part, ago(j.finished)].filter(Boolean).join(' · '))}</span></div>`).join('')}</div>` : '';
    const fail = failed.length ? `<div class="quiet">Could not finish ${esc(failed[0].title)} (${esc(ago(failed[0].finished))}).</div>` : '';
    return `<section><div class="lab">Building</div><div class="rows">${now}${shots}${fail}</div></section>`;
  }

  _feedHtml(s) {
    const f = s.world_feed;
    const events = ((f && f.attributes && f.attributes.events) || [])
      .filter((e) => e && e.kind !== 'save').slice(0, this._config.feed);
    if (!events.length) return '';
    return `<section><div class="lab">In the world</div><div class="feed">${events.map((e) => `
      <div class="ev ${esc(e.kind)}"><span class="m" aria-hidden="true">${KIND_MARK[e.kind] || '•'}</span>
      <span class="t">${esc(e.text)}</span><span class="w">${esc(ago(e.time))}</span></div>`).join('')}</div></section>`;
  }

  _footHtml(s) {
    const bits = [];
    if (usable(s.last_save)) bits.push(`Saved ${ago(s.last_save.state)}`);
    if (usable(s.last_backup)) bits.push(`backed up ${ago(s.last_backup.state)}`);
    return bits.length ? `<div class="foot">${esc(bits.join(' · '))}</div>` : '';
  }

  _render(s) {
    const cfg = this._config;
    if (!Object.keys(s).length) {
      this.shadowRoot.innerHTML = `<style>${css}</style><div class="wrap"><div class="quiet">BRUH Minecraft's world sensors are not in Home Assistant yet. Update the BRUH Minecraft add-on and restart Home Assistant.</div></div>`;
      return;
    }
    this.shadowRoot.innerHTML = `<style>${css}</style><div class="wrap">
      ${cfg.title ? `<div class="title">${esc(cfg.title)}</div>` : ''}
      ${this._skyHtml(s)}
      ${this._whoHtml(s)}
      ${this._buildingHtml(s)}
      ${this._feedHtml(s)}
      ${this._footHtml(s)}
    </div>`;
  }
}

// Guarded: a file loaded twice (Morph reloads a changed card) may define a
// name only once.
if (!customElements.get('morph-minecraft-world')) customElements.define('morph-minecraft-world', MorphMinecraftWorld);
console.info(`%c MORPH MINECRAFT WORLD %c ${CARD_VERSION} `,
  'background:#5b8731;color:#fff;font-weight:700;border-radius:3px 0 0 3px',
  'background:#16181d;color:#fff;border-radius:0 3px 3px 0');
