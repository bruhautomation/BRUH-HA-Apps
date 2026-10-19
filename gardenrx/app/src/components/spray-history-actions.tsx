'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type {
  Product,
  Crop,
  CropGroup,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
} from '@/lib/database.types';
import { createClient } from '@/lib/db/client';
import { DialogFooter } from '@/components/ui/dialog';
import { FormDialog, ConfirmDialog } from '@/components/ui/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Plus, Pencil, Trash2, X, Search } from 'lucide-react';
import { productLabel } from '@/lib/product-label';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';
import { CropChips } from '@/components/crop-chips';

type IngredientMap = Map<number, Array<{ name: string }>>;

const RATE_UNITS = [
  'fl oz/gal',
  'tbsp/gal',
  'tsp/gal',
  'mL/gal',
  'g/gal',
  'oz/gal',
  'oz/100gal',
  'pt/100gal',
  'qt/100gal',
  'lb/100gal',
  'oz/acre',
  'pt/acre',
  'qt/acre',
  'lb/acre',
] as const;

// Searchable product picker — shows selected products + search to add more
function SearchableProductPicker({
  products,
  selectedIds,
  rates,
  units,
  ingredientMap,
  onToggle,
  onRateChange,
  onUnitChange,
}: {
  products: Product[];
  selectedIds: number[];
  rates: Record<number, string>;
  units: Record<number, string>;
  ingredientMap: IngredientMap;
  onToggle: (pid: number) => void;
  onRateChange: (pid: number, val: string) => void;
  onUnitChange: (pid: number, val: string) => void;
}) {
  const [search, setSearch] = useState('');

  // Show selected products first (even if no longer in the active list, so we
  // can render the existing selection on an old spray event); only allow active
  // products to be picked through search.
  const selected = products.filter((p) => selectedIds.includes(p.id));
  const searchResults = search
    ? products
        .filter((p) => ACTIVE_PRODUCT_IDS.has(p.id))
        .filter(
          (p) => !selectedIds.includes(p.id) && p.brand.toLowerCase().includes(search.toLowerCase())
        )
        .slice(0, 10)
    : [];

  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-medium text-muted-foreground">Products</Label>

      {/* Selected products */}
      {selected.length > 0 && (
        <div className="space-y-1">
          {selected.map((p) => (
            <div
              key={p.id}
              className="rounded-lg bg-emerald-50 ring-1 ring-emerald-300 px-3 py-1.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">
                  {productLabel(p.brand, ingredientMap.get(p.id))}
                </span>
                <button
                  type="button"
                  onClick={() => onToggle(p.id)}
                  className="text-muted-foreground/60 hover:text-terra-500 p-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <label className="text-[10px] text-muted-foreground shrink-0">Rate:</label>
                <Input
                  type="number"
                  step="0.1"
                  placeholder="e.g., 1.5"
                  value={rates[p.id] ?? ''}
                  onChange={(e) => onRateChange(p.id, e.target.value)}
                  className="h-6 text-[11px] rounded-md w-20"
                />
                <select
                  value={units[p.id] ?? 'fl oz/gal'}
                  onChange={(e) => onUnitChange(p.id, e.target.value)}
                  className="h-6 text-[10px] rounded-md ring-1 ring-border/60 bg-card px-1 focus:outline-none"
                >
                  {RATE_UNITS.map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Search to add */}
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
            type="button"
            onClick={() => setSearch('')}
            className="absolute right-2.5 top-1/2 -translate-y-1/2"
          >
            <X className="w-3 h-3 text-muted-foreground/60" />
          </button>
        )}
      </div>

      {/* Search results */}
      {searchResults.length > 0 && (
        <div className="max-h-32 overflow-y-auto space-y-0.5 rounded-lg ring-1 ring-border/40 p-1">
          {searchResults.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                onToggle(p.id);
                setSearch('');
              }}
              className="w-full flex items-center gap-2 rounded px-2.5 py-1.5 text-xs text-left hover:bg-emerald-50 transition-colors"
            >
              <Plus className="w-3 h-3 text-emerald-500 shrink-0" />
              <span>{productLabel(p.brand, ingredientMap.get(p.id))}</span>
            </button>
          ))}
        </div>
      )}
      {search && searchResults.length === 0 && (
        <p className="text-[11px] text-muted-foreground/50 text-center py-2">
          No products match &ldquo;{search}&rdquo;
        </p>
      )}
    </div>
  );
}

interface Props {
  products: Product[];
  crops: Crop[];
  cropGroups: CropGroup[];
  ingredientMap: IngredientMap;
}

interface SprayFormState {
  date: string;
  notes: string;
  volumeGallons: string;
  selectedProductIds: number[];
  selectedCropIds: number[];
  rates: Record<number, string>;
  units: Record<number, string>;
}

function emptyForm(): SprayFormState {
  return {
    date: new Date().toISOString().split('T')[0],
    notes: '',
    volumeGallons: '4',
    selectedProductIds: [],
    selectedCropIds: [],
    rates: {},
    units: {},
  };
}

export function AddSprayButton({ products, crops, cropGroups, ingredientMap }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<SprayFormState>(emptyForm());
  const [saving, setSaving] = useState(false);

  async function save() {
    if (form.selectedProductIds.length === 0 || form.selectedCropIds.length === 0) return;
    setSaving(true);
    const supabase = createClient();

    const { data: event } = await supabase
      .from('spray_events')
      .insert({
        date: form.date,
        notes: form.notes || null,
        volume_gallons: form.volumeGallons ? parseFloat(form.volumeGallons) : null,
      })
      .select()
      .single();

    if (event) {
      await Promise.all([
        ...form.selectedProductIds.map((pid) =>
          supabase.from('spray_event_products').insert({
            spray_event_id: event.id,
            product_id: pid,
            rate_applied: form.rates[pid] ? parseFloat(form.rates[pid]) : null,
            rate_unit: form.units[pid] ?? 'fl oz/gal',
          })
        ),
        ...form.selectedCropIds.map((cid) =>
          supabase.from('spray_event_crops').insert({
            spray_event_id: event.id,
            crop_id: cid,
          })
        ),
      ]);
    }

    setSaving(false);
    setOpen(false);
    setForm(emptyForm());
    router.refresh();
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700"
      >
        <Plus className="w-3.5 h-3.5" />
        Log Spray
      </button>

      <FormDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setForm(emptyForm());
        }}
        title="Log Spray Event"
        className="sm:max-w-md"
      >
        <div className="space-y-4 mt-1 max-h-[60vh] overflow-y-auto">
          {/* Date + total mix volume */}
          <div className="flex gap-2">
            <div className="flex-1 space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Date</Label>
              <Input
                type="date"
                value={form.date}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
                className="rounded-lg"
              />
            </div>
            <div className="w-28 space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Volume (gal)</Label>
              <Input
                type="number"
                step="0.25"
                min="0.25"
                value={form.volumeGallons}
                onChange={(e) => setForm({ ...form, volumeGallons: e.target.value })}
                placeholder="4"
                className="rounded-lg tabular-nums"
              />
            </div>
          </div>

          {/* Products — searchable */}
          <SearchableProductPicker
            products={products}
            selectedIds={form.selectedProductIds}
            rates={form.rates}
            units={form.units}
            ingredientMap={ingredientMap}
            onToggle={(pid) =>
              setForm({
                ...form,
                selectedProductIds: form.selectedProductIds.includes(pid)
                  ? form.selectedProductIds.filter((id) => id !== pid)
                  : [...form.selectedProductIds, pid],
              })
            }
            onRateChange={(pid, val) => setForm({ ...form, rates: { ...form.rates, [pid]: val } })}
            onUnitChange={(pid, val) => setForm({ ...form, units: { ...form.units, [pid]: val } })}
          />

          {/* Crops */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">Crops Sprayed</Label>
            <CropChips
              crops={crops}
              cropGroups={cropGroups}
              selectedIds={form.selectedCropIds}
              onToggle={(id) =>
                setForm({
                  ...form,
                  selectedCropIds: form.selectedCropIds.includes(id)
                    ? form.selectedCropIds.filter((x) => x !== id)
                    : [...form.selectedCropIds, id],
                })
              }
            />
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">Notes</Label>
            <Textarea
              placeholder="Optional notes..."
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="text-sm rounded-lg"
            />
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setForm(emptyForm());
            }}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={
              saving || form.selectedProductIds.length === 0 || form.selectedCropIds.length === 0
            }
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Log Spray'}
          </button>
        </DialogFooter>
      </FormDialog>
    </>
  );
}

export function SprayEventActions({
  event,
  eventProducts,
  eventCrops,
  allProducts,
  allCrops,
  cropGroups,
  ingredientMap,
}: {
  event: SprayEvent;
  eventProducts: SprayEventProduct[];
  eventCrops: SprayEventCrop[];
  allProducts: Product[];
  allCrops: Crop[];
  cropGroups: CropGroup[];
  ingredientMap: IngredientMap;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState<SprayFormState>({
    date: event.date,
    notes: event.notes ?? '',
    volumeGallons: (event.volume_gallons ?? 4).toString(),
    selectedProductIds: eventProducts.map((ep) => ep.product_id),
    selectedCropIds: eventCrops.map((ec) => ec.crop_id),
    rates: Object.fromEntries(
      eventProducts
        .filter((ep) => ep.rate_applied != null)
        .map((ep) => [ep.product_id, String(ep.rate_applied)])
    ),
    units: Object.fromEntries(
      eventProducts.map((ep) => [ep.product_id, ep.rate_unit || 'fl oz/gal'])
    ),
  });

  async function saveEdit() {
    setSaving(true);
    const supabase = createClient();

    // Update event
    await supabase
      .from('spray_events')
      .update({
        date: form.date,
        notes: form.notes || null,
        volume_gallons: form.volumeGallons ? parseFloat(form.volumeGallons) : null,
      })
      .eq('id', event.id);

    // Delete old products/crops and re-insert
    await supabase.from('spray_event_products').delete().eq('spray_event_id', event.id);
    await supabase.from('spray_event_crops').delete().eq('spray_event_id', event.id);

    await Promise.all([
      ...form.selectedProductIds.map((pid) =>
        supabase.from('spray_event_products').insert({
          spray_event_id: event.id,
          product_id: pid,
          rate_applied: form.rates[pid] ? parseFloat(form.rates[pid]) : null,
          rate_unit: form.units[pid] ?? 'fl oz/gal',
        })
      ),
      ...form.selectedCropIds.map((cid) =>
        supabase.from('spray_event_crops').insert({
          spray_event_id: event.id,
          crop_id: cid,
        })
      ),
    ]);

    setSaving(false);
    setEditing(false);
    router.refresh();
  }

  async function deleteEvent() {
    setSaving(true);
    const supabase = createClient();
    await supabase.from('spray_events').delete().eq('id', event.id);
    setSaving(false);
    setDeleting(false);
    router.refresh();
  }

  return (
    <>
      {/* Action buttons */}
      <div className="flex gap-1 mt-2 pt-1.5 border-t border-black/[0.04]">
        <button
          onClick={() => setEditing(true)}
          className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-emerald-700 transition-colors px-1.5 py-0.5 rounded"
        >
          <Pencil className="w-3 h-3" />
          Edit
        </button>
        <button
          onClick={() => setDeleting(true)}
          className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-terra-700 transition-colors px-1.5 py-0.5 rounded"
        >
          <Trash2 className="w-3 h-3" />
          Delete
        </button>
      </div>

      {/* Edit dialog */}
      <FormDialog
        open={editing}
        onOpenChange={setEditing}
        title="Edit Spray Event"
        className="sm:max-w-md"
      >
        <div className="space-y-4 mt-1 max-h-[60vh] overflow-y-auto">
          <div className="flex gap-2">
            <div className="flex-1 space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Date</Label>
              <Input
                type="date"
                value={form.date}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
                className="rounded-lg"
              />
            </div>
            <div className="w-28 space-y-1.5">
              <Label className="text-xs font-medium text-muted-foreground">Volume (gal)</Label>
              <Input
                type="number"
                step="0.25"
                min="0.25"
                value={form.volumeGallons}
                onChange={(e) => setForm({ ...form, volumeGallons: e.target.value })}
                placeholder="4"
                className="rounded-lg tabular-nums"
              />
            </div>
          </div>

          <SearchableProductPicker
            products={allProducts}
            selectedIds={form.selectedProductIds}
            rates={form.rates}
            units={form.units}
            ingredientMap={ingredientMap}
            onToggle={(pid) =>
              setForm({
                ...form,
                selectedProductIds: form.selectedProductIds.includes(pid)
                  ? form.selectedProductIds.filter((id) => id !== pid)
                  : [...form.selectedProductIds, pid],
              })
            }
            onRateChange={(pid, val) => setForm({ ...form, rates: { ...form.rates, [pid]: val } })}
            onUnitChange={(pid, val) => setForm({ ...form, units: { ...form.units, [pid]: val } })}
          />

          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">Crops</Label>
            <CropChips
              crops={allCrops}
              cropGroups={cropGroups}
              selectedIds={form.selectedCropIds}
              onToggle={(id) =>
                setForm({
                  ...form,
                  selectedCropIds: form.selectedCropIds.includes(id)
                    ? form.selectedCropIds.filter((x) => x !== id)
                    : [...form.selectedCropIds, id],
                })
              }
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-muted-foreground">Notes</Label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="text-sm rounded-lg"
            />
          </div>
        </div>

        <DialogFooter>
          <button
            onClick={() => setEditing(false)}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={saveEdit}
            disabled={saving}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </DialogFooter>
      </FormDialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Delete Spray Event?"
        description="This will permanently remove this spray event and all associated product and crop records. This cannot be undone."
        onConfirm={deleteEvent}
        loading={saving}
      />
    </>
  );
}
