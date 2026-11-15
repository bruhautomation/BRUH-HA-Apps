'use client';

import { useState } from 'react';
import type { HourlyForecast, SprayRating } from '@/lib/weather';
import { rateSprayWindow } from '@/lib/weather';
import { ratingColors, ratingColorsLight } from '@/lib/theme';

export function SprayWindowTimeline({
  hourly,
  compact = false,
}: {
  hourly: HourlyForecast[];
  compact?: boolean;
}) {
  const [tooltip, setTooltip] = useState<{
    hour: number;
    rating: SprayRating;
    temp: number;
    wind: number;
    dayLabel: string;
  } | null>(null);

  if (hourly.length === 0) return null;

  const now = new Date();
  const currentHour = now.getHours();
  const currentDayStr = now.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });

  // Group hours by day
  const days = new Map<
    string,
    Array<{ hour: number; rating: SprayRating; temp: number; wind: number; isCurrent: boolean }>
  >();

  for (let i = 0; i < Math.min(72, hourly.length); i++) {
    const h = hourly[i];
    const d = new Date(h.time);
    const hour = d.getHours();
    if (hour < 5) continue;

    const dayKey = d.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });

    let hoursUntilRain: number | null = null;
    for (let j = i + 1; j < hourly.length; j++) {
      if (hourly[j].precipitation > 0.01) {
        hoursUntilRain = j - i;
        break;
      }
    }

    const rating = rateSprayWindow(h.temp, h.windSpeed, hoursUntilRain);
    const isCurrent = dayKey === currentDayStr && hour === currentHour;
    const list = days.get(dayKey) ?? [];
    list.push({ hour, rating, temp: h.temp, wind: h.windSpeed, isCurrent });
    days.set(dayKey, list);
  }

  return (
    <div className="space-y-2">
      {Array.from(days.entries()).map(([dayLabel, hours], dayIdx) => {
        const bestRating = hours.reduce<SprayRating>((best, h) => {
          const order: Record<SprayRating, number> = { EXCELLENT: 0, GOOD: 1, FAIR: 2, POOR: 3 };
          return order[h.rating] < order[best] ? h.rating : best;
        }, 'POOR');

        return (
          <div key={dayLabel}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium text-foreground/70">
                {dayLabel}
                {dayIdx === 0 && <span className="text-emerald-600 ml-1 text-[9px]">Today</span>}
              </span>
              <span
                className={`text-[10px] font-semibold px-1.5 py-0 rounded-full ${ratingColorsLight[bestRating]}`}
              >
                {bestRating}
              </span>
            </div>

            <div className="flex gap-px rounded-md overflow-hidden h-4 relative">
              {hours.map((h, i) => (
                <div
                  key={i}
                  className={`flex-1 ${ratingColors[h.rating]} transition-all relative cursor-pointer hover:opacity-80`}
                  onClick={() =>
                    setTooltip(
                      tooltip?.hour === h.hour && tooltip?.dayLabel === dayLabel
                        ? null
                        : { ...h, dayLabel }
                    )
                  }
                >
                  {/* Current time marker */}
                  {h.isCurrent && (
                    <div className="absolute inset-x-0 top-0 bottom-0 ring-2 ring-foreground/80 rounded-sm z-10">
                      <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-0 h-0 border-l-[3px] border-r-[3px] border-t-[3px] border-l-transparent border-r-transparent border-t-foreground/80" />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Tooltip for selected hour */}
            {tooltip && tooltip.dayLabel === dayLabel && (
              <div className="mt-1 rounded-lg bg-card px-2.5 py-1.5 ring-1 ring-black/[0.06] shadow-sm text-[11px]">
                <span className="font-medium">
                  {tooltip.hour === 0 ? '12' : tooltip.hour > 12 ? tooltip.hour - 12 : tooltip.hour}
                  :00 {tooltip.hour >= 12 ? 'PM' : 'AM'}
                </span>
                <span
                  className={`ml-2 px-1.5 py-0 rounded-full text-[9px] font-semibold ${ratingColorsLight[tooltip.rating]}`}
                >
                  {tooltip.rating}
                </span>
                <span className="text-muted-foreground ml-2">
                  {Math.round(tooltip.temp)}°F · Wind {Math.round(tooltip.wind)} mph
                </span>
              </div>
            )}

            {!compact && (
              <div className="flex justify-between mt-0.5">
                <span className="text-[9px] text-muted-foreground/70">5am</span>
                <span className="text-[9px] text-muted-foreground/70">noon</span>
                <span className="text-[9px] text-muted-foreground/70">12am</span>
              </div>
            )}
          </div>
        );
      })}

      {/* Legend */}
      <div className="flex items-center gap-3 pt-1">
        {(['EXCELLENT', 'GOOD', 'FAIR', 'POOR'] as const).map((r) => (
          <div key={r} className="flex items-center gap-1">
            <div className={`w-2 h-2 rounded-sm ${ratingColors[r]}`} />
            <span className="text-[9px] text-muted-foreground capitalize">{r.toLowerCase()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
