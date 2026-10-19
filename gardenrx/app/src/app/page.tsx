import { fetchWeather, getCurrentSprayRating } from '@/lib/weather';
import { SPRAY_RATING, LOCATION } from '@/config/thresholds';
import { getSprayRecordsForCrop, computeCoverage } from '@/lib/protection';
import { buildPhiByProductGroup, computeCropPhi } from '@/lib/phi';
import { harvestSeason } from '@/lib/harvest-windows';
import { applyPhenology } from '@/lib/phenology';
import {
  fetchCrops,
  fetchCropGroups,
  fetchVarieties,
  fetchVarietyStages,
  fetchProducts,
  fetchProductIngredients,
  fetchActiveIngredients,
  fetchCropUses,
  fetchSprayHistory,
  fetchQueuedSprays,
  buildIngredientMap,
} from '@/lib/queries';
import { VerdictHero } from '@/components/today/verdict-hero';
import {
  NeedsAttention,
  ComingUp,
  SprayConditions,
  WeatherUnavailable,
  type AttentionItem,
  type ComingUpItem,
} from '@/components/today/sections';
import { QueuedSprayCard } from '@/components/queued-spray-card';
import { RainTracker } from '@/components/rain-tracker';
import { dailyRainfall, rainfallSummary } from '@/lib/rainfall';

export const dynamic = 'force-dynamic';

export default async function TodayPage() {
  const [
    weather,
    crops,
    cropGroups,
    varieties,
    varietyStages,
    products,
    productIngredients,
    activeIngredients,
    cropUses,
    { sprayEvents, sprayEventProducts, sprayEventCrops },
    { queuedSprays, queuedSprayProducts, queuedSprayCrops },
  ] = await Promise.all([
    fetchWeather().catch(() => null),
    fetchCrops({ activeOnly: true }),
    fetchCropGroups(),
    fetchVarieties(),
    fetchVarietyStages(),
    fetchProducts(),
    fetchProductIngredients(),
    fetchActiveIngredients(),
    fetchCropUses(),
    fetchSprayHistory(),
    fetchQueuedSprays(),
  ]);

  const cropGroupName = new Map(cropGroups.map((g) => [g.id, g.name]));
  const ingredientMap = buildIngredientMap(productIngredients, activeIngredients);
  const productBrand = (id: number) => products.find((p) => p.id === id)?.brand ?? 'a spray';
  const phiByProductGroup = buildPhiByProductGroup(cropUses);

  const now = new Date();
  // Stages advance with the Holly Springs phenology calendar (manual overrides kept).
  const effectiveStages = applyPhenology(varietyStages, varieties, crops, cropGroups, now);

  // Per-crop protection + PHI (existing logic — not reimplemented)
  const cropData = crops.map((crop) => {
    const cropVarieties = varieties.filter((v) => v.crop_id === crop.id);
    const stages = cropVarieties.map((v) => {
      const vs = effectiveStages.find((s) => s.variety_id === v.id);
      return {
        variety: v,
        stage: vs?.stage ?? 'dormant',
        isOverride: vs?.is_manual_override ?? false,
      };
    });
    const inBloom = stages.some((s) => s.stage === 'bloom');

    const sprayRecords = getSprayRecordsForCrop(
      crop.id,
      sprayEvents,
      sprayEventProducts,
      sprayEventCrops,
      products,
      ingredientMap
    );
    const precipHistory = weather?.precipHistory ?? [];
    // As-needed (manual) crops aren't monitored — skip their coverage entirely so
    // they never surface as "due" / "unprotected" on the dashboard.
    const monitorFung = crop.track_fungicide;
    const monitorIns = crop.track_insecticide;
    const fungicideCoverage = monitorFung
      ? computeCoverage(sprayRecords, 'fungicide', now, precipHistory)
      : null;
    const insecticideCoverage = monitorIns
      ? computeCoverage(sprayRecords, 'insecticide', now, precipHistory)
      : null;
    const phi = computeCropPhi(
      crop.id,
      crop.crop_group_id,
      sprayEvents,
      sprayEventProducts,
      sprayEventCrops,
      phiByProductGroup,
      productBrand,
      now
    );

    const inSeason = harvestSeason(crop.id, cropVarieties, now).inSeason;

    return {
      crop,
      varieties: cropVarieties,
      stages,
      inBloom,
      monitorFung,
      monitorIns,
      fungicideCoverage,
      insecticideCoverage,
      phi,
      inSeason,
    };
  });

  // ── Hero inputs ──
  const currentRating = weather ? getCurrentSprayRating(weather.current, weather.hourly) : null;
  const bloomCrops = cropData.filter((c) => c.inBloom).map((c) => c.crop.name);
  // Only count crops whose fruit is in season — a PHI is irrelevant otherwise.
  const phiCount = cropData.filter((c) => c.phi.active && c.inSeason).length;

  let weatherBlocker: string | null = null;
  if (weather) {
    if (weather.current.windSpeed > SPRAY_RATING.windPoor) {
      weatherBlocker = `Too windy — wind ${Math.round(weather.current.windSpeed)} mph.`;
    } else if (weather.current.temp < SPRAY_RATING.tempMinPoor) {
      weatherBlocker = `Too cold — ${Math.round(weather.current.temp)}°F.`;
    } else if (weather.current.temp > SPRAY_RATING.tempMaxPoor) {
      weatherBlocker = `Too hot — ${Math.round(weather.current.temp)}°F.`;
    } else if (weather.current.precipitation > 0) {
      weatherBlocker = 'Currently raining.';
    }
  }

  // Crops whose coverage has lapsed (red) — or brand-new crops with no history.
  const urgent = cropData
    .map((c) => {
      const fc = c.fungicideCoverage,
        ic = c.insecticideCoverage;
      const missing: Array<'fungicide' | 'insecticide'> = [];
      // A monitored type with lapsed (red) coverage — or no history at all — is due.
      if (c.monitorFung && (!fc || fc.status === 'red')) missing.push('fungicide');
      if (c.monitorIns && !c.inBloom && (!ic || ic.status === 'red')) missing.push('insecticide');
      return { cropId: c.crop.id, cropName: c.crop.name, missing };
    })
    .filter((u) => u.missing.length > 0);
  const fungDue = urgent.filter((u) => u.missing.includes('fungicide')).map((u) => u.cropName);
  const insDue = urgent.filter((u) => u.missing.includes('insecticide')).map((u) => u.cropName);
  // Crop ids behind the hero's "Plan a spray" CTA, so the planner opens
  // pre-loaded with exactly what's due instead of an empty picker.
  const dueCropIds = urgent.map((u) => u.cropId);
  // "Good to spray" only matters when something actually needs spraying — when
  // nothing's due we drop the spray-readiness rating and the spray-window card
  // rather than tell you conditions are great for a spray you don't need.
  const somethingDue = urgent.length > 0;

  // Soonest expiring healthy coverage
  const coverageExpiries = cropData
    .flatMap((c) => {
      const out: ComingUpItem[] = [];
      if (c.fungicideCoverage && c.fungicideCoverage.daysRemaining > 0)
        out.push({
          cropId: c.crop.id,
          cropName: c.crop.name,
          type: 'fungicide',
          daysLeft: c.fungicideCoverage.daysRemaining,
        });
      if (c.insecticideCoverage && c.insecticideCoverage.daysRemaining > 0)
        out.push({
          cropId: c.crop.id,
          cropName: c.crop.name,
          type: 'insecticide',
          daysLeft: c.insecticideCoverage.daysRemaining,
        });
      return out;
    })
    .sort((a, b) => a.daysLeft - b.daysLeft);
  const upcoming = coverageExpiries[0] ?? null;

  // "Unprotected" = a monitored crop where every tracked type still lacks coverage.
  // As-needed crops are intentionally manual, so they never count here.
  const unprotectedCount = cropData.filter(
    (c) =>
      (c.monitorFung || c.monitorIns) &&
      (!c.monitorFung || !c.fungicideCoverage) &&
      (!c.monitorIns || !c.insecticideCoverage)
  ).length;

  // ── Needs attention — lapsed (red) or degrading (yellow) ──
  const attention: AttentionItem[] = [];
  for (const c of cropData) {
    const due: string[] = [];
    const soon: string[] = [];
    const fc = c.fungicideCoverage,
      ic = c.insecticideCoverage;
    if (fc?.status === 'red') due.push('Fungicide');
    else if (fc?.status === 'yellow') soon.push('Fungicide');
    if (!c.inBloom) {
      if (ic?.status === 'red') due.push('Insecticide');
      else if (ic?.status === 'yellow') soon.push('Insecticide');
    }
    if (due.length || soon.length) {
      attention.push({
        cropId: c.crop.id,
        cropName: c.crop.name,
        cropGroup: c.crop.crop_group_id ? (cropGroupName.get(c.crop.crop_group_id) ?? null) : null,
        due,
        soon,
        inBloom: c.inBloom,
      });
    }
  }
  attention.sort(
    (a, b) =>
      (b.due.length ? 1 : 0) - (a.due.length ? 1 : 0) || a.cropName.localeCompare(b.cropName)
  );

  // ── Coming up — healthy coverage countdowns ──
  const comingUp: ComingUpItem[] = cropData
    .flatMap((c) => {
      const out: ComingUpItem[] = [];
      if (c.fungicideCoverage?.status === 'green' && c.fungicideCoverage.daysRemaining > 0)
        out.push({
          cropId: c.crop.id,
          cropName: c.crop.name,
          type: 'fungicide',
          daysLeft: c.fungicideCoverage.daysRemaining,
        });
      if (
        !c.inBloom &&
        c.insecticideCoverage?.status === 'green' &&
        c.insecticideCoverage.daysRemaining > 0
      )
        out.push({
          cropId: c.crop.id,
          cropName: c.crop.name,
          type: 'insecticide',
          daysLeft: c.insecticideCoverage.daysRemaining,
        });
      return out;
    })
    .sort((a, b) => a.daysLeft - b.daysLeft)
    .slice(0, 4);

  // ── Queued sprays ──
  const queuedSprayData = queuedSprays.map((qs) => {
    const qProducts = queuedSprayProducts
      .filter((qp) => qp.queued_spray_id === qs.id)
      .map((qp) => ({ ...qp, product: products.find((p) => p.id === qp.product_id) }))
      .filter((qp) => qp.product);
    const qCrops = queuedSprayCrops
      .filter((qc) => qc.queued_spray_id === qs.id)
      .map((qc) => ({ ...qc, crop: crops.find((c) => c.id === qc.crop_id) }))
      .filter((qc) => qc.crop);
    const coverageDays = qProducts.map((qp) => ({
      brand: qp.product!.brand,
      days: qp.product!.cover_spray_interval_days ?? 14,
    }));
    const phiImpacts = qProducts.flatMap((qp) =>
      qCrops
        .map((qc) => {
          const use = cropUses.find(
            (cu) => cu.product_id === qp.product_id && cu.crop_group_id === qc.crop?.crop_group_id
          );
          return use?.phi_days && use.phi_days > 0
            ? { cropName: qc.crop!.name, productName: qp.product!.brand, phiDays: use.phi_days }
            : null;
        })
        .filter(Boolean)
    );
    return {
      id: qs.id,
      notes: qs.notes,
      createdAt: qs.created_at,
      products: qProducts.map((qp) => ({
        brand: qp.product!.brand,
        rateApplied: qp.rate_applied,
        rateUnit: qp.rate_unit,
        ingredients: ingredientMap.get(qp.product_id) ?? [],
      })),
      crops: qCrops.map((qc) => qc.crop!.name),
      coverageDays,
      phiImpacts,
    };
  });

  // Greet in the orchard's local timezone — the server runs in UTC, which would
  // otherwise read "Good afternoon" during the user's actual morning.
  const localHour = Number(
    new Intl.DateTimeFormat('en-US', {
      timeZone: LOCATION.timezone,
      hour: '2-digit',
      hourCycle: 'h23',
    }).format(now)
  );
  const greeting =
    localHour < 12 ? 'Good morning' : localHour < 18 ? 'Good afternoon' : 'Good evening';
  const dateFull = new Intl.DateTimeFormat('en-US', {
    timeZone: LOCATION.timezone,
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).format(now);

  // 30-day rainfall summary + watering advice for the home-page Rainfall card.
  const rainDaily = dailyRainfall(weather?.precipHistory ?? [], 30);
  const rainSummary = rainDaily.length ? rainfallSummary(rainDaily) : null;
  const dailyHighs = (weather?.daily ?? [])
    .map((d) => d.tempHigh)
    .filter((t): t is number => typeof t === 'number');
  const avgHigh7 = dailyHighs.length
    ? dailyHighs.slice(0, 7).reduce((s, t) => s + t, 0) / Math.min(7, dailyHighs.length)
    : null;

  return (
    <div className="page animate-stagger">
      <div className="section-title" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 22 }}>{greeting}</h2>
        <span className="meta">{dateFull}</span>
      </div>

      <VerdictHero
        rating={currentRating}
        temp={weather?.current.temp ?? null}
        wind={weather?.current.windSpeed ?? null}
        fungDue={fungDue}
        insDue={insDue}
        dueCropIds={dueCropIds}
        bloomCrops={bloomCrops}
        weatherBlocker={weatherBlocker}
        weatherUnavailable={!weather}
        upcoming={upcoming}
        unprotectedCount={unprotectedCount}
        totalCrops={cropData.length}
        phiCount={phiCount}
      />

      <div className="detail-grid" style={{ marginTop: 'var(--gap)' }}>
        <div>
          <NeedsAttention items={attention} />
          <ComingUp items={comingUp} />
        </div>
        <div>
          {somethingDue &&
            (weather ? (
              <SprayConditions
                rating={currentRating}
                temp={weather.current.temp}
                wind={weather.current.windSpeed}
                humidity={weather.current.humidity}
                description={weather.current.description}
                hourly={weather.hourly}
                daily={weather.daily}
              />
            ) : (
              <WeatherUnavailable />
            ))}
          {queuedSprayData.length > 0 && (
            <section className="t-sec">
              <div className="t-sec-h">
                <h2>Queued sprays</h2>
                <span className="n">{queuedSprayData.length}</span>
              </div>
              <div className="flex flex-col gap-2.5">
                {queuedSprayData.map((qs) => (
                  <QueuedSprayCard key={qs.id} spray={qs} />
                ))}
              </div>
            </section>
          )}
          {rainSummary && (
            <section className="t-sec">
              <RainTracker
                daily={rainDaily}
                summary={rainSummary}
                avgHighF={avgHigh7}
                humidityPct={weather?.current?.humidity ?? null}
              />
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
