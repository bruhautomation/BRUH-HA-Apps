export type IngredientType = "fungicide" | "insecticide" | "herbicide" | "bactericide";
export type RegionType = "planting" | "path" | "structure" | "tree" | "landmark" | "trellis";
export type SignalWord = "CAUTION" | "WARNING" | "DANGER";
export type BeeToxicityTier = "low" | "moderate" | "high";
export type TankRuleType = "separation" | "block" | "warning";
export type ManagementTier = "elite_resistant" | "standard" | "critical" | "sentinel";
export type ThemeMode = "light" | "medium" | "dark" | "auto";
export type FiguresPref = "sans" | "mono";
export type DensityPref = "comfortable" | "compact";
export type PhiAlertPref = "loud" | "badges";
export type PhenologicalStage =
  | "dormant" | "bud_break" | "green_tip" | "tight_cluster" | "pink"
  | "bloom" | "petal_fall" | "fruit_set" | "green_fruit" | "cover_spray"
  | "pre_harvest" | "harvest" | "post_harvest";

export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[];

export interface Database {
  public: {
    Tables: {
      products: {
        Row: {
          id: number;
          brand: string;
          manufacturer: string | null;
          epa_reg_number: string | null;
          formulation: string | null;
          concentration: string | null;
          signal_word: SignalWord | null;
          rei_hours: number | null;
          bee_toxicity: BeeToxicityTier | null;
          rain_fastness_hours: number | null;
          cover_spray_interval_days: number | null;
          rain_tolerance_inches: number | null;
          temp_min: number | null;
          temp_max: number | null;
          ppe_requirements: Json;
          safety_notes: string | null;
          first_aid_summary: string | null;
          source_pdf_hash: string | null;
          price_dollars: number | null;
          price_size: string | null;
          retail_url: string | null;
          image_url: string | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["products"]["Row"], "id" | "created_at" | "image_url"> & {
          id?: number;
          image_url?: string | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["products"]["Insert"]>;
        Relationships: [];
      };
      active_ingredients: {
        Row: {
          id: number;
          name: string;
          type: IngredientType;
          frac_irac_hrac_group: string | null;
          mode_of_action: string | null;
          is_single_site: boolean;
        };
        Insert: Omit<Database["public"]["Tables"]["active_ingredients"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["active_ingredients"]["Insert"]>;
        Relationships: [];
      };
      product_ingredients: {
        Row: {
          product_id: number;
          ingredient_id: number;
          concentration_pct: number | null;
        };
        Insert: Database["public"]["Tables"]["product_ingredients"]["Row"];
        Update: Partial<Database["public"]["Tables"]["product_ingredients"]["Row"]>;
        Relationships: [];
      };
      crop_groups: {
        Row: {
          id: number;
          name: string;
          description: string | null;
        };
        Insert: Omit<Database["public"]["Tables"]["crop_groups"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["crop_groups"]["Insert"]>;
        Relationships: [];
      };
      crop_uses: {
        Row: {
          id: number;
          product_id: number;
          crop_group_id: number;
          rate_min: number | null;
          rate_max: number | null;
          rate_unit: string;
          phi_days: number | null;
          max_apps_per_season: number | null;
          min_interval_days: number | null;
          growth_stage_restrictions: string | null;
          restrictions_text: string | null;
          source_pdf_page: string | null;
        };
        Insert: Omit<Database["public"]["Tables"]["crop_uses"]["Row"], "id" | "rate_unit"> & {
          id?: number;
          rate_unit?: string;
        };
        Update: Partial<Database["public"]["Tables"]["crop_uses"]["Insert"]>;
        Relationships: [];
      };
      tank_mix_rules: {
        Row: {
          id: number;
          product_a_id: number;
          product_b_id: number;
          rule_type: TankRuleType;
          separation_days: number | null;
          explanation: string | null;
          mix_order_note: string | null;
        };
        Insert: Omit<Database["public"]["Tables"]["tank_mix_rules"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["tank_mix_rules"]["Insert"]>;
        Relationships: [];
      };
      crops: {
        Row: {
          id: number;
          name: string;
          crop_group_id: number | null;
          is_active: boolean;
          track_fungicide: boolean;
          track_insecticide: boolean;
          price_market_per_lb: number | null;
          price_grocery_per_lb: number | null;
          avg_lb_per_count: number | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["crops"]["Row"], "id" | "is_active" | "track_fungicide" | "track_insecticide" | "created_at" | "price_market_per_lb" | "price_grocery_per_lb" | "avg_lb_per_count"> & {
          id?: number;
          is_active?: boolean;
          track_fungicide?: boolean;
          track_insecticide?: boolean;
          price_market_per_lb?: number | null;
          price_grocery_per_lb?: number | null;
          avg_lb_per_count?: number | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["crops"]["Insert"]>;
        Relationships: [];
      };
      varieties: {
        Row: {
          id: number;
          name: string;
          crop_id: number;
          is_sentinel: boolean;
          disease_susceptibility: Json;
          management_tier: ManagementTier;
          price_per_lb: number | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["varieties"]["Row"], "id" | "is_sentinel" | "disease_susceptibility" | "management_tier" | "price_per_lb" | "created_at"> & {
          id?: number;
          is_sentinel?: boolean;
          disease_susceptibility?: Json;
          management_tier?: ManagementTier;
          price_per_lb?: number | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["varieties"]["Insert"]>;
        Relationships: [];
      };
      variety_stages: {
        Row: {
          id: number;
          variety_id: number;
          stage: PhenologicalStage;
          is_manual_override: boolean;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["variety_stages"]["Row"], "id" | "stage" | "is_manual_override" | "updated_at"> & {
          id?: number;
          stage?: PhenologicalStage;
          is_manual_override?: boolean;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["variety_stages"]["Insert"]>;
        Relationships: [];
      };
      spray_events: {
        Row: {
          id: number;
          date: string;
          notes: string | null;
          weather_snapshot: Json;
          volume_gallons: number | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["spray_events"]["Row"], "id" | "date" | "weather_snapshot" | "volume_gallons" | "created_at"> & {
          id?: number;
          date?: string;
          weather_snapshot?: Json;
          volume_gallons?: number | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["spray_events"]["Insert"]>;
        Relationships: [];
      };
      spray_event_products: {
        Row: {
          id: number;
          spray_event_id: number;
          product_id: number;
          rate_applied: number | null;
          rate_unit: string;
        };
        Insert: Omit<Database["public"]["Tables"]["spray_event_products"]["Row"], "id" | "rate_unit"> & {
          id?: number;
          rate_unit?: string;
        };
        Update: Partial<Database["public"]["Tables"]["spray_event_products"]["Insert"]>;
        Relationships: [];
      };
      spray_event_crops: {
        Row: {
          id: number;
          spray_event_id: number;
          crop_id: number;
        };
        Insert: Omit<Database["public"]["Tables"]["spray_event_crops"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["spray_event_crops"]["Insert"]>;
        Relationships: [];
      };
      phenology_calendar: {
        Row: {
          id: number;
          crop_group_id: number;
          stage: PhenologicalStage;
          typical_start_date: string;
          typical_end_date: string;
        };
        Insert: Omit<Database["public"]["Tables"]["phenology_calendar"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["phenology_calendar"]["Insert"]>;
        Relationships: [];
      };
      weather_cache: {
        Row: {
          id: number;
          fetched_at: string;
          current_conditions: Json;
          hourly_forecast: Json;
          daily_forecast: Json;
          hourly_precipitation_history: Json;
        };
        Insert: Omit<Database["public"]["Tables"]["weather_cache"]["Row"], "id" | "fetched_at"> & {
          id?: number;
          fetched_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["weather_cache"]["Insert"]>;
        Relationships: [];
      };
      garden_zones: {
        Row: {
          id: number;
          name: string;
          rows: number;
          cols: number;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["garden_zones"]["Row"], "id" | "created_at"> & {
          id?: number;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["garden_zones"]["Insert"]>;
        Relationships: [];
      };
      garden_cells: {
        Row: {
          id: number;
          zone_id: number;
          row: number;
          col: number;
          variety_id: number | null;
          color: string | null;
          notes: string | null;
        };
        Insert: Omit<Database["public"]["Tables"]["garden_cells"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["garden_cells"]["Insert"]>;
        Relationships: [];
      };
      harvests: {
        Row: {
          id: number;
          variety_id: number | null;
          crop_id: number | null;
          weight: number;
          unit: string;
          harvested_at: string;
          notes: string | null;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["harvests"]["Row"], "id" | "created_at"> & {
          id?: number;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["harvests"]["Insert"]>;
        Relationships: [];
      };
      treatment_inventory: {
        Row: {
          id: number;
          product_id: number;
          quantity: number;
          unit: string;
          purchase_date: string | null;
          notes: string | null;
          updated_at: string;
          bottle_size: number | null;
          bottle_unit: string | null;
          bottles: number | null;
          cost_dollars: number | null;
          image_url: string | null;
        };
        Insert: {
          id?: number;
          product_id: number;
          quantity: number;
          unit: string;
          purchase_date?: string | null;
          notes?: string | null;
          updated_at?: string;
          bottle_size?: number | null;
          bottle_unit?: string | null;
          bottles?: number | null;
          cost_dollars?: number | null;
          image_url?: string | null;
        };
        Update: Partial<Database["public"]["Tables"]["treatment_inventory"]["Insert"]>;
        Relationships: [];
      };
      queued_sprays: {
        Row: {
          id: number;
          planned_date: string | null;
          notes: string | null;
          created_at: string;
        };
        Insert: {
          id?: number;
          planned_date?: string | null;
          notes?: string | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["queued_sprays"]["Insert"]>;
        Relationships: [];
      };
      queued_spray_products: {
        Row: {
          id: number;
          queued_spray_id: number;
          product_id: number;
          rate_applied: number | null;
          rate_unit: string;
        };
        Insert: {
          id?: number;
          queued_spray_id: number;
          product_id: number;
          rate_applied?: number | null;
          rate_unit?: string;
        };
        Update: Partial<Database["public"]["Tables"]["queued_spray_products"]["Insert"]>;
        Relationships: [];
      };
      queued_spray_crops: {
        Row: {
          id: number;
          queued_spray_id: number;
          crop_id: number;
        };
        Insert: Omit<Database["public"]["Tables"]["queued_spray_crops"]["Row"], "id"> & { id?: number };
        Update: Partial<Database["public"]["Tables"]["queued_spray_crops"]["Insert"]>;
        Relationships: [];
      };
      garden_regions: {
        Row: {
          id: number;
          zone_id: number;
          name: string;
          variety_id: number | null;
          region_type: RegionType;
          x: number;
          y: number;
          width: number;
          height: number;
          color: string | null;
          border_color: string | null;
          notes: string | null;
          z_index: number;
          template_id: number | null;
          cells: RegionCell[] | null;
          created_at: string;
        };
        Insert: {
          id?: number;
          zone_id: number;
          name: string;
          variety_id?: number | null;
          region_type: RegionType;
          x: number;
          y: number;
          width: number;
          height: number;
          color?: string | null;
          border_color?: string | null;
          notes?: string | null;
          z_index?: number;
          template_id?: number | null;
          cells?: RegionCell[] | null;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["garden_regions"]["Insert"]>;
        Relationships: [];
      };
      garden_templates: {
        Row: {
          id: number;
          name: string;
          element_type: RegionType;
          width: number;
          height: number;
          color: string;
          border_color: string;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["garden_templates"]["Row"], "id" | "created_at"> & {
          id?: number;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["garden_templates"]["Insert"]>;
        Relationships: [];
      };
      app_settings: {
        Row: {
          id: number;
          theme_mode: ThemeMode;
          figures: FiguresPref;
          density: DensityPref;
          phi_alerts: PhiAlertPref;
          weather_bar: boolean;
          updated_at: string;
        };
        Insert: Partial<Database["public"]["Tables"]["app_settings"]["Row"]>;
        Update: Partial<Database["public"]["Tables"]["app_settings"]["Row"]>;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: {
      ingredient_type: IngredientType;
      signal_word: SignalWord;
      bee_toxicity_tier: BeeToxicityTier;
      tank_rule_type: TankRuleType;
      management_tier: ManagementTier;
      phenological_stage: PhenologicalStage;
    };
  };
}

// Convenience row type aliases
export type Product = Database["public"]["Tables"]["products"]["Row"];
export type ActiveIngredient = Database["public"]["Tables"]["active_ingredients"]["Row"];
export type ProductIngredient = Database["public"]["Tables"]["product_ingredients"]["Row"];
export type CropGroup = Database["public"]["Tables"]["crop_groups"]["Row"];
export type CropUse = Database["public"]["Tables"]["crop_uses"]["Row"];
export type TankMixRule = Database["public"]["Tables"]["tank_mix_rules"]["Row"];
export type Crop = Database["public"]["Tables"]["crops"]["Row"];
export type Variety = Database["public"]["Tables"]["varieties"]["Row"];
export type VarietyStage = Database["public"]["Tables"]["variety_stages"]["Row"];
export type SprayEvent = Database["public"]["Tables"]["spray_events"]["Row"];
export type SprayEventProduct = Database["public"]["Tables"]["spray_event_products"]["Row"];
export type SprayEventCrop = Database["public"]["Tables"]["spray_event_crops"]["Row"];
export type PhenologyCalendar = Database["public"]["Tables"]["phenology_calendar"]["Row"];
export type WeatherCache = Database["public"]["Tables"]["weather_cache"]["Row"];
export type GardenZone = Database["public"]["Tables"]["garden_zones"]["Row"];
export type GardenCell = Database["public"]["Tables"]["garden_cells"]["Row"];
export type Harvest = Database["public"]["Tables"]["harvests"]["Row"];
export type TreatmentInventory = Database["public"]["Tables"]["treatment_inventory"]["Row"];
export type QueuedSpray = Database["public"]["Tables"]["queued_sprays"]["Row"];
export type QueuedSprayProduct = Database["public"]["Tables"]["queued_spray_products"]["Row"];
export type QueuedSprayCrop = Database["public"]["Tables"]["queued_spray_crops"]["Row"];
export type GardenRegion = Database["public"]["Tables"]["garden_regions"]["Row"];
export type GardenTemplate = Database["public"]["Tables"]["garden_templates"]["Row"];
export type AppSettings = Database["public"]["Tables"]["app_settings"]["Row"];

/** Composite-footprint sub-rectangle, offsets in grid cells from region (x,y) */
export interface RegionCell {
  dx: number;
  dy: number;
  dw: number;
  dh: number;
}
