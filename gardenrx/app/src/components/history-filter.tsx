'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { CATEGORY_ORDER, type CropCategory } from '@/lib/crop-category';
import { AREA_STYLE } from '@/lib/area-meta';

/**
 * Filter the spray journal by garden area (Orchard / Garden / Landscape) —
 * the same buckets the Stock page uses. Only areas that actually have sprays
 * are offered.
 */
export function HistoryFilter({ areas }: { areas: CropCategory[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeArea = searchParams.get('area');

  function setArea(area: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (area) params.set('area', area);
    else params.delete('area');
    const qs = params.toString();
    router.push(qs ? `/history?${qs}` : '/history');
  }

  const present = CATEGORY_ORDER.filter((a) => areas.includes(a));
  if (present.length === 0) return null;

  return (
    <div className="flex gap-1.5 flex-wrap mb-4">
      <button
        onClick={() => setArea(null)}
        className={`text-[11px] font-medium px-2.5 py-1 rounded-full ring-1 transition-all ${
          !activeArea
            ? 'bg-foreground text-card ring-foreground shadow-sm'
            : 'bg-card text-muted-foreground ring-border/60 hover:ring-border'
        }`}
      >
        All
      </button>
      {present.map((a) => {
        const Icon = AREA_STYLE[a].icon;
        const active = activeArea === a;
        return (
          <button
            key={a}
            onClick={() => setArea(active ? null : a)}
            className={`inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-full ring-1 transition-all ${
              active
                ? AREA_STYLE[a].chip
                : 'bg-card text-muted-foreground ring-border/60 hover:ring-border'
            }`}
          >
            <Icon className="w-3 h-3" />
            {a}
          </button>
        );
      })}
    </div>
  );
}
