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

export const DROUGHT_META: Record<
  DroughtStatus,
  { label: string; badge: string; bar: string; note: string }
> = {
  drought: {
    label: 'Drought',
    badge: 'bg-rose-100 text-rose-700 ring-rose-300/60',
    bar: 'bg-rose-400',
    note: 'Well below the ~1 in/week target — irrigate.',
  },
  dry: {
    label: 'Dry',
    badge: 'bg-amber-100 text-amber-700 ring-amber-300/60',
    bar: 'bg-amber-400',
    note: 'Below normal — keep an eye on soil moisture.',
  },
  adequate: {
    label: 'Adequate',
    badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60',
    bar: 'bg-emerald-400',
    note: 'Near the ~1 in/week target.',
  },
  wet: {
    label: 'Wet',
    badge: 'bg-sky-100 text-sky-700 ring-sky-300/60',
    bar: 'bg-sky-400',
    note: 'Above normal — you can hold off watering.',
  },
};

// ── Watering recommendation ──

export type WateringStatus = 'soak' | 'water-soon' | 'ok' | 'wet';

export interface WateringAdvice {
  status: WateringStatus;
  rain7: number; // last 7 days of rain, inches
  targetWeekly: number; // evapotranspiration-adjusted weekly need, inches
  deficit: number; // shortfall vs target, inches (>= 0)
  headline: string; // short call to action
  detail: string; // one-line explanation
}

/**
 * Should you water this week? Plants want a deep soak roughly weekly — twice a
 * week in real heat — so we compare the *last 7 days* of rain against a weekly
 * target that scales with evapotranspiration demand (hotter and drier air pull
 * more moisture) rather than a flat "1 inch/week". A multi-day deficit means
 * it's time to irrigate, even if the 30-day total looks fine.
 */
export function wateringAdvice(
  daily: DailyRain[],
  opts: { avgHighF?: number | null; humidityPct?: number | null } = {}
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

  const deficit = round2(Math.max(0, target - rain7));
  const hot = high != null && high >= 88;
  const cadence = hot
    ? 'a deep soak ~twice this week'
    : high != null && high < 65
      ? 'a soak every week or two is plenty'
      : 'a deep soak about once a week';

  let status: WateringStatus;
  let headline: string;
  if (rain7 >= target * 1.4) {
    status = 'wet';
    headline = 'Skip watering';
  } else if (deficit <= 0.2) {
    status = 'ok';
    headline = 'No watering needed';
  } else if (deficit <= target * 0.6) {
    status = 'water-soon';
    headline = 'Water in a day or two';
  } else {
    status = 'soak';
    headline = 'Water now';
  }

  const heatNote = high != null ? `, highs near ${Math.round(high)}°` : '';
  const detail =
    status === 'wet'
      ? `${rain7.toFixed(2)}″ of rain in the last 7 days — well above the ~${target.toFixed(1)}″ this week's weather calls for${heatNote}.`
      : status === 'ok'
        ? `${rain7.toFixed(2)}″ of rain in the last 7 days covers about ${target.toFixed(1)}″ of need${heatNote}.`
        : `Only ${rain7.toFixed(2)}″ of rain in the last 7 days vs ~${target.toFixed(1)}″ needed${heatNote}. Aim for ${cadence}.`;

  return { status, rain7, targetWeekly: target, deficit, headline, detail };
}

export const WATERING_META: Record<WateringStatus, { badge: string; bar: string }> = {
  soak: { badge: 'bg-rose-100 text-rose-700 ring-rose-300/60', bar: 'bg-rose-400' },
  'water-soon': { badge: 'bg-amber-100 text-amber-700 ring-amber-300/60', bar: 'bg-amber-400' },
  ok: { badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60', bar: 'bg-emerald-400' },
  wet: { badge: 'bg-sky-100 text-sky-700 ring-sky-300/60', bar: 'bg-sky-400' },
};
