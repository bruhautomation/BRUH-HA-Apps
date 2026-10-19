'use client';

import { useState, useMemo, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useToast } from '@/components/ui/toast';
import { createClient } from '@/lib/db/client';
import {
  analyzeCropNeeds,
  generateMixPlans,
  getAlternatives,
  type MixPlan,
  type MixProduct,
} from '@/lib/mix-planner';
import { evaluateInterlocks } from '@/lib/interlocks';
import { calculateDose } from '@/lib/dose';
import { doseCost } from '@/lib/spray-cost';
import { useSprayerGallons } from '@/lib/use-sprayer-gallons';
import { productLabel } from '@/lib/product-label';
import { cropPillStyle, colorsForCrop } from '@/lib/crop-colors';
import { cropsByCategory } from '@/lib/crop-category';
import { AREA_STYLE } from '@/lib/area-meta';
import { SprayWindowTimeline } from '@/components/spray-window-timeline';
import { COVERAGE_DEFAULTS } from '@/config/thresholds';
import { urgencyConfig, roleDot } from '@/lib/theme';
import { useSprayMutations } from './use-spray-mutations';
import { QueuedEditPanel } from './queued-edit-panel';
import { SprayTimingPanel } from './spray-timing-panel';
import type { SprayPlannerProps } from './types';
import {
  Shield,
  AlertTriangle,
  Flower2,
  ChevronDown,
  Check,
  ArrowRight,
  X,
  CloudRain,
  Crosshair,
  Trash2,
} from 'lucide-react';
import { withBase } from '@/lib/base-path';

export type { SprayPlannerProps } from './types';

export function SprayPlanner(props: SprayPlannerProps) {
  const [sprayerGallons] = useSprayerGallons();
  const { logging, queueSpray, logMix, saveQueuedEdit, removeQueuedSpray, logQueuedSpray } =
    useSprayMutations(props.inventoryData, sprayerGallons);

  // ── State ──
  const [selectedCropIds, setSelectedCropIds] = useState<number[]>(props.initialCropIds ?? []);
  const [overrides, setOverrides] = useState<Map<string, number>>(new Map());
  const [swapping, setSwapping] = useState<{
    planId: string;
    mixProduct: MixProduct;
    groupIds: number[];
  } | null>(null);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [loggedMixes, setLoggedMixes] = useState<string[]>([]);
  const [expandedMix, setExpandedMix] = useState<string | null>(null);
  const [dismissedMixes, setDismissedMixes] = useState<string[]>([]);
  const [removedProducts, setRemovedProducts] = useState<string[]>([]);
  const [queuedMixId, setQueuedMixId] = useState<string | null>(null);
  const [editingQueued, setEditingQueued] = useState<number | null>(null);
  const [inventoryEditProductId, setInventoryEditProductId] = useState<number | null>(null);
  const [planAhead, setPlanAhead] = useState(false);
  const [editProducts, setEditProducts] = useState<number[]>([]);
  const [editRates, setEditRates] = useState<Record<number, number>>({});
  const [editNotes, setEditNotes] = useState('');
  const [groupInfo, setGroupInfo] = useState<{
    scheme: 'FRAC' | 'IRAC';
    group: string;
    productBrand: string;
    modeOfAction: string | null;
  } | null>(null);

  // ── Memoized data ──
  const ingMap = useMemo(
    () => new Map(Object.entries(props.ingredientMap).map(([k, v]) => [Number(k), v])),
    [props.ingredientMap]
  );

  const plannerData = useMemo(
    () => ({
      crops: props.crops,
      products: props.products,
      cropGroups: props.cropGroups,
      cropUses: props.cropUses,
      tankMixRules: props.tankMixRules,
      ingredientMap: ingMap,
      sprayEvents: props.sprayEvents,
      sprayEventProducts: props.sprayEventProducts,
      sprayEventCrops: props.sprayEventCrops,
      precipHistory: props.precipHistory,
      inventoryProductIds: planAhead ? undefined : props.inventoryProductIds,
      varietyStages: props.varietyStages.map((vs) => ({
        variety_id: vs.variety_id,
        stage: vs.stage,
      })),
      varieties: props.varieties.map((v) => ({ id: v.id, crop_id: v.crop_id, name: v.name })),
    }),
    [props, ingMap, planAhead]
  );

  // ── Derived data ──
  const cropNeeds = useMemo(
    () => (selectedCropIds.length > 0 ? analyzeCropNeeds(selectedCropIds, plannerData) : []),
    [selectedCropIds, plannerData]
  );

  const mixPlans = useMemo(() => {
    if (cropNeeds.length === 0) return [];
    const needs = planAhead ? cropNeeds.map((cn) => ({ ...cn, needsFungicide: true })) : cropNeeds;
    return generateMixPlans(needs, plannerData, overrides);
  }, [cropNeeds, plannerData, overrides, planAhead]);

  const effectiveExpanded = expandedMix ?? mixPlans[0]?.id ?? null;
  const showMixes = selectedCropIds.length > 0;

  // When crops are handed off from the Today dashboard, scroll the
  // recommendations into view so the user lands on the actionable part
  // rather than re-confirming the crop picker.
  const mixSectionRef = useRef<HTMLDivElement | null>(null);
  const didHandoffScroll = useRef(false);
  useEffect(() => {
    if (didHandoffScroll.current) return;
    if ((props.initialCropIds?.length ?? 0) === 0 || mixPlans.length === 0) return;
    didHandoffScroll.current = true;
    mixSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [props.initialCropIds, mixPlans.length]);

  // ── Handlers ──
  function toggleCrop(id: number) {
    setSelectedCropIds((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
    setOverrides(new Map());
    setLoggedMixes([]);
    setDismissedMixes([]);
    setRemovedProducts([]);
    setPlanAhead(false);
  }

  function selectAll() {
    setSelectedCropIds(props.crops.map((c) => c.id));
    setOverrides(new Map());
  }

  function substituteProduct(groupIds: number[], role: MixProduct['role'], newProductId: number) {
    const next = new Map(overrides);
    for (const gid of groupIds) {
      next.set(`${gid}-${role}`, newProductId);
    }
    setOverrides(next);
    setSwapping(null);
  }

  async function handleQueueSpray(plan: MixPlan) {
    await queueSpray(plan, rates, notes);
    setQueuedMixId(plan.id);
  }

  async function handleLogMix(plan: MixPlan, volumeGallons?: number) {
    await logMix(plan, rates, notes, volumeGallons);
    setLoggedMixes((prev) => [...prev, plan.id]);
    setQueuedMixId(null);
  }

  function getInterlocks(plan: MixPlan) {
    return evaluateInterlocks({
      selectedProducts: plan.products.map((p) => p.product),
      selectedCropIds: plan.crops.map((c) => c.id),
      crops: props.crops,
      cropGroups: props.cropGroups,
      varieties: props.varieties,
      varietyStages: props.varietyStages,
      productIngredientMap: ingMap,
      tankMixRules: props.tankMixRules,
      sprayEvents: props.sprayEvents,
      sprayEventProducts: props.sprayEventProducts,
      sprayEventCrops: props.sprayEventCrops,
      allProducts: props.products,
      currentTemp: null,
      forecastHighTemp: null,
      windSpeed: null,
      hoursUntilRain: null,
      now: new Date(),
    });
  }

  // ── Queued spray cards ──
  const queuedSprayCards = props.queuedSprays.map((qs) => {
    const qProds = props.queuedSprayProducts
      .filter((qp) => qp.queued_spray_id === qs.id)
      .map((qp) => ({ ...qp, product: props.products.find((p) => p.id === qp.product_id) }))
      .filter((qp) => qp.product);
    const qCrops = props.queuedSprayCrops
      .filter((qc) => qc.queued_spray_id === qs.id)
      .map((qc) => ({ ...qc, crop: props.crops.find((c) => c.id === qc.crop_id) }))
      .filter((qc) => qc.crop);
    return { ...qs, products: qProds, crops: qCrops };
  });

  function startEditQueued(qs: (typeof queuedSprayCards)[0]) {
    setEditingQueued(qs.id);
    setEditProducts(qs.products.map((p) => p.product_id));
    setEditRates(
      Object.fromEntries(
        qs.products.filter((p) => p.rate_applied).map((p) => [p.product_id, p.rate_applied!])
      )
    );
    setEditNotes(qs.notes || '');
    setExpandedMix(`queued-${qs.id}`);
  }

  // ── Render ──
  return (
    <div className="space-y-6">
      {/* ── Queued Sprays ── */}
      {queuedSprayCards.length > 0 && (
        <section>
          <h2 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70 mb-3">
            Queued Sprays
          </h2>
          <div className="space-y-2">
            {queuedSprayCards.map((qs) => {
              const isExpQ = expandedMix === `queued-${qs.id}`;
              const maxRainFast = Math.max(
                ...qs.products.map(
                  (p) => p.product?.rain_fastness_hours ?? COVERAGE_DEFAULTS.rainFastnessHours
                )
              );
              let hUntilRain: number | null = null;
              for (let i = 0; i < props.weatherHourly.length; i++) {
                if (props.weatherHourly[i].precipitation > 0.01) {
                  hUntilRain = i;
                  break;
                }
              }
              const rainOk = hUntilRain === null || hUntilRain >= maxRainFast;

              const coverages = qs.products
                .filter((p) => p.product?.cover_spray_interval_days)
                .map((p) => ({
                  brand: p.product!.brand,
                  days: p.product!.cover_spray_interval_days!,
                }));

              return (
                <div
                  key={qs.id}
                  className="rounded-xl bg-leaf-tint ring-1 ring-leaf-lt shadow-sm overflow-hidden"
                >
                  <button
                    onClick={() => setExpandedMix(isExpQ ? null : `queued-${qs.id}`)}
                    className="w-full flex items-center gap-3 px-3.5 py-3 text-left hover:bg-emerald-50/40 transition-colors"
                  >
                    <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-emerald-100 ring-1 ring-emerald-200/50 shrink-0">
                      <Crosshair className="w-3.5 h-3.5 text-emerald-700" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-emerald-800">
                        {qs.crops.map((qc) => qc.crop!.name).join(', ')}
                      </p>
                      <p className="text-[10px] text-emerald-600/70 truncate">
                        {qs.products.map((qp) => qp.product!.brand).join(' + ')}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {!rainOk && <CloudRain className="w-3.5 h-3.5 text-amber-500" />}
                      <ChevronDown
                        className={`w-4 h-4 text-emerald-500/50 transition-transform ${isExpQ ? 'rotate-180' : ''}`}
                      />
                    </div>
                  </button>

                  {isExpQ && editingQueued === qs.id && (
                    <QueuedEditPanel
                      allProducts={props.products}
                      selectedProducts={editProducts}
                      rates={editRates}
                      notes={editNotes}
                      ingredientMap={ingMap}
                      onToggleProduct={(pid) =>
                        setEditProducts(
                          editProducts.includes(pid)
                            ? editProducts.filter((p) => p !== pid)
                            : [...editProducts, pid]
                        )
                      }
                      onRateChange={(pid, rate) => setEditRates({ ...editRates, [pid]: rate })}
                      onNotesChange={setEditNotes}
                      onSave={() => saveQueuedEdit(qs.id, editProducts, editRates, editNotes)}
                      onCancel={() => setEditingQueued(null)}
                      saving={logging === `edit-${qs.id}`}
                    />
                  )}
                  {isExpQ && editingQueued !== qs.id && (
                    <div className="border-t border-emerald-200/30 px-3.5 py-3.5 space-y-3">
                      <div className="flex flex-wrap gap-1.5">
                        {qs.products.map((qp) => (
                          <span
                            key={qp.product_id}
                            className="rounded-full text-[11px] font-medium px-2 py-0.5 bg-leaf-tint text-leaf-dk ring-1 ring-leaf-lt"
                          >
                            {productLabel(qp.product!.brand, ingMap.get(qp.product_id))}
                            {qp.rate_applied ? ` ${qp.rate_applied} ${qp.rate_unit}` : ''}
                          </span>
                        ))}
                      </div>

                      {props.weatherHourly.length > 0 && (
                        <div className="rounded-lg bg-card/60 p-2.5 ring-1 ring-leaf-lt">
                          <p className="text-[10px] font-medium tracking-widest uppercase text-emerald-600/60 mb-2">
                            Spray Windows
                          </p>
                          <SprayWindowTimeline hourly={props.weatherHourly} compact />
                        </div>
                      )}

                      <div
                        className={`rounded-lg px-3 py-2 ring-1 text-[11px] ${rainOk ? 'bg-emerald-50/60 ring-emerald-200/40 text-emerald-700' : 'bg-amber-50 ring-amber-200/50 text-amber-700'}`}
                      >
                        <span className="font-semibold">Rain-fast:</span> Need {maxRainFast}h.
                        {hUntilRain !== null
                          ? ` Rain in ~${hUntilRain}h. ${rainOk ? 'OK.' : 'Tight — time carefully.'}`
                          : ' No rain forecast.'}
                      </div>

                      {coverages.length > 0 && (
                        <div className="text-[11px] text-emerald-700">
                          <span className="font-semibold">Coverage:</span>{' '}
                          {coverages.map((c) => `${c.brand} ${c.days}d`).join(', ')}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <button
                          onClick={() =>
                            removeQueuedSpray({
                              id: qs.id,
                              notes: qs.notes,
                              products: qs.products.map((p) => ({
                                product_id: p.product_id,
                                rate_applied: p.rate_applied,
                                rate_unit: p.rate_unit,
                              })),
                              crops: qs.crops.map((c) => ({ crop_id: c.crop_id })),
                            })
                          }
                          disabled={logging === `remove-${qs.id}`}
                          aria-label="Remove queued spray"
                          className="rounded-lg py-2 px-3 text-xs font-medium text-terra-600 ring-1 ring-terra-200 hover:bg-terra-50 disabled:opacity-50 transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => startEditQueued(qs)}
                          className="flex-1 rounded-lg py-2 text-xs font-medium text-emerald-700 ring-1 ring-emerald-300 hover:bg-emerald-50 transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => logQueuedSpray(qs)}
                          disabled={logging === `queued-${qs.id}`}
                          className="flex-[2] bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 rounded-lg py-2 text-xs font-medium transition-colors"
                        >
                          {logging === `queued-${qs.id}` ? 'Logging...' : 'Log Spray'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Step 1: Select Crops ── */}
      <section>
        {selectedCropIds.length === 0 && (
          <p className="text-sm text-muted-foreground mb-3">
            Select the crops you want to spray to see recommended products and mixes.
            {props.inventoryProductIds.length === 0 && (
              <span className="block mt-1 text-amber-700 font-medium">
                No products in inventory.{' '}
                <a href={withBase('/inventory')} className="underline">
                  Add products to your stock
                </a>{' '}
                to get recommendations.
              </span>
            )}
          </p>
        )}
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
            Select Crops
          </h2>
          {selectedCropIds.length < props.crops.length && (
            <button
              onClick={selectAll}
              className="text-xs text-emerald-600 font-medium hover:text-emerald-700"
            >
              Select all
            </button>
          )}
          {selectedCropIds.length > 0 && selectedCropIds.length === props.crops.length && (
            <button
              onClick={() => setSelectedCropIds([])}
              className="text-xs text-muted-foreground font-medium hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>

        <div className="space-y-3.5">
          {cropsByCategory(props.crops, props.cropGroups).map(({ category, crops }) => {
            const Icon = AREA_STYLE[category].icon;
            return (
              <div key={category}>
                <div className="flex items-center gap-1.5 mb-1.5 px-0.5">
                  <Icon className="w-3 h-3 text-muted-foreground/55" />
                  <p className="text-[10px] font-semibold tracking-[0.16em] uppercase text-muted-foreground/55">
                    {category}
                  </p>
                  <span className="text-[10px] text-muted-foreground/40">{crops.length}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {crops.map((crop) => {
                    const selected = selectedCropIds.includes(crop.id);
                    const cropVarieties = props.varieties.filter((v) => v.crop_id === crop.id);
                    const inBloom = cropVarieties.some((v) => {
                      const vs = props.varietyStages.find((s) => s.variety_id === v.id);
                      return vs?.stage === 'bloom';
                    });

                    const cropColors = colorsForCrop(crop.id);
                    return (
                      <button
                        key={crop.id}
                        onClick={() => toggleCrop(crop.id)}
                        className={`relative flex items-center gap-2 rounded-xl px-3 py-2.5 text-left transition-all ring-1 shadow-sm ${
                          selected ? 'shadow-md' : 'hover:ring-2'
                        }`}
                        style={{
                          backgroundColor: selected ? `${cropColors.fill}40` : 'var(--card)',
                          borderColor: selected ? cropColors.border : 'transparent',
                          boxShadow: selected
                            ? `inset 0 0 0 1.5px ${cropColors.border}`
                            : undefined,
                        }}
                      >
                        <div
                          className="flex items-center justify-center w-5 h-5 rounded-md border-2 transition-colors shrink-0"
                          style={{
                            backgroundColor: selected ? cropColors.border : 'transparent',
                            borderColor: selected ? cropColors.border : 'rgba(0,0,0,0.15)',
                          }}
                        >
                          {selected && <Check className="w-3 h-3 text-white" />}
                        </div>
                        <span className="font-medium text-sm truncate">{crop.name}</span>
                        {inBloom && (
                          <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-pink-600 ml-auto shrink-0">
                            <Flower2 className="w-3 h-3" />
                            Bloom
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Crop Needs Summary ── */}
      {showMixes && cropNeeds.length > 0 && (
        <section>
          <h2 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70 mb-2">
            Coverage Status
          </h2>
          <div className="space-y-1">
            {cropNeeds.map((cn) => {
              const cfg = urgencyConfig[cn.urgency];
              return (
                <div key={cn.crop.id} className="flex items-center gap-2 text-sm py-1">
                  <div className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
                  <span
                    className="inline-flex items-center rounded-full ring-1 text-[11px] font-semibold px-1.5 py-0.5"
                    style={cropPillStyle(cn.crop.id)}
                  >
                    {cn.crop.name}
                  </span>
                  <span className="text-[11px] text-muted-foreground ml-auto">
                    {cn.needsFungicide && cn.needsInsecticide
                      ? 'Fungicide + insecticide'
                      : cn.needsFungicide
                        ? 'Fungicide needed'
                        : cn.needsInsecticide
                          ? 'Insecticide needed'
                          : 'OK'}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Mix Plans ── */}
      {showMixes && (
        <section ref={mixSectionRef}>
          {mixPlans.length === 0 ? (
            <div className="text-center py-10 space-y-3">
              {cropNeeds.some((cn) => cn.needsFungicide || cn.needsInsecticide) ? (
                <>
                  <div className="mx-auto w-14 h-14 rounded-full bg-amber-100 flex items-center justify-center">
                    <AlertTriangle className="w-7 h-7 text-amber-600" />
                  </div>
                  <p className="font-heading font-semibold text-lg text-amber-800">
                    No matching products in inventory
                  </p>
                  <p className="text-sm text-muted-foreground mb-2">
                    {props.inventoryProductIds.length === 0
                      ? 'Your inventory is empty. Add products to get mix recommendations.'
                      : 'None of your stocked products are labeled for the selected crops.'}
                  </p>
                  <div className="flex gap-2 justify-center">
                    <a
                      href={withBase('/inventory')}
                      className="text-sm bg-emerald-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-emerald-700 transition-colors"
                    >
                      Go to Inventory
                    </a>
                    {!planAhead && (
                      <button
                        onClick={() => setPlanAhead(true)}
                        className="text-sm text-emerald-600 font-medium px-4 py-2 rounded-lg ring-1 ring-emerald-300 hover:bg-emerald-50 transition-colors"
                      >
                        Show all products
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="mx-auto w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center">
                    <Shield className="w-7 h-7 text-emerald-600" />
                  </div>
                  <p className="font-heading font-semibold text-lg text-emerald-800">
                    All selected crops are protected
                  </p>
                  <p className="text-sm text-muted-foreground mb-2">
                    No urgent sprays needed right now.
                  </p>
                  <button
                    onClick={() => setPlanAhead(true)}
                    className="text-sm text-emerald-600 font-medium hover:text-emerald-700 underline underline-offset-2"
                  >
                    Plan next spray anyway
                  </button>
                </>
              )}
            </div>
          ) : (
            <>
              <div className="flex items-baseline justify-between mb-3">
                <h2 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
                  Recommended Mixes
                  <span className="ml-1.5 text-muted-foreground/60 font-normal tracking-normal normal-case">
                    {mixPlans.filter((p) => !dismissedMixes.includes(p.id)).length}
                  </span>
                </h2>
                {(dismissedMixes.length > 0 || removedProducts.length > 0) && (
                  <button
                    onClick={() => {
                      setDismissedMixes([]);
                      setRemovedProducts([]);
                    }}
                    className="text-xs text-emerald-600 font-medium hover:text-emerald-700"
                  >
                    Reset
                  </button>
                )}
              </div>

              <div className="space-y-3 animate-stagger">
                {mixPlans
                  .filter((p) => !dismissedMixes.includes(p.id))
                  .map((plan, idx) => {
                    const activePlan = {
                      ...plan,
                      products: plan.products.filter(
                        (p) => !removedProducts.includes(`${plan.id}-${p.product.id}`)
                      ),
                    };
                    if (activePlan.products.length === 0) return null;

                    const isExpanded = effectiveExpanded === plan.id;
                    const isLogged = loggedMixes.includes(plan.id);
                    const interlocks = getInterlocks(activePlan);
                    const blocks = interlocks.filter((i) => i.severity === 'block');
                    const warnings = interlocks.filter((i) => i.severity === 'warning');

                    return (
                      <div
                        key={plan.id}
                        className={`rounded-xl bg-card shadow-sm ring-1 overflow-hidden transition-all ${
                          isLogged ? 'ring-emerald-300 bg-emerald-50/30' : 'ring-black/[0.04]'
                        }`}
                      >
                        {/* Header */}
                        <div className="flex items-center">
                          <button
                            onClick={() => setExpandedMix(isExpanded ? null : plan.id)}
                            className="flex-1 flex items-center gap-3 px-4 py-3.5 text-left hover:bg-muted/30 transition-colors"
                          >
                            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-emerald-50 ring-1 ring-emerald-200/50 shrink-0">
                              {isLogged ? (
                                <Check className="w-4 h-4 text-emerald-600" />
                              ) : (
                                <span className="text-sm font-heading font-semibold text-emerald-700">
                                  {idx + 1}
                                </span>
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              {isLogged ? (
                                <p className="font-heading font-semibold text-sm text-emerald-700">
                                  Logged
                                </p>
                              ) : (
                                <div className="flex flex-wrap gap-1 items-baseline">
                                  {activePlan.crops.map((c) => (
                                    <span
                                      key={c.id}
                                      className="rounded-full text-[11px] font-semibold ring-1 px-1.5 py-0.5"
                                      style={cropPillStyle(c.id)}
                                    >
                                      {c.name}
                                    </span>
                                  ))}
                                </div>
                              )}
                              <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
                                {activePlan.products.map((p) => p.product.brand).join(' + ')}
                                {' · '}
                                {activePlan.coverageTypes.join(' + ')}
                              </p>
                            </div>
                            <ChevronDown
                              className={`w-4 h-4 text-muted-foreground/50 shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                            />
                          </button>
                          {!isLogged && (
                            <button
                              onClick={() => setDismissedMixes([...dismissedMixes, plan.id])}
                              className="px-3 py-3.5 text-muted-foreground/50 hover:text-terra-500 transition-colors shrink-0"
                              title="Skip this mix"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>

                        {/* Expanded */}
                        {isExpanded && !isLogged && (
                          <div className="border-t border-border/40">
                            {/* Products — flat rows with thin dividers, no nested cards */}
                            <div className="divide-y divide-border/30">
                              {activePlan.products.map((mp) => {
                                const key = `${plan.id}-${mp.product.id}`;
                                const rate = rates[key] ?? mp.suggestedRate;
                                const dose = calculateDose(rate, mp.rateUnit, sprayerGallons);
                                const fracGroup = mp.ingredients.find(
                                  (i) => i.frac_irac_hrac_group
                                )?.frac_irac_hrac_group;
                                const inv = props.inventoryData.find(
                                  (i) => i.product_id === mp.product.id
                                );
                                const cost = inv
                                  ? doseCost(inv, rate, mp.rateUnit, sprayerGallons)
                                  : null;
                                const costStr = cost != null ? cost.toFixed(2) : null;

                                return (
                                  <div key={mp.product.id} className="px-4 py-3 space-y-2">
                                    {/* Row 1: identity + swap/remove */}
                                    <div className="flex items-start gap-2.5">
                                      <div
                                        className={`w-2 h-2 rounded-full shrink-0 mt-1.5 ${roleDot[mp.role] ?? 'bg-muted'}`}
                                      />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-baseline gap-1.5 flex-wrap">
                                          <button
                                            onClick={() =>
                                              setSwapping({
                                                planId: plan.id,
                                                mixProduct: mp,
                                                groupIds: plan.cropGroupIds,
                                              })
                                            }
                                            className="font-medium text-sm text-left text-foreground hover:text-emerald-700 transition-colors"
                                          >
                                            {productLabel(mp.product.brand, mp.ingredients)}
                                          </button>
                                          {fracGroup &&
                                            (() => {
                                              const scheme =
                                                mp.role === 'insecticide' ? 'IRAC' : 'FRAC';
                                              const moa =
                                                mp.ingredients.find((i) => i.mode_of_action)
                                                  ?.mode_of_action ?? null;
                                              return (
                                                <button
                                                  type="button"
                                                  onClick={() =>
                                                    setGroupInfo({
                                                      scheme,
                                                      group: fracGroup,
                                                      productBrand: mp.product.brand,
                                                      modeOfAction: moa,
                                                    })
                                                  }
                                                  className="inline-flex items-center gap-0.5 text-[10px] font-medium text-emerald-700/70 tabular-nums rounded-full px-1.5 py-0.5 ring-1 ring-emerald-200/50 hover:bg-emerald-50 hover:text-emerald-800 transition-colors"
                                                  aria-label={`What is ${scheme} group ${fracGroup}?`}
                                                  title={`Tap: what does ${scheme} ${fracGroup} mean?`}
                                                >
                                                  {scheme} {fracGroup}
                                                  <span className="text-[9px] opacity-60">ⓘ</span>
                                                </button>
                                              );
                                            })()}
                                        </div>
                                        <button
                                          onClick={() =>
                                            setSwapping({
                                              planId: plan.id,
                                              mixProduct: mp,
                                              groupIds: plan.cropGroupIds,
                                            })
                                          }
                                          className="text-[11px] text-muted-foreground capitalize text-left hover:text-foreground transition-colors"
                                        >
                                          {mp.role.replace('-', ' ')} · {mp.coverageType} · tap to
                                          swap
                                        </button>
                                      </div>
                                      {activePlan.products.length > 1 && (
                                        <button
                                          onClick={() =>
                                            setRemovedProducts([
                                              ...removedProducts,
                                              `${plan.id}-${mp.product.id}`,
                                            ])
                                          }
                                          className="p-1 -m-1 text-muted-foreground/40 hover:text-terra-500 transition-colors shrink-0"
                                          title="Remove from mix"
                                        >
                                          <X className="w-3.5 h-3.5" />
                                        </button>
                                      )}
                                    </div>

                                    {/* Row 2: rate slider + editable numeric readout */}
                                    <div className="flex items-center gap-3">
                                      <input
                                        type="range"
                                        min={mp.rateMin ?? 0}
                                        max={mp.rateMax ?? rate * 2}
                                        step={0.05}
                                        value={rate}
                                        onChange={(e) =>
                                          setRates({ ...rates, [key]: parseFloat(e.target.value) })
                                        }
                                        aria-label={`Rate for ${mp.product.brand}`}
                                        className="flex-1 h-1.5 accent-emerald-600"
                                      />
                                      <div className="flex items-center gap-1 shrink-0">
                                        <input
                                          type="number"
                                          inputMode="decimal"
                                          min={mp.rateMin ?? 0}
                                          max={mp.rateMax ?? undefined}
                                          step={0.05}
                                          value={
                                            Number.isFinite(rate) ? Number(rate.toFixed(2)) : ''
                                          }
                                          onChange={(e) => {
                                            const v = parseFloat(e.target.value);
                                            setRates({
                                              ...rates,
                                              [key]: Number.isNaN(v) ? 0 : Math.max(0, v),
                                            });
                                          }}
                                          aria-label={`Rate for ${mp.product.brand} in ${mp.rateUnit}`}
                                          className="w-14 text-right text-[11px] font-mono tabular-nums rounded-md ring-1 ring-border/60 bg-card px-1.5 py-1 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                                        />
                                        <span className="text-[11px] font-mono text-muted-foreground w-10 truncate">
                                          {mp.rateUnit.replace('/gal', '')}
                                        </span>
                                      </div>
                                    </div>

                                    {/* Row 3: dose inline */}
                                    <div className="flex items-baseline gap-2 text-[12px]">
                                      <ArrowRight className="w-3 h-3 text-emerald-600/70 shrink-0" />
                                      <span className="text-muted-foreground">Add</span>
                                      <span className="font-heading font-semibold text-emerald-800">
                                        {dose.bestDisplay}
                                      </span>
                                      <span className="text-muted-foreground">
                                        to {dose.totalGallons} gal tank
                                      </span>
                                      <span className="text-muted-foreground/50 ml-auto tabular-nums flex items-baseline gap-1.5">
                                        <span>{dose.mL}&nbsp;mL</span>
                                        {costStr ? (
                                          <button
                                            type="button"
                                            onClick={() => setInventoryEditProductId(mp.product.id)}
                                            className="text-emerald-700 font-medium hover:text-emerald-800 hover:underline"
                                            title="Edit price / inventory for this product"
                                          >
                                            ${costStr}
                                          </button>
                                        ) : (
                                          <button
                                            type="button"
                                            onClick={() => setInventoryEditProductId(mp.product.id)}
                                            className="text-[10px] text-emerald-600/70 hover:text-emerald-700 hover:underline font-medium"
                                            title="Enter inventory + price to estimate spray cost"
                                          >
                                            + price
                                          </button>
                                        )}
                                      </span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>

                            {/* Interlocks — inline warnings, above summary */}
                            {(blocks.length > 0 || warnings.length > 0) && (
                              <div className="px-4 pt-3 space-y-1.5">
                                {blocks.map((b, i) => (
                                  <div
                                    key={`b${i}`}
                                    className="flex items-start gap-2 text-[11px] leading-snug"
                                  >
                                    <AlertTriangle className="w-3.5 h-3.5 text-terra-500 shrink-0 mt-0.5" />
                                    <div>
                                      <span className="font-semibold text-terra-700">
                                        Blocked: {b.rule}.
                                      </span>
                                      <span className="text-terra-600/80"> {b.explanation}</span>
                                    </div>
                                  </div>
                                ))}
                                {warnings.map((w, i) => (
                                  <div
                                    key={`w${i}`}
                                    className="flex items-start gap-2 text-[11px] leading-snug"
                                  >
                                    <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
                                    <div>
                                      <span className="font-semibold text-amber-700">
                                        {w.rule}.
                                      </span>
                                      <span className="text-amber-600/80"> {w.explanation}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Footer: cost + PPE as subtle key: value pairs, no boxes */}
                            {(() => {
                              let totalCost = 0;
                              let hasCost = false;
                              for (const mp of activePlan.products) {
                                const inv = props.inventoryData.find(
                                  (i) => i.product_id === mp.product.id
                                );
                                if (!inv) continue;
                                const rate =
                                  rates[`${plan.id}-${mp.product.id}`] ?? mp.suggestedRate;
                                const c = doseCost(inv, rate, mp.rateUnit, sprayerGallons);
                                if (c != null) {
                                  totalCost += c;
                                  hasCost = true;
                                }
                              }
                              const ppe = Array.from(
                                new Set(
                                  activePlan.products.flatMap((p) => {
                                    const req = p.product.ppe_requirements as Record<
                                      string,
                                      unknown
                                    > | null;
                                    return req
                                      ? Object.entries(req)
                                          .filter(([, v]) => v)
                                          .map(([k]) => k.replace(/_/g, ' '))
                                      : [];
                                  })
                                )
                              ).join(', ');
                              if (!hasCost && !ppe) return null;
                              return (
                                <dl className="px-4 pt-3 text-[11px] space-y-1">
                                  {hasCost && (
                                    <div className="flex items-baseline gap-2">
                                      <dt className="text-muted-foreground/60 tracking-wide uppercase text-[10px] shrink-0 w-10">
                                        Cost
                                      </dt>
                                      <dd className="font-mono tabular-nums text-foreground">
                                        ${totalCost.toFixed(2)}
                                      </dd>
                                    </div>
                                  )}
                                  {ppe && (
                                    <div className="flex items-baseline gap-2">
                                      <dt className="text-muted-foreground/60 tracking-wide uppercase text-[10px] shrink-0 w-10">
                                        PPE
                                      </dt>
                                      <dd className="text-muted-foreground">{ppe}</dd>
                                    </div>
                                  )}
                                </dl>
                              );
                            })()}

                            {/* Queue or Log */}
                            <div className="px-4 pt-3 pb-4">
                              {queuedMixId === plan.id ? (
                                <SprayTimingPanel
                                  plan={activePlan}
                                  cropUses={props.cropUses}
                                  weatherHourly={props.weatherHourly}
                                  notes={notes[plan.id] ?? ''}
                                  onNotesChange={(v) => setNotes({ ...notes, [plan.id]: v })}
                                  onLog={(vol) => handleLogMix(activePlan, vol)}
                                  onBack={() => setQueuedMixId(null)}
                                  logging={logging === plan.id}
                                  hasBlocks={blocks.length > 0}
                                  defaultVolume={sprayerGallons}
                                />
                              ) : (
                                <button
                                  onClick={() => handleQueueSpray(activePlan)}
                                  disabled={blocks.length > 0 || logging === plan.id}
                                  className="w-full bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-50 rounded-xl h-11 font-medium text-sm transition-colors"
                                >
                                  {logging === plan.id ? 'Queuing...' : 'Queue This Spray'}
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            </>
          )}
        </section>
      )}

      {/* ── Inventory / price quick-edit ── */}
      {inventoryEditProductId !== null && (
        <InventoryQuickEdit
          product={props.products.find((p) => p.id === inventoryEditProductId) ?? null}
          current={props.inventoryData.find((i) => i.product_id === inventoryEditProductId) ?? null}
          onClose={() => setInventoryEditProductId(null)}
          onSaved={() => {
            setInventoryEditProductId(null);
          }}
        />
      )}

      {/* ── FRAC / IRAC explanation ── */}
      {groupInfo && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
          <div
            className="fixed inset-0 bg-black/20 backdrop-blur-sm"
            onClick={() => setGroupInfo(null)}
          />
          <div className="relative w-full max-w-sm bg-popover rounded-t-2xl sm:rounded-2xl shadow-xl ring-1 ring-foreground/10 overflow-hidden">
            <div className="px-4 pt-4 pb-3 border-b border-border/40 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
                  {groupInfo.scheme} Group {groupInfo.group}
                </p>
                <p className="font-heading font-semibold text-base mt-0.5 truncate">
                  {groupInfo.productBrand}
                </p>
              </div>
              <button
                onClick={() => setGroupInfo(null)}
                className="p-1 rounded-lg hover:bg-muted transition-colors shrink-0"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-4 py-3 space-y-3 text-sm">
              {groupInfo.modeOfAction && (
                <div>
                  <p className="text-[10px] font-semibold tracking-[0.18em] uppercase text-muted-foreground/60 mb-1">
                    Mode of action
                  </p>
                  <p className="text-foreground/80 leading-snug">{groupInfo.modeOfAction}</p>
                </div>
              )}
              <div>
                <p className="text-[10px] font-semibold tracking-[0.18em] uppercase text-muted-foreground/60 mb-1">
                  What this is
                </p>
                <p className="text-foreground/80 leading-snug">
                  {groupInfo.scheme === 'FRAC' ? (
                    <>
                      The <strong>Fungicide Resistance Action Committee</strong> (FRAC) classifies
                      fungicides by how they attack fungi. Two fungicides in the same FRAC group
                      share the same biochemical target, so pests resistant to one will also resist
                      the other. Rotate between different groups to slow resistance.
                    </>
                  ) : (
                    <>
                      The <strong>Insecticide Resistance Action Committee</strong> (IRAC) classifies
                      insecticides by their nerve or growth target in the insect. Two insecticides
                      in the same IRAC group share a target, so pests that become resistant to one
                      will also resist the other. Rotate groups across sprays.
                    </>
                  )}
                </p>
              </div>
              <div className="rounded-lg bg-emerald-50/60 ring-1 ring-emerald-200/40 px-3 py-2 text-[12px] text-emerald-800 leading-snug">
                <strong>Rotation tip:</strong> don&apos;t use Group {groupInfo.group} twice in a
                row. Pick a different {groupInfo.scheme} group next spray to keep resistance
                pressure low.
              </div>
              <a
                href={
                  groupInfo.scheme === 'FRAC'
                    ? 'https://www.frac.info/'
                    : 'https://irac-online.org/modes-of-action/'
                }
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600 hover:text-emerald-700"
              >
                Learn more on {groupInfo.scheme}.info
                <ArrowRight className="w-3 h-3" />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ── Substitution Picker ── */}
      {swapping && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
          <div
            className="fixed inset-0 bg-black/10 backdrop-blur-sm"
            onClick={() => setSwapping(null)}
          />
          <div className="relative w-full max-w-md max-h-[70vh] bg-popover rounded-t-2xl sm:rounded-2xl shadow-xl ring-1 ring-foreground/10 overflow-hidden flex flex-col">
            <div className="px-4 pt-4 pb-2 border-b border-border/40 flex items-center justify-between shrink-0">
              <div>
                <p className="text-[10px] font-medium tracking-widest uppercase text-muted-foreground/60">
                  Swap {swapping.mixProduct.role.replace('-', ' ')}
                </p>
                <p className="font-heading font-semibold text-sm">
                  Replace{' '}
                  {productLabel(swapping.mixProduct.product.brand, swapping.mixProduct.ingredients)}
                </p>
              </div>
              <button
                onClick={() => setSwapping(null)}
                className="p-1.5 rounded-lg hover:bg-muted transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-2">
              {(() => {
                const plan = mixPlans.find((p) => p.id === swapping.planId);
                if (!plan) return null;

                const otherIds = plan.products
                  .filter((p) => p.product.id !== swapping.mixProduct.product.id)
                  .map((p) => p.product.id);

                const hasPear = plan.crops.some((c) => c.name.toLowerCase().includes('pear'));

                const alts = getAlternatives(
                  swapping.groupIds,
                  swapping.mixProduct.role,
                  swapping.mixProduct.product.id,
                  otherIds,
                  plannerData,
                  hasPear
                );

                if (alts.length === 0) {
                  return (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      No alternative products available for this role and crop group.
                    </p>
                  );
                }

                return alts.map((alt) => (
                  <button
                    key={alt.product.id}
                    onClick={() => {
                      if (!alt.blocked) {
                        substituteProduct(
                          swapping.groupIds,
                          swapping.mixProduct.role,
                          alt.product.id
                        );
                      }
                    }}
                    disabled={alt.blocked}
                    className={`w-full text-left rounded-xl px-3 py-3 mb-1 transition-all ${
                      alt.blocked
                        ? 'opacity-50 cursor-not-allowed bg-muted/30'
                        : 'hover:bg-emerald-50/60 hover:ring-1 hover:ring-emerald-200/50'
                    }`}
                  >
                    <div className="flex items-start gap-2.5">
                      <div
                        className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${roleDot[alt.role]}`}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-sm">
                            {productLabel(alt.product.brand, alt.ingredients)}
                          </span>
                          {alt.ingredients[0]?.frac_irac_hrac_group && (
                            <span className="text-[10px] text-muted-foreground bg-parchment-100 px-1.5 py-0 rounded-full">
                              Group {alt.ingredients[0].frac_irac_hrac_group}
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {alt.ingredients.map((i) => i.name).join(', ')}
                          {alt.ingredients[0]?.mode_of_action &&
                            ` — ${alt.ingredients[0].mode_of_action}`}
                        </p>
                        {alt.blocked && alt.blockReason && (
                          <p className="text-[11px] text-terra-600 mt-0.5 font-medium">
                            {alt.blockReason}
                          </p>
                        )}
                      </div>
                      {!alt.blocked && (
                        <ArrowRight className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-1" />
                      )}
                    </div>
                  </button>
                ));
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Inline popover/dialog for editing a product's inventory + pricing without
// leaving the spray planner. If the product isn't in inventory yet, saving
// inserts a new row; otherwise it updates the existing one.
function InventoryQuickEdit({
  product,
  current,
  onClose,
  onSaved,
}: {
  product: { id: number; brand: string } | null;
  current: {
    id: number;
    product_id: number;
    quantity: number;
    unit: string;
    bottle_size: number | null;
    cost_dollars: number | null;
  } | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [quantity, setQuantity] = useState(current?.quantity?.toString() ?? '');
  const [bottleSize, setBottleSize] = useState(current?.bottle_size?.toString() ?? '');
  const [cost, setCost] = useState(current?.cost_dollars?.toString() ?? '');
  const [unit, setUnit] = useState(current?.unit ?? 'fl oz');

  if (!product) return null;

  async function save() {
    setSaving(true);
    const supabase = createClient();
    const payload = {
      product_id: product!.id,
      quantity: parseFloat(quantity) || 0,
      bottle_size: bottleSize ? parseFloat(bottleSize) : null,
      cost_dollars: cost ? parseFloat(cost) : null,
      unit,
      bottle_unit: unit,
      updated_at: new Date().toISOString(),
    };
    const { error } = current
      ? await supabase.from('treatment_inventory').update(payload).eq('id', current.id)
      : await supabase.from('treatment_inventory').insert(payload);
    setSaving(false);
    if (error) {
      console.error('Inventory save failed:', error);
      toast({
        variant: 'error',
        title: "Couldn't save inventory",
        description: 'Please try again.',
      });
      return;
    }
    toast({ variant: 'success', title: 'Inventory updated', description: product!.brand });
    onSaved();
    router.refresh();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
      <div className="fixed inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-sm bg-popover rounded-t-2xl sm:rounded-2xl shadow-xl ring-1 ring-foreground/10 overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-border/40 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
              Inventory & price
            </p>
            <p className="font-heading font-semibold text-base mt-0.5 truncate">{product.brand}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-muted transition-colors shrink-0"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-4 py-3 space-y-3">
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-medium tracking-[0.14em] uppercase text-muted-foreground/60 block mb-1">
                On hand
              </label>
              <input
                type="number"
                step="0.1"
                min="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="0"
                className="w-full h-9 rounded-lg ring-1 ring-border/60 bg-card px-2.5 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
              />
            </div>
            <div className="w-24">
              <label className="text-[10px] font-medium tracking-[0.14em] uppercase text-muted-foreground/60 block mb-1">
                Unit
              </label>
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="w-full h-9 rounded-lg ring-1 ring-border/60 bg-card px-1.5 text-sm focus:outline-none"
              >
                {['fl oz', 'mL', 'gal', 'qt', 'pt', 'tbsp', 'tsp', 'oz', 'lb', 'g', 'packets'].map(
                  (u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  )
                )}
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-medium tracking-[0.14em] uppercase text-muted-foreground/60 block mb-1">
                Bottle size
              </label>
              <input
                type="number"
                step="0.1"
                min="0"
                value={bottleSize}
                onChange={(e) => setBottleSize(e.target.value)}
                placeholder={quantity || 'e.g. 32'}
                className="w-full h-9 rounded-lg ring-1 ring-border/60 bg-card px-2.5 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
              />
            </div>
            <div className="flex-1">
              <label className="text-[10px] font-medium tracking-[0.14em] uppercase text-muted-foreground/60 block mb-1">
                Cost ($)
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                placeholder="0.00"
                className="w-full h-9 rounded-lg ring-1 ring-border/60 bg-card px-2.5 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
              />
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground/60 leading-snug">
            Bottle size is what you paid for; on-hand is what&apos;s left. If bottle size is blank,
            cost estimates fall back to on-hand as the basis.
          </p>
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 h-10 rounded-lg ring-1 ring-border text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="flex-[2] h-10 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
