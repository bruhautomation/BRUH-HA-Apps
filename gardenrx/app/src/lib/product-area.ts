/**
 * Map each product to the garden area(s) it's labeled for — Orchard / Garden /
 * Landscape — derived from its `crop_uses` (which crop groups it can treat).
 *
 * A product labeled for both fruit trees and vegetables shows up under BOTH
 * Orchard and Garden, so it appears in either filter on the Stock page.
 */

import type { CropUse, CropGroup } from '@/lib/database.types';
import { CATEGORY_ORDER, categoryForGroupName, type CropCategory } from '@/lib/crop-category';

/** product id → ordered list of areas (Orchard, Garden, Landscape). */
export function areasByProduct(
  cropUses: CropUse[],
  cropGroups: CropGroup[]
): Record<number, CropCategory[]> {
  const groupCategory = new Map<number, CropCategory>();
  for (const g of cropGroups) {
    const cat = categoryForGroupName(g.name);
    if (cat) groupCategory.set(g.id, cat);
  }

  const sets = new Map<number, Set<CropCategory>>();
  for (const cu of cropUses) {
    const cat = groupCategory.get(cu.crop_group_id);
    if (!cat) continue;
    let set = sets.get(cu.product_id);
    if (!set) sets.set(cu.product_id, (set = new Set()));
    set.add(cat);
  }

  const out: Record<number, CropCategory[]> = {};
  for (const [productId, set] of sets) {
    out[productId] = CATEGORY_ORDER.filter((c) => set.has(c));
  }
  return out;
}
