import { createClient } from '@/lib/db/server';
import {
  fetchVarieties,
  fetchCrops,
  fetchCropGroups,
  fetchSprayHistory,
  fetchInventory,
  fetchProducts,
  fetchCropUses,
} from '@/lib/queries';
import { sprayEventCost } from '@/lib/spray-cost';
import { SPRAYER } from '@/config/thresholds';
import { HarvestTracker } from '@/components/harvest-tracker';
import { HarvestCalendar } from '@/components/harvest-calendar';
import { HarvestStatusCards, type StatusCrop } from '@/components/harvest-status-cards';
import { computeCropPhi } from '@/lib/phi';
import { parseHarvestWindow } from '@/lib/harvest-windows';
import { VARIETY_CATALOG } from '@/lib/variety-catalog';

export const dynamic = 'force-dynamic';

export default async function HarvestPage() {
  const supabase = await createClient();

  const [
    varieties,
    crops,
    cropGroups,
    { data: harvests },
    sprayHistory,
    inventory,
    products,
    cropUses,
  ] = await Promise.all([
    fetchVarieties(),
    fetchCrops(),
    fetchCropGroups(),
    supabase.from('harvests').select('*').order('harvested_at', { ascending: false }),
    fetchSprayHistory(),
    fetchInventory(),
    fetchProducts(),
    fetchCropUses(),
  ]);

  // Season spray cost — only the products actually applied in THIS season's spray
  // events (not all-time, and not the full purchase price of what's in inventory).
  const seasonYear = new Date().getFullYear();
  const invByProduct = new Map(inventory.map((i) => [i.product_id, i] as const));
  const sprayCost = sprayHistory.sprayEvents
    .filter((ev) => new Date(ev.date + 'T12:00:00').getFullYear() === seasonYear)
    .reduce((sum, ev) => {
      const eps = sprayHistory.sprayEventProducts.filter((ep) => ep.spray_event_id === ev.id);
      return sum + sprayEventCost(eps, invByProduct, ev.volume_gallons ?? SPRAYER.gallons).cost;
    }, 0);

  // Pre-harvest interval (PHI): for each crop, the sprays whose product carries a
  // PHI for that crop's group — used to warn when a pick is logged too soon after.
  const cropById = new Map(crops.map((c) => [c.id, c] as const));
  const productById = new Map(products.map((p) => [p.id, p] as const));
  const phiByProductGroup = new Map<string, number>();
  for (const cu of cropUses)
    if (cu.phi_days != null)
      phiByProductGroup.set(`${cu.product_id}:${cu.crop_group_id}`, cu.phi_days);
  const phiSprays: Record<number, { date: string; phiDays: number; brand: string }[]> = {};
  for (const ev of sprayHistory.sprayEvents) {
    const evProducts = sprayHistory.sprayEventProducts.filter((ep) => ep.spray_event_id === ev.id);
    for (const ec of sprayHistory.sprayEventCrops.filter((x) => x.spray_event_id === ev.id)) {
      const crop = cropById.get(ec.crop_id);
      if (!crop?.crop_group_id) continue;
      for (const ep of evProducts) {
        const phi = phiByProductGroup.get(`${ep.product_id}:${crop.crop_group_id}`);
        if (phi != null && phi > 0) {
          (phiSprays[ec.crop_id] ??= []).push({
            date: ev.date,
            phiDays: phi,
            brand: productById.get(ep.product_id)?.brand ?? 'a spray',
          });
        }
      }
    }
  }

  // ── Harvest status cards (Do not harvest / Ready / Developing) ──
  const cropGroupName = new Map(cropGroups.map((g) => [g.id, g.name] as const));
  const now = new Date();
  const month = now.getMonth();
  const fmtShort = (d: Date | null) =>
    d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
  const inWindowNow = (m: number, r: { startMonth: number; endMonth: number }) =>
    r.startMonth <= r.endMonth
      ? m >= r.startMonth && m <= r.endMonth
      : m >= r.startMonth || m <= r.endMonth;
  const harvestWindow = (
    cropId: number
  ): { ready: boolean; phrase: string | null; hasWindow: boolean } => {
    let hasWindow = false;
    let phrase: string | null = null;
    for (const v of varieties.filter((vv) => vv.crop_id === cropId)) {
      const p = VARIETY_CATALOG[v.name];
      if (!p?.harvestWindow) continue;
      hasWindow = true;
      phrase ??= p.harvestWindow;
      if (parseHarvestWindow(p.harvestWindow).some((r) => inWindowNow(month, r))) {
        return { ready: true, phrase: p.harvestWindow, hasWindow: true };
      }
    }
    return { ready: false, phrase, hasWindow };
  };

  const doNotHarvest: StatusCrop[] = [];
  const ready: StatusCrop[] = [];
  const developing: StatusCrop[] = [];
  for (const crop of crops) {
    const group = crop.crop_group_id ? (cropGroupName.get(crop.crop_group_id) ?? null) : null;
    const phi = computeCropPhi(
      crop.id,
      crop.crop_group_id,
      sprayHistory.sprayEvents,
      sprayHistory.sprayEventProducts,
      sprayHistory.sprayEventCrops,
      phiByProductGroup,
      (id) => productById.get(id)?.brand ?? 'a spray',
      now
    );
    const w = harvestWindow(crop.id);
    // A PHI is only worth flagging in season — out of season the crop is just developing.
    if (phi.active && w.ready) {
      doNotHarvest.push({
        id: crop.id,
        name: crop.name,
        group,
        note: `Safe ${fmtShort(phi.endDate)} · ${phi.daysLeft}d left`,
      });
      continue;
    }
    if (w.ready) ready.push({ id: crop.id, name: crop.name, group, note: w.phrase ?? 'In season' });
    else if (w.hasWindow)
      developing.push({ id: crop.id, name: crop.name, group, note: w.phrase ?? 'Upcoming' });
  }

  return (
    <div className="page">
      <div className="section-title">
        <h2>Harvest</h2>
        <span className="meta">Track your yield</span>
      </div>
      <div className="mx-auto max-w-3xl">
        <HarvestStatusCards doNotHarvest={doNotHarvest} ready={ready} developing={developing} />
        <HarvestTracker
          harvests={harvests ?? []}
          varieties={varieties}
          crops={crops}
          cropGroups={cropGroups}
          sprayCost={sprayCost}
          phiSprays={phiSprays}
        />

        {/* Expected harvest windows — reference, kept at the bottom */}
        <div className="mt-8">
          <HarvestCalendar crops={crops} varieties={varieties} cropGroups={cropGroups} />
        </div>
      </div>
    </div>
  );
}
