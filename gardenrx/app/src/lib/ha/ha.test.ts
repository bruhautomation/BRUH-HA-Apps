// @vitest-environment node
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { execute, openForTest } from '@/lib/db/sqlite';
import { makeClient } from '@/lib/db/query';
import { ACTIONS } from './actions';
import { loadGardenRows } from './load';
import { buildSummary } from './summary';

const SEED = path.join(__dirname, '..', '..', '..', 'seed', 'catalog.json');
const TZ = 'America/New_York';
const NOW = new Date('2026-07-15T16:00:00Z');

async function garden() {
  const raw = openForTest(SEED);
  const db = makeClient(async (req) => execute(raw, req));
  // A pome-fruit crop with a variety, and a product labelled for pome fruit
  // with a pre-harvest interval, taken from the shipped catalog.
  const { data: use } = await db.from('crop_uses').select('*').gt('phi_days', 3).limit(1).single();
  const { data: crop } = await db
    .from('crops')
    .insert({ name: 'Apples', crop_group_id: use!.crop_group_id, price_market_per_lb: 3 })
    .select()
    .single();
  await db.from('varieties').insert({ name: 'Liberty', crop_id: crop!.id });
  return { db, crop: crop!, use: use! };
}

describe('the Home Assistant actions', () => {
  it('logs a harvest by name, values it, and the summary counts it', async () => {
    const { db } = await garden();
    const res = await ACTIONS.log_harvest(db, { crop: 'apples', variety: 'lib', weight: 32, unit: 'oz' }, NOW, TZ);
    expect(res).toMatchObject({ ok: true, crop: 'Apples', variety: 'Liberty', lb: 2, value: 6, date: '2026-07-15' });
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.harvest.total_lb).toBe(2);
    expect(s.harvest.total_value).toBe(6);
    expect(s.harvest.by_crop[0]).toMatchObject({ crop: 'Apples', picks: 1 });
    expect(s.harvest.recent[0]).toMatchObject({ variety: 'Liberty', unit: 'oz' });
  });

  it('refuses with a sentence rather than guessing', async () => {
    const { db } = await garden();
    expect(await ACTIONS.log_harvest(db, { crop: 'kiwi', weight: 1 }, NOW, TZ)).toMatchObject({ ok: false });
    expect(await ACTIONS.log_harvest(db, { crop: 'Apples', weight: -1 }, NOW, TZ)).toMatchObject({ ok: false });
    expect(await ACTIONS.log_harvest(db, { crop: 'Apples', weight: 1, unit: 'bushel' }, NOW, TZ)).toMatchObject({
      ok: false,
    });
    expect(await ACTIONS.delete_harvest(db, { id: 999 })).toMatchObject({ ok: false });
  });

  it('a queued spray marked done becomes a spray, starts the PHI, and leaves the queue', async () => {
    const { db, crop, use } = await garden();
    await db.from('treatment_inventory').insert({ product_id: use.product_id, quantity: 32, unit: 'fl oz' });
    const { data: q } = await db.from('queued_sprays').insert({ notes: 'cover spray' }).select().single();
    await db
      .from('queued_spray_products')
      .insert({ queued_spray_id: q!.id, product_id: use.product_id, rate_applied: 1, rate_unit: 'fl oz/gal' });
    await db.from('queued_spray_crops').insert({ queued_spray_id: q!.id, crop_id: crop.id });

    const before = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(before.sprays.queued).toHaveLength(1);

    const res = await ACTIONS.complete_queued_spray(db, { id: q!.id, volume_gallons: 2 }, NOW, TZ);
    expect(res).toMatchObject({ ok: true, products: 1, crops: 1 });

    const after = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(after.sprays.queued).toHaveLength(0);
    expect(after.sprays.last).toMatchObject({ date: '2026-07-15', days_ago: 0, crops: ['Apples'] });
    expect(after.phi.active_count).toBe(1);
    expect(after.phi.crops[0]).toMatchObject({ crop: 'Apples', days_left: use.phi_days });
    // 1 fl oz/gal × 2 gal came out of a 32 fl oz bottle.
    const { data: inv } = await db.from('treatment_inventory').select('quantity').single();
    expect(inv?.quantity).toBe(30);

    const warned = await ACTIONS.log_harvest(db, { crop: 'Apples', weight: 1 }, NOW, TZ);
    expect(warned).toMatchObject({ ok: true });
    expect((warned as unknown as { phi_warning: string }).phi_warning).toMatch(/pre-harvest interval/);
  });

  it('flags a bottle that is nearly empty', async () => {
    const { db } = await garden();
    await db.from('treatment_inventory').insert({ product_id: 32, quantity: 1, unit: 'fl oz', bottle_size: 32 });
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.inventory.low_count).toBe(1);
    expect(s.inventory.items[0]).toMatchObject({ pct: 3, low: true });
  });
});
