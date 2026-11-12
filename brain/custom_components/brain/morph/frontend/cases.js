// brAIn's cases, drawn where their subject is — docs/design/morph-vision.md
// §13–§14. There is one list and it is brAIn's (`/config/.brain/morph/
// cases.json`, read by the integration); Morph keeps none of its own.
//
// A case card reads the way brAIn's own Needs you reads it (#452): the one
// status chip (Urgent / Problem / Tidy-up / Suggestion / Question), the
// title with names where brAIn has ids, the detail, the ask, the thread, a
// reply line, and brAIn's presses under brAIn's labels — every one Morph can
// carry back to brAIn's queue (Fix or Apply or Add to To Do, Dismiss,
// Snooze, Doesn't apply), in brAIn's order. A reply is still read by
// brAIn's interpreter, so a Yes, a No or "yes, but call it Sump Pump
// Current" is the reply's words.

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

// brAIn's chip words (answers.CHIP_WORDS), and the rule that picks one
// (answers.chip) for a row cases.json sent without its `chip`.
export const CHIP_WORDS = { urgent: 'Urgent', problem: 'Problem', tidy: 'Tidy-up', suggestion: 'Suggestion', question: 'Question' };
const CHIP_COLORS = { urgent: 'var(--rose)', problem: 'var(--amber)', tidy: 'var(--quiet)', suggestion: 'var(--violet)', question: 'var(--violet)' };
const TIDY_SOURCES = ['check:reg.hardware_name', 'check:reg.no_area'];
export function caseChip(c) {
  if (c && CHIP_WORDS[c.chip]) return c.chip;
  if (!c) return 'problem';
  if (c.urgent) return 'urgent';
  if (c.kind === 'question') return 'question';
  if (c.kind === 'opportunity') return 'suggestion';
  const src = String(c.source || '');
  if (src === 'safety' || src === 'security' || src.startsWith('check:sec.')) return 'problem';
  if ((TIDY_SOURCES.includes(src) && c.fixable) || c.severity === 'info') return 'tidy';
  return 'problem';
}

// The presses Morph can carry back (the integration's CASE_ACTIONS), with
// brAIn's own words for each.
const PRESS_WORDS = { fix: 'Fix', apply: 'Apply', todo: 'Add to To Do', dismiss: 'Dismiss', snooze: 'Snooze', not_applicable: "Doesn't apply" };
export function casePresses(c) {
  if (!c || ['planning', 'fixing'].includes(c.status)) return [];
  const sent = Array.isArray(c.answers) ? c.answers.filter((a) => a && PRESS_WORDS[a.action]) : [];
  let list = sent.map((a) => ({ action: a.action, label: a.label || PRESS_WORDS[a.action] }));
  if (!list.length && !(Array.isArray(c.answers) && c.answers.length)) {
    // A row from a brAIn that sent no presses: brAIn's own rule, roughly.
    if (c.status === 'planned') list.push({ action: 'apply', label: 'Apply' });
    else if (c.fixable && c.kind === 'problem') list.push({ action: 'fix', label: 'Fix' });
    else if (c.kind === 'problem') list.push({ action: 'todo', label: 'Add to To Do' });
    if (c.kind !== 'question') list.push({ action: 'dismiss', label: 'Dismiss' });
    if (c.kind === 'change') list.push({ action: 'todo', label: 'Add to To Do' });
  }
  // brAIn puts Snooze on every card that can be put off, before the ending
  // that waves it away; cases.json leaves it out, so Morph puts it back.
  if (['problem', 'question', 'opportunity'].includes(c.kind) && !list.some((a) => a.action === 'snooze')) {
    const at = list.findIndex((a) => ['not_applicable', 'wrong'].includes(a.action));
    list.splice(at < 0 ? list.length : at, 0, { action: 'snooze', label: 'Snooze' });
  }
  return list;
}

// Ids in brAIn's sentence read as the device's name, as brAIn's panel does.
const named = (text, name) => String(text || '').replace(/\b[a-z_]+\.[a-z0-9_]+\b/g, (id) => (name && name(id)) || id);

const turnHtml = (t) => `<div class="turnline ${t.who === 'you' ? 'you' : 'brain'}">${esc(t.text)}</div>`;

// The card's face. `ui`: {pending, draft, family, replyOpen, admin, who,
// name}: `who` is the household's name for the assistant (brAIn's
// personality), `name(id)` a device's friendly name.
export function caseFace(c, ui) {
  const u = ui || {};
  const who = u.who || 'brAIn';
  const color = caseColor(c);
  const thread = c.thread || [];
  const shown = thread.slice(-THREAD_SHOWN);
  const earlier = thread.length - shown.length;
  const chip = caseChip(c);
  const plan = c.status === 'planned' && c.plan ? `<div class="caseplan"><span class="small">What Apply will change</span>${(c.plan.steps || []).slice(0, 6).map((s) => `<span class="sm">· ${esc(named(s, u.name))}</span>`).join('')}${c.plan.risk ? `<span class="sm"><b>What could go wrong:</b> ${esc(c.plan.risk)}</span>` : ''}</div>` : '';
  const phase = c.status === 'planning' ? `${who} is working out a plan…` : c.status === 'fixing' ? `${who} is making the change…` : c.status === 'triaging' ? `${who} has not looked at this yet.` : '';
  const busy = u.pending ? `<div class="working"><span class="pulse"></span><span>${esc(u.pending)}</span></div>` : '';
  const words = u.admin === false ? [] : casePresses(c).map((a, i) => `<button type="button" class="wd${i === 0 && ['fix', 'apply', 'todo'].includes(a.action) ? ' strong' : ''}" data-act="case" data-v="${esc(a.action)}" data-case="${esc(c.id)}">${esc(a.label)}</button>`);
  // A wall tablet shows a question's reply line only once tapped, so a
  // child leaning on the counter cannot answer it (§14.6).
  const hideReply = u.family && c.kind === 'question' && !u.replyOpen;
  const reply = u.admin === false ? '' : hideReply
    ? `<button type="button" class="wd" data-act="case-open-reply" data-case="${esc(c.id)}">Reply</button>`
    : `<input class="replyin" type="text" data-keep="reply:${esc(c.id)}" data-act-enter="case-reply" data-case="${esc(c.id)}" placeholder="Reply…" aria-label="Reply to ${esc(who)} about this" style="--cc:${color}">`;
  const detail = c.detail && c.detail !== c.claim ? `<p class="casebody">${esc(named(c.detail, u.name))}</p>` : '';
  return `<div class="case" data-ctl="1" style="--cc:${color}" data-case-card="${esc(c.id)}">
<span class="casechip" data-chip="${chip}" style="--chip:${CHIP_COLORS[chip]}"><i></i>${esc(CHIP_WORDS[chip])}</span>
<p class="claim">${esc(named(c.claim || c.text || '', u.name))}</p>${detail}${c.ask ? `<p class="caseask">${esc(named(c.ask, u.name))}</p>` : ''}${phase ? `<p class="small">${esc(phase)}</p>` : ''}${plan}
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
