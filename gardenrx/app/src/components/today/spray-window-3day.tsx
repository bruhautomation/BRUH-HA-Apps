import type { HourlyForecast, DailyForecast, SprayRating } from '@/lib/weather';
import { rateSprayWindow } from '@/lib/weather';

const COLOR: Record<SprayRating, string> = {
  EXCELLENT: 'var(--leaf)',
  GOOD: 'var(--leaf)',
  FAIR: 'var(--warn)',
  POOR: 'var(--danger)',
};
const OPACITY: Record<SprayRating, number> = {
  EXCELLENT: 1,
  GOOD: 0.68,
  FAIR: 0.85,
  POOR: 0.7,
};

type RatedHour = { hour: number; rating: SprayRating; temp: number; wind: number };

/** Wind-aware 3-day spray window — daytime (6a–8p) hourly bands, best contiguous
 *  good/excellent block highlighted. Uses the repo's rateSprayWindow. */
export function SprayWindow3Day({
  hourly,
  daily,
}: {
  hourly: HourlyForecast[];
  daily: DailyForecast[];
}) {
  // Rate every hour (hours-until-rain measured forward across the full series).
  const rated = hourly.map((h, i) => {
    let hoursUntilRain: number | null = null;
    for (let j = i + 1; j < hourly.length; j++) {
      if (hourly[j].precipitation > 0.01) {
        hoursUntilRain = j - i;
        break;
      }
    }
    return {
      date: h.time.slice(0, 10),
      hour: new Date(h.time).getHours(),
      rating: rateSprayWindow(h.temp, h.windSpeed, hoursUntilRain),
      temp: h.temp,
      wind: h.windSpeed,
    };
  });

  // Group daytime hours by date, keep first 3 days.
  const byDate = new Map<string, RatedHour[]>();
  for (const r of rated) {
    if (r.hour < 6 || r.hour > 20) continue;
    if (!byDate.has(r.date)) byDate.set(r.date, []);
    byDate.get(r.date)!.push({ hour: r.hour, rating: r.rating, temp: r.temp, wind: r.wind });
  }
  const dates = [...byDate.keys()].sort().slice(0, 3);
  const dailyByDate = new Map(daily.map((d) => [d.date, d]));

  const axis = ['6a', '9a', '12p', '3p', '6p', '8p'];

  return (
    <div className="sw3">
      <div className="sw3-legend">
        <span>
          <i style={{ background: 'var(--leaf)' }} />
          Good to spray
        </span>
        <span>
          <i style={{ background: 'var(--warn)' }} />
          Caution
        </span>
        <span>
          <i style={{ background: 'var(--danger)' }} />
          Hold
        </span>
      </div>
      {dates.map((date, i) => {
        const hours = byDate.get(date)!;
        const best = bestWindow(hours);
        const d = dailyByDate.get(date);
        const hi = d ? Math.round(d.tempHigh) : Math.round(Math.max(...hours.map((h) => h.temp)));
        const lo = d ? Math.round(d.tempLow) : Math.round(Math.min(...hours.map((h) => h.temp)));
        return (
          <div className="sw3-day" key={date}>
            <div className="sw3-meta">
              <div className="sw3-dow">
                {i === 0
                  ? 'Today'
                  : new Date(date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })}
              </div>
              <div className="sw3-temp">
                {hi}°<span>/{lo}°</span>
              </div>
            </div>
            <div className="sw3-band">
              {hours.map((h) => {
                const inBest = best != null && h.hour >= best.start && h.hour <= best.end;
                return (
                  <div
                    key={h.hour}
                    className={`sw3-cell${inBest ? ' best' : ''}`}
                    style={{ background: COLOR[h.rating], opacity: OPACITY[h.rating] }}
                    title={`${fmtHour(h.hour)} · ${Math.round(h.temp)}° · ${Math.round(h.wind)} mph · ${h.rating.toLowerCase()}`}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
      <div className="sw3-axis">
        <div className="sw3-meta" />
        <div className="sw3-ticks">
          {axis.map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Longest contiguous run of GOOD/EXCELLENT daytime hours. */
function bestWindow(hours: RatedHour[]): { start: number; end: number } | null {
  let best: { start: number; end: number } | null = null;
  let cur: { start: number; end: number } | null = null;
  for (const h of hours) {
    const good = h.rating === 'GOOD' || h.rating === 'EXCELLENT';
    if (good) {
      cur = cur === null ? { start: h.hour, end: h.hour } : { start: cur.start, end: h.hour };
      if (best === null || cur.end - cur.start > best.end - best.start) best = { ...cur };
    } else {
      cur = null;
    }
  }
  return best;
}

function fmtHour(h: number): string {
  return h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`;
}
