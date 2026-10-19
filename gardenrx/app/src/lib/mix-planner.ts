import type {
  Crop,
  Product,
  ActiveIngredient,
  CropGroup,
  CropUse,
  TankMixRule,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
  IngredientType,
} from './database.types';
import { getSprayRecordsForCrop, computeCoverage } from './protection';
import { ACTIVE_PRODUCT_IDS } from '@/config/active-products';

export interface CropNeed {
  crop: Crop;
  cropGroup: CropGroup | undefined;
  urgency: 'red' | 'yellow' | 'green' | 'none';
  fungicideStatus: 'red' | 'yellow' | 'green' | null;
  insecticideStatus: 'red' | 'yellow' | 'green' | null;
  needsFungicide: boolean;
  needsInsecticide: boolean;
  inBloom: boolean;
  stage: string;
}

export interface MixProduct {
  product: Product;
  ingredients: ActiveIngredient[];
  coverageType: IngredientType;
  rateMin: number | null;
  rateMax: number | null;
  rateUnit: string;
  suggestedRate: number;
  role: 'multi-site' | 'single-site' | 'insecticide';
}

export interface MixPlan {
  id: string;
  crops: Crop[];
  cropGroupId: number; // primary group (for backwards compat)
  cropGroupIds: number[]; // all groups in this merged mix
  cropGroupName: string;
  products: MixProduct[];
  coverageTypes: IngredientType[];
}

export interface AlternativeProduct {
  product: Product;
  ingredients: ActiveIngredient[];
  coverageType: IngredientType;
  rateMin: number | null;
  rateMax: number | null;
  rateUnit: string;
  role: 'multi-site' | 'single-site' | 'insecticide';
  reason: string;
  blocked: boolean;
  blockReason?: string;
}

interface PlannerData {
  crops: Crop[];
  products: Product[];
  cropGroups: CropGroup[];
  cropUses: CropUse[];
  tankMixRules: TankMixRule[];
  ingredientMap: Map<number, ActiveIngredient[]>;
  sprayEvents: SprayEvent[];
  sprayEventProducts: SprayEventProduct[];
  sprayEventCrops: SprayEventCrop[];
  precipHistory: Array<{ time: string; precipitation: number }>;
  inventoryProductIds?: number[]; // If set, only use products from inventory
  varietyStages: Array<{ variety_id: number; stage: string }>;
  varieties: Array<{ id: number; crop_id: number; name: string }>;
}

/**
 * Analyze crop coverage needs.
 */
export function analyzeCropNeeds(selectedCropIds: number[], data: PlannerData): CropNeed[] {
  const now = new Date();

  return selectedCropIds
    .map((cropId) => {
      const crop = data.crops.find((c) => c.id === cropId)!;
      const cropVarieties = data.varieties.filter((v) => v.crop_id === cropId);
      const inBloom = cropVarieties.some((v) => {
        const vs = data.varietyStages.find((s) => s.variety_id === v.id);
        return vs?.stage === 'bloom';
      });
      const dominantStage =
        data.varietyStages.find((vs) => cropVarieties.some((v) => v.id === vs.variety_id))?.stage ??
        'dormant';

      const sprayRecords = getSprayRecordsForCrop(
        cropId,
        data.sprayEvents,
        data.sprayEventProducts,
        data.sprayEventCrops,
        data.products,
        data.ingredientMap
      );

      const fCov = computeCoverage(sprayRecords, 'fungicide', now, data.precipHistory);
      const iCov = computeCoverage(sprayRecords, 'insecticide', now, data.precipHistory);

      const fStatus = fCov?.status ?? null;
      const iStatus = iCov?.status ?? null;

      const needsFungicide = fStatus === 'red' || fStatus === 'yellow' || fStatus === null;
      const needsInsecticide = iStatus === 'red' && !inBloom;

      const urgency: CropNeed['urgency'] =
        fStatus === 'red' || iStatus === 'red'
          ? 'red'
          : fStatus === 'yellow' || iStatus === 'yellow'
            ? 'yellow'
            : fStatus === 'green' || iStatus === 'green'
              ? 'green'
              : 'none';

      return {
        crop,
        cropGroup: data.cropGroups.find((g) => g.id === crop.crop_group_id),
        urgency,
        fungicideStatus: fStatus,
        insecticideStatus: iStatus,
        needsFungicide,
        needsInsecticide,
        inBloom,
        stage: dominantStage,
      };
    })
    .sort((a, b) => {
      const order = { red: 0, yellow: 1, none: 2, green: 3 };
      return order[a.urgency] - order[b.urgency];
    });
}

/**
 * Generate recommended mix plans that MINIMIZE the number of tank mixes.
 *
 * Strategy:
 * 1. For each crop group that needs spraying, determine ideal products.
 * 2. Find groups that can share the exact same products (because those
 *    products are labeled for all those groups). Merge them into one mix.
 * 3. Groups that can't share get their own mix.
 *
 * This means if Pome Fruit and Stone Fruit both need Captan + Immunox,
 * and both products are labeled for both groups, it's one tank mix.
 */
export function generateMixPlans(
  needs: CropNeed[],
  data: PlannerData,
  overrides: Map<string, number> = new Map()
): MixPlan[] {
  // Filter crop uses to only products in inventory (if set), and always exclude
  // deactivated products so the planner never suggests something the user can't
  // act on.
  const activeCropUses = data.cropUses.filter((cu) => ACTIVE_PRODUCT_IDS.has(cu.product_id));
  const availableCropUses =
    data.inventoryProductIds && data.inventoryProductIds.length > 0
      ? activeCropUses.filter((cu) => data.inventoryProductIds!.includes(cu.product_id))
      : activeCropUses;

  // Group crops by crop_group_id
  const grouped = new Map<number, CropNeed[]>();
  for (const cn of needs) {
    if (!cn.needsFungicide && !cn.needsInsecticide) continue;
    const gid = cn.crop.crop_group_id;
    if (!gid) continue;
    grouped.set(gid, [...(grouped.get(gid) ?? []), cn]);
  }

  // For each group, determine the ideal product set
  interface GroupPlan {
    groupId: number;
    groupName: string;
    crops: CropNeed[];
    productIds: number[]; // sorted product IDs for this group
    products: MixProduct[];
    coverageTypes: IngredientType[];
    hasPear: boolean;
  }

  const groupPlans: GroupPlan[] = [];

  for (const [groupId, groupCrops] of grouped) {
    const needsFungicide = groupCrops.some((c) => c.needsFungicide);
    const needsInsecticide = groupCrops.some((c) => c.needsInsecticide);
    const anyBloom = groupCrops.some((c) => c.inBloom);
    const hasPear = groupCrops.some((c) => c.crop.name.toLowerCase().includes('pear'));
    const group = data.cropGroups.find((g) => g.id === groupId);

    const planProducts: MixProduct[] = [];
    const coverageTypes: IngredientType[] = [];

    if (needsFungicide) {
      coverageTypes.push('fungicide');
      const fungicideUses = availableCropUses.filter(
        (cu) =>
          cu.crop_group_id === groupId &&
          data.ingredientMap.get(cu.product_id)?.some((i) => i.type === 'fungicide')
      );

      const multiSiteOverride = overrides.get(`${groupId}-multi-site`);
      const singleSiteOverride = overrides.get(`${groupId}-single-site`);

      const multiSiteUse = multiSiteOverride
        ? fungicideUses.find((cu) => cu.product_id === multiSiteOverride)
        : findBestMultiSite(fungicideUses, data, hasPear);

      if (multiSiteUse) {
        const product = data.products.find((p) => p.id === multiSiteUse!.product_id)!;
        planProducts.push({
          product,
          ingredients: data.ingredientMap.get(product.id) ?? [],
          coverageType: 'fungicide',
          rateMin: multiSiteUse.rate_min,
          rateMax: multiSiteUse.rate_max,
          rateUnit: multiSiteUse.rate_unit,
          suggestedRate: multiSiteUse.rate_max ?? multiSiteUse.rate_min ?? 1,
          role: 'multi-site',
        });
      }

      const singleSiteUse = singleSiteOverride
        ? fungicideUses.find((cu) => cu.product_id === singleSiteOverride)
        : findBestSingleSite(fungicideUses, data, multiSiteUse?.product_id ?? null);

      if (singleSiteUse && multiSiteUse) {
        if (!isBlocked(multiSiteUse.product_id, singleSiteUse.product_id, data.tankMixRules)) {
          const product = data.products.find((p) => p.id === singleSiteUse!.product_id)!;
          planProducts.push({
            product,
            ingredients: data.ingredientMap.get(product.id) ?? [],
            coverageType: 'fungicide',
            rateMin: singleSiteUse.rate_min,
            rateMax: singleSiteUse.rate_max,
            rateUnit: singleSiteUse.rate_unit,
            suggestedRate: singleSiteUse.rate_max ?? singleSiteUse.rate_min ?? 1,
            role: 'single-site',
          });
        }
      }
    }

    if (needsInsecticide && !anyBloom) {
      coverageTypes.push('insecticide');
      const insecticideUses = availableCropUses.filter(
        (cu) =>
          cu.crop_group_id === groupId &&
          data.ingredientMap.get(cu.product_id)?.some((i) => i.type === 'insecticide')
      );
      const insecticideOverride = overrides.get(`${groupId}-insecticide`);
      const use = insecticideOverride
        ? insecticideUses.find((cu) => cu.product_id === insecticideOverride)
        : insecticideUses[0];
      if (use) {
        const product = data.products.find((p) => p.id === use.product_id)!;
        planProducts.push({
          product,
          ingredients: data.ingredientMap.get(product.id) ?? [],
          coverageType: 'insecticide',
          rateMin: use.rate_min,
          rateMax: use.rate_max,
          rateUnit: use.rate_unit,
          suggestedRate: use.rate_max ?? use.rate_min ?? 1,
          role: 'insecticide',
        });
      }
    }

    if (planProducts.length > 0) {
      groupPlans.push({
        groupId,
        groupName: group?.name ?? 'Unknown',
        crops: groupCrops,
        productIds: planProducts.map((p) => p.product.id).sort((a, b) => a - b),
        products: planProducts,
        coverageTypes,
        hasPear,
      });
    }
  }

  // ── Merge groups that use the same products ──
  // Two groups can merge if:
  //   1. They selected the same product IDs
  //   2. Every product is actually labeled for ALL the groups being merged
  const merged: MixPlan[] = [];
  const used = new Set<number>(); // groupIds already merged

  for (let i = 0; i < groupPlans.length; i++) {
    if (used.has(groupPlans[i].groupId)) continue;
    const base = groupPlans[i];
    const productKey = base.productIds.join(',');

    // Find other groups with the same product set that can merge
    const compatible = [base];
    for (let j = i + 1; j < groupPlans.length; j++) {
      if (used.has(groupPlans[j].groupId)) continue;
      const candidate = groupPlans[j];
      const candKey = candidate.productIds.join(',');

      if (candKey === productKey) {
        // Verify every product is labeled for the candidate's group too
        const allLabeled = base.productIds.every((pid) =>
          data.cropUses.some(
            (cu) => cu.product_id === pid && cu.crop_group_id === candidate.groupId
          )
        );
        if (allLabeled) {
          compatible.push(candidate);
          used.add(candidate.groupId);
        }
      }
    }
    used.add(base.groupId);

    // Build the merged plan
    const allCrops = compatible.flatMap((g) => g.crops.map((c) => c.crop));
    const allGroupIds = compatible.map((g) => g.groupId);
    const groupNames = compatible.map((g) => g.groupName);
    const coverageTypes = [
      ...new Set(compatible.flatMap((g) => g.coverageTypes)),
    ] as IngredientType[];

    // For rates, find the SAFE OVERLAP across all groups:
    //   - rateMin = highest minimum (safe for the most sensitive crop)
    //   - rateMax = lowest maximum (don't exceed any label max)
    //   - suggestedRate = midpoint of the overlap, biased slightly high for efficacy
    const mergedProducts: MixProduct[] = base.products.map((bp) => {
      const allUses = allGroupIds.flatMap((gid) =>
        data.cropUses.filter((cu) => cu.product_id === bp.product.id && cu.crop_group_id === gid)
      );
      const mins = allUses.map((u) => u.rate_min ?? 0).filter((v) => v > 0);
      const maxes = allUses.map((u) => u.rate_max).filter((v): v is number => v != null);

      const safeMin = mins.length > 0 ? Math.max(...mins) : bp.rateMin;
      const safeMax = maxes.length > 0 ? Math.min(...maxes) : bp.rateMax;

      // Suggested rate: 2/3 of the safe range (biased toward higher efficacy but within limits)
      let suggested: number;
      if (safeMin != null && safeMax != null) {
        suggested = safeMin + (safeMax - safeMin) * 0.67;
      } else {
        suggested = safeMax ?? safeMin ?? bp.suggestedRate;
      }

      return {
        ...bp,
        rateMin: safeMin,
        rateMax: isFinite(safeMax ?? Infinity) ? safeMax : bp.rateMax,
        suggestedRate: Math.round(suggested * 100) / 100,
      };
    });

    merged.push({
      id: `mix-${allGroupIds.join('-')}`,
      crops: allCrops,
      cropGroupId: base.groupId,
      cropGroupIds: allGroupIds,
      cropGroupName: groupNames.join(' + '),
      products: mergedProducts,
      coverageTypes,
    });
  }

  return merged;
}

/**
 * Get alternative products for a specific role in a mix.
 * For merged mixes, the product must be labeled for ALL groups.
 */
export function getAlternatives(
  groupIds: number[],
  role: MixProduct['role'],
  currentProductId: number,
  otherProductIds: number[],
  data: PlannerData,
  hasPear: boolean
): AlternativeProduct[] {
  const type: IngredientType = role === 'insecticide' ? 'insecticide' : 'fungicide';

  // Find products labeled for the first group, restricted to the active set
  const candidateProductIds = new Set(
    data.cropUses
      .filter(
        (cu) =>
          ACTIVE_PRODUCT_IDS.has(cu.product_id) &&
          cu.crop_group_id === groupIds[0] &&
          data.ingredientMap.get(cu.product_id)?.some((i) => i.type === type)
      )
      .map((cu) => cu.product_id)
  );

  // Filter to only products labeled for ALL groups in this mix
  const validProductIds = [...candidateProductIds].filter((pid) =>
    groupIds.every((gid) =>
      data.cropUses.some((cu) => cu.product_id === pid && cu.crop_group_id === gid)
    )
  );

  const alternatives: AlternativeProduct[] = [];

  for (const pid of validProductIds) {
    if (pid === currentProductId) continue;

    const product = data.products.find((p) => p.id === pid);
    if (!product) continue;

    const ings = data.ingredientMap.get(product.id) ?? [];
    const isSingleSite = ings.some((i) => i.is_single_site);

    if (role === 'multi-site' && isSingleSite) continue;
    if (role === 'single-site' && !isSingleSite) continue;

    let blocked = false;
    let blockReason = '';
    for (const otherId of otherProductIds) {
      if (isBlocked(product.id, otherId, data.tankMixRules)) {
        const other = data.products.find((p) => p.id === otherId);
        blocked = true;
        blockReason = `Incompatible with ${other?.brand ?? 'another product'} in this mix`;
        break;
      }
    }

    if (hasPear && ings.some((i) => i.name.toLowerCase() === 'captan')) {
      blocked = true;
      blockReason = 'Captan is phytotoxic to pears';
    }

    // Use rate from first group for display
    const use = data.cropUses.find(
      (cu) => cu.product_id === pid && cu.crop_group_id === groupIds[0]
    );

    const fracGroup = ings.find((i) => i.frac_irac_hrac_group)?.frac_irac_hrac_group;
    let reason = product.brand;
    if (fracGroup) reason += ` (Group ${fracGroup})`;
    if (ings[0]?.mode_of_action) reason += ` — ${ings[0].mode_of_action}`;

    alternatives.push({
      product,
      ingredients: ings,
      coverageType: type,
      rateMin: use?.rate_min ?? null,
      rateMax: use?.rate_max ?? null,
      rateUnit: use?.rate_unit ?? 'fl oz/gal',
      role,
      reason,
      blocked,
      blockReason,
    });
  }

  alternatives.sort((a, b) => {
    if (a.blocked !== b.blocked) return a.blocked ? 1 : -1;
    return a.product.brand.localeCompare(b.product.brand);
  });

  return alternatives;
}

// ── Helpers ──

function findBestMultiSite(
  uses: CropUse[],
  data: PlannerData,
  hasPear: boolean
): CropUse | undefined {
  return uses.find((cu) => {
    const ings = data.ingredientMap.get(cu.product_id) ?? [];
    const isMultiSite = ings.some((i) => !i.is_single_site && i.type === 'fungicide');
    if (!isMultiSite) return false;
    if (hasPear && ings.some((i) => i.name.toLowerCase() === 'captan')) return false;
    return true;
  });
}

function findBestSingleSite(
  uses: CropUse[],
  data: PlannerData,
  multiSiteProductId: number | null
): CropUse | undefined {
  return uses.find((cu) => {
    const ings = data.ingredientMap.get(cu.product_id) ?? [];
    const isSingleSite = ings.some((i) => i.is_single_site && i.type === 'fungicide');
    if (!isSingleSite) return false;
    if (multiSiteProductId && isBlocked(cu.product_id, multiSiteProductId, data.tankMixRules))
      return false;
    return true;
  });
}

function isBlocked(a: number, b: number, rules: TankMixRule[]): boolean {
  return rules.some(
    (r) =>
      r.rule_type === 'block' &&
      ((r.product_a_id === a && r.product_b_id === b) ||
        (r.product_b_id === a && r.product_a_id === b))
  );
}
