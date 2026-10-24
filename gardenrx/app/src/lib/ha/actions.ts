/**
 * What Home Assistant may do to the garden, and how each is done.
 *
 * Every action is what the panel's own button does, done with the same
 * builder against the same database: logging a harvest is the harvest
 * tracker's insert, and marking a queued spray done is the spray planner's
 * `logQueuedSpray` — insert the event and its rows, delete the queue entry,
 * deduct what the spray used from inventory. A second implementation of
 * "what logging a spray means" would be the same press teaching the garden
 * two different things depending on where it was pressed.
 *
 * An action answers `{ ok: false, error }` for a refusal and never throws:
 * the integration hands the sentence to whoever called the service.
 */

import type { DbClient } from '@/lib/db/query';
import { calculateDose } from '@/lib/dose';
import { deductionFor } from '@/lib/inventory-deduct';
import { SPRAYER } from '@/config/thresholds';
import { buildPhiByProductGroup } from '@/lib/phi';
import { HARVEST_UNITS, harvestLb, harvestValue, localDate } from './summary';
import type { Crop, Variety } from '@/lib/database.types';
import { CATEGORY_ORDER, categoryForCrop, cropsByCategory } from '@/lib/crop-category';
import { CROP_CATALOG } from '@/lib/crop-catalog';
import { COUNT_UNITS, parseSize, VOLUME_UNITS, WEIGHT_UNITS } from '@/lib/container';

export type ActionResult = { ok: true; [k: string]: unknown } | { ok: false; error: string };

const fail = (error: string): ActionResult => ({ ok: false, error });
const norm = (s: string) => s.trim().toLowerCase();

const isId = (ref: unknown) =>
  typeof ref === 'number' || (typeof ref === 'string' && /^\d+$/.test(ref.trim()));

/** `"x" could be A, B or C` — the names a reference might mean, capped. */
function couldBe(ref: string, names: string[]): string {
  const shown = names.slice(0, 5);
  const rest = names.length - shown.length;
  const list =
    shown.length > 1
      ? `${shown.slice(0, -1).join(', ')} or ${shown[shown.length - 1]}`
      : (shown[0] ?? '');
  return `"${ref}" could be ${list}${rest > 0 ? ` (and ${rest} more)` : ''}.`;
}

/**
 * Find one row by its id or its name: an exact name (any case) first, then
 * a part of a name when only one matches. Anything else is a sentence saying
 * what is wrong, never a guess.
 */
function resolveNamed<T extends { id: number }>(
  rows: T[],
  ref: unknown,
  nameOf: (row: T) => string,
  what: string,
  missing: string
): T | string {
  if (isId(ref)) return rows.find((r) => r.id === Number(ref)) ?? `No ${what} has id ${ref}.`;
  if (typeof ref !== 'string' || !ref.trim()) return missing;
  const exact = rows.filter((r) => norm(nameOf(r)) === norm(ref));
  if (exact.length === 1) return exact[0];
  if (exact.length > 1) return couldBe(ref.trim(), exact.map(nameOf));
  const partial = rows.filter((r) => norm(nameOf(r)).includes(norm(ref)));
  if (partial.length === 1) return partial[0];
  if (partial.length > 1) return couldBe(ref.trim(), partial.map(nameOf));
  return `No ${what} is called "${ref.trim()}".`;
}

function resolveCrop(
  crops: Crop[],
  ref: unknown,
  missing = 'Say which crop was harvested.'
): Crop | string {
  return resolveNamed(crops, ref, (c) => c.name, 'crop', missing);
}

function resolveVariety(varieties: Variety[], crop: Crop, ref: unknown): Variety | null | string {
  if (ref === undefined || ref === null || ref === '') return null;
  const mine = varieties.filter((v) => v.crop_id === crop.id);
  if (typeof ref === 'number' || (typeof ref === 'string' && /^\d+$/.test(ref.trim()))) {
    return mine.find((v) => v.id === Number(ref)) ?? `${crop.name} has no variety with id ${ref}.`;
  }
  if (typeof ref !== 'string') return 'The variety must be a name or an id.';
  const exact = mine.filter((v) => norm(v.name) === norm(ref));
  if (exact.length === 1) return exact[0];
  const partial = mine.filter((v) => norm(v.name).includes(norm(ref)));
  if (partial.length === 1) return partial[0];
  return `${crop.name} has no variety called "${ref}".`;
}

export async function logHarvest(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const [{ data: crops }, { data: varieties }] = await Promise.all([
    db.from('crops').select('*'),
    db.from('varieties').select('*'),
  ]);
  const crop = resolveCrop(crops ?? [], input.crop ?? input.crop_id);
  if (typeof crop === 'string') return fail(crop);
  const variety = resolveVariety(varieties ?? [], crop, input.variety ?? input.variety_id);
  if (typeof variety === 'string') return fail(variety);

  const weight = Number(input.weight);
  if (!Number.isFinite(weight) || weight <= 0)
    return fail('The weight must be a number above zero.');
  const unit = String(input.unit ?? 'lb');
  if (!(HARVEST_UNITS as readonly string[]).includes(unit)) {
    return fail(`The unit must be one of ${HARVEST_UNITS.join(', ')}.`);
  }
  const day = input.date ? String(input.date) : localDate(now, timeZone);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || isNaN(Date.parse(day))) {
    return fail('The date must be YYYY-MM-DD.');
  }
  const notes =
    typeof input.notes === 'string' && input.notes.trim() ? input.notes.trim().slice(0, 500) : null;

  // Stored at UTC noon, as the panel does, so the calendar day reads the same
  // in every time zone.
  const row = {
    crop_id: crop.id,
    variety_id: variety?.id ?? null,
    weight,
    unit,
    harvested_at: new Date(`${day}T12:00:00Z`).toISOString(),
    notes,
  };
  const { data, error } = await db.from('harvests').insert(row).select().single();
  if (error || !data)
    return fail(`The harvest was not saved: ${error?.message ?? 'no row came back'}.`);

  return {
    ok: true,
    id: data.id,
    crop: crop.name,
    variety: variety?.name ?? null,
    weight,
    unit,
    date: day,
    lb: Math.round(harvestLb(data, crop) * 1000) / 1000,
    value: Math.round(harvestValue(data, crop) * 100) / 100,
    phi_warning: await phiWarning(db, crop, day),
  };
}

/**
 * The harvest tracker's PHI check: a pick inside a pre-harvest interval is
 * logged (it happened) and said, never refused.
 */
async function phiWarning(db: DbClient, crop: Crop, day: string): Promise<string | null> {
  if (crop.crop_group_id == null) return null;
  const [
    { data: uses },
    { data: eventCrops },
    { data: events },
    { data: eventProducts },
    { data: products },
  ] = await Promise.all([
    db.from('crop_uses').select('*').eq('crop_group_id', crop.crop_group_id),
    db.from('spray_event_crops').select('*').eq('crop_id', crop.id),
    db.from('spray_events').select('*'),
    db.from('spray_event_products').select('*'),
    db.from('products').select('id, brand'),
  ]);
  const phi = buildPhiByProductGroup(uses ?? []);
  const eventIds = new Set((eventCrops ?? []).map((c) => c.spray_event_id));
  const hDay = Date.parse(`${day}T12:00:00Z`);
  let worst: { brand: string; short: number; safe: string } | null = null;
  for (const ev of events ?? []) {
    if (!eventIds.has(ev.id)) continue;
    const sDay = Date.parse(ev.date.slice(0, 10) + 'T12:00:00Z');
    if (isNaN(sDay) || sDay > hDay) continue;
    for (const ep of (eventProducts ?? []).filter((p) => p.spray_event_id === ev.id)) {
      const days = phi.get(`${ep.product_id}:${crop.crop_group_id}`);
      if (!days) continue;
      const elapsed = Math.round((hDay - sDay) / 86400000);
      if (elapsed >= days) continue;
      const short = days - elapsed;
      if (!worst || short > worst.short) {
        worst = {
          brand:
            (products ?? []).find((p) => p.id === ep.product_id)?.brand ??
            `product ${ep.product_id}`,
          short,
          safe: new Date(sDay + days * 86400000).toISOString().slice(0, 10),
        };
      }
    }
  }
  return worst
    ? `Picked ${worst.short} day${worst.short === 1 ? '' : 's'} inside the pre-harvest interval for ${worst.brand} (safe from ${worst.safe}).`
    : null;
}

export async function deleteHarvest(
  db: DbClient,
  input: Record<string, unknown>
): Promise<ActionResult> {
  const id = Number(input.id);
  if (!Number.isInteger(id) || id <= 0) return fail('Say which harvest to delete by its id.');
  const { data, error } = await db.from('harvests').delete().eq('id', id).select();
  if (error) return fail(`The harvest was not deleted: ${error.message}.`);
  if (!data?.length) return fail(`No harvest has id ${id}.`);
  return { ok: true, id };
}

/** YYYY-MM-DD and a real day, or the sentence that says it is not. */
function dayOf(input: unknown, now: Date, timeZone: string): string | { error: string } {
  const day =
    input === undefined || input === null || input === ''
      ? localDate(now, timeZone)
      : String(input);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || isNaN(Date.parse(day))) {
    return { error: 'The date must be YYYY-MM-DD.' };
  }
  return day;
}

const list = (v: unknown): unknown[] =>
  v === undefined || v === null || v === '' ? [] : Array.isArray(v) ? v : [v];

type SprayLine = { product_id: number; rate_applied: number | null; rate_unit: string };

/**
 * The spray planner's `insertSprayEvent`: the event, then its products and
 * crops, and the event taken back if any of those could not be saved — a
 * spray logged without its products is worse than none.
 */
async function recordSpray(
  db: DbClient,
  spray: {
    date: string;
    notes: string | null;
    gallons: number;
    lines: SprayLine[];
    cropIds: number[];
  }
): Promise<{ id: number } | { error: string }> {
  const { data: event, error } = await db
    .from('spray_events')
    .insert({ date: spray.date, notes: spray.notes, volume_gallons: spray.gallons })
    .select()
    .single();
  if (error || !event)
    return { error: `The spray was not logged: ${error?.message ?? 'no row came back'}.` };
  const writes = await Promise.all([
    ...spray.lines.map((p) =>
      db.from('spray_event_products').insert({
        spray_event_id: event.id,
        product_id: p.product_id,
        rate_applied: p.rate_applied,
        rate_unit: p.rate_unit,
      })
    ),
    ...spray.cropIds.map((crop_id) =>
      db.from('spray_event_crops').insert({ spray_event_id: event.id, crop_id })
    ),
  ]);
  if (writes.some((w) => w.error)) {
    await db.from('spray_events').delete().eq('id', event.id);
    return { error: 'The spray was not logged: its products or crops could not be saved.' };
  }
  return { id: event.id };
}

/**
 * Best-effort, exactly as the planner's applyPostLogSideEffects: the spray is
 * logged whether or not the stock could be adjusted.
 */
async function deductStock(
  db: DbClient,
  lines: SprayLine[],
  gallons: number,
  now: Date
): Promise<string[]> {
  const deducted: string[] = [];
  for (const p of lines) {
    if (p.rate_applied == null) continue;
    const { data: inv } = await db
      .from('treatment_inventory')
      .select('*')
      .eq('product_id', p.product_id);
    const item = inv?.[0];
    if (!item) continue;
    const used = deductionFor(calculateDose(p.rate_applied, p.rate_unit, gallons), item.unit);
    if (used === null) continue;
    await db
      .from('treatment_inventory')
      .update({ quantity: Math.max(0, (item.quantity ?? 0) - used), updated_at: now.toISOString() })
      .eq('id', item.id);
    deducted.push(`${Math.round(used * 100) / 100} ${item.unit}`);
  }
  return deducted;
}

export async function completeQueuedSpray(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const id = Number(input.id);
  if (!Number.isInteger(id) || id <= 0) return fail('Say which queued spray was done by its id.');
  const gallons = gallonsOf(input.volume_gallons);
  if (gallons === null) return fail('The sprayer volume must be a number above zero.');

  const { data: queued } = await db.from('queued_sprays').select('*').eq('id', id).maybeSingle();
  if (!queued) return fail(`No queued spray has id ${id} — it may already have been logged.`);
  const [{ data: qProducts }, { data: qCrops }] = await Promise.all([
    db.from('queued_spray_products').select('*').eq('queued_spray_id', id),
    db.from('queued_spray_crops').select('*').eq('queued_spray_id', id),
  ]);
  const lines = (qProducts ?? []).map((p) => ({
    product_id: p.product_id,
    rate_applied: p.rate_applied,
    rate_unit: p.rate_unit,
  }));
  const cropIds = (qCrops ?? []).map((c) => c.crop_id);

  const date = input.date ? String(input.date) : localDate(now, timeZone);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return fail('The date must be YYYY-MM-DD.');

  const event = await recordSpray(db, { date, notes: queued.notes, gallons, lines, cropIds });
  if ('error' in event) return fail(event.error);
  await db.from('queued_sprays').delete().eq('id', id);
  const deducted = await deductStock(db, lines, gallons, now);

  return {
    ok: true,
    spray_event_id: event.id,
    date,
    products: lines.length,
    crops: cropIds.length,
    deducted,
  };
}

function gallonsOf(v: unknown): number | null {
  const gallons = v === undefined || v === null || v === '' ? SPRAYER.gallons : Number(v);
  return Number.isFinite(gallons) && gallons > 0 ? gallons : null;
}

export async function deleteQueuedSpray(
  db: DbClient,
  input: Record<string, unknown>
): Promise<ActionResult> {
  const id = Number(input.id);
  if (!Number.isInteger(id) || id <= 0) return fail('Say which queued spray to remove by its id.');
  const { data, error } = await db.from('queued_sprays').delete().eq('id', id).select();
  if (error) return fail(`The queued spray was not removed: ${error.message}.`);
  if (!data?.length) return fail(`No queued spray has id ${id}.`);
  return { ok: true, id };
}

/**
 * What a spray (logged or queued) is: which crops, which products at which
 * rate. Crops are named one by one, or as one of the garden's three areas, or
 * both; a product's rate is the one given, else its label's for one of those
 * crops, as the planner suggests it.
 */
async function sprayPlan(
  db: DbClient,
  input: Record<string, unknown>
): Promise<
  | { error: string }
  | { crops: Crop[]; lines: (SprayLine & { brand: string })[]; offLabel: string[] }
> {
  const [{ data: crops }, { data: groups }, { data: products }] = await Promise.all([
    db.from('crops').select('*'),
    db.from('crop_groups').select('*'),
    db.from('products').select('id, brand'),
  ]);
  const allCrops = crops ?? [];
  const chosen = new Map<number, Crop>();
  for (const ref of list(input.crop ?? input.crops ?? input.crop_id)) {
    const crop = resolveCrop(allCrops, ref);
    if (typeof crop === 'string') return { error: crop };
    chosen.set(crop.id, crop);
  }
  for (const ref of list(input.area)) {
    const area = CATEGORY_ORDER.find((a) => norm(a) === norm(String(ref)));
    if (!area)
      return {
        error: `The area must be Orchard, Garden or Landscape, not "${String(ref).trim()}".`,
      };
    const inArea = cropsByCategory(
      allCrops.filter((c) => c.is_active),
      groups ?? []
    ).find((g) => g.category === area);
    if (!inArea?.crops.length) return { error: `No crop is in the ${area} yet.` };
    for (const c of inArea.crops) chosen.set(c.id, c);
  }
  if (!chosen.size)
    return { error: 'Say which crops were sprayed, or an area (Orchard, Garden or Landscape).' };

  const refs = list(input.product ?? input.products ?? input.product_id);
  if (!refs.length) return { error: 'Say which product was sprayed.' };
  const catalog = (products ?? []) as { id: number; brand: string }[];
  const picked: { id: number; brand: string }[] = [];
  for (const ref of refs) {
    const product = resolveNamed(
      catalog,
      ref,
      (p) => p.brand,
      'product',
      'Say which product was sprayed.'
    );
    if (typeof product === 'string') return { error: product };
    if (!picked.some((p) => p.id === product.id)) picked.push(product);
  }
  const rates = list(input.rate);
  const units = list(input.rate_unit);
  if (rates.length > 1 && rates.length !== picked.length) {
    return {
      error: `Give one rate for each product (${picked.length}), or one rate for all of them.`,
    };
  }
  if (units.length > 1 && units.length !== picked.length) {
    return {
      error: `Give one rate unit for each product (${picked.length}), or one for all of them.`,
    };
  }

  const groupIds = [
    ...new Set([...chosen.values()].map((c) => c.crop_group_id).filter((g) => g != null)),
  ];
  const { data: uses } = groupIds.length
    ? await db
        .from('crop_uses')
        .select('*')
        .in(
          'product_id',
          picked.map((p) => p.id)
        )
        .in('crop_group_id', groupIds as number[])
        .order('id')
    : { data: [] };
  const lines: (SprayLine & { brand: string })[] = [];
  const offLabel: string[] = [];
  for (const [i, product] of picked.entries()) {
    const label = (uses ?? []).find((u) => u.product_id === product.id);
    const rateIn = rates.length ? rates[rates.length === 1 ? 0 : i] : undefined;
    let rate: number | null = label ? (label.rate_max ?? label.rate_min ?? null) : null;
    if (rateIn !== undefined && rateIn !== null && rateIn !== '') {
      rate = Number(rateIn);
      if (!Number.isFinite(rate) || rate <= 0)
        return { error: 'A rate must be a number above zero.' };
    }
    const unitIn = units.length ? units[units.length === 1 ? 0 : i] : undefined;
    const unit =
      typeof unitIn === 'string' && unitIn.trim()
        ? unitIn.trim().slice(0, 40)
        : (label?.rate_unit ?? 'fl oz/gal');
    lines.push({
      product_id: product.id,
      brand: product.brand,
      rate_applied: rate,
      rate_unit: unit,
    });
    for (const crop of chosen.values()) {
      if (crop.crop_group_id == null) continue;
      if (
        !(uses ?? []).some(
          (u) => u.product_id === product.id && u.crop_group_id === crop.crop_group_id
        )
      ) {
        offLabel.push(`${product.brand} is not labelled for ${crop.name}.`);
      }
    }
  }
  const sorted = [...chosen.values()].sort((a, b) => a.name.localeCompare(b.name));
  return { crops: sorted, lines, offLabel };
}

const describeLines = (lines: (SprayLine & { brand: string })[]) =>
  lines.map((l) => ({ product: l.brand, rate: l.rate_applied, rate_unit: l.rate_unit }));

const notesOf = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 500) : null);

/** A spray nobody queued — the planner's Log button. */
export async function logSpray(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const plan = await sprayPlan(db, input);
  if ('error' in plan) return fail(plan.error);
  const date = dayOf(input.date, now, timeZone);
  if (typeof date !== 'string') return fail(date.error);
  const gallons = gallonsOf(input.volume_gallons);
  if (gallons === null) return fail('The sprayer volume must be a number above zero.');
  const cropIds = plan.crops.map((c) => c.id);

  const event = await recordSpray(db, {
    date,
    notes: notesOf(input.notes),
    gallons,
    lines: plan.lines,
    cropIds,
  });
  if ('error' in event) return fail(event.error);

  // The planner clears a queued spray that covered any of these crops.
  const cleared: number[] = [];
  const [{ data: queued }, { data: qCrops }] = await Promise.all([
    db.from('queued_sprays').select('id'),
    db.from('queued_spray_crops').select('queued_spray_id, crop_id'),
  ]);
  for (const q of queued ?? []) {
    const covers = (qCrops ?? []).some(
      (qc) => qc.queued_spray_id === q.id && cropIds.includes(qc.crop_id)
    );
    if (covers) {
      await db.from('queued_sprays').delete().eq('id', q.id);
      cleared.push(q.id);
    }
  }
  const deducted = await deductStock(db, plan.lines, gallons, now);
  const unrated = plan.lines.filter((l) => l.rate_applied == null).map((l) => l.brand);

  return {
    ok: true,
    spray_event_id: event.id,
    date,
    volume_gallons: gallons,
    crops: plan.crops.map((c) => c.name),
    products: describeLines(plan.lines),
    deducted,
    cleared_queued: cleared,
    label_warning: plan.offLabel.length ? plan.offLabel.join(' ') : null,
    note: unrated.length
      ? `No rate was given or found on the label for ${unrated.join(', ')}, so nothing came out of stock for it.`
      : null,
  };
}

/** A spray planned for later — the planner's Queue button. */
export async function queueSpray(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const plan = await sprayPlan(db, input);
  if ('error' in plan) return fail(plan.error);
  let planned: string | null = null;
  if (
    input.planned_date !== undefined &&
    input.planned_date !== null &&
    input.planned_date !== ''
  ) {
    const day = dayOf(input.planned_date, now, timeZone);
    if (typeof day !== 'string') return fail(day.error);
    planned = day;
  }
  const { data: queued, error } = await db
    .from('queued_sprays')
    .insert({ planned_date: planned, notes: notesOf(input.notes) })
    .select()
    .single();
  if (error || !queued)
    return fail(`The spray was not queued: ${error?.message ?? 'no row came back'}.`);
  const writes = await Promise.all([
    ...plan.lines.map((p) =>
      db.from('queued_spray_products').insert({
        queued_spray_id: queued.id,
        product_id: p.product_id,
        rate_applied: p.rate_applied,
        rate_unit: p.rate_unit,
      })
    ),
    ...plan.crops.map((c) =>
      db.from('queued_spray_crops').insert({ queued_spray_id: queued.id, crop_id: c.id })
    ),
  ]);
  if (writes.some((w) => w.error)) {
    await db.from('queued_sprays').delete().eq('id', queued.id);
    return fail('The spray was not queued: its products or crops could not be saved.');
  }
  return {
    ok: true,
    id: queued.id,
    planned_date: planned,
    crops: plan.crops.map((c) => c.name),
    products: describeLines(plan.lines),
    label_warning: plan.offLabel.length ? plan.offLabel.join(' ') : null,
  };
}

const STOCK_UNITS: readonly string[] = [...VOLUME_UNITS, ...WEIGHT_UNITS, ...COUNT_UNITS];

/**
 * Stock of one treatment: add to it, take from it, or say how much is on
 * hand. A product not stocked yet is started the way the Stock page's Add
 * does — one bottle of the size its label is sold in.
 */
export async function adjustInventory(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  _timeZone: string
): Promise<ActionResult> {
  const { data: products } = await db.from('products').select('*');
  const product = resolveNamed(
    products ?? [],
    input.product ?? input.product_id,
    (p) => p.brand,
    'product',
    'Say which product the stock is of.'
  );
  if (typeof product === 'string') return fail(product);

  const given = (v: unknown) => v !== undefined && v !== null && v !== '';
  if (given(input.change) && given(input.quantity)) {
    return fail('Give either an amount to add or take out, or how much is on hand — not both.');
  }
  if (!given(input.change) && !given(input.quantity)) {
    return fail(`Say how much ${product.brand} to add or take out, or how much is on hand.`);
  }
  const change = given(input.change) ? Number(input.change) : null;
  const quantity = given(input.quantity) ? Number(input.quantity) : null;
  if (change !== null && (!Number.isFinite(change) || change === 0)) {
    return fail(
      'The amount must be a number other than zero: above zero adds, below zero takes out.'
    );
  }
  if (quantity !== null && (!Number.isFinite(quantity) || quantity < 0)) {
    return fail('How much is on hand must be zero or more.');
  }
  const unitIn = given(input.unit) ? String(input.unit).trim() : null;
  if (unitIn !== null && !STOCK_UNITS.includes(unitIn)) {
    return fail(`The unit must be one of ${STOCK_UNITS.join(', ')}.`);
  }

  const { data: rows } = await db
    .from('treatment_inventory')
    .select('*')
    .eq('product_id', product.id);
  const item = rows?.[0];
  const round = (n: number) => Math.round(n * 100) / 100;
  if (!item) {
    if (change !== null && change < 0) {
      return fail(`${product.brand} is not in stock, so nothing can be taken out of it.`);
    }
    const label = parseSize(product.price_size ?? null);
    const unit = unitIn ?? label.unit;
    const bottle = label.unit === unit ? label.size : null;
    const { data: created, error } = await db
      .from('treatment_inventory')
      .insert({
        product_id: product.id,
        quantity: change ?? quantity ?? 0,
        unit,
        bottle_size: bottle,
        bottle_unit: unit,
        bottles: 1,
        cost_dollars: product.price_dollars ?? null,
        notes: notesOf(input.notes),
      })
      .select()
      .single();
    if (error || !created)
      return fail(`The stock was not saved: ${error?.message ?? 'no row came back'}.`);
    return {
      ok: true,
      id: created.id,
      product: product.brand,
      quantity: round(created.quantity),
      unit,
      created: true,
    };
  }
  if (unitIn !== null && unitIn !== item.unit) {
    return fail(
      `Stock of ${product.brand} is counted in ${item.unit}; give the amount in ${item.unit}.`
    );
  }
  const before = Number(item.quantity) || 0;
  const after = quantity ?? Math.max(0, before + (change as number));
  const { error } = await db
    .from('treatment_inventory')
    .update({ quantity: after, updated_at: now.toISOString() })
    .eq('id', item.id);
  if (error) return fail(`The stock was not saved: ${error.message}.`);
  return {
    ok: true,
    id: item.id,
    product: product.brand,
    quantity: round(after),
    before: round(before),
    unit: item.unit,
    created: false,
  };
}

/** A crop on the Crops page — the catalog's group when the name is one it knows. */
export async function addCrop(
  db: DbClient,
  input: Record<string, unknown>,
  _now: Date,
  _timeZone: string
): Promise<ActionResult> {
  const typed = typeof input.name === 'string' ? input.name.trim() : '';
  if (!typed) return fail('Say what the crop is called.');
  if (typed.length > 80) return fail('A crop name is at most 80 characters.');
  const [{ data: crops }, { data: groups }] = await Promise.all([
    db.from('crops').select('*'),
    db.from('crop_groups').select('*'),
  ]);
  const same = (crops ?? []).find((c) => norm(c.name) === norm(typed));
  if (same) return fail(`A crop called "${same.name}" already exists.`);
  const known = CROP_CATALOG.find((e) => norm(e.name) === norm(typed));
  let group = null as { id: number; name: string } | null;
  if (input.crop_group !== undefined && input.crop_group !== null && input.crop_group !== '') {
    const g = resolveNamed(
      groups ?? [],
      input.crop_group,
      (x) => x.name,
      'crop group',
      'Say which crop group.'
    );
    if (typeof g === 'string') return fail(g);
    group = g;
  } else if (known?.cropGroup) {
    group = (groups ?? []).find((g) => g.name === known.cropGroup) ?? null;
  }
  const name = known?.name ?? typed;
  const { data, error } = await db
    .from('crops')
    .insert({ name, crop_group_id: group?.id ?? null })
    .select()
    .single();
  if (error || !data)
    return fail(`The crop was not saved: ${error?.message ?? 'no row came back'}.`);
  return {
    ok: true,
    id: data.id,
    name,
    crop_group: group?.name ?? null,
    area: categoryForCrop(data, group?.name ?? null),
  };
}

/** A variety on a crop's page — and its stage row, as the page adds one. */
export async function addVariety(
  db: DbClient,
  input: Record<string, unknown>,
  _now: Date,
  _timeZone: string
): Promise<ActionResult> {
  const [{ data: crops }, { data: varieties }] = await Promise.all([
    db.from('crops').select('*'),
    db.from('varieties').select('*'),
  ]);
  const crop = resolveCrop(
    crops ?? [],
    input.crop ?? input.crop_id,
    'Say which crop the variety is of.'
  );
  if (typeof crop === 'string') return fail(crop);
  const name = typeof input.name === 'string' ? input.name.trim() : '';
  if (!name) return fail('Say what the variety is called.');
  if (name.length > 80) return fail('A variety name is at most 80 characters.');
  const same = (varieties ?? []).find((v) => v.crop_id === crop.id && norm(v.name) === norm(name));
  if (same) return fail(`${crop.name} already has a variety called "${same.name}".`);
  const { data, error } = await db
    .from('varieties')
    .insert({ name, crop_id: crop.id })
    .select()
    .single();
  if (error || !data)
    return fail(`The variety was not saved: ${error?.message ?? 'no row came back'}.`);
  await db.from('variety_stages').insert({ variety_id: data.id });
  return { ok: true, id: data.id, crop: crop.name, name };
}

/**
 * A dated note about a place in the garden. The garden has no journal table,
 * so the note is kept where the app already keeps words about a place: the
 * notes of an element on the garden map, one dated line each, newest last —
 * the same notes the map's Edit dialog shows and edits.
 */
export async function logNote(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const text = typeof input.note === 'string' ? input.note.replace(/\s+/g, ' ').trim() : '';
  if (!text) return fail('Say what the note is.');
  if (text.length > 500) return fail('A note is at most 500 characters.');
  const date = dayOf(input.date, now, timeZone);
  if (typeof date !== 'string') return fail(date.error);
  const [{ data: regions }, { data: zones }] = await Promise.all([
    db.from('garden_regions').select('*'),
    db.from('garden_zones').select('*'),
  ]);
  if (!regions?.length) {
    return fail(
      'Nothing is drawn on the garden map yet. A note is kept on a place on the map; draw it there first.'
    );
  }
  const zoneName = (id: number) => (zones ?? []).find((z) => z.id === id)?.name ?? 'the map';
  const labelOf = (r: (typeof regions)[number]) => r.name;
  const place = resolveNamed(
    regions,
    input.place,
    labelOf,
    'place',
    'Say which place on the garden map the note is about.'
  );
  if (typeof place === 'string') {
    // Two places can share a name in different zones; say which zones.
    const named = regions.filter(
      (r) => typeof input.place === 'string' && norm(r.name).includes(norm(input.place))
    );
    if (named.length > 1)
      return fail(
        couldBe(
          String(input.place).trim(),
          named.map((r) => `${r.name} in ${zoneName(r.zone_id)}`)
        )
      );
    return fail(place.replace(/^No place is called/, 'Nothing on the garden map is called'));
  }
  const line = `${date}: ${text}`;
  const notes = place.notes?.trim() ? `${place.notes.trim()}\n${line}` : line;
  const { error } = await db.from('garden_regions').update({ notes }).eq('id', place.id);
  if (error) return fail(`The note was not saved: ${error.message}.`);
  return {
    ok: true,
    id: place.id,
    place: place.name,
    zone: zoneName(place.zone_id),
    date,
    note: text,
  };
}

const HARVESTS_SHOWN = 200;

/** Harvests read back: by crop and between two days, with totals per crop and unit. */
export async function getHarvests(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const [{ data: crops }, { data: varieties }, { data: harvests }] = await Promise.all([
    db.from('crops').select('*'),
    db.from('varieties').select('*'),
    db.from('harvests').select('*'),
  ]);
  const allCrops = crops ?? [];
  let only: Crop | null = null;
  if (input.crop !== undefined && input.crop !== null && input.crop !== '') {
    const crop = resolveCrop(allCrops, input.crop);
    if (typeof crop === 'string') return fail(crop);
    only = crop;
  }
  const bound = (v: unknown) => {
    if (v === undefined || v === null || v === '') return null;
    return dayOf(v, now, timeZone);
  };
  const start = bound(input.start);
  const end = bound(input.end);
  if (start && typeof start !== 'string') return fail(start.error);
  if (end && typeof end !== 'string') return fail(end.error);
  if (start && end && start > end) return fail('The start date must be on or before the end date.');

  const cropById = new Map(allCrops.map((c) => [c.id, c]));
  const varietyById = new Map((varieties ?? []).map((v) => [v.id, v]));
  const rows = (harvests ?? [])
    .map((h) => {
      const crop =
        h.crop_id != null
          ? cropById.get(h.crop_id)
          : cropById.get(varietyById.get(h.variety_id ?? -1)?.crop_id ?? -1);
      return { h, crop, date: localDate(new Date(h.harvested_at), timeZone) };
    })
    .filter(
      (r) =>
        (!only || r.crop?.id === only.id) &&
        (!start || r.date >= (start as string)) &&
        (!end || r.date <= (end as string))
    )
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.h.id - a.h.id));

  const totals = new Map<
    string,
    { crop: string; unit: string; amount: number; picks: number; lb: number; value: number }
  >();
  for (const { h, crop } of rows) {
    const key = `${crop?.name ?? ''}\u0000${h.unit}`;
    const t = totals.get(key) ?? {
      crop: crop?.name ?? 'Unknown crop',
      unit: h.unit,
      amount: 0,
      picks: 0,
      lb: 0,
      value: 0,
    };
    t.amount += Number(h.weight) || 0;
    t.picks += 1;
    t.lb += harvestLb(h, crop);
    t.value += harvestValue(h, crop);
    totals.set(key, t);
  }
  const unitRank = (u: string) => {
    const i = (HARVEST_UNITS as readonly string[]).indexOf(u);
    return i < 0 ? HARVEST_UNITS.length : i;
  };
  const r3 = (n: number) => Math.round(n * 1000) / 1000;
  const r2 = (n: number) => Math.round(n * 100) / 100;
  return {
    ok: true,
    crop: only?.name ?? null,
    start,
    end,
    count: rows.length,
    total_lb: r3(rows.reduce((s, r) => s + harvestLb(r.h, r.crop), 0)),
    total_value: r2(rows.reduce((s, r) => s + harvestValue(r.h, r.crop), 0)),
    totals: [...totals.values()]
      .sort((a, b) => a.crop.localeCompare(b.crop) || unitRank(a.unit) - unitRank(b.unit))
      .map((t) => ({ ...t, amount: r3(t.amount), lb: r3(t.lb), value: r2(t.value) })),
    harvests: rows.slice(0, HARVESTS_SHOWN).map(({ h, crop, date }) => ({
      id: h.id,
      date,
      crop: crop?.name ?? null,
      variety: h.variety_id != null ? (varietyById.get(h.variety_id)?.name ?? null) : null,
      weight: h.weight,
      unit: h.unit,
      lb: r3(harvestLb(h, crop)),
      value: r2(harvestValue(h, crop)),
      notes: h.notes,
    })),
    shown: Math.min(rows.length, HARVESTS_SHOWN),
  };
}

export const ACTIONS = {
  log_harvest: logHarvest,
  delete_harvest: deleteHarvest,
  complete_queued_spray: completeQueuedSpray,
  delete_queued_spray: deleteQueuedSpray,
  log_spray: logSpray,
  queue_spray: queueSpray,
  adjust_inventory: adjustInventory,
  add_crop: addCrop,
  add_variety: addVariety,
  log_note: logNote,
  get_harvests: getHarvests,
} as const;

export type ActionName = keyof typeof ACTIONS;
