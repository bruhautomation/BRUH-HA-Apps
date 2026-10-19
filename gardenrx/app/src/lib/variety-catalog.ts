export interface VarietyProfile {
  name: string;
  description: string;
  taste: string;
  features: string[];
  harvestWindow: string;
  chillHours?: string;
  diseaseNotes?: string;
}

export const VARIETY_CATALOG: Record<string, VarietyProfile> = {
  // ── Apples ──────────────────────────────────────────────

  'Arkansas Black': {
    name: 'Arkansas Black',
    description:
      'A late-season keeper originating from Benton County, Arkansas in the 1840s. The fruit develops an extraordinarily dark red skin that deepens to near-black in storage.',
    taste:
      'Firm, crisp flesh with complex wine-like sweetness, hints of cherry and vanilla, improving dramatically after 2-3 months in storage.',
    features: [
      'One of the longest-keeping heritage apples — holds 6+ months in cold storage',
      'Extremely hard flesh at harvest; requires patience for peak eating quality',
      'Vigorous, upright tree with good heat tolerance for the Piedmont',
      'Outstanding cider blending apple with high tannin and acid',
    ],
    harvestWindow: 'Late October – November',
    chillHours: '800–900',
    diseaseNotes:
      'Moderate resistance to cedar-apple rust and fire blight; somewhat susceptible to bitter rot in humid summers.',
  },

  'Belle De Boskoop': {
    name: 'Belle De Boskoop',
    description:
      'A large, vigorous Dutch triploid discovered in Boskoop around 1856. Prized in Europe as a dual-purpose cooking and dessert apple with distinctive rough, russeted skin.',
    taste:
      'Tart and aromatic with rich, complex acidity that balances well with moderate sugar; exceptional for baking where it holds its shape.',
    features: [
      'Triploid — requires two compatible diploid pollinizers nearby',
      'Very large fruit, often 3-4 inches in diameter',
      'Excellent cooking apple that retains structure in pies and sauces',
      'Good keeper, 3-4 months in cold storage',
    ],
    harvestWindow: 'Mid-October – early November',
    chillHours: '800–1000',
    diseaseNotes:
      'Susceptible to scab and powdery mildew; benefits from consistent fungicide program in NC humidity.',
  },

  'Esopus Spitzenberg': {
    name: 'Esopus Spitzenberg',
    description:
      "Thomas Jefferson's favorite apple, originating from Esopus, New York in the 1700s. Widely considered one of the finest-flavored American heritage apples.",
    taste:
      'Rich, spicy-sweet flavor with distinct notes of orange zest and clove; fine-grained, juicy flesh.',
    features: [
      'Considered among the top 5 best-tasting heritage apples in North America',
      'Medium-sized, conical fruit with bright red-orange skin',
      'Good cider apple with balanced sugar-acid ratio',
      'Keeps 2-3 months in cold storage',
    ],
    harvestWindow: 'Early – mid October',
    chillHours: '800–1000',
    diseaseNotes:
      'Highly susceptible to fire blight, scab, and cedar-apple rust — one of the more disease-prone heritage varieties for the Southeast.',
  },

  Gala: {
    name: 'Gala',
    description:
      "Developed in New Zealand from a Golden Delicious x Kidd's Orange Red cross. One of the most commercially successful apples worldwide, valued for reliable, sweet flavor and early season.",
    taste:
      'Mild, sweet, and aromatic with light vanilla and floral notes; low acidity makes it a crowd-pleaser for fresh eating.',
    features: [
      'Early to bear — often produces fruit by year 3 on dwarf rootstock',
      'Consistent annual cropper with heavy fruit set requiring aggressive thinning',
      'Medium-sized, attractive red-striped fruit over yellow base',
      'Short storage life — best within 2-3 months',
    ],
    harvestWindow: 'Late July – mid August',
    chillHours: '500–600',
    diseaseNotes:
      'Moderate fire blight susceptibility; prone to bitter rot and flyspeck in humid Piedmont summers without a spray program.',
  },

  'Ginger Gold': {
    name: 'Ginger Gold',
    description:
      'A chance seedling discovered in the orchard of Ginger Harvey in Lovingston, Virginia after Hurricane Camille (1969). One of the best early-season yellow apples.',
    taste: 'Mildly tart with clean, crisp sweetness; subtle ginger-spice undertone.',
    features: [
      'One of the earliest quality apples of the season in Zone 7b',
      'Attractive pale yellow-green skin',
      'Virginia origin makes it well-suited to Southeast heat and humidity',
      'Limited storage life — eat within 4-6 weeks of harvest',
    ],
    harvestWindow: 'Late July – early August',
    chillHours: '500–600',
    diseaseNotes:
      'Moderate scab susceptibility; reasonably tolerant of fire blight for a yellow apple.',
  },

  Goldrush: {
    name: 'Goldrush',
    description:
      'Released by the PRI cooperative breeding program in 1993. A scab-immune late-season yellow apple that stores exceptionally well. Cornerstone of low-spray orchards.',
    taste:
      'Intensely tart at harvest, mellowing to rich, spicy, well-balanced sweet-tart after 1-2 months in storage.',
    features: [
      'Immune to apple scab (Vf gene)',
      'Outstanding keeper; improves for months in cold storage',
      'Medium-sized golden fruit with occasional russeting',
      'Patience in storage is essential for best eating quality',
    ],
    harvestWindow: 'Late October – November',
    chillHours: '700–800',
    diseaseNotes:
      'Immune to scab; moderate susceptibility to fire blight and cedar-apple rust; powdery mildew can still occur.',
  },

  Harrison: {
    name: 'Harrison',
    description:
      'The legendary cider apple of Newark, New Jersey, considered the finest American cider variety of the 18th and 19th centuries. Nearly lost to extinction, rediscovered in the 1970s.',
    taste:
      'Too astringent for fresh eating; yields deep amber cider with rich body, high sugar (often 14+ Brix), and moderate tannin.',
    features: [
      'Premier American heritage cider apple',
      'High sugar content for single-variety cider',
      'Small to medium fruit, yellow-green with russeting',
      'Fruit drops readily when ripe — harvest promptly',
    ],
    harvestWindow: 'Mid – late October',
    chillHours: '800–1000',
    diseaseNotes:
      'Moderate disease resistance overall; some fire blight susceptibility; limited data in Southeast conditions.',
  },

  Honeycrisp: {
    name: 'Honeycrisp',
    description:
      'Developed at the University of Minnesota, released in 1991. Known for explosive crisp texture from exceptionally large cells. Can be challenging to grow in the Southeast.',
    taste:
      'Sweet-tart with honey-like aromatic quality; shattering crunch from unusually large cellular structure.',
    features: [
      'Exceptionally crisp — the benchmark modern eating apple',
      'Prone to bitter pit; manage calcium carefully',
      'Biennial bearing tendency; aggressive thinning essential',
      'Somewhat brittle wood with narrow crotch angles',
    ],
    harvestWindow: 'Late August – mid September',
    chillHours: '800–1000',
    diseaseNotes:
      'Susceptible to scab, fire blight, and bitter rot; demands a full spray program in Zone 7b; bitter pit is the primary physiological disorder.',
  },

  'Mountain Rose': {
    name: 'Mountain Rose',
    description:
      'A modern red-fleshed apple bred in Oregon. Vivid pink-to-red interior makes striking cider, sauce, and fresh slices. Flesh color holds when cooked.',
    taste:
      'Bright, tart-sweet with berry-like undertones; higher acidity than typical dessert apples.',
    features: [
      'Vivid red flesh throughout — color holds in cooking',
      'Makes visually striking pink applesauce and rosé cider',
      'Medium-sized fruit with reddish-purple skin',
      'Semi-upright growth habit',
    ],
    harvestWindow: 'Early – mid September',
    chillHours: '600–800',
    diseaseNotes:
      'Limited disease data for the Southeast; appears moderately susceptible to scab and fire blight.',
  },

  'Newtown Pippin': {
    name: 'Newtown Pippin',
    description:
      "One of America's oldest and most distinguished apples, from Newtown, Queens, New York in the early 1700s. Famously exported to England. Improves markedly in storage.",
    taste:
      'Complex tart-sweet flavor with citrus and pine notes; develops depth after 6-8 weeks in storage.',
    features: [
      'Historic American variety grown by Washington, Jefferson, and Franklin',
      'Excellent keeper — 4-6 months in cold storage',
      'Outstanding for both fresh eating (after storage) and hard cider',
      'Slow to come into bearing',
    ],
    harvestWindow: 'Mid – late October',
    chillHours: '800–900',
    diseaseNotes:
      'Moderately susceptible to scab and powdery mildew; reasonable fire blight tolerance.',
  },

  'Pink Lady': {
    name: 'Pink Lady',
    description:
      'Trademarked name for Cripps Pink, bred in Western Australia. One of the latest-ripening commercial apples, requiring a long, warm season for its signature pink blush.',
    taste:
      'Crisp and effervescent with well-balanced sweet-tart profile; bright acidity with honey and citrus notes.',
    features: [
      'Requires a long growing season — one of the last apples harvested',
      'Distinctive pink-over-green bicolor skin',
      'Excellent storage apple; holds 3-5 months',
      'High farmers market value due to name recognition',
    ],
    harvestWindow: 'Late October – mid November',
    chillHours: '400–600',
    diseaseNotes:
      'Moderate scab and fire blight susceptibility; can be prone to sunburn in hot summers.',
  },

  'Pink Pearl': {
    name: 'Pink Pearl',
    description:
      'Bred by Albert Etter in Humboldt County, California in 1944. Striking pink-fleshed apple with translucent, pale yellow-green skin.',
    taste:
      'Tart and tangy with raspberry-like overtones; lower in sugar, best for those who enjoy sharp apples.',
    features: [
      'Translucent skin reveals vivid pink flesh',
      'Makes spectacular pink applesauce',
      'Early season for a novelty apple',
      'Moderate tree vigor with willowy branching',
    ],
    harvestWindow: 'Late August – early September',
    chillHours: '600–700',
    diseaseNotes: 'Moderately susceptible to scab; general Southeast spray program recommended.',
  },

  'Porters Perfection': {
    name: 'Porters Perfection',
    description:
      "Traditional English bittersharp cider apple from Somerset. Not for fresh eating — a dedicated cidermaker's variety providing structure and backbone to blends.",
    taste:
      'Bitter, tannic, and sharp; contributes essential body, color, and depth to cider blends.',
    features: [
      'True bittersharp cider apple with high tannin and acid',
      'Deep-colored juice with excellent structure',
      'Can be biennial; manage with aggressive thinning',
      'Pairs well with sweeter American varieties like Harrison',
    ],
    harvestWindow: 'Mid – late October',
    chillHours: '800–1000',
    diseaseNotes:
      'Expect moderate scab and mildew pressure; limited Southeast-specific disease data.',
  },

  'Roxbury Russet': {
    name: 'Roxbury Russet',
    description:
      'The oldest named American apple variety, from Roxbury, Massachusetts in the early 1600s. Fully russeted with a devoted following among cider makers.',
    taste:
      'Rich, nutty sweetness with caramel and dried fruit notes; dense, deeply flavorful character.',
    features: [
      'Oldest named American apple — over 400 years of cultivation',
      'Full russet skin with golden-brown finish',
      'Outstanding cider apple; high sugar (often 15+ Brix)',
      'Excellent keeper — 4-6 months in cold storage',
    ],
    harvestWindow: 'Mid – late October',
    chillHours: '800–1000',
    diseaseNotes:
      'Good overall disease resistance; russeted skin naturally less prone to flyspeck and sooty blotch.',
  },

  Wickson: {
    name: 'Wickson',
    description:
      'A crabapple-sized apple bred by Albert Etter from a Spitzenberg x crabapple cross. Packs extraordinary sugar content despite small size. Prized for single-variety cider.',
    taste: 'Explosively sweet and tart with tropical fruit notes; Brix readings often exceed 20.',
    features: [
      'Very high sugar — among the sweetest of all apples',
      'Small fruit (1.5-2 inches) — a crab-sized apple',
      'Outstanding single-variety cider',
      'Heavy bearer; clusters require thinning',
    ],
    harvestWindow: 'Early – mid September',
    chillHours: '600–800',
    diseaseNotes:
      'Moderate scab susceptibility; dense fruit clusters can promote brown rot if not thinned.',
  },

  Winesap: {
    name: 'Winesap',
    description:
      'Classic American apple documented since the late 1700s, long dominant in Virginia and the southern Appalachians. True triple-purpose apple — fresh, cooking, and cider.',
    taste:
      'Distinctly wine-like and spicy with firm, juicy flesh; pronounced tartness balanced by moderate sweetness.',
    features: [
      'True triple-purpose: fresh eating, cooking, and cider',
      'Well-adapted to the Southeast with long regional track record',
      'Deep red fruit with tough skin',
      'Triploid — ensure compatible pollinizers',
    ],
    harvestWindow: 'Mid – late October',
    chillHours: '800–900',
    diseaseNotes:
      'Moderate disease resistance; some susceptibility to fire blight and scab; performs better than many heritage varieties in the Southeast.',
  },

  // ── Pears ───────────────────────────────────────────────

  Bartlett: {
    name: 'Bartlett',
    description:
      "The classic European pear, known as Williams' Bon Chretien in Europe. The standard by which all dessert pears are measured. Requires careful harvest timing.",
    taste:
      "Buttery, smooth, and intensely aromatic with honey-sweet juiciness that defines 'pear flavor.'",
    features: [
      'The benchmark dessert pear',
      'Must be picked mature-green and ripened at room temperature',
      'Self-fertile but sets better with a pollinizer',
      'Excellent for fresh eating, canning, and perry',
    ],
    harvestWindow: 'Mid – late August',
    chillHours: '800–900',
    diseaseNotes:
      'Highly susceptible to fire blight — streptomycin sprays at bloom often necessary in the Southeast.',
  },

  'Hosui Asian Pear': {
    name: 'Hosui Asian Pear',
    description:
      "One of the most popular Japanese pear varieties, meaning 'much water.' Crisp and juicy, ripens on the tree unlike European pears.",
    taste:
      'Exceptionally juicy and refreshing with mild butterscotch-sweet flavor; crisp like an apple with pear fragrance.',
    features: [
      'Eat crisp off the tree — no post-harvest ripening needed',
      'Large, golden-brown russeted fruit',
      'Requires aggressive thinning to one fruit per cluster',
      'Self-fertile but cross-pollination improves set',
    ],
    harvestWindow: 'Mid August – early September',
    chillHours: '450–500',
    diseaseNotes:
      'Moderate fire blight susceptibility — less vulnerable than Bartlett but still a concern.',
  },

  Kieffer: {
    name: 'Kieffer',
    description:
      'Tough, disease-resistant European/Asian pear hybrid widely planted across the South since the 1800s. Coarse-grained; best for canning, preserves, and cooking.',
    taste:
      'Gritty, firm flesh with mild sweetness; best cooked or canned; improves with cold storage.',
    features: [
      'Outstanding fire blight resistance — the safest pear for the Southeast',
      'Extremely vigorous and productive',
      'Best used for canning, preserves, baking, and pear butter',
      'Often found on old homesteads still bearing',
    ],
    harvestWindow: 'Late September – October',
    chillHours: '350–400',
    diseaseNotes: 'Exceptional fire blight resistance; most disease-proof pear commonly available.',
  },

  Moonglow: {
    name: 'Moonglow',
    description:
      'Developed by USDA in Beltsville, Maryland, released in 1960. Bred specifically for fire blight resistance while maintaining good eating quality. Reliable early-season pear.',
    taste:
      'Mild, sweet, slightly musky with soft, juicy flesh; less aromatic than Bartlett but pleasant.',
    features: [
      'Bred for fire blight resistance — much safer than Bartlett',
      'Early season; fills the gap before Bartlett',
      'Excellent pollinizer for other European pears',
      'Pick firm and ripen at room temp for 5-7 days',
    ],
    harvestWindow: 'Early – mid August',
    chillHours: '700–800',
    diseaseNotes:
      'Good fire blight resistance; some susceptibility to pear scab and leaf spot in wet years.',
  },

  // ── Berries, Stone Fruit, Pawpaws ──────────────────────

  'Shinseiki Asian Pear': {
    name: 'Shinseiki Asian Pear',
    description:
      'Early-ripening Japanese pear with smooth yellow-green skin. Crisp, juicy flesh with mild sweetness. Partially self-fertile but benefits from a pollinizer. Moderate fire blight resistance.',
    taste: 'Mild, refreshing sweetness with crisp, apple-like texture and high juice content',
    features: ['Early ripening', 'Partially self-fertile', 'Long storage life'],
    harvestWindow: 'Late July - August',
    chillHours: '450-500',
    diseaseNotes: 'Moderate fire blight resistance; watch for pear psylla and codling moth',
  },

  Lapins: {
    name: 'Lapins',
    description:
      'Self-fertile sweet cherry producing large, dark red fruit. Strong vigor and heavy bearing. One of the best self-pollinating cherries for the Southeast, though heat and humidity remain challenges.',
    taste: 'Rich, sweet flavor with firm, meaty flesh',
    features: ['Self-fertile', 'Large fruit', 'Heavy bearing', 'Crack resistant'],
    harvestWindow: 'Late May - Early June',
    chillHours: '800-900',
    diseaseNotes:
      'Susceptible to bacterial canker and brown rot; rain cracking less of a concern than most sweet cherries',
  },

  Rainier: {
    name: 'Rainier',
    description:
      'Premium yellow-blushed sweet cherry prized for exceptional sweetness. Requires a pollinizer such as Lapins or Stella. Challenging in Zone 7b due to heat sensitivity and disease pressure.',
    taste: 'Exceptionally sweet and delicate with low acidity; fine-textured flesh',
    features: ['Premium dessert quality', 'Yellow with red blush', 'High sugar content'],
    harvestWindow: 'Late May - Early June',
    chillHours: '700-900',
    diseaseNotes:
      'Very susceptible to brown rot and rain cracking; needs aggressive fungicide program in humid climates',
  },

  Stella: {
    name: 'Stella',
    description:
      'Self-fertile dark sweet cherry and universal pollinizer. Vigorous, upright tree with reliable crops. One of the first commercially available self-fertile sweet cherries.',
    taste: 'Sweet, mildly aromatic with moderately firm flesh',
    features: ['Self-fertile', 'Universal pollinizer', 'Vigorous grower'],
    harvestWindow: 'Late May - Early June',
    chillHours: '700-800',
    diseaseNotes: 'Susceptible to bacterial canker and brown rot; moderate rain-crack resistance',
  },

  Susquehanna: {
    name: 'Susquehanna',
    description:
      'Top-tier pawpaw cultivar producing very large fruit with small seed-to-flesh ratio. Selected by Neal Peterson. Rich, custard-like texture with complex tropical flavor. Needs a genetically distinct pollinizer.',
    taste: 'Rich, custardy with mango-banana notes and minimal bitterness',
    features: ['Very large fruit', 'Small seed ratio', 'Peterson selection'],
    harvestWindow: 'Mid September - Early October',
    chillHours: '400-800',
    diseaseNotes: undefined,
  },

  Tallahatchie: {
    name: 'Tallahatchie',
    description:
      'Peterson pawpaw selection with large, flavorful fruit and good tree form. Named for the Mississippi river. Produces reliably in the Southeast with adequate cross-pollination from another pawpaw cultivar.',
    taste: 'Sweet, tropical custard flavor with hints of vanilla and caramel',
    features: ['Large fruit', 'Good tree form', 'Peterson selection'],
    harvestWindow: 'Mid September - October',
    chillHours: '400-800',
    diseaseNotes: undefined,
  },

  Bluejay: {
    name: 'Bluejay',
    description:
      'Northern highbush blueberry with vigorous, upright growth. Medium-sized berries in tight clusters ripen uniformly. Good ornamental value with bright fall color. Consistent producer in upper Zone 7.',
    taste: 'Mild, pleasant sweetness with slight tang',
    features: ['Uniform ripening', 'Vigorous upright habit', 'Good fall color'],
    harvestWindow: 'Early - Mid June',
    chillHours: '800-1000',
    diseaseNotes: 'Good mummy berry resistance; moderate resistance to anthracnose',
  },

  Brightwell: {
    name: 'Brightwell',
    description:
      'Rabbiteye blueberry well-suited to the Piedmont. Vigorous, upright bush with medium to large berries. Excellent heat and drought tolerance once established. Requires another rabbiteye for pollination.',
    taste: 'Sweet with good flavor; small dry scar',
    features: ['Heat tolerant', 'Drought tolerant', 'Reliable producer'],
    harvestWindow: 'Mid June - July',
    chillHours: '350-400',
    diseaseNotes: 'Good overall disease resistance; occasional leaf spot in wet seasons',
  },

  Legacy: {
    name: 'Legacy',
    description:
      'Southern highbush-northern highbush hybrid with outstanding flavor and productivity. Upright, vigorous bush with excellent ornamental qualities. One of the highest-rated blueberries for fresh eating.',
    taste: 'Exceptionally sweet and aromatic; considered one of the best-flavored blueberries',
    features: ['Outstanding flavor', 'High yield', 'Excellent ornamental value'],
    harvestWindow: 'Mid June - July',
    chillHours: '500-600',
    diseaseNotes: 'Moderate mummy berry susceptibility; good overall disease resistance',
  },

  'New Hanover': {
    name: 'New Hanover',
    description:
      'Southern highbush blueberry developed by NC State for the Coastal Plain and Piedmont. Medium-large berries with good firmness and shelf life. Adapted to low-chill areas of North Carolina.',
    taste: 'Good sweet-tart balance with firm texture',
    features: ['NC State release', 'Good firmness', 'Low chill adapted'],
    harvestWindow: 'Late May - Mid June',
    chillHours: '400-500',
    diseaseNotes: 'Bred for improved disease resistance in humid Southeast conditions',
  },

  ONeal: {
    name: 'ONeal',
    description:
      'Southern highbush blueberry and one of the most widely planted in the Southeast. Early ripening with large, flavorful berries. Semi-upright habit. Performs well across the NC Piedmont.',
    taste: 'Very sweet with rich, complex blueberry flavor',
    features: ['Early ripening', 'Large berries', 'Widely adapted in Southeast'],
    harvestWindow: 'Late May - Early June',
    chillHours: '400-500',
    diseaseNotes: 'Moderate susceptibility to Phytophthora root rot in poorly drained soils',
  },

  Powderblue: {
    name: 'Powderblue',
    description:
      'Rabbiteye blueberry and one of the most dependable varieties for the Southeast. Light blue, medium-sized berries with good post-harvest quality. Extremely vigorous and productive with excellent heat tolerance.',
    taste: 'Good mild flavor; slightly dry texture compared to highbush types',
    features: ['Extremely reliable', 'Heat tolerant', 'Long harvest season'],
    harvestWindow: 'Late June - July',
    chillHours: '550-650',
    diseaseNotes:
      'Excellent disease resistance overall; one of the most trouble-free rabbiteye varieties',
  },

  Premier: {
    name: 'Premier',
    description:
      'Early-ripening rabbiteye blueberry with large, high-quality fruit. Vigorous, spreading bush. Good pollinizer for other rabbiteye varieties. Well-proven across the Southeast Piedmont.',
    taste: 'Sweet, rich flavor with tender skin for a rabbiteye',
    features: ['Early for rabbiteye', 'Large fruit', 'Good pollinizer'],
    harvestWindow: 'Early - Mid June',
    chillHours: '550-600',
    diseaseNotes: 'Good disease resistance; occasional leaf rust in humid conditions',
  },

  Sharpblue: {
    name: 'Sharpblue',
    description:
      'Low-chill southern highbush blueberry with early, extended harvest. Spreading, semi-evergreen habit. One of the original southern highbush releases from the University of Florida.',
    taste: 'Tangy-sweet with aromatic blueberry flavor',
    features: ['Very low chill requirement', 'Extended harvest', 'Semi-evergreen'],
    harvestWindow: 'Late May - June',
    chillHours: '150-200',
    diseaseNotes: 'Susceptible to stem blight; needs well-drained acidic soil to avoid root rot',
  },

  Sunshine: {
    name: 'Sunshine',
    description:
      'Southern highbush blueberry bred for the mid-South. Medium berries with bright blue color and good scar. Compact, manageable plant size suited to smaller spaces and container growing.',
    taste: 'Sweet, mild flavor with firm texture',
    features: ['Compact habit', 'Bright blue fruit', 'Container friendly'],
    harvestWindow: 'Late May - Mid June',
    chillHours: '400-500',
    diseaseNotes: 'Good general disease tolerance for a southern highbush',
  },

  Sweetheart: {
    name: 'Sweetheart',
    description:
      'Southern highbush blueberry with medium-large, flavorful berries. Upright bush with moderate vigor. Developed for consistent quality in warm-winter regions. Requires cross-pollination.',
    taste: 'Sweet, pleasant flavor true to its name',
    features: ['Consistent quality', 'Medium-large berries', 'Upright habit'],
    harvestWindow: 'Late May - June',
    chillHours: '400-500',
    diseaseNotes: 'Average disease resistance; monitor for leaf spot diseases in wet years',
  },

  Titan: {
    name: 'Titan',
    description:
      'Rabbiteye blueberry producing exceptionally large berries, among the biggest of any blueberry variety. Vigorous, upright habit. Released by the University of Georgia. Requires rabbiteye pollinizer.',
    taste: 'Mild, sweet flavor; good for fresh eating given large size',
    features: ['Exceptionally large fruit', 'Vigorous', 'UGA release'],
    harvestWindow: 'Mid June - July',
    chillHours: '500-600',
    diseaseNotes: 'Good general disease resistance; standard rabbiteye toughness',
  },

  Vernon: {
    name: 'Vernon',
    description:
      'Rabbiteye blueberry from the University of Georgia breeding program. Early ripening for a rabbiteye with large, firm berries. Good companion pollinizer for Titan and other late rabbiteyes.',
    taste: 'Good balance of sweetness and acidity with firm flesh',
    features: ['Early for rabbiteye', 'Large firm berries', 'UGA release'],
    harvestWindow: 'Early - Mid June',
    chillHours: '500-550',
    diseaseNotes: 'Good disease resistance; monitor for Exobasidium leaf and fruit spot',
  },

  Caroline: {
    name: 'Caroline',
    description:
      'Primocane-fruiting red raspberry with large, conical berries. Outstanding flavor considered among the best of fall-bearing types. Vigorous canes with good yield potential in Zone 7b.',
    taste: 'Intensely sweet-tart with rich, full raspberry aroma; considered top-tier flavor',
    features: ['Primocane fruiting', 'Large fruit', 'Outstanding flavor'],
    harvestWindow: 'August - October',
    chillHours: undefined,
    diseaseNotes: 'Good resistance to Phytophthora root rot; tolerant of root lesion nematode',
  },

  Heritage: {
    name: 'Heritage',
    description:
      'Classic primocane-fruiting red raspberry and the industry standard for fall-bearing types. Medium-sized, firm berries on sturdy, upright canes. Extremely reliable and widely adapted.',
    taste: 'Classic raspberry flavor with good sweetness and firm texture',
    features: ['Primocane fruiting', 'Industry standard', 'Very reliable'],
    harvestWindow: 'August - Frost',
    chillHours: undefined,
    diseaseNotes: 'Susceptible to late leaf rust; resistant to most common raspberry viruses',
  },

  'Sweetie Pie': {
    name: 'Sweetie Pie',
    description:
      'Thornless, patented floricane blackberry from the University of Arkansas. Large, glossy berries with notably sweet flavor and low acidity. Erect to semi-erect habit with manageable vigor.',
    taste: 'Very sweet with low acidity; smooth, non-astringent finish',
    features: ['Thornless', 'Very sweet', 'Erect habit'],
    harvestWindow: 'June - July',
    chillHours: '400-500',
    diseaseNotes:
      'Monitor for orange rust, anthracnose, and double blossom (rosette) in humid conditions',
  },

  Cambiante: {
    name: 'Cambiante',
    description:
      'Day-neutral strawberry from UC Davis breeding program. Distinctive rose-pink exterior when ripe, unusual among commercial varieties. Good heat tolerance for a day-neutral, performing well through NC summers.',
    taste: 'Sweet with aromatic, fruity complexity; unique among pink-skinned varieties',
    features: ['Day-neutral', 'Pink-skinned fruit', 'Heat tolerant'],
    harvestWindow: 'April - October (day-neutral, multiple flushes)',
    chillHours: undefined,
    diseaseNotes:
      'Good powdery mildew tolerance; standard Phytophthora and Botrytis monitoring recommended',
  },

  // ── Vegetables, Herbs, Ornamentals ────────────────────

  "Bonnie's Best": {
    name: "Bonnie's Best",
    description:
      'Classic indeterminate slicer from the early 1900s, prized for reliable yields of medium-sized red fruit on vigorous vines.',
    taste: 'Well-balanced old-fashioned tomato flavor with moderate acidity and sweetness.',
    features: ['Indeterminate', '70-75 days to maturity', 'Medium 8-12 oz fruit'],
    harvestWindow: 'July through September',
    chillHours: undefined,
    diseaseNotes:
      'Moderate resistance to Fusarium wilt; susceptible to late blight and early blight in humid Piedmont summers.',
  },

  'Cherokee Purple': {
    name: 'Cherokee Purple',
    description:
      'Heirloom beefsteak with dusky rose-purple skin and deep crimson flesh, originating from Tennessee seed stock predating 1890.',
    taste:
      'Rich, complex sweetness with smoky undertones and low acidity. One of the most flavorful heirloom slicers.',
    features: ['Indeterminate', '80-90 days to maturity', 'Large 10-16 oz fruit'],
    harvestWindow: 'Late July through September',
    chillHours: undefined,
    diseaseNotes:
      'No notable disease resistance; prone to cracking and susceptible to early blight and bacterial wilt in hot, humid conditions.',
  },

  Roma: {
    name: 'Roma',
    description:
      'Compact determinate paste tomato producing heavy clusters of oval, meaty fruit with few seeds and thick walls.',
    taste:
      'Mild, low-acid flavor with dense flesh. Best for cooking, sauces, and canning rather than fresh eating.',
    features: ['Determinate', '75-80 days to maturity', 'Compact 2-3 oz plum-shaped fruit'],
    harvestWindow: 'July through August',
    chillHours: undefined,
    diseaseNotes:
      'Resistant to Verticillium and Fusarium wilt (VF). Susceptible to blossom end rot if watering is inconsistent.',
  },

  'San Marzano': {
    name: 'San Marzano',
    description:
      'Indeterminate Italian paste tomato producing elongated, pointed fruit with minimal seed cavities and thick pericarp walls.',
    taste:
      'Sweet, low-acid flesh with strong umami depth. The benchmark for Neapolitan-style sauces.',
    features: ['Indeterminate', '80-85 days to maturity', 'Elongated 4-5 oz fruit'],
    harvestWindow: 'Late July through September',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to blossom end rot and late blight. Staking critical to keep fruit off soil in humid Piedmont conditions.',
  },

  'Mr. Stripey': {
    name: 'Mr. Stripey',
    description:
      "Indeterminate beefsteak-type heirloom (often sold as Tigerella's larger American cousin) producing 1-2 lb fruit marbled yellow and red, inside and out.",
    taste:
      'Mild, low-acid, and sweet with a fruity finish — one of the gentlest-flavored bicolor heirlooms, excellent sliced fresh.',
    features: [
      'Indeterminate — needs tall staking or a cage',
      '80 days to maturity',
      'Striking yellow-red striped fruit, often 1 lb+',
      'Low acidity suits those who find big reds too sharp',
    ],
    harvestWindow: 'Late July through September',
    chillHours: undefined,
    diseaseNotes:
      'No bred-in resistances — susceptible to early blight, late blight, and septoria leaf spot. Mulch, prune for airflow, and rotate beds yearly.',
  },

  'Orange Bell Pepper': {
    name: 'Orange Bell Pepper',
    description:
      'Sweet bell pepper maturing from green to deep orange, with thick-walled blocky fruit on sturdy upright plants.',
    taste:
      'Very sweet and fruity when fully ripe, with higher sugar content than green-stage bells.',
    features: [
      '75-80 days to maturity (from transplant)',
      '3-4 lobed blocky fruit',
      'High vitamin C content',
    ],
    harvestWindow: 'July through September',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to bacterial leaf spot and phytophthora in waterlogged soils. Rotate away from other solanaceous crops.',
  },

  Burpless: {
    name: 'Burpless',
    description:
      'Long, slender-skinned slicing cucumber bred for reduced cucurbitacin, producing mild fruit on vigorous trailing vines.',
    taste: 'Mild, crisp, and nearly bitterness-free with thin, edible skin. No peeling required.',
    features: ['50-60 days to maturity', '12-14 inch fruit', 'Thin skin, small seed cavity'],
    harvestWindow: 'June through August',
    chillHours: undefined,
    diseaseNotes:
      'Moderate powdery mildew tolerance. Susceptible to downy mildew and cucumber beetles, which vector bacterial wilt.',
  },

  'Black Beauty': {
    name: 'Black Beauty',
    description:
      'Prolific open-pollinated bush zucchini producing dark green, nearly black cylindrical fruit on compact, spineless plants.',
    taste:
      'Mild, tender flesh when harvested at 6-8 inches. Flavor deteriorates and seeds toughen if left to overgrow.',
    features: ['Bush habit', '50-55 days to maturity', 'Heavy producer'],
    harvestWindow: 'June through September',
    chillHours: undefined,
    diseaseNotes:
      'Highly susceptible to powdery mildew and squash vine borer. Monitor stems for frass starting in June.',
  },

  Delicata: {
    name: 'Delicata',
    description:
      'Small oblong winter squash with cream-and-green striped skin thin enough to eat. Compact semi-bush vines suit smaller gardens.',
    taste:
      'Sweet, nutty, chestnut-like flavor with creamy flesh that caramelizes well when roasted.',
    features: ['Bush-vine habit', '80-100 days to maturity', '1-2 lb fruit, edible skin'],
    harvestWindow: 'September through October',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to powdery mildew and squash vine borer. Less prone to vine borer than larger Cucurbita maxima types.',
  },

  'Trombetta di Albenga': {
    name: 'Trombetta di Albenga',
    description:
      'Italian heirloom climbing summer squash producing long, curved, trumpet-shaped pale green fruit on vigorous vines that benefit from trellising.',
    taste:
      'Sweet, nutty flavor superior to standard zucchini, with a dense, seedless bulb end. Best harvested at 12-18 inches.',
    features: ['Vigorous climber, needs trellis', '60-70 days to maturity', 'Unique trumpet shape'],
    harvestWindow: 'July through September',
    chillHours: undefined,
    diseaseNotes:
      'Good airflow from trellising reduces powdery mildew pressure. Less attractive to squash vine borer than bush types.',
  },

  "Heirloom Hale's Best Jumbo": {
    name: "Heirloom Hale's Best Jumbo",
    description:
      'Classic open-pollinated muskmelon discovered in a California field in 1923 and an heirloom standard ever since. Heavily netted, oval 3-5 lb fruit with deep salmon-orange flesh on vigorous, drought-tolerant vines.',
    taste:
      'Sweet, aromatic, old-fashioned cantaloupe flavor with juicy flesh; sweetest when allowed to slip fully from the vine.',
    features: [
      'Open-pollinated heirloom — seeds can be saved true',
      '85-90 days to maturity',
      '3-5 lb oval fruit with heavy netting',
      'More drought-tolerant than most modern hybrids',
    ],
    harvestWindow: 'Late July through early September',
    chillHours: undefined,
    diseaseNotes:
      'Little inherent disease resistance — susceptible to powdery mildew, downy mildew, and Fusarium wilt. Needs airflow, drip irrigation, and a preventive fungicide program in NC humidity.',
  },

  'Mini Sugar Cube': {
    name: 'Mini Sugar Cube',
    description:
      'Personal-sized hybrid cantaloupe producing 2-4 lb netted fruit with deep orange flesh on semi-compact vines.',
    taste: 'Intensely sweet, aromatic flesh with high brix. Ripe fruit slips easily from the vine.',
    features: [
      'Personal-sized 2-4 lb fruit',
      '75-80 days to maturity',
      'Strong netting, small seed cavity',
    ],
    harvestWindow: 'Late July through August',
    chillHours: undefined,
    diseaseNotes:
      'Intermediate resistance to powdery mildew. Susceptible to downy mildew and Fusarium wilt; avoid overhead watering.',
  },

  'Crimson Sweet': {
    name: 'Crimson Sweet',
    description:
      'The 1964 Kansas State release that became the benchmark American picnic watermelon. Round-oval 15-25 lb fruit with light green rind, dark stripes, and firm bright red flesh.',
    taste:
      'Crisp, very sweet (10-12% sugar) fine-grained red flesh with small seeds and a classic summer-melon finish.',
    features: [
      'Open-pollinated — seeds can be saved true',
      '80-85 days to maturity',
      '15-25 lb round-oval fruit',
      'AAS Winner; still the standard for home gardens',
    ],
    harvestWindow: 'Mid-July through August',
    chillHours: undefined,
    diseaseNotes:
      'Resistant to anthracnose and Fusarium wilt — one of the most disease-resistant open-pollinated melons. Watch for cucumber beetles and downy mildew late season.',
  },

  Jubilee: {
    name: 'Jubilee',
    description:
      'Florida-bred (1963) southern classic producing long, oblong 25-40 lb melons with a light green rind and dark green stripes, built for hot, humid summers.',
    taste:
      'Bright red, crisp, sweet flesh with the firm texture that made it a roadside-stand favorite across the Southeast.',
    features: [
      'Open-pollinated heirloom',
      '90-95 days to maturity',
      'Large oblong 25-40 lb fruit',
      'Excellent rind toughness — handles and keeps well',
    ],
    harvestWindow: 'Late July through early September',
    chillHours: undefined,
    diseaseNotes:
      'Resistant to Fusarium wilt and anthracnose race 1. Long season demands consistent moisture; mulch to deter blossom end rot.',
  },

  'Dolce Fresca': {
    name: 'Dolce Fresca',
    description:
      'Compact Genovese-type basil bred for prolonged harvest, maintaining bushy form and delaying bolting well into summer heat.',
    taste:
      'Classic sweet Italian basil flavor with strong clove and anise notes. Excellent for pesto.',
    features: ['Slow to bolt', 'Compact 12-24 inch mounding habit', '2016 AAS Winner'],
    harvestWindow: 'June through October',
    chillHours: undefined,
    diseaseNotes:
      'Improved tolerance to Fusarium wilt. Susceptible to downy mildew; avoid overhead irrigation and ensure airflow.',
  },

  Gorizia: {
    name: 'Gorizia',
    description:
      'Large-leaved Italian rosemary cultivar from the Friuli region, with broader, more pungent foliage than common upright types.',
    taste:
      'Robust, resinous rosemary flavor with strong pine and camphor notes. Excellent for roasting and hearty dishes.',
    features: ['Upright habit to 4-5 ft', 'Large broad leaves', 'Cold-hardy to Zone 7'],
    harvestWindow: 'Year-round (evergreen perennial in Zone 7b)',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to root rot in poorly drained clay soils. Ensure sharp drainage; raised beds recommended in Piedmont clay.',
  },

  Romaine: {
    name: 'Romaine',
    description:
      'Upright cos-type lettuce forming tall, tight heads with thick crunchy midribs and dark green outer leaves.',
    taste: 'Crisp, mildly sweet with a slight bitter edge. The standard for Caesar salads.',
    features: [
      '60-75 days to head maturity',
      'Cut-and-come-again harvesting possible',
      'Heat-tolerant varieties available',
    ],
    harvestWindow: 'March through May, September through November',
    chillHours: undefined,
    diseaseNotes:
      'Bolts quickly in summer heat above 80F. Susceptible to downy mildew, tipburn, and bottom rot in wet conditions.',
  },

  Kale: {
    name: 'Kale',
    description:
      'Cold-hardy brassica producing ruffled or flat blue-green leaves on upright stalks. Flavor sweetens markedly after frost.',
    taste:
      'Earthy, slightly peppery raw; sweet and tender when cooked or after exposure to freezing temperatures.',
    features: [
      '55-65 days to maturity',
      'Extremely cold-hardy',
      'Harvest outer leaves for continuous production',
    ],
    harvestWindow: 'October through March (fall/winter crop); spring crop March through May',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to cabbage worms, aphids, and harlequin bugs. Clubroot can be an issue in acidic Piedmont soils; lime to pH 6.5+.',
  },

  'Bowl of Cream': {
    name: 'Bowl of Cream',
    description:
      'Double herbaceous peony with large, pure white bomb-type blooms on strong stems that rarely need staking.',
    taste: 'Lightly fragrant with a clean, sweet scent.',
    features: ['Double bomb form', 'Strong stems', 'Mid-to-late season bloom'],
    harvestWindow: 'Late April through May',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to botrytis blight in wet springs. Remove spent blooms promptly; ensure good air circulation at crown.',
  },

  Gardenia: {
    name: 'Gardenia',
    description:
      'Double herbaceous peony with soft blush-pink buds opening to creamy white, densely petaled rose-form blooms.',
    taste: 'Sweet, moderate fragrance reminiscent of its namesake shrub.',
    features: ['Double rose form', 'Blush buds open white', 'Mid-season bloom'],
    harvestWindow: 'Late April through May',
    chillHours: undefined,
    diseaseNotes:
      'Prone to botrytis gray mold on buds in cool, wet weather. Avoid overhead irrigation during bloom.',
  },

  Hermione: {
    name: 'Hermione',
    description:
      'Double herbaceous peony with large, apple-blossom pink blooms that are deeply fragrant and hold well as cut flowers.',
    taste: 'Intense, old-rose fragrance. One of the most strongly scented herbaceous peonies.',
    features: ['Double form', 'Intensely fragrant', 'Mid-season bloom'],
    harvestWindow: 'Late April through May',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to botrytis blight; space plants for airflow and avoid mulching over the crown.',
  },

  'Sarah Bernhardt': {
    name: 'Sarah Bernhardt',
    description:
      'Classic double herbaceous peony with large, fully double rose-pink blooms. One of the most widely grown and dependable peony cultivars worldwide.',
    taste: 'Moderate sweet fragrance with a soft rose character.',
    features: ['Fully double rose-pink blooms', 'Excellent cut flower', 'Late-season bloom'],
    harvestWindow: 'May',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to botrytis blight. Heavy blooms may require support rings in rainy seasons. Generally vigorous and disease-tolerant.',
  },

  TIF419: {
    name: 'TIF419',
    description:
      'Fine-textured hybrid bermudagrass developed by the University of Georgia, producing a dense, dark green turf with excellent wear tolerance and reduced mowing frequency.',
    taste: 'N/A',
    features: [
      'Fine leaf texture',
      'Dense, low-growth habit',
      'Reduced mowing frequency vs. Tifway 419',
    ],
    harvestWindow: 'Active growth May through October (warm-season grass)',
    chillHours: undefined,
    diseaseNotes:
      'Susceptible to spring dead spot and large patch (Rhizoctonia) in Zone 7b. Avoid excessive nitrogen in fall to reduce disease pressure.',
  },
};
