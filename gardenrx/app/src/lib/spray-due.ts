import {
  fetchCrops,
  fetchCropGroups,
  fetchVarieties,
  fetchVarietyStages,
  fetchProducts,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchSprayHistory,
  buildIngredientMap,
} from '@/lib/queries';
import { applyPhenology } from '@/lib/phenology';
import { getSprayRecordsForCrop, computeCoverage } from '@/lib/protection';
import { cropStages, groupStages, needsCoverageNow, sprayMissing } from '@/lib/coverage-season';

/**
 * Whether any active crop needs a spray now, by the rule Today uses (see
 * `sprayMissing`). For screens that show spray windows without Today's own
 * per-crop table, so they never offer a spray Today would not ask for.
 */
export async function anySprayDue(
  precipHistory: Array<{ time: string; precipitation: number }>,
  now: Date = new Date()
): Promise<boolean> {
  const [crops, cropGroups, varieties, varietyStages, products, pis, ais, history] =
    await Promise.all([
      fetchCrops({ activeOnly: true }),
      fetchCropGroups(),
      fetchVarieties(),
      fetchVarietyStages(),
      fetchProducts(),
      fetchProductIngredients(),
      fetchActiveIngredients(),
      fetchSprayHistory(),
    ]);
  const ingredientMap = buildIngredientMap(pis, ais);
  const effective = applyPhenology(varietyStages, varieties, crops, cropGroups, now);
  const groupStage = groupStages(cropGroups, now);
  return crops.some((crop) => {
    const stages = cropStages(crop.id, varieties, effective, groupStage(crop.crop_group_id));
    if (!crop.track_fungicide && !crop.track_insecticide) return false;
    const records = getSprayRecordsForCrop(
      crop.id,
      history.sprayEvents,
      history.sprayEventProducts,
      history.sprayEventCrops,
      products,
      ingredientMap
    );
    return (
      sprayMissing({
        active: needsCoverageNow(stages.map((stage) => ({ stage }))),
        inBloom: stages.includes('bloom'),
        monitorFung: crop.track_fungicide,
        monitorIns: crop.track_insecticide,
        fung: crop.track_fungicide
          ? computeCoverage(records, 'fungicide', now, precipHistory)
          : null,
        ins: crop.track_insecticide
          ? computeCoverage(records, 'insecticide', now, precipHistory)
          : null,
      }).length > 0
    );
  });
}
