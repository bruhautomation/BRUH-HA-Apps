import type { DbClient } from '@/lib/db/query';
import type { GardenRows } from './summary';

/** Every table the summary reads, in one round of queries. */
export async function loadGardenRows(db: DbClient): Promise<GardenRows> {
  const all = async <T>(
    p: PromiseLike<{ data: T[] | null; error: { message: string } | null }>
  ) => {
    const { data, error } = await p;
    if (error) throw new Error(error.message);
    return data ?? [];
  };
  const [
    crops,
    varieties,
    cropGroups,
    cropUses,
    products,
    harvests,
    sprayEvents,
    sprayEventProducts,
    sprayEventCrops,
    queuedSprays,
    queuedSprayProducts,
    queuedSprayCrops,
    inventory,
  ] = await Promise.all([
    all(db.from('crops').select('*')),
    all(db.from('varieties').select('*')),
    all(db.from('crop_groups').select('*')),
    all(db.from('crop_uses').select('*')),
    all(db.from('products').select('*')),
    all(db.from('harvests').select('*')),
    all(db.from('spray_events').select('*')),
    all(db.from('spray_event_products').select('*')),
    all(db.from('spray_event_crops').select('*')),
    all(db.from('queued_sprays').select('*')),
    all(db.from('queued_spray_products').select('*')),
    all(db.from('queued_spray_crops').select('*')),
    all(db.from('treatment_inventory').select('*')),
  ]);
  return {
    crops,
    varieties,
    cropGroups,
    cropUses,
    products,
    harvests,
    sprayEvents,
    sprayEventProducts,
    sprayEventCrops,
    queuedSprays,
    queuedSprayProducts,
    queuedSprayCrops,
    inventory,
  };
}
