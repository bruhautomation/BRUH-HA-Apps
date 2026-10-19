import type {
  Product,
  ActiveIngredient,
  Crop,
  Variety,
  VarietyStage,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
  CropGroup,
  TankMixRule,
} from './database.types';
import { INTERLOCK } from '@/config/thresholds';

export type InterlockSeverity = 'block' | 'warning';

export interface InterlockResult {
  severity: InterlockSeverity;
  rule: string;
  explanation: string;
}

export interface InterlockState {
  selectedProducts: Product[];
  selectedCropIds: number[];
  // Lookup maps
  crops: Crop[];
  cropGroups: CropGroup[];
  varieties: Variety[];
  varietyStages: VarietyStage[];
  productIngredientMap: Map<number, ActiveIngredient[]>;
  tankMixRules: TankMixRule[];
  // History
  sprayEvents: SprayEvent[];
  sprayEventProducts: SprayEventProduct[];
  sprayEventCrops: SprayEventCrop[];
  // Optional full product catalog — lets the separation warning resolve
  // product brands when the conflicting product was applied earlier and is
  // no longer in selectedProducts.
  allProducts?: Product[];
  // Weather
  currentTemp: number | null;
  forecastHighTemp: number | null;
  windSpeed: number | null;
  hoursUntilRain: number | null;
  // Time
  now: Date;
}

/**
 * Evaluate all safety interlocks. Returns array of blocks and warnings.
 * Blocks prevent spraying. Warnings are shown but don't prevent it.
 */
export function evaluateInterlocks(state: InterlockState): InterlockResult[] {
  const results: InterlockResult[] = [];

  results.push(...checkPollinatorInterlock(state));
  results.push(...checkCaptanOnPears(state));
  results.push(...checkCopperAfterBudBreak(state));
  results.push(...checkCarbarylPostPetalFall(state));
  results.push(...checkSulfurHighTemp(state));
  results.push(...checkStreptomycinOutsideBloom(state));
  results.push(...checkSingleSiteBare(state));
  results.push(...checkTankMixRules(state));
  results.push(...checkSeparationRules(state));
  results.push(...checkPHIViolation(state));
  results.push(...checkWeatherWarnings(state));
  results.push(...checkRotationWarnings(state));
  results.push(...checkMaxAppsWarning(state));

  return results;
}

// -- HARD BLOCKS --

function checkPollinatorInterlock(state: InterlockState): InterlockResult[] {
  const hasInsecticide = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.type === 'insecticide');
  });
  if (!hasInsecticide) return [];

  // Check which varieties in the entire orchard are in bloom (orchard-wide
  // bloom block). Index active crops + variety stages once so this is a single
  // O(n) pass rather than re-running the same `.find()` lookups twice.
  const activeCropIds = new Set(state.crops.filter((c) => c.is_active).map((c) => c.id));
  const stageByVariety = new Map<number, string>();
  for (const s of state.varietyStages) {
    if (!stageByVariety.has(s.variety_id)) stageByVariety.set(s.variety_id, s.stage);
  }
  const bloomNames = state.varieties
    .filter((v) => activeCropIds.has(v.crop_id) && stageByVariety.get(v.id) === 'bloom')
    .map((v) => v.name);

  if (bloomNames.length > 0) {
    return [
      {
        severity: 'block',
        rule: 'Pollinator interlock',
        explanation: `All insecticides blocked orchard-wide during bloom. Currently in bloom: ${bloomNames.join(', ')}.`,
      },
    ];
  }
  return [];
}

function checkCaptanOnPears(state: InterlockState): InterlockResult[] {
  const hasCaptanSelected = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.name.toLowerCase() === 'captan');
  });
  if (!hasCaptanSelected) return [];

  const pearCrops = state.crops.filter(
    (c) => state.selectedCropIds.includes(c.id) && c.name.toLowerCase().includes('pear')
  );

  if (pearCrops.length > 0) {
    return [
      {
        severity: 'block',
        rule: 'Captan on pears',
        explanation:
          'Captan is phytotoxic to pears. Remove pears from this spray or choose a different fungicide.',
      },
    ];
  }
  return [];
}

function checkCopperAfterBudBreak(state: InterlockState): InterlockResult[] {
  const hasCopper = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.name.toLowerCase().includes('copper'));
  });
  if (!hasCopper) return [];

  const cherryCrops = state.crops.filter(
    (c) => state.selectedCropIds.includes(c.id) && c.name.toLowerCase().includes('cherr')
  );
  if (cherryCrops.length === 0) return [];

  const cherryVarieties = state.varieties.filter((v) =>
    cherryCrops.some((c) => c.id === v.crop_id)
  );
  const pastDormant = cherryVarieties.some((v) => {
    const vs = state.varietyStages.find((s) => s.variety_id === v.id);
    return vs && vs.stage !== 'dormant';
  });

  if (pastDormant) {
    return [
      {
        severity: 'block',
        rule: 'Copper after bud break on cherries',
        explanation:
          'Copper is phytotoxic to cherries after dormancy. Remove cherries or switch products.',
      },
    ];
  }
  return [];
}

function checkCarbarylPostPetalFall(state: InterlockState): InterlockResult[] {
  const hasCarbaryl = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.name.toLowerCase() === 'carbaryl');
  });
  if (!hasCarbaryl) return [];

  const appleCrops = state.crops.filter(
    (c) => state.selectedCropIds.includes(c.id) && c.name.toLowerCase().includes('apple')
  );
  if (appleCrops.length === 0) return [];

  // Check if any apple variety is within 30 days of petal fall
  const appleVarieties = state.varieties.filter((v) => appleCrops.some((c) => c.id === v.crop_id));
  const recentPetalFall = appleVarieties.some((v) => {
    const vs = state.varietyStages.find((s) => s.variety_id === v.id);
    return vs && (vs.stage === 'petal_fall' || vs.stage === 'fruit_set');
  });

  if (recentPetalFall) {
    return [
      {
        severity: 'block',
        rule: 'Carbaryl post-petal-fall',
        explanation:
          'Carbaryl causes excessive fruit thinning on apples within 30 days of petal fall.',
      },
    ];
  }
  return [];
}

function checkSulfurHighTemp(state: InterlockState): InterlockResult[] {
  const hasSulfur = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.name.toLowerCase().includes('sulfur'));
  });
  if (!hasSulfur) return [];

  const highTemp = state.forecastHighTemp ?? state.currentTemp;
  if (highTemp && highTemp > INTERLOCK.sulfurMaxTemp) {
    return [
      {
        severity: 'block',
        rule: 'Sulfur high temp',
        explanation: `Sulfur causes phytotoxicity above ${INTERLOCK.sulfurMaxTemp}\u00b0F. Forecast high: ${highTemp}\u00b0F.`,
      },
    ];
  }
  return [];
}

function checkStreptomycinOutsideBloom(state: InterlockState): InterlockResult[] {
  const hasStrep = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.name.toLowerCase().includes('streptomycin'));
  });
  if (!hasStrep) return [];

  const pomeStone = state.crops.filter((c) => {
    if (!state.selectedCropIds.includes(c.id)) return false;
    const name = c.name.toLowerCase();
    return name.includes('apple') || name.includes('pear');
  });
  if (pomeStone.length === 0) return [];

  const allInBloom = pomeStone.every((c) => {
    const vs = state.varieties
      .filter((v) => v.crop_id === c.id)
      .some((v) => {
        const s = state.varietyStages.find((s) => s.variety_id === v.id);
        return s?.stage === 'bloom';
      });
    return vs;
  });

  if (!allInBloom) {
    return [
      {
        severity: 'block',
        rule: 'Streptomycin outside bloom',
        explanation: 'Streptomycin is labeled for fire blight control during bloom only.',
      },
    ];
  }
  return [];
}

function checkSingleSiteBare(state: InterlockState): InterlockResult[] {
  const singleSiteProducts = state.selectedProducts.filter((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => i.is_single_site);
  });
  if (singleSiteProducts.length === 0) return [];

  const hasMultiSite = state.selectedProducts.some((p) => {
    const ingredients = state.productIngredientMap.get(p.id) || [];
    return ingredients.some((i) => !i.is_single_site && i.type === 'fungicide');
  });

  if (!hasMultiSite) {
    const names = singleSiteProducts.map((p) => p.brand).join(', ');
    return [
      {
        severity: 'warning',
        rule: 'Resistance management',
        explanation: `${names} ${singleSiteProducts.length > 1 ? 'are' : 'is'} single-site. Consider adding a multi-site partner (e.g., Captan) to slow resistance development.`,
      },
    ];
  }
  return [];
}

function checkTankMixRules(state: InterlockState): InterlockResult[] {
  const results: InterlockResult[] = [];
  const selectedIds = state.selectedProducts.map((p) => p.id);

  for (const rule of state.tankMixRules) {
    if (rule.rule_type !== 'block') continue;
    const aSelected = selectedIds.includes(rule.product_a_id);
    const bSelected = selectedIds.includes(rule.product_b_id);
    if (aSelected && bSelected) {
      const prodA = state.selectedProducts.find((p) => p.id === rule.product_a_id);
      const prodB = state.selectedProducts.find((p) => p.id === rule.product_b_id);
      results.push({
        severity: 'block',
        rule: 'Tank mix incompatibility',
        explanation:
          rule.explanation ||
          `${prodA?.brand} and ${prodB?.brand} cannot be mixed in the same tank.`,
      });
    }
  }
  return results;
}

function checkSeparationRules(state: InterlockState): InterlockResult[] {
  const results: InterlockResult[] = [];
  const selectedIds = state.selectedProducts.map((p) => p.id);

  for (const rule of state.tankMixRules) {
    if (rule.rule_type !== 'separation') continue;
    if (!rule.separation_days) continue;

    // Check if one product is selected and the other was recently sprayed
    for (const selectedId of selectedIds) {
      const otherId =
        selectedId === rule.product_a_id
          ? rule.product_b_id
          : selectedId === rule.product_b_id
            ? rule.product_a_id
            : null;
      if (!otherId) continue;

      // Find last spray of the other product
      const lastSpray = findLastSprayOfProduct(otherId, state);
      if (!lastSpray) continue;

      const daysSince = daysBetween(new Date(lastSpray.date), state.now);
      if (daysSince < rule.separation_days) {
        const selected = state.selectedProducts.find((p) => p.id === selectedId);
        const otherProduct = [...state.selectedProducts, ...getProductsFromEvents(state)].find(
          (p) => p.id === otherId
        );
        results.push({
          severity: 'block',
          rule: 'Separation interval',
          explanation:
            rule.explanation ||
            `${selected?.brand} requires ${rule.separation_days}-day separation from ${otherProduct?.brand || 'a recently applied product'}. Last applied ${daysSince} days ago.`,
        });
      }
    }
  }
  return results;
}

function checkPHIViolation(_state: InterlockState): InterlockResult[] {
  // This would need harvest date estimates from phenology_calendar.
  // For now, return empty — will be fully wired when phenology data is available.
  return [];
}

// -- SOFT WARNINGS --

function checkWeatherWarnings(state: InterlockState): InterlockResult[] {
  const results: InterlockResult[] = [];

  if (
    state.windSpeed &&
    state.windSpeed >= INTERLOCK.windWarning &&
    state.windSpeed <= INTERLOCK.windBlock
  ) {
    results.push({
      severity: 'warning',
      rule: 'Marginal wind',
      explanation: `Wind speed ${state.windSpeed} mph — spray effectiveness may be reduced.`,
    });
  }
  if (state.windSpeed && state.windSpeed > INTERLOCK.windBlock) {
    results.push({
      severity: 'block',
      rule: 'High wind',
      explanation: `Wind speed ${state.windSpeed} mph — too windy to spray safely.`,
    });
  }
  if (state.hoursUntilRain !== null && state.hoursUntilRain > 0 && state.hoursUntilRain <= 24) {
    results.push({
      severity: 'warning',
      rule: 'Rain approaching',
      explanation: `Rain expected in ${state.hoursUntilRain} hours. Ensure products are rain-fast before then.`,
    });
  }
  if (state.currentTemp !== null) {
    if (state.currentTemp < INTERLOCK.tempLowWarning) {
      results.push({
        severity: 'warning',
        rule: 'Low temperature',
        explanation: `Current temp ${state.currentTemp}\u00b0F — some products may not be effective below ${INTERLOCK.tempLowWarning}\u00b0F.`,
      });
    }
    if (state.currentTemp > INTERLOCK.tempHighWarning) {
      results.push({
        severity: 'warning',
        rule: 'High temperature',
        explanation: `Current temp ${state.currentTemp}\u00b0F — phytotoxicity risk increases above ${INTERLOCK.tempHighWarning}\u00b0F.`,
      });
    }
  }

  return results;
}

function checkRotationWarnings(state: InterlockState): InterlockResult[] {
  const results: InterlockResult[] = [];

  for (const product of state.selectedProducts) {
    const ingredients = state.productIngredientMap.get(product.id) || [];
    for (const ingredient of ingredients) {
      if (!ingredient.frac_irac_hrac_group) continue;

      // Count consecutive uses of same group on each selected crop
      for (const cropId of state.selectedCropIds) {
        const count = countConsecutiveGroupUses(ingredient.frac_irac_hrac_group, cropId, state);
        if (count >= 2) {
          // This would be the 3rd consecutive use
          const crop = state.crops.find((c) => c.id === cropId);
          results.push({
            severity: 'warning',
            rule: 'FRAC/IRAC rotation',
            explanation: `Group ${ingredient.frac_irac_hrac_group} has been used ${count} times consecutively on ${crop?.name}. Adding another increases resistance risk.`,
          });
        }
      }
    }
  }

  return results;
}

function checkMaxAppsWarning(_state: InterlockState): InterlockResult[] {
  // Would check crop_uses.max_apps_per_season against spray history counts.
  // Requires crop_uses data to be passed in — will wire when pages are built.
  return [];
}

// -- HELPERS --

function findLastSprayOfProduct(productId: number, state: InterlockState): SprayEvent | null {
  const eventIds = state.sprayEventProducts
    .filter((ep) => ep.product_id === productId)
    .map((ep) => ep.spray_event_id);

  const events = state.sprayEvents
    .filter((e) => eventIds.includes(e.id))
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  return events[0] || null;
}

function getProductsFromEvents(state: InterlockState): Product[] {
  // Resolve sprayed product IDs to full product rows when the caller passed
  // allProducts. Without it, we silently return nothing — the caller falls
  // back to a generic message.
  if (!state.allProducts || state.allProducts.length === 0) return [];
  const sprayedIds = new Set(state.sprayEventProducts.map((ep) => ep.product_id));
  return state.allProducts.filter((p) => sprayedIds.has(p.id));
}

function daysBetween(a: Date, b: Date): number {
  return Math.floor(Math.abs(b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

function countConsecutiveGroupUses(group: string, cropId: number, state: InterlockState): number {
  // Get spray events for this crop, sorted most recent first
  const cropEventIds = new Set(
    state.sprayEventCrops.filter((ec) => ec.crop_id === cropId).map((ec) => ec.spray_event_id)
  );
  const events = state.sprayEvents
    .filter((e) => cropEventIds.has(e.id))
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  let count = 0;
  for (const event of events) {
    const prods = state.sprayEventProducts.filter((ep) => ep.spray_event_id === event.id);
    const usedGroup = prods.some((ep) => {
      const ingredients = state.productIngredientMap.get(ep.product_id) || [];
      return ingredients.some((i) => i.frac_irac_hrac_group === group);
    });
    if (usedGroup) {
      count++;
    } else {
      break; // Streak broken
    }
  }
  return count;
}
