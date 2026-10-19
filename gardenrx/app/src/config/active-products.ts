/**
 * Products shown across the app (Treatments reference, Inventory picker, Mix planner).
 *
 * Curated to the homeowner-available chemistry actually used in this NC garden:
 * the owner's Amazon order list plus the most common, readily-stocked staples
 * (Lowe's / Home Depot / Walmart / Tractor Supply). Commercial-only / niche
 * SKUs (Kasumin, Actigard, Rely, Chateau, Alion, Prowl, Cabrio, Mancozeb,
 * Surround, Roundup PowerMAX, …) are intentionally excluded.
 *
 * Pricing lives on `products.price_dollars` / `price_size` (≈ Amazon, May 2026).
 * To add a product: insert/curate it in the database, then add its ID here.
 */

export const ACTIVE_PRODUCT_IDS = new Set([
  // ── Fungicides ──────────────────────────────────────────
  1, // Bonide Captan 50W (Captan)
  3, // Spectracide Immunox Multi-Purpose (Myclobutanil)  ★ owned
  4, // Bonide Sulfur Plant Fungicide (Sulfur)
  5, // Bonide Copper Fungicide (Copper octanoate)
  6, // Atticus Gravex 20EW (Myclobutanil 19.7%)          ★ owned · Amazon
  237, // Bonide Neem Oil Concentrate (Clarified neem oil)
  239, // Ortho MAX Garden Disease Control (Chlorothalonil)
  18, // GardenTech Daconil Fungicide (Chlorothalonil)

  // ── Insecticides / Miticides ────────────────────────────
  83, // Bonide Eight (Permethrin)
  101, // Thuricide BT Concentrate (Bt kurstaki)
  114, // Bonide All Seasons Horticultural Oil
  240, // BioAdvanced Fruit, Citrus & Vegetable (Imidacloprid)
  246, // Sevin Insect Killer Concentrate (Zeta-cypermethrin) ★ owned · Amazon
  249, // Captain Jack's Deadbug Brew (Spinosad)             · Amazon
  256, // Bonide Malathion Insect Control (Malathion 50%)    · Amazon
  245, // Atticus Talak 7.9% F (Bifenthrin) — insecticide/miticide  ★ owned
  235, // Suspend SC (Deltamethrin) — premise / perimeter    · Amazon
  236, // NyGuard IGR Concentrate (Pyriproxyfen) — premise   · Amazon

  // ── Combination (fungicide + insecticide + miticide) ────
  152, // Captain Jack's Citrus, Fruit & Nut Orchard Spray (Pyrethrins + Sulfur) · Amazon
  242, // Bonide Fruit Tree Spray Concentrate (Captan + Malathion + Carbaryl)
  252, // Bonide Fruit Tree & Plant Guard (λ-cyhalothrin + Boscalid + Pyraclostrobin) · Amazon
  234, // Bayer Advanced 3-in-1 Insect Disease & Mite Control (Imidacloprid + Tau-fluvalinate + Tebuconazole) — ornamentals

  // ── Bactericides ────────────────────────────────────────
  255, // Fertilome Fire Blight Spray (Streptomycin sulfate) · Amazon

  // ── Herbicides ──────────────────────────────────────────
  195, // Quali-Pro Negate 37WG (Rimsulfuron + Metsulfuron) — turf · Amazon · owned
  250, // Compare-N-Save Grass & Weed Killer (Glyphosate 41%)      · Amazon
]);
