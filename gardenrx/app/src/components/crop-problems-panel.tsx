'use client';

import { useState } from 'react';
import { CROP_PROBLEMS } from '@/lib/crop-problems';
import { Bug, Leaf, AlertTriangle, ChevronDown, FlaskConical, ArrowRight } from 'lucide-react';
import Link from 'next/link';
import { getProblemImagePaths } from '@/lib/image-paths';
import { RefImage } from '@/components/ref-image';

const typeConfig = {
  disease: {
    icon: Leaf,
    color: 'text-violet-600',
    bg: 'bg-violet-50',
    ring: 'ring-violet-200/50',
    label: 'Disease',
  },
  insect: {
    icon: Bug,
    color: 'text-sky-600',
    bg: 'bg-sky-50',
    ring: 'ring-sky-200/50',
    label: 'Insect',
  },
  cultural: {
    icon: AlertTriangle,
    color: 'text-amber-600',
    bg: 'bg-amber-50',
    ring: 'ring-amber-200/50',
    label: 'Cultural',
  },
};

const severityConfig = {
  high: { bg: 'bg-terra-50', text: 'text-terra-700', ring: 'ring-terra-200/60', label: 'High' },
  moderate: {
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    ring: 'ring-amber-200/60',
    label: 'Moderate',
  },
  low: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200/60', label: 'Low' },
};

export function CropProblemsPanel({ cropGroupName }: { cropGroupName: string | null }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filter, setFilter] = useState<'disease' | 'insect'>('disease');

  if (!cropGroupName) return null;

  const problems = CROP_PROBLEMS[cropGroupName];
  if (!problems || problems.length === 0) return null;

  const filtered = problems.filter((p) => p.type === filter);

  return (
    <div>
      <details open className="group/section">
        <summary className="flex items-center justify-between mb-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden select-none">
          <div className="flex items-center gap-2">
            <p className="text-xs font-medium tracking-widest uppercase text-muted-foreground">
              Common Problems
            </p>
            <span className="text-[10px] text-muted-foreground/50">({filtered.length})</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {(['disease', 'insect'] as const).map((f) => (
                <button
                  key={f}
                  onClick={(e) => {
                    e.preventDefault();
                    setFilter(f);
                  }}
                  className={`text-xs font-medium px-2.5 py-0.5 rounded-full transition-colors ${
                    filter === f
                      ? 'bg-emerald-600 text-white'
                      : 'text-muted-foreground/50 hover:text-muted-foreground'
                  }`}
                >
                  {f === 'disease' ? 'Disease' : 'Insects'}
                </button>
              ))}
            </div>
            <ChevronDown className="w-4 h-4 text-muted-foreground/40 transition-transform group-open/section:rotate-180" />
          </div>
        </summary>

        <div className="space-y-1.5">
          {filtered.map((problem) => {
            const isExpanded = expanded === problem.name;
            const tc = typeConfig[problem.type];
            const sc = severityConfig[problem.severity];
            const Icon = tc.icon;

            return (
              <div
                key={problem.name}
                className="rounded-lg bg-card ring-1 ring-black/[0.04] overflow-hidden"
              >
                <button
                  onClick={() => setExpanded(isExpanded ? null : problem.name)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-muted/30 transition-colors"
                >
                  <div
                    className={`flex items-center justify-center w-6 h-6 rounded-md ${tc.bg} shrink-0`}
                  >
                    <Icon className={`w-3 h-3 ${tc.color}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium truncate block">{problem.name}</span>
                  </div>
                  <span
                    className={`rounded-full text-[9px] font-semibold px-1.5 py-0 ring-1 ${sc.bg} ${sc.text} ${sc.ring}`}
                  >
                    {sc.label}
                  </span>
                  <ChevronDown
                    className={`w-3 h-3 text-muted-foreground/60 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  />
                </button>

                {isExpanded && (
                  <div className="px-3 pb-3 space-y-2 text-[11px] leading-relaxed">
                    {/* Reference image */}
                    {cropGroupName && (
                      <RefImage
                        paths={getProblemImagePaths(cropGroupName, problem.name)}
                        alt={`${problem.name} on ${cropGroupName}`}
                        description={`${problem.symptoms}\n\nWhen to watch: ${problem.timing}\n\nTreatment: ${problem.remediation}`}
                        className="w-full h-36 rounded-lg"
                      />
                    )}

                    <p className="text-muted-foreground">{problem.description}</p>

                    <div>
                      <p className="font-semibold text-foreground/80 mb-0.5">Symptoms</p>
                      <p className="text-muted-foreground">{problem.symptoms}</p>
                    </div>

                    <div className="flex gap-4">
                      <div className="flex-1">
                        <p className="font-semibold text-foreground/80 mb-0.5">When to Watch</p>
                        <p className="text-muted-foreground">{problem.timing}</p>
                      </div>
                    </div>

                    <div>
                      <p className="font-semibold text-foreground/80 mb-0.5">
                        Favorable Conditions
                      </p>
                      <p className="text-muted-foreground">{problem.conditions}</p>
                    </div>

                    <div className={`rounded-lg px-2.5 py-2 ${tc.bg} ring-1 ${tc.ring}`}>
                      <p className="font-semibold text-foreground/80 mb-0.5">
                        Treatment & Prevention
                      </p>
                      <p className="text-muted-foreground">{problem.remediation}</p>
                      {problem.products.length > 0 && (
                        <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                          <FlaskConical className="w-3 h-3 text-muted-foreground/50" />
                          {problem.products.map((p) => (
                            <Link
                              key={p}
                              href={`/products?q=${encodeURIComponent(p)}`}
                              className="rounded-full bg-paper-2 px-1.5 py-0 text-[10px] font-medium ring-1 ring-line hover:bg-leaf-tint hover:ring-leaf-lt transition-colors"
                            >
                              {p}
                            </Link>
                          ))}
                          <Link
                            href={`/products?q=${encodeURIComponent(problem.products[0])}`}
                            className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600 font-medium hover:text-emerald-700 ml-1"
                          >
                            See treatments <ArrowRight className="w-2.5 h-2.5" />
                          </Link>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </details>
    </div>
  );
}
