'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Input } from '@/components/ui/input';
import { useTransition, useRef } from 'react';
import { Search } from 'lucide-react';
import { typeFilterStyles } from '@/lib/theme';
import { CATEGORY_ORDER } from '@/lib/crop-category';

const typeKeys = Object.keys(typeFilterStyles);

export function ProductSearch({
  crops,
}: {
  /** The actual crops in this garden — used as filter buttons, grouped by zone. */
  crops: { id: number; name: string; category: string }[];
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const qTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function updateParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    startTransition(() => {
      router.push(`/products?${params.toString()}`);
    });
  }

  // Debounced + replace (no per-keystroke navigation / history spam).
  function updateQuery(value: string) {
    if (qTimer.current) clearTimeout(qTimer.current);
    qTimer.current = setTimeout(() => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set('q', value);
      else params.delete('q');
      startTransition(() => {
        router.replace(`/products?${params.toString()}`);
      });
    }, 300);
  }

  const activeCrop = searchParams.get('crop');

  return (
    <div className="space-y-3 sticky top-0 z-10 bg-background/95 backdrop-blur-sm pb-3 -mx-4 px-4 pt-1">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground/60" />
        <Input
          placeholder="Search by name or ingredient..."
          defaultValue={searchParams.get('q') ?? ''}
          onChange={(e) => updateQuery(e.target.value)}
          className="pl-9 bg-card shadow-sm ring-1 ring-black/[0.04] border-0 h-10 rounded-xl"
        />
      </div>

      {/* Type pills */}
      <div className="flex gap-1.5 flex-wrap">
        {typeKeys.map((type) => {
          const isActive = searchParams.get('type') === type;
          const style = typeFilterStyles[type];
          return (
            <button
              key={type}
              onClick={() => updateParam('type', isActive ? '' : type)}
              className={`text-[11px] font-medium tracking-wide px-2.5 py-1 rounded-full transition-all duration-200 ${
                isActive ? style.active : style.inactive
              }`}
            >
              {style.label}
            </button>
          );
        })}
      </div>

      {/* Crop filter buttons — the actual crops in this garden. Active agents are
          universal across a category, so these filter to everything labeled for
          that crop's group. */}
      {crops.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium tracking-widest uppercase text-muted-foreground/60">
            Labeled for my crops
          </p>
          {CATEGORY_ORDER.filter((cat) => crops.some((c) => c.category === cat)).map((cat) => (
            <div key={cat}>
              <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/45">
                {cat}
              </p>
              <div className="flex gap-1.5 flex-wrap">
                {crops
                  .filter((c) => c.category === cat)
                  .map((c) => {
                    const isActive = activeCrop === String(c.id);
                    return (
                      <button
                        key={c.id}
                        onClick={() => updateParam('crop', isActive ? '' : String(c.id))}
                        className={`text-[11px] font-medium tracking-wide px-2.5 py-1 rounded-full transition-all duration-200 ${
                          isActive
                            ? 'bg-emerald-700 text-white shadow-sm'
                            : 'bg-card text-foreground/70 ring-1 ring-border/60 hover:ring-emerald-300 hover:bg-emerald-50/40'
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
      )}
    </div>
  );
}
