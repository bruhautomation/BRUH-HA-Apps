// Comprehensive crop catalog for the "Add Crop" picker
// cropGroup maps to crop_groups.name in the database

export interface CatalogEntry {
  name: string;
  cropGroup: string | null;
  emoji: string;
}

export const CROP_CATALOG: CatalogEntry[] = [
  // ── Tree Fruit ──
  { name: 'Apples', cropGroup: 'Pome Fruit', emoji: '🍎' },
  { name: 'Pears', cropGroup: 'Pome Fruit', emoji: '🍐' },
  { name: 'Asian Pears', cropGroup: 'Pome Fruit', emoji: '🍐' },
  { name: 'Crabapples', cropGroup: 'Pome Fruit', emoji: '🍎' },
  { name: 'Quince', cropGroup: 'Pome Fruit', emoji: '🍐' },
  { name: 'Peaches', cropGroup: 'Stone Fruit', emoji: '🍑' },
  { name: 'Nectarines', cropGroup: 'Stone Fruit', emoji: '🍑' },
  { name: 'Plums', cropGroup: 'Stone Fruit', emoji: '🟣' },
  { name: 'Cherries', cropGroup: 'Stone Fruit', emoji: '🍒' },
  { name: 'Apricots', cropGroup: 'Stone Fruit', emoji: '🍑' },
  { name: 'Figs', cropGroup: null, emoji: '🫒' },
  { name: 'Persimmons', cropGroup: null, emoji: '🟠' },
  { name: 'Pawpaws', cropGroup: null, emoji: '🟢' },
  { name: 'Mulberries', cropGroup: null, emoji: '🫐' },
  { name: 'Jujube', cropGroup: null, emoji: '🔴' },

  // ── Small Fruit & Berries ──
  { name: 'Blueberries', cropGroup: 'Berries', emoji: '🫐' },
  { name: 'Raspberries', cropGroup: 'Berries', emoji: '🔴' },
  { name: 'Blackberries', cropGroup: 'Berries', emoji: '⚫' },
  { name: 'Strawberries', cropGroup: 'Berries', emoji: '🍓' },
  { name: 'Gooseberries', cropGroup: 'Berries', emoji: '🟢' },
  { name: 'Currants', cropGroup: 'Berries', emoji: '🔴' },
  { name: 'Elderberries', cropGroup: 'Berries', emoji: '🟣' },
  { name: 'Cranberries', cropGroup: 'Berries', emoji: '🔴' },
  { name: 'Honeyberries', cropGroup: 'Berries', emoji: '🫐' },

  // ── Grapes ──
  { name: 'Grapes', cropGroup: 'Grapes', emoji: '🍇' },
  { name: 'Muscadine Grapes', cropGroup: 'Grapes', emoji: '🍇' },
  { name: 'Table Grapes', cropGroup: 'Grapes', emoji: '🍇' },

  // ── Cucurbits ──
  { name: 'Squash', cropGroup: 'Cucurbits', emoji: '🎃' },
  { name: 'Zucchini', cropGroup: 'Cucurbits', emoji: '🥒' },
  { name: 'Cucumbers', cropGroup: 'Cucurbits', emoji: '🥒' },
  { name: 'Melons', cropGroup: 'Cucurbits', emoji: '🍈' },
  { name: 'Watermelon', cropGroup: 'Cucurbits', emoji: '🍉' },
  { name: 'Cantaloupe', cropGroup: 'Cucurbits', emoji: '🍈' },
  { name: 'Pumpkins', cropGroup: 'Cucurbits', emoji: '🎃' },
  { name: 'Gourds', cropGroup: 'Cucurbits', emoji: '🎃' },

  // ── Nightshades ──
  { name: 'Tomatoes', cropGroup: 'Nightshades', emoji: '🍅' },
  { name: 'Peppers', cropGroup: 'Nightshades', emoji: '🌶️' },
  { name: 'Eggplant', cropGroup: 'Nightshades', emoji: '🍆' },
  { name: 'Tomatillos', cropGroup: 'Nightshades', emoji: '🟢' },
  { name: 'Potatoes', cropGroup: 'Nightshades', emoji: '🥔' },

  // ── Legumes ──
  { name: 'Green Beans', cropGroup: 'Legumes', emoji: '🫛' },
  { name: 'Snap Peas', cropGroup: 'Legumes', emoji: '🫛' },
  { name: 'Lima Beans', cropGroup: 'Legumes', emoji: '🫘' },
  { name: 'Black-Eyed Peas', cropGroup: 'Legumes', emoji: '🫘' },
  { name: 'Soybeans (Edamame)', cropGroup: 'Legumes', emoji: '🫛' },

  // ── Brassicas ──
  { name: 'Broccoli', cropGroup: 'Brassicas', emoji: '🥦' },
  { name: 'Cauliflower', cropGroup: 'Brassicas', emoji: '🥦' },
  { name: 'Cabbage', cropGroup: 'Brassicas', emoji: '🥬' },
  { name: 'Brussels Sprouts', cropGroup: 'Brassicas', emoji: '🥬' },
  { name: 'Kale', cropGroup: 'Brassicas', emoji: '🥬' },
  { name: 'Collard Greens', cropGroup: 'Brassicas', emoji: '🥬' },
  { name: 'Kohlrabi', cropGroup: 'Brassicas', emoji: '🥬' },
  { name: 'Turnips', cropGroup: 'Root Vegetables', emoji: '🟣' },
  { name: 'Radishes', cropGroup: 'Root Vegetables', emoji: '🔴' },

  // ── Alliums ──
  { name: 'Onions', cropGroup: 'Alliums', emoji: '🧅' },
  { name: 'Garlic', cropGroup: 'Alliums', emoji: '🧄' },
  { name: 'Leeks', cropGroup: 'Alliums', emoji: '🧅' },
  { name: 'Shallots', cropGroup: 'Alliums', emoji: '🧅' },
  { name: 'Scallions', cropGroup: 'Alliums', emoji: '🧅' },

  // ── Leafy Greens ──
  { name: 'Lettuce', cropGroup: 'Leafy Greens', emoji: '🥬' },
  { name: 'Spinach', cropGroup: 'Leafy Greens', emoji: '🥬' },
  { name: 'Arugula', cropGroup: 'Leafy Greens', emoji: '🥬' },
  { name: 'Swiss Chard', cropGroup: 'Leafy Greens', emoji: '🥬' },
  { name: 'Mustard Greens', cropGroup: 'Leafy Greens', emoji: '🥬' },

  // ── Root Vegetables ──
  { name: 'Carrots', cropGroup: 'Root Vegetables', emoji: '🥕' },
  { name: 'Beets', cropGroup: 'Root Vegetables', emoji: '🟣' },
  { name: 'Sweet Potatoes', cropGroup: 'Root Vegetables', emoji: '🍠' },
  { name: 'Parsnips', cropGroup: 'Root Vegetables', emoji: '🥕' },
  { name: 'Rutabaga', cropGroup: 'Root Vegetables', emoji: '🟡' },
  { name: 'Celery', cropGroup: 'Leafy Greens', emoji: '🥬' },

  // ── Corn ──
  { name: 'Sweet Corn', cropGroup: null, emoji: '🌽' },

  // ── Herbs ──
  { name: 'Basil', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Cilantro', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Dill', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Parsley', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Rosemary', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Thyme', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Sage', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Oregano', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Mint', cropGroup: 'Herbs', emoji: '🌿' },
  { name: 'Lavender', cropGroup: 'Herbs', emoji: '💜' },

  // ── Turf Grass ──
  { name: 'Bermuda Grass', cropGroup: 'Turf Grass', emoji: '🌾' },
  { name: 'Zoysia Grass', cropGroup: 'Turf Grass', emoji: '🌾' },
  { name: 'Tall Fescue', cropGroup: 'Turf Grass', emoji: '🌾' },
  { name: 'Centipede Grass', cropGroup: 'Turf Grass', emoji: '🌾' },
  { name: 'St. Augustine Grass', cropGroup: 'Turf Grass', emoji: '🌾' },
  { name: 'Kentucky Bluegrass', cropGroup: 'Turf Grass', emoji: '🌾' },

  // ── Orchard Floor ──
  { name: 'Orchard Floor (Tree Fruit)', cropGroup: 'Orchard Floor', emoji: '🌳' },
  { name: 'Orchard Floor (Berry)', cropGroup: 'Orchard Floor', emoji: '🫐' },
  { name: 'Vineyard Floor', cropGroup: 'Orchard Floor', emoji: '🍇' },
  { name: 'Garden Paths & Beds', cropGroup: 'Orchard Floor', emoji: '🪴' },

  // ── Other Edibles ──
  { name: 'Asparagus', cropGroup: null, emoji: '🌿' },
  { name: 'Rhubarb', cropGroup: null, emoji: '🟢' },
  { name: 'Okra', cropGroup: null, emoji: '🟢' },
  { name: 'Artichokes', cropGroup: null, emoji: '🟢' },
  { name: 'Sunflowers', cropGroup: null, emoji: '🌻' },
  { name: 'Hops', cropGroup: null, emoji: '🌿' },

  // ── Ornamentals: Roses ──
  { name: 'Knock Out Roses', cropGroup: 'Ornamentals', emoji: '🌹' },
  { name: 'Hybrid Tea Roses', cropGroup: 'Ornamentals', emoji: '🌹' },
  { name: 'Climbing Roses', cropGroup: 'Ornamentals', emoji: '🌹' },
  { name: 'Floribunda Roses', cropGroup: 'Ornamentals', emoji: '🌹' },
  { name: 'Shrub Roses', cropGroup: 'Ornamentals', emoji: '🌹' },
  { name: 'David Austin Roses', cropGroup: 'Ornamentals', emoji: '🌹' },

  // ── Ornamentals: Flowering Shrubs ──
  { name: 'Hydrangeas', cropGroup: 'Ornamentals', emoji: '💠' },
  { name: 'Peonies', cropGroup: 'Ornamentals', emoji: '🌸' },
  { name: 'Loropetalum', cropGroup: 'Ornamentals', emoji: '🌺' },
  { name: 'Azaleas', cropGroup: 'Ornamentals', emoji: '🌺' },
  { name: 'Rhododendrons', cropGroup: 'Ornamentals', emoji: '🌺' },
  { name: 'Camellias', cropGroup: 'Ornamentals', emoji: '🌸' },
  { name: 'Gardenias', cropGroup: 'Ornamentals', emoji: '🤍' },
  { name: 'Lilacs', cropGroup: 'Ornamentals', emoji: '💜' },
  { name: 'Forsythia', cropGroup: 'Ornamentals', emoji: '💛' },
  { name: 'Spirea', cropGroup: 'Ornamentals', emoji: '🤍' },
  { name: 'Viburnum', cropGroup: 'Ornamentals', emoji: '🤍' },
  { name: 'Butterfly Bush', cropGroup: 'Ornamentals', emoji: '🦋' },
  { name: 'Weigela', cropGroup: 'Ornamentals', emoji: '🌺' },
  { name: 'Crape Myrtle', cropGroup: 'Ornamentals', emoji: '🌸' },
  { name: 'Boxwood', cropGroup: 'Ornamentals', emoji: '🟩' },
  { name: 'Holly', cropGroup: 'Ornamentals', emoji: '🟢' },
  { name: 'Nandina', cropGroup: 'Ornamentals', emoji: '🔴' },

  // ── Ornamentals: Perennials ──
  { name: 'Daylilies', cropGroup: 'Ornamentals', emoji: '🌼' },
  { name: 'Hostas', cropGroup: 'Ornamentals', emoji: '🌿' },
  { name: 'Coneflowers', cropGroup: 'Ornamentals', emoji: '🌼' },
  { name: 'Black-Eyed Susans', cropGroup: 'Ornamentals', emoji: '🌻' },
  { name: 'Clematis', cropGroup: 'Ornamentals', emoji: '💜' },
  { name: 'Dahlias', cropGroup: 'Ornamentals', emoji: '🌸' },
  { name: 'Irises', cropGroup: 'Ornamentals', emoji: '💜' },

  // ── Ornamentals: Trees ──
  { name: 'Dogwood', cropGroup: 'Ornamentals', emoji: '🌸' },
  { name: 'Japanese Maple', cropGroup: 'Ornamentals', emoji: '🍁' },
  { name: 'Magnolia', cropGroup: 'Ornamentals', emoji: '🤍' },
  { name: 'Redbud', cropGroup: 'Ornamentals', emoji: '💜' },

  // ── Structures & Premise — non-crop spray targets around the home ──
  { name: 'House Perimeter', cropGroup: 'Structures & Premise', emoji: '🏠' },
  { name: 'Deck', cropGroup: 'Structures & Premise', emoji: '🪵' },
  { name: 'Patio', cropGroup: 'Structures & Premise', emoji: '🧱' },
  { name: 'Fence Line', cropGroup: 'Structures & Premise', emoji: '🪵' },
  { name: 'Driveway Edge', cropGroup: 'Structures & Premise', emoji: '🛣️' },
  { name: 'Walkway', cropGroup: 'Structures & Premise', emoji: '🪨' },
  { name: 'Shed', cropGroup: 'Structures & Premise', emoji: '🛖' },
  { name: 'Garage', cropGroup: 'Structures & Premise', emoji: '🚗' },
  { name: 'Mulch Beds', cropGroup: 'Structures & Premise', emoji: '🟫' },
  { name: 'Gravel Areas', cropGroup: 'Structures & Premise', emoji: '🪨' },
  { name: 'Retaining Walls', cropGroup: 'Structures & Premise', emoji: '🧱' },
  { name: 'Playset', cropGroup: 'Structures & Premise', emoji: '🛝' },
  { name: 'Trash Area', cropGroup: 'Structures & Premise', emoji: '🗑️' },
  { name: 'Compost Pile', cropGroup: 'Structures & Premise', emoji: '♻️' },
];
