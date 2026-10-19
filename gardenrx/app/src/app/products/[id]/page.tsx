import { createClient } from '@/lib/db/server';
import { Badge } from '@/components/ui/badge';
import { DoseCalculator } from '@/components/dose-calculator';
import { LabelViewer } from '@/components/label-viewer';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Bug,
  Clock,
  CloudRain,
  Thermometer,
  CalendarClock,
  Shield,
  Droplets,
  FlaskConical,
  Leaf,
  ChevronDown,
  Eye,
  Hand,
  Shirt,
  Wind,
  ExternalLink,
} from 'lucide-react';
import { ProductAvatar } from '@/components/product-avatar';
import { avatarTypeFor } from '@/lib/product-visual';
import type {
  Product,
  ProductIngredient,
  ActiveIngredient,
  CropUse,
  CropGroup,
  SprayEventProduct,
} from '@/lib/database.types';
import { signalWordColors, typeColors } from '@/lib/theme';

export const dynamic = 'force-dynamic';

const ppeIcons: Record<string, typeof Eye> = {
  eye_protection: Eye,
  gloves: Hand,
  long_sleeves: Shirt,
  respirator: Wind,
};

export default async function ProductDetailPage(props: PageProps<'/products/[id]'>) {
  const { id } = await props.params;
  const supabase = await createClient();

  const productId = parseInt(id);

  // These reads are independent — run them in one round-trip batch instead of
  // six sequential awaits.
  const [
    { data: _product },
    { data: _productIngredients },
    { data: _activeIngredients },
    { data: _cropUses },
    { data: _cropGroups },
    { data: _sprayEventProducts },
  ] = await Promise.all([
    supabase.from('products').select('*').eq('id', productId).single(),
    supabase.from('product_ingredients').select('*').eq('product_id', productId),
    supabase.from('active_ingredients').select('*'),
    supabase.from('crop_uses').select('*').eq('product_id', productId),
    supabase.from('crop_groups').select('*'),
    supabase.from('spray_event_products').select('*').eq('product_id', productId),
  ]);

  const product = _product as Product | null;
  if (!product) notFound();

  const productIngredients = (_productIngredients ?? []) as ProductIngredient[];
  const activeIngredients = (_activeIngredients ?? []) as ActiveIngredient[];
  const cropUses = (_cropUses ?? []) as CropUse[];
  const cropGroups = (_cropGroups ?? []) as CropGroup[];
  const sprayEventProducts = (_sprayEventProducts ?? []) as SprayEventProduct[];

  const ingredients = productIngredients.map((pi) => ({
    ...pi,
    ingredient: activeIngredients.find((a) => a.id === pi.ingredient_id),
  }));

  const ppe = product.ppe_requirements as Record<string, unknown> | null;
  const ppeItems = ppe
    ? Object.entries(ppe)
        .filter(([, v]) => v)
        .map(([k, v]) => ({
          key: k,
          label: typeof v === 'string' ? `${k.replace(/_/g, ' ')}: ${v}` : k.replace(/_/g, ' '),
        }))
    : [];

  // Season usage count
  const seasonUses = sprayEventProducts.length;

  // Build spec items for the stat grid
  const specItems: { icon: typeof Clock; label: string; value: string }[] = [];

  if (ingredients[0]?.ingredient?.mode_of_action) {
    specItems.push({
      icon: FlaskConical,
      label: 'Mode of Action',
      value: ingredients[0].ingredient.mode_of_action,
    });
  }
  if (product.bee_toxicity) {
    specItems.push({ icon: Bug, label: 'Bee Toxicity', value: product.bee_toxicity });
  }
  if (product.rei_hours != null) {
    specItems.push({ icon: Clock, label: 'REI', value: `${product.rei_hours} hrs` });
  }
  if (product.rain_fastness_hours != null) {
    specItems.push({
      icon: CloudRain,
      label: 'Rain-fast',
      value: `${product.rain_fastness_hours} hrs`,
    });
  }
  if (product.cover_spray_interval_days != null) {
    specItems.push({
      icon: CalendarClock,
      label: 'Cover Interval',
      value: `${product.cover_spray_interval_days} days`,
    });
  }
  if (product.rain_tolerance_inches != null) {
    specItems.push({
      icon: Droplets,
      label: 'Rain Tolerance',
      value: `${product.rain_tolerance_inches}" cumul.`,
    });
  }
  if (product.temp_min != null || product.temp_max != null) {
    specItems.push({
      icon: Thermometer,
      label: 'Temp Range',
      value: `${product.temp_min ?? '\u2014'}\u00b0 \u2013 ${product.temp_max ?? '\u2014'}\u00b0F`,
    });
  }
  // Determine max apps from crop_uses if available
  const maxApps = cropUses.find((cu) => cu.max_apps_per_season != null)?.max_apps_per_season;
  specItems.push({
    icon: CalendarClock,
    label: 'Used This Season',
    value: maxApps != null ? `${seasonUses} of ${maxApps}` : `${seasonUses}`,
  });

  return (
    <div className="page">
      <div className="animate-stagger mx-auto max-w-3xl space-y-6">
        {/* Back link */}
        <Link href="/products" className="btn btn-ghost">
          <ArrowLeft className="size-4" />
          Treatments
        </Link>

        {/* Hero header */}
        <div className="space-y-3">
          <div className="flex items-start gap-4">
            <ProductAvatar
              productId={productId}
              type={avatarTypeFor(ingredients.map((pi) => pi.ingredient?.type))}
              brand={product.brand}
              imageUrl={product.image_url}
              className="w-16 h-16"
              iconClassName="w-7 h-7"
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-3">
                <h1 className="text-3xl font-heading font-semibold tracking-tight text-foreground">
                  {product.brand}
                </h1>
                {product.signal_word && (
                  <Badge
                    className={`rounded-full text-xs font-medium px-3 py-1 shrink-0 ${signalWordColors[product.signal_word]}`}
                  >
                    {product.signal_word}
                  </Badge>
                )}
              </div>
              {/* Active ingredient, always under the product name */}
              {ingredients.length > 0 && (
                <p className="text-sm text-foreground/70 mt-0.5">
                  {ingredients
                    .map((pi) => pi.ingredient?.name)
                    .filter(Boolean)
                    .join(' + ')}
                </p>
              )}
              <div className="flex items-center gap-2 text-sm text-muted-foreground/70 mt-0.5">
                {product.manufacturer && <span>{product.manufacturer}</span>}
                {product.manufacturer && product.epa_reg_number && (
                  <span className="text-muted-foreground/30">&middot;</span>
                )}
                {product.epa_reg_number && (
                  <span className="font-mono text-xs">EPA #{product.epa_reg_number}</span>
                )}
              </div>
            </div>
          </div>

          {/* Price + buy link */}
          {product.price_dollars != null && (
            <div className="flex items-center gap-3 rounded-xl bg-emerald-50/70 ring-1 ring-emerald-200/50 px-4 py-2.5">
              <div className="flex items-baseline gap-1.5">
                <span className="text-xl font-heading font-semibold text-emerald-800 tabular-nums">
                  ${Number(product.price_dollars).toFixed(2)}
                </span>
                {product.price_size && (
                  <span className="text-xs text-emerald-700/70">/ {product.price_size}</span>
                )}
              </div>
              <span className="text-[10px] text-muted-foreground/60 ml-auto">≈ Amazon</span>
              <a
                href={
                  product.retail_url ??
                  `https://www.amazon.com/s?k=${encodeURIComponent(product.brand)}`
                }
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-full bg-emerald-700 text-white px-3 py-1.5 text-xs font-medium hover:bg-emerald-800 transition-colors"
              >
                Buy
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}
        </div>

        {/* Active Ingredients */}
        <details open className="group/section">
          <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                Active Ingredients
              </p>
              <span className="text-[10px] text-muted-foreground/50">({ingredients.length})</span>
            </div>
            <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
          </summary>
          <div className="flex flex-wrap gap-2">
            {ingredients.map((pi) => {
              const type = pi.ingredient?.type;
              const colorClass = type
                ? (typeColors[type] ?? '')
                : 'bg-muted text-muted-foreground ring-1 ring-black/[0.04]';
              return (
                <div
                  key={pi.ingredient_id}
                  className={`inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-medium ${colorClass}`}
                >
                  <span>{pi.ingredient?.name}</span>
                  {pi.concentration_pct && (
                    <span className="opacity-60 text-xs">{pi.concentration_pct}%</span>
                  )}
                  {pi.ingredient?.frac_irac_hrac_group && (
                    <span className="bg-card/60 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase">
                      {pi.ingredient.type === 'fungicide'
                        ? 'FRAC'
                        : pi.ingredient.type === 'insecticide'
                          ? 'IRAC'
                          : pi.ingredient.type === 'herbicide'
                            ? 'HRAC'
                            : 'Group'}{' '}
                      {pi.ingredient.frac_irac_hrac_group}
                    </span>
                  )}
                  {pi.ingredient?.is_single_site && (
                    <span className="bg-terra-100 text-terra-700 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ring-1 ring-terra-200/60">
                      Single-site
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </details>

        {/* Spec strip */}
        <details open className="group/section">
          <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                Specifications
              </p>
              <span className="text-[10px] text-muted-foreground/50">({specItems.length})</span>
            </div>
            <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
          </summary>
          {specItems.length <= 1 ? (
            <div className="grid grid-cols-2 gap-2">
              {specItems.map((spec) => {
                const Icon = spec.icon;
                return (
                  <div
                    key={spec.label}
                    className="rounded-xl bg-card p-3 shadow-sm ring-1 ring-black/[0.04] flex items-start gap-3"
                  >
                    <div className="rounded-lg bg-emerald-50 p-1.5 shrink-0">
                      <Icon className="w-3.5 h-3.5 text-emerald-700" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 leading-none mb-1">
                        {spec.label}
                      </p>
                      <p className="text-sm font-medium text-foreground truncate">{spec.value}</p>
                    </div>
                  </div>
                );
              })}
              <div className="col-span-2 rounded-xl bg-parchment-50/60 p-3 ring-1 ring-border/30">
                <p className="text-xs text-muted-foreground/70 leading-relaxed">
                  Detailed specifications not yet available for this product. See label for complete
                  information.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {specItems.map((spec) => {
                const Icon = spec.icon;
                return (
                  <div
                    key={spec.label}
                    className="rounded-xl bg-card p-3 shadow-sm ring-1 ring-black/[0.04] flex items-start gap-3"
                  >
                    <div className="rounded-lg bg-emerald-50 p-1.5 shrink-0">
                      <Icon className="w-3.5 h-3.5 text-emerald-700" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 leading-none mb-1">
                        {spec.label}
                      </p>
                      <p className="text-sm font-medium text-foreground truncate">{spec.value}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </details>

        {/* Safety & PPE -- warm terra-toned card */}
        {(product.safety_notes || product.first_aid_summary || ppeItems.length > 0) && (
          <details open className="group/section">
            <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                  Safety & Handling
                </p>
              </div>
              <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
            </summary>
            <div className="rounded-xl bg-terra-50/60 p-4 ring-1 ring-terra-200/40 space-y-3">
              {ppeItems.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <Shield className="w-3.5 h-3.5 text-terra-600" />
                    <p className="text-xs font-semibold text-terra-800">PPE Requirements</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {ppeItems.map(({ key, label }) => {
                      const Icon = ppeIcons[key] ?? Shield;
                      return (
                        <span
                          key={key}
                          className="capitalize inline-flex items-center gap-1.5 bg-paper-2 text-ink-2 px-2.5 py-1 rounded-full text-[11px] font-medium ring-1 ring-line"
                        >
                          <Icon className="w-3 h-3 text-terra-600" />
                          {label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
              {product.safety_notes && (
                <div>
                  <p className="text-xs font-semibold text-terra-800 mb-0.5">Safety Notes</p>
                  <p className="text-sm text-terra-700/80 leading-relaxed">
                    {product.safety_notes}
                  </p>
                </div>
              )}
              {product.first_aid_summary && (
                <div>
                  <p className="text-xs font-semibold text-terra-800 mb-0.5">First Aid</p>
                  <p className="text-sm text-terra-700/80 leading-relaxed">
                    {product.first_aid_summary}
                  </p>
                </div>
              )}
            </div>
          </details>
        )}

        {/* Crop Uses */}
        {cropUses.length > 0 && (
          <details open className="group/section">
            <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                  Labeled Crops
                </p>
                <span className="text-[10px] text-muted-foreground/50">({cropUses.length})</span>
              </div>
              <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
            </summary>
            <div className="space-y-3">
              {cropUses.map((cu) => {
                const group = cropGroups.find((g) => g.id === cu.crop_group_id);
                return (
                  <details
                    key={cu.id}
                    className="group/card rounded-xl bg-card shadow-sm ring-1 ring-black/[0.04] overflow-hidden"
                  >
                    <summary className="flex items-center justify-between gap-3 p-4 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden">
                      <div className="flex items-center gap-2.5">
                        <div className="rounded-lg bg-emerald-50 p-1.5">
                          <Leaf className="w-4 h-4 text-emerald-700" />
                        </div>
                        <div>
                          <p className="font-heading font-semibold text-sm">
                            {group?.name ?? 'Unknown'}
                          </p>
                          <p className="text-xs text-muted-foreground/60">
                            {cu.rate_min}&ndash;{cu.rate_max} {cu.rate_unit}
                            {cu.phi_days != null && <> &middot; {cu.phi_days}d PHI</>}
                          </p>
                        </div>
                      </div>
                      <ChevronDown className="w-4 h-4 text-muted-foreground/60 transition-transform group-open/card:rotate-180" />
                    </summary>
                    <div className="px-4 pb-4 pt-0 space-y-3">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded-lg bg-parchment-50 p-2.5">
                          <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 mb-0.5">
                            Rate
                          </p>
                          <p className="text-sm font-medium">
                            {cu.rate_min}&ndash;{cu.rate_max} {cu.rate_unit}
                          </p>
                        </div>
                        {cu.phi_days != null && (
                          <div className="rounded-lg bg-parchment-50 p-2.5">
                            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 mb-0.5">
                              PHI
                            </p>
                            <p className="text-sm font-medium">{cu.phi_days} days</p>
                          </div>
                        )}
                        {cu.max_apps_per_season != null && (
                          <div className="rounded-lg bg-parchment-50 p-2.5">
                            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 mb-0.5">
                              Max Apps
                            </p>
                            <p className="text-sm font-medium">
                              <span className="text-emerald-700">{seasonUses}</span>
                              <span className="text-muted-foreground/60"> / </span>
                              {cu.max_apps_per_season}
                            </p>
                          </div>
                        )}
                        {cu.min_interval_days != null && (
                          <div className="rounded-lg bg-parchment-50 p-2.5">
                            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60 mb-0.5">
                              Min Interval
                            </p>
                            <p className="text-sm font-medium">{cu.min_interval_days} days</p>
                          </div>
                        )}
                      </div>
                      {cu.growth_stage_restrictions && (
                        <p className="text-xs text-muted-foreground/70 italic leading-relaxed">
                          {cu.growth_stage_restrictions}
                        </p>
                      )}
                      {cu.restrictions_text && (
                        <details className="text-xs text-muted-foreground/70">
                          <summary className="cursor-pointer font-medium text-emerald-700 hover:text-emerald-800 transition-colors">
                            View full restrictions
                          </summary>
                          <p className="mt-2 pl-3 border-l-2 border-emerald-200 leading-relaxed">
                            {cu.restrictions_text}
                          </p>
                        </details>
                      )}
                      <DoseCalculator
                        rateMin={cu.rate_min}
                        rateMax={cu.rate_max}
                        rateUnit={cu.rate_unit}
                      />
                    </div>
                  </details>
                );
              })}
            </div>
          </details>
        )}

        {/* Full Product Label — searchable embedded */}
        <details open className="group/section">
          <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                Product Label
              </p>
            </div>
            <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
          </summary>
          <LabelViewer productId={productId} />
        </details>
      </div>
    </div>
  );
}
