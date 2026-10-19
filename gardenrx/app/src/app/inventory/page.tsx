import {
  fetchProducts,
  fetchInventory,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchCropUses,
  fetchCropGroups,
  buildIngredientRecord,
} from '@/lib/queries';
import { areasByProduct } from '@/lib/product-area';
import { InventoryList } from '@/components/inventory-list';
import { SectionTabs, TREATMENT_TABS } from '@/components/shell/section-tabs';

export const dynamic = 'force-dynamic';

export default async function InventoryPage() {
  const [products, inventory, productIngredients, activeIngredients, cropUses, cropGroups] =
    await Promise.all([
      fetchProducts(),
      fetchInventory(),
      fetchProductIngredients(),
      fetchActiveIngredients(),
      fetchCropUses(),
      fetchCropGroups(),
    ]);

  const ingredients = buildIngredientRecord(productIngredients, activeIngredients);
  const areas = areasByProduct(cropUses, cropGroups);

  return (
    <div className="page">
      <div className="section-title">
        <h2>Treatments</h2>
        <span className="meta">Your stock · on hand</span>
      </div>
      <div className="mx-auto max-w-3xl">
        <SectionTabs tabs={TREATMENT_TABS} />
        <InventoryList
          products={products}
          inventory={inventory}
          ingredients={ingredients}
          areas={areas}
        />
      </div>
    </div>
  );
}
