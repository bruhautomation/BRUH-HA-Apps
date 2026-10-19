'use client';

import type { Crop, CropGroup } from '@/lib/database.types';
import { cropsByCategory } from '@/lib/crop-category';

/** Multi-select crop chips, grouped under Orchard / Garden / Landscape headers.
 *  Used wherever a spray's crops are chosen. */
export function CropChips({
  crops,
  cropGroups,
  selectedIds,
  onToggle,
}: {
  crops: Crop[];
  cropGroups: CropGroup[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}) {
  const groups = cropsByCategory(crops, cropGroups);
  return (
    <div className="space-y-2">
      {groups.map(({ category, crops }) => (
        <div key={category}>
          <p className="text-[10px] font-semibold tracking-[0.16em] uppercase text-muted-foreground/55 mb-1">
            {category}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {crops.map((c) => {
              const selected = selectedIds.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onToggle(c.id)}
                  className={`text-xs font-medium px-3 py-1.5 rounded-full transition-all ${
                    selected
                      ? 'bg-emerald-600 text-white shadow-sm'
                      : 'bg-card text-muted-foreground ring-1 ring-border/60 hover:ring-border'
                  }`}
                >
                  {c.name}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
