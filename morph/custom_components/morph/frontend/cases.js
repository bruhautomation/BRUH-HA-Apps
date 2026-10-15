// brAIn's cases, drawn where their subject is — docs/design/morph-vision.md
// §13–§14. There is one list and it is brAIn's (`/config/.brain/morph/
// cases.json`, read by the integration); Morph keeps none of its own.
//
// A case card has four parts and nothing else: the claim, the ask (only
// when brAIn wants something), a reply line, and the words Dismiss and To
// Do (with Fix leading them where brAIn could make the change). No Yes, no
// No, no Wrong, no Snooze: a reply is read by brAIn's interpreter, and the
// words decide the ending — "yes, but call it Sump Pump Current" is one
// reply. A reply brAIn cannot place is answered with a question, in the
// card, as a turn.

import { esc, mix, friendly } from './util.js';

export const THREAD_SHOWN = 3;

// The meaning colour (§9.2): rose for a problem worth a look, amber for
// caution, violet for a question or a suggestion.
export function caseColor(c) {
  if (!c) return 'var(--violet)';
  if (['question', 'opportunity', 'change'].includes(c.kind)) return 'var(--violet)';
  if (c.urgent || ['critical', 'serious'].includes(c.severity)) return 'var(--rose)';
  return 'var(--amber)';
}

// Which room a case belongs in: its entity's section on the page, else the
// section whose area is its area. None is a house-wide case.
export function placeCase(c, secFor) {
  // The case's own subject first: the room that shows it, else its area;
  // then the area brAIn sent; only then the evidence, by the room most of
  // it is shown in. Taking the first evidence id that matched anything —
  // with the case's area handed to every lookup — put a case about the
  // garage freezer in whichever room happened to show the outdoor sensor
  // cited beside it.
  if (c.entity_id) { const s = secFor(c.entity_id, ''); if (s) return s; }
  if (c.area_id) { const s = secFor('', c.area_id); if (s) return s; }
  const votes = {}; let best = null;
  (c.evidence || []).filter(Boolean).forEach((e, i) => {
    const s = secFor(e, ''); if (!s) return;
    votes[s] = (votes[s] || 0) + 1 - i * 0.01;
    if (!best || votes[s] > votes[best]) best = s;
  });
  return best;
}

const turnHtml = (t) => `<div class="turnline ${t.who === 'you' ? 'you' : 'brain'}">${esc(t.text)}</div>`;

// The card's face. `ui`: {pending, draft, family, replyOpen, admin}.
export function caseFace(c, ui) {
  const u = ui || {};
  const color = caseColor(c);
  const thread = c.thread || [];
  const shown = thread.slice(-THREAD_SHOWN);
  const earlier = thread.length - shown.length;
  const plan = c.status === 'planned' && c.plan ? `<div class="caseplan"><span class="small">What Apply will change</span>${(c.plan.steps || []).slice(0, 6).map((s) => `<span class="sm">· ${esc(s)}</span>`).join('')}${c.plan.risk ? `<span class="sm"><b>What could go wrong:</b> ${esc(c.plan.risk)}</span>` : ''}</div>` : '';
  const phase = c.status === 'planning' ? 'brAIn is working out a plan…' : c.status === 'fixing' ? 'brAIn is making the change…' : c.status === 'triaging' ? 'brAIn has not looked at this yet.' : '';
  const busy = u.pending ? `<div class="working"><span class="pulse"></span><span>${esc(u.pending)}</span></div>` : '';
  const words = [];
  if (u.admin !== false) {
    if (c.status === 'planned') words.push(`<button type="button" class="wd strong" data-act="case" data-v="apply" data-case="${esc(c.id)}">Apply</button>`);
    else if (c.fixable && c.kind === 'problem' && !['fixing', 'planning'].includes(c.status)) words.push(`<button type="button" class="wd strong" data-act="case" data-v="fix" data-case="${esc(c.id)}">Fix</button>`);
    words.push(`<button type="button" class="wd" data-act="case" data-v="dismiss" data-case="${esc(c.id)}">Dismiss</button>`);
    if (c.kind !== 'chore') words.push(`<button type="button" class="wd" data-act="case" data-v="todo" data-case="${esc(c.id)}">To Do</button>`);
  }
  // A wall tablet shows a question's reply line only once tapped, so a
  // child leaning on the counter cannot answer it (§14.6).
  const hideReply = u.family && c.kind === 'question' && !u.replyOpen;
  const reply = u.admin === false ? '' : hideReply
    ? `<button type="button" class="wd" data-act="case-open-reply" data-case="${esc(c.id)}">Reply</button>`
    : `<input class="replyin" type="text" data-keep="reply:${esc(c.id)}" data-act-enter="case-reply" data-case="${esc(c.id)}" placeholder="Reply…" aria-label="Reply to brAIn about this" style="--cc:${color}">`;
  return `<div class="case" data-ctl="1" style="--cc:${color}" data-case-card="${esc(c.id)}">
<p class="claim">${esc(c.claim || c.text || '')}</p>${c.ask ? `<p class="caseask">${esc(c.ask)}</p>` : ''}${phase ? `<p class="small">${esc(phase)}</p>` : ''}${plan}
${thread.length ? `<div class="thread">${earlier ? `<details class="earlier"><summary>earlier</summary>${thread.slice(0, earlier).map(turnHtml).join('')}</details>` : ''}${shown.map(turnHtml).join('')}</div>` : ''}${busy}
<div class="replyrow">${reply}<span class="casewords">${words.join('')}</span></div></div>`;
}

// The To Do section: one line per item, the sentence and its room. Tap
// ticks it off; slide right snoozes it a week; hold opens its options.
export function todoFace(items, hass, ui) {
  const u = ui || {};
  if (!items.length) return '';
  return `<div class="todolist" data-ctl="1">${items.map((t) => {
    const open = u.open === t.id;
    const room = t.area_name || '';
    return `<div class="todorow${open ? ' open' : ''}" data-todo="${esc(t.id)}" data-k="todo-${esc(t.id)}" role="button" tabindex="0" aria-label="${esc(String(t.text).replace(/\.$/, ""))}. Tap to tick it off.">
<span class="tick" aria-hidden="true"></span><span class="lx"><span>${esc(t.text)}</span>${room ? `<span class="small">${esc(room)}</span>` : ''}</span>${u.sliding === t.id ? `<span class="small" style="color:var(--violet)">${esc(u.slideWord || '')}</span>` : ''}
${open ? `<span class="todoacts"><button type="button" class="wd" data-act="todo" data-v="snooze" data-id="${esc(t.id)}">Snooze a week</button><button type="button" class="wd bad" data-act="todo" data-v="drop" data-id="${esc(t.id)}">Delete</button></span>` : ''}</div>`;
  }).join('')}</div>`;
}

// The friendly name brAIn's sentence uses; the panel's own lookup is the
// same one, so a case and a card name a device alike.
export function caseName(hass, c) { return c.entity_id ? friendly(hass, c.entity_id) : ''; }

export const caseWash = (c) => mix(caseColor(c), 6, 'var(--surface)');
