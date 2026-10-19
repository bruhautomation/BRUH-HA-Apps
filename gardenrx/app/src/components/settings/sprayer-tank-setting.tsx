'use client';

import { FlaskConical } from 'lucide-react';
import { useSprayerGallons } from '@/lib/use-sprayer-gallons';

/** Sprayer tank size (gallons). Persisted to localStorage via useSprayerGallons,
 *  and read by the Plan Mix / crop dose math. Moved here from the Inventory page. */
export function SprayerTankSetting() {
  const [gallons, setGallons] = useSprayerGallons();
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <div className="flex items-center gap-1.5 rounded-xl bg-paper-2 px-3 py-2 ring-1 ring-line">
        <FlaskConical className="size-4 text-ink-3" />
        <span className="text-[13px] text-ink-2">Tank size</span>
        <input
          type="number"
          min={0.25}
          step={0.25}
          value={gallons}
          onChange={(e) => {
            const n = parseFloat(e.target.value);
            if (!isNaN(n) && n > 0) setGallons(n);
          }}
          className="w-16 h-8 text-right text-sm tabular-nums rounded-md ring-1 ring-line bg-card px-2 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
          aria-label="Sprayer tank size in gallons"
        />
        <span className="text-sm text-ink-3">gal</span>
      </div>
      <p className="max-w-sm text-xs text-ink-3">
        Used to size mixes (how much product per tankful) on the Plan&nbsp;Mix and crop pages. It
        doesn&apos;t affect your inventory counts.
      </p>
    </div>
  );
}
