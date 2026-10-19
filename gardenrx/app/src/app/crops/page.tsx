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
import { getSprayRecordsForCrop, computeCoverage, type CoverageInfo } from '@/lib/protection';
import { buildPhiByProductGroup, computeCropPhi } from '@/lib/phi';
import { harvestSeason } from '@/lib/harvest-windows';
import { applyPhenology } from '@/lib/phenology';
import { stageIndex, stageVarColor, stageLabel } from '@/lib/stage-color';
import { CropsBoard, type CropCardModel, type CovCell } from '@/components/crops/crops-board';
import type { PhenologicalStage } from '@/lib/database.types';

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

function covCell(c: CoverageInfo | null): CovCell {
  return c ? { status: c.status, daysRemaining: c.daysRemaining } : null;
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
    const stages = cropVarieties.map((v) => {
      const vs = effectiveStages.find((s) => s.variety_id === v.id);
      return (vs?.stage ?? 'dormant') as PhenologicalStage;
    });
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

    const statuses = [fung?.status, inBloom ? undefined : ins?.status].filter(Boolean) as string[];
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
      fung: covCell(fung),
      ins: covCell(ins),
      phiActive,
      phiDaysLeft: phi.daysLeft,
      protection,
    };
  });

  return <CropsBoard cards={cards} cropGroups={cropGroups} />;
}
