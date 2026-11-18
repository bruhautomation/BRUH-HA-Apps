'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { Product, ActiveIngredient, Database } from '@/lib/database.types';
import { createClient } from '@/lib/db/client';
import { Plus, Trash2, Search, X, Package, ExternalLink, ArrowDownUp, Pencil } from 'lucide-react';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';
import { ProductAvatar } from '@/components/product-avatar';
import { avatarTypeFor } from '@/lib/product-visual';
import { CATEGORY_ORDER, type CropCategory } from '@/lib/crop-category';
import { AREA_STYLE } from '@/lib/area-meta';
import { formForUnit, containerNoun, parseSize, UNIT_GROUPS } from '@/lib/container';

/** A numeric input that only saves on blur or Enter — no per-keystroke writes */
function DebouncedNumber({
  value,
  onCommit,
  placeholder,
  className,
  prefix,
}: {
  value: number | null;
  onCommit: (v: number | null) => void;
  placeholder?: string;
  className?: string;
  prefix?: string;
}) {
  const [local, setLocal] = useState(value?.toString() ?? '');
  const [prevValue, setPrevValue] = useState(value);
  if (value !== prevValue) {
    setPrevValue(value);
    setLocal(value?.toString() ?? '');
  }
  function commit() {
    const parsed = parseFloat(local);
    onCommit(isNaN(parsed) ? null : parsed);
  }
  return (
    <span className="inline-flex items-center gap-0.5">
      {prefix && <span className="text-base text-muted-foreground">{prefix}</span>}
      <input
        type="text"
        inputMode="decimal"
        placeholder={placeholder}
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur();
        }}
        className={className}
      />
    </span>
  );
}

/**
 * Draggable stock level. The bar *is* the slider — drag it to set how much is
 * left. We still keep an absolute quantity on hand (so logging a spray can
 * subtract a real amount), so the committed value is quantity = (% ÷ 100) × capacity.
 */
function StockSlider({
  pct,
  capacity,
  onCommit,
}: {
  pct: number | null;
  capacity: number | null;
  onCommit: (quantity: number) => void;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  const disabled = capacity == null;
  const shown = drag ?? pct ?? 0;
  const barColor = disabled
    ? 'bg-muted'
    : shown > 50
      ? 'bg-emerald-500'
      : shown > 20
        ? 'bg-amber-500'
        : 'bg-terra-500';
  const pctColor = disabled
    ? 'text-muted-foreground/40'
    : shown > 50
      ? 'text-emerald-700'
      : shown > 20
        ? 'text-warn'
        : 'text-terra-600';

  function commit(v: number) {
    if (capacity == null) return;
    onCommit(Math.round((v / 100) * capacity * 100) / 100);
    setDrag(null);
  }

  return (
    <div
      className="flex items-center gap-2"
      title={
        disabled
          ? 'Set a container size below to track % remaining'
          : 'Drag to set how much is left'
      }
    >
      <div className="relative flex-1 h-2">
        <div className="absolute inset-0 rounded-full bg-muted/50 overflow-hidden">
          {!disabled && (
            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${shown}%` }} />
          )}
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={shown}
          disabled={disabled}
          aria-label="Percent remaining"
          onChange={(e) => setDrag(Number(e.target.value))}
          onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
          onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
          onBlur={() => {
            if (drag != null) commit(drag);
          }}
          className="absolute inset-x-0 -inset-y-2 w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        />
      </div>
      <span className={`text-xs font-semibold tabular-nums shrink-0 ${pctColor}`}>
        {disabled ? '—' : `${Math.round(shown)}%`}
        <span className="text-xs font-normal text-muted-foreground/50 ml-0.5">left</span>
      </span>
    </div>
  );
}

interface InventoryItem {
  id: number;
  product_id: number;
  quantity: number;
  unit: string;
  purchase_date: string | null;
  notes: string | null;
  updated_at: string;
  bottle_size: number | null;
  bottle_unit: string | null;
  bottles: number | null;
  cost_dollars: number | null;
  image_url: string | null;
}

type SortKey = 'name' | 'area' | 'stock';

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function InventoryList({
  products,
  inventory,
  ingredients,
  areas,
}: {
  products: Product[];
  inventory: InventoryItem[];
  ingredients: Record<number, ActiveIngredient[]>;
  areas: Record<number, CropCategory[]>;
}) {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [areaFilter, setAreaFilter] = useState<CropCategory | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>('name');
  const [editing, setEditing] = useState<Set<number>>(new Set());
  const toggleEditing = (id: number) =>
    setEditing((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const aiNames = (id: number) => (ingredients[id] ?? []).map((i) => i.name).join(' + ');
  const avatarType = (id: number) => avatarTypeFor((ingredients[id] ?? []).map((i) => i.type));
  const areasFor = (id: number) => areas[id] ?? [];

  const inStock = inventory.flatMap((inv) => {
    const product = products.find((p) => p.id === inv.product_id);
    if (!product) return [];
    const capacity =
      inv.bottle_size && inv.bottle_size > 0
        ? inv.bottle_size * (inv.bottles && inv.bottles > 0 ? inv.bottles : 1)
        : null;
    const pct = capacity ? Math.min(100, Math.round((inv.quantity / capacity) * 100)) : null;
    return [{ ...inv, product, capacity, pct, areas: areasFor(product.id) }];
  });

  const searchResults = search
    ? products
        .filter((p) => ACTIVE_PRODUCT_IDS.has(p.id))
        .filter((p) => !inventory.some((inv) => inv.product_id === p.id))
        .filter(
          (p) =>
            p.brand.toLowerCase().includes(search.toLowerCase()) ||
            aiNames(p.id).toLowerCase().includes(search.toLowerCase())
        )
        .slice(0, 8)
    : [];

  // ── filter + sort ──
  const presentAreas = CATEGORY_ORDER.filter((a) => inStock.some((i) => i.areas.includes(a)));
  const areaRank = (a: CropCategory[]) => {
    const first = CATEGORY_ORDER.find((c) => a.includes(c));
    return first ? CATEGORY_ORDER.indexOf(first) : CATEGORY_ORDER.length;
  };
  type StockItem = (typeof inStock)[number];
  const sortItems = (items: StockItem[]) => {
    const byName = (a: StockItem, b: StockItem) => a.product.brand.localeCompare(b.product.brand);
    return [...items].sort((a, b) => {
      if (sortBy === 'area') return areaRank(a.areas) - areaRank(b.areas) || byName(a, b);
      if (sortBy === 'stock') return (a.pct ?? Infinity) - (b.pct ?? Infinity) || byName(a, b);
      return byName(a, b);
    });
  };

  const matched = sortItems(
    areaFilter ? inStock.filter((i) => i.areas.includes(areaFilter)) : inStock
  );
  const outside = areaFilter ? sortItems(inStock.filter((i) => !i.areas.includes(areaFilter))) : [];

  async function addToInventory(productId: number) {
    setSaving(true);
    const product = products.find((p) => p.id === productId);
    const { size, unit } = parseSize(product?.price_size ?? null);
    await createClient()
      .from('treatment_inventory')
      .insert({
        product_id: productId,
        quantity: size ?? 0,
        unit,
        bottle_size: size,
        bottle_unit: unit,
        bottles: 1,
        cost_dollars: product?.price_dollars ?? null,
      });
    setSaving(false);
    setSearch('');
    router.refresh();
  }

  async function updateField(id: number, field: string, value: number | string | null) {
    const inv = inStock.find((i) => i.id === id);
    const supabase = createClient();
    const patch = {
      [field]: value,
      updated_at: new Date().toISOString(),
    } as Database['public']['Tables']['treatment_inventory']['Update'];
    const { error } = await supabase.from('treatment_inventory').update(patch).eq('id', id);
    if (error) {
      console.error(error);
      window.alert(`Couldn't save ${field.replace(/_/g, ' ')}: ${error.message}`);
      router.refresh();
      return;
    }
    // Your inventory numbers are the source of truth — push the per-bottle cost (and
    // bottle size) to the product so the price shows the same everywhere.
    if (inv) {
      if (field === 'cost_dollars') {
        await supabase
          .from('products')
          .update({ price_dollars: value as number | null })
          .eq('id', inv.product_id);
      } else if (field === 'bottle_size') {
        await supabase
          .from('products')
          .update({ price_size: value != null ? `${value} ${inv.bottle_unit ?? inv.unit}` : null })
          .eq('id', inv.product_id);
      }
    }
    router.refresh();
  }

  const VOLUME_FACTORS: Record<string, number> = {
    mL: 1 / 29.5735,
    'fl oz': 1,
    tbsp: 0.5,
    tsp: 1 / 6,
    pt: 16,
    qt: 32,
    gal: 128,
  };
  const WEIGHT_FACTORS: Record<string, number> = { g: 1 / 28.3495, oz: 1, lb: 16 };
  function unitCategory(u: string): 'volume' | 'weight' | 'count' | 'unknown' {
    if (u in VOLUME_FACTORS) return 'volume';
    if (u in WEIGHT_FACTORS) return 'weight';
    if (u === 'packets' || u === 'ct') return 'count';
    return 'unknown';
  }

  async function updateUnit(id: number, newUnit: string) {
    const inv = inStock.find((i) => i.id === id);
    if (!inv) {
      router.refresh();
      return;
    }
    const oldCat = unitCategory(inv.unit);
    const newCat = unitCategory(newUnit);
    let newQty = inv.quantity;
    let newBottle = inv.bottle_size;
    if (oldCat === newCat && (oldCat === 'volume' || oldCat === 'weight')) {
      const factors = oldCat === 'volume' ? VOLUME_FACTORS : WEIGHT_FACTORS;
      const ratio = factors[inv.unit] / factors[newUnit];
      newQty = Math.round(inv.quantity * ratio * 100) / 100;
      newBottle = inv.bottle_size ? Math.round(inv.bottle_size * ratio * 100) / 100 : null;
    } else if (oldCat !== newCat) {
      // Crossing volume/weight/count: no meaningful numeric conversion — drop the
      // bottle size so "% Left" isn't computed from mismatched units.
      newBottle = null;
    }
    const supabase = createClient();
    const { error } = await supabase
      .from('treatment_inventory')
      .update({
        unit: newUnit,
        quantity: newQty,
        bottle_size: newBottle,
        bottle_unit: newUnit,
        updated_at: new Date().toISOString(),
      })
      .eq('id', id);
    if (error) {
      console.error(error);
      window.alert(`Couldn't change unit: ${error.message}`);
      router.refresh();
      return;
    }
    await supabase
      .from('products')
      .update({ price_size: newBottle != null ? `${newBottle} ${newUnit}` : null })
      .eq('id', inv.product_id);
    router.refresh();
  }

  async function removeFromInventory(id: number) {
    const { error } = await createClient().from('treatment_inventory').delete().eq('id', id);
    if (error) {
      console.error(error);
      window.alert(`Couldn't remove: ${error.message}`);
    }
    router.refresh();
  }

  const numCls =
    'w-24 h-10 text-right text-base tabular-nums rounded-md ring-1 ring-border/50 bg-card px-2 focus:outline-none focus:ring-2 focus:ring-emerald-400/50';
  const unitCls =
    'h-10 text-base rounded-md ring-1 ring-border/50 bg-card pl-1 pr-0.5 focus:outline-none';
  const lblCls = 'text-xs font-medium text-muted-foreground';

  const renderCard = (inv: StockItem, dimmed = false) => {
    const product = inv.product;
    const form = formForUnit(inv.unit);
    const noun = containerNoun(form);
    const bottleCount = inv.bottles && inv.bottles > 0 ? inv.bottles : 1;
    const pct = inv.pct;
    const open = editing.has(inv.id);
    return (
      <div
        key={inv.id}
        className={`rounded-xl bg-card ring-1 ring-black/[0.05] shadow-sm p-3 transition-opacity ${dimmed ? 'opacity-55 hover:opacity-100' : ''}`}
      >
        {/* header: product + reorder/remove */}
        <div className="flex items-center gap-3 mb-2">
          <ProductAvatar
            productId={product.id}
            type={avatarType(product.id)}
            brand={product.brand}
            imageUrl={product.image_url}
            className="w-10 h-10 shrink-0"
            iconClassName="w-4 h-4"
            rounded="rounded-md"
          />
          <div className="min-w-0 flex-1">
            <Link
              href={`/products/${product.id}`}
              className="font-medium text-sm line-clamp-2 break-words hover:text-emerald-800 transition-colors leading-tight"
            >
              {product.brand}
            </Link>
            {aiNames(product.id) && (
              <span className="text-xs text-muted-foreground line-clamp-1 block">
                {aiNames(product.id)}
              </span>
            )}
          </div>
          <button
            onClick={() => toggleEditing(inv.id)}
            aria-expanded={open}
            aria-label={`${open ? 'Done editing' : 'Edit'} ${product.brand}`}
            className={`grid size-10 shrink-0 place-items-center rounded-full transition-colors ${
              open
                ? 'bg-emerald-100 text-emerald-800'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {open ? <X className="w-4 h-4" /> : <Pencil className="w-4 h-4" />}
          </button>
        </div>

        {/* how much is left — drag the bar to set the level (quantity is derived) */}
        <StockSlider
          pct={pct}
          capacity={inv.capacity}
          onCommit={(qty) => updateField(inv.id, 'quantity', qty)}
        />
        <p className="text-xs text-muted-foreground mt-1 tabular-nums">
          {inv.capacity != null
            ? `${+inv.quantity.toFixed(2)} of ${+inv.capacity.toFixed(2)} ${inv.unit} · ${bottleCount} ${containerNoun(form, bottleCount)}`
            : `${+inv.quantity.toFixed(2)} ${inv.unit} on hand`}
        </p>

        {open && (
          <div className="mt-3 flex flex-col gap-3 border-t border-border/40 pt-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
              <label
                className="flex items-center gap-2"
                title={`Full size of one ${noun} (what you bought)`}
              >
                <span className={lblCls}>{cap(noun)} size</span>
                <DebouncedNumber
                  value={inv.bottle_size}
                  onCommit={(v) => updateField(inv.id, 'bottle_size', v)}
                  placeholder="—"
                  className={numCls}
                />
                <select
                  value={inv.unit}
                  onChange={(e) => updateUnit(inv.id, e.target.value)}
                  className={unitCls}
                  title="Unit this product is measured in"
                >
                  {UNIT_GROUPS.map((g) => (
                    <optgroup key={g.label} label={g.label}>
                      {g.units.map((u) => (
                        <option key={u} value={u}>
                          {u}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              <label
                className="flex items-center gap-2"
                title={`How many ${containerNoun(form, 2)} you keep on hand (the level bar measures across all of them)`}
              >
                <span className={lblCls}>{cap(containerNoun(form, 2))}</span>
                <DebouncedNumber
                  value={inv.bottles}
                  onCommit={(v) =>
                    updateField(inv.id, 'bottles', v != null && v >= 1 ? Math.round(v) : null)
                  }
                  placeholder="1"
                  className={numCls}
                />
              </label>
              <label className="flex items-center gap-2">
                <span
                  className={lblCls}
                  title={`Price for ONE ${noun} (not your total). Drives spray-cost math across the app.`}
                >
                  Cost / {noun}
                </span>
                <DebouncedNumber
                  value={inv.cost_dollars}
                  onCommit={(v) => updateField(inv.id, 'cost_dollars', v)}
                  placeholder="—"
                  prefix="$"
                  className="w-24 h-10 text-right text-base tabular-nums rounded-md ring-1 ring-border/50 bg-card px-2 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
              </label>
            </div>
            {inv.areas.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className={lblCls}>Used for</span>
                {inv.areas.map((a) => {
                  const Icon = AREA_STYLE[a].icon;
                  return (
                    <span
                      key={a}
                      className={`inline-flex items-center gap-1 rounded-full text-xs font-medium px-3 py-1 ring-1 ${AREA_STYLE[a].badge}`}
                    >
                      <Icon className="w-3 h-3" />
                      {a}
                    </span>
                  );
                })}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {product.price_dollars != null && (
                <a
                  href={
                    product.retail_url ??
                    `https://www.amazon.com/s?k=${encodeURIComponent(product.brand)}`
                  }
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex h-10 items-center gap-2 rounded-full px-3 text-sm font-medium text-leaf ring-1 ring-border/60"
                >
                  <ExternalLink className="w-4 h-4" /> Reorder · $
                  {Number(product.price_dollars).toFixed(2)}
                </a>
              )}
              <button
                onClick={() => removeFromInventory(inv.id)}
                className="inline-flex h-10 items-center gap-2 rounded-full px-3 text-sm font-medium text-terra-600 ring-1 ring-border/60"
              >
                <Trash2 className="w-4 h-4" /> Remove from stock
              </button>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Add a product to your stock */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
        <input
          type="text"
          placeholder="Add a product to your stock..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full h-10 pl-9 pr-11 text-base rounded-xl ring-1 ring-black/[0.06] bg-card shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            aria-label="Clear search"
            className="absolute right-0.5 top-1/2 -translate-y-1/2 grid size-10 place-items-center"
          >
            <X className="w-3.5 h-3.5 text-muted-foreground/50" />
          </button>
        )}
      </div>

      {searchResults.length > 0 && (
        <div className="rounded-xl ring-1 ring-border/40 bg-card shadow-sm divide-y divide-border/30 overflow-hidden">
          {searchResults.map((p) => (
            <button
              key={p.id}
              onClick={() => addToInventory(p.id)}
              disabled={saving}
              className="w-full flex items-center gap-3 px-3 py-3 text-left hover:bg-emerald-50/50 transition-colors"
            >
              <ProductAvatar
                productId={p.id}
                type={avatarType(p.id)}
                brand={p.brand}
                imageUrl={p.image_url}
                className="w-10 h-10"
                iconClassName="w-4 h-4"
                rounded="rounded-lg"
              />
              <div className="min-w-0 flex-1">
                <span className="font-medium text-sm truncate block">{p.brand}</span>
                {aiNames(p.id) && (
                  <span className="text-xs text-muted-foreground truncate block">
                    {aiNames(p.id)}
                  </span>
                )}
              </div>
              {p.price_dollars != null && (
                <span className="text-xs font-semibold text-emerald-700 tabular-nums shrink-0">
                  ${Number(p.price_dollars).toFixed(2)}
                </span>
              )}
              <Plus className="w-4 h-4 text-emerald-500 shrink-0" />
            </button>
          ))}
        </div>
      )}

      {/* Filter + sort controls */}
      {inStock.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setAreaFilter(null)}
              className={`min-h-10 text-sm font-medium px-3 rounded-full ring-1 transition-all ${
                !areaFilter
                  ? 'bg-foreground text-card ring-foreground shadow-sm'
                  : 'bg-card text-muted-foreground ring-border/60 hover:ring-border'
              }`}
            >
              All <span className="opacity-60">{inStock.length}</span>
            </button>
            {presentAreas.map((a) => {
              const Icon = AREA_STYLE[a].icon;
              const count = inStock.filter((i) => i.areas.includes(a)).length;
              const active = areaFilter === a;
              return (
                <button
                  key={a}
                  onClick={() => setAreaFilter(active ? null : a)}
                  className={`inline-flex min-h-10 items-center gap-1 text-sm font-medium px-3 rounded-full ring-1 transition-all ${
                    active
                      ? AREA_STYLE[a].chip
                      : 'bg-card text-muted-foreground ring-border/60 hover:ring-border'
                  }`}
                >
                  <Icon className="w-3 h-3" />
                  {a} <span className="opacity-60">{count}</span>
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-1 ml-auto">
            <ArrowDownUp className="w-3 h-3 text-muted-foreground/50" />
            {(['name', 'area', 'stock'] as SortKey[]).map((k) => (
              <button
                key={k}
                onClick={() => setSortBy(k)}
                className={`min-h-10 text-sm font-medium px-3 rounded-md transition-colors ${
                  sortBy === k
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                title={k === 'stock' ? 'Sort by % remaining (low first)' : `Sort by ${k}`}
              >
                {k === 'stock' ? '% left' : cap(k)}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Stock cards */}
      {inStock.length === 0 ? (
        <div className="text-center py-12 rounded-xl bg-card ring-1 ring-black/[0.05] shadow-sm">
          <Package className="w-8 h-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="font-heading font-semibold text-foreground mb-1">No products in stock</p>
          <p className="text-sm text-muted-foreground">
            Search above to add products you have on hand.
          </p>
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
            {matched.map((inv) => renderCard(inv))}
          </div>

          {areaFilter && matched.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-6">
              No products in stock for {areaFilter}.
            </p>
          )}

          {/* Out-of-filter products — kept visible but dimmed, pushed to the bottom */}
          {outside.length > 0 && (
            <>
              <div className="flex items-center gap-2 mt-5 mb-2">
                <div className="h-px flex-1 bg-border/50" />
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground/50">
                  Not used in {areaFilter}
                </span>
                <div className="h-px flex-1 bg-border/50" />
              </div>
              <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
                {outside.map((inv) => renderCard(inv, true))}
              </div>
            </>
          )}

          <p className="text-xs text-muted-foreground/50 px-1 py-2">
            Drag the level bar to set how much is left; tap the pencil to edit size, count and cost.{' '}
            {inStock.length} {inStock.length === 1 ? 'product' : 'products'} in stock.
          </p>
        </div>
      )}
    </div>
  );
}
