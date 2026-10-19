// Comprehensive crop problem / disease / pest reference for GardenRX
// Zone 7b/8a — Holly Springs, NC
// Used for spray-decision guidance and problem identification

export interface CropProblem {
  name: string;
  type: 'disease' | 'insect' | 'cultural';
  description: string;
  symptoms: string;
  timing: string;
  conditions: string;
  remediation: string;
  products: string[];
  imageSearch: string;
  severity: 'high' | 'moderate' | 'low';
}

export const CROP_PROBLEMS: Record<string, CropProblem[]> = {
  // ═══════════════════════════════════════════════════════════════════
  // POME FRUIT (Apples, Pears, Crabapples, Quince, Asian Pears)
  // ═══════════════════════════════════════════════════════════════════
  'Pome Fruit': [
    {
      name: 'Apple Scab',
      type: 'disease',
      description:
        'Caused by the fungus Venturia inaequalis. The most important disease of apples in the Southeast. Overwinters in fallen leaves and releases ascospores during spring rains.',
      symptoms:
        'Olive-green to dark brown velvety lesions on leaves and fruit. Leaves may yellow and drop prematurely. Fruit lesions become corky and cracked, causing deformed fruit.',
      timing:
        'Primary infections March through May during green tip to petal fall. Secondary infections continue through summer. Critical window is tight cluster through 2nd cover spray.',
      conditions:
        'Requires leaf wetness and moderate temperatures (55-75°F). Classic infection periods: 9 hours of wetness at 61-75°F, 12+ hours at 50-60°F. Rain events are the primary driver.',
      remediation:
        'Protectant fungicides before rain events from green tip through 2nd cover. Captan is the backbone protectant. Myclobutanil (Immunox) is a curative/protectant for scab — apply within 72 hours of infection. Sulfur is effective as a protectant but avoid above 85°F. Remove fallen leaves in autumn. Choose resistant cultivars (Liberty, Enterprise, GoldRush).',
      products: ['Captan', 'Myclobutanil', 'Sulfur'],
      imageSearch: 'apple scab fungus lesions on leaves and fruit',
      severity: 'high',
    },
    {
      name: 'Cedar-Apple Rust',
      type: 'disease',
      description:
        'Caused by Gymnosporangium juniperi-virginianae. Requires two hosts — Eastern red cedar (Juniperus virginiana) and apple. Very common in NC where cedars are abundant. Galls on cedars release spores during warm spring rains.',
      symptoms:
        'Bright yellow-orange spots on upper leaf surfaces, often with a red border. Undersides develop tube-like projections (aecia). Fruit may develop similar lesions. Heavy infections cause premature defoliation.',
      timing:
        'Spore release from cedar galls April through mid-May, coinciding with bloom through petal fall. Infection period is narrow — roughly 4-6 weeks in spring.',
      conditions:
        'Warm spring rains (60-75°F) with gall wetting for 2+ hours. Proximity to Eastern red cedars greatly increases pressure. Spores can travel up to a mile.',
      remediation:
        'Myclobutanil (Immunox) is the most effective homeowner option — apply at pink bud, bloom, petal fall, and 1st cover. Captan has limited efficacy against rust. Remove nearby cedar galls in winter if possible. Choose resistant cultivars (Liberty, Freedom, Redfree).',
      products: ['Myclobutanil'],
      imageSearch: 'cedar apple rust orange spots on apple leaves',
      severity: 'high',
    },
    {
      name: 'Fire Blight',
      type: 'disease',
      description:
        'Caused by the bacterium Erwinia amylovora. Extremely destructive to apples and pears. Can kill entire trees. Bacteria enter through blossoms, wounds, and succulent shoot tips. Spread by rain splash, insects, and pruning tools.',
      symptoms:
        "Blossoms wilt and turn brown/black (blossom blight). Shoot tips curl into a characteristic 'shepherd's crook.' Bark appears water-soaked then darkens. Bacterial ooze (amber droplets) appears on infected tissue. Cankers form on branches and trunks.",
      timing:
        'Blossom blight risk peaks April during bloom. Shoot blight follows in May-June on actively growing terminals. Canker expansion occurs in warm weather.',
      conditions:
        'Warm temperatures (65°F+ daily average) during bloom with rain or heavy dew. Hail or wind damage creates entry points. Excess nitrogen fertilization promotes susceptible growth.',
      remediation:
        'Copper sprays at early green tip (delayed dormant) and again at 1/4-inch green. Do NOT spray copper after bloom begins — phytotoxic to open flowers. During bloom, streptomycin (Ferti-lome Fire Blight Spray) is the primary tool if available. Prune infected branches 12-18 inches below visible symptoms; sterilize tools with 10% bleach between cuts. Avoid excess nitrogen. Choose resistant cultivars (Enterprise, Liberty).',
      products: ['Copper'],
      imageSearch: 'fire blight shepherds crook apple tree branch',
      severity: 'high',
    },
    {
      name: 'Powdery Mildew',
      type: 'disease',
      description:
        'Caused by Podosphaera leucotricha. Overwinters in infected buds. Common on susceptible cultivars (Jonathan, Gala, Granny Smith). Unlike most fungi, does NOT require free water for infection.',
      symptoms:
        'White to grayish powdery coating on leaves, shoots, and blossoms. Infected leaves curl, become stunted, and may develop a silvery sheen. Fruit develops a net-like russet pattern. Terminal growth is often stunted.',
      timing:
        'Appears at tight cluster through petal fall from infected buds. Continues spreading on new growth April through July. Hot summers slow it down.',
      conditions:
        'Moderate temperatures (60-80°F) with high humidity but NOT rain — rain actually washes spores off. Shaded, crowded canopies with poor air circulation. Overcast days favor development.',
      remediation:
        'Myclobutanil (Immunox) is highly effective as both protectant and curative. Sulfur is a good protectant but avoid above 85°F and do not combine with oil sprays. Apply at tight cluster, pink, petal fall, and 1st-2nd cover. Prune to open canopy for air circulation.',
      products: ['Myclobutanil', 'Sulfur'],
      imageSearch: 'powdery mildew white coating on apple leaves',
      severity: 'moderate',
    },
    {
      name: 'Sooty Blotch & Flyspeck',
      type: 'disease',
      description:
        'A complex of fungi (Peltaster fructicola, Schizothyrium pomi, and others) that colonize the fruit surface. Cosmetic — does not penetrate flesh. Very common in humid Southeast summers. Often grouped together as SBFS.',
      symptoms:
        'Sooty blotch: dark, smudgy olive-green to black patches on fruit skin. Flyspeck: clusters of tiny, shiny black dots in circular or irregular patterns on fruit. Both are superficial and can be rubbed off.',
      timing:
        'Develops mid-summer through harvest (July-October). Becomes visible 3-4 weeks after infection. Cover sprays through mid-summer are critical.',
      conditions:
        'High humidity (prolonged dew periods of 8+ hours) and moderate temperatures (65-80°F). Poorly pruned trees with dense canopies. Shaded fruit, proximity to woods or hedgerows that block air movement.',
      remediation:
        'Captan cover sprays every 10-14 days from petal fall through mid-August are the primary control. Myclobutanil also effective. Thin canopy aggressively for air circulation. Remove nearby brush or hedgerows that impede airflow. Cosmetic only — fruit is perfectly edible; wipe off with a cloth and dilute bleach solution.',
      products: ['Captan', 'Myclobutanil'],
      imageSearch: 'sooty blotch flyspeck dark spots on apple fruit surface',
      severity: 'low',
    },
    {
      name: 'Bitter Rot',
      type: 'disease',
      description:
        'Caused by Colletotrichum spp. A warm-season fruit rot that is the most important summer disease of apples in the Southeast. Fungi overwinter in mummified fruit and cankers.',
      symptoms:
        'Sunken, tan to brown, circular lesions on fruit, often with concentric rings. Lesions expand rapidly in warm weather. Salmon to pink spore masses form in moist conditions. Internally, flesh is brown and V-shaped in cross section.',
      timing:
        'Infections begin June-July as fruit size increases. Symptoms appear July-September. Warm, wet summers dramatically increase incidence. Most critical late June through harvest.',
      conditions:
        'Hot, humid weather (80°F+) with frequent rain. Inoculum from old mummified fruit hanging in tree or on ground. Southern and southeastern exposures of fruit most affected.',
      remediation:
        'Captan cover sprays every 10-14 days from 2nd cover through harvest, especially during hot, humid periods. Myclobutanil is NOT effective against Colletotrichum. Remove mummified fruit and prune out cankers in winter. Promote rapid drying through canopy management.',
      products: ['Captan'],
      imageSearch: 'bitter rot apple concentric rings brown lesion',
      severity: 'high',
    },
    {
      name: 'Codling Moth',
      type: 'insect',
      description:
        "Cydia pomonella. The classic 'worm in the apple.' Larvae bore into fruit, feeding at the core. Overwinters as mature larvae in cocoons under loose bark. Two generations per year in Zone 7b/8a.",
      symptoms:
        'Entry holes on fruit surface, often near the calyx or stem end, with reddish-brown frass (excrement) pushed out. Tunnels lead to the seed cavity. Fruit drops prematurely. Cut fruit reveals larval tunnels and brown excrement.',
      timing:
        'First flight (adults) mid-April to May; first generation larvae enter fruit late May-June. Second flight July; second generation larvae enter fruit August-September. Time first spray 250 degree-days (base 50°F) after first sustained moth catch.',
      conditions:
        'Warmer springs lead to earlier emergence. Unsprayed orchards near wild or abandoned apple trees have high pressure. Pheromone traps help time sprays.',
      remediation:
        'Carbaryl (Sevin) applied at 1st and 2nd cover sprays (10-14 days after petal fall, then 10-14 days later). Repeat for second generation in mid-July. Do NOT spray Sevin during bloom — toxic to bees. Kaolin clay (Surround) is an organic barrier option. Hang codling moth traps to time sprays. Remove and destroy dropped fruit promptly.',
      products: ['Carbaryl'],
      imageSearch: 'codling moth larva damage inside apple fruit',
      severity: 'high',
    },
    {
      name: 'Plum Curculio',
      type: 'insect',
      description:
        'Conotrachelus nenuphar. A snout beetle and the most damaging insect pest of tree fruit in the eastern US. Adults emerge from soil in spring and move to trees at petal fall to feed and lay eggs in developing fruit.',
      symptoms:
        'Crescent-shaped egg-laying scars on fruit — the signature mark. Larvae feed inside fruit causing internal damage and premature fruit drop. Fruit may have bumpy, misshapen surface from healed feeding punctures.',
      timing:
        'Adults active from petal fall through about 3 weeks after (mid-April through mid-May). Critical spray window is immediately at petal fall and 7-10 days later. A single generation per year in most of NC.',
      conditions:
        'Adults become active when evening temperatures reach 60°F+. Most active on warm, calm evenings. Emerge from soil under trees and nearby woods. Highest pressure near wooded edges.',
      remediation:
        'Carbaryl (Sevin) at petal fall and 10 days later is the standard homeowner control. This is the single most important insect spray for tree fruit. Do NOT spray during bloom. Pick up and destroy dropped fruit (which contain larvae). Trunk traps and jarring branches onto a white sheet can monitor populations.',
      products: ['Carbaryl'],
      imageSearch: 'plum curculio crescent shaped scar on apple fruit',
      severity: 'high',
    },
    {
      name: 'Apple Maggot',
      type: 'insect',
      description:
        'Rhagoletis pomonella. Fly lays eggs under apple skin; larvae tunnel through flesh creating brown, winding trails. Pupae overwinter in soil. More of a late-season pest. One generation per year.',
      symptoms:
        'Tiny puncture marks on fruit surface from egg laying. Internal tunnels appear as brown, winding trails through the flesh. Fruit may be dimpled and misshapen. Flesh breaks down around tunnels creating soft, mushy areas.',
      timing:
        'Adults emerge late June-July and are active through September. Egg-laying peaks July-August. Late-maturing cultivars are most affected. Red sticky sphere traps deployed by late June monitor emergence.',
      conditions:
        'Proximity to wild or abandoned apple trees is the biggest risk factor. Adults are attracted to fruit by visual cues (round, red objects). Warm, humid summers.',
      remediation:
        'Carbaryl (Sevin) cover sprays in July-August (every 10-14 days) when traps catch flies. Red sticky sphere traps (1-2 per tree) both monitor and trap adults. Bag individual fruit with footie socks or paper bags after June drop for complete protection without spraying. Remove nearby wild apple trees.',
      products: ['Carbaryl'],
      imageSearch: 'apple maggot fly damage brown trails inside apple flesh',
      severity: 'moderate',
    },
    {
      name: 'Japanese Beetles',
      type: 'insect',
      description:
        'Popillia japonica. Metallic green and copper beetles that feed gregariously on foliage of many plants. Adults emerge from turf in late June and feed for 6-8 weeks. Extremely common in the NC Piedmont.',
      symptoms:
        'Skeletonized leaves — beetles eat tissue between veins leaving a lace-like pattern. Aggregation pheromones cause heavy feeding on individual branches. Can defoliate young trees. Also feed directly on ripening fruit.',
      timing:
        'Adults emerge late June, peak feeding in July, taper off by mid-August. Grubs feed on turf roots the prior fall and spring.',
      conditions:
        'Worst in areas with irrigated lawns or turf nearby (grubs thrive in moist soil). Warm, sunny days trigger feeding. Beetles aggregate — damage is patchy but intense.',
      remediation:
        'Carbaryl (Sevin) is highly effective as a foliar spray — kills on contact and provides 1-2 weeks residual. Spray when beetles are actively feeding (morning is best). Do NOT use Japanese beetle bag traps near the orchard — they attract more beetles than they catch. Hand-pick into soapy water for small infestations. Treat lawn grubs with milky spore or beneficial nematodes for long-term reduction.',
      products: ['Carbaryl'],
      imageSearch: 'japanese beetle skeletonized apple tree leaves feeding damage',
      severity: 'moderate',
    },
  ],

  // ═══════════════════════════════════════════════════════════════════
  // STONE FRUIT (Peaches, Nectarines, Plums, Cherries, Apricots)
  // ═══════════════════════════════════════════════════════════════════
  'Stone Fruit': [
    {
      name: 'Brown Rot',
      type: 'disease',
      description:
        'Caused by Monilinia fructicola. The most destructive disease of stone fruit in the Southeast. Attacks blossoms (blossom blight) and ripening fruit (fruit rot). Overwinters in mummified fruit and twig cankers.',
      symptoms:
        'Blossom blight: flowers turn brown and collapse; brown cankers form on twigs with gummy ooze. Fruit rot: rapidly expanding brown, soft lesions covered with tan to gray powdery spore tufts. Entire fruit can rot in 2-3 days in warm, wet weather. Mummified fruit hang on tree.',
      timing:
        'Blossom blight risk during bloom (March-April). Fruit rot intensifies 3-4 weeks before harvest as fruit ripens and sugars increase (June-August depending on cultivar). Two critical spray windows: bloom and pre-harvest.',
      conditions:
        'Warm, wet weather (70-80°F) with rain during bloom. High humidity and rain near harvest. Insects wounds on fruit provide entry points. Dense canopy traps moisture.',
      remediation:
        'Captan or Myclobutanil (Immunox) at pink bud, full bloom, and petal fall for blossom blight. Pre-harvest sprays: Captan at 3 weeks, 2 weeks, and 1 week before harvest (check PHI — Captan 0 days on peaches). Myclobutanil is systemic and highly effective. Remove and destroy mummified fruit in winter. Prune for open center to promote air circulation.',
      products: ['Captan', 'Myclobutanil'],
      imageSearch: 'brown rot monilinia peach fruit tan spore tufts',
      severity: 'high',
    },
    {
      name: 'Peach Leaf Curl',
      type: 'disease',
      description:
        'Caused by Taphrina deformans. Affects peaches and nectarines. Fungus overwinters on bud scales and bark. Infection occurs during bud swell — once leaves emerge, the window has passed. A single well-timed dormant spray prevents it entirely.',
      symptoms:
        'Leaves emerge puckered, thickened, and curled with red, pink, or yellow discoloration. Severely affected leaves turn brown and drop. Tree produces a second flush of normal leaves but is weakened. Repeated annual infections can reduce vigor and yield significantly.',
      timing:
        'Infection occurs during bud swell in late winter (February-early March in Zone 7b). By the time symptoms appear (April), it is too late to treat. Spray window is narrow: after leaf drop in fall or before bud swell in late winter.',
      conditions:
        'Cool, wet weather (50-70°F) during bud swell drives infection. Warm, dry springs have much less curl. Rain during bud swell is the key trigger.',
      remediation:
        'A SINGLE dormant spray of Copper (fixed copper like Bonide Copper Fungicide) or Copper + Sulfur in late January to mid-February (before bud swell) is highly effective. Chlorothalonil (Daconil) also works as a dormant spray. Once symptoms appear, there is NO curative treatment — remove affected leaves if limited, fertilize lightly, and water to support the second leaf flush. Must spray EVERY year as a preventive.',
      products: ['Copper', 'Sulfur'],
      imageSearch: 'peach leaf curl taphrina red puckered distorted leaves',
      severity: 'high',
    },
    {
      name: 'Bacterial Spot',
      type: 'disease',
      description:
        'Caused by Xanthomonas arboricola pv. pruni. Affects peaches, nectarines, and plums. Extremely common in the humid Southeast. Bacteria overwinter in cankers and leaf scars. Nectarines are more susceptible than peaches.',
      symptoms:
        "Small, angular, water-soaked spots on leaves that turn brown/purple and fall out leaving a 'shot-hole' appearance. Fruit lesions start as small water-soaked spots that become sunken, dark, and cracked. Twig cankers appear as dark, sunken areas.",
      timing:
        'Symptoms appear May-July as temperatures and rainfall increase. Worst during warm, rainy periods. Fruit symptoms appear closer to harvest.',
      conditions:
        'Warm temperatures (75-85°F), wind-driven rain, and sandy soils (low pH). Splashing rain spreads bacteria. Windbreaks help. Southeast NC is a hot spot for this disease.',
      remediation:
        'Copper sprays at leaf fall (November) and again at delayed dormant (late February) before bud swell. Do NOT spray copper after shuck split — phytotoxic to foliage and fruit. Myclobutanil is NOT effective (bacterial, not fungal). Oxytetracycline (Mycoshield) is an option in commercial orchards. Choose resistant cultivars (Contender, Redhaven have some tolerance). Avoid overhead irrigation. No cure during growing season — prevention is key.',
      products: ['Copper'],
      imageSearch: 'bacterial spot xanthomonas peach leaf shot hole and fruit lesions',
      severity: 'high',
    },
    {
      name: 'Black Knot',
      type: 'disease',
      description:
        'Caused by Apiosporina morbosa (syn. Dibotryon morbosum). Primarily affects plums and cherries. Fungus produces distinctive black, hard, elongated galls on branches. Spreads by spores released during spring rains.',
      symptoms:
        'Hard, rough, black swellings (knots) that encircle branches. New infections start as olive-green soft swellings in late spring, hardening and darkening over the following year. Girdled branches die beyond the knot. Severe infections can kill trees.',
      timing:
        'Spore release occurs during rainy periods from green tip through bloom (March-May). Galls become visible the following growing season — the disease has a long latency period. Prune out knots in winter.',
      conditions:
        'Warm, wet spring weather. Proximity to wild plums or cherries with existing infections is a major inoculum source. New infections establish during rain events when temperatures are 55-77°F.',
      remediation:
        'Prune out knots in winter, cutting at least 4-6 inches below visible gall into healthy wood. Burn or discard prunings — do NOT compost. Captan or Sulfur sprays from white bud through shuck fall help prevent new infections. Myclobutanil may provide some suppression. Remove wild plums/cherries within 600 feet if possible. Badly infected trees should be removed entirely.',
      products: ['Captan', 'Sulfur', 'Myclobutanil'],
      imageSearch: 'black knot disease hard black gall on plum branch',
      severity: 'high',
    },
    {
      name: 'Cherry Leaf Spot',
      type: 'disease',
      description:
        'Caused by Blumeriella jaapii. Primarily affects tart and sweet cherries. Causes premature defoliation which weakens trees and reduces winter hardiness. Very common in humid eastern climates.',
      symptoms:
        'Small, round, purple to reddish-brown spots on upper leaf surface. Spots may merge into larger necrotic areas. Infected leaves yellow and drop prematurely — severely affected trees may be nearly defoliated by mid-summer. White to pink spore masses on leaf undersides.',
      timing:
        'Symptoms appear May-June, 1-2 weeks after petal fall. Defoliation peaks July-August. Spores spread by rain splash throughout the growing season.',
      conditions:
        'Warm, wet weather (60-80°F) with frequent rain. Extended leaf wetness periods. Heavy dews in summer.',
      remediation:
        'Captan sprays at petal fall, shuck fall, and then every 10-14 days through mid-summer. Myclobutanil (Immunox) is also effective and provides curative activity. Copper at delayed dormant helps reduce overwintering inoculum. Rake and destroy fallen leaves in autumn.',
      products: ['Captan', 'Myclobutanil', 'Copper'],
      imageSearch: 'cherry leaf spot blumeriella purple spots defoliation',
      severity: 'moderate',
    },
    {
      name: 'Oriental Fruit Moth',
      type: 'insect',
      description:
        'Grapholita molesta. A major pest of peaches in the Southeast. Larvae bore into shoot tips (first generation) and fruit (later generations). Three to four generations per year in NC. Overwinters as larvae in cocoons on the tree or in soil debris.',
      symptoms:
        'First generation: wilted, flagging shoot tips with larvae boring inside — similar to peach twig borer. Later generations: larvae enter fruit near the stem end, boring to the pit. Entry holes with frass on fruit. Internal feeding causes fruit breakdown.',
      timing:
        'First generation adults fly March-April; shoot tip damage April-May. Second generation June; fruit entry begins. Third generation July-August targets ripening fruit. Pheromone traps help time sprays — treat 10-14 days after sustained trap catch.',
      conditions:
        'Warm springs lead to early emergence. Multiple generations mean continuous pressure. Proximity to abandoned peach trees increases pressure.',
      remediation:
        'Carbaryl (Sevin) at petal fall and cover sprays targeting each generation. Critical timing is 10-14 days after peak trap catch for each generation. Do not spray during bloom. Remove water sprouts and suckers which attract egg-laying. Mating disruption with pheromone twist-ties is effective in larger plantings.',
      products: ['Carbaryl'],
      imageSearch: 'oriental fruit moth larva damage peach shoot tip wilting',
      severity: 'high',
    },
    {
      name: 'Plum Curculio',
      type: 'insect',
      description:
        'Conotrachelus nenuphar. The most important insect pest of stone fruit in the eastern US. Adults feed and lay eggs in developing fruit shortly after petal fall. Larvae develop inside fruit and exit to pupate in soil.',
      symptoms:
        "Crescent-shaped egg-laying scars on fruit surface — the diagnostic sign. Larvae feed inside, causing internal browning and often premature fruit drop ('June drop' is partially curculio-related). Adults also make small circular feeding punctures.",
      timing:
        'Adults emerge at petal fall when evening temperatures exceed 60°F (mid-April in Zone 7b). Most egg-laying occurs within 2-3 weeks of petal fall. The petal fall + 10-day cover spray window is critical.',
      conditions:
        'Warm, calm evenings above 60°F trigger movement into trees. Adults migrate from surrounding woods and brush. Heaviest pressure near forest edges.',
      remediation:
        'Carbaryl (Sevin) at petal fall is the single most important insect spray for stone fruit. Repeat 10-14 days later. Do NOT spray during bloom — lethal to pollinators. Collect and destroy dropped fruit (contain developing larvae). Tarp under tree and jar branches to monitor adult presence.',
      products: ['Carbaryl'],
      imageSearch: 'plum curculio crescent scar on peach fruit surface',
      severity: 'high',
    },
    {
      name: 'Japanese Beetles',
      type: 'insect',
      description:
        'Popillia japonica. Feed on foliage and ripening fruit of stone fruit, especially peaches and plums. Heavy feeding can defoliate young trees and damage ripe fruit at harvest time.',
      symptoms:
        'Skeletonized leaves with only veins remaining. Beetles feed in groups, often starting at the top of the canopy. Direct feeding damage on ripening fruit — ragged holes in skin exposing flesh, leading to secondary brown rot infection.',
      timing:
        'Adults emerge late June, peak July, decline by mid-August. Fruit damage worst on early-ripening cultivars whose harvest overlaps beetle peak.',
      conditions:
        'Warm, sunny days. Areas with well-watered turf (grub habitat). Beetles aggregate via pheromones, creating intense localized damage.',
      remediation:
        'Carbaryl (Sevin) is very effective — spray when beetles are present, provides 1-2 weeks residual. Observe pre-harvest interval (PHI: 3 days for peaches with Sevin). Avoid Japanese beetle bag traps near trees. Hand-pick into soapy water. Treat lawn grubs with milky spore disease or beneficial nematodes (Heterorhabditis bacteriophora).',
      products: ['Carbaryl'],
      imageSearch: 'japanese beetle feeding damage on peach tree leaves and fruit',
      severity: 'moderate',
    },
  ],

  // ═══════════════════════════════════════════════════════════════════
  // SMALL FRUIT (Blueberries, Raspberries, Blackberries, Strawberries)
  // ═══════════════════════════════════════════════════════════════════
  Berries: [
    {
      name: 'Mummy Berry',
      type: 'disease',
      description:
        'Caused by Monilinia vaccinii-corymbosi. The most important disease of blueberries in the Southeast. Fungus overwinters in mummified berries on the ground. Two phases: shoot strike (primary) and fruit infection (secondary).',
      symptoms:
        "Shoot strike: newly emerging leaves and shoots wilt, turn brown, and curl — resembles frost damage. Fruit infection: berries appear healthy externally but turn tan/salmon-pink inside, become hard and shriveled, falling to the ground as 'mummies.'",
      timing:
        'Shoot strike phase: March-April during bud break. Fruit infection phase: during bloom (April-May) when apothecia release ascospores that land on open flowers. Conidia from blighted shoots also infect flowers.',
      conditions:
        'Cool, moist conditions during bud break and bloom. Mummified berries on the soil surface from previous season. Mulch can inhibit apothecia but does not eliminate them.',
      remediation:
        'Captan at early bloom, full bloom, and petal fall. Myclobutanil can also be used. Rake and remove mummified berries in winter or add 2+ inches of fresh mulch to bury them before spring. Avoid overhead irrigation during bloom. Sulfur has some protectant activity. Choose resistant cultivars where possible.',
      products: ['Captan', 'Myclobutanil', 'Sulfur'],
      imageSearch: 'mummy berry blueberry shriveled hard fruit and shoot blight',
      severity: 'high',
    },
    {
      name: 'Anthracnose (Ripe Rot)',
      type: 'disease',
      description:
        'Caused by Colletotrichum spp. Affects blueberries, strawberries, raspberries, and blackberries. Causes fruit rot at or near harvest. Fungus overwinters in dead canes, twigs, and old fruit. Very common in the warm, humid Southeast.',
      symptoms:
        'Blueberries: soft, sunken lesions on ripening fruit with orange spore masses. Strawberries: firm, sunken dark spots on fruit. Brambles: lesions on canes (gray centers with purple margins), fruit rot. Leaves may have small spots.',
      timing:
        'Infections occur during bloom and green fruit stage (April-May) but symptoms do not appear until fruit ripens (June-July). Latent infections are common — fruit looks fine until it begins to color.',
      conditions:
        'Warm, wet weather (75-85°F) during bloom and fruit development. Overhead irrigation, rain splash, dense plantings with poor air circulation.',
      remediation:
        'Captan sprays at bloom, petal fall, and pre-harvest (observe PHI — 0 days for Captan on most berries). Remove and destroy infected fruit. Prune out dead and diseased canes in winter. Promote air circulation by proper spacing and pruning. Copper at dormant can reduce overwintering inoculum on canes.',
      products: ['Captan', 'Copper'],
      imageSearch: 'anthracnose colletotrichum ripe rot blueberry orange spore mass',
      severity: 'high',
    },
    {
      name: 'Botrytis Gray Mold',
      type: 'disease',
      description:
        'Caused by Botrytis cinerea. Affects strawberries, blueberries, and brambles. The most important disease of strawberries in wet years. Ubiquitous fungus that attacks senescing tissue, wounded fruit, and blooms.',
      symptoms:
        'Fuzzy gray mold growth on fruit, especially at soil contact points (strawberries) or in tight clusters (blueberries). Fruit becomes soft and watery, then covered in gray spores. Blossoms turn brown and collapse. Entire berry clusters can rot.',
      timing:
        'Bloom through harvest (April-June for strawberries, May-July for blueberries and brambles). Worst during prolonged wet periods at or near harvest.',
      conditions:
        'Cool to moderate temperatures (60-77°F) with high humidity and rain. Poor air circulation. Dense plant canopy. Overripe or damaged fruit. Straw mulch under strawberries helps reduce soil splash but can harbor spores.',
      remediation:
        'Captan sprays at early bloom, full bloom, and petal fall. Space plants for good air circulation. Remove overripe and damaged fruit promptly. Use straw mulch (strawberries) or landscape fabric to reduce soil splash. Avoid overhead irrigation during bloom and ripening. Harvest frequently — do not leave ripe fruit on the plant.',
      products: ['Captan'],
      imageSearch: 'botrytis gray mold fuzzy strawberry fruit rot',
      severity: 'high',
    },
    {
      name: 'Spotted Wing Drosophila (SWD)',
      type: 'insect',
      description:
        'Drosophila suzukii. An invasive vinegar fly from Asia that lays eggs in RIPE, undamaged fruit (unlike native vinegar flies that only attack damaged fruit). A devastating pest of all soft fruit. Females have a serrated ovipositor that cuts into intact fruit skin.',
      symptoms:
        'Small, soft depressions on fruit surface where eggs are laid. Fruit becomes soft and collapses. Small white larvae visible inside fruit when broken open. Fruit may appear slightly sunken or have tiny holes. Secondary fungal infections follow. Juice leaks from damaged areas.',
      timing:
        'Adults active from late May through November in NC. Population builds through summer, peaking in August-September. Most damaging on mid- and late-season fruit. Early-ripening cultivars often escape the worst pressure.',
      conditions:
        'Moderate temperatures (68-86°F). Shade and high humidity favor adult survival. Worst in late summer. Fruit with higher sugar content is more attractive. Adjacent woods or shaded areas harbor adults.',
      remediation:
        "Carbaryl (Sevin) applied when fruit begins to color, every 7 days through harvest (observe PHI: 7 days for blueberries, 1 day for strawberries). Monitor with apple cider vinegar traps. Harvest frequently and completely — leave no ripe fruit. Refrigerate immediately after picking. Remove wild brambles nearby. Exclude with fine mesh netting (< 1mm openings). Spinosad (Captain Jack's) is an organic option for SWD.",
      products: ['Carbaryl'],
      imageSearch: 'spotted wing drosophila SWD larvae in blueberry raspberry',
      severity: 'high',
    },
    {
      name: 'Phytophthora Root Rot',
      type: 'disease',
      description:
        'Caused by Phytophthora cinnamomi and other Phytophthora species. Affects blueberries, strawberries, and brambles. A water mold that thrives in poorly drained soils. Kills roots, leading to plant decline and death.',
      symptoms:
        'Gradual plant decline: stunted growth, small pale leaves, marginal leaf scorch, poor fruit production. Roots are brown/black and rotted (healthy roots are white). Plants wilt even when soil is moist. Crown may show brown internal discoloration. Often kills plants in patches in low spots.',
      timing:
        'Symptoms appear spring through summer, often becoming severe during hot, dry weather when compromised roots cannot supply water. Root infection occurs during wet periods — fall and spring rains.',
      conditions:
        'Poorly drained, heavy clay soils (common in NC Piedmont). Overwatering. Low spots where water collects. Raised beds dramatically reduce risk for blueberries. Acidic soil conditions.',
      remediation:
        'Prevention is critical — plant in raised beds or well-drained sites. Ensure proper drainage before planting. No chemical cure once established; phosphorous acid products (Agri-Fos) can help prevent spread to adjacent plants. Remove and destroy dead plants (do not replant in same spot). Copper drenches have limited preventive value. Pine bark mulch improves drainage around blueberries.',
      products: ['Copper'],
      imageSearch: 'phytophthora root rot blueberry wilting brown roots',
      severity: 'high',
    },
    {
      name: 'Cane Blight',
      type: 'disease',
      description:
        'Caused by Leptosphaeria coniothyrium. Affects raspberries and blackberries. Enters through wounds (pruning cuts, insect damage, mechanical injury). Causes dieback of fruiting canes.',
      symptoms:
        'Large brown to dark-brown cankers on canes, starting at wound sites. Cankers may girdle canes, causing wilting and death of lateral branches above the canker. Dark streaking visible in the pith when cane is cut open. Fruiting laterals wilt during berry development.',
      timing:
        'Infection occurs spring through summer through wounds. Symptoms appear late spring through summer when fruiting canes begin to wilt. Most visible during fruit development (June-July).',
      conditions:
        'Rainy periods following pruning or mechanical damage. Wounds from insects, hail, or improper pruning. Dense plantings with poor air circulation.',
      remediation:
        'Prune during dry weather. Make clean cuts with sharp, sterilized tools. Remove and destroy infected canes immediately. Copper spray at delayed dormant (late February) helps prevent new infections. Apply Captan at early bloom if cane blight has been a problem. Improve air circulation by proper spacing and trellis training.',
      products: ['Copper', 'Captan'],
      imageSearch: 'cane blight leptosphaeria raspberry blackberry brown canker',
      severity: 'moderate',
    },
    {
      name: 'Spider Mites',
      type: 'insect',
      description:
        'Primarily Tetranychus urticae (two-spotted spider mite). Tiny arachnids that feed on leaf undersides, sucking cell contents. Not technically insects but managed similarly. Populations explode in hot, dry conditions. Broad-spectrum insecticide use can worsen outbreaks by killing natural predators.',
      symptoms:
        'Fine stippling (tiny yellow/white dots) on upper leaf surface. Leaves may turn bronze, yellow, or brown. Fine webbing on leaf undersides in heavy infestations. Leaves dry and drop in severe cases. Hold a white sheet of paper under leaves and tap — mites appear as tiny moving dots.',
      timing:
        'Populations build June-August, peaking in hot, dry midsummer. Can appear as early as May in warm years. Worst during drought conditions.',
      conditions:
        'Hot, dry weather (85°F+) with low humidity. Dusty conditions along roads or paths. Overuse of broad-spectrum insecticides (especially carbaryl and pyrethroids) that kill predatory mites. Water stress on plants.',
      remediation:
        'Strong water sprays to leaf undersides knock off mites and break webbing. Sulfur has miticidal activity — apply every 7-10 days (avoid above 85°F). Insecticidal soap or horticultural oil (summer rate) are effective. AVOID Carbaryl (Sevin) near mite-prone plants — it kills predator mites and causes mite flares. Introduce predatory mites (Phytoseiulus persimilis). Maintain adequate irrigation to reduce plant stress.',
      products: ['Sulfur'],
      imageSearch: 'two spotted spider mite stippling webbing on berry leaves',
      severity: 'moderate',
    },
  ],

  // ═══════════════════════════════════════════════════════════════════
  // GRAPES (Bunch Grapes, Muscadine Grapes, Table Grapes)
  // ═══════════════════════════════════════════════════════════════════
  Grapes: [
    {
      name: 'Black Rot',
      type: 'disease',
      description:
        'Caused by Guignardia bidwellii. The most destructive grape disease in the Southeast. Overwinters in mummified berries and infected cane tissue. Extremely common and can destroy entire crops if unmanaged.',
      symptoms:
        'Leaf spots: tan circular lesions with dark brown borders and tiny black pycnidia (spore-producing structures) visible with a hand lens. Fruit rot: berries turn brown, shrivel, and harden into black mummies. Infection spreads rapidly through a cluster once started. Tendrils and cane lesions also occur.',
      timing:
        'Infections begin at bud break (March) and continue through veraison. Most critical spray window is immediate pre-bloom through 4 weeks post-bloom (late April through mid-June). Berries become resistant to infection as they ripen (after veraison).',
      conditions:
        'Warm (60-90°F), wet conditions with leaf wetness of 6+ hours. Rain is the primary spore dispersal mechanism. Mummified berries on the ground or in the vine are the primary inoculum source.',
      remediation:
        'Myclobutanil (Immunox) is the most effective homeowner fungicide for black rot — apply at immediate pre-bloom, bloom, and 2 post-bloom sprays at 10-14 day intervals. Captan also provides good protectant activity. Remove ALL mummified berries in winter sanitation — this is critical. Drop infected clusters during the season. Prune for open canopy and air circulation. Sulfur has limited activity against black rot.',
      products: ['Myclobutanil', 'Captan'],
      imageSearch: 'grape black rot guignardia mummified berries and leaf spots',
      severity: 'high',
    },
    {
      name: 'Downy Mildew',
      type: 'disease',
      description:
        'Caused by Plasmopara viticola. An oomycete (water mold) that affects all green parts of the vine. Especially severe on American and hybrid grapes. Muscadine grapes have moderate resistance. Overwinters in fallen leaves.',
      symptoms:
        "Upper leaf surface: yellow, oily-looking spots ('oil spots'). Lower leaf surface: white, cottony sporulation corresponding to spots above. Severe infections cause defoliation. Infected shoot tips and tendrils turn brown and curl. Young berries turn gray-brown and shrivel ('gray rot' phase).",
      timing:
        'Primary infections begin shortly after bud break (April) when soil temperatures reach 50°F and rain splashes spores onto new growth. Continues through the growing season. Worst May-July.',
      conditions:
        'Warm (60-80°F), wet weather with prolonged leaf wetness (overnight rain, heavy dew). Frequent rainfall and high humidity. Poor canopy management trapping moisture. Splashing rain from soil is primary spore source.',
      remediation:
        'Copper-based fungicides are the backbone of downy mildew control. Apply at 6-8 inch shoot growth, pre-bloom, post-bloom, and every 10-14 days during wet weather. Captan also provides good activity. Myclobutanil is NOT effective against downy mildew (it is an oomycete, not a true fungus). Open canopy through shoot positioning and leaf removal in the fruiting zone. Remove leaves around clusters for air circulation.',
      products: ['Copper', 'Captan'],
      imageSearch: 'grape downy mildew plasmopara oil spots white sporulation underside',
      severity: 'high',
    },
    {
      name: 'Powdery Mildew',
      type: 'disease',
      description:
        'Caused by Erysiphe necator (syn. Uncinula necator). Affects all cultivated grape varieties. Unlike downy mildew, does NOT require free water — grows in warm, dry, humid conditions. Overwinters in dormant buds and bark crevices.',
      symptoms:
        'White to gray powdery coating on upper and lower leaf surfaces, shoots, and fruit. Infected berries may crack or split, especially as they size, leading to secondary Botrytis or sour rot. Young shoots show stunted, distorted growth. Severe leaf infection causes premature defoliation.',
      timing:
        'Appears as early as bud break from infected buds. Most active May-August. Sprays needed from 6-8 inch shoot growth through veraison. Berry infection that occurs at bloom through pea-size is most damaging.',
      conditions:
        'Moderate temperatures (68-86°F) and high humidity (but NOT rain — rain inhibits spore germination). Shaded fruit zones and dense canopies. Warm, overcast days with poor air movement.',
      remediation:
        'Sulfur is the classic and highly effective protectant — apply every 10-14 days from 6-inch shoot growth through veraison. Avoid sulfur above 85°F (phytotoxic) and on sulfur-sensitive cultivars (Concord). Myclobutanil (Immunox) provides excellent curative and protectant activity. Canopy management — shoot positioning, leaf removal in fruit zone — is essential to reduce humidity around clusters.',
      products: ['Sulfur', 'Myclobutanil'],
      imageSearch: 'grape powdery mildew erysiphe white coating on berries and leaves',
      severity: 'high',
    },
    {
      name: 'Botrytis Bunch Rot',
      type: 'disease',
      description:
        'Caused by Botrytis cinerea. Attacks grape clusters, especially tight-clustered cultivars. Enters through wounds (insect damage, hail, powdery mildew cracks) and senescing floral parts. Can devastate crops in wet harvest seasons.',
      symptoms:
        'Gray-brown fuzzy mold enveloping individual berries and spreading through the cluster. Berries become soft, watery, and brown. In tight clusters, rot spreads by berry-to-berry contact. Entire clusters can be lost. Sometimes secondary sour rot organisms colonize Botrytis-damaged tissue.',
      timing:
        'Bloom-time infections remain latent until veraison. Visible symptoms appear at veraison through harvest (August-October). Worst during wet weather near harvest.',
      conditions:
        'Cool to moderate temperatures (59-77°F), high humidity, and rain during ripening. Tight clusters, thick canopy, and poor air circulation. Wounds from insects, hail, or berry cracking. Cultivars with tight clusters (e.g., Vignoles, Pinot Noir) are highly susceptible.',
      remediation:
        'Captan sprays at bloom and pre-bunch closure (when berries touch in the cluster). Improve air circulation by leaf removal in the fruit zone (pull leaves around clusters after fruit set). Shoot position for vertical canopy. Thin clusters on susceptible cultivars to reduce tightness. Remove damaged or infected clusters promptly. Avoid overhead irrigation.',
      products: ['Captan'],
      imageSearch: 'botrytis bunch rot gray mold fuzzy grape cluster',
      severity: 'high',
    },
    {
      name: 'Phomopsis Cane and Leaf Spot',
      type: 'disease',
      description:
        'Caused by Phomopsis viticola. Common in the Southeast, especially in wet springs. Affects canes, leaves, and fruit. Overwinters in infected cane tissue. Causes cane lesions that weaken fruiting wood.',
      symptoms:
        'Cane lesions: dark brown to black, elongated lesions on the basal internodes of new shoots, often cracking. Leaf spots: small, yellow spots with dark centers on young leaves. Fruit: brown, shriveled berries late in the season. Cane lesions weaken wood, leading to breakage.',
      timing:
        'Infections occur primarily from bud break through 3-4 weeks post-bud break (March-April) when new shoots are most susceptible. Cane lesions become visible by May-June. Fruit symptoms appear near harvest.',
      conditions:
        'Cool, rainy weather during early shoot growth (50-68°F with rain). Splashing rain from infected cane debris. Dense, untrained canopies.',
      remediation:
        'Captan or Copper at bud break and 1-2 weeks later during the rapid shoot growth phase. This is primarily an early-season disease — cover sprays later in the season target other diseases. Prune out infected canes during dormant pruning. Bury or destroy pruning debris. Good canopy management reduces disease pressure.',
      products: ['Captan', 'Copper'],
      imageSearch: 'phomopsis cane leaf spot grape dark basal cane lesion',
      severity: 'moderate',
    },
    {
      name: 'Japanese Beetles',
      type: 'insect',
      description:
        'Popillia japonica. A major pest of grapes in the eastern US. Feed on grape leaves, skeletonizing them rapidly. Can defoliate vines, reducing photosynthesis, fruit quality, and winter hardiness. Especially attracted to certain cultivars.',
      symptoms:
        'Skeletonized leaves with only tough veins remaining. Feeding starts at the top of the canopy and works down. Heavy defoliation weakens vines and reduces sugar accumulation in fruit. May also feed on ripening fruit.',
      timing:
        'Adults emerge late June, peak feeding in July, decline by mid-August. A 6-8 week feeding period.',
      conditions:
        'Warm, sunny days. Irrigated turf and lawns nearby support large grub populations. Certain cultivars (Niagara, Concord) are more attractive than others.',
      remediation:
        'Carbaryl (Sevin) is highly effective — spray when beetles are present, repeat every 10-14 days as needed. Observe PHI. Hand-pick into soapy water for small plantings. Do NOT use Japanese beetle bag traps near the vineyard. Lawn grub treatments (milky spore, beneficial nematodes) reduce local populations over time.',
      products: ['Carbaryl'],
      imageSearch: 'japanese beetle skeletonized grape vine leaves feeding',
      severity: 'moderate',
    },
    {
      name: 'Grape Berry Moth',
      type: 'insect',
      description:
        'Paralobesia viteana (syn. Endopiza viteana). Larvae feed inside grape berries, webbing them together. Two to three generations per year in NC. Overwinters as pupae in leaf litter on the ground. The most important insect pest of grapes in the eastern US.',
      symptoms:
        'First generation: webbed, discolored berries shortly after bloom. Later generations: purple, stained berries with entry/exit holes. Larvae web berries and leaves together. Damaged berries are susceptible to secondary rot. Larvae are small, olive-green caterpillars inside berries.',
      timing:
        'First generation adults emerge at wild grape bloom (mid-May). First generation larval feeding late May-June. Second generation mid-July. Third generation September. Most damaging is the second generation.',
      conditions:
        'Vineyards near wooded edges have highest pressure (wind-blown pupae from leaf litter). Poorly managed vineyards with fruit on the ground.',
      remediation:
        'Carbaryl (Sevin) at post-bloom (timing to wild grape bloom) and again for second generation in mid-July. Pheromone traps help time sprays. Remove leaf litter under vines in fall to reduce overwintering pupae (cultivation or mulching). Fruit-zone leaf removal improves spray coverage and reduces egg-laying sites. Focus sprays on vineyard edges near woods.',
      products: ['Carbaryl'],
      imageSearch: 'grape berry moth larva damage webbed purple berries',
      severity: 'high',
    },
  ],

  // ═══════════════════════════════════════════════════════════════════
  // CUCURBITS (Squash, Zucchini, Cucumbers, Melons, Pumpkins)
  // ═══════════════════════════════════════════════════════════════════
  Cucurbits: [
    {
      name: 'Powdery Mildew',
      type: 'disease',
      description:
        'Caused by Podosphaera xanthii and Erysiphe cichoracearum. The most common disease of cucurbits. Occurs every year in NC. Does NOT require free water for infection — spreads in warm, dry, humid conditions. Spores are wind-dispersed over long distances.',
      symptoms:
        'White to gray powdery growth on upper and lower leaf surfaces, petioles, and stems. Starts as small circular white spots that expand and coalesce. Severely infected leaves turn yellow, then brown, and die. Premature defoliation reduces fruit size and quality and can cause sunscald on fruit.',
      timing:
        'Typically appears mid-summer (July-August) and intensifies through fall. In NC, often becomes severe by August. Late-planted crops are most affected.',
      conditions:
        'Warm temperatures (68-86°F) and moderate to high humidity. Does NOT need rain. Shade, crowded plantings, and poor air circulation. Older leaves are infected first.',
      remediation:
        "Myclobutanil (Immunox) is highly effective — apply at first signs and every 10-14 days. Sulfur is an excellent protectant; apply every 7-10 days starting before symptoms appear (avoid above 85°F — difficult in NC summers). Potassium bicarbonate (MilStop, GreenCure) is an organic option. Choose resistant cultivars (many modern varieties have PM resistance — look for 'PM' in catalog descriptions). Avoid excessive nitrogen which promotes lush, susceptible growth.",
      products: ['Myclobutanil', 'Sulfur'],
      imageSearch: 'powdery mildew white coating on squash cucumber leaves',
      severity: 'high',
    },
    {
      name: 'Downy Mildew',
      type: 'disease',
      description:
        'Caused by Pseudoperonospora cubensis. An oomycete that can devastate cucurbits in the Southeast. Spores blow in on storm fronts from southern overwintering areas — does NOT overwinter in NC soil. Cucumbers are most susceptible, followed by cantaloupe.',
      symptoms:
        'Angular, yellow to brown lesions on upper leaf surface, bounded by leaf veins (giving a blocky, mosaic-like appearance). Purple-gray fuzzy sporulation on the lower leaf surface (best seen in early morning with dew). Leaves curl upward, dry out, and die rapidly. Does NOT affect fruit directly but defoliation leads to sunscald and poor fruit quality.',
      timing:
        'Arrives in NC typically June-August, carried northward on wind from the Gulf states. Timing varies yearly — monitor the Cucurbit Downy Mildew forecasting system (CDM ipmPIPE). Can appear earlier in warm, wet years.',
      conditions:
        'Warm (59-77°F), wet weather with prolonged leaf wetness (fog, dew, rain). Night temperatures above 55°F. Splashing water and wind spread spores. High humidity at night.',
      remediation:
        'Copper is the primary homeowner protectant — apply every 5-7 days when conditions favor the disease or forecasting system issues an alert. Begin applications before symptoms appear if possible. Captan has some activity but is less effective than copper. Myclobutanil is NOT effective (oomycete). Remove and destroy infected plants at season end. Avoid overhead irrigation. Plant resistant cultivars when available.',
      products: ['Copper', 'Captan'],
      imageSearch: 'cucurbit downy mildew angular yellow lesions cucumber leaves',
      severity: 'high',
    },
    {
      name: 'Bacterial Wilt',
      type: 'disease',
      description:
        'Caused by Erwinia tracheiphila. Transmitted exclusively by striped and spotted cucumber beetles. Bacteria colonize the xylem, blocking water transport. Affects cucumbers and muskmelons most severely; squash and watermelons are more tolerant. No chemical cure — prevention is through beetle management.',
      symptoms:
        'Sudden wilting of individual runners or entire plant, even with adequate soil moisture. Wilting starts at one end and progresses. Cut stem exudes milky, sticky bacterial ooze — diagnostic: touch cut end with knife and slowly pull away; sticky threads = bacterial wilt. Plants die within days of symptom onset.',
      timing:
        'Symptoms appear late May through July, following cucumber beetle feeding. Beetles arrive at transplanting time and transmit bacteria while feeding. Once symptoms appear, the plant is already doomed.',
      conditions:
        'Presence of cucumber beetles (striped or spotted). Beetles overwinter as adults and become active when temperatures exceed 65°F. Anything that attracts or fails to exclude beetles increases risk.',
      remediation:
        "Control cucumber beetles with Carbaryl (Sevin) at transplanting and every 7-10 days while beetles are active. Row covers over seedlings/transplants exclude beetles until bloom (must remove for pollination). Kaolin clay (Surround) deters beetle feeding. Remove and destroy wilted plants immediately to prevent beetle-mediated spread. Avoid planting near last year's cucurbit patch. Trap crops of Blue Hubbard squash can lure beetles away.",
      products: ['Carbaryl'],
      imageSearch: 'bacterial wilt cucumber wilting sticky ooze stem test',
      severity: 'high',
    },
    {
      name: 'Squash Vine Borer',
      type: 'insect',
      description:
        'Melittia cucurbitae. A clearwing moth whose larvae bore into squash and pumpkin stems, causing sudden wilt. A single larva can kill a plant. One generation per year in NC, occasionally a partial second. Primarily affects summer squash, winter squash, and pumpkins. Cucumbers and watermelons are rarely attacked.',
      symptoms:
        'Sudden wilting of runners or entire plant, usually mid-season. Yellow-green sawdust-like frass (excrement) piling up at the base of the stem at the entry point. Stems feel mushy and hollow at the base. White, wrinkled larvae (up to 1 inch) found inside the stem when split open.',
      timing:
        'Adult moths emerge and lay eggs late May through June in Zone 7b. Eggs are laid at the stem base. Larvae bore in within 1-2 weeks. Damage and wilting appears June-July. By the time plants wilt, it may be too late.',
      conditions:
        "Warm weather. Plants grown in the same area as previous year's cucurbits (pupae overwinter in soil). Thick-stemmed squash varieties are most susceptible.",
      remediation:
        'Carbaryl (Sevin) applied to the base of stems weekly from late May through June to kill eggs and young larvae before they bore in. Wrap aluminum foil or row cover fabric around the base of stems to prevent egg-laying. Inject Bt (Bacillus thuringiensis) into stems with a syringe if frass is detected. Mound soil over vine nodes to encourage secondary rooting. Delay planting until late June to avoid peak egg-laying. Destroy spent vines and till soil in fall to expose pupae.',
      products: ['Carbaryl'],
      imageSearch: 'squash vine borer larva inside stem frass base of squash plant',
      severity: 'high',
    },
    {
      name: 'Squash Bugs',
      type: 'insect',
      description:
        'Anasa tristis. Gray-brown stink-bug relatives that feed by piercing leaves and stems and sucking plant juices. Can vector cucurbit yellow vine decline. Adults overwinter under debris and emerge in spring. Very difficult to control once mature.',
      symptoms:
        'Yellow stippling and wilting of leaves from feeding. Leaves become crispy and brown. Young plants may be killed outright. Dark gray adults cluster at the base of plants and under leaves. Bronze-colored egg masses on the underside of leaves. Nymphs are pale green to gray with dark legs.',
      timing:
        'Adults emerge late May and begin egg-laying in June. One generation per year but adults are long-lived and feed through fall. Nymphs are most vulnerable and present June-July. Adults are very difficult to kill with insecticides.',
      conditions:
        "Warm weather. Plants with heavy foliage that provides hiding spots. Mulch and debris around plant bases provide shelter. Previous season's crop residue harbors overwintering adults.",
      remediation:
        'Carbaryl (Sevin) is effective against nymphs but less so against adults (hard exoskeleton). Target sprays at nymphs when they first hatch (check leaf undersides for bronze egg clusters and destroy them). Hand-pick adults and nymphs into soapy water. Place boards near plants overnight — adults congregate under them and can be collected in the morning. Remove crop debris in fall to eliminate overwintering sites. Succession planting — have young replacement plants ready.',
      products: ['Carbaryl'],
      imageSearch: 'squash bug anasa tristis adults nymphs eggs on squash leaves',
      severity: 'moderate',
    },
    {
      name: 'Anthracnose',
      type: 'disease',
      description:
        'Caused by Colletotrichum orbiculare. Affects all cucurbits, especially watermelon and cucumber. Overwinters in seed and crop debris. Causes defoliation and fruit blemishes. Very common in warm, wet Southeast summers.',
      symptoms:
        'Leaf spots: circular, tan to brown lesions with dark borders, often along veins. Lesions may have salmon-pink spore masses in wet weather. Leaves turn brown and die. Fruit lesions: circular, sunken spots with dark margins and pink spore masses. Watermelon and cucumber fruit are most commonly affected.',
      timing:
        'Appears June-August during warm, wet weather. Worst in mid to late summer when conditions are optimal and inoculum has built up.',
      conditions:
        'Warm (75-85°F) and wet conditions. Overhead irrigation, frequent rain, prolonged leaf wetness. Monoculture or short rotations of cucurbits.',
      remediation:
        'Captan sprays every 7-10 days during wet weather from first fruit set through harvest. Copper also provides protectant activity. Rotate crops — do not plant cucurbits in the same area for 2-3 years. Use drip irrigation instead of overhead. Remove crop debris at season end. Use certified disease-free seed. Choose resistant cultivars when available.',
      products: ['Captan', 'Copper'],
      imageSearch: 'anthracnose colletotrichum watermelon cucumber leaf spots fruit lesions',
      severity: 'moderate',
    },
    {
      name: 'Cucumber Beetles',
      type: 'insect',
      description:
        'Acalymma vittatum (striped) and Diabrotica undecimpunctata (spotted). Feed on leaves, flowers, and fruit. More importantly, they vector bacterial wilt. Adults overwinter and emerge when temperatures exceed 65°F. Two or more generations per year.',
      symptoms:
        'Chewed holes in leaves, flowers, and fruit rind. Feeding scars on fruit surface reduce marketability. Larvae feed on roots underground (less important for home gardens). The primary concern is transmission of bacterial wilt — even low beetle numbers can introduce the disease.',
      timing:
        'Adults active April through September. Most critical at transplanting through early bloom when plants are small and wilt transmission risk is highest. Spring populations are overwintered adults; summer populations are the new generation.',
      conditions:
        "Warm weather (65°F+). Yellow flowers attract beetles. Cucurbit volatiles attract beetles to the garden. Fields near corn or last year's cucurbit patch may have higher spotted cucumber beetle pressure.",
      remediation:
        'Carbaryl (Sevin) at transplanting and every 7-10 days while beetles are present. Concentrate sprays on young plants. Row covers from transplanting until bloom exclude beetles entirely (the most effective organic strategy). Kaolin clay (Surround) deters feeding. Trap cropping with Blue Hubbard squash concentrates beetles for targeted treatment. Yellow sticky traps monitor populations. Perimeter sprays can reduce immigration.',
      products: ['Carbaryl'],
      imageSearch: 'striped cucumber beetle feeding on squash leaves flowers',
      severity: 'high',
    },
  ],

  // ═══════════════════════════════════════════════════════════════════
  // ORNAMENTALS (Roses, Flowering Shrubs, Landscape Plants)
  // ═══════════════════════════════════════════════════════════════════
  Ornamentals: [
    {
      name: 'Black Spot',
      type: 'disease',
      description:
        'Caused by Diplocarpon rosae. The most important disease of roses in the Southeast. Causes severe defoliation in humid climates. Overwinters in fallen leaves and infected canes. Virtually impossible to grow susceptible hybrid tea roses in NC without fungicide.',
      symptoms:
        'Circular, black spots with fringed (feathery) margins on upper leaf surface. Leaves yellow around spots and drop prematurely. Severe infections defoliate the entire bush by midsummer, weakening the plant and reducing bloom. Infections can also occur on young canes as dark purple blotches.',
      timing:
        'Appears April-May as new growth emerges and continues through fall. Worst during warm, wet weather. Preventive sprays must begin before symptoms appear — once established, it is nearly impossible to stop.',
      conditions:
        'Warm (75-85°F) and wet conditions. Leaf wetness of 7+ hours (rain, irrigation, dew). Overhead irrigation is a primary contributor. Dense plantings with poor air circulation.',
      remediation:
        'Myclobutanil (Immunox) every 10-14 days from spring growth through fall — the most effective homeowner product. Captan also provides good protectant activity. Sulfur is effective but must be reapplied frequently. Start sprays when new leaves emerge in March. Rake and remove fallen leaves. Prune for open, vase-shaped bushes with good air circulation. Avoid overhead watering. Choose resistant cultivars (Knock Out series, Drift series, Oso Easy series — these rarely need fungicide).',
      products: ['Myclobutanil', 'Captan', 'Sulfur'],
      imageSearch: 'black spot diplocarpon rose leaves circular dark spots yellowing',
      severity: 'high',
    },
    {
      name: 'Powdery Mildew',
      type: 'disease',
      description:
        'Multiple species affect ornamentals — Podosphaera pannosa on roses, Erysiphe spp. on crape myrtle, zinnia, phlox, and many others. Does NOT require free water. Extremely common in the Southeast on susceptible plants.',
      symptoms:
        'White to grayish powdery coating on leaves, buds, and stems. Leaves may curl, distort, or become stunted. Rose buds may fail to open properly. Crape myrtle leaves curl and drop. New growth is most susceptible. Heavily infected plants look whitewashed.',
      timing:
        'Appears spring through fall. On roses, often starts in April-May on new growth. On crape myrtles, worst in late spring and fall. Warm days and cool nights with high humidity are peak periods.',
      conditions:
        'Moderate temperatures (60-80°F) with high humidity but NOT rain (rain washes spores off). Shaded locations, crowded plantings, poor air circulation. Warm days followed by cool nights with heavy dew.',
      remediation:
        'Myclobutanil (Immunox) is the most effective treatment — both curative and protectant. Apply every 10-14 days. Sulfur is a good protectant but avoid above 85°F and do not mix with or apply within 2 weeks of oil sprays. Neem oil has some activity. Improve air circulation by pruning and spacing. Avoid late-day watering. Choose resistant cultivars (for crape myrtles: Natchez, Tuscarora, Sioux).',
      products: ['Myclobutanil', 'Sulfur'],
      imageSearch: 'powdery mildew white coating on rose leaves and buds',
      severity: 'moderate',
    },
    {
      name: 'Japanese Beetles',
      type: 'insect',
      description:
        'Popillia japonica. Feed on over 300 plant species. In ornamental landscapes, roses are a favorite — adults feed on both foliage and flowers. Also attack crape myrtles, lindens, birches, grapes, and many others. Adults are present for about 6 weeks in summer.',
      symptoms:
        'Skeletonized leaves (tissue eaten between veins). Rose flowers are chewed and tattered, especially light-colored blooms. Beetles feed in groups, producing rapid, severe damage. Petals may be completely consumed. Droppings and dead beetles accumulate on damaged plants.',
      timing:
        'Adults emerge late June, peak feeding early to mid-July, decline by mid-August. Morning feeding is heaviest.',
      conditions:
        'Warm, sunny days. Well-watered lawns nearby support grub populations. Damaged plants release volatile compounds that attract more beetles. Certain rose varieties and colors are more attractive.',
      remediation:
        'Carbaryl (Sevin) is very effective — spray foliage and flowers when beetles are active. Provides 1-2 weeks residual. Hand-pick into soapy water in the morning when beetles are sluggish. Prune off heavily damaged flowers to reduce volatile attractants. Do NOT use Japanese beetle bag traps — they attract beetles from a wide area. Treat lawn grubs with milky spore or beneficial nematodes for long-term population reduction. Choose less-preferred plants where possible (Japanese beetles avoid boxwood, holly, dogwood, redbud).',
      products: ['Carbaryl'],
      imageSearch: 'japanese beetle feeding on rose flower petals and leaves',
      severity: 'moderate',
    },
    {
      name: 'Aphids',
      type: 'insect',
      description:
        'Multiple species including Macrosiphum rosae (rose aphid) and many others. Small, soft-bodied, pear-shaped insects that feed in colonies on new growth, sucking plant sap. Reproduce rapidly — a single female can produce 50-100 offspring without mating. Nearly every ornamental is susceptible.',
      symptoms:
        'Clusters of small green, pink, or black insects on shoot tips, buds, and leaf undersides. Leaves curl and distort. Sticky honeydew excretion on leaves below feeding sites. Black sooty mold grows on honeydew. Stunted, distorted new growth. Flower buds may fail to open.',
      timing:
        'Present spring through fall. Populations explode in spring (March-May) on tender new growth. Natural enemies usually bring them under control by mid-summer. Late summer and fall resurgence possible.',
      conditions:
        'Excess nitrogen fertilization promotes lush, aphid-attractive growth. Cool to warm temperatures (60-80°F). Sheltered locations. Ants farm and protect aphid colonies for honeydew.',
      remediation:
        'Strong water spray knocks off aphids and breaks colonies — often sufficient for moderate infestations. Insecticidal soap or horticultural oil (summer rate) for heavier infestations. Avoid broad-spectrum insecticides (Carbaryl/Sevin) if possible — they kill natural enemies (ladybugs, lacewings, parasitoid wasps) and can cause aphid resurgence. Encourage beneficial insects. Ant control reduces aphid protection. Prune off heavily infested shoot tips. Avoid excessive nitrogen fertilization.',
      products: [],
      imageSearch: 'aphid colony on rose bud new growth green pink aphids',
      severity: 'low',
    },
    {
      name: 'Cercospora Leaf Spot',
      type: 'disease',
      description:
        'Caused by Cercospora spp. Affects many ornamentals including crape myrtles, hydrangeas, roses, and others. Has become a significant problem on crape myrtles in the Southeast since first reported in 2015. Causes premature defoliation.',
      symptoms:
        'Crape myrtles: circular dark brown to purple spots on leaves, often with yellow halos. Heavily infected leaves drop. Defoliation progresses from the bottom of the canopy upward. Trees may be nearly bare by August. Hydrangeas: similar circular spots, brown with purple margins.',
      timing:
        'Symptoms appear June-July and intensify through September. Worst in late summer when cumulative infections cause heavy defoliation. Spores spread by rain splash throughout the growing season.',
      conditions:
        'Warm (77-95°F), humid conditions with frequent rain. Overhead irrigation worsens spread. Dense plantings with poor air circulation. Fallen leaves on the ground provide overwintering inoculum.',
      remediation:
        'Myclobutanil (Immunox) every 14 days beginning when spots first appear. Copper provides protectant activity if applied preventively. Captan also has some efficacy. For crape myrtles, begin treatments in June before heavy spotting develops. Rake and remove fallen leaves. Prune for open canopy and air circulation. Avoid overhead irrigation. Choose resistant crape myrtle cultivars if planting new (disease resistance varies — check NCSU Extension recommendations).',
      products: ['Myclobutanil', 'Copper', 'Captan'],
      imageSearch: 'cercospora leaf spot crape myrtle dark spots yellowing defoliation',
      severity: 'moderate',
    },
    {
      name: 'Scale Insects',
      type: 'insect',
      description:
        'Multiple species including tea scale (Fiorinia theae), euonymus scale, and various soft scales. Small, immobile insects hidden under waxy or armored coverings that attach to bark, stems, and leaves, sucking plant sap. Often go unnoticed until heavy infestation. Common on camellias, hollies, euonymus, magnolias, and many other landscape plants.',
      symptoms:
        'White, brown, or gray bumps on stems, branches, and leaf undersides. Yellowing and decline of affected branches. Honeydew and sooty mold from soft scales. Sparse canopy and thinning foliage. In severe cases, branch dieback and plant death. Tea scale on camellias causes yellow stippling on upper leaf surfaces.',
      timing:
        'Crawler stage (vulnerable, mobile young) emerges in spring (April-May) and sometimes a second generation in late summer (August). Crawlers are the only stage vulnerable to contact sprays. Mature scales are protected by their covering year-round.',
      conditions:
        'Stressed plants are more susceptible. Shaded, sheltered locations. Dense, unpruned hedges. Overuse of broad-spectrum insecticides kills natural enemies (parasitoid wasps, lady beetles) that otherwise control scale.',
      remediation:
        'Dormant oil spray in late winter (February-March) smothers overwintering scales — the most effective single treatment. Summer-rate horticultural oil for crawlers. Carbaryl (Sevin) has limited effect — scale coverings protect adults. Target crawler stage with insecticidal soap or oil in May and August. Prune out heavily encrusted branches. Promote plant health with proper watering and mulching. Inspect new plants before purchasing.',
      products: [],
      imageSearch: 'scale insects tea scale white bumps on camellia holly branches',
      severity: 'moderate',
    },
    {
      name: 'Rose Rosette Disease',
      type: 'disease',
      description:
        'Caused by Rose Rosette Virus (RRV), vectored by the eriophyid mite Phyllocoptes fructiphilus. An incurable, lethal disease of roses spreading rapidly through the Southeast. Affects all rose species including Knock Outs (previously considered low-maintenance). Transmitted by tiny wind-blown mites from infected plants.',
      symptoms:
        "Rapid, elongated shoot growth with excessive thorniness — shoots are thick, red, and distorted ('witches broom'). Leaves are small, distorted, often deep red/maroon, and tightly clustered. Flowers are deformed with excessive petals. Plant declines and dies within 2-5 years of symptom onset. Not all symptoms appear at once.",
      timing:
        'Mite vectors are active spring through fall, with peak transmission in late spring and summer. Symptoms may appear months after infection. Often first noticed in mid to late summer when distorted growth becomes obvious.',
      conditions:
        'Proximity to infected roses (including wild multiflora rose, which is a major reservoir). Wind-borne mites can travel significant distances. Dense rose plantings facilitate spread. Multiflora rose in woods and hedgerows is the primary reservoir.',
      remediation:
        'NO CURE — there is no treatment, fungicide, or pesticide that can cure rose rosette disease. Infected plants must be removed and destroyed (bag and trash — do NOT compost) including the root system. Remove multiflora rose from the surrounding area (major virus reservoir). Miticide applications may slow mite spread to nearby roses. Replace with resistant plants or wait at least a year before replanting roses. Space roses to reduce mite movement between plants.',
      products: [],
      imageSearch: 'rose rosette disease witches broom red distorted excessive thorns',
      severity: 'high',
    },
  ],
  'Turf Grass': [
    {
      name: 'Brown Patch',
      type: 'disease',
      description:
        'Most common lawn disease in the Southeast. Caused by Rhizoctonia solani. Attacks tall fescue, bermuda, and zoysia.',
      symptoms:
        'Circular patches of brown, thinned turf 6 inches to several feet wide. Lesions on grass blades near soil with dark brown borders. Turf pulls up easily at patch edges.',
      timing:
        'Active when nighttime temps exceed 65°F with high humidity. Peak: June–September in Zone 7b.',
      conditions:
        'Hot, humid weather. Evening irrigation, poor drainage, excessive nitrogen. Worst on tall fescue.',
      remediation:
        'Heritage (azoxystrobin) or thiophanate-methyl (3336) preventive or curative. Reduce nitrogen in summer. Water early morning, not evening. Improve drainage and air circulation. Raise mowing height.',
      products: ['Azoxystrobin', 'Thiophanate-methyl'],
      imageSearch: 'brown patch rhizoctonia lawn circular patch fescue',
      severity: 'high',
    },
    {
      name: 'Dollar Spot',
      type: 'disease',
      description:
        'Common on bermuda, zoysia, and fescue lawns. Caused by Clarireedia jacksonii (formerly Sclerotinia).',
      symptoms:
        'Small silver-dollar-sized tan spots. White cottony mycelium visible in morning dew. Individual blades show hourglass-shaped lesions.',
      timing:
        'Spring through fall. Peak when temps are 60–80°F with heavy dew. Can be active almost year-round in mild winters.',
      conditions: 'Low nitrogen, drought stress, heavy dew. Thatch buildup.',
      remediation:
        'Increase nitrogen fertility. Reduce thatch. Water deeply but infrequently. Heritage or thiophanate-methyl if chemical control needed. Remove dew with morning mowing.',
      products: ['Azoxystrobin', 'Thiophanate-methyl'],
      imageSearch: 'dollar spot lawn fungus small tan patches bermuda',
      severity: 'moderate',
    },
    {
      name: 'Large Patch (Zoysia Patch)',
      type: 'disease',
      description:
        'Major disease of zoysia and bermuda. Caused by Rhizoctonia solani AG 2-2 LP. Different from brown patch.',
      symptoms:
        'Large circular patches of orange-brown turf, expanding outward. Active at patch margins. Grass recovers slowly from center.',
      timing:
        'Fall (October–November) and spring (March–May) when soil temps are 50–70°F. NOT a summer disease.',
      conditions: 'Cool, wet weather during spring/fall transitions. Excess thatch. Poor drainage.',
      remediation:
        'Heritage or thiophanate-methyl applied preventively in fall (October) and/or spring (March). Reduce thatch. Avoid excess nitrogen in fall. Improve drainage.',
      products: ['Azoxystrobin', 'Thiophanate-methyl'],
      imageSearch: 'large patch zoysia grass rhizoctonia circular orange brown',
      severity: 'high',
    },
    {
      name: 'Crabgrass',
      type: 'cultural',
      description:
        'Annual grassy weed. Germinates when soil temperature reaches 55°F for several consecutive days.',
      symptoms:
        'Light green, coarse-textured grass growing in patches, spreading by stolons. Thrives in thin, bare, or stressed turf areas.',
      timing:
        'Germination: March–April in Zone 7b. Apply pre-emergent BEFORE germination (February–early March).',
      conditions: 'Thin turf, bare spots, compacted soil, low mowing height. Full sun, warm soil.',
      remediation:
        'Pre-emergent (prodiamine/Barricade or dithiopyr/Dimension) in February before soil hits 55°F. Post-emergent (quinclorac/Drive XLR8) for established crabgrass. Maintain thick, healthy turf at proper mowing height.',
      products: ['Prodiamine', 'Quinclorac'],
      imageSearch: 'crabgrass digitaria weed in lawn close up',
      severity: 'moderate',
    },
    {
      name: 'White Grubs',
      type: 'insect',
      description:
        'Larvae of Japanese beetles, June bugs, and masked chafers. Feed on grass roots underground.',
      symptoms:
        'Spongy, brown patches of turf that pull up like carpet (roots eaten). Increased bird, skunk, or raccoon digging. Adult beetles seen in summer.',
      timing:
        'Grubs feed August–October and March–May. Preventive treatment: June–July. Adults fly June–August.',
      conditions: 'Moist, irrigated lawns are preferred egg-laying sites. Sandy loam soils.',
      remediation:
        'Preventive: imidacloprid (Merit) or clothianidin (Arena) applied June–July before eggs hatch. Curative: trichlorfon for active infestations. Biological: milky spore disease or beneficial nematodes (Heterorhabditis) for organic control.',
      products: ['Imidacloprid', 'Clothianidin'],
      imageSearch: 'white grub japanese beetle larva lawn root damage',
      severity: 'high',
    },
    {
      name: 'Nutsedge',
      type: 'cultural',
      description:
        'Perennial sedge (not a grass). Yellow nutsedge and purple nutsedge. Spreads by underground tubers (nutlets).',
      symptoms:
        'Bright yellow-green, fast-growing, triangular-stemmed plants that stick up above the lawn. "Sedge — I can feel the edge." Grows faster than grass.',
      timing: 'Appears May–June when soil warms. Persists through first frost. Tubers overwinter.',
      conditions:
        'Wet, poorly drained areas. Warm soil. Once established, very persistent due to tuber network.',
      remediation:
        'Halosulfuron (Sedgehammer) or sulfentrazone (Dismiss) for post-emergent control. Multiple applications needed to deplete tuber reserves. Improve drainage. Do NOT pull — breaks tubers and stimulates more growth.',
      products: ['Halosulfuron'],
      imageSearch: 'yellow nutsedge cyperus lawn triangular stem',
      severity: 'moderate',
    },
  ],
  'Orchard Floor': [
    {
      name: 'Annual Grasses (Crabgrass, Foxtail, Goosegrass)',
      type: 'cultural',
      description:
        'Annual grassy weeds that compete with trees for water and nutrients. Harbor voles and provide pest habitat.',
      symptoms:
        'Dense grass growth in the tree row or under canopy. Competes with shallow-rooted trees. Vole damage to trunk bark under grass cover.',
      timing:
        'Germination: March–May. Apply pre-emergent before germination or post-emergent grass killer when actively growing.',
      conditions: 'Bare or thin ground cover. Warm soil in spring.',
      remediation:
        'Pre-emergent: Prowl H2O, Surflan, or Chateau (dormant season). Post-emergent grass killer: Poast, Fusilade, or Select (safe over trees). Maintain 4-foot weed-free strip under trees.',
      products: ['Pendimethalin', 'Oryzalin', 'Sethoxydim', 'Fluazifop-P', 'Clethodim'],
      imageSearch: 'crabgrass orchard floor weed management tree row',
      severity: 'moderate',
    },
    {
      name: 'Broadleaf Weeds (Horseweed, Dandelion, Pigweed)',
      type: 'cultural',
      description:
        'Broadleaf weeds in the orchard floor compete with trees and can harbor diseases and pests.',
      symptoms:
        'Various broadleaf weeds growing in tree rows and between rows. Some (horseweed/marestail) are glyphosate-resistant.',
      timing:
        'Year-round depending on species. Winter annuals germinate fall. Summer annuals germinate spring.',
      conditions: 'Disturbed soil, gaps in mulch or groundcover.',
      remediation:
        'Glyphosate (Roundup) directed spray for most broadleaf. Glufosinate (Rely/Liberty) for glyphosate-resistant weeds. Clopyralid (Stinger) for composites. Pre-emergent programs reduce emergence. Maintain mulch or cover crop.',
      products: ['Glyphosate', 'Glufosinate', 'Clopyralid'],
      imageSearch: 'broadleaf weeds orchard floor horseweed dandelion',
      severity: 'moderate',
    },
    {
      name: 'Vole Damage',
      type: 'cultural',
      description:
        'Meadow voles (Microtus) girdle tree trunks at ground level under grass/mulch cover. Can kill young trees.',
      symptoms:
        'Bark chewed away in a ring around the trunk base (girdling). Runways visible in grass. Young trees may die suddenly in spring.',
      timing:
        'Damage occurs fall through spring when voles are active under cover. Worst in heavy grass or deep mulch.',
      conditions:
        'Tall grass or heavy mulch around tree trunks. High vole populations in adjacent fields.',
      remediation:
        'Maintain weed-free strip (4 ft) around trunks — remove grass and pull mulch 6" from trunk. Hardware cloth trunk guards. Snap traps in runways. Zinc phosphide bait (Restricted Use). Mow orchard floor short in fall.',
      products: [],
      imageSearch: 'vole damage tree trunk bark girdling orchard',
      severity: 'high',
    },
  ],
};
