/**
 * Rainfall aggregation + a simple home-garden drought heuristic, built from the
 * hourly precipitation history that `fetchWeather()` already returns.
 */

export type DroughtStatus = 'wet' | 'adequate' | 'dry' | 'drought';

export interface DailyRain {
  date: string; // YYYY-MM-DD (location-local calendar day)
  inches: number;
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

/**
 * Roll hourly precip into per-day totals for the last `days` calendar days,
 * ending on the most recent day present in the data (so it's stable regardless
 * of the server's timezone). Missing days are filled with 0.
 */
export function dailyRainfall(
  history: Array<{ time: string; precipitation: number }>,
  days = 30
): DailyRain[] {
  const byDate = new Map<string, number>();
  let maxKey = '';
  for (const h of history) {
    const d = h.time.slice(0, 10); // YYYY-MM-DD from the API's local-tz timestamp
    byDate.set(d, (byDate.get(d) ?? 0) + (Number(h.precipitation) || 0));
    if (d > maxKey) maxKey = d;
  }
  if (!maxKey) return [];

  // Walk back `days` calendar days from the last data day, in UTC, so the
  // date-only keys don't drift with server timezone.
  const [y, m, d] = maxKey.split('-').map(Number);
  const end = new Date(Date.UTC(y, m - 1, d));
  const out: DailyRain[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(end);
    dt.setUTCDate(end.getUTCDate() - i);
    const key = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
    out.push({ date: key, inches: round2(byDate.get(key) ?? 0) });
  }
  return out;
}

export interface RainSummary {
  week: number; // last 7 days, inches
  month: number; // last 30 days, inches
  daysSinceRain: number | null; // days since a day with >= 0.1"
  wettest: DailyRain | null;
  status: DroughtStatus;
  monthExpected: number; // ~1"/week reference for the window
}

const RAIN_DAY = 0.1; // a day with at least this much counts as "it rained"

export function rainfallSummary(daily: DailyRain[]): RainSummary {
  const n = daily.length;
  const lastN = (k: number) => daily.slice(Math.max(0, n - k)).reduce((s, d) => s + d.inches, 0);
  const week = round2(lastN(7));
  const month = round2(lastN(30));

  let daysSinceRain: number | null = null;
  for (let i = n - 1; i >= 0; i--) {
    if (daily[i].inches >= RAIN_DAY) {
      daysSinceRain = n - 1 - i;
      break;
    }
  }

  const wettest = daily.reduce<DailyRain | null>(
    (best, d) => (!best || d.inches > best.inches ? d : best),
    null
  );

  // Gardens want roughly 1 inch of water per week; compare the window total to that.
  const monthExpected = round2((Math.min(30, n) / 7) * 1.0);
  const ratio = monthExpected > 0 ? month / monthExpected : 0;
  const status: DroughtStatus =
    ratio < 0.33 ? 'drought' : ratio < 0.66 ? 'dry' : ratio < 1.5 ? 'adequate' : 'wet';

  return { week, month, daysSinceRain, wettest, status, monthExpected };
}

export const DROUGHT_META: Record<DroughtStatus, { label: string; badge: string; bar: string }> = {
  drought: {
    label: 'Drought',
    badge: 'bg-rose-100 text-rose-700 ring-rose-300/60',
    bar: 'bg-rose-400',
  },
  dry: {
    label: 'Dry',
    badge: 'bg-amber-100 text-amber-700 ring-amber-300/60',
    bar: 'bg-amber-400',
  },
  adequate: {
    label: 'Adequate',
    badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60',
    bar: 'bg-emerald-400',
  },
  wet: {
    label: 'Wet',
    badge: 'bg-sky-100 text-sky-700 ring-sky-300/60',
    bar: 'bg-sky-400',
  },
};

// ── Watering recommendation ──

/** With the garden resting, highs below this mean resting plants: no watering call. */
const RESTING_WARM_F = 75;
/** Resting plants draw roughly this share of a growing garden's weekly water. */
const RESTING_SHARE = 0.5;

export type WateringStatus = 'soak' | 'water-soon' | 'ok' | 'wet' | 'rest';

export interface WateringAdvice {
  status: WateringStatus;
  rain7: number; // last 7 days of rain, inches
  targetWeekly: number; // evapotranspiration-adjusted weekly need, inches
  deficit: number; // shortfall vs target, inches (>= 0)
  headline: string; // the one instruction
  detail: string; // why, in one line
}

/**
 * Should you water this week? Plants want a deep soak roughly weekly — twice a
 * week in real heat — so we compare the *last 7 days* of rain against a weekly
 * target that scales with evapotranspiration demand (hotter and drier air pull
 * more moisture) and with the season: a resting garden (most crops dormant or
 * past harvest) needs about half, and outside real heat it is never told to
 * water, only reminded to check the soil after a dry spell.
 */
export function wateringAdvice(
  daily: DailyRain[],
  opts: { avgHighF?: number | null; humidityPct?: number | null; dormant?: boolean } = {}
): WateringAdvice {
  const n = daily.length;
  const rain7 = round2(daily.slice(Math.max(0, n - 7)).reduce((s, d) => s + d.inches, 0));
  const high = opts.avgHighF ?? null;
  const hum = opts.humidityPct ?? null;

  // Base ~1"/week, scaled by heat (evapotranspiration demand).
  let target =
    high == null
      ? 1.0
      : high >= 95
        ? 1.8
        : high >= 88
          ? 1.5
          : high >= 80
            ? 1.2
            : high >= 70
              ? 1.0
              : high >= 60
                ? 0.8
                : 0.6;
  // Dry air pulls more moisture from soil and leaves; humid air, less.
  if (hum != null) target += hum < 40 ? 0.2 : hum < 55 ? 0.1 : hum > 80 ? -0.15 : 0;
  target = Math.max(0.5, Math.min(2.2, Math.round(target * 10) / 10));
  if (opts.dormant) target = Math.round(target * RESTING_SHARE * 10) / 10;

  const deficit = round2(Math.max(0, target - rain7));
  const heatNote = high != null ? `, highs near ${Math.round(high)}°` : '';
  const rainNote = `${rain7.toFixed(2)}″ of rain in the last 7 days`;

  if (rain7 >= target * 1.4) {
    return {
      status: 'wet',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'Skip watering',
      detail: `${rainNote}, well above the ~${target.toFixed(1)}″ this week calls for${heatNote}.`,
    };
  }
  if (opts.dormant && (high == null || high < RESTING_WARM_F)) {
    // Resting plants in cool weather barely draw on the soil: a soft note at most.
    return {
      status: 'rest',
      rain7,
      targetWeekly: target,
      deficit,
      headline:
        deficit > target * 0.6
          ? 'Check the soil before winter'
          : 'No watering needed while the garden rests',
      detail:
        deficit > target * 0.6
          ? `Most of the garden is dormant${heatNote}; ${rainNote}. If the soil is dry a few inches down, one deep watering will carry the roots into winter.`
          : `Most of the garden is dormant${heatNote}; ${rainNote} covers its ~${target.toFixed(1)}″ a week.`,
    };
  }

  const hot = high != null && high >= 88;
  if (deficit <= 0.2)
    return {
      status: 'ok',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'No watering needed',
      detail: `${rainNote} covers about ${target.toFixed(1)}″ of need${heatNote}.`,
    };
  // A resting garden in heat is never told to water now: the soft call at most.
  if (deficit <= target * 0.6 || opts.dormant)
    return {
      status: 'water-soon',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'Water in a day or two',
      detail: `${rainNote} vs ~${target.toFixed(1)}″ needed${heatNote}: one deep soak covers it.`,
    };
  return {
    status: 'soak',
    rain7,
    targetWeekly: target,
    deficit,
    headline: hot ? 'Water now, and again in a few days' : 'Water now',
    detail: `Only ${rainNote} vs ~${target.toFixed(1)}″ needed${heatNote}.`,
  };
}

export const WATERING_META: Record<WateringStatus, { badge: string; bar: string }> = {
  soak: { badge: 'bg-rose-100 text-rose-700 ring-rose-300/60', bar: 'bg-rose-400' },
  'water-soon': { badge: 'bg-amber-100 text-amber-700 ring-amber-300/60', bar: 'bg-amber-400' },
  ok: { badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60', bar: 'bg-emerald-400' },
  wet: { badge: 'bg-sky-100 text-sky-700 ring-sky-300/60', bar: 'bg-sky-400' },
  rest: { badge: 'bg-muted/60 text-foreground/80 ring-border/60', bar: 'bg-muted' },
};
