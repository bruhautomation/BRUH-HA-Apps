'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Search,
  X,
  ChevronRight,
  ChevronDown,
  ArrowUpDown,
  Plus,
  Leaf,
  Sprout,
  Map as MapIcon,
  TriangleAlert,
} from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { createClient } from '@/lib/db/client';
import { CROP_CATALOG, type CatalogEntry } from '@/lib/crop-catalog';
import { CropGlyph, resolveGlyphKind } from '@/components/crop-glyph';
import { cropIconColor } from '@/components/crop-icon';
import { CovDot, covColor } from '@/components/status';
import type { CropGroup } from '@/lib/database.types';

export type CovCell = { status: 'green' | 'yellow' | 'red'; daysRemaining: number } | null;

export type CropCardModel = {
  id: number;
  name: string;
  group: string | null;
  category: string;
  varietyCount: number;
  stageLabel: string | null;
  stageColor: string;
  inBloom: boolean;
  trackFung: boolean;
  trackIns: boolean;
  fung: CovCell;
  ins: CovCell;
  phiActive: boolean;
  phiDaysLeft: number;
  protection: 'green' | 'yellow' | 'red' | 'untracked';
};

const CATEGORY_ORDER = ['Orchard', 'Garden', 'Landscape'];
const CATEGORY_ICON: Record<string, typeof Leaf> = {
  Orchard: Leaf,
  Garden: Sprout,
  Landscape: MapIcon,
};

const SORTS: Record<string, string> = {
  priority: 'Priority',
  name: 'Name (A–Z)',
  coverage: 'Coverage left',
};

function urgency(c: CropCardModel): number {
  if (c.phiActive) return 0;
  if (c.protection === 'red') return 1;
  if (c.protection === 'yellow') return 2;
  if (c.protection === 'green') return 3;
  return 4;
}
function covSoonest(c: CropCardModel): number {
  const vals = [c.fung, c.inBloom ? null : c.ins]
    .filter(Boolean)
    .map((x) => (x!.status === 'red' ? 0 : x!.daysRemaining));
  return vals.length ? Math.min(...vals) : 9999;
}

export function CropsBoard({
  cards,
  cropGroups,
}: {
  cards: CropCardModel[];
  cropGroups: CropGroup[];
}) {
  const [cat, setCat] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('priority');

  const categories = useMemo(() => {
    const present = new Set(cards.map((c) => c.category));
    return CATEGORY_ORDER.filter((c) => present.has(c));
  }, [cards]);

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    const comparators: Record<string, (a: CropCardModel, b: CropCardModel) => number> = {
      priority: (a, b) => urgency(a) - urgency(b) || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
      coverage: (a, b) => covSoonest(a) - covSoonest(b) || a.name.localeCompare(b.name),
    };
    return cards
      .filter((c) => (cat === 'all' || c.category === cat) && c.name.toLowerCase().includes(needle))
      .slice()
      .sort(comparators[sort]);
  }, [cards, cat, q, sort]);

  const grouped = cat === 'all' && sort === 'priority';

  return (
    <div className="page">
      <div className="section-title">
        <h2>All crops</h2>
        <span className="meta">
          {filtered.length} of {cards.length}
        </span>
        <div className="spacer" />
        <div className="relative w-[200px] min-w-0 max-w-full">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
          <input
            className="text-input w-full pl-9"
            placeholder="Search crops…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="chips">
          <button className={`chip${cat === 'all' ? ' active' : ''}`} onClick={() => setCat('all')}>
            All crops
          </button>
          {categories.map((c) => (
            <button
              key={c}
              className={`chip${cat === c ? ' active' : ''}`}
              onClick={() => setCat(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="spacer flex-1" />
        <label className="sort-ctl">
          <ArrowUpDown className="size-[15px]" />
          <span>{SORTS[sort]}</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort crops">
            {Object.entries(SORTS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <ChevronDown className="size-3.5" />
        </label>
        <AddCropButton cropGroups={cropGroups} existing={cards.map((c) => c.name)} />
      </div>

      {grouped ? (
        categories.map((category) => {
          const list = filtered.filter((c) => c.category === category);
          if (!list.length) return null;
          const Icon = CATEGORY_ICON[category] ?? Leaf;
          const due = list.filter((c) => c.protection === 'red').length;
          const phi = list.filter((c) => c.phiActive).length;
          const meta = [due ? `${due} due` : '', phi ? `${phi} under PHI` : '']
            .filter(Boolean)
            .join(' · ');
          return (
            <div key={category}>
              <div className="cat-head">
                <div className="cat-ico">
                  <Icon className="size-[17px]" />
                </div>
                <h2>{category}</h2>
                <span className="cat-count">
                  {list.length} crops{meta ? ` · ${meta}` : ''}
                </span>
                <div className="cat-line" />
              </div>
              <div className="crop-grid">
                {list.map((c) => (
                  <CropCard key={c.id} c={c} />
                ))}
              </div>
            </div>
          );
        })
      ) : (
        <div className="crop-grid">
          {filtered.map((c) => (
            <CropCard key={c.id} c={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function CropCard({ c }: { c: CropCardModel }) {
  const accent =
    c.phiActive || c.protection === 'red'
      ? 'var(--danger)'
      : c.protection === 'yellow'
        ? 'var(--warn)'
        : c.protection === 'green'
          ? 'var(--leaf)'
          : 'var(--line-2)';
  return (
    <Link
      href={`/crops/${c.id}`}
      className={`crop-card${c.phiActive ? ' phi-active' : ''}`}
      style={{ ['--cc-accent' as string]: accent }}
    >
      <div className="cc-top">
        <div
          className="cc-emoji"
          style={{
            background: `color-mix(in srgb, ${cropIconColor(c.name, c.group)} 16%, transparent)`,
            color: cropIconColor(c.name, c.group),
          }}
        >
          <CropGlyph kind={resolveGlyphKind(c.name, c.group)} size={24} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="cc-name">{c.name}</div>
          <div className="cc-var">
            {c.varietyCount
              ? `${c.varietyCount} ${c.varietyCount === 1 ? 'variety' : 'varieties'}`
              : 'Ornamental'}
          </div>
        </div>
        <ChevronRight className="mt-1 size-[18px] shrink-0 text-ink-3" />
      </div>

      <div className="cc-stage-line">
        {c.stageLabel && (
          <span className="cc-stage" style={{ ['--stg' as string]: c.stageColor }}>
            <span className="dot" /> {c.stageLabel}
          </span>
        )}
        {c.phiActive && (
          <span className="cc-flag hold">
            <TriangleAlert className="size-3.5" /> Hold {c.phiDaysLeft}d
          </span>
        )}
      </div>

      <div className="cc-covs">
        <CovChip label="Fung" cov={c.fung} manual={!c.trackFung} />
        <CovChip label="Ins" cov={c.ins} suppressed={c.inBloom} manual={!c.trackIns} />
      </div>
    </Link>
  );
}

function CovChip({
  label,
  cov,
  suppressed,
  manual,
}: {
  label: string;
  cov: CovCell;
  suppressed?: boolean;
  manual?: boolean;
}) {
  if (manual) {
    return (
      <span className="cc-cov">
        <span
          className="inline-block rounded-full"
          style={{ width: 7, height: 7, background: 'var(--ink-3)', opacity: 0.5 }}
        />
        <span className="cc-cov-k">{label}</span>
        <span className="cc-cov-v" style={{ color: 'var(--ink-3)' }}>
          as needed
        </span>
      </span>
    );
  }
  if (suppressed) {
    return (
      <span className="cc-cov">
        <span
          className="inline-block rounded-full"
          style={{ width: 7, height: 7, background: 'var(--bloom)', opacity: 0.45 }}
        />
        <span className="cc-cov-k">{label}</span>
        <span className="cc-cov-v" style={{ color: 'var(--bloom)' }}>
          bloom
        </span>
      </span>
    );
  }
  if (!cov) {
    return (
      <span className="cc-cov">
        <CovDot status="untracked" size={7} />
        <span className="cc-cov-k">{label}</span>
        <span className="cc-cov-v" style={{ color: 'var(--ink-3)' }}>
          —
        </span>
      </span>
    );
  }
  return (
    <span className="cc-cov">
      <CovDot status={cov.status} size={7} />
      <span className="cc-cov-k">{label}</span>
      <span className="cc-cov-v" style={{ color: covColor(cov.status) }}>
        {cov.status === 'red' ? 'lapsed' : `${cov.daysRemaining}d`}
      </span>
    </span>
  );
}

function AddCropButton({ cropGroups, existing }: { cropGroups: CropGroup[]; existing: string[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);

  const existingNames = useMemo(() => new Set(existing.map((n) => n.toLowerCase())), [existing]);
  const filtered = CROP_CATALOG.filter((e) => !existingNames.has(e.name.toLowerCase())).filter(
    (e) =>
      search === '' ||
      e.name.toLowerCase().includes(search.toLowerCase()) ||
      (e.cropGroup?.toLowerCase().includes(search.toLowerCase()) ?? false)
  );

  async function addFromCatalog(entry: CatalogEntry) {
    setSaving(true);
    const supabase = createClient();
    const group = entry.cropGroup ? cropGroups.find((g) => g.name === entry.cropGroup) : null;
    await supabase.from('crops').insert({ name: entry.name, crop_group_id: group?.id ?? null });
    setSaving(false);
    setOpen(false);
    setSearch('');
    router.refresh();
  }
  async function addCustom() {
    if (!search.trim()) return;
    setSaving(true);
    await createClient().from('crops').insert({ name: search.trim(), crop_group_id: null });
    setSaving(false);
    setOpen(false);
    setSearch('');
    router.refresh();
  }

  const groups = new Map<string, CatalogEntry[]>();
  for (const e of filtered) {
    const k = e.cropGroup ?? 'Other';
    const arr = groups.get(k);
    if (arr) arr.push(e);
    else groups.set(k, [e]);
  }

  return (
    <>
      <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
        <Plus className="size-4" /> Add crop
      </button>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setSearch('');
        }}
      >
        <DialogContent className="rounded-xl sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl font-semibold tracking-tight">
              Add crop
            </DialogTitle>
          </DialogHeader>
          <div className="relative mt-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/50" />
            <Input
              placeholder="Search crops…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="rounded-lg pl-9"
              autoFocus
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
          <div className="mt-1 max-h-[50vh] space-y-0.5 overflow-y-auto px-1">
            {groups.size === 0 && search ? (
              <div className="py-6 text-center">
                <p className="mb-2 text-sm text-muted-foreground">
                  No match for &ldquo;{search}&rdquo;
                </p>
                <button onClick={addCustom} disabled={saving} className="btn btn-primary mx-auto">
                  <Plus className="size-3.5" /> {saving ? 'Adding…' : `Add "${search.trim()}"`}
                </button>
              </div>
            ) : (
              [...groups.entries()].map(([groupName, entries]) => (
                <div key={groupName}>
                  <p className="sticky top-0 bg-popover/95 px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-widest text-muted-foreground/70 backdrop-blur-sm">
                    {groupName}
                  </p>
                  {entries.map((e) => (
                    <button
                      key={e.name}
                      onClick={() => addFromCatalog(e)}
                      disabled={saving}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted/60 disabled:opacity-50"
                    >
                      <span className="w-6 shrink-0 text-center text-lg">{e.emoji}</span>
                      <span className="text-sm font-medium text-foreground">{e.name}</span>
                      {e.cropGroup && (
                        <span className="ml-auto text-[10px] text-muted-foreground/50">
                          {e.cropGroup}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
