'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { Harvest, Variety, Crop, CropGroup, Database } from '@/lib/database.types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DialogFooter } from '@/components/ui/dialog';
import { FormDialog, ConfirmDialog } from '@/components/ui/form-dialog';
import Link from 'next/link';
import { createClient } from '@/lib/db/client';
import { CropAvatar } from '@/components/crop-glyph';
import { HarvestCharts } from '@/components/harvest-charts';
import { cropsByCategory } from '@/lib/crop-category';
import { Plus, Trash2, Scale, Info, AlertTriangle } from 'lucide-react';

const UNITS = ['lb', 'oz', 'kg', 'g', 'ct'];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/* ── helpers ── */
function fmtAmount(w: number, unit: string) {
  const n = Math.round(Number(w) * 1000) / 1000; // trim float noise
  return `${n} ${unit}`;
}
function fmtMoney(n: number) {
  return '$' + n.toFixed(2);
}
/** Today's date in the *local* calendar (not UTC) — avoids logging "tomorrow" in the evening. */
function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function dateInputValue(iso: string) {
  // UTC-based so server (UTC) and client (local) produce the same string — avoids
  // hydration mismatches on dates stored at arbitrary times.
  return new Date(iso).toISOString().slice(0, 10);
}
function isoFromDate(dateStr: string) {
  // store at UTC noon so the calendar day is stable everywhere
  return new Date(`${dateStr}T12:00:00Z`).toISOString();
}
function toLb(weight: number, unit: string): number {
  switch (unit) {
    case 'oz':
      return weight / 16;
    case 'kg':
      return weight * 2.20462;
    case 'g':
      return weight / 453.592;
    case 'ct':
      return 0; // counts aren't a weight — valued via the crop's avg weight each
    default:
      return weight;
  }
}

/* A number input that only commits on blur / Enter. */
function NumberCell({ value, onCommit }: { value: number; onCommit: (v: number) => void }) {
  const [local, setLocal] = useState(String(value));
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    setLocal(String(value));
  }
  return (
    <input
      type="text"
      inputMode="decimal"
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => {
        const n = parseFloat(local);
        if (!isNaN(n) && n >= 0 && n !== value) onCommit(n);
        else if (isNaN(n)) setLocal(String(value));
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
      }}
      className="w-14 h-7 text-right text-sm tabular-nums rounded-md ring-1 ring-border/60 bg-card px-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
    />
  );
}

interface Props {
  harvests: Harvest[];
  varieties: Variety[];
  crops: Crop[];
  cropGroups: CropGroup[];
  sprayCost: number;
  /** Per-crop sprays carrying a PHI for that crop's group — to warn on early harvest. */
  phiSprays: Record<number, { date: string; phiDays: number; brand: string }[]>;
}

export function HarvestTracker({
  harvests,
  varieties,
  crops,
  cropGroups,
  sprayCost,
  phiSprays,
}: Props) {
  const router = useRouter();
  const [logOpen, setLogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; label: string } | null>(null);

  // Optimistic copy of the server data so totals update instantly on edit.
  const [rows, setRows] = useState<Harvest[]>(harvests);
  const [prevHarvests, setPrevHarvests] = useState(harvests);
  if (harvests !== prevHarvests) {
    setPrevHarvests(harvests);
    setRows(harvests);
  } // reconcile after refresh

  /* log-form state */
  const [selectedCropId, setSelectedCropId] = useState<number | ''>('');
  const [selectedVarietyId, setSelectedVarietyId] = useState<number | ''>('');
  const [weight, setWeight] = useState('');
  const [unit, setUnit] = useState('lb');
  const [harvestedOn, setHarvestedOn] = useState('');
  const [notes, setNotes] = useState('');

  /* lookups */
  const varietyMap = useMemo(() => new Map(varieties.map((v) => [v.id, v])), [varieties]);
  const cropMap = useMemo(() => new Map(crops.map((c) => [c.id, c])), [crops]);
  const cropGroupName = useMemo(() => new Map(cropGroups.map((g) => [g.id, g.name])), [cropGroups]);
  const groupNameFor = (c: Crop | undefined) =>
    c?.crop_group_id ? (cropGroupName.get(c.crop_group_id) ?? null) : null;
  const cropForHarvest = (h: Harvest): Crop | undefined => {
    if (h.crop_id) return cropMap.get(h.crop_id);
    if (h.variety_id) {
      const v = varietyMap.get(h.variety_id);
      if (v) return cropMap.get(v.crop_id);
    }
    return undefined;
  };

  const filteredVarieties = useMemo(
    () => (selectedCropId === '' ? [] : varieties.filter((v) => v.crop_id === selectedCropId)),
    [varieties, selectedCropId]
  );

  const cropCategories = useMemo(() => cropsByCategory(crops, cropGroups), [crops, cropGroups]);

  /* newest first for the picks table */
  const sortedRows = useMemo(
    () =>
      [...rows].sort((a, b) =>
        a.harvested_at < b.harvested_at ? 1 : a.harvested_at > b.harvested_at ? -1 : b.id - a.id
      ),
    [rows]
  );

  /* ── season summary, grouped by crop. Counts (ct) are converted to pounds via
        the crop's avg weight-each and folded into the lb total — everything is lb. ── */
  const byCrop = useMemo(() => {
    type VarietySlice = { id: number; name: string; picks: number; totalLb: number; value: number };
    const m = new Map<
      number,
      {
        crop: Crop;
        picks: number;
        totalLb: number;
        value: number;
        varieties: Map<number, VarietySlice>;
      }
    >();
    for (const h of rows) {
      let crop: Crop | undefined;
      const variety = h.variety_id ? varietyMap.get(h.variety_id) : undefined;
      if (h.crop_id) crop = cropMap.get(h.crop_id);
      else if (variety) crop = cropMap.get(variety.crop_id);
      if (!crop) continue;
      if (!m.has(crop.id))
        m.set(crop.id, { crop, picks: 0, totalLb: 0, value: 0, varieties: new Map() });
      const e = m.get(crop.id)!;
      e.picks += 1;
      const price = Number(crop.price_market_per_lb) || 0;
      const lb =
        h.unit === 'ct'
          ? Number(h.weight) * (Number(crop.avg_lb_per_count) || 0)
          : toLb(Number(h.weight), h.unit);
      e.totalLb += lb;
      e.value += lb * price;
      // A pick tagged with a variety also feeds that variety's slice of the
      // crop, priced identically so the slices always sum to the crop total.
      if (variety) {
        if (!e.varieties.has(variety.id))
          e.varieties.set(variety.id, {
            id: variety.id,
            name: variety.name,
            picks: 0,
            totalLb: 0,
            value: 0,
          });
        const v = e.varieties.get(variety.id)!;
        v.picks += 1;
        v.totalLb += lb;
        v.value += lb * price;
      }
    }
    return [...m.values()]
      .map(({ varieties, ...c }) => ({
        ...c,
        varieties: [...varieties.values()].sort((a, b) => b.totalLb - a.totalLb),
      }))
      .sort((a, b) => b.totalLb - a.totalLb);
  }, [rows, varietyMap, cropMap]);

  /* per-harvest priced events for the charts (value + lb per pick, tagged with
     the crop so the cumulative chart can break down by crop, and with the
     variety so a crop's row can break down further). */
  const events = useMemo(
    () =>
      rows.map((h) => {
        let crop: Crop | undefined;
        const variety = h.variety_id ? varietyMap.get(h.variety_id) : undefined;
        if (h.crop_id) crop = cropMap.get(h.crop_id);
        else if (variety) crop = cropMap.get(variety.crop_id);
        const price = Number(crop?.price_market_per_lb) || 0;
        const date = dateInputValue(h.harvested_at);
        const cropId = crop?.id ?? null;
        const varietyId = variety?.id ?? null;
        if (h.unit === 'ct') {
          const lb = Number(h.weight) * (Number(crop?.avg_lb_per_count) || 0);
          return { date, value: lb * price, lb, cropId, varietyId };
        }
        const lb = toLb(Number(h.weight), h.unit);
        return { date, value: lb * price, lb, cropId, varietyId };
      }),
    [rows, cropMap, varietyMap]
  );

  const grandTotalLb = byCrop.reduce((s, d) => s + d.totalLb, 0);
  const grandValue = byCrop.reduce((s, d) => s + d.value, 0);
  const anyValue = grandValue > 0;

  /** $ value of a single harvest row (weight × $/lb, or count × avg-lb × $/lb). */
  function harvestValue(h: Harvest): number {
    const crop = cropForHarvest(h);
    if (!crop) return 0;
    const price = Number(crop.price_market_per_lb) || 0;
    const lb =
      h.unit === 'ct'
        ? Number(h.weight) * (Number(crop.avg_lb_per_count) || 0)
        : toLb(Number(h.weight), h.unit);
    return lb * price;
  }

  /** If this crop was sprayed within a product's pre-harvest interval before this
   *  harvest date, return the worst (longest-remaining) violation. */
  function phiViolation(
    cropId: number | undefined,
    harvestedAt: string
  ): { brand: string; daysShort: number; safe: string } | null {
    if (cropId == null) return null;
    const sprays = phiSprays[cropId];
    if (!sprays || sprays.length === 0) return null;
    const hDay = Date.parse(harvestedAt.slice(0, 10) + 'T12:00:00Z');
    if (isNaN(hDay)) return null;
    let worst: { brand: string; daysShort: number; safe: string } | null = null;
    for (const s of sprays) {
      const sDay = Date.parse(s.date.slice(0, 10) + 'T12:00:00Z');
      if (isNaN(sDay) || sDay > hDay) continue; // sprayed after the harvest — irrelevant
      const elapsed = Math.round((hDay - sDay) / 86400000);
      if (elapsed < s.phiDays) {
        const daysShort = s.phiDays - elapsed;
        const safe = new Date(sDay + s.phiDays * 86400000).toISOString().slice(0, 10);
        if (!worst || daysShort > worst.daysShort) worst = { brand: s.brand, daysShort, safe };
      }
    }
    return worst;
  }

  /* ── handlers (optimistic, with error surfacing) ── */
  function openLogDialog() {
    setHarvestedOn(todayLocal());
    setSelectedCropId('');
    setSelectedVarietyId('');
    setWeight('');
    setUnit('lb');
    setNotes('');
    setLogOpen(true);
  }

  async function submitHarvest() {
    if (!selectedCropId || !weight || saving) return;
    const insert = {
      crop_id: selectedCropId as number,
      variety_id: selectedVarietyId === '' ? null : (selectedVarietyId as number),
      weight: parseFloat(weight),
      unit,
      harvested_at: isoFromDate(harvestedOn),
      notes: notes.trim() || null,
    };
    // optimistic add with a temporary id
    const optimistic: Harvest = {
      id: -Date.now(),
      created_at: new Date().toISOString(),
      ...insert,
    };
    setRows((r) => [optimistic, ...r]);
    setSaving(true);
    setLogOpen(false);
    const { error } = await createClient().from('harvests').insert(insert);
    setSaving(false);
    if (error) {
      console.error(error);
      window.alert(`Couldn't save harvest: ${error.message}`);
      setRows(harvests);
    }
    router.refresh();
  }

  async function patchHarvest(
    id: number,
    patch: Database['public']['Tables']['harvests']['Update']
  ) {
    setRows((r) => r.map((h) => (h.id === id ? ({ ...h, ...patch } as Harvest) : h))); // optimistic
    const { error } = await createClient().from('harvests').update(patch).eq('id', id);
    if (error) {
      console.error(error);
      window.alert(`Couldn't update: ${error.message}`);
      setRows(harvests);
    }
    router.refresh();
  }

  async function deleteHarvest(id: number) {
    setRows((r) => r.filter((h) => h.id !== id)); // optimistic
    setDeleteConfirm(null);
    const { error } = await createClient().from('harvests').delete().eq('id', id);
    if (error) {
      console.error(error);
      window.alert(`Couldn't delete: ${error.message}`);
      setRows(harvests);
    }
    router.refresh();
  }

  return (
    <div className="space-y-6">
      {/* ── Season total ── */}
      {(() => {
        const net = grandValue - sprayCost;
        const yieldStr = `${grandTotalLb > 0 ? (grandTotalLb % 1 === 0 ? grandTotalLb : grandTotalLb.toFixed(1)) : 0} lb`;
        const stats: { label: string; value: string; cls: string; title?: string }[] = [
          { label: 'Yield', value: yieldStr, cls: 'text-foreground' },
        ];
        if (anyValue)
          stats.push({ label: 'Value', value: fmtMoney(grandValue), cls: 'text-emerald-700' });
        if (sprayCost > 0)
          stats.push({
            label: 'Spray cost',
            value: fmtMoney(sprayCost),
            cls: 'text-terra-600',
            title:
              'Cost of the products you sprayed this season (applied amounts, valued from inventory pricing).',
          });
        if (anyValue && sprayCost > 0)
          stats.push({
            label: 'Net',
            value: net >= 0 ? fmtMoney(net) : `−${fmtMoney(-net)}`,
            cls: net >= 0 ? 'text-emerald-700' : 'text-terra-600',
            title: 'Harvest value minus spray cost.',
          });
        const colsClass =
          stats.length >= 4
            ? 'sm:grid-cols-4'
            : stats.length === 3
              ? 'sm:grid-cols-3'
              : 'sm:grid-cols-2';
        return (
          <div className="rounded-2xl bg-card ring-1 ring-black/[0.05] shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/40">
              <p className="text-[11px] font-medium tracking-widest uppercase text-muted-foreground/60">
                Season total
              </p>
              <span className="text-[11px] text-muted-foreground/60 tabular-nums">
                {byCrop.length} {byCrop.length === 1 ? 'crop' : 'crops'} · {rows.length}{' '}
                {rows.length === 1 ? 'pick' : 'picks'}
              </span>
            </div>
            <div className={`grid grid-cols-2 ${colsClass} gap-px bg-border/30`}>
              {stats.map((s) => (
                <div key={s.label} className="bg-card px-4 py-3" title={s.title}>
                  <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/55 mb-1">
                    {s.label}
                  </p>
                  <p
                    className={`text-2xl font-heading font-semibold tracking-tight tabular-nums ${s.cls}`}
                  >
                    {s.value}
                  </p>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* where to set prices */}
      <Link
        href="/crops"
        className="flex items-center gap-1.5 text-[11px] text-muted-foreground/70 -mt-3 px-1 hover:text-emerald-700 transition-colors"
      >
        <Info className="w-3 h-3 shrink-0" />
        <span>
          Value uses the $/lb set on each crop (plus an avg weight for counts) — tap to edit on the{' '}
          <span className="underline">Crops page</span>.
        </span>
      </Link>

      <HarvestCharts byCrop={byCrop} events={events} />

      {/* ── Recent picks (editable table) ── */}
      <section>
        <div className="flex items-baseline justify-between mb-2">
          <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
            Picks log
          </p>
          <span className="text-[10px] text-muted-foreground/50">{rows.length}</span>
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl bg-card shadow-sm ring-1 ring-black/[0.05] px-6 py-12 text-center">
            <Scale className="w-8 h-8 text-muted-foreground/20 mx-auto mb-3" />
            <p className="font-heading font-semibold text-foreground mb-1">No harvests yet</p>
            <p className="text-sm text-muted-foreground">
              Tap &ldquo;Log Harvest&rdquo; to record your first pick.
            </p>
          </div>
        ) : (
          <div className="rounded-xl bg-card ring-1 ring-black/[0.05] overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[10px] font-medium tracking-widest uppercase text-muted-foreground/60 border-b border-border/50">
                    <th className="px-3 py-2 font-medium">Crop</th>
                    <th className="px-2 py-2 font-medium">Date</th>
                    <th className="px-2 py-2 font-medium text-right">Amount</th>
                    <th className="px-2 py-2 font-medium text-right">Value</th>
                    <th className="px-2 py-2 font-medium w-8"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {sortedRows.map((h) => {
                    const c = cropForHarvest(h);
                    const v = h.variety_id ? varietyMap.get(h.variety_id) : null;
                    const val = harvestValue(h);
                    const phi = phiViolation(c?.id, h.harvested_at);
                    return (
                      <tr key={h.id} className="hover:bg-muted/20">
                        <td className="px-3 py-1.5 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <CropAvatar
                              name={c?.name ?? ''}
                              group={groupNameFor(c)}
                              size={24}
                              className="shrink-0"
                            />
                            <span className="font-medium">{c?.name ?? 'Unknown'}</span>
                            {v && <span className="text-muted-foreground/60">({v.name})</span>}
                            {phi && (
                              <span
                                title={`PHI not met — ${phi.brand} sprayed too recently; safe to harvest ${phi.safe} (${phi.daysShort}d short)`}
                                className="inline-flex items-center text-terra-600 shrink-0"
                              >
                                <AlertTriangle className="w-3.5 h-3.5" />
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            type="date"
                            value={dateInputValue(h.harvested_at)}
                            onChange={(e) => {
                              const val = e.target.value;
                              if (DATE_RE.test(val)) {
                                const yr = Number(val.slice(0, 4));
                                if (yr >= 2000 && yr <= 2100)
                                  patchHarvest(h.id, { harvested_at: isoFromDate(val) });
                              }
                            }}
                            className="h-7 text-xs rounded-md ring-1 ring-border/50 bg-card px-1.5 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center justify-end gap-1">
                            <NumberCell
                              value={Number(h.weight)}
                              onCommit={(n) => patchHarvest(h.id, { weight: n })}
                            />
                            <select
                              value={h.unit}
                              onChange={(e) => patchHarvest(h.id, { unit: e.target.value })}
                              className="h-7 text-xs rounded-md ring-1 ring-border/50 bg-card pl-1 pr-0.5 focus:outline-none"
                            >
                              {UNITS.map((u) => (
                                <option key={u} value={u}>
                                  {u}
                                </option>
                              ))}
                            </select>
                          </div>
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums whitespace-nowrap">
                          {val > 0 ? (
                            <span className="font-medium text-emerald-700">{fmtMoney(val)}</span>
                          ) : (
                            <span className="text-muted-foreground/40">—</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <button
                            onClick={() =>
                              setDeleteConfirm({
                                id: h.id,
                                label: `${c?.name ?? 'harvest'} (${fmtAmount(Number(h.weight), h.unit)})`,
                              })
                            }
                            className="text-muted-foreground/40 hover:text-terra-500 transition-colors p-1"
                            title="Delete"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[10px] text-muted-foreground/50 px-3 py-1.5 border-t border-border/40">
              Tap any date, amount, or unit to edit inline.
            </p>
          </div>
        )}
      </section>

      {/* ── Log Harvest FAB ── */}
      <button
        onClick={openLogDialog}
        className="fixed bottom-20 right-4 z-40 flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-600/25 transition-all hover:bg-emerald-700 active:scale-95"
      >
        <Plus className="w-4 h-4" />
        Log Harvest
      </button>

      {/* ── Log Harvest Dialog ── */}
      <FormDialog open={logOpen} onOpenChange={setLogOpen} title="Log Harvest">
        <div className="space-y-4 mt-1">
          <div className="space-y-1.5">
            <Label htmlFor="h-crop" className="text-xs font-medium text-muted-foreground">
              Crop
            </Label>
            <select
              id="h-crop"
              value={selectedCropId}
              onChange={(e) => {
                setSelectedCropId(e.target.value ? Number(e.target.value) : '');
                setSelectedVarietyId('');
              }}
              className="w-full rounded-lg border px-3 py-2 text-sm bg-background ring-1 ring-black/[0.04]"
              required
            >
              <option value="">Select a crop</option>
              {cropCategories.map((g) => (
                <optgroup key={g.category} label={g.category}>
                  {g.crops.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="h-variety" className="text-xs font-medium text-muted-foreground">
              Variety <span className="text-muted-foreground/40">(optional)</span>
            </Label>
            <select
              id="h-variety"
              value={selectedVarietyId}
              onChange={(e) => setSelectedVarietyId(e.target.value ? Number(e.target.value) : '')}
              disabled={selectedCropId === ''}
              className="w-full rounded-lg border px-3 py-2 text-sm bg-background ring-1 ring-black/[0.04] disabled:opacity-50"
            >
              <option value=""></option>
              {filteredVarieties.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-3">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="h-weight" className="text-xs font-medium text-muted-foreground">
                Amount
              </Label>
              <Input
                id="h-weight"
                type="number"
                step="0.1"
                min="0"
                placeholder="0.0"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                className="rounded-lg"
                required
              />
            </div>
            <div className="w-24 space-y-1.5">
              <Label htmlFor="h-unit" className="text-xs font-medium text-muted-foreground">
                Unit
              </Label>
              <select
                id="h-unit"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm bg-background ring-1 ring-black/[0.04]"
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="h-date" className="text-xs font-medium text-muted-foreground">
              Date
            </Label>
            <Input
              id="h-date"
              type="date"
              value={harvestedOn}
              onChange={(e) => setHarvestedOn(e.target.value)}
              className="rounded-lg"
            />
          </div>

          {(() => {
            const lp =
              selectedCropId !== '' && harvestedOn
                ? phiViolation(selectedCropId as number, isoFromDate(harvestedOn))
                : null;
            return lp ? (
              <div className="flex items-start gap-1.5 rounded-lg bg-terra-50 ring-1 ring-terra-200/60 px-3 py-2 text-[11px] text-terra-700">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>
                  <span className="font-semibold">Pre-harvest interval not met.</span> {lp.brand}{' '}
                  was applied within its PHI — safe to harvest on{' '}
                  <span className="font-medium">{lp.safe}</span> ({lp.daysShort} day
                  {lp.daysShort !== 1 ? 's' : ''} short). Harvesting now may leave residue above the
                  label limit.
                </span>
              </div>
            ) : null;
          })()}

          <div className="space-y-1.5">
            <Label htmlFor="h-notes" className="text-xs font-medium text-muted-foreground">
              Notes <span className="text-muted-foreground/40">(optional)</span>
            </Label>
            <Input
              id="h-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="rounded-lg"
            />
          </div>
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => setLogOpen(false)}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submitHarvest}
            disabled={saving || !selectedCropId || !weight}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Log Harvest'}
          </button>
        </DialogFooter>
      </FormDialog>

      {/* ── Delete Confirmation ── */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={() => setDeleteConfirm(null)}
        title="Delete harvest?"
        description={`Remove ${deleteConfirm?.label}? This cannot be undone.`}
        onConfirm={() => deleteConfirm && deleteHarvest(deleteConfirm.id)}
        loading={saving}
      />
    </div>
  );
}
