/**
 * Crop icon key resolver — maps a crop name (or its group) to a stable icon key.
 * The neutral, on-theme crop glyphs live in crop-glyph.tsx (the restyle uses
 * neutral avatars per the color rule); this module is just the name→key logic
 * shared by that resolver.
 *
 * Resolution order: exact crop name → known alias → singular/plural nudge →
 * crop-group fallback → generic sprout.
 */

// crop name (slug) → icon key
const NAME_TO_KEY: Record<string, string> = {
  apples: 'apple',
  apple: 'apple',
  crabapples: 'apple',
  pears: 'pear',
  pear: 'pear',
  'asian-pears': 'pear',
  quince: 'pear',
  cherries: 'cherry',
  cherry: 'cherry',
  peaches: 'peach',
  peach: 'peach',
  nectarines: 'peach',
  apricots: 'peach',
  plums: 'peach',
  blueberries: 'blueberry',
  honeyberries: 'blueberry',
  blackberries: 'blackberry',
  raspberries: 'raspberry',
  currants: 'raspberry',
  elderberries: 'blackberry',
  gooseberries: 'grape',
  strawberries: 'strawberry',
  grapes: 'grape',
  'muscadine-grapes': 'grape',
  'table-grapes': 'grape',
  cantaloupe: 'melon',
  melons: 'melon',
  watermelon: 'watermelon',
  pumpkins: 'squash',
  gourds: 'squash',
  cucumbers: 'cucumber',
  zucchini: 'zucchini',
  squash: 'squash',
  tomatoes: 'tomato',
  tomatillos: 'tomato',
  peppers: 'pepper',
  eggplant: 'pepper',
  kale: 'kale',
  'collard-greens': 'kale',
  'mustard-greens': 'kale',
  cabbage: 'lettuce',
  broccoli: 'kale',
  cauliflower: 'kale',
  lettuce: 'lettuce',
  spinach: 'lettuce',
  arugula: 'lettuce',
  'swiss-chard': 'kale',
  basil: 'basil',
  cilantro: 'basil',
  parsley: 'basil',
  mint: 'basil',
  oregano: 'basil',
  sage: 'basil',
  dill: 'rosemary',
  thyme: 'rosemary',
  rosemary: 'rosemary',
  lavender: 'rosemary',
  pawpaws: 'pawpaw',
  figs: 'pawpaw',
  persimmons: 'peach',
  'knock-out-roses': 'rose',
  'hybrid-tea-roses': 'rose',
  'climbing-roses': 'rose',
  'shrub-roses': 'rose',
  'floribunda-roses': 'rose',
  'david-austin-roses': 'rose',
  roses: 'rose',
  peonies: 'peony',
  dahlias: 'peony',
  camellias: 'peony',
  loropetalum: 'loropetalum',
  azaleas: 'loropetalum',
  rhododendrons: 'loropetalum',
  'bermuda-grass': 'grass',
  'zoysia-grass': 'grass',
  'tall-fescue': 'grass',
  'centipede-grass': 'grass',
  'st-augustine-grass': 'grass',
  'kentucky-bluegrass': 'grass',
  'sweet-corn': 'grass',
  hydrangeas: 'peony',
};

// crop-group name → icon key (fallback when the crop itself isn't mapped)
const GROUP_TO_KEY: Record<string, string> = {
  'Pome Fruit': 'apple',
  'Stone Fruit': 'cherry',
  Berries: 'blueberry',
  Grapes: 'grape',
  Cucurbits: 'melon',
  Nightshades: 'tomato',
  Brassicas: 'kale',
  'Leafy Greens': 'lettuce',
  Legumes: 'sprout',
  Alliums: 'sprout',
  'Root Vegetables': 'sprout',
  Herbs: 'basil',
  Ornamentals: 'rose',
  'Turf Grass': 'grass',
  'Orchard Floor': 'grass',
  'Structures & Premise': 'sprout',
};

// icon key → a representative, true-to-life color for the crop glyph.
const ICON_COLORS: Record<string, string> = {
  apple: '#d64545',
  pear: '#a3b557',
  cherry: '#b3303f',
  peach: '#e8915b',
  blueberry: '#5a76c4',
  blackberry: '#5d4571',
  raspberry: '#cc4d77',
  grape: '#7c5bbf',
  strawberry: '#df4659',
  melon: '#e59b4a',
  watermelon: '#e35d72',
  cucumber: '#5a9a4f',
  zucchini: '#4f8a43',
  squash: '#dd9130',
  tomato: '#df4b3a',
  pepper: '#dd5232',
  kale: '#3f7a52',
  lettuce: '#7cb45c',
  basil: '#4f9a55',
  rosemary: '#5e8f74',
  rose: '#df6f9c',
  peony: '#e58fb0',
  loropetalum: '#a85fbf',
  grass: '#6aa84f',
  pawpaw: '#b6a24c',
  sprout: '#6aa84f',
};

/** Representative color for a crop's icon (red apple, blue blueberries, …). */
export function cropIconColor(name: string, group?: string | null): string {
  return ICON_COLORS[resolveCropIconKey(name, group)] ?? ICON_COLORS.sprout;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function resolveCropIconKey(name: string, group?: string | null): string {
  const slug = slugify(name);
  if (NAME_TO_KEY[slug]) return NAME_TO_KEY[slug];
  // singular/plural nudge
  if (slug.endsWith('s') && NAME_TO_KEY[slug.slice(0, -1)]) return NAME_TO_KEY[slug.slice(0, -1)];
  if (NAME_TO_KEY[`${slug}s`]) return NAME_TO_KEY[`${slug}s`];
  if (group && GROUP_TO_KEY[group]) return GROUP_TO_KEY[group];
  return 'sprout';
}
