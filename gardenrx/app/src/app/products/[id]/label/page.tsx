'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Search, X } from 'lucide-react';
import { withBase } from '@/lib/base-path';

type LoadState = 'loading' | 'ready' | 'missing';

export default function LabelPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [state, setState] = useState<LoadState>('loading');
  const [brand, setBrand] = useState('');
  const [labelText, setLabelText] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const indexRes = await fetch(withBase('/data/label_texts.json'));
        const index = indexRes.ok ? await indexRes.json() : {};
        const entry = index[id];
        if (!cancelled && entry?.brand) setBrand(entry.brand);

        const txtRes = await fetch(withBase(`/data/labels/${id}.txt`));
        if (!txtRes.ok) {
          if (!cancelled) setState('missing');
          return;
        }
        const text = await txtRes.text();
        if (cancelled) return;
        setLabelText(text);
        setState('ready');
      } catch {
        if (!cancelled) setState('missing');
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Highlight matches by splitting text on the query (case-insensitive)
  const rendered = useMemo(() => {
    if (!query.trim()) return null;
    const q = query.trim();
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const parts = labelText.split(re);
    return parts.map((part, i) =>
      re.test(part) ? (
        <mark key={i} className="bg-amber-200/70 text-foreground rounded-sm px-0.5">
          {part}
        </mark>
      ) : (
        <span key={i}>{part}</span>
      )
    );
  }, [labelText, query]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-parchment-50">
      {/* Header bar */}
      <div className="flex items-center gap-3 px-4 py-3 bg-card border-b border-border/40 shadow-sm shrink-0">
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground/70 hover:text-emerald-700 transition-colors group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
          Back
        </button>
        {brand && (
          <>
            <span className="text-muted-foreground/30">|</span>
            <span className="text-sm font-heading font-semibold text-foreground truncate flex-1 min-w-0">
              {brand}
            </span>
          </>
        )}
      </div>

      {/* Search bar */}
      {state === 'ready' && (
        <div className="px-4 py-2 bg-card/60 border-b border-border/30 shrink-0">
          <div className="relative max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search label text…"
              className="w-full pl-8 pr-7 py-1.5 text-sm rounded-lg ring-1 ring-border/60 bg-card focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5 text-muted-foreground/50" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-auto">
        {state === 'loading' && (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-muted-foreground/60">Loading label…</p>
          </div>
        )}
        {state === 'missing' && (
          <div className="flex flex-col items-center justify-center h-full px-6 text-center">
            <p className="text-sm font-medium text-foreground/80 mb-1">No label text on file</p>
            <p className="text-xs text-muted-foreground/60 max-w-sm">
              We don&apos;t yet have the extracted label for this product. See the
              manufacturer&apos;s website for the official label.
            </p>
          </div>
        )}
        {state === 'ready' && (
          <article className="max-w-3xl mx-auto px-4 py-6">
            <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-foreground/90">
              {rendered ?? labelText}
            </pre>
          </article>
        )}
      </div>
    </div>
  );
}
