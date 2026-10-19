'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronDown, TriangleAlert, Check, Sprout } from 'lucide-react';
import { CropAvatar } from '@/components/crop-glyph';

export type StatusCrop = { id: number; name: string; group: string | null; note: string };

const CARDS = [
  {
    key: 'phi',
    label: 'Do not harvest',
    color: 'var(--danger)',
    Icon: TriangleAlert,
    sub: 'Under a pre-harvest interval',
  },
  {
    key: 'ready',
    label: 'Ready to pick',
    color: 'var(--leaf)',
    Icon: Check,
    sub: 'In their harvest window',
  },
  {
    key: 'dev',
    label: 'Still developing',
    color: 'var(--ink-3)',
    Icon: Sprout,
    sub: 'Not in window yet',
  },
] as const;

export function HarvestStatusCards({
  doNotHarvest,
  ready,
  developing,
}: {
  doNotHarvest: StatusCrop[];
  ready: StatusCrop[];
  developing: StatusCrop[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const lists: Record<string, StatusCrop[]> = { phi: doNotHarvest, ready, developing };
  if (doNotHarvest.length + ready.length + developing.length === 0) return null;

  return (
    <div className="mb-[var(--gap)] grid gap-[var(--gap)] sm:grid-cols-3">
      {CARDS.map(({ key, label, color, Icon, sub }) => {
        const list = lists[key === 'dev' ? 'developing' : key];
        const isOpen = open === key;
        return (
          <div key={key}>
            <button
              className={`card accent-card hv-card${isOpen ? ' open' : ''}`}
              style={{ ['--ac' as string]: color }}
              onClick={() => setOpen(isOpen ? null : key)}
              aria-expanded={isOpen}
            >
              <div className="hv-num" style={{ color: list.length ? color : 'var(--ink-3)' }}>
                {list.length}
              </div>
              <div className="hv-body">
                <div className="hv-label">{label}</div>
                <div className="hv-sub">{sub}</div>
              </div>
              <Icon
                className="size-4 shrink-0 text-ink-3"
                style={{ color: list.length ? color : undefined }}
              />
              <ChevronDown
                className={`size-4 shrink-0 text-ink-3 transition-transform${isOpen ? ' rotate-180' : ''}`}
              />
            </button>
            {isOpen && (
              <div className="hv-expand card panel">
                {list.length === 0 ? (
                  <div className="py-2 text-center text-[13px] text-ink-3">No crops here.</div>
                ) : (
                  <div className="row-list !border-0 !shadow-none">
                    {list.map((c) => (
                      <Link key={c.id} href={`/crops/${c.id}`} className="row-item">
                        <CropAvatar name={c.name} group={c.group} size={32} />
                        <div className="ri-body">
                          <div className="ri-name">{c.name}</div>
                          <div className="text-[11px] text-ink-3">{c.note}</div>
                        </div>
                        <ChevronDown className="size-4 shrink-0 -rotate-90 text-ink-3" />
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
