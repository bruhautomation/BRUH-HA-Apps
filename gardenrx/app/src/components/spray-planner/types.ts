import type {
  Crop,
  Variety,
  VarietyStage,
  Product,
  ActiveIngredient,
  CropGroup,
  CropUse,
  TankMixRule,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
} from '@/lib/database.types';
import type { CurrentConditions, HourlyForecast, DailyForecast, SprayRating } from '@/lib/weather';

export interface SprayPlannerProps {
  crops: Crop[];
  varieties: Variety[];
  varietyStages: VarietyStage[];
  products: Product[];
  cropGroups: CropGroup[];
  cropUses: CropUse[];
  tankMixRules: TankMixRule[];
  ingredientMap: Record<number, ActiveIngredient[]>;
  sprayEvents: SprayEvent[];
  sprayEventProducts: SprayEventProduct[];
  sprayEventCrops: SprayEventCrop[];
  precipHistory: Array<{ time: string; precipitation: number }>;
  weatherCurrent: CurrentConditions | null;
  weatherHourly: HourlyForecast[];
  weatherDaily: DailyForecast[];
  sprayWindows: Array<{
    time: string;
    rating: SprayRating;
    temp: number;
    windSpeed: number;
    hoursUntilRain: number | null;
  }>;
  currentRating: SprayRating | null;
  queuedSprays: Array<{
    id: number;
    planned_date: string | null;
    notes: string | null;
    created_at: string;
  }>;
  queuedSprayProducts: Array<{
    id: number;
    queued_spray_id: number;
    product_id: number;
    rate_applied: number | null;
    rate_unit: string;
  }>;
  queuedSprayCrops: Array<{ id: number; queued_spray_id: number; crop_id: number }>;
  inventoryProductIds: number[];
  inventoryData: Array<{
    id: number;
    product_id: number;
    quantity: number;
    unit: string;
    bottle_unit: string | null;
    bottle_size: number | null;
    cost_dollars: number | null;
  }>;
  /** Crops to pre-select on load (e.g. handed off from the Today dashboard). */
  initialCropIds?: number[];
}
