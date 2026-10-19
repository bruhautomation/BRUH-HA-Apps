'use client';

import { useState } from 'react';
import { calculateDose } from '@/lib/dose';
import { useSprayerGallons } from '@/lib/use-sprayer-gallons';

export function DoseCalculator({
  rateMin,
  rateMax,
  rateUnit,
}: {
  rateMin: number | null;
  rateMax: number | null;
  rateUnit: string;
}) {
  const [defaultGallons] = useSprayerGallons();
  const [rate, setRate] = useState(rateMax ?? rateMin ?? 1);
  // Derive gallons from the user's explicit override (if any) or fall back to
  // the saved preference — no effect required.
  const [tankOverride, setTankOverride] = useState<number | null>(null);
  const gallons = tankOverride ?? defaultGallons;
  const setGallons = setTankOverride;
  const [customTank, setCustomTank] = useState(false);
  const [customTankValue, setCustomTankValue] = useState('');

  if (rateMin == null && rateMax == null) return null;

  const dose = calculateDose(rate, rateUnit, gallons);

  const tankSizes = [1, 2, 4] as const;

  return (
    <div className="mt-3 rounded-lg bg-parchment-100/50 p-3 ring-1 ring-border/40 space-y-2.5">
      <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground/60">
        Dose Calculator
      </p>

      {/* Rate slider */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label className="text-xs text-muted-foreground">Rate</label>
          <span className="font-mono text-xs tabular-nums">
            {rate.toFixed(2)} {rateUnit}
          </span>
        </div>
        <input
          type="range"
          min={rateMin ?? 0}
          max={rateMax ?? rate * 2}
          step={0.05}
          value={rate}
          onChange={(e) => setRate(parseFloat(e.target.value))}
          className="w-full h-1.5 accent-emerald-600"
        />
      </div>

      {/* Tank size pills */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Tank</label>
        <div className="flex items-center gap-1.5">
          {tankSizes.map((size) => (
            <button
              key={size}
              type="button"
              onClick={() => {
                setGallons(size);
                setCustomTank(false);
                setCustomTankValue('');
              }}
              className={`rounded-full px-3 py-0.5 text-xs font-medium transition-colors ${
                gallons === size && !customTank
                  ? 'bg-emerald-600 text-white'
                  : 'bg-card text-muted-foreground ring-1 ring-border/40 hover:ring-emerald-300'
              }`}
            >
              {size} gal
            </button>
          ))}
          <div
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
              customTank
                ? 'bg-emerald-600 text-white ring-1 ring-emerald-600'
                : 'bg-card text-muted-foreground ring-1 ring-border/40'
            }`}
          >
            <input
              type="number"
              min={0.1}
              step="any"
              placeholder="Custom"
              value={customTankValue}
              onChange={(e) => {
                const val = e.target.value;
                setCustomTankValue(val);
                const num = parseFloat(val);
                if (!isNaN(num) && num > 0) {
                  setCustomTank(true);
                  setGallons(num);
                }
              }}
              onFocus={() => {
                if (customTankValue) {
                  setCustomTank(true);
                }
              }}
              className="w-14 bg-transparent outline-none text-center placeholder:text-muted-foreground/50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
            <span className={customTank ? 'text-white/70' : 'text-muted-foreground/50'}>gal</span>
          </div>
        </div>
      </div>

      {/* Dose result */}
      <div className="rounded-lg bg-card p-2.5 ring-1 ring-emerald-200/40">
        <p className="text-xs text-muted-foreground">Add</p>
        <p className="font-heading font-semibold text-emerald-800">{dose.bestDisplay}</p>
        <p className="text-xs text-muted-foreground">
          {dose.mL} mL &middot; {dose.tbsp} tbsp
        </p>
      </div>
    </div>
  );
}
