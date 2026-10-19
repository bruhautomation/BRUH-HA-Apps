'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Search, X, FlaskConical, Sprout, Bug, Leaf } from 'lucide-react';
import { CROP_PROBLEMS } from '@/lib/crop-problems';

interface SearchResult {
  type: 'product' | 'crop' | 'problem' | 'label';
  title: string;
  subtitle: string;
  href: string;
  icon: typeof Search;
}

export function GlobalSearch({
  products,
  crops,
  cropGroups,
}: {
  products: Array<{
    id: number;
    brand: string;
    formulation: string | null;
    concentration: string | null;
  }>;
  crops: Array<{ id: number; name: string; crop_group_id: number | null }>;
  cropGroups: Array<{ id: number; name: string }>;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut: Cmd+K or /
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === 'Escape') {
        setOpen(false);
        setQuery('');
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const results: SearchResult[] = [];

  if (query.length >= 2) {
    const q = query.toLowerCase();

    // Search products
    for (const p of products) {
      if (
        p.brand.toLowerCase().includes(q) ||
        (p.concentration ?? '').toLowerCase().includes(q) ||
        (p.formulation ?? '').toLowerCase().includes(q)
      ) {
        results.push({
          type: 'product',
          title: p.brand,
          subtitle: p.concentration ?? p.formulation ?? '',
          href: `/products/${p.id}`,
          icon: FlaskConical,
        });
      }
      if (results.length >= 20) break;
    }

    // Search crops
    for (const c of crops) {
      if (c.name.toLowerCase().includes(q)) {
        const group = cropGroups.find((g) => g.id === c.crop_group_id);
        results.push({
          type: 'crop',
          title: c.name,
          subtitle: group?.name ?? '',
          href: `/crops/${c.id}`,
          icon: Sprout,
        });
      }
    }

    // Search crop problems
    for (const [groupName, problems] of Object.entries(CROP_PROBLEMS)) {
      for (const p of problems) {
        if (
          p.name.toLowerCase().includes(q) ||
          p.symptoms.toLowerCase().includes(q) ||
          p.remediation.toLowerCase().includes(q)
        ) {
          const crop = crops.find((c) => {
            const group = cropGroups.find((g) => g.id === c.crop_group_id);
            return group?.name === groupName;
          });
          results.push({
            type: 'problem',
            title: p.name,
            subtitle: `${groupName} — ${p.type}`,
            href: crop ? `/crops/${crop.id}` : '/crops',
            icon: p.type === 'insect' ? Bug : Leaf,
          });
        }
        if (results.length >= 25) break;
      }
    }
  }

  function navigate(href: string) {
    setOpen(false);
    setQuery('');
    router.push(href);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center justify-center w-9 h-9 rounded-full bg-card/90 backdrop-blur-sm text-muted-foreground ring-1 ring-black/[0.06] shadow-sm hover:ring-emerald-300 hover:text-emerald-700 transition-all"
        title="Search (⌘K)"
      >
        <Search className="w-4 h-4" />
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-[90]">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 backdrop-blur-sm"
        onClick={() => {
          setOpen(false);
          setQuery('');
        }}
      />

      {/* Search panel */}
      <div className="fixed top-[10%] left-1/2 -translate-x-1/2 w-full max-w-lg px-4">
        <div className="rounded-2xl bg-card shadow-2xl ring-1 ring-black/[0.08] overflow-hidden">
          {/* Input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40">
            <Search className="w-5 h-5 text-muted-foreground/50 shrink-0" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search treatments, crops, diseases, ingredients..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 text-sm bg-transparent outline-none placeholder:text-muted-foreground/40"
            />
            {query && (
              <button onClick={() => setQuery('')}>
                <X className="w-4 h-4 text-muted-foreground/50" />
              </button>
            )}
            <kbd className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-[60vh] overflow-y-auto">
            {query.length < 2 && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground/50">
                Type to search across treatments, crops, and problems
              </div>
            )}

            {query.length >= 2 && results.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground/50">
                No results for &ldquo;{query}&rdquo;
              </div>
            )}

            {results.length > 0 && (
              <div className="py-2">
                {results.map((r, i) => {
                  const Icon = r.icon;
                  return (
                    <button
                      key={`${r.type}-${i}`}
                      onClick={() => navigate(r.href)}
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-emerald-50/60 transition-colors"
                    >
                      <div
                        className={`flex items-center justify-center w-8 h-8 rounded-lg shrink-0 ${
                          r.type === 'product'
                            ? 'bg-violet-50 text-violet-600'
                            : r.type === 'crop'
                              ? 'bg-emerald-50 text-emerald-600'
                              : r.type === 'problem'
                                ? 'bg-amber-50 text-amber-600'
                                : 'bg-sky-50 text-sky-600'
                        }`}
                      >
                        <Icon className="w-4 h-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{r.title}</p>
                        <p className="text-[11px] text-muted-foreground truncate">{r.subtitle}</p>
                      </div>
                      <span className="text-[10px] text-muted-foreground/50 shrink-0 capitalize">
                        {r.type}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
