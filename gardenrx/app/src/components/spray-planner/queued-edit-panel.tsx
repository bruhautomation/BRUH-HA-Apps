'use client';

import { useState } from 'react';
import type { Product } from '@/lib/database.types';
import { Check, Search, X } from 'lucide-react';
import { productLabel } from '@/lib/product-label';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';

export function QueuedEditPanel({
  allProducts,
  selectedProducts,
  rates,
  notes,
  ingredientMap,
  onToggleProduct,
  onRateChange,
  onNotesChange,
  onSave,
  onCancel,
  saving,
}: {
  allProducts: Product[];
  selectedProducts: number[];
  rates: Record<number, number>;
  notes: string;
  ingredientMap: Map<number, Array<{ name: string }>>;
  onToggleProduct: (pid: number) => void;
  onRateChange: (pid: number, rate: number) => void;
  onNotesChange: (notes: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [search, setSearch] = useState('');

  // When searching, only show active products (with selected ones still
  // visible). With no search, show whatever was already selected on this queued
  // spray, even if a product has since been deactivated.
  const filtered = search
    ? allProducts.filter(
        (p) =>
          (ACTIVE_PRODUCT_IDS.has(p.id) || selectedProducts.includes(p.id)) &&
          p.brand.toLowerCase().includes(search.toLowerCase())
      )
    : allProducts.filter((p) => selectedProducts.includes(p.id));

  return (
    <div className="border-t border-emerald-200/30 px-3.5 py-3.5 space-y-3">
      <p className="text-[10px] font-medium tracking-widest uppercase text-muted-foreground/50">
        Edit Products
      </p>

      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/60" />
        <input
          type="text"
          placeholder="Search products to add..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg ring-1 ring-border/60 bg-card focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-2 top-1/2 -translate-y-1/2"
          >
            <X className="w-3 h-3 text-muted-foreground/60" />
          </button>
        )}
      </div>

      <div className="max-h-48 overflow-y-auto space-y-1">
        {filtered.map((p) => {
          const selected = selectedProducts.includes(p.id);
          return (
            <div key={p.id}>
              <button
                onClick={() => onToggleProduct(p.id)}
                className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                  selected ? 'bg-emerald-50 ring-1 ring-emerald-300' : 'hover:bg-muted/50'
                }`}
              >
                <div
                  className={`w-3.5 h-3.5 rounded border-2 flex items-center justify-center shrink-0 ${
                    selected ? 'bg-emerald-600 border-emerald-600' : 'border-muted-foreground/30'
                  }`}
                >
                  {selected && <Check className="w-2 h-2 text-white" />}
                </div>
                <span className={selected ? 'font-medium' : 'text-muted-foreground'}>
                  {productLabel(p.brand, ingredientMap.get(p.id))}
                </span>
              </button>
              {selected && (
                <div className="flex items-center gap-2 pl-8 pr-2 py-1">
                  <label className="text-[10px] text-muted-foreground shrink-0">Rate:</label>
                  <input
                    type="number"
                    step="0.1"
                    value={rates[p.id] ?? ''}
                    onChange={(e) => onRateChange(p.id, parseFloat(e.target.value) || 0)}
                    className="w-20 h-6 text-[11px] rounded border ring-1 ring-border/40 px-1.5 bg-card focus:outline-none focus:ring-emerald-400/50"
                    placeholder="e.g. 1.5"
                  />
                </div>
              )}
            </div>
          );
        })}
        {search && filtered.length === 0 && (
          <p className="text-[11px] text-muted-foreground/50 text-center py-3">
            No products match &quot;{search}&quot;
          </p>
        )}
      </div>

      <input
        type="text"
        placeholder="Notes (optional)"
        value={notes}
        onChange={(e) => onNotesChange(e.target.value)}
        className="w-full px-2.5 py-1.5 text-xs rounded-lg ring-1 ring-border/60 bg-card focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
      />

      <div className="flex gap-2">
        <button
          onClick={onCancel}
          className="flex-1 rounded-lg py-2 text-xs font-medium text-muted-foreground ring-1 ring-border hover:bg-muted transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onSave}
          disabled={saving || selectedProducts.length === 0}
          className="flex-[2] bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 rounded-lg py-2 text-xs font-medium transition-colors"
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
}
