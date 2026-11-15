import { Droplets, CalendarDays, CloudSun, CloudRain, ChevronDown } from 'lucide-react';
import {
  fetchProducts,
  fetchCrops,
  fetchCropGroups,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchSprayHistory,
  buildIngredientMap,
  fetchInventory,
} from '@/lib/queries';
import { sprayEventCost } from '@/lib/spray-cost';
import { SPRAYER } from '@/config/thresholds';
import { AddSprayButton, SprayEventActions } from '@/components/spray-history-actions';
import { HistoryFilter } from '@/components/history-filter';
import { fetchWeather } from '@/lib/weather';
import { cumulativeRainSince } from '@/lib/protection';
import { productLabel } from '@/lib/product-label';
import { cropPillStyle } from '@/lib/crop-colors';
import { categoryForCrop, CATEGORY_ORDER, type CropCategory } from '@/lib/crop-category';
import { SectionTabs, SPRAY_TABS } from '@/components/shell/section-tabs';
import Link from 'next/link';

export const dynamic = 'force-dynamic';

export default async function HistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ area?: string }>;
}) {
  const params = await searchParams;
  const filterArea = (CATEGORY_ORDER as readonly string[]).includes(params.area ?? '')
    ? (params.area as CropCategory)
    : null;

  const [
    { sprayEvents, sprayEventProducts, sprayEventCrops },
    products,
    crops,
    cropGroups,
    productIngredients,
    activeIngredients,
    inventory,
  ] = await Promise.all([
    fetchSprayHistory(),
    fetchProducts(),
    fetchCrops(),
    fetchCropGroups(),
    fetchProductIngredients(),
    fetchActiveIngredients(),
    fetchInventory(),
  ]);

  const inventoryByProduct = new Map(inventory.map((i) => [i.product_id, i] as const));

  // Group the spray-event join rows by event id once. The timeline (and a few
  // derived calculations) look these up per event; grouping up front keeps the
  // page O(n) instead of re-filtering both join tables inside every map/loop.
  const productsByEvent = new Map<number, typeof sprayEventProducts>();
  for (const ep of sprayEventProducts) {
    const arr = productsByEvent.get(ep.spray_event_id);
    if (arr) arr.push(ep);
    else productsByEvent.set(ep.spray_event_id, [ep]);
  }
  const cropsByEvent = new Map<number, typeof sprayEventCrops>();
  for (const ec of sprayEventCrops) {
    const arr = cropsByEvent.get(ec.spray_event_id);
    if (arr) arr.push(ec);
    else cropsByEvent.set(ec.spray_event_id, [ec]);
  }
  const productsFor = (eventId: number) => productsByEvent.get(eventId) ?? [];
  const cropsFor = (eventId: number) => cropsByEvent.get(eventId) ?? [];

  // Season-to-date spray cost (moved here from the Inventory page).
  const seasonYear = new Date().getFullYear();
  const seasonEvents = sprayEvents.filter(
    (e) => new Date(e.date + 'T12:00:00').getFullYear() === seasonYear
  );
  const seasonCost = seasonEvents.reduce((sum, ev) => {
    const eps = productsFor(ev.id);
    return sum + sprayEventCost(eps, inventoryByProduct, ev.volume_gallons ?? SPRAYER.gallons).cost;
  }, 0);

  const weather = await fetchWeather().catch(() => null);
  const precipHistory = weather?.precipHistory ?? [];

  const productMap = new Map(products.map((p) => [p.id, p] as const));
  const cropMap = new Map(crops.map((c) => [c.id, c] as const));

  // Map each crop to its garden area, then derive which area each spray touched
  // (an event belongs to every area its crops fall in).
  const groupName = new Map(cropGroups.map((g) => [g.id, g.name] as const));
  const cropArea = new Map<number, CropCategory>(
    crops.map(
      (c) =>
        [
          c.id,
          categoryForCrop(c, c.crop_group_id ? (groupName.get(c.crop_group_id) ?? null) : null),
        ] as const
    )
  );
  const areasForEvent = (eventId: number): Set<CropCategory> => {
    const set = new Set<CropCategory>();
    for (const ec of cropsFor(eventId)) {
      const a = cropArea.get(ec.crop_id);
      if (a) set.add(a);
    }
    return set;
  };
  const availableAreas = CATEGORY_ORDER.filter((a) =>
    sprayEvents.some((e) => areasForEvent(e.id).has(a))
  );

  const ingredientMap = buildIngredientMap(productIngredients, activeIngredients);

  return (
    <div className="page">
      <div className="mx-auto max-w-3xl">
        <SectionTabs tabs={SPRAY_TABS} />
        <div className="section-title">
          <h2>Spray History</h2>
          <div className="spacer" />
          <AddSprayButton
            products={products}
            crops={crops}
            cropGroups={cropGroups}
            ingredientMap={ingredientMap}
          />
        </div>

        {/* Season spray cost */}
        <div
          className="card accent-card mb-4"
          style={{ padding: '16px 18px 16px 22px', ['--ac' as string]: 'var(--leaf)' }}
        >
          <div className="text-xs font-semibold uppercase tracking-[0.06em] text-ink-3">
            Season spray cost
          </div>
          <div className="mt-0.5 font-display text-[28px] font-semibold">
            ${seasonCost.toFixed(2)}
          </div>
          <div className="mono text-xs text-ink-3">
            {seasonEvents.length} application{seasonEvents.length === 1 ? '' : 's'} · {seasonYear}
          </div>
        </div>

        {/* Area filter */}
        <div className="mb-4">
          <HistoryFilter areas={availableAreas} />
        </div>

        {/* Timeline */}
        <section>
          <details open className="group/section">
            <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
                  Timeline
                </p>
                <span className="text-[10px] text-muted-foreground/50">({sprayEvents.length})</span>
              </div>
              <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
            </summary>

            {sprayEvents.length === 0 && (
              <div className="rounded-xl bg-card shadow-sm ring-1 ring-black/[0.04] px-6 py-12 text-center">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-parchment-100 ring-1 ring-black/[0.04] mx-auto mb-4">
                  <Droplets className="w-6 h-6 text-emerald-400" />
                </div>
                <p className="font-heading font-semibold text-foreground mb-1">
                  No spray events yet
                </p>
                <p className="text-sm text-muted-foreground max-w-xs mx-auto">
                  Once you log your first application, your spray journal will appear here with
                  timelines, usage tracking, and rotation analysis.
                </p>
              </div>
            )}

            {sprayEvents.length > 0 &&
              (() => {
                // Filter events by selected garden area
                const filteredEvents = filterArea
                  ? sprayEvents.filter((e) => areasForEvent(e.id).has(filterArea))
                  : sprayEvents;

                return (
                  <div className="relative animate-stagger">
                    {/* Vertical timeline line */}
                    <div className="absolute left-[19px] top-4 bottom-4 w-px bg-border/60" />

                    {filteredEvents.length === 0 && (
                      <p className="text-sm text-muted-foreground text-center py-8">
                        No spray events for this area.
                      </p>
                    )}

                    {filteredEvents.map((event) => {
                      const eventProducts = productsFor(event.id);
                      const eventCrops = cropsFor(event.id);
                      const eventWeather = event.weather_snapshot as Record<string, unknown> | null;
                      const eventDate = new Date(event.date + 'T12:00:00');

                      // The rain window for this spray ends the next time the SAME CROP was
                      // sprayed (any product) — that's when you were back out renewing
                      // coverage. Use the *soonest* such spray; if none, it runs to now.
                      const eventCropIds = new Set(eventCrops.map((ec) => ec.crop_id));
                      let nextReplacementDate: Date | undefined;
                      for (const laterEvent of filteredEvents) {
                        if (laterEvent.id === event.id) continue;
                        const laterDate = new Date(laterEvent.date + 'T12:00:00');
                        if (laterDate <= eventDate) continue; // only look forward
                        const laterCropIds = cropsFor(laterEvent.id).map((ec) => ec.crop_id);
                        if (!laterCropIds.some((id) => eventCropIds.has(id))) continue; // must share a crop
                        if (!nextReplacementDate || laterDate < nextReplacementDate) {
                          nextReplacementDate = laterDate;
                        }
                      }

                      // Rain between this spray and the next spray on the same crop (or now).
                      const rainSinceSpray = cumulativeRainSince(
                        eventDate,
                        precipHistory,
                        nextReplacementDate
                      );
                      const isReplaced = !!nextReplacementDate;

                      const worstRainFast = Math.max(
                        ...eventProducts.map((ep) => {
                          const p = productMap.get(ep.product_id);
                          return p?.rain_fastness_hours ?? 2;
                        }),
                        2
                      );
                      const rainFastDeadline = new Date(
                        eventDate.getTime() + worstRainFast * 3600000
                      );
                      const rainBeforeRainFast = precipHistory.some((h) => {
                        const t = new Date(h.time);
                        return t >= eventDate && t <= rainFastDeadline && h.precipitation > 0.01;
                      });
                      const worstRainTolerance = Math.min(
                        ...eventProducts.map((ep) => {
                          const p = productMap.get(ep.product_id);
                          return p?.rain_tolerance_inches ?? 2;
                        }),
                        2
                      );
                      const rainDegraded = rainSinceSpray >= worstRainTolerance;
                      const rainWashed = rainSinceSpray >= worstRainTolerance * 2;

                      // Estimated cost of this spray from inventory pricing (shared with the
                      // Harvest page's spray-cost vs. harvest-value comparison). Volume:
                      // prefer the event's recorded volume_gallons, else the app default.
                      const sprayVolume = event.volume_gallons ?? SPRAYER.gallons;
                      const {
                        cost: totalCost,
                        hasCost,
                        pricedCount,
                      } = sprayEventCost(eventProducts, inventoryByProduct, sprayVolume);
                      const ratedCount = eventProducts.filter(
                        (ep) => ep.rate_applied != null
                      ).length;
                      const partialCost = hasCost && pricedCount < ratedCount;

                      return (
                        <div
                          key={event.id}
                          id={`spray-${event.id}`}
                          className="relative pl-12 pb-4 scroll-mt-24 target:ring-2 target:ring-emerald-400/60 target:rounded-xl"
                        >
                          {/* Timeline dot */}
                          <div className="absolute left-[14px] top-4 w-2.5 h-2.5 rounded-full bg-emerald-500 ring-2 ring-card" />

                          <div className="rounded-xl bg-card shadow-sm ring-1 ring-black/[0.04] px-4 py-3">
                            {/* Date heading + volume + cost */}
                            <div className="flex items-center gap-2 mb-2">
                              <CalendarDays className="w-3.5 h-3.5 text-muted-foreground/70" />
                              <p className="font-heading font-semibold text-sm tracking-tight">
                                {eventDate.toLocaleDateString('en-US', {
                                  weekday: 'short',
                                  month: 'short',
                                  day: 'numeric',
                                })}
                              </p>
                              <div className="ml-auto flex items-center gap-1.5">
                                {event.volume_gallons != null && (
                                  <span
                                    className="inline-flex items-baseline gap-0.5 text-[11px] font-mono tabular-nums rounded-full bg-parchment-100 text-foreground/70 ring-1 ring-border/40 px-2 py-0.5"
                                    title="Total mix volume sprayed"
                                  >
                                    {event.volume_gallons}
                                    <span className="text-[9px] text-muted-foreground ml-0.5">
                                      gal
                                    </span>
                                  </span>
                                )}
                                {hasCost && (
                                  <span
                                    className="inline-flex items-baseline gap-0.5 text-[11px] font-mono tabular-nums rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60 px-2 py-0.5"
                                    title={
                                      partialCost
                                        ? `Estimated from inventory pricing — only ${pricedCount} of ${ratedCount} products are priced, so this is a partial total. Add prices on the Stock page.`
                                        : 'Estimated cost from inventory pricing'
                                    }
                                  >
                                    <span className="text-[10px] text-emerald-600/70">$</span>
                                    {totalCost.toFixed(2)}
                                    {partialCost && (
                                      <span className="text-[9px] text-emerald-600/60 ml-0.5">
                                        +
                                      </span>
                                    )}
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Products as pills — clickable */}
                            <div className="flex flex-wrap gap-1.5 mb-2">
                              {eventProducts.map((ep) => {
                                const p = productMap.get(ep.product_id);
                                return (
                                  <Link
                                    key={ep.product_id}
                                    href={`/products/${ep.product_id}`}
                                    className="rounded-full text-[11px] font-medium ring-1 px-2 py-0.5 bg-emerald-50 text-emerald-800 ring-emerald-200/60 hover:bg-emerald-100 hover:ring-emerald-300 transition-colors"
                                  >
                                    {productLabel(
                                      p?.brand ?? 'Unknown',
                                      ingredientMap.get(ep.product_id)
                                    )}
                                    {ep.rate_applied ? ` ${ep.rate_applied} ${ep.rate_unit}` : ''}
                                  </Link>
                                );
                              })}
                            </div>

                            {/* Crops as pills — color-coded per crop, consistent with the garden map */}
                            <div className="flex flex-wrap gap-1.5 mb-2">
                              {eventCrops.map((ec) => (
                                <span
                                  key={ec.crop_id}
                                  className="rounded-full text-[11px] font-medium ring-1 px-2 py-0.5"
                                  style={cropPillStyle(ec.crop_id)}
                                >
                                  {cropMap.get(ec.crop_id)?.name ?? 'Unknown'}
                                </span>
                              ))}
                            </div>

                            {/* Weather at spray time */}
                            {eventWeather && (
                              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                                <CloudSun className="w-3 h-3" />
                                <span>
                                  {eventWeather.temp ? `${eventWeather.temp}\u00b0F` : ''}
                                  {eventWeather.wind ? ` \u00b7 Wind ${eventWeather.wind} mph` : ''}
                                  {typeof eventWeather.conditions === 'string'
                                    ? ` \u00b7 ${eventWeather.conditions}`
                                    : ''}
                                </span>
                              </div>
                            )}

                            {/* Rain penalty */}
                            {rainSinceSpray > 0 && (
                              <div
                                className={`flex items-start gap-1.5 text-[11px] mt-1 rounded-lg px-2 py-1.5 ${
                                  rainWashed
                                    ? 'bg-terra-50 text-terra-700 ring-1 ring-terra-200/50'
                                    : rainDegraded
                                      ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-200/50'
                                      : rainBeforeRainFast
                                        ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-200/50'
                                        : 'bg-sky-50 text-sky-700 ring-1 ring-sky-200/50'
                                }`}
                              >
                                <CloudRain className="w-3 h-3 mt-0.5 shrink-0" />
                                <div>
                                  <span className="font-medium">
                                    {rainSinceSpray.toFixed(1)}&quot; rain
                                    {isReplaced
                                      ? ` before next spray (${nextReplacementDate!.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })})`
                                      : ' since spray'}
                                  </span>
                                  {rainWashed && !isReplaced && (
                                    <p className="text-[10px] mt-0.5">
                                      Coverage washed off — exceeded{' '}
                                      {(worstRainTolerance * 2).toFixed(1)}&quot; tolerance. Respray
                                      needed.
                                    </p>
                                  )}
                                  {rainDegraded && !rainWashed && !isReplaced && (
                                    <p className="text-[10px] mt-0.5">
                                      Coverage degraded — rain exceeded{' '}
                                      {worstRainTolerance.toFixed(1)}&quot; tolerance.
                                    </p>
                                  )}
                                  {rainBeforeRainFast && !rainDegraded && (
                                    <p className="text-[10px] mt-0.5">
                                      Rain fell within {worstRainFast}h rain-fast window — may have
                                      needed re-application.
                                    </p>
                                  )}
                                </div>
                              </div>
                            )}

                            {/* Notes */}
                            {event.notes && (
                              <p className="text-xs text-muted-foreground/60 italic mt-1.5">
                                {event.notes}
                              </p>
                            )}

                            {/* Edit/Delete actions */}
                            <SprayEventActions
                              event={event}
                              eventProducts={eventProducts}
                              eventCrops={eventCrops}
                              allProducts={products}
                              allCrops={crops}
                              cropGroups={cropGroups}
                              ingredientMap={ingredientMap}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
          </details>
        </section>
      </div>
    </div>
  );
}
