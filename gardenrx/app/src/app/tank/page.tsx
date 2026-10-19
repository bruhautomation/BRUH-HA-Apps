import {
  fetchCrops,
  fetchVarieties,
  fetchVarietyStages,
  fetchProducts,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchCropGroups,
  fetchCropUses,
  fetchTankMixRules,
  fetchSprayHistory,
  fetchQueuedSprays,
  fetchInventory,
  buildIngredientRecord,
} from '@/lib/queries';
import { fetchWeather, findBestSprayWindows, getCurrentSprayRating } from '@/lib/weather';
import { applyPhenology } from '@/lib/phenology';
import { SprayPlanner } from '@/components/spray-planner/index';
import { SectionTabs, SPRAY_TABS } from '@/components/shell/section-tabs';

export const dynamic = 'force-dynamic';

export default async function TankPage(props: PageProps<'/tank'>) {
  const sp = await props.searchParams;
  const cropsParam = typeof sp.crops === 'string' ? sp.crops : undefined;

  const weather = await fetchWeather().catch(() => null);

  const [
    crops,
    varieties,
    varietyStages,
    products,
    productIngredients,
    activeIngredients,
    cropGroups,
    cropUses,
    tankMixRules,
    { sprayEvents, sprayEventProducts, sprayEventCrops },
    { queuedSprays, queuedSprayProducts, queuedSprayCrops },
    inventory,
  ] = await Promise.all([
    fetchCrops({ activeOnly: true }),
    fetchVarieties(),
    fetchVarietyStages(),
    fetchProducts(),
    fetchProductIngredients(),
    fetchActiveIngredients(),
    fetchCropGroups(),
    fetchCropUses(),
    fetchTankMixRules(),
    fetchSprayHistory(),
    fetchQueuedSprays(),
    fetchInventory(),
  ]);

  const ingredientMap = buildIngredientRecord(productIngredients, activeIngredients);
  const inventoryProductIds = inventory.filter((i) => i.quantity > 0).map((i) => i.product_id);
  // Stages advance with the Holly Springs phenology calendar (manual overrides kept) so
  // the planner's bloom interlock and stage badges reflect today, not a stale snapshot.
  const effectiveStages = applyPhenology(varietyStages, varieties, crops, cropGroups, new Date());

  // Crops handed off from the Today dashboard ("Plan a spray") — validated
  // against the active crop list so a stale/invalid id is simply ignored.
  const validCropIds = new Set(crops.map((c) => c.id));
  const initialCropIds = (cropsParam ?? '')
    .split(',')
    .map((s) => parseInt(s, 10))
    .filter((n) => Number.isInteger(n) && validCropIds.has(n));

  return (
    <div className="page">
      <div className="section-title">
        <h2>Spray</h2>
        <span className="meta">Tank-mix builder</span>
      </div>
      <div className="mx-auto max-w-2xl">
        <SectionTabs tabs={SPRAY_TABS} />
        <SprayPlanner
          crops={crops}
          varieties={varieties}
          varietyStages={effectiveStages}
          products={products}
          cropGroups={cropGroups}
          cropUses={cropUses}
          tankMixRules={tankMixRules}
          ingredientMap={ingredientMap}
          sprayEvents={sprayEvents}
          sprayEventProducts={sprayEventProducts}
          sprayEventCrops={sprayEventCrops}
          precipHistory={weather?.precipHistory ?? []}
          weatherCurrent={weather?.current ?? null}
          weatherHourly={weather?.hourly ?? []}
          weatherDaily={weather?.daily ?? []}
          sprayWindows={weather ? findBestSprayWindows(weather.hourly, 5) : []}
          currentRating={weather ? getCurrentSprayRating(weather.current, weather.hourly) : null}
          queuedSprays={queuedSprays}
          queuedSprayProducts={queuedSprayProducts}
          queuedSprayCrops={queuedSprayCrops}
          inventoryProductIds={inventoryProductIds}
          inventoryData={inventory}
          initialCropIds={initialCropIds}
        />
      </div>
    </div>
  );
}
