import {
  fetchCrops,
  fetchVarieties,
  fetchVarietyStages,
  fetchCropGroups,
  fetchProducts,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchCropUses,
  fetchSprayHistory,
  buildIngredientMap,
} from '@/lib/queries';
import { fetchWeather } from '@/lib/weather';
import { LOCATION } from '@/config/thresholds';
import { getSprayRecordsForCrop, computeCoverage, type CoverageInfo } from '@/lib/protection';
import { buildPhiByProductGroup, computeCropPhi } from '@/lib/phi';
import { harvestSeason } from '@/lib/harvest-windows';
import { applyPhenology } from '@/lib/phenology';
import { stageIndex, stageVarColor, stageLabel } from '@/lib/stage-color';
import { CropsBoard, type CropCardModel, type CovCell } from '@/components/crops/crops-board';
import { needsCoverageNow, dueTypes, cropStages } from '@/lib/coverage-season';

export const dynamic = 'force-dynamic';

// crop group → category (mirrors the legacy Crops grouping)
const GROUP_CATEGORY: Record<string, string> = {
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
const ORCHARD_NONGROUP = new Set(['Figs', 'Persimmons', 'Pawpaws', 'Mulberries', 'Jujube']);

function covCell(c: CoverageInfo | null, now: Date): CovCell {
  if (!c) return null;
  // The day the cover runs out, on the garden's calendar: "next due Dec 3".
  const due = new Date(now.getTime() + Math.max(0, c.daysRemaining) * 86400000).toLocaleDateString(
    'en-US',
    { month: 'short', day: 'numeric', timeZone: LOCATION.timezone }
  );
  return { status: c.status, daysRemaining: c.daysRemaining, due };
}

export default async function CropsPage() {
  const [
    weather,
    crops,
    varieties,
    varietyStages,
    cropGroups,
    products,
    productIngredients,
    activeIngredients,
    cropUses,
    { sprayEvents, sprayEventProducts, sprayEventCrops },
  ] = await Promise.all([
    fetchWeather().catch(() => null),
    fetchCrops(),
    fetchVarieties(),
    fetchVarietyStages(),
    fetchCropGroups(),
    fetchProducts(),
    fetchProductIngredients(),
    fetchActiveIngredients(),
    fetchCropUses(),
    fetchSprayHistory(),
  ]);

  const groupName = new Map(cropGroups.map((g) => [g.id, g.name]));
  const ingredientMap = buildIngredientMap(productIngredients, activeIngredients);
  const productBrand = (id: number) => products.find((p) => p.id === id)?.brand ?? 'a spray';
  const phiByProductGroup = buildPhiByProductGroup(cropUses);
  const precipHistory = weather?.precipHistory ?? [];
  const now = new Date();
  // Stages advance with the Holly Springs phenology calendar (manual overrides kept).
  const effectiveStages = applyPhenology(varietyStages, varieties, crops, cropGroups, now);

  const cards: CropCardModel[] = crops.map((crop) => {
    const cropVarieties = varieties.filter((v) => v.crop_id === crop.id);
    const stages = cropStages(crop.id, varieties, effectiveStages);
    const topStage = stages.length
      ? stages.reduce((a, b) => (stageIndex(b) > stageIndex(a) ? b : a))
      : null;
    const inBloom = stages.includes('bloom');

    const trackFung = crop.track_fungicide;
    const trackIns = crop.track_insecticide;
    const records = getSprayRecordsForCrop(
      crop.id,
      sprayEvents,
      sprayEventProducts,
      sprayEventCrops,
      products,
      ingredientMap
    );
    // As-needed (manual) types aren't monitored — leave their coverage null.
    const fung = trackFung ? computeCoverage(records, 'fungicide', now, precipHistory) : null;
    const ins = trackIns ? computeCoverage(records, 'insecticide', now, precipHistory) : null;
    const phi = computeCropPhi(
      crop.id,
      crop.crop_group_id,
      sprayEvents,
      sprayEventProducts,
      sprayEventCrops,
      phiByProductGroup,
      productBrand,
      now
    );
    // A PHI is only worth flagging when the fruit is actually in season.
    const phiActive = phi.active && harvestSeason(crop.id, cropVarieties, now).inSeason;

    // Dormant and post-harvest crops are resting: no lapsed or due flags.
    const resting = !needsCoverageNow(stages.map((stage) => ({ stage })));
    const due = dueTypes({ active: !resting, inBloom, fung, ins });
    const statuses = resting
      ? []
      : ([fung?.status, inBloom ? undefined : ins?.status].filter(Boolean) as string[]);
    const protection: CropCardModel['protection'] =
      statuses.length === 0
        ? 'untracked'
        : statuses.includes('red')
          ? 'red'
          : statuses.includes('yellow')
            ? 'yellow'
            : 'green';

    const gName = crop.crop_group_id ? (groupName.get(crop.crop_group_id) ?? null) : null;
    const category =
      (gName && GROUP_CATEGORY[gName]) ?? (ORCHARD_NONGROUP.has(crop.name) ? 'Orchard' : 'Garden');

    return {
      id: crop.id,
      name: crop.name,
      group: gName,
      category,
      varietyCount: cropVarieties.length,
      stageLabel: topStage ? stageLabel(topStage) : null,
      stageColor: topStage ? stageVarColor(topStage) : 'var(--ink-3)',
      inBloom,
      trackFung,
      trackIns,
      fung: covCell(fung, now),
      ins: covCell(ins, now),
      phiActive,
      phiDaysLeft: phi.daysLeft,
      protection,
      resting,
      due: due.length > 0,
    };
  });

  return <CropsBoard cards={cards} cropGroups={cropGroups} />;
}
