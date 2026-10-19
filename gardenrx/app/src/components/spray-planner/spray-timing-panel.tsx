'use client';

import { useState } from 'react';
import type { CropUse } from '@/lib/database.types';
import type { HourlyForecast } from '@/lib/weather';
import type { MixPlan } from '@/lib/mix-planner';
import { COVERAGE_DEFAULTS } from '@/config/thresholds';
import { Textarea } from '@/components/ui/textarea';
import { SprayWindowTimeline } from '@/components/spray-window-timeline';
import { CloudRain, Shield, Timer, CalendarClock } from 'lucide-react';

export function SprayTimingPanel({
  plan,
  cropUses,
  weatherHourly,
  notes,
  onNotesChange,
  onLog,
  onBack,
  logging,
  hasBlocks,
  defaultVolume,
}: {
  plan: MixPlan;
  cropUses: CropUse[];
  weatherHourly: HourlyForecast[];
  notes: string;
  onNotesChange: (v: string) => void;
  onLog: (volumeGallons: number) => void;
  onBack: () => void;
  logging: boolean;
  hasBlocks: boolean;
  defaultVolume: number;
}) {
  const [nowMs] = useState(() => Date.now());
  const [volumeGallons, setVolumeGallons] = useState<number>(defaultVolume);

  const maxRainFastHours = Math.max(
    ...plan.products.map(
      (p) => p.product.rain_fastness_hours ?? COVERAGE_DEFAULTS.rainFastnessHours
    )
  );

  const hoursUntilRain = weatherHourly.findIndex((h) => h.precipitation > 0.01);
  const rainFastOk = hoursUntilRain === -1 || hoursUntilRain >= maxRainFastHours;

  const coverageDurations = plan.products
    .filter((p) => p.product.cover_spray_interval_days)
    .map((p) => ({
      brand: p.product.brand,
      days: p.product.cover_spray_interval_days!,
      nextSprayDate: new Date(nowMs + p.product.cover_spray_interval_days! * 86400000),
    }));

  const phiImpacts = plan.crops.flatMap((crop) =>
    plan.products.flatMap((mp) => {
      const use = cropUses.find(
        (cu) => cu.product_id === mp.product.id && cu.crop_group_id === crop.crop_group_id
      );
      if (!use?.phi_days || use.phi_days <= 0) return [];
      return [
        {
          cropName: crop.name,
          phiDays: use.phi_days,
          harvestDate: new Date(nowMs + use.phi_days * 86400000),
          productName: mp.product.brand,
        },
      ];
    })
  );

  const mostRestrictivePhi =
    phiImpacts.length > 0 ? Math.max(...phiImpacts.map((p) => p.phiDays)) : 0;

  return (
    <div className="pt-3 border-t border-border/40 space-y-4">
      {/* Spray windows — no inner card, just the chart */}
      {weatherHourly.length > 0 && (
        <div>
          <div className="flex items-baseline gap-2 mb-2">
            <CalendarClock className="w-3.5 h-3.5 text-emerald-600 shrink-0 self-center" />
            <h3 className="text-[11px] font-semibold tracking-[0.18em] uppercase text-foreground/70">
              Next 72 hours
            </h3>
          </div>
          <SprayWindowTimeline hourly={weatherHourly} />
        </div>
      )}

      {/* Single check list — rain-fast / coverage / harvest — no per-item cards */}
      <dl className="space-y-2.5 text-[12px]">
        <div className="flex items-baseline gap-2">
          <CloudRain
            className={`w-3.5 h-3.5 shrink-0 self-center ${rainFastOk ? 'text-emerald-600' : 'text-amber-600'}`}
          />
          <dt className="font-medium text-foreground shrink-0">Rain-fast</dt>
          <dd className="text-muted-foreground leading-snug">
            Need <span className="font-mono tabular-nums text-foreground">{maxRainFastHours}h</span>
            .
            {hoursUntilRain !== -1 ? (
              <>
                {' '}
                Next rain in <span className="font-mono tabular-nums">
                  ~{hoursUntilRain}h
                </span>.{' '}
                <span className={rainFastOk ? 'text-emerald-700' : 'text-amber-700 font-medium'}>
                  {rainFastOk ? 'OK.' : 'Tight — time carefully.'}
                </span>
              </>
            ) : (
              ' No rain in forecast.'
            )}
          </dd>
        </div>

        {coverageDurations.length > 0 && (
          <div className="flex items-baseline gap-2">
            <Shield className="w-3.5 h-3.5 text-emerald-600 shrink-0 self-center" />
            <dt className="font-medium text-foreground shrink-0">Covers</dt>
            <dd className="text-muted-foreground flex-1 leading-snug">
              {coverageDurations.map((c, i) => (
                <span key={c.brand}>
                  {i > 0 && <span className="text-muted-foreground/40"> · </span>}
                  <span className="font-medium text-foreground">{c.days}d</span>{' '}
                  {c.brand.split(' ').slice(0, 2).join(' ')}
                </span>
              ))}
            </dd>
          </div>
        )}

        {phiImpacts.length > 0 && (
          <div className="flex items-baseline gap-2">
            <Timer className="w-3.5 h-3.5 text-orange-500 shrink-0 self-center" />
            <dt className="font-medium text-foreground shrink-0">Harvest</dt>
            <dd className="text-muted-foreground leading-snug">
              <span className="font-medium text-foreground">{mostRestrictivePhi}d</span> PHI most
              restrictive · harvest-safe after{' '}
              {new Date(
                Math.max(...phiImpacts.map((p) => p.harvestDate.getTime()))
              ).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </dd>
          </div>
        )}
      </dl>

      {/* Session volume — how many gallons of mix will actually be sprayed.
          This gets multiplied by each product's rate to compute real product-used
          and cost numbers. Defaults to the user's sprayer preference. */}
      <div className="flex items-baseline gap-2 text-[12px]">
        <label htmlFor="spray-volume" className="font-medium text-foreground shrink-0">
          Volume
        </label>
        <div className="flex items-center gap-1">
          <input
            id="spray-volume"
            type="number"
            min={0.25}
            step={0.25}
            value={volumeGallons}
            onChange={(e) => setVolumeGallons(Math.max(0.25, parseFloat(e.target.value) || 0.25))}
            className="w-16 h-8 text-right text-sm font-mono tabular-nums rounded-lg ring-1 ring-border/60 bg-card px-2 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
          />
          <span className="text-muted-foreground">gal of mix total</span>
        </div>
      </div>

      <Textarea
        placeholder="Notes (optional)"
        value={notes}
        onChange={(e) => onNotesChange(e.target.value)}
        className="text-sm"
      />

      <div className="flex gap-2">
        <button
          onClick={onBack}
          className="flex-1 rounded-xl h-11 font-medium text-sm transition-colors ring-1 ring-border hover:bg-muted"
        >
          Back
        </button>
        <button
          onClick={() => onLog(volumeGallons)}
          disabled={hasBlocks || logging}
          className="flex-[2] bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-50 rounded-xl h-11 font-medium text-sm transition-colors"
        >
          {logging ? 'Logging...' : 'Log Spray Now'}
        </button>
      </div>
    </div>
  );
}
