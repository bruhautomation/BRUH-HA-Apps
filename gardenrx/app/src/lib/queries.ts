/**
 * Shared Supabase query functions.
 *
 * Consolidates repeated `.from()` calls across server pages
 * into reusable, type-safe functions with standardized error handling.
 */

import { createClient } from '@/lib/db/server';
import type {
  Crop,
  Variety,
  VarietyStage,
  Product,
  ProductIngredient,
  ActiveIngredient,
  CropGroup,
  CropUse,
  TankMixRule,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
  QueuedSpray,
  QueuedSprayProduct,
  QueuedSprayCrop,
  TreatmentInventory,
  AppSettings,
} from '@/lib/database.types';
import { DEFAULT_SETTINGS } from '@/lib/settings';

// ── Helpers ──

/** Extract data from a Supabase response, defaulting to empty array on error. */
function rows<T>(result: { data: T[] | null }): T[] {
  return (result.data ?? []) as T[];
}

// ── Appearance / UI preferences (singleton) ──

export async function fetchAppSettings(): Promise<AppSettings> {
  try {
    const supabase = await createClient();
    const { data } = await supabase.from('app_settings').select('*').eq('id', 1).maybeSingle();
    return data ? { ...DEFAULT_SETTINGS, ...data } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

// ── Core reference data ──

export async function fetchCrops(options?: { activeOnly?: boolean }) {
  const supabase = await createClient();
  let query = supabase.from('crops').select('*').order('name');
  if (options?.activeOnly) query = query.eq('is_active', true);
  return rows<Crop>(await query);
}

export async function fetchVarieties() {
  const supabase = await createClient();
  return rows<Variety>(await supabase.from('varieties').select('*').order('name'));
}

export async function fetchVarietyStages() {
  const supabase = await createClient();
  return rows<VarietyStage>(await supabase.from('variety_stages').select('*'));
}

export async function fetchProducts(options?: { ordered?: boolean }) {
  const supabase = await createClient();
  let query = supabase.from('products').select('*');
  if (options?.ordered !== false) query = query.order('brand');
  return rows<Product>(await query);
}

export async function fetchProductIngredients() {
  const supabase = await createClient();
  return rows<ProductIngredient>(await supabase.from('product_ingredients').select('*'));
}

export async function fetchActiveIngredients() {
  const supabase = await createClient();
  return rows<ActiveIngredient>(
    await supabase.from('active_ingredients').select('*').order('name')
  );
}

export async function fetchCropGroups() {
  const supabase = await createClient();
  return rows<CropGroup>(await supabase.from('crop_groups').select('*').order('name'));
}

export async function fetchCropUses() {
  const supabase = await createClient();
  return rows<CropUse>(await supabase.from('crop_uses').select('*'));
}

export async function fetchTankMixRules() {
  const supabase = await createClient();
  return rows<TankMixRule>(await supabase.from('tank_mix_rules').select('*'));
}

// ── Spray history ──

export async function fetchSprayHistory() {
  const supabase = await createClient();
  const [events, eventProducts, eventCrops] = await Promise.all([
    supabase.from('spray_events').select('*').order('date', { ascending: false }),
    supabase.from('spray_event_products').select('*'),
    supabase.from('spray_event_crops').select('*'),
  ]);
  return {
    sprayEvents: rows<SprayEvent>(events),
    sprayEventProducts: rows<SprayEventProduct>(eventProducts),
    sprayEventCrops: rows<SprayEventCrop>(eventCrops),
  };
}

// ── Queued sprays ──

export async function fetchQueuedSprays() {
  const supabase = await createClient();
  const [sprays, products, crops] = await Promise.all([
    supabase.from('queued_sprays').select('*').order('created_at', { ascending: false }),
    supabase.from('queued_spray_products').select('*'),
    supabase.from('queued_spray_crops').select('*'),
  ]);
  return {
    queuedSprays: rows<QueuedSpray>(sprays),
    queuedSprayProducts: rows<QueuedSprayProduct>(products),
    queuedSprayCrops: rows<QueuedSprayCrop>(crops),
  };
}

// ── Phenology calendar ──

export async function fetchPhenologyCalendar() {
  const supabase = await createClient();
  return (await supabase.from('phenology_calendar').select('*')).data ?? [];
}

// ── Inventory ──

export async function fetchInventory() {
  const supabase = await createClient();
  return rows<TreatmentInventory>(await supabase.from('treatment_inventory').select('*'));
}

// ── Ingredient map builder ──

/**
 * Build a lookup map from product ID → its active ingredients.
 * This pattern is repeated in 3+ pages.
 *
 * Ingredients are indexed by id up front so this stays O(n) instead of doing a
 * linear `.find()` per join row (the catalog has ~250 products).
 */
export function buildIngredientMap(
  productIngredients: ProductIngredient[],
  activeIngredients: ActiveIngredient[]
): Map<number, ActiveIngredient[]> {
  const byId = new Map(activeIngredients.map((ai) => [ai.id, ai] as const));
  const map = new Map<number, ActiveIngredient[]>();
  for (const pi of productIngredients) {
    const ingredient = byId.get(pi.ingredient_id);
    if (!ingredient) continue;
    const existing = map.get(pi.product_id);
    if (existing) existing.push(ingredient);
    else map.set(pi.product_id, [ingredient]);
  }
  return map;
}

/**
 * Build ingredient map as a serializable Record (for passing to client components).
 */
export function buildIngredientRecord(
  productIngredients: ProductIngredient[],
  activeIngredients: ActiveIngredient[]
): Record<number, ActiveIngredient[]> {
  return Object.fromEntries(buildIngredientMap(productIngredients, activeIngredients));
}
