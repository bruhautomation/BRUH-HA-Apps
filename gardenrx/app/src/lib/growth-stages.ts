import type { PhenologicalStage } from './database.types';

/** Stage-specific pill colors for consistent rendering across the app */
export const STAGE_COLORS: Record<string, { bg: string; text: string; ring: string }> = {
  dormant: { bg: 'bg-slate-100', text: 'text-slate-600', ring: 'ring-slate-200/60' },
  bud_break: { bg: 'bg-lime-50', text: 'text-lime-700', ring: 'ring-lime-200/60' },
  green_tip: { bg: 'bg-lime-50', text: 'text-lime-700', ring: 'ring-lime-200/60' },
  tight_cluster: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200/50' },
  pink: { bg: 'bg-pink-50', text: 'text-pink-600', ring: 'ring-pink-200/60' },
  bloom: { bg: 'bg-pink-50', text: 'text-pink-700', ring: 'ring-pink-200/60' },
  petal_fall: { bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200/60' },
  fruit_set: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200/50' },
  green_fruit: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200/50' },
  cover_spray: { bg: 'bg-sky-50', text: 'text-sky-700', ring: 'ring-sky-200/60' },
  pre_harvest: { bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200/60' },
  harvest: { bg: 'bg-orange-50', text: 'text-orange-700', ring: 'ring-orange-200/60' },
  post_harvest: { bg: 'bg-slate-100', text: 'text-slate-600', ring: 'ring-slate-200/60' },
};

const DEFAULT_STAGE_COLOR = {
  bg: 'bg-emerald-50',
  text: 'text-emerald-700',
  ring: 'ring-emerald-200/50',
};

export function getStageColor(stage: string) {
  return STAGE_COLORS[stage] ?? DEFAULT_STAGE_COLOR;
}

/**
 * Crop-group-specific growth stages with descriptions and illustrations.
 *
 * Each crop group only shows the stages that are biologically relevant.
 * The stage keys still use the PhenologicalStage enum, but each group
 * maps to a subset with crop-specific descriptions.
 */

export interface StageInfo {
  stage: PhenologicalStage;
  label: string;
  description: string;
  emoji: string;
}

// ── Pome Fruit (Apples, Pears, Quince) ──
// Follows the classic Chapman-Catlin phenology scale
export const POME_FRUIT_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant',
    emoji: '🌑',
    description:
      'Buds tightly closed, no visible swelling. Tree is leafless. Ideal window for dormant oil and copper sprays.',
  },
  {
    stage: 'bud_break',
    label: 'Silver Tip',
    emoji: '🔘',
    description:
      'Bud scales separating, silvery-gray tissue visible at bud tips. First sign of spring activity.',
  },
  {
    stage: 'green_tip',
    label: 'Green Tip',
    emoji: '🌱',
    description:
      'About ½ inch of green leaf tissue emerging beyond bud scales. First scab infection risk begins.',
  },
  {
    stage: 'tight_cluster',
    label: 'Tight Cluster',
    emoji: '🌿',
    description:
      'Individual flower buds visible in a tight cluster but still closed. Leaves unfurling. Key timing for early fungicide.',
  },
  {
    stage: 'pink',
    label: 'Pink / Red Bud',
    emoji: '🌸',
    description:
      'Flower buds showing pink (apple) or white (pear) color, petals still closed. Critical scab and fire blight timing.',
  },
  {
    stage: 'bloom',
    label: 'Full Bloom',
    emoji: '🌺',
    description:
      'King bloom and side flowers open. Active pollination. DO NOT spray insecticides — protect pollinators.',
  },
  {
    stage: 'petal_fall',
    label: 'Petal Fall',
    emoji: '🍃',
    description:
      '75%+ of petals dropped. Calyx closing on fruitlets. Resume insecticide sprays. First cover spray timing.',
  },
  {
    stage: 'fruit_set',
    label: 'Fruit Set',
    emoji: '🫒',
    description: 'Fruitlets visible at 5-8mm. June drop period. Begin regular cover spray program.',
  },
  {
    stage: 'green_fruit',
    label: 'Green Fruit',
    emoji: '🍏',
    description:
      'Fruit enlarging through the summer. Maintain fungicide and insect management on regular intervals.',
  },
  {
    stage: 'harvest',
    label: 'Harvest',
    emoji: '🍎',
    description:
      "Fruit ripening and being picked — early varieties (Ginger Gold, Gala) from late July, late keepers (Goldrush, Pink Lady) into November. Mind each product's pre-harvest interval before picking.",
  },
  {
    stage: 'post_harvest',
    label: 'Post-Harvest',
    emoji: '🍂',
    description:
      'Fruit off the tree, leaves dropping. Good window for a post-harvest copper and a foliar urea at leaf fall. Tree settling into dormancy.',
  },
];

// ── Stone Fruit (Peaches, Cherries, Plums, Apricots, Nectarines) ──
export const STONE_FRUIT_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant',
    emoji: '🌑',
    description:
      'Leaf and flower buds dormant, tree bare. Apply dormant sprays for scale, peach leaf curl, and bacterial diseases.',
  },
  {
    stage: 'bud_break',
    label: 'Bud Swell',
    emoji: '🟤',
    description:
      'Buds visibly swollen, scales separating. Last chance for peach leaf curl spray (copper or chlorothalonil).',
  },
  {
    stage: 'green_tip',
    label: 'Green Calyx',
    emoji: '🌱',
    description: 'Green tissue visible at bud tips. Flower buds distinguishable from leaf buds.',
  },
  {
    stage: 'pink',
    label: 'Pink / Popcorn',
    emoji: '🌸',
    description:
      'Flower petals visible but not yet open, resembling popcorn. Critical brown rot blossom blight timing.',
  },
  {
    stage: 'bloom',
    label: 'Full Bloom',
    emoji: '🌺',
    description: 'Flowers fully open. Active pollination period. No insecticide spraying.',
  },
  {
    stage: 'petal_fall',
    label: 'Shuck Split',
    emoji: '🍃',
    description:
      'Petals fallen, the dried calyx (shuck) splits away from the developing fruitlet. Resume cover sprays.',
  },
  {
    stage: 'fruit_set',
    label: 'Fruit Set',
    emoji: '🫒',
    description:
      'Small fruitlets developing. Thin peaches to 6-8 inch spacing. Begin brown rot and insect cover sprays.',
  },
  {
    stage: 'green_fruit',
    label: 'Fruit Development',
    emoji: '🟢',
    description:
      'Fruit sizing through pit hardening. Maintain regular spray schedule for brown rot, oriental fruit moth, plum curculio.',
  },
  {
    stage: 'harvest',
    label: 'Harvest',
    emoji: '🍑',
    description:
      'Cherries ripen late May–June; peaches and plums June–August. Keep brown rot covered right up to picking and observe pre-harvest intervals.',
  },
  {
    stage: 'post_harvest',
    label: 'Post-Harvest',
    emoji: '🍂',
    description:
      'Crop picked. Renewal-prune if needed, stay ahead of borers, and let the tree harden off toward dormancy.',
  },
];

// ── Small Fruit (Blueberries, Raspberries, Blackberries, Strawberries) ──
export const SMALL_FRUIT_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant',
    emoji: '🌑',
    description:
      'Plants dormant, no active growth. Prune canes/bushes. Apply dormant sprays if needed.',
  },
  {
    stage: 'bud_break',
    label: 'Bud Break',
    emoji: '🟤',
    description:
      'Buds swelling, first green tissue pushing out. Begin mummy berry and anthracnose prevention.',
  },
  {
    stage: 'green_tip',
    label: 'Early Growth',
    emoji: '🌱',
    description: 'New shoots and leaves emerging. Strawberry crowns pushing new growth.',
  },
  {
    stage: 'tight_cluster',
    label: 'Flower Bud',
    emoji: '🌿',
    description:
      'Flower clusters visible but still closed. Critical timing for Botrytis prevention on strawberries.',
  },
  {
    stage: 'bloom',
    label: 'Bloom',
    emoji: '🌺',
    description:
      'Flowers open. Pollinators active. No insecticide spraying. Blueberry flowers are bell-shaped.',
  },
  {
    stage: 'petal_fall',
    label: 'Petal Fall',
    emoji: '🍃',
    description:
      'Flowers fading, small green fruit forming. Resume pest management. Watch for spotted wing drosophila.',
  },
  {
    stage: 'fruit_set',
    label: 'Green Fruit',
    emoji: '🫒',
    description:
      'Berries developing, still hard and green. Maintain disease coverage for anthracnose and mummy berry.',
  },
  {
    stage: 'green_fruit',
    label: 'Fruit Coloring',
    emoji: '🫐',
    description:
      'Fruit beginning to size and show color. Ramp up SWD monitoring. Watch PHI restrictions on late sprays.',
  },
  {
    stage: 'harvest',
    label: 'Harvest',
    emoji: '🫐',
    description:
      'Picking underway — southern highbush blueberries from late May, rabbiteye and blackberries June–July. Watch spotted wing drosophila and respect the short pre-harvest intervals on any spray.',
  },
  {
    stage: 'post_harvest',
    label: 'Post-Harvest',
    emoji: '🍂',
    description:
      'Harvest wrapping up. Prune out spent floricanes, renew the planting, and keep foliage healthy into fall before dormancy.',
  },
];

// ── Grapes ──
// Uses modified Eichhorn-Lorenz (E-L) scale descriptions
export const GRAPE_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant',
    emoji: '🌑',
    description: 'Vines fully dormant, buds winterized. Prune during dormancy. No spray needed.',
  },
  {
    stage: 'bud_break',
    label: 'Bud Break / Woolly Bud',
    emoji: '🟤',
    description:
      'Brown wool visible at bud tips, scales cracking open. Begin early-season disease scouting.',
  },
  {
    stage: 'green_tip',
    label: 'Shoot Growth (1-3 leaves)',
    emoji: '🌱',
    description:
      'First leaves unfolding, shoots 1-4 inches. Begin phomopsis and black rot management.',
  },
  {
    stage: 'tight_cluster',
    label: 'Pre-bloom (shoots 10-12")',
    emoji: '🌿',
    description:
      'Shoots elongated, individual flower clusters visible and separated. Critical timing for downy mildew.',
  },
  {
    stage: 'bloom',
    label: 'Bloom / Capfall',
    emoji: '🌺',
    description:
      'Flower caps (calyptras) shedding, stamens exposed. Critical for botrytis and downy mildew. Pollination underway.',
  },
  {
    stage: 'fruit_set',
    label: 'Fruit Set (BB-size)',
    emoji: '🫒',
    description:
      'Berries at BB-shot size after successful pollination. Begin regular cover spray program.',
  },
  {
    stage: 'green_fruit',
    label: 'Pre-Veraison',
    emoji: '🟢',
    description:
      'Berries growing, still hard and green. Bunch closure period. Maintain powdery mildew and black rot coverage.',
  },
  {
    stage: 'harvest',
    label: 'Harvest',
    emoji: '🍇',
    description:
      'Veraison through ripe — bunch grapes August–September, muscadines September–October. Hold late-season fungicides per their pre-harvest intervals.',
  },
  {
    stage: 'post_harvest',
    label: 'Post-Harvest',
    emoji: '🍂',
    description:
      'Fruit picked, leaves senescing. Vines storing reserves ahead of dormant-season pruning.',
  },
];

// ── Cucurbits (Squash, Melons, Cucumbers, Pumpkins) ──
export const CUCURBIT_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Seed / Pre-plant',
    emoji: '🌑',
    description:
      'Seeds not yet planted or just planted. Prepare soil, plan disease management strategy.',
  },
  {
    stage: 'bud_break',
    label: 'Emergence',
    emoji: '🌱',
    description:
      'Cotyledons (seed leaves) emerging from soil. Protect from damping off and cucumber beetles.',
  },
  {
    stage: 'green_tip',
    label: 'Vine Growth',
    emoji: '🌿',
    description:
      'True leaves developing, vines beginning to run. Start fungicide program for downy and powdery mildew.',
  },
  {
    stage: 'bloom',
    label: 'Flowering',
    emoji: '🌺',
    description:
      'Male and female flowers open. Pollinator activity critical for fruit set. Avoid insecticides during active bloom.',
  },
  {
    stage: 'fruit_set',
    label: 'Fruit Set',
    emoji: '🫒',
    description:
      'Small fruit developing after pollination. Maintain disease coverage. Scout for vine borers and squash bugs.',
  },
  {
    stage: 'green_fruit',
    label: 'Fruit Development',
    emoji: '🎃',
    description:
      'Fruit sizing and maturing. Continue spray program. Watch PHI as harvest approaches.',
  },
];

// ── Ornamentals (Roses, Hydrangeas, Flowering Shrubs, etc.) ──
export const ORNAMENTAL_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant',
    emoji: '🌑',
    description:
      'Plants dormant, no active growth. Ideal for dormant oil sprays on roses. Prune hybrid teas and floribundas.',
  },
  {
    stage: 'bud_break',
    label: 'Bud Break',
    emoji: '🟤',
    description:
      'New growth emerging from buds. Red-tinged new leaves on roses. Begin black spot prevention.',
  },
  {
    stage: 'green_tip',
    label: 'Active Growth',
    emoji: '🌿',
    description:
      'Leaves expanding, shoots elongating. Rose canes growing vigorously. Start regular fungicide program.',
  },
  {
    stage: 'bloom',
    label: 'Bloom',
    emoji: '🌹',
    description:
      'Flowers open. Peak display period. Avoid insecticides if pollinators active. Deadhead spent blooms.',
  },
  {
    stage: 'petal_fall',
    label: 'Post-Bloom',
    emoji: '🍃',
    description:
      'Flowers fading. Resume insecticide sprays if needed. Continue fungicide for black spot and powdery mildew.',
  },
  {
    stage: 'green_fruit',
    label: 'Summer Growth',
    emoji: '🌿',
    description:
      'Active vegetative growth. Roses may rebloom. Maintain disease and pest management through the season.',
  },
];

// ── Turf Grass ──
export const TURF_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant / Winter',
    emoji: '🌑',
    description:
      'Grass dormant and brown (warm-season) or slow-growing (cool-season). Apply pre-emergents before soil hits 55°F.',
  },
  {
    stage: 'bud_break',
    label: 'Spring Green-Up',
    emoji: '🌱',
    description:
      'Grass breaking dormancy, greening up. Apply pre-emergent crabgrass control. Begin mowing when growth resumes.',
  },
  {
    stage: 'green_tip',
    label: 'Active Growth',
    emoji: '🌿',
    description:
      'Full active growth period. Post-emergent weed control window. Fertilize warm-season grasses. Watch for fungal disease.',
  },
  {
    stage: 'bloom',
    label: 'Peak Season',
    emoji: '🟢',
    description:
      'Maximum growth rate. Regular mowing. Watch for brown patch, dollar spot. Grub preventive window (June-July).',
  },
  {
    stage: 'green_fruit',
    label: 'Late Season',
    emoji: '🍂',
    description:
      'Growth slowing. Fall pre-emergent for winter annuals (cool-season). Overseed fescue (Sept). Bermuda entering dormancy.',
  },
];

// ── Orchard Floor ──
export const ORCHARD_FLOOR_STAGES: StageInfo[] = [
  {
    stage: 'dormant',
    label: 'Dormant Season',
    emoji: '🌑',
    description:
      'Trees dormant. Apply pre-emergent herbicides to clean ground. Chateau, Prowl H2O, Surflan before weed germination.',
  },
  {
    stage: 'bud_break',
    label: 'Early Spring',
    emoji: '🌱',
    description:
      'Weeds germinating. Burndown with glyphosate or glufosinate for emerged weeds. Pre-emergent still effective if soil not yet warm.',
  },
  {
    stage: 'green_tip',
    label: 'Growing Season',
    emoji: '🌿',
    description:
      'Active weed growth. Post-emergent grass killers (Poast, Fusilade) safe over trees. Directed sprays for broadleaf.',
  },
  {
    stage: 'green_fruit',
    label: 'Mid-Late Season',
    emoji: '🟢',
    description:
      'Maintain weed-free strip under trees. Spot-treat escapes. Second pre-emergent application if needed.',
  },
];

// ── Lookup by crop group name ──
export const STAGES_BY_GROUP: Record<string, StageInfo[]> = {
  'Pome Fruit': POME_FRUIT_STAGES,
  'Stone Fruit': STONE_FRUIT_STAGES,
  Berries: SMALL_FRUIT_STAGES,
  Grapes: GRAPE_STAGES,
  Cucurbits: CUCURBIT_STAGES,
  Ornamentals: ORNAMENTAL_STAGES,
  'Turf Grass': TURF_STAGES,
  'Orchard Floor': ORCHARD_FLOOR_STAGES,
  Nightshades: [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description:
        'Seeds started indoors or awaiting transplant. Plan disease management strategy.',
    },
    {
      stage: 'bud_break',
      label: 'Transplant / Emergence',
      emoji: '🌱',
      description:
        'Seedlings transplanted or direct-seeded. Protect from cutworms and flea beetles.',
    },
    {
      stage: 'green_tip',
      label: 'Vegetative Growth',
      emoji: '🌿',
      description:
        'Active vine/plant growth. Begin fungicide program for early blight. Scout for Colorado potato beetle.',
    },
    {
      stage: 'bloom',
      label: 'Flowering',
      emoji: '🌺',
      description:
        'Flowers open. Fruit setting. Continue disease prevention. Monitor for hornworms.',
    },
    {
      stage: 'fruit_set',
      label: 'Fruit Development',
      emoji: '🍅',
      description:
        'Fruit sizing and ripening. Watch for late blight, blossom end rot. Maintain spray schedule.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🫑',
      description: 'Harvesting. Observe PHI. Continue scouting for late-season diseases.',
    },
  ],
  Brassicas: [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description: 'Plan spring or fall planting. Cool-season crop.',
    },
    {
      stage: 'bud_break',
      label: 'Transplant',
      emoji: '🌱',
      description: 'Transplants set out. Protect from cutworms and flea beetles immediately.',
    },
    {
      stage: 'green_tip',
      label: 'Head Formation',
      emoji: '🥦',
      description:
        'Leaves expanding, heads forming. Scout for cabbage loopers, imported cabbageworm.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🥬',
      description:
        'Heads/leaves at harvest size. Observe PHI. Fall crop continues through light frost.',
    },
  ],
  'Leafy Greens': [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description: 'Prepare beds. Direct seed or start transplants.',
    },
    {
      stage: 'bud_break',
      label: 'Emergence',
      emoji: '🌱',
      description: 'Seedlings emerging. Thin as needed. Watch for flea beetles.',
    },
    {
      stage: 'green_tip',
      label: 'Growth',
      emoji: '🥬',
      description: 'Leaves expanding. Scout for aphids, slugs. Begin harvest of outer leaves.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🥗',
      description: 'Continuous harvest. Succession plant for extended season.',
    },
  ],
  Legumes: [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description:
        'Inoculate seeds with rhizobium if not previously grown. Direct seed after frost.',
    },
    {
      stage: 'bud_break',
      label: 'Emergence',
      emoji: '🌱',
      description: 'Seedlings emerging. Watch for cutworms and bean leaf beetles.',
    },
    {
      stage: 'green_tip',
      label: 'Vine Growth',
      emoji: '🌿',
      description:
        'Vines growing. Provide supports for pole types. Scout for Mexican bean beetles.',
    },
    {
      stage: 'bloom',
      label: 'Flowering',
      emoji: '🌺',
      description:
        'Flowers open. Avoid insecticides to protect pollinators. Monitor for stink bugs.',
    },
    {
      stage: 'fruit_set',
      label: 'Pod Development',
      emoji: '🫛',
      description: 'Pods forming and filling. Begin harvest when pods snap cleanly.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🫘',
      description: 'Continuous harvest. Pick regularly to encourage production.',
    },
  ],
  Alliums: [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description: 'Plant garlic in October. Start onion seeds January. Prepare beds.',
    },
    {
      stage: 'bud_break',
      label: 'Emergence',
      emoji: '🌱',
      description: 'Green shoots emerging. Begin thrips scouting.',
    },
    {
      stage: 'green_tip',
      label: 'Bulb Growth',
      emoji: '🧅',
      description:
        'Tops growing, bulbs sizing. Apply fungicide for purple blotch and downy mildew if wet.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🧄',
      description:
        'Tops falling over (onions) or lower leaves browning (garlic). Cure after harvest.',
    },
  ],
  'Root Vegetables': [
    {
      stage: 'dormant',
      label: 'Pre-plant',
      emoji: '🌑',
      description: 'Prepare loose, stone-free soil. Direct seed in spring or fall.',
    },
    {
      stage: 'bud_break',
      label: 'Emergence',
      emoji: '🌱',
      description: 'Seedlings emerging. Thin to proper spacing. Watch for flea beetles.',
    },
    {
      stage: 'green_tip',
      label: 'Root Growth',
      emoji: '🥕',
      description:
        'Tops growing, roots sizing underground. Scout for carrot rust fly, flea beetles.',
    },
    {
      stage: 'green_fruit',
      label: 'Harvest',
      emoji: '🥕',
      description:
        'Roots at target size. Harvest before ground freezes. Fall carrots sweetened by frost.',
    },
  ],
  Herbs: [
    {
      stage: 'dormant',
      label: 'Dormant / Indoor',
      emoji: '🌑',
      description: 'Perennial herbs dormant. Start basil and tender herbs indoors.',
    },
    {
      stage: 'bud_break',
      label: 'Spring Growth',
      emoji: '🌱',
      description: 'New growth emerging on perennials. Transplant tender herbs after frost.',
    },
    {
      stage: 'green_tip',
      label: 'Active Growth',
      emoji: '🌿',
      description:
        'Harvest regularly to encourage bushiness. Most herbs need minimal pest management.',
    },
    {
      stage: 'bloom',
      label: 'Flowering',
      emoji: '🌸',
      description:
        'Flowers attract pollinators. Pinch basil flowers to extend leaf harvest. Let some flower for beneficial insects.',
    },
    {
      stage: 'green_fruit',
      label: 'Late Season',
      emoji: '🍂',
      description: 'Harvest and dry/freeze for winter. Take cuttings of tender herbs before frost.',
    },
  ],
};

// Fallback for unknown groups
export const DEFAULT_STAGES: StageInfo[] = [
  { stage: 'dormant', label: 'Dormant', emoji: '🌑', description: 'No active growth.' },
  { stage: 'bud_break', label: 'Emergence', emoji: '🌱', description: 'First growth visible.' },
  {
    stage: 'green_tip',
    label: 'Vegetative Growth',
    emoji: '🌿',
    description: 'Active leaf and shoot growth.',
  },
  { stage: 'bloom', label: 'Bloom', emoji: '🌺', description: 'Flowers open.' },
  { stage: 'fruit_set', label: 'Fruit Set', emoji: '🫒', description: 'Fruit or seed developing.' },
  {
    stage: 'green_fruit',
    label: 'Maturation',
    emoji: '🟢',
    description: 'Fruit or plant maturing.',
  },
];
