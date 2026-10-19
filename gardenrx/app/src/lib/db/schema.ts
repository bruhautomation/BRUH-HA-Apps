/**
 * The SQLite schema, as data.
 *
 * One description serves three readers: the migration that creates the tables
 * (`sqlite.ts`), the request validator that refuses a table or column name it
 * does not know, and the row codec that turns SQLite's integers back into the
 * booleans and its TEXT back into the JSON the app was written against. A
 * second copy of any of the three is a copy that drifts, so there is none.
 *
 * The shape follows the Supabase tables this app was built on, column for
 * column, so `database.types.ts` still describes what comes back.
 *
 * This module imports nothing, because the browser half of the query builder
 * reads it too.
 */

export type ColType = 'int' | 'real' | 'text' | 'bool' | 'json';

export interface Column {
  type: ColType;
  /** NOT NULL. */
  required?: boolean;
  /** A SQL expression — evaluated by SQLite, never by this code. */
  default?: string;
  references?: { table: string; column?: string; onDelete: 'CASCADE' | 'SET NULL' };
}

export interface Table {
  columns: Record<string, Column>;
  /** Defaults to an `id INTEGER PRIMARY KEY AUTOINCREMENT`. */
  primaryKey?: string[];
}

const NOW = "(strftime('%Y-%m-%dT%H:%M:%fZ','now'))";
const TODAY = "(date('now','localtime'))";

const id: Column = { type: 'int' };
const createdAt: Column = { type: 'text', required: true, default: NOW };
const ref = (table: string, onDelete: 'CASCADE' | 'SET NULL' = 'CASCADE') => ({
  table,
  onDelete,
});

export const SCHEMA: Record<string, Table> = {
  crop_groups: {
    columns: {
      id,
      name: { type: 'text', required: true },
      description: { type: 'text' },
    },
  },
  active_ingredients: {
    columns: {
      id,
      name: { type: 'text', required: true },
      type: { type: 'text', required: true },
      frac_irac_hrac_group: { type: 'text' },
      mode_of_action: { type: 'text' },
      is_single_site: { type: 'bool', required: true, default: '0' },
    },
  },
  products: {
    columns: {
      id,
      brand: { type: 'text', required: true },
      manufacturer: { type: 'text' },
      epa_reg_number: { type: 'text' },
      formulation: { type: 'text' },
      concentration: { type: 'text' },
      signal_word: { type: 'text' },
      rei_hours: { type: 'real' },
      bee_toxicity: { type: 'text' },
      rain_fastness_hours: { type: 'real' },
      cover_spray_interval_days: { type: 'real' },
      rain_tolerance_inches: { type: 'real' },
      temp_min: { type: 'real' },
      temp_max: { type: 'real' },
      ppe_requirements: { type: 'json', required: true, default: "'{}'" },
      safety_notes: { type: 'text' },
      first_aid_summary: { type: 'text' },
      source_pdf_hash: { type: 'text' },
      is_active: { type: 'bool', required: true, default: '1' },
      price_dollars: { type: 'real' },
      price_size: { type: 'text' },
      retail_url: { type: 'text' },
      image_url: { type: 'text' },
      created_at: createdAt,
    },
  },
  product_ingredients: {
    primaryKey: ['product_id', 'ingredient_id'],
    columns: {
      product_id: { type: 'int', required: true, references: ref('products') },
      ingredient_id: { type: 'int', required: true, references: ref('active_ingredients') },
      concentration_pct: { type: 'real' },
    },
  },
  crop_uses: {
    columns: {
      id,
      product_id: { type: 'int', required: true, references: ref('products') },
      crop_group_id: { type: 'int', required: true, references: ref('crop_groups') },
      rate_min: { type: 'real' },
      rate_max: { type: 'real' },
      rate_unit: { type: 'text', required: true, default: "'fl oz/gal'" },
      phi_days: { type: 'real' },
      max_apps_per_season: { type: 'real' },
      min_interval_days: { type: 'real' },
      growth_stage_restrictions: { type: 'text' },
      restrictions_text: { type: 'text' },
      source_pdf_page: { type: 'text' },
    },
  },
  tank_mix_rules: {
    columns: {
      id,
      product_a_id: { type: 'int', required: true, references: ref('products') },
      product_b_id: { type: 'int', required: true, references: ref('products') },
      rule_type: { type: 'text', required: true },
      separation_days: { type: 'real' },
      explanation: { type: 'text' },
      mix_order_note: { type: 'text' },
    },
  },
  phenology_calendar: {
    columns: {
      id,
      crop_group_id: { type: 'int', required: true, references: ref('crop_groups') },
      stage: { type: 'text', required: true },
      typical_start_date: { type: 'text', required: true },
      typical_end_date: { type: 'text', required: true },
    },
  },
  crops: {
    columns: {
      id,
      name: { type: 'text', required: true },
      crop_group_id: { type: 'int', references: ref('crop_groups', 'SET NULL') },
      is_active: { type: 'bool', required: true, default: '1' },
      track_fungicide: { type: 'bool', required: true, default: '0' },
      track_insecticide: { type: 'bool', required: true, default: '0' },
      price_market_per_lb: { type: 'real' },
      price_grocery_per_lb: { type: 'real' },
      avg_lb_per_count: { type: 'real' },
      created_at: createdAt,
    },
  },
  varieties: {
    columns: {
      id,
      name: { type: 'text', required: true },
      crop_id: { type: 'int', required: true, references: ref('crops') },
      is_sentinel: { type: 'bool', required: true, default: '0' },
      disease_susceptibility: { type: 'json', required: true, default: "'{}'" },
      management_tier: { type: 'text', required: true, default: "'standard'" },
      price_per_lb: { type: 'real' },
      created_at: createdAt,
    },
  },
  variety_stages: {
    columns: {
      id,
      variety_id: { type: 'int', required: true, references: ref('varieties') },
      stage: { type: 'text', required: true, default: "'dormant'" },
      is_manual_override: { type: 'bool', required: true, default: '0' },
      updated_at: { type: 'text', required: true, default: NOW },
    },
  },
  spray_events: {
    columns: {
      id,
      date: { type: 'text', required: true, default: TODAY },
      notes: { type: 'text' },
      weather_snapshot: { type: 'json', required: true, default: "'{}'" },
      volume_gallons: { type: 'real' },
      created_at: createdAt,
    },
  },
  spray_event_products: {
    columns: {
      id,
      spray_event_id: { type: 'int', required: true, references: ref('spray_events') },
      product_id: { type: 'int', required: true, references: ref('products') },
      rate_applied: { type: 'real' },
      rate_unit: { type: 'text', required: true, default: "'fl oz/gal'" },
    },
  },
  spray_event_crops: {
    columns: {
      id,
      spray_event_id: { type: 'int', required: true, references: ref('spray_events') },
      crop_id: { type: 'int', required: true, references: ref('crops') },
    },
  },
  weather_cache: {
    columns: {
      id,
      fetched_at: { type: 'text', required: true, default: NOW },
      current_conditions: { type: 'json', required: true, default: "'{}'" },
      hourly_forecast: { type: 'json', required: true, default: "'[]'" },
      daily_forecast: { type: 'json', required: true, default: "'[]'" },
      hourly_precipitation_history: { type: 'json', required: true, default: "'[]'" },
    },
  },
  garden_zones: {
    columns: {
      id,
      name: { type: 'text', required: true },
      rows: { type: 'int', required: true },
      cols: { type: 'int', required: true },
      created_at: createdAt,
    },
  },
  garden_cells: {
    columns: {
      id,
      zone_id: { type: 'int', required: true, references: ref('garden_zones') },
      row: { type: 'int', required: true },
      col: { type: 'int', required: true },
      variety_id: { type: 'int', references: ref('varieties', 'SET NULL') },
      color: { type: 'text' },
      notes: { type: 'text' },
    },
  },
  harvests: {
    columns: {
      id,
      variety_id: { type: 'int', references: ref('varieties', 'SET NULL') },
      crop_id: { type: 'int', references: ref('crops') },
      weight: { type: 'real', required: true },
      unit: { type: 'text', required: true },
      harvested_at: { type: 'text', required: true, default: NOW },
      notes: { type: 'text' },
      created_at: createdAt,
    },
  },
  treatment_inventory: {
    columns: {
      id,
      product_id: { type: 'int', required: true, references: ref('products') },
      quantity: { type: 'real', required: true, default: '0' },
      unit: { type: 'text', required: true },
      purchase_date: { type: 'text' },
      notes: { type: 'text' },
      bottle_size: { type: 'real' },
      bottle_unit: { type: 'text' },
      bottles: { type: 'real' },
      cost_dollars: { type: 'real' },
      image_url: { type: 'text' },
      created_at: createdAt,
      updated_at: { type: 'text', required: true, default: NOW },
    },
  },
  queued_sprays: {
    columns: {
      id,
      planned_date: { type: 'text' },
      notes: { type: 'text' },
      created_at: createdAt,
    },
  },
  queued_spray_products: {
    columns: {
      id,
      queued_spray_id: { type: 'int', required: true, references: ref('queued_sprays') },
      product_id: { type: 'int', required: true, references: ref('products') },
      rate_applied: { type: 'real' },
      rate_unit: { type: 'text', required: true, default: "'fl oz/gal'" },
    },
  },
  queued_spray_crops: {
    columns: {
      id,
      queued_spray_id: { type: 'int', required: true, references: ref('queued_sprays') },
      crop_id: { type: 'int', required: true, references: ref('crops') },
    },
  },
  garden_templates: {
    columns: {
      id,
      name: { type: 'text', required: true },
      element_type: { type: 'text', required: true },
      width: { type: 'real', required: true },
      height: { type: 'real', required: true },
      color: { type: 'text', required: true },
      border_color: { type: 'text', required: true },
      created_at: createdAt,
    },
  },
  garden_regions: {
    columns: {
      id,
      zone_id: { type: 'int', required: true, references: ref('garden_zones') },
      name: { type: 'text', required: true },
      variety_id: { type: 'int', references: ref('varieties', 'SET NULL') },
      region_type: { type: 'text', required: true },
      x: { type: 'real', required: true },
      y: { type: 'real', required: true },
      width: { type: 'real', required: true },
      height: { type: 'real', required: true },
      color: { type: 'text' },
      border_color: { type: 'text' },
      notes: { type: 'text' },
      z_index: { type: 'int', required: true, default: '0' },
      template_id: { type: 'int', references: ref('garden_templates', 'SET NULL') },
      cells: { type: 'json' },
      created_at: createdAt,
    },
  },
  app_settings: {
    columns: {
      id,
      theme_mode: { type: 'text', required: true, default: "'light'" },
      figures: { type: 'text', required: true, default: "'sans'" },
      density: { type: 'text', required: true, default: "'comfortable'" },
      phi_alerts: { type: 'text', required: true, default: "'loud'" },
      weather_bar: { type: 'bool', required: true, default: '1' },
      updated_at: { type: 'text', required: true, default: NOW },
    },
  },
};

/** Tables in an order where every reference points at a table already made. */
export const TABLE_ORDER: string[] = Object.keys(SCHEMA);

export const IDENT = /^[a-z_][a-z0-9_]*$/;

export function tableOf(name: string): Table | null {
  return IDENT.test(name) && Object.prototype.hasOwnProperty.call(SCHEMA, name)
    ? SCHEMA[name]
    : null;
}

export function primaryKeyOf(table: Table): string[] {
  return table.primaryKey ?? ['id'];
}
