/**
 * Pre-harvest interval (PHI) status for a crop, computed from logged sprays +
 * the product↔crop-group PHI in `crop_uses`. This is the same rule the Harvest
 * tracker uses (spray date + phi_days), evaluated against "now" so Today / Crops
 * can show "do not harvest" without reimplementing the math.
 */

import type { SprayEvent, SprayEventProduct, SprayEventCrop, CropUse } from '@/lib/database.types';

export interface CropPhi {
  /** The crop has at least one PHI-bearing spray on record. */
  applies: boolean;
  /** Currently within a pre-harvest interval (do not harvest). */
  active: boolean;
  /** Days until the longest-running PHI clears (0 when not active). */
  daysLeft: number;
  /** Date the PHI clears. */
  endDate: Date | null;
  /** Brand driving the longest-running PHI. */
  product: string | null;
  /** Date the driving spray was applied. */
  appliedDate: Date | null;
}

const NONE: CropPhi = {
  applies: false,
  active: false,
  daysLeft: 0,
  endDate: null,
  product: null,
  appliedDate: null,
};

export function buildPhiByProductGroup(cropUses: CropUse[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const cu of cropUses) {
    if (cu.phi_days != null && cu.phi_days > 0) {
      m.set(`${cu.product_id}:${cu.crop_group_id}`, cu.phi_days);
    }
  }
  return m;
}

const dayMs = (iso: string) => Date.parse(iso.slice(0, 10) + 'T12:00:00Z');

export function computeCropPhi(
  cropId: number,
  cropGroupId: number | null,
  sprayEvents: SprayEvent[],
  sprayEventProducts: SprayEventProduct[],
  sprayEventCrops: SprayEventCrop[],
  phiByProductGroup: Map<string, number>,
  productBrand: (id: number) => string,
  now: Date
): CropPhi {
  if (cropGroupId == null) return NONE;
  const todayMs = dayMs(now.toISOString());
  const eventIds = new Set(
    sprayEventCrops.filter((ec) => ec.crop_id === cropId).map((ec) => ec.spray_event_id)
  );
  if (eventIds.size === 0) return NONE;

  let sawPhi = false;
  let worst: CropPhi = NONE;
  for (const ev of sprayEvents) {
    if (!eventIds.has(ev.id)) continue;
    const sDay = dayMs(ev.date);
    if (isNaN(sDay) || sDay > todayMs) continue;
    for (const ep of sprayEventProducts) {
      if (ep.spray_event_id !== ev.id) continue;
      const phi = phiByProductGroup.get(`${ep.product_id}:${cropGroupId}`);
      if (phi == null || phi <= 0) continue;
      sawPhi = true;
      const elapsed = Math.round((todayMs - sDay) / 86400000);
      if (elapsed < phi) {
        const daysLeft = phi - elapsed;
        if (!worst.active || daysLeft > worst.daysLeft) {
          worst = {
            applies: true,
            active: true,
            daysLeft,
            endDate: new Date(sDay + phi * 86400000),
            product: productBrand(ep.product_id),
            appliedDate: new Date(sDay),
          };
        }
      }
    }
  }
  if (worst.active) return worst;
  return { ...NONE, applies: sawPhi };
}
