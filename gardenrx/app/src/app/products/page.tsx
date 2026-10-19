import Link from 'next/link';
import { Clock, CalendarClock } from 'lucide-react';
import { ProductSearch } from '@/components/product-search';
import { ProductAvatar } from '@/components/product-avatar';
import { avatarTypeFor } from '@/lib/product-visual';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';
import type { Product, ActiveIngredient } from '@/lib/database.types';
import { typeDot } from '@/lib/theme';
import {
  fetchProducts,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchCrops,
  fetchCropUses,
  fetchCropGroups,
} from '@/lib/queries';
import { categoryForCrop } from '@/lib/crop-category';
import { SectionTabs, TREATMENT_TABS } from '@/components/shell/section-tabs';

export const dynamic = 'force-dynamic';

const TYPE_ORDER = ['fungicide', 'insecticide', 'bactericide', 'herbicide', 'combo'] as const;
const TYPE_LABEL: Record<string, string> = {
  fungicide: 'Fungicides',
  insecticide: 'Insecticides',
  bactericide: 'Bactericides',
  herbicide: 'Herbicides',
  combo: 'Combination Sprays',
};

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; type?: string; crop?: string }>;
}) {
  const params = await searchParams;

  const [products, productIngredients, activeIngredients, crops, cropUses, cropGroups] =
    await Promise.all([
      fetchProducts(),
      fetchProductIngredients(),
      fetchActiveIngredients(),
      fetchCrops({ activeOnly: true }),
      fetchCropUses(),
      fetchCropGroups(),
    ]);

  const activeProducts = products.filter((p) => ACTIVE_PRODUCT_IDS.has(p.id));

  // product → its active ingredients
  const ingredientsByProduct = new Map<number, ActiveIngredient[]>();
  for (const pi of productIngredients) {
    const ing = activeIngredients.find((a) => a.id === pi.ingredient_id);
    if (ing) {
      const list = ingredientsByProduct.get(pi.product_id) ?? [];
      list.push(ing);
      ingredientsByProduct.set(pi.product_id, list);
    }
  }

  // Crops we can filter by (must belong to a crop group to map onto labels),
  // tagged with their garden zone so the picker can group them.
  const groupName = new Map(cropGroups.map((g) => [g.id, g.name] as const));
  const filterableCrops = crops
    .filter((c) => c.crop_group_id != null)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => ({
      id: c.id,
      name: c.name,
      category: categoryForCrop(
        c,
        c.crop_group_id ? (groupName.get(c.crop_group_id) ?? null) : null
      ),
    }));

  // ── filters ──
  let filtered = activeProducts;

  if (params.q) {
    const q = params.q.toLowerCase();
    filtered = filtered.filter((p) => {
      const ings = ingredientsByProduct.get(p.id) ?? [];
      return (
        p.brand.toLowerCase().includes(q) || ings.some((i) => i.name.toLowerCase().includes(q))
      );
    });
  }

  if (params.type) {
    filtered = filtered.filter((p) =>
      (ingredientsByProduct.get(p.id) ?? []).some((i) => i.type === params.type)
    );
  }

  let activeCropName: string | null = null;
  if (params.crop) {
    const cropId = Number(params.crop);
    const crop = Number.isFinite(cropId) ? crops.find((c) => c.id === cropId) : undefined;
    activeCropName = crop?.name ?? null;
    const groupId = crop?.crop_group_id ?? null;
    if (groupId == null) {
      filtered = []; // crop isn't mapped to a label group → nothing to show
    } else {
      const productIdsForGroup = new Set(
        cropUses.filter((cu) => cu.crop_group_id === groupId).map((cu) => cu.product_id)
      );
      filtered = filtered.filter((p) => productIdsForGroup.has(p.id));
    }
  }

  // ── group into sections by type (multi-ingredient → combo) ──
  const sections = new Map<string, Product[]>();
  for (const p of filtered) {
    const ings = ingredientsByProduct.get(p.id) ?? [];
    const key = ings.length > 1 ? 'combo' : (ings[0]?.type ?? 'combo');
    const list = sections.get(key) ?? [];
    list.push(p);
    sections.set(key, list);
  }
  for (const list of sections.values()) list.sort((a, b) => a.brand.localeCompare(b.brand));

  const total = filtered.length;

  return (
    <div className="page">
      <div className="section-title">
        <h2>Treatments</h2>
        <span className="meta">
          {total} {total === 1 ? 'product' : 'products'}
          {activeCropName ? ` · ${activeCropName}` : params.q || params.type ? ' · matching' : ''}
        </span>
      </div>

      <SectionTabs tabs={TREATMENT_TABS} />

      <div className="mb-4">
        <ProductSearch crops={filterableCrops} />
      </div>

      <div className="space-y-8 animate-stagger">
        {TYPE_ORDER.map((type) => {
          const list = sections.get(type);
          if (!list || list.length === 0) return null;
          return (
            <section key={type}>
              <div className="flex items-center gap-2 mb-3">
                <div className={`w-2 h-2 rounded-full ${typeDot[type] ?? 'bg-fuchsia-500'}`} />
                <h2 className="text-sm font-heading font-semibold tracking-wide uppercase text-muted-foreground/70">
                  {TYPE_LABEL[type]}
                </h2>
                <span className="text-[10px] text-muted-foreground/40">({list.length})</span>
                <div className="flex-1 h-px bg-border/40" />
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {list.map((product) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    ingredients={ingredientsByProduct.get(product.id) ?? []}
                  />
                ))}
              </div>
            </section>
          );
        })}

        {total === 0 && (
          <p className="text-muted-foreground text-sm py-12 text-center">
            No products found{activeCropName ? ` for ${activeCropName}` : ''}.
          </p>
        )}
      </div>
    </div>
  );
}

function ProductCard({
  product,
  ingredients,
}: {
  product: Product;
  ingredients: ActiveIngredient[];
}) {
  const rei = product.rei_hours;
  const interval = product.cover_spray_interval_days;
  const primary = ingredients[0];
  const groupLabel = primary?.frac_irac_hrac_group
    ? `${primary.type === 'fungicide' ? 'FRAC' : primary.type === 'insecticide' ? 'IRAC' : primary.type === 'herbicide' ? 'HRAC' : 'Grp'} ${primary.frac_irac_hrac_group}`
    : null;

  return (
    <Link
      href={`/products/${product.id}`}
      className="group flex items-start gap-3 rounded-xl bg-card p-3 shadow-sm ring-1 ring-black/[0.04] hover:shadow-md hover:ring-emerald-200/70 transition-all duration-200"
    >
      <ProductAvatar
        productId={product.id}
        type={avatarTypeFor(ingredients.map((i) => i.type))}
        brand={product.brand}
        imageUrl={product.image_url}
      />
      <div className="min-w-0 flex-1">
        <p className="font-heading font-semibold text-sm leading-tight group-hover:text-emerald-800 transition-colors">
          {product.brand}
        </p>
        {/* Active ingredient — always shown under the product name */}
        <p className="text-[11.5px] text-muted-foreground leading-snug mt-0.5">
          {ingredients.length > 0 ? ingredients.map((i) => i.name).join(' + ') : '—'}
          {groupLabel && (
            <span className="ml-1.5 text-[10px] font-medium text-muted-foreground/60 bg-muted/60 px-1.5 py-0.5 rounded">
              {groupLabel}
            </span>
          )}
        </p>
        {(rei != null || interval != null) && (
          <div className="flex items-center gap-1.5 mt-1.5 tabular-nums">
            {rei != null && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-muted/60 text-foreground/60 px-1.5 py-0.5 text-[10px] font-medium"
                title="Re-entry interval"
              >
                <Clock className="w-2.5 h-2.5" />
                {rei}h
              </span>
            )}
            {interval != null && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-800 px-1.5 py-0.5 text-[10px] font-medium"
                title="Cover-spray interval"
              >
                <CalendarClock className="w-2.5 h-2.5" />
                {interval}d
              </span>
            )}
          </div>
        )}
      </div>
      {product.price_dollars != null && (
        <div className="text-right shrink-0">
          <p className="text-sm font-semibold text-emerald-700 tabular-nums leading-none">
            ${Number(product.price_dollars).toFixed(2)}
          </p>
          {product.price_size && (
            <p className="text-[10px] text-muted-foreground/60 mt-0.5">{product.price_size}</p>
          )}
        </div>
      )}
    </Link>
  );
}
