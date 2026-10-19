'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type {
  Crop,
  Variety,
  VarietyStage,
  CropGroup,
  PhenologicalStage,
  Product,
  ActiveIngredient,
  Database,
} from '@/lib/database.types';
import type { CoverageInfo } from '@/lib/protection';
import type { CropPhi } from '@/lib/phi';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DialogFooter } from '@/components/ui/dialog';
import { FormDialog, ConfirmDialog } from '@/components/ui/form-dialog';
import { createClient } from '@/lib/db/client';
import {
  Flower2,
  Plus,
  Trash2,
  CalendarDays,
  FlaskConical,
  Shield,
  ChevronDown,
  ChevronLeft,
  ExternalLink,
  Info,
  TriangleAlert,
  Sprout,
  Gauge,
  ShieldCheck,
  Beaker,
  Bug,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { STAGES_BY_GROUP, DEFAULT_STAGES, getStageColor } from '@/lib/growth-stages';
import { stageIndex, stageVarColor, stageLabel } from '@/lib/stage-color';
import { CropProblemsPanel } from '@/components/crop-problems-panel';
import { getStageImagePaths } from '@/lib/image-paths';
import { RefImage } from '@/components/ref-image';
import { CropAvatar } from '@/components/crop-glyph';
import { CoverageMeter } from '@/components/coverage-meter';
import { StageTimeline } from '@/components/stage-timeline';
import { covLabel, covColor } from '@/components/status';
import { calculateDose } from '@/lib/dose';
import { useSprayerGallons } from '@/lib/use-sprayer-gallons';
import { productLabel } from '@/lib/product-label';
import { VARIETY_CATALOG } from '@/lib/variety-catalog';
import { withBase } from '@/lib/base-path';

function formatStage(s: string) {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
function fmtDate(d: Date | null) {
  return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
}

const stageImageSlugs: Record<string, Record<string, string>> = {
  'Pome Fruit': {
    dormant: 'dormant',
    bud_break: 'silver-tip',
    green_tip: 'green-tip',
    tight_cluster: 'tight-cluster',
    pink: 'pink',
    bloom: 'bloom',
    petal_fall: 'petal-fall',
    fruit_set: 'fruit-set',
    green_fruit: 'green-fruit',
  },
  'Stone Fruit': {
    dormant: 'dormant',
    bud_break: 'bud-swell',
    pink: 'pink',
    bloom: 'bloom',
    petal_fall: 'shuck-split',
    fruit_set: 'fruit-set',
    green_fruit: 'green-fruit',
  },
  Berries: {
    dormant: 'dormant',
    bud_break: 'bud-break',
    bloom: 'bloom',
    fruit_set: 'green-fruit',
    green_fruit: 'fruit-coloring',
  },
  Grapes: {
    dormant: 'dormant',
    bud_break: 'bud-break',
    green_tip: 'shoot-growth',
    bloom: 'bloom',
    fruit_set: 'fruit-set',
    green_fruit: 'veraison',
  },
  Ornamentals: { dormant: 'dormant', bud_break: 'bud-break', bloom: 'bloom' },
};

function slugifyStage(stage: string, groupName?: string): string {
  if (groupName && stageImageSlugs[groupName]?.[stage]) return stageImageSlugs[groupName][stage];
  return stage.replace(/_/g, '-');
}

/** Segmented Monitored / As-needed control for one treatment type. */
function MonitorRow({
  label,
  icon: Icon,
  tracked,
  onChange,
  disabled,
}: {
  label: string;
  icon: LucideIcon;
  tracked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-paper-2 px-3 py-2 ring-1 ring-line">
      <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-2">
        <Icon className="size-3.5 text-ink-3" /> {label}
      </span>
      <div
        className="inline-flex rounded-lg bg-card p-0.5 ring-1 ring-line"
        role="group"
        aria-label={`${label} monitoring mode`}
      >
        <button
          type="button"
          aria-pressed={tracked}
          disabled={disabled}
          onClick={() => onChange(true)}
          className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors ${tracked ? 'bg-leaf text-on-leaf shadow-sm' : 'text-ink-3 hover:text-ink-2'}`}
        >
          Monitored
        </button>
        <button
          type="button"
          aria-pressed={!tracked}
          disabled={disabled}
          onClick={() => onChange(false)}
          className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors ${!tracked ? 'bg-ink text-paper shadow-sm' : 'text-ink-3 hover:text-ink-2'}`}
        >
          As needed
        </button>
      </div>
    </div>
  );
}

/** Meter-slot stand-in shown when a treatment type is set to as-needed (manual). */
function AsNeededMeter({ type }: { type: 'fungicide' | 'insecticide' }) {
  const Icon = type === 'fungicide' ? Beaker : Bug;
  const label = type === 'fungicide' ? 'Fungicide' : 'Insecticide';
  return (
    <div className="cov-meter">
      <div className="cov-top">
        <span className="cov-name">
          <Icon className="size-3.5" /> {label}
        </span>
        <span className="cov-stat" style={{ color: 'var(--ink-3)' }}>
          As needed
        </span>
      </div>
      <div className="cov-track">
        <div className="cov-fill" style={{ width: '100%', background: 'var(--line-2)' }} />
      </div>
      <div className="cov-sub">Manual interventions only — not monitored.</div>
    </div>
  );
}

interface Props {
  crop: Crop;
  cropGroup: CropGroup | null;
  varieties: Variety[];
  varietyStages: VarietyStage[];
  fungCoverage: CoverageInfo | null;
  insCoverage: CoverageInfo | null;
  phi: CropPhi;
  /** Whether the crop's fruit is in season now — PHI is only flagged when it is. */
  phiInSeason: boolean;
  labeledProducts: Array<{
    product: Product;
    ingredients: ActiveIngredient[];
    rate_min: number | null;
    rate_max: number | null;
    rate_unit: string;
    phi_days: number | null;
    max_apps_per_season: number | null;
    min_interval_days: number | null;
    growth_stage_restrictions: string | null;
    restrictions_text: string | null;
  }>;
  recentSprays: Array<{
    id: number;
    date: string;
    notes: string | null;
    products: Array<{
      brand: string;
      rate_applied: number | null;
      rate_unit: string;
      ingredients: Array<{ name: string }>;
    }>;
  }>;
}

export function CropDetailView({
  crop,
  cropGroup,
  varieties,
  varietyStages,
  fungCoverage,
  insCoverage,
  phi,
  phiInSeason,
  labeledProducts,
  recentSprays,
}: Props) {
  const router = useRouter();
  const [sprayerGallons] = useSprayerGallons();
  const [addVarietyOpen, setAddVarietyOpen] = useState(false);
  const [stageEdit, setStageEdit] = useState<{
    varietyId: number;
    varietyName: string;
    current: PhenologicalStage;
  } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; name: string } | null>(null);
  const [deleteCropConfirm, setDeleteCropConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [expandedProduct, setExpandedProduct] = useState<number | null>(null);
  // Monitoring mode per treatment type — optimistic so the toggle flips instantly.
  const [trackFung, setTrackFung] = useState(crop.track_fungicide);
  const [trackIns, setTrackIns] = useState(crop.track_insecticide);

  const stageInfos = STAGES_BY_GROUP[cropGroup?.name ?? ''] ?? DEFAULT_STAGES;

  // Index variety stages by variety id (keeping the first row, matching the
  // previous `.find()` semantics) so per-variety lookups below stay O(1).
  const stageByVariety = new Map<number, (typeof varietyStages)[number]>();
  for (const s of varietyStages) {
    if (!stageByVariety.has(s.variety_id)) stageByVariety.set(s.variety_id, s);
  }

  // Representative stage = most advanced across varieties.
  const stages = varieties.map(
    (v) => (stageByVariety.get(v.id)?.stage ?? 'dormant') as PhenologicalStage
  );
  const inBloom = stages.includes('bloom');
  const topStage = stages.length
    ? stages.reduce((a, b) => (stageIndex(b) > stageIndex(a) ? b : a))
    : null;
  const currentIndex = topStage ? stageInfos.findIndex((si) => si.stage === topStage) : -1;

  // Only monitored types drive the protection verdict; as-needed ones are manual.
  const protStatuses = [
    trackFung ? fungCoverage?.status : undefined,
    trackIns && !inBloom ? insCoverage?.status : undefined,
  ].filter(Boolean) as string[];
  const worst = protStatuses.includes('red')
    ? 'red'
    : protStatuses.includes('yellow')
      ? 'yellow'
      : protStatuses.length
        ? 'green'
        : 'untracked';
  const bothManual = !trackFung && !trackIns;

  const noHarvestValue = [
    'Ornamentals',
    'Turf Grass',
    'Structures & Premise',
    'Orchard Floor',
  ].includes(cropGroup?.name ?? '');

  // A pre-harvest interval only matters when the fruit is actually in season —
  // out of season there's nothing to harvest, so don't flag it.
  const phiFlag = phi.active && phiInSeason;
  const phiCleared = phi.applies && !phi.active && phiInSeason;

  async function addVariety(formData: FormData) {
    setSaving(true);
    const supabase = createClient();
    const name = formData.get('name') as string;
    const { data } = await supabase
      .from('varieties')
      .insert({ name, crop_id: crop.id })
      .select()
      .single();
    if (data) await supabase.from('variety_stages').insert({ variety_id: data.id });
    setSaving(false);
    setAddVarietyOpen(false);
    router.refresh();
  }
  async function updateStage(varietyId: number, stage: PhenologicalStage) {
    setSaving(true);
    const supabase = createClient();
    const existing = stageByVariety.get(varietyId);
    if (existing) {
      await supabase
        .from('variety_stages')
        .update({ stage, is_manual_override: true, updated_at: new Date().toISOString() })
        .eq('variety_id', varietyId);
    } else {
      await supabase
        .from('variety_stages')
        .insert({ variety_id: varietyId, stage, is_manual_override: true });
    }
    setSaving(false);
    setStageEdit(null);
    router.refresh();
  }
  async function deleteVariety(id: number) {
    setSaving(true);
    await createClient().from('varieties').delete().eq('id', id);
    setSaving(false);
    setDeleteConfirm(null);
    router.refresh();
  }
  async function deleteCrop() {
    setSaving(true);
    await createClient().from('crops').delete().eq('id', crop.id);
    setSaving(false);
    setDeleteCropConfirm(false);
    router.push('/crops');
    router.refresh();
  }
  async function setMonitoring(
    field: 'track_fungicide' | 'track_insecticide',
    value: boolean,
    setLocal: (v: boolean) => void
  ) {
    setLocal(value); // optimistic
    const patch = { [field]: value } as Database['public']['Tables']['crops']['Update'];
    const { error } = await createClient().from('crops').update(patch).eq('id', crop.id);
    if (error) {
      setLocal(!value);
      window.alert(`Couldn't update monitoring: ${error.message}`);
      return;
    }
    router.refresh();
  }

  return (
    <div className="page animate-stagger">
      <Link href="/crops" className="btn btn-ghost mb-3.5">
        <ChevronLeft className="size-4" /> Crops
      </Link>

      {/* Header */}
      <div className="mb-[var(--gap)] flex flex-wrap items-center gap-4">
        <CropAvatar name={crop.name} group={cropGroup?.name ?? null} size={56} />
        <div className="min-w-[200px] flex-1">
          <h1 className="text-[26px] font-semibold tracking-tight">{crop.name}</h1>
          <div className="mono mt-0.5 text-[13px] text-ink-3">
            {cropGroup?.name ?? 'Uncategorized'} · {varieties.length}{' '}
            {varieties.length === 1 ? 'variety' : 'varieties'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {topStage && (
            <span
              className="badge badge-stage"
              style={{ ['--stg' as string]: stageVarColor(topStage) }}
            >
              <span className="dot" /> {stageLabel(topStage)}
            </span>
          )}
          {phiCleared && (
            <span className="badge badge-safe">
              <ShieldCheck className="size-3" /> Safe to harvest
            </span>
          )}
          <button
            onClick={() => setDeleteCropConfirm(true)}
            className="icon-btn"
            title="Delete crop"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>

      {/* PHI bar (loud) — only while the fruit is in season */}
      {phiFlag && (
        <div className="phi-bar">
          <div className="pb-ico">
            <TriangleAlert className="size-5" />
          </div>
          <div className="txt">
            <strong>Do not harvest.</strong> {phi.product} applied {fmtDate(phi.appliedDate)} —
            pre-harvest interval clears <strong>{fmtDate(phi.endDate)}</strong> ({phi.daysLeft} day
            {phi.daysLeft === 1 ? '' : 's'} away).
          </div>
        </div>
      )}

      {/* Metric trio */}
      <div className="metric-row mb-[var(--gap)]">
        <div className="metric">
          <div className="m-k">Growth stage</div>
          <div className="m-v" style={{ color: topStage ? stageVarColor(topStage) : 'var(--ink)' }}>
            {topStage ? stageLabel(topStage) : '—'}
          </div>
          <div className="m-sub">
            {noHarvestValue ? 'Ornamental' : `${cropGroup?.name ?? 'Crop'}`}
          </div>
        </div>
        <div className="metric">
          <div className="m-k">Protection</div>
          <div
            className="m-v"
            style={{
              color: bothManual
                ? 'var(--ink-3)'
                : covColor(worst === 'untracked' ? null : (worst as 'red' | 'yellow' | 'green')),
            }}
          >
            {bothManual
              ? 'As needed'
              : worst === 'untracked'
                ? 'Untracked'
                : covLabel(worst as 'red' | 'yellow' | 'green')}
          </div>
          <div className="m-sub">
            {!trackFung
              ? 'Fung manual'
              : fungCoverage
                ? `Fung ${fungCoverage.status === 'red' ? 'lapsed' : `${fungCoverage.daysRemaining}d`}`
                : 'Fung —'}
            {' · '}
            {!trackIns
              ? 'Ins manual'
              : inBloom
                ? 'Ins held'
                : insCoverage
                  ? `Ins ${insCoverage.status === 'red' ? 'lapsed' : `${insCoverage.daysRemaining}d`}`
                  : 'Ins —'}
          </div>
        </div>
        <div className="metric">
          <div className="m-k">Harvest status</div>
          <div className="m-v" style={{ color: phiFlag ? 'var(--danger)' : 'var(--ink)' }}>
            {noHarvestValue ? 'N/A' : phiFlag ? `Safe ${fmtDate(phi.endDate)}` : 'Clear'}
          </div>
          <div className="m-sub">
            {noHarvestValue
              ? 'Ornamental'
              : phiFlag
                ? `${phi.daysLeft} day${phi.daysLeft === 1 ? '' : 's'} of PHI left`
                : 'No active PHI'}
          </div>
        </div>
      </div>

      {/* Growth timeline */}
      {topStage && (
        <div className="card panel mb-[var(--gap)]">
          <div className="panel-h">
            <Sprout className="size-[18px] text-leaf" />
            <h3>Growth timeline</h3>
            <span className="ph-meta">{cropGroup?.name ?? 'stages'}</span>
          </div>
          <StageTimeline stages={stageInfos} currentIndex={currentIndex} />
        </div>
      )}

      {/* Protection coverage */}
      <div className="card panel mb-[var(--gap)]">
        <div className="panel-h">
          <Gauge className="size-[18px] text-leaf" />
          <h3>Protection coverage</h3>
          <span className="ph-meta">
            {bothManual
              ? 'manual'
              : worst === 'untracked'
                ? 'no spray history'
                : covLabel(worst as 'red' | 'yellow' | 'green')}
          </span>
        </div>

        {/* Monitoring mode — track coverage or treat as-needed, per type */}
        <p className="mb-2.5 text-[12px] leading-snug text-ink-3">
          <span className="font-semibold text-ink-2">Monitored</span> tracks spray coverage and
          flags this crop on the dashboard when it lapses.{' '}
          <span className="font-semibold text-ink-2">As needed</span> means you treat it manually —
          it&apos;s never shown as due.
        </p>
        <div className="mb-[18px] grid grid-cols-1 gap-2 sm:grid-cols-2">
          <MonitorRow
            label="Fungicide"
            icon={Beaker}
            tracked={trackFung}
            disabled={saving}
            onChange={(v) => setMonitoring('track_fungicide', v, setTrackFung)}
          />
          <MonitorRow
            label="Insecticide"
            icon={Bug}
            tracked={trackIns}
            disabled={saving}
            onChange={(v) => setMonitoring('track_insecticide', v, setTrackIns)}
          />
        </div>

        <div className="grid grid-cols-1 gap-[22px] sm:grid-cols-2">
          {trackFung ? (
            <CoverageMeter cov={fungCoverage} type="fungicide" />
          ) : (
            <AsNeededMeter type="fungicide" />
          )}
          {trackIns ? (
            <CoverageMeter cov={insCoverage} type="insecticide" suppressed={inBloom} />
          ) : (
            <AsNeededMeter type="insecticide" />
          )}
        </div>
      </div>

      {/* Harvest value */}
      {!noHarvestValue && (
        <div className="mb-[var(--gap)]">
          <HarvestValueEditor
            cropId={crop.id}
            pricePerLb={crop.price_market_per_lb}
            avgLbPerCount={crop.avg_lb_per_count}
          />
        </div>
      )}

      {/* Treatment history + Varieties */}
      <div
        className="detail-grid"
        style={varieties.length === 0 ? { gridTemplateColumns: '1fr' } : undefined}
      >
        <div className="card panel">
          <div className="panel-h">
            <FlaskConical className="size-[18px] text-warn" />
            <h3>Treatment history</h3>
            <span className="ph-meta">
              {recentSprays.length} application{recentSprays.length === 1 ? '' : 's'}
            </span>
          </div>
          {recentSprays.length ? (
            <div className="spray-list">
              {recentSprays.map((spray) => (
                <Link
                  key={spray.id}
                  href={`/history#spray-${spray.id}`}
                  className="spray-item !no-underline"
                >
                  <div className="si-rail">
                    <div
                      className="si-icon"
                      style={{
                        background: 'color-mix(in srgb, var(--leaf) 14%, var(--card))',
                        color: 'var(--leaf)',
                      }}
                    >
                      <CalendarDays className="size-4" />
                    </div>
                  </div>
                  <div className="si-body">
                    <div className="si-top">
                      <span className="si-name">
                        {spray.products
                          .map((p) => productLabel(p.brand, p.ingredients))
                          .join(' + ') || 'Spray'}
                      </span>
                      <span className="si-date">
                        {new Date(spray.date + 'T12:00:00').toLocaleDateString('en-US', {
                          month: 'short',
                          day: 'numeric',
                        })}
                      </span>
                    </div>
                    {spray.products.some((p) => p.rate_applied != null) && (
                      <div className="si-facts">
                        {spray.products
                          .filter((p) => p.rate_applied != null)
                          .map((p, i) => (
                            <span key={i}>
                              {p.brand} {p.rate_applied} {p.rate_unit}
                            </span>
                          ))}
                      </div>
                    )}
                    {spray.notes && (
                      <div className="mt-2 flex gap-1.5 text-[12.5px] text-ink-2">
                        <Info className="mt-0.5 size-3.5 shrink-0 text-ink-3" /> {spray.notes}
                      </div>
                    )}
                  </div>
                  <ExternalLink className="size-3.5 shrink-0 self-center text-ink-3" />
                </Link>
              ))}
            </div>
          ) : (
            <div className="py-5 text-center text-[13px] text-ink-3">
              No treatments logged for {crop.name}.
            </div>
          )}
        </div>

        {varieties.length > 0 && (
          <div className="card panel">
            <div className="panel-h">
              <Sprout className="size-[18px] text-leaf" />
              <h3>Varieties</h3>
              <button
                onClick={() => setAddVarietyOpen(true)}
                className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-leaf hover:text-leaf-dk"
              >
                <Plus className="size-3" /> Add
              </button>
            </div>
            <div className="space-y-1.5">
              {varieties.map((v) => {
                const vs = stageByVariety.get(v.id);
                const stage = vs?.stage ?? 'dormant';
                const isBloom = stage === 'bloom';
                const sc = getStageColor(stage);
                const profile = VARIETY_CATALOG[v.name];
                const imgSlug = v.name
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, '-')
                  .replace(/^-|-$/g, '');
                const imgPaths = [
                  withBase(`/images/varieties/${imgSlug}.jpg`),
                  withBase(`/images/varieties/${imgSlug}.png`),
                  withBase(`/images/varieties/${imgSlug}.webp`),
                ];
                return (
                  <details
                    key={v.id}
                    className="group/variety overflow-hidden rounded-lg bg-card ring-1 ring-border/60"
                  >
                    <summary className="flex cursor-pointer list-none select-none items-center gap-2.5 px-3 py-2 transition-colors hover:bg-muted/40 [&::-webkit-details-marker]:hidden">
                      <RefImage
                        paths={imgPaths}
                        alt={v.name}
                        className="size-10 shrink-0 rounded-lg ring-1 ring-black/[0.06]"
                        fallback={
                          <CropAvatar name={crop.name} group={cropGroup?.name ?? null} size={40} />
                        }
                      />
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium">{v.name}</span>
                        {profile && (
                          <span className="block truncate text-[10px] text-muted-foreground/60">
                            {profile.harvestWindow}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          setStageEdit({ varietyId: v.id, varietyName: v.name, current: stage });
                        }}
                        className="shrink-0"
                      >
                        <span
                          className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 transition-all hover:ring-2 ${sc.bg} ${sc.text} ${sc.ring}`}
                        >
                          {isBloom && <Flower2 className="size-2.5" />}
                          {formatStage(stage)}
                        </span>
                      </button>
                      <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-open/variety:rotate-180" />
                    </summary>
                    <div className="space-y-3 border-t border-border/40 px-3 pb-3">
                      {profile ? (
                        <div className="space-y-2.5 pt-3 text-[12px] leading-snug">
                          <p className="text-foreground/80">{profile.description}</p>
                          <div>
                            <p className="mb-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                              Flavor
                            </p>
                            <p className="text-foreground/80">{profile.taste}</p>
                          </div>
                          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                            <div>
                              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                                Harvest
                              </p>
                              <p className="text-foreground/80">{profile.harvestWindow}</p>
                            </div>
                            {profile.chillHours && (
                              <div>
                                <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                                  Chill hrs
                                </p>
                                <p className="text-foreground/80">{profile.chillHours}</p>
                              </div>
                            )}
                            {profile.diseaseNotes && (
                              <div className="col-span-2">
                                <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                                  Disease notes
                                </p>
                                <p className="leading-snug text-foreground/80">
                                  {profile.diseaseNotes}
                                </p>
                              </div>
                            )}
                          </div>
                          {profile.features.length > 0 && (
                            <div>
                              <p className="mb-1 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                                Key features
                              </p>
                              <ul className="space-y-0.5 text-[11px] leading-snug text-foreground/75">
                                {profile.features.map((f, i) => (
                                  <li key={i} className="flex gap-1.5">
                                    <span className="shrink-0 text-leaf/60">•</span>
                                    <span>{f}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="pt-3 text-[12px] italic text-muted-foreground/60">
                          No catalog profile for this variety yet.
                        </p>
                      )}
                      <div className="flex justify-end pt-1">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            setDeleteConfirm({ id: v.id, name: v.name });
                          }}
                          className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/50 transition-colors hover:text-destructive"
                        >
                          <Trash2 className="size-3" /> Remove variety
                        </button>
                      </div>
                    </div>
                  </details>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Add variety inline (when none) */}
      {varieties.length === 0 && (
        <div className="mt-[var(--gap)] text-center">
          <button onClick={() => setAddVarietyOpen(true)} className="btn">
            <Plus className="size-4" /> Add a variety
          </button>
        </div>
      )}

      {/* Problems & disease reference */}
      <div className="mt-[var(--gap)]">
        <CropProblemsPanel cropGroupName={cropGroup?.name ?? null} />
      </div>

      {/* Labeled products */}
      {labeledProducts.length > 0 && (
        <details className="info-banner mt-[var(--gap)]">
          <summary>
            <FlaskConical className="size-4 !text-leaf" />
            <b>Labeled products</b>
            <span className="ib-hint">
              {labeledProducts.length} for {cropGroup?.name ?? 'this crop'}
            </span>
          </summary>
          <div className="ib-body space-y-1.5">
            {labeledProducts.map((lp, i) => {
              const isExpanded = expandedProduct === i;
              const dose = lp.rate_max
                ? calculateDose(lp.rate_max, lp.rate_unit, sprayerGallons)
                : null;
              const ingType = lp.ingredients[0]?.type;
              return (
                <div key={i} className="overflow-hidden rounded-lg bg-card ring-1 ring-border/60">
                  <button
                    onClick={() => setExpandedProduct(isExpanded ? null : i)}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-muted/40"
                  >
                    <div className="grid size-6 shrink-0 place-items-center rounded-md bg-paper-2">
                      <FlaskConical className="size-3 text-ink-2" />
                    </div>
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">
                      {productLabel(lp.product.brand, lp.ingredients)}
                    </span>
                    <span className="grp-badge capitalize">{ingType}</span>
                    <ChevronDown
                      className={`size-3 text-muted-foreground/60 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    />
                  </button>
                  {isExpanded && (
                    <div className="space-y-2 px-3 pb-3 text-[11px] leading-relaxed">
                      <div>
                        <p className="mb-0.5 font-semibold text-foreground/80">
                          Active ingredients
                        </p>
                        <p className="text-muted-foreground">
                          {lp.ingredients.map((ing) => ing.name).join(', ')}
                          {lp.ingredients[0]?.frac_irac_hrac_group && (
                            <span className="text-muted-foreground/50">
                              {' '}
                              · Group {lp.ingredients[0].frac_irac_hrac_group}
                            </span>
                          )}
                        </p>
                      </div>
                      <div className="flex gap-4">
                        <div className="flex-1">
                          <p className="mb-0.5 font-semibold text-foreground/80">
                            Application rate
                          </p>
                          <p className="text-muted-foreground">
                            {lp.rate_min}–{lp.rate_max} {lp.rate_unit}
                            {dose && (
                              <span className="text-leaf"> ({dose.bestDisplay} / 4gal)</span>
                            )}
                          </p>
                        </div>
                        {lp.phi_days != null && (
                          <div>
                            <p className="mb-0.5 font-semibold text-foreground/80">PHI</p>
                            <p className="text-muted-foreground">{lp.phi_days} days</p>
                          </div>
                        )}
                      </div>
                      {lp.restrictions_text && (
                        <div className="rounded-lg bg-paper-2 px-2.5 py-2 ring-1 ring-border/60">
                          <p className="mb-0.5 font-semibold text-foreground/80">Restrictions</p>
                          <p className="text-muted-foreground">{lp.restrictions_text}</p>
                        </div>
                      )}
                      <Link
                        href={`/products/${lp.product.id}`}
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-leaf hover:text-leaf-dk"
                      >
                        View full product details <Shield className="size-2.5" />
                      </Link>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </details>
      )}

      {/* Dialogs */}
      <FormDialog open={addVarietyOpen} onOpenChange={setAddVarietyOpen} title="Add Variety">
        <form action={addVariety} className="mt-1 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="var-name" className="text-xs font-medium text-muted-foreground">
              Name
            </Label>
            <Input
              id="var-name"
              name="name"
              required
              placeholder="e.g., Honeycrisp"
              className="rounded-lg"
            />
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setAddVarietyOpen(false)}
              className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Add Variety'}
            </button>
          </DialogFooter>
        </form>
      </FormDialog>

      <FormDialog
        open={stageEdit !== null}
        onOpenChange={() => setStageEdit(null)}
        title="Set Growth Stage"
        className="sm:max-w-md"
      >
        <div className="mt-1 max-h-[60vh] space-y-1.5 overflow-y-auto pb-2 pr-1">
          {stageInfos.map((info) => {
            const s = info.stage;
            const isCurrent = stageEdit?.current === s;
            const isBloom = s === 'bloom';
            return (
              <button
                key={s}
                onClick={() => stageEdit && updateStage(stageEdit.varietyId, s)}
                disabled={saving}
                className={`w-full rounded-xl px-3 py-3 text-left transition-all ${isCurrent ? (isBloom ? 'bg-bloom-bg ring-2 ring-bloom shadow-sm' : 'bg-leaf-tint ring-2 ring-leaf shadow-sm') : 'bg-card ring-1 ring-border/60 hover:bg-muted/50'}`}
              >
                <div className="flex items-start gap-3">
                  <RefImage
                    paths={getStageImagePaths(
                      cropGroup?.name ?? '',
                      slugifyStage(info.stage, cropGroup?.name ?? '')
                    )}
                    alt={`${crop.name} — ${info.label}`}
                    description={info.description}
                    className="size-14 shrink-0 rounded-lg ring-1 ring-black/[0.06]"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold">{info.label}</span>
                      {isCurrent && (
                        <span className="rounded-full bg-leaf-lt px-1.5 py-0 text-[10px] font-semibold text-leaf-dk">
                          Current
                        </span>
                      )}
                      {isBloom && !isCurrent && <Flower2 className="size-3 text-bloom" />}
                    </div>
                    {info.description && (
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {info.description}
                      </p>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </FormDialog>

      <ConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={() => setDeleteConfirm(null)}
        title={`Delete ${deleteConfirm?.name}?`}
        description="This variety will be permanently removed."
        onConfirm={() => deleteConfirm && deleteVariety(deleteConfirm.id)}
        loading={saving}
      />
      <ConfirmDialog
        open={deleteCropConfirm}
        onOpenChange={setDeleteCropConfirm}
        title={`Delete ${crop.name}?`}
        description={`This will permanently delete ${crop.name} and all its varieties. This cannot be undone.`}
        confirmLabel="Delete Crop"
        onConfirm={deleteCrop}
        loading={saving}
      />
    </div>
  );
}

const WEIGHT_UNITS = ['lb', 'oz', 'kg', 'g'] as const;

function toLbDetail(weight: number, unit: string): number {
  switch (unit) {
    case 'oz':
      return weight / 16;
    case 'kg':
      return weight * 2.20462;
    case 'g':
      return weight / 453.592;
    default:
      return weight;
  }
}

function HarvestValueEditor({
  cropId,
  pricePerLb,
  avgLbPerCount,
}: {
  cropId: number;
  pricePerLb: number | null;
  avgLbPerCount: number | null;
}) {
  const router = useRouter();
  async function save(patch: {
    price_market_per_lb?: number | null;
    avg_lb_per_count?: number | null;
  }) {
    await createClient().from('crops').update(patch).eq('id', cropId);
    router.refresh();
  }
  return (
    <section className="card panel space-y-3">
      <div className="panel-h !mb-0">
        <Info className="size-[18px] text-ink-3" />
        <h3>Harvest value</h3>
      </div>
      <MoneyPerLbField value={pricePerLb} onSave={(v) => save({ price_market_per_lb: v })} />
      <ContainerCalc onApply={(perLb) => save({ price_market_per_lb: perLb })} />
      <WeightEachField value={avgLbPerCount} onSave={(v) => save({ avg_lb_per_count: v })} />
    </section>
  );
}

function MoneyPerLbField({
  value,
  onSave,
}: {
  value: number | null;
  onSave: (v: number | null) => void;
}) {
  const [local, setLocal] = useState(value?.toString() ?? '');
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    setLocal(value?.toString() ?? '');
  }
  function commit() {
    const n = parseFloat(local);
    const next = isNaN(n) || n < 0 ? null : n;
    if (next !== value) onSave(next);
  }
  return (
    <label className="block">
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
        Price per pound
      </span>
      <span className="mt-1 flex items-center gap-1 rounded-lg bg-card px-2.5 py-2 ring-1 ring-border/60 focus-within:ring-2 focus-within:ring-ring/50">
        <span className="text-sm text-muted-foreground">$</span>
        <input
          type="text"
          inputMode="decimal"
          placeholder="—"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
          className="min-w-0 flex-1 bg-transparent text-sm tabular-nums focus:outline-none"
        />
        <span className="text-xs text-muted-foreground/60">/ lb</span>
      </span>
    </label>
  );
}

function ContainerCalc({ onApply }: { onApply: (perLb: number) => void }) {
  const [qty, setQty] = useState('');
  const [unit, setUnit] = useState('oz');
  const [price, setPrice] = useState('');
  const q = parseFloat(qty);
  const p = parseFloat(price);
  const lb = !isNaN(q) && q > 0 ? toLbDetail(q, unit) : null;
  const perLb = lb != null && !isNaN(p) && p >= 0 ? p / lb : null;
  return (
    <div className="space-y-2 rounded-lg bg-muted/40 p-2.5 ring-1 ring-border/50">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
        Set from a store price
      </p>
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <input
          inputMode="decimal"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="16"
          className="h-8 w-12 rounded-md bg-card px-1.5 text-right tabular-nums ring-1 ring-border/60 focus:outline-none focus:ring-2 focus:ring-ring/50"
        />
        <select
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          className="h-8 rounded-md bg-card px-1 text-xs ring-1 ring-border/60 focus:outline-none"
        >
          {WEIGHT_UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <span className="text-muted-foreground/70">for</span>
        <span className="flex h-8 items-center rounded-md bg-card px-1.5 ring-1 ring-border/60 focus-within:ring-2 focus-within:ring-ring/50">
          <span className="text-xs text-muted-foreground">$</span>
          <input
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="3.98"
            className="w-14 bg-transparent text-sm tabular-nums focus:outline-none"
          />
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs tabular-nums text-muted-foreground">
          {perLb != null ? `= $${perLb.toFixed(2)} / lb` : 'enter weight + price'}
        </span>
        <button
          type="button"
          disabled={perLb == null}
          onClick={() => {
            if (perLb != null) onApply(Number(perLb.toFixed(4)));
          }}
          className="text-xs font-medium text-leaf hover:text-leaf-dk disabled:cursor-not-allowed disabled:opacity-40"
        >
          Use this
        </button>
      </div>
    </div>
  );
}

function WeightEachField({
  value,
  onSave,
}: {
  value: number | null;
  onSave: (v: number | null) => void;
}) {
  const [local, setLocal] = useState(value?.toString() ?? '');
  const [unit, setUnit] = useState('lb');
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    setLocal(value?.toString() ?? '');
    setUnit('lb');
  }
  function commit() {
    const n = parseFloat(local);
    if (isNaN(n) || n <= 0) {
      if (value != null) onSave(null);
      else setLocal('');
      return;
    }
    const lb = Number(toLbDetail(n, unit).toFixed(4));
    if (lb !== value) onSave(lb);
  }
  return (
    <label className="block">
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/60">
        Avg weight each
      </span>
      <span className="mt-1 flex items-center gap-1.5">
        <span className="flex flex-1 items-center rounded-lg bg-card px-2.5 py-2 ring-1 ring-border/60 focus-within:ring-2 focus-within:ring-ring/50">
          <input
            type="text"
            inputMode="decimal"
            placeholder="—"
            value={local}
            onChange={(e) => setLocal(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
            }}
            className="min-w-0 flex-1 bg-transparent text-sm tabular-nums focus:outline-none"
          />
        </span>
        <select
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          className="h-[38px] rounded-lg bg-card px-1.5 text-xs ring-1 ring-border/60 focus:outline-none"
        >
          {WEIGHT_UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </span>
      <span className="mt-1 block text-[10px] text-muted-foreground/50">
        Used to value picks logged by the count (e.g. &ldquo;3 ct&rdquo;).
      </span>
    </label>
  );
}
