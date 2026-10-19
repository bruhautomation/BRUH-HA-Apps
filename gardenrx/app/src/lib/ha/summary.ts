/**
 * What Home Assistant is told about the garden.
 *
 * The `gardenrx` integration polls `/api/ha/summary` and turns this into
 * sensors; the Lovelace and Morph cards read those sensors' attributes. It is
 * one derivation, pure over the rows it is handed, so the panel's numbers and
 * the card's cannot come from two different sums — every rule here is the one
 * the panel already uses: `computeCropPhi` for the pre-harvest interval, the
 * harvest tracker's lb conversion and $/lb value, and the inventory list's
 * "% left" over bottle size × bottles.
 */

import type {
  Crop,
  CropGroup,
  CropUse,
  Harvest,
  Product,
  QueuedSpray,
  QueuedSprayCrop,
  QueuedSprayProduct,
  SprayEvent,
  SprayEventCrop,
  SprayEventProduct,
  TreatmentInventory,
  Variety,
} from '@/lib/database.types';
import { buildPhiByProductGroup, computeCropPhi } from '@/lib/phi';

export const SUMMARY_VERSION = 1;
/** "% left" at or below this is low stock — the inventory bar's red band. */
export const LOW_STOCK_PCT = 20;
export const RECENT_HARVESTS = 10;
export const HARVEST_UNITS = ['lb', 'oz', 'kg', 'g', 'ct'] as const;

export interface GardenRows {
  crops: Crop[];
  varieties: Variety[];
  cropGroups: CropGroup[];
  cropUses: CropUse[];
  products: Product[];
  harvests: Harvest[];
  sprayEvents: SprayEvent[];
  sprayEventProducts: SprayEventProduct[];
  sprayEventCrops: SprayEventCrop[];
  queuedSprays: QueuedSpray[];
  queuedSprayProducts: QueuedSprayProduct[];
  queuedSprayCrops: QueuedSprayCrop[];
  inventory: TreatmentInventory[];
}

const round = (n: number, places = 2) => {
  const f = 10 ** places;
  return Math.round(n * f) / f;
};

/** The harvest tracker's conversion. A count is not a weight. */
export function toLb(weight: number, unit: string): number {
  switch (unit) {
    case 'oz':
      return weight / 16;
    case 'kg':
      return weight * 2.20462;
    case 'g':
      return weight / 453.592;
    case 'ct':
      return 0;
    default:
      return weight;
  }
}

/** Pounds a pick represents: weighed, or counted × the crop's average weight each. */
export function harvestLb(h: Pick<Harvest, 'weight' | 'unit'>, crop: Crop | undefined): number {
  const w = Number(h.weight) || 0;
  return h.unit === 'ct' ? w * (Number(crop?.avg_lb_per_count) || 0) : toLb(w, h.unit);
}

export function harvestValue(h: Pick<Harvest, 'weight' | 'unit'>, crop: Crop | undefined): number {
  return harvestLb(h, crop) * (Number(crop?.price_market_per_lb) || 0);
}

/**
 * YYYY-MM-DD in a time zone. Built from parts rather than from a locale's
 * date format, because a Node without full ICU data (Alpine's, by default)
 * formats every locale as en-US and "en-CA" stops meaning ISO.
 */
export function localDate(now: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

const dayMs = (iso: string) => Date.parse(iso.slice(0, 10) + 'T12:00:00Z');

export function buildSummary(rows: GardenRows, now: Date, timeZone: string) {
  const today = localDate(now, timeZone);
  const year = today.slice(0, 4);
  const cropById = new Map(rows.crops.map((c) => [c.id, c]));
  const varietyById = new Map(rows.varieties.map((v) => [v.id, v]));
  const groupById = new Map(rows.cropGroups.map((g) => [g.id, g.name]));
  const brandOf = (id: number) => rows.products.find((p) => p.id === id)?.brand ?? `Product ${id}`;
  const cropOfHarvest = (h: Harvest) =>
    h.crop_id != null
      ? cropById.get(h.crop_id)
      : h.variety_id != null
        ? cropById.get(varietyById.get(h.variety_id)?.crop_id ?? -1)
        : undefined;

  // ── Harvest ──
  const season = rows.harvests.filter((h) =>
    localDate(new Date(h.harvested_at), timeZone).startsWith(year)
  );
  const byCrop = new Map<
    number,
    {
      crop_id: number;
      crop: string;
      lb: number;
      count: number;
      value: number;
      picks: number;
      last_at: string;
    }
  >();
  let totalLb = 0;
  let totalValue = 0;
  for (const h of season) {
    const crop = cropOfHarvest(h);
    const lb = harvestLb(h, crop);
    const value = harvestValue(h, crop);
    totalLb += lb;
    totalValue += value;
    if (!crop) continue;
    const e = byCrop.get(crop.id) ?? {
      crop_id: crop.id,
      crop: crop.name,
      lb: 0,
      count: 0,
      value: 0,
      picks: 0,
      last_at: h.harvested_at,
    };
    e.lb += lb;
    e.value += value;
    e.picks += 1;
    if (h.unit === 'ct') e.count += Number(h.weight) || 0;
    if (h.harvested_at > e.last_at) e.last_at = h.harvested_at;
    byCrop.set(crop.id, e);
  }
  const recent = [...rows.harvests]
    .sort((a, b) => b.harvested_at.localeCompare(a.harvested_at) || b.id - a.id)
    .slice(0, RECENT_HARVESTS)
    .map((h) => {
      const crop = cropOfHarvest(h);
      return {
        id: h.id,
        crop_id: crop?.id ?? null,
        crop: crop?.name ?? null,
        variety: h.variety_id != null ? (varietyById.get(h.variety_id)?.name ?? null) : null,
        weight: Number(h.weight),
        unit: h.unit,
        lb: round(harvestLb(h, crop), 3),
        value: round(harvestValue(h, crop)),
        harvested_at: h.harvested_at,
        notes: h.notes,
      };
    });

  // ── Pre-harvest intervals, per active crop ──
  const phiByProductGroup = buildPhiByProductGroup(rows.cropUses);
  const activeCrops = rows.crops
    .filter((c) => c.is_active)
    .sort((a, b) => a.name.localeCompare(b.name));
  const crops = activeCrops.map((c) => {
    const phi = computeCropPhi(
      c.id,
      c.crop_group_id,
      rows.sprayEvents,
      rows.sprayEventProducts,
      rows.sprayEventCrops,
      phiByProductGroup,
      brandOf,
      now
    );
    return {
      id: c.id,
      name: c.name,
      group: c.crop_group_id != null ? (groupById.get(c.crop_group_id) ?? null) : null,
      phi: phi.active
        ? {
            active: true,
            days_left: phi.daysLeft,
            clear_date: phi.endDate?.toISOString().slice(0, 10) ?? null,
            product: phi.product,
          }
        : { active: false, days_left: 0, clear_date: null, product: null },
      varieties: rows.varieties
        .filter((v) => v.crop_id === c.id)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((v) => ({ id: v.id, name: v.name })),
    };
  });
  const phiActive = crops
    .filter((c) => c.phi.active)
    .map((c) => ({ crop_id: c.id, crop: c.name, ...c.phi }))
    .sort((a, b) => b.days_left - a.days_left);

  // ── Sprays ──
  const todayMs = dayMs(today);
  const past = rows.sprayEvents
    .filter((e) => !isNaN(dayMs(e.date)) && dayMs(e.date) <= todayMs)
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  const describeEvent = (e: SprayEvent) => ({
    id: e.id,
    date: e.date.slice(0, 10),
    days_ago: Math.round((todayMs - dayMs(e.date)) / 86400000),
    notes: e.notes,
    products: rows.sprayEventProducts
      .filter((p) => p.spray_event_id === e.id)
      .map((p) => brandOf(p.product_id)),
    crops: rows.sprayEventCrops
      .filter((c) => c.spray_event_id === e.id)
      .map((c) => cropById.get(c.crop_id)?.name ?? `Crop ${c.crop_id}`),
  });
  const queued = [...rows.queuedSprays]
    .sort(
      (a, b) => (a.planned_date ?? '9999').localeCompare(b.planned_date ?? '9999') || a.id - b.id
    )
    .map((q) => ({
      id: q.id,
      planned_date: q.planned_date,
      notes: q.notes,
      created_at: q.created_at,
      products: rows.queuedSprayProducts
        .filter((p) => p.queued_spray_id === q.id)
        .map((p) => ({
          product_id: p.product_id,
          brand: brandOf(p.product_id),
          rate: p.rate_applied,
          unit: p.rate_unit,
        })),
      crops: rows.queuedSprayCrops
        .filter((c) => c.queued_spray_id === q.id)
        .map((c) => ({
          crop_id: c.crop_id,
          name: cropById.get(c.crop_id)?.name ?? `Crop ${c.crop_id}`,
        })),
    }));

  // ── Inventory ──
  const items = rows.inventory
    .map((inv) => {
      const capacity =
        inv.bottle_size && inv.bottle_size > 0
          ? inv.bottle_size * (inv.bottles && inv.bottles > 0 ? inv.bottles : 1)
          : null;
      const pct = capacity ? Math.min(100, Math.round((inv.quantity / capacity) * 100)) : null;
      return {
        id: inv.id,
        product_id: inv.product_id,
        product: brandOf(inv.product_id),
        quantity: round(Number(inv.quantity) || 0),
        unit: inv.unit,
        pct,
        low: (Number(inv.quantity) || 0) <= 0 || (pct != null && pct <= LOW_STOCK_PCT),
      };
    })
    .sort((a, b) => (a.pct ?? 101) - (b.pct ?? 101) || a.product.localeCompare(b.product));

  return {
    version: SUMMARY_VERSION,
    generated_at: now.toISOString(),
    today,
    harvest: {
      year: Number(year),
      total_lb: round(totalLb),
      total_value: round(totalValue),
      picks: season.length,
      by_crop: [...byCrop.values()]
        .map((e) => ({ ...e, lb: round(e.lb), value: round(e.value) }))
        .sort((a, b) => b.lb - a.lb || b.value - a.value),
      recent,
      units: [...HARVEST_UNITS],
    },
    crops,
    phi: { active_count: phiActive.length, crops: phiActive },
    sprays: {
      last: past.length ? describeEvent(past[0]) : null,
      this_year: past.filter((e) => e.date.startsWith(year)).length,
      recent: past.slice(0, 5).map(describeEvent),
      queued,
    },
    inventory: {
      items,
      low_count: items.filter((i) => i.low).length,
    },
  };
}

export type GardenSummary = ReturnType<typeof buildSummary>;
