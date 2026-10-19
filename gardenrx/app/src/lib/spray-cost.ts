import { calculateDose } from '@/lib/dose';
import type { SprayEventProduct, TreatmentInventory } from '@/lib/database.types';

/** Convert a container's contents (in its stored unit) to fluid ounces, so we can
 *  derive a $/fl-oz and multiply by a spray's dose. Weight units use an
 *  approximate 1:1 water-equivalent density (g↔mL, oz↔fl oz) — the same basis the
 *  dose calculator uses, so the two cancel cleanly. */
export function bottleToFlOz(unit: string, amount: number): number {
  switch (unit) {
    case 'mL':
      return amount / 29.5735;
    case 'gal':
      return amount * 128;
    case 'qt':
      return amount * 32;
    case 'pt':
      return amount * 16;
    case 'tbsp':
      return amount * 0.5;
    case 'tsp':
      return amount * (1 / 6);
    case 'lb':
      return amount * 16;
    case 'g':
      return amount / 29.5735;
    default:
      return amount; // fl oz / oz
  }
}

/** The shape of an inventory row we can price from. */
export interface PricedInventory {
  unit: string;
  bottle_unit?: string | null;
  bottle_size: number | null;
  quantity?: number | null;
  cost_dollars: number | null;
}

/**
 * Price per fluid ounce of a product, from the size of ONE container (preferred)
 * or the amount on hand. `cost_dollars` is per-container, so the bottle count is
 * intentionally NOT part of this. Returns null when it can't be priced.
 *
 * Critically, the basis is converted from its OWN unit (`bottle_unit` for the
 * bottle size, else `unit`) — skipping that conversion is what made earlier cost
 * estimates wrong by ~30× for products tracked in mL or grams.
 */
export function costPerFlOz(inv: PricedInventory): number | null {
  if (inv.cost_dollars == null) return null;
  const useBottle = inv.bottle_size != null && inv.bottle_size > 0;
  const basis = useBottle ? inv.bottle_size! : (inv.quantity ?? 0);
  if (!basis || basis <= 0) return null;
  const unit = useBottle ? (inv.bottle_unit ?? inv.unit) : inv.unit;
  const flOz = bottleToFlOz(unit, basis);
  if (flOz <= 0) return null;
  return Number(inv.cost_dollars) / flOz;
}

/** Dollar cost of applying `rate` (in `rateUnit`) across `gallons` of mix for this
 *  product. Null when it can't be priced or the rate isn't a foliar tank-mix. */
export function doseCost(
  inv: PricedInventory,
  rate: number,
  rateUnit: string,
  gallons: number
): number | null {
  const perFlOz = costPerFlOz(inv);
  if (perFlOz == null) return null;
  const dose = calculateDose(rate, rateUnit, gallons);
  if (dose.notFoliar) return null;
  return perFlOz * dose.flOz;
}

/**
 * Estimated dollar cost of a single spray event, derived from inventory pricing.
 * Also reports how many of the event's products could be priced, so callers can
 * flag a partial total.
 */
export function sprayEventCost(
  eventProducts: SprayEventProduct[],
  inventoryByProduct: Map<number, TreatmentInventory>,
  volumeGallons: number
): { cost: number; hasCost: boolean; pricedCount: number; productCount: number } {
  let cost = 0;
  let pricedCount = 0;
  for (const ep of eventProducts) {
    if (ep.rate_applied == null) continue;
    const inv = inventoryByProduct.get(ep.product_id);
    if (!inv) continue;
    const c = doseCost(inv, ep.rate_applied, ep.rate_unit, volumeGallons);
    if (c == null) continue;
    cost += c;
    pricedCount += 1;
  }
  return { cost, hasCost: pricedCount > 0, pricedCount, productCount: eventProducts.length };
}
