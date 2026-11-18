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
import { PageShell } from '@/components/ui/page-shell';

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
    <PageShell width="narrow" title="Treatments" meta="Your stock · on hand">
      <SectionTabs tabs={TREATMENT_TABS} />
      <InventoryList
        products={products}
        inventory={inventory}
        ingredients={ingredients}
        areas={areas}
      />
    </PageShell>
  );
}
