import type { Crop, CropGroup } from '@/lib/database.types';

/** Top-level garden locations the crops are organized under. */
export const CATEGORY_ORDER = ['Orchard', 'Garden', 'Landscape'] as const;
export type CropCategory = (typeof CATEGORY_ORDER)[number];

const GROUP_CATEGORY: Record<string, CropCategory> = {
  'Pome Fruit': 'Orchard',
  'Stone Fruit': 'Orchard',
  Berries: 'Orchard',
  Grapes: 'Orchard',
  Cucurbits: 'Garden',
  Nightshades: 'Garden',
  Brassicas: 'Garden',
  'Leafy Greens': 'Garden',
  Legumes: 'Garden',
  Alliums: 'Garden',
  'Root Vegetables': 'Garden',
  Herbs: 'Garden',
  Ornamentals: 'Landscape',
  'Turf Grass': 'Landscape',
  'Orchard Floor': 'Landscape',
  'Structures & Premise': 'Landscape',
};
// Fruit crops that carry no crop_group still belong in the orchard.
const ORCHARD_NONGROUP = new Set(['Figs', 'Persimmons', 'Pawpaws', 'Mulberries', 'Jujube']);

export function categoryForCrop(crop: { name: string }, groupName: string | null): CropCategory {
  if (groupName && GROUP_CATEGORY[groupName]) return GROUP_CATEGORY[groupName];
  return ORCHARD_NONGROUP.has(crop.name) ? 'Orchard' : 'Garden';
}

/** Map a crop-group *name* straight to its garden area, or null if unmapped. */
export function categoryForGroupName(groupName: string | null | undefined): CropCategory | null {
  return groupName ? (GROUP_CATEGORY[groupName] ?? null) : null;
}

/** Group crops into Orchard / Garden / Landscape order, crops sorted by name. */
export function cropsByCategory(
  crops: Crop[],
  cropGroups: CropGroup[]
): { category: CropCategory; crops: Crop[] }[] {
  const groupName = new Map(cropGroups.map((g) => [g.id, g.name]));
  const map = new Map<CropCategory, Crop[]>();
  for (const c of crops) {
    const gname = c.crop_group_id ? (groupName.get(c.crop_group_id) ?? null) : null;
    const cat = categoryForCrop(c, gname);
    (map.get(cat) ?? map.set(cat, []).get(cat)!).push(c);
  }
  return CATEGORY_ORDER.filter((cat) => map.has(cat)).map((cat) => ({
    category: cat,
    crops: map
      .get(cat)!
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name)),
  }));
}
