import { CloudRain, Droplets } from 'lucide-react';
import type { DailyRain, RainSummary } from '@/lib/rainfall';
import { DROUGHT_META, WATERING_META, wateringAdvice } from '@/lib/rainfall';

/** Home-page rainfall card: a watering call-to-action (rain vs. evapotranspiration
 *  demand), 30-day daily bars, week/month totals, drought status. */
export function RainTracker({
  daily,
  summary,
  avgHighF,
  humidityPct,
}: {
  daily: DailyRain[];
  summary: RainSummary;
  avgHighF?: number | null;
  humidityPct?: number | null;
}) {
  if (daily.length === 0) return null;
  const meta = DROUGHT_META[summary.status];
  const advice = wateringAdvice(daily, { avgHighF, humidityPct });
  const adviceMeta = WATERING_META[advice.status];
  const scaleMax = Math.max(0.25, ...daily.map((d) => d.inches));
  const fmtDay = (key: string) =>
    new Date(`${key}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const midIdx = Math.floor(daily.length / 2);

  return (
    <section className="rounded-2xl bg-card ring-1 ring-black/[0.05] shadow-sm px-4 py-3">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5">
          <CloudRain className="w-4 h-4 text-sky-500" />
          <h2 className="text-[10px] font-semibold tracking-[0.18em] uppercase text-foreground/60">
            Rainfall
          </h2>
        </div>
        <span
          className={`text-[10px] font-semibold tracking-wide uppercase px-2 py-0.5 rounded-full ring-1 ${meta.badge}`}
        >
          {meta.label}
        </span>
      </div>

      {/* watering call-to-action — rain vs. evapotranspiration demand */}
      <div
        className={`mb-3 flex items-start gap-2.5 rounded-lg px-3 py-2 ring-1 ${adviceMeta.badge}`}
      >
        <Droplets className="w-4 h-4 mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-[13px] font-semibold leading-tight">{advice.headline}</p>
          <p className="text-[11px] leading-snug mt-0.5 opacity-90">{advice.detail}</p>
        </div>
      </div>

      {/* week / month totals */}
      <div className="flex items-baseline gap-6 mb-3">
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-heading font-semibold tracking-tight text-foreground tabular-nums">
            {summary.week.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">in · this week</span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-heading font-semibold tracking-tight text-foreground tabular-nums">
            {summary.month.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">in · 30 days</span>
        </div>
        <div className="ml-auto text-right text-[11px] text-muted-foreground/70">
          {summary.daysSinceRain === null
            ? 'no rain logged'
            : summary.daysSinceRain === 0
              ? 'rain today'
              : `${summary.daysSinceRain}d since rain`}
        </div>
      </div>

      {/* days vs rainfall — 30 daily bars */}
      <div className="flex items-end gap-px h-16">
        {daily.map((d) => {
          const pct = d.inches > 0 ? Math.max(6, Math.round((d.inches / scaleMax) * 100)) : 0;
          return (
            <div
              key={d.date}
              className="flex-1 h-full flex items-end"
              title={`${fmtDay(d.date)}: ${d.inches.toFixed(2)}″`}
            >
              <div
                className={`w-full rounded-t-sm ${d.inches > 0 ? 'bg-sky-400 hover:bg-sky-500 transition-colors' : 'bg-muted/40'}`}
                style={{ height: d.inches > 0 ? `${pct}%` : '2px' }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1 text-[9px] text-muted-foreground/60">
        <span>{fmtDay(daily[0].date)}</span>
        <span>{fmtDay(daily[midIdx].date)}</span>
        <span>Today</span>
      </div>

      <p className="text-[10px] text-muted-foreground/60 mt-2">
        {meta.note}
        {summary.wettest && summary.wettest.inches > 0
          ? ` Wettest day: ${summary.wettest.inches.toFixed(2)}″ on ${fmtDay(summary.wettest.date)}.`
          : ''}
      </p>
    </section>
  );
}
