import type { SprayEvent, SprayEventCrop, SprayEventProduct } from '@/lib/database.types';

/**
 * The most recent spray day, described once.
 *
 * Today's "Last spray" row and the Home Assistant card (through
 * `/api/ha/summary`) both read this, so they cannot describe the same date
 * differently. When several sprays share that date, every one of them is in
 * the sentence, newest first: "2 sprays: Captan on Apples; Sulfur + Oil on 3
 * crops".
 */
export type LastSprayDay = {
  date: string;
  /** The newest spray on that date. */
  id: number;
  notes: string | null;
  /** How many sprays share the date. */
  count: number;
  /** Every product and crop sprayed that day, each once. */
  products: string[];
  crops: string[];
  /** One sentence for all of that day's sprays, without the date. */
  summary: string;
};

function names(list: string[]): string {
  const uniq = [...new Set(list)];
  if (uniq.length <= 2) return uniq.join(' and ');
  return `${uniq.length} crops`;
}

export function lastSprayDay(input: {
  events: SprayEvent[];
  eventProducts: SprayEventProduct[];
  eventCrops: SprayEventCrop[];
  /** YYYY-MM-DD on the garden's clock; a spray dated later is not "last". */
  today: string;
  productName: (id: number) => string | undefined;
  cropName: (id: number) => string | undefined;
}): LastSprayDay | null {
  const { events, eventProducts, eventCrops, today, productName, cropName } = input;
  const past = events
    .filter((e) => typeof e.date === 'string' && e.date.slice(0, 10) <= today)
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  if (!past.length) return null;
  const date = past[0].date.slice(0, 10);
  const day = past.filter((e) => e.date.slice(0, 10) === date);

  const parts = day.map((e) => {
    const products = eventProducts
      .filter((p) => p.spray_event_id === e.id)
      .map((p) => productName(p.product_id))
      .filter((n): n is string => !!n);
    const crops = eventCrops
      .filter((c) => c.spray_event_id === e.id)
      .map((c) => cropName(c.crop_id))
      .filter((n): n is string => !!n);
    const text =
      ([...new Set(products)].join(' + ') || 'A spray') +
      (crops.length ? ` on ${names(crops)}` : '');
    return { products, crops, text };
  });

  return {
    date,
    id: day[0].id,
    notes: day[0].notes,
    count: day.length,
    products: [...new Set(parts.flatMap((p) => p.products))],
    crops: [...new Set(parts.flatMap((p) => p.crops))],
    summary:
      day.length === 1
        ? parts[0].text
        : `${day.length} sprays: ${parts.map((p) => p.text).join('; ')}`,
  };
}
