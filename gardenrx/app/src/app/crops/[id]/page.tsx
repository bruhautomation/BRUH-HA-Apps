import { createClient } from '@/lib/db/server';
import { notFound } from 'next/navigation';
import type { Crop } from '@/lib/database.types';
import { CropDetailView } from '@/components/crop-detail-view';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';
import {
  fetchVarietyStages,
  fetchCropGroups,
  fetchCropUses,
  fetchProducts,
  fetchActiveIngredients,
  fetchProductIngredients,
  fetchSprayHistory,
  buildIngredientMap,
} from '@/lib/queries';
import { fetchWeather } from '@/lib/weather';
import { getSprayRecordsForCrop, computeCoverage } from '@/lib/protection';
import { buildPhiByProductGroup, computeCropPhi } from '@/lib/phi';
import { harvestSeason } from '@/lib/harvest-windows';
import { applyPhenology } from '@/lib/phenology';

export const dynamic = 'force-dynamic';

export default async function CropDetailPage(props: PageProps<'/crops/[id]'>) {
  const { id } = await props.params;
  const supabase = await createClient();
  const cropId = parseInt(id);

  // Crop-specific query + shared reference data in parallel
  const [
    { data: _crop },
    { data: _varieties },
    varietyStages,
    cropGroups,
    allCropUses,
    products,
    activeIngredients,
    productIngredients,
    { sprayEvents, sprayEventProducts, sprayEventCrops: allSprayEventCrops },
    weather,
  ] = await Promise.all([
    supabase.from('crops').select('*').eq('id', cropId).single(),
    supabase.from('varieties').select('*').eq('crop_id', cropId).order('name'),
    fetchVarietyStages(),
    fetchCropGroups(),
    fetchCropUses(),
    fetchProducts(),
    fetchActiveIngredients(),
    fetchProductIngredients(),
    fetchSprayHistory(),
    fetchWeather().catch(() => null),
  ]);

  const crop = _crop as Crop | null;
  if (!crop) notFound();

  const varieties = _varieties ?? [];
  const cropGroup = cropGroups.find((g) => g.id === crop.crop_group_id);

  // Products labeled for this crop group
  const cropUses = allCropUses.filter((cu) => cu.crop_group_id === crop.crop_group_id);
  const ingredientMap = buildIngredientMap(productIngredients, activeIngredients);

  // Coverage + PHI (existing logic) for this crop
  const now = new Date();
  // Stages advance with the Holly Springs phenology calendar (manual overrides kept).
  const effectiveStages = applyPhenology(varietyStages, varieties, [crop], cropGroups, now);
  const productBrand = (pid: number) => products.find((p) => p.id === pid)?.brand ?? 'a spray';
  const records = getSprayRecordsForCrop(
    cropId,
    sprayEvents,
    sprayEventProducts,
    allSprayEventCrops,
    products,
    ingredientMap
  );
  const fungCoverage = computeCoverage(records, 'fungicide', now, weather?.precipHistory ?? []);
  const insCoverage = computeCoverage(records, 'insecticide', now, weather?.precipHistory ?? []);
  const phi = computeCropPhi(
    cropId,
    crop.crop_group_id,
    sprayEvents,
    sprayEventProducts,
    allSprayEventCrops,
    buildPhiByProductGroup(allCropUses),
    productBrand,
    now
  );
  const phiInSeason = harvestSeason(cropId, varieties, now).inSeason;

  const labeledProducts = cropUses
    .filter((cu) => ACTIVE_PRODUCT_IDS.has(cu.product_id))
    .flatMap((cu) => {
      const product = products.find((p) => p.id === cu.product_id);
      if (!product) return [];
      const pIngs = ingredientMap.get(cu.product_id) ?? [];
      return [{ ...cu, product, ingredients: pIngs }];
    });

  // Spray history for this crop
  const sprayEventCrops = allSprayEventCrops.filter((ec) => ec.crop_id === cropId);
  const cropEventIds = sprayEventCrops.map((ec) => ec.spray_event_id);
  const recentSprays = sprayEvents
    .filter((e) => cropEventIds.includes(e.id))
    .slice(0, 5)
    .map((e) => {
      const eventProds = sprayEventProducts
        .filter((ep) => ep.spray_event_id === e.id)
        .map((ep) => {
          const product = products.find((p) => p.id === ep.product_id);
          const ingredients = ingredientMap.get(ep.product_id) ?? [];
          return { ...ep, brand: product?.brand ?? 'Unknown', ingredients };
        });
      return { ...e, products: eventProds };
    });

  return (
    <CropDetailView
      crop={crop}
      cropGroup={cropGroup ?? null}
      varieties={varieties}
      varietyStages={effectiveStages}
      fungCoverage={fungCoverage}
      insCoverage={insCoverage}
      phi={phi}
      phiInSeason={phiInSeason}
      labeledProducts={labeledProducts}
      recentSprays={recentSprays}
    />
  );
}
