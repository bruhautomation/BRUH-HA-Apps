'use client';

import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/db/client';
import { Crosshair, Shield, Timer, Trash2, ArrowRight } from 'lucide-react';
import { useState } from 'react';
import Link from 'next/link';
import { productLabel } from '@/lib/product-label';

interface QueuedSpray {
  id: number;
  notes: string | null;
  createdAt: string;
  products: Array<{
    brand: string;
    rateApplied: number | null;
    rateUnit: string;
    ingredients: Array<{ name: string }>;
  }>;
  crops: string[];
  coverageDays: Array<{ brand: string; days: number }>;
  phiImpacts: Array<{ cropName: string; productName: string; phiDays: number } | null>;
}

export function QueuedSprayCard({ spray }: { spray: QueuedSpray }) {
  const router = useRouter();
  const [removing, setRemoving] = useState(false);
  const [nowMs] = useState(() => Date.now());

  async function removeQueued() {
    setRemoving(true);
    const supabase = createClient();
    await supabase.from('queued_sprays').delete().eq('id', spray.id);
    setRemoving(false);
    router.refresh();
  }

  const validPhis = spray.phiImpacts.filter(Boolean) as Array<{
    cropName: string;
    productName: string;
    phiDays: number;
  }>;
  const maxCoverage = Math.max(...spray.coverageDays.map((c) => c.days), 0);
  const nextSprayDate = new Date(nowMs + maxCoverage * 86400000);

  return (
    <div className="relative rounded-xl bg-gradient-to-br from-emerald-50 via-emerald-50/80 to-emerald-50/60 p-4 ring-1 ring-emerald-300/60 shadow-md overflow-hidden">
      <div className="absolute -top-6 -right-6 w-20 h-20 rounded-full bg-emerald-200/15 blur-2xl" />

      <div className="relative">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-emerald-100 ring-1 ring-emerald-200/50">
              <Crosshair className="w-3.5 h-3.5 text-emerald-700" />
            </div>
            <div>
              <p className="text-xs font-semibold text-emerald-800">Queued Spray</p>
              <p className="text-[10px] text-emerald-700/70">{spray.crops.join(', ')}</p>
            </div>
          </div>
          <button
            onClick={removeQueued}
            disabled={removing}
            className="text-muted-foreground/50 hover:text-terra-500 transition-colors p-1"
            title="Remove from queue"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Products */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {spray.products.map((p, i) => (
            <span
              key={i}
              className="rounded-full text-[11px] font-medium px-2 py-0.5 bg-leaf-tint text-leaf-dk ring-1 ring-leaf-lt"
            >
              {productLabel(p.brand, p.ingredients)}
              {p.rateApplied ? ` ${p.rateApplied} ${p.rateUnit}` : ''}
            </span>
          ))}
        </div>

        {/* Impact summary */}
        <div className="space-y-1.5 text-sm mb-3">
          <div className="flex items-start gap-2">
            <Shield className="w-3.5 h-3.5 text-emerald-600 mt-0.5 shrink-0" />
            <div className="text-xs">
              <p className="text-emerald-800">
                Coverage: <strong>{maxCoverage} days</strong>
                <span className="text-emerald-600/70 ml-1">
                  (next spray ~
                  {nextSprayDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })})
                </span>
              </p>
              {spray.coverageDays.length > 1 && (
                <div className="mt-0.5 space-y-0.5">
                  {spray.coverageDays.map((c) => (
                    <p key={c.brand} className="text-emerald-700/70">
                      {c.brand}: {c.days}d
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
          {validPhis.length > 0 && (
            <div className="flex items-start gap-2">
              <Timer className="w-3.5 h-3.5 text-orange-500 mt-0.5 shrink-0" />
              <div className="text-xs text-foreground/70 space-y-0.5">
                {validPhis.map((p, i) => (
                  <p key={i}>
                    {p.cropName}: {p.phiDays}d PHI ({p.productName})
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Action — go to mix page to log */}
        <Link
          href="/tank"
          className="flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 text-white px-3 py-2.5 text-xs font-medium transition-colors hover:bg-emerald-700"
        >
          Log Spray
          <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}
