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

export type ActionResult = { ok: true; [k: string]: unknown } | { ok: false; error: string };

const fail = (error: string): ActionResult => ({ ok: false, error });
const norm = (s: string) => s.trim().toLowerCase();

function resolveCrop(crops: Crop[], ref: unknown): Crop | string {
  if (typeof ref === 'number' || (typeof ref === 'string' && /^\d+$/.test(ref.trim()))) {
    return crops.find((c) => c.id === Number(ref)) ?? `No crop has id ${ref}.`;
  }
  if (typeof ref !== 'string' || !ref.trim()) return 'Say which crop was harvested.';
  const exact = crops.filter((c) => norm(c.name) === norm(ref));
  if (exact.length === 1) return exact[0];
  const partial = crops.filter((c) => norm(c.name).includes(norm(ref)));
  if (partial.length === 1) return partial[0];
  if (partial.length > 1) return `"${ref}" could be ${partial.map((c) => c.name).join(' or ')}.`;
  return `No crop is called "${ref}".`;
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

export async function completeQueuedSpray(
  db: DbClient,
  input: Record<string, unknown>,
  now: Date,
  timeZone: string
): Promise<ActionResult> {
  const id = Number(input.id);
  if (!Number.isInteger(id) || id <= 0) return fail('Say which queued spray was done by its id.');
  const gallonsIn = input.volume_gallons;
  const gallons =
    gallonsIn === undefined || gallonsIn === null || gallonsIn === ''
      ? SPRAYER.gallons
      : Number(gallonsIn);
  if (!Number.isFinite(gallons) || gallons <= 0)
    return fail('The sprayer volume must be a number above zero.');

  const { data: queued } = await db.from('queued_sprays').select('*').eq('id', id).maybeSingle();
  if (!queued) return fail(`No queued spray has id ${id} — it may already have been logged.`);
  const [{ data: qProducts }, { data: qCrops }] = await Promise.all([
    db.from('queued_spray_products').select('*').eq('queued_spray_id', id),
    db.from('queued_spray_crops').select('*').eq('queued_spray_id', id),
  ]);
  const products = qProducts ?? [];
  const cropIds = (qCrops ?? []).map((c) => c.crop_id);

  const date = input.date ? String(input.date) : localDate(now, timeZone);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return fail('The date must be YYYY-MM-DD.');

  const { data: event, error } = await db
    .from('spray_events')
    .insert({ date, notes: queued.notes, volume_gallons: gallons })
    .select()
    .single();
  if (error || !event)
    return fail(`The spray was not logged: ${error?.message ?? 'no row came back'}.`);

  const writes = await Promise.all([
    ...products.map((p) =>
      db.from('spray_event_products').insert({
        spray_event_id: event.id,
        product_id: p.product_id,
        rate_applied: p.rate_applied,
        rate_unit: p.rate_unit,
      })
    ),
    ...cropIds.map((crop_id) =>
      db.from('spray_event_crops').insert({ spray_event_id: event.id, crop_id })
    ),
  ]);
  if (writes.some((w) => w.error)) {
    // The panel's rollback: a spray logged without its products is worse than none.
    await db.from('spray_events').delete().eq('id', event.id);
    return fail('The spray was not logged: its products or crops could not be saved.');
  }
  await db.from('queued_sprays').delete().eq('id', id);

  // Best-effort, exactly as the planner's applyPostLogSideEffects: the spray is
  // logged whether or not the stock could be adjusted.
  const deducted: string[] = [];
  for (const p of products) {
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

  return {
    ok: true,
    spray_event_id: event.id,
    date,
    products: products.length,
    crops: cropIds.length,
    deducted,
  };
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

export const ACTIONS = {
  log_harvest: logHarvest,
  delete_harvest: deleteHarvest,
  complete_queued_spray: completeQueuedSpray,
  delete_queued_spray: deleteQueuedSpray,
} as const;

export type ActionName = keyof typeof ACTIONS;
