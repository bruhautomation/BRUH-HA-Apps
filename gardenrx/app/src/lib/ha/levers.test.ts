// @vitest-environment node
//
// The levers Home Assistant has on the garden beyond the harvest and the
// queue: logging a spray nobody queued, queueing one, stock, crops, varieties,
// a dated note on a place on the map, and reading the harvests back. Each one
// is driven against the real SQLite layer, and each one is read back the way
// the panel's own screens read it.
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
  // A labelled use whose rate is per gallon, and the FIRST use of that product
  // on that group — the one the label rate is read from.
  const { data: uses } = await db.from('crop_uses').select('*').order('id');
  const use = (uses ?? []).find(
    (u) =>
      (u.phi_days ?? 0) > 3 &&
      (u.rate_max ?? 0) > 0 &&
      u.rate_unit === 'fl oz/gal' &&
      (uses ?? []).find(
        (o) => o.product_id === u.product_id && o.crop_group_id === u.crop_group_id
      ) === u
  );
  const { data: crop } = await db
    .from('crops')
    .insert({ name: 'Apples', crop_group_id: use!.crop_group_id, price_market_per_lb: 3 })
    .select()
    .single();
  const { data: pears } = await db
    .from('crops')
    .insert({ name: 'Pears', crop_group_id: use!.crop_group_id })
    .select()
    .single();
  await db.from('varieties').insert({ name: 'Liberty', crop_id: crop!.id });
  const { data: product } = await db
    .from('products')
    .select('*')
    .eq('id', use!.product_id)
    .single();
  return { db, crop: crop!, pears: pears!, use: use!, product: product! };
}

const ok = (r: unknown) => r as { ok: true; [k: string]: unknown };
const refused = (r: unknown) => (r as { ok: false; error: string }).error;

describe('log_spray', () => {
  it('logs a spray nobody queued, by name, at the label rate, and takes it out of stock', async () => {
    const { db, crop, use, product } = await garden();
    await db
      .from('treatment_inventory')
      .insert({ product_id: product.id, quantity: 64, unit: 'fl oz' });
    const res = await ACTIONS.log_spray(
      db,
      {
        crop: 'apples',
        product: product.brand.toUpperCase(),
        volume_gallons: 2,
        notes: 'petal fall',
      },
      NOW,
      TZ
    );
    expect(res).toMatchObject({ ok: true, date: '2026-07-15', crops: ['Apples'] });
    const rate = use.rate_max ?? use.rate_min;
    expect(ok(res).products).toEqual([{ product: product.brand, rate, rate_unit: 'fl oz/gal' }]);
    // The panel's History and the sensors read the same rows.
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.sprays.last).toMatchObject({ date: '2026-07-15', crops: ['Apples'] });
    expect(s.phi.crops[0]).toMatchObject({ crop: crop.name });
    const { data: inv } = await db.from('treatment_inventory').select('quantity').single();
    expect(inv?.quantity).toBe(64 - (rate as number) * 2);
    const { data: ev } = await db.from('spray_events').select('*').single();
    expect(ev?.notes).toBe('petal fall');
  });

  it('sprays a whole area, and the rate given wins over the label', async () => {
    const { db, product } = await garden();
    const res = await ACTIONS.log_spray(
      db,
      {
        area: 'orchard',
        product: product.id,
        rate: 0.5,
        rate_unit: 'tbsp/gal',
        date: '2026-07-01',
      },
      NOW,
      TZ
    );
    expect(res).toMatchObject({ ok: true, date: '2026-07-01' });
    expect((ok(res).crops as string[]).sort()).toEqual(['Apples', 'Pears']);
    expect(ok(res).products).toEqual([
      { product: product.brand, rate: 0.5, rate_unit: 'tbsp/gal' },
    ]);
  });

  it('clears a queued spray for the same crop, as the planner does', async () => {
    const { db, crop, product } = await garden();
    const { data: q } = await db.from('queued_sprays').insert({ notes: 'cover' }).select().single();
    await db.from('queued_spray_crops').insert({ queued_spray_id: q!.id, crop_id: crop.id });
    const res = await ACTIONS.log_spray(db, { crop: 'Apples', product: product.brand }, NOW, TZ);
    expect(ok(res).cleared_queued).toEqual([q!.id]);
    expect((await db.from('queued_sprays').select('*')).data).toHaveLength(0);
  });

  it('refuses with a sentence naming what is wrong, and writes nothing', async () => {
    const { db, product } = await garden();
    expect(
      refused(await ACTIONS.log_spray(db, { crop: 'tomatos', product: product.brand }, NOW, TZ))
    ).toBe('No crop is called "tomatos".');
    expect(
      refused(await ACTIONS.log_spray(db, { crop: 'Apples', product: 'no such spray' }, NOW, TZ))
    ).toBe('No product is called "no such spray".');
    expect(refused(await ACTIONS.log_spray(db, { product: product.brand }, NOW, TZ))).toMatch(
      /which crops/
    );
    expect(refused(await ACTIONS.log_spray(db, { crop: 'Apples' }, NOW, TZ))).toMatch(
      /which product/
    );
    expect(
      refused(await ACTIONS.log_spray(db, { area: 'moon', product: product.brand }, NOW, TZ))
    ).toMatch(/Orchard, Garden or Landscape/);
    expect(
      refused(
        await ACTIONS.log_spray(db, { crop: 'Apples', product: product.brand, rate: -2 }, NOW, TZ)
      )
    ).toMatch(/rate/);
    expect(
      refused(
        await ACTIONS.log_spray(
          db,
          { crop: 'Apples', product: product.brand, date: 'July' },
          NOW,
          TZ
        )
      )
    ).toBe('The date must be YYYY-MM-DD.');
    expect((await db.from('spray_events').select('*')).data).toHaveLength(0);
  });
});

describe('queue_spray', () => {
  it('queues a spray the planner and the sensors then show', async () => {
    const { db, product } = await garden();
    const res = await ACTIONS.queue_spray(
      db,
      {
        crop: ['apples', 'pears'],
        product: [product.brand],
        planned_date: '2026-07-20',
        notes: 'next week',
      },
      NOW,
      TZ
    );
    expect(res).toMatchObject({ ok: true, planned_date: '2026-07-20', crops: ['Apples', 'Pears'] });
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.sprays.queued).toHaveLength(1);
    // And it can be marked done by the service that already existed.
    const done = await ACTIONS.complete_queued_spray(db, { id: ok(res).id }, NOW, TZ);
    expect(done).toMatchObject({ ok: true, crops: 2, products: 1 });
  });

  it('refuses a crop nobody grows', async () => {
    const { db, product } = await garden();
    expect(
      refused(await ACTIONS.queue_spray(db, { crop: 'kiwi', product: product.brand }, NOW, TZ))
    ).toBe('No crop is called "kiwi".');
    expect((await db.from('queued_sprays').select('*')).data).toHaveLength(0);
  });
});

describe('adjust_inventory', () => {
  it('starts stocking a product, then adds to it and takes from it', async () => {
    const { db, product } = await garden();
    const added = await ACTIONS.adjust_inventory(
      db,
      { product: product.brand, change: 32, unit: 'fl oz' },
      NOW,
      TZ
    );
    expect(added).toMatchObject({
      ok: true,
      product: product.brand,
      quantity: 32,
      unit: 'fl oz',
      created: true,
    });
    const more = await ACTIONS.adjust_inventory(
      db,
      { product: product.brand.toLowerCase(), change: 8 },
      NOW,
      TZ
    );
    expect(more).toMatchObject({ ok: true, quantity: 40, created: false });
    const used = await ACTIONS.adjust_inventory(db, { product: product.id, change: -50 }, NOW, TZ);
    expect(used).toMatchObject({ ok: true, quantity: 0 });
    const set = await ACTIONS.adjust_inventory(db, { product: product.id, quantity: 12 }, NOW, TZ);
    expect(set).toMatchObject({ ok: true, quantity: 12 });
    // The Stock page and the low-stock sensor read the same row.
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.inventory.items[0]).toMatchObject({ product: product.brand, quantity: 12 });
  });

  it('refuses what it cannot do, in words', async () => {
    const { db, product } = await garden();
    expect(
      refused(
        await ACTIONS.adjust_inventory(db, { product: 'nothing like it', change: 1 }, NOW, TZ)
      )
    ).toBe('No product is called "nothing like it".');
    expect(
      refused(await ACTIONS.adjust_inventory(db, { product: product.brand, change: -1 }, NOW, TZ))
    ).toMatch(/not in stock/);
    expect(
      refused(await ACTIONS.adjust_inventory(db, { product: product.brand }, NOW, TZ))
    ).toMatch(/how much/);
    expect(
      refused(
        await ACTIONS.adjust_inventory(
          db,
          { product: product.brand, change: 1, unit: 'bucket' },
          NOW,
          TZ
        )
      )
    ).toMatch(/unit must be one of/);
    await ACTIONS.adjust_inventory(
      db,
      { product: product.brand, change: 4, unit: 'fl oz' },
      NOW,
      TZ
    );
    expect(
      refused(
        await ACTIONS.adjust_inventory(
          db,
          { product: product.brand, change: 1, unit: 'lb' },
          NOW,
          TZ
        )
      )
    ).toMatch(/counted in fl oz/);
  });
});

describe('add_crop and add_variety', () => {
  it('adds a crop with its group from the catalog, and a variety to it', async () => {
    const { db } = await garden();
    const crop = await ACTIONS.add_crop(db, { name: 'tomatoes' }, NOW, TZ);
    expect(crop).toMatchObject({
      ok: true,
      name: 'Tomatoes',
      crop_group: 'Nightshades',
      area: 'Garden',
    });
    const variety = await ACTIONS.add_variety(db, { crop: 'tomato', name: 'Sungold' }, NOW, TZ);
    expect(variety).toMatchObject({ ok: true, crop: 'Tomatoes', name: 'Sungold' });
    // The Crops page reads crops, and the crop page its varieties and their stage.
    const { data: stages } = await db
      .from('variety_stages')
      .select('*')
      .eq('variety_id', ok(variety).id as number);
    expect(stages).toHaveLength(1);
    const s = buildSummary(await loadGardenRows(db), NOW, TZ);
    expect(s.crops.map((c) => c.name)).toContain('Tomatoes');
    // And the new names are what a harvest can now be logged against.
    expect(
      await ACTIONS.log_harvest(db, { crop: 'Tomatoes', variety: 'sungold', weight: 1 }, NOW, TZ)
    ).toMatchObject({
      ok: true,
      variety: 'Sungold',
    });
  });

  it('refuses a duplicate, an unknown group and an unknown crop', async () => {
    const { db } = await garden();
    expect(refused(await ACTIONS.add_crop(db, { name: 'APPLES' }, NOW, TZ))).toBe(
      'A crop called "Apples" already exists.'
    );
    expect(
      refused(await ACTIONS.add_crop(db, { name: 'Okra', crop_group: 'Space plants' }, NOW, TZ))
    ).toBe('No crop group is called "Space plants".');
    expect(refused(await ACTIONS.add_crop(db, { name: '  ' }, NOW, TZ))).toMatch(
      /Say what the crop is called/
    );
    expect(
      refused(await ACTIONS.add_variety(db, { crop: 'Apples', name: 'liberty' }, NOW, TZ))
    ).toBe('Apples already has a variety called "Liberty".');
    expect(
      refused(await ACTIONS.add_variety(db, { crop: 'tomatos', name: 'Sungold' }, NOW, TZ))
    ).toBe('No crop is called "tomatos".');
  });

  it('a group named by hand is matched without regard to case', async () => {
    const { db } = await garden();
    expect(
      await ACTIONS.add_crop(db, { name: 'Ground cherries', crop_group: 'nightshades' }, NOW, TZ)
    ).toMatchObject({
      ok: true,
      crop_group: 'Nightshades',
    });
  });
});

describe('log_note', () => {
  async function withBed() {
    const g = await garden();
    const { data: zone } = await g.db
      .from('garden_zones')
      .insert({ name: 'Back yard', rows: 10, cols: 10 })
      .select()
      .single();
    await g.db.from('garden_regions').insert({
      zone_id: zone!.id,
      name: 'North Bed',
      region_type: 'planting',
      x: 0,
      y: 0,
      width: 2,
      height: 2,
    });
    return g;
  }

  it('keeps a dated note on a place on the garden map, newest last', async () => {
    const { db } = await withBed();
    const one = await ACTIONS.log_note(
      db,
      { place: 'north bed', note: 'Aphids on the kale', date: '2026-07-10' },
      NOW,
      TZ
    );
    expect(one).toMatchObject({
      ok: true,
      place: 'North Bed',
      zone: 'Back yard',
      date: '2026-07-10',
    });
    await ACTIONS.log_note(db, { place: 'North', note: 'Mulched' }, NOW, TZ);
    const { data: region } = await db.from('garden_regions').select('*').single();
    expect(region?.notes).toBe('2026-07-10: Aphids on the kale\n2026-07-15: Mulched');
  });

  it('refuses a place the map does not have, and an empty note', async () => {
    const { db } = await withBed();
    expect(refused(await ACTIONS.log_note(db, { place: 'pond', note: 'x' }, NOW, TZ))).toBe(
      'Nothing on the garden map is called "pond".'
    );
    expect(refused(await ACTIONS.log_note(db, { place: 'North Bed', note: ' ' }, NOW, TZ))).toMatch(
      /Say what/
    );
  });

  it('says so when nothing is drawn on the map yet', async () => {
    const { db } = await garden();
    expect(refused(await ACTIONS.log_note(db, { place: 'North Bed', note: 'x' }, NOW, TZ))).toMatch(
      /Nothing is drawn on the garden map yet/
    );
  });
});

describe('get_harvests', () => {
  it('reads harvests back filtered by crop and dates, with totals per crop and unit', async () => {
    const { db } = await garden();
    await ACTIONS.log_harvest(
      db,
      { crop: 'Apples', weight: 2, unit: 'lb', date: '2026-07-01' },
      NOW,
      TZ
    );
    await ACTIONS.log_harvest(
      db,
      { crop: 'Apples', weight: 16, unit: 'oz', date: '2026-07-05' },
      NOW,
      TZ
    );
    await ACTIONS.log_harvest(
      db,
      { crop: 'Apples', weight: 3, unit: 'lb', date: '2026-07-10' },
      NOW,
      TZ
    );
    await ACTIONS.log_harvest(
      db,
      { crop: 'Pears', weight: 5, unit: 'ct', date: '2026-07-05' },
      NOW,
      TZ
    );
    await ACTIONS.log_harvest(
      db,
      { crop: 'Apples', weight: 9, unit: 'lb', date: '2026-06-01' },
      NOW,
      TZ
    );

    const all = ok(
      await ACTIONS.get_harvests(db, { start: '2026-07-01', end: '2026-07-31' }, NOW, TZ)
    );
    expect(all.count).toBe(4);
    expect(all.totals).toEqual([
      { crop: 'Apples', unit: 'lb', amount: 5, picks: 2, lb: 5, value: 15 },
      { crop: 'Apples', unit: 'oz', amount: 16, picks: 1, lb: 1, value: 3 },
      { crop: 'Pears', unit: 'ct', amount: 5, picks: 1, lb: 0, value: 0 },
    ]);
    const apples = ok(
      await ACTIONS.get_harvests(db, { crop: 'apples', end: '2026-07-06' }, NOW, TZ)
    );
    expect(apples.count).toBe(3);
    expect((apples.harvests as { date: string }[]).map((h) => h.date)).toEqual([
      '2026-07-05',
      '2026-07-01',
      '2026-06-01',
    ]);
  });

  it('refuses a crop it cannot find and dates the wrong way round', async () => {
    const { db } = await garden();
    expect(refused(await ACTIONS.get_harvests(db, { crop: 'tomatos' }, NOW, TZ))).toBe(
      'No crop is called "tomatos".'
    );
    expect(
      refused(await ACTIONS.get_harvests(db, { start: '2026-08-01', end: '2026-07-01' }, NOW, TZ))
    ).toMatch(/before/);
  });
});
