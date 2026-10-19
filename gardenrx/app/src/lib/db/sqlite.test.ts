// @vitest-environment node
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { execute, openForTest, type SqliteDb } from './sqlite';
import { makeClient, type DbRequest } from './query';
import { SCHEMA } from './schema';

const SEED = path.join(__dirname, '..', '..', '..', 'seed', 'catalog.json');

function client(db: SqliteDb) {
  return makeClient(async (req: DbRequest) => execute(db, req));
}

describe('the SQLite executor', () => {
  it('creates every table the app names', () => {
    const db = openForTest();
    const have = db
      .prepare("SELECT name FROM sqlite_master WHERE type = 'table'")
      .all()
      .map((r) => r.name);
    for (const t of Object.keys(SCHEMA)) expect(have).toContain(t);
  });

  it('round-trips booleans and JSON as the app wrote them', async () => {
    const db = client(openForTest());
    const { data: crop } = await db
      .from('crops')
      .insert({ name: 'Apples', crop_group_id: null })
      .select()
      .single();
    expect(crop?.is_active).toBe(true);
    expect(crop?.track_fungicide).toBe(false);
    const { data: v } = await db
      .from('varieties')
      .insert({ name: 'Liberty', crop_id: crop!.id, disease_susceptibility: { scab: 'resistant' } })
      .select()
      .single();
    expect(v?.disease_susceptibility).toEqual({ scab: 'resistant' });
    const { data: active } = await db.from('crops').select('*').eq('is_active', true);
    expect(active).toHaveLength(1);
  });

  it('a write without select() returns no rows, as supabase-js does', async () => {
    const db = client(openForTest());
    const res = await db.from('crops').insert({ name: 'Figs', crop_group_id: null });
    expect(res.error).toBeNull();
    expect(res.data).toBeNull();
  });

  it('orders, limits and projects columns', async () => {
    const db = client(openForTest());
    await db.from('crops').insert([
      { name: 'Pears', crop_group_id: null },
      { name: 'Apples', crop_group_id: null },
    ]);
    const { data } = await db.from('crops').select('id, name').order('name').limit(1);
    expect(data).toEqual([{ id: 2, name: 'Apples' }]);
  });

  it('single() is an error unless exactly one row matches; maybeSingle() allows none', async () => {
    const db = client(openForTest());
    const none = await db.from('crops').select('*').eq('id', 9).single();
    expect(none.error?.code).toBe('PGRST116');
    const maybe = await db.from('crops').select('*').eq('id', 9).maybeSingle();
    expect(maybe.error).toBeNull();
    expect(maybe.data).toBeNull();
  });

  it('deleting a parent takes its join rows with it', async () => {
    const db = client(openForTest(SEED));
    const { data: q } = await db.from('queued_sprays').insert({ notes: 'x' }).select().single();
    await db.from('queued_spray_products').insert({ queued_spray_id: q!.id, product_id: 32 });
    await db.from('queued_sprays').delete().eq('id', q!.id);
    const { data } = await db.from('queued_spray_products').select('*');
    expect(data).toEqual([]);
  });

  it('refuses names it does not know, and never builds them into SQL', () => {
    const db = openForTest();
    const bad = (req: DbRequest) => execute(db, req).error?.message ?? '';
    expect(bad({ table: 'crops; DROP TABLE crops', action: 'select' })).toMatch(/does not exist/);
    expect(bad({ table: 'crops', action: 'select', columns: 'name, "x"' })).toMatch(
      /does not exist/
    );
    expect(
      bad({
        table: 'crops',
        action: 'select',
        filters: [{ column: 'id = 1 OR 1', op: 'eq', value: 1 }],
      })
    ).toMatch(/does not exist/);
    expect(
      bad({ table: 'crops', action: 'insert', values: JSON.parse('{"__proto__": 1, "name": "a"}') })
    ).toMatch(/column crops.__proto__ does not exist/);
    expect(
      bad({ table: 'crops', action: 'select', order: [{ column: 'name desc', ascending: true }] })
    ).toMatch(/does not exist/);
    expect(bad({ table: 'crops', action: 'delete' })).toMatch(/needs a filter/);
    expect(bad({ table: 'crops', action: 'update', values: { name: 'x' } })).toMatch(
      /needs a filter/
    );
  });

  it('values are bound, so a value can never be SQL', async () => {
    const db = client(openForTest());
    await db.from('crops').insert({ name: "x'); DROP TABLE crops; --", crop_group_id: null });
    const { data } = await db.from('crops').select('name');
    expect(data?.[0].name).toBe("x'); DROP TABLE crops; --");
  });

  it('seeds the catalog once and never overwrites an edit', async () => {
    const raw = openForTest(SEED);
    const db = client(raw);
    const { data: products } = await db.from('products').select('id');
    expect(products!.length).toBeGreaterThan(200);
    await db.from('products').update({ brand: 'Mine' }).eq('id', 32);
    // A second seed pass at the same version is a no-op; a newer one only adds.
    raw.exec('DELETE FROM gardenrx_meta');
    const { seed } = await import('./sqlite');
    seed(raw, SEED);
    const { data: p } = await db.from('products').select('brand').eq('id', 32).single();
    expect(p?.brand).toBe('Mine');
    const { data: settings } = await db.from('app_settings').select('*').eq('id', 1).maybeSingle();
    expect(settings?.weather_bar).toBe(true);
  });
});
