import type { HourlyForecast, DailyForecast, SprayRating } from '@/lib/weather';
import { sprayHours, type SprayHour } from '@/lib/weather';

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

/** Wind-aware 3-day spray window: hourly bands from 6a to 8p, rated by the same
 *  rule as the next opening (`sprayHours`). Hours already over and dark hours
 *  are greyed, and the highlighted block is the longest good stretch still
 *  ahead, so the first green cell is the opening the banner names. */
export function SprayWindow3Day({
  hourly,
  daily,
  now = new Date(),
}: {
  hourly: HourlyForecast[];
  daily: DailyForecast[];
  now?: Date;
}) {
  // Group the 6a–8p hours by date, keep the first 3 days.
  const byDate = new Map<string, SprayHour[]>();
  for (const r of sprayHours(hourly, now)) {
    if (r.hour < 6 || r.hour > 20) continue;
    if (!byDate.has(r.date)) byDate.set(r.date, []);
    byDate.get(r.date)!.push(r);
  }
  const dates = [...byDate.keys()].sort().slice(0, 3);
  const dailyByDate = new Map(daily.map((d) => [d.date, d]));
  const anyOff = dates.some((d) => byDate.get(d)!.some((h) => h.over || h.dark));

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
        {anyOff && (
          <span>
            <i className="sw3-off" />
            Past or dark
          </span>
        )}
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
                const off = h.over || h.dark;
                const inBest = best != null && h.hour >= best.start && h.hour <= best.end;
                const note = h.over ? 'past' : h.dark ? 'dark' : h.rating.toLowerCase();
                return (
                  <div
                    key={h.hour}
                    className={`sw3-cell${off ? ' sw3-off' : ''}${inBest ? ' best' : ''}`}
                    style={
                      off ? undefined : { background: COLOR[h.rating], opacity: OPACITY[h.rating] }
                    }
                    title={`${fmtHour(h.hour)} · ${Math.round(h.temp)}° · ${Math.round(h.wind)} mph · ${note}`}
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

/** Longest contiguous run of good hours still ahead (not over, not dark). */
function bestWindow(hours: SprayHour[]): { start: number; end: number } | null {
  let best: { start: number; end: number } | null = null;
  let cur: { start: number; end: number } | null = null;
  for (const h of hours) {
    const good = h.ok && !h.over;
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
