// @vitest-environment node
//
// The route the `gardenrx.*` services call, driven as Home Assistant drives
// it: a bearer token, an action name and its data. A refusal comes back as a
// 409 carrying the sentence the integration raises, and a write lands in the
// same database the panel's screens read.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { execute, openForTest } from '@/lib/db/sqlite';
import { makeClient, type DbClient } from '@/lib/db/query';

const SEED = path.join(__dirname, '..', '..', '..', '..', '..', 'seed', 'catalog.json');
const TOKEN = 'a'.repeat(40);
let db: DbClient;

vi.mock('@/lib/db/server', () => ({ createClient: async () => db }));

let POST: (typeof import('./route'))['POST'];

function call(action: string, data: Record<string, unknown>, token = TOKEN) {
  return POST(
    new Request('http://gardenrx/api/ha/action', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ action, data }),
    })
  );
}

beforeAll(async () => {
  ({ POST } = await import('./route'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gardenrx-route-'));
  const file = path.join(dir, 'api_token');
  fs.writeFileSync(file, TOKEN);
  process.env.GARDENRX_HA_TOKEN_FILE = file;
  const raw = openForTest(SEED);
  db = makeClient(async (req) => execute(raw, req));
});

describe('/api/ha/action', () => {
  it('refuses a caller without the token', async () => {
    const res = await call('add_crop', { name: 'Okra' }, 'b'.repeat(40));
    expect(res.status).toBe(401);
  });

  it('adds a crop and a variety, and the next call can name them', async () => {
    const crop = await call('add_crop', { name: 'Okra' });
    expect(crop.status).toBe(200);
    expect(await crop.json()).toMatchObject({ ok: true, name: 'Okra' });
    const variety = await call('add_variety', { crop: 'okra', name: 'Clemson Spineless' });
    expect(await variety.json()).toMatchObject({
      ok: true,
      crop: 'Okra',
      name: 'Clemson Spineless',
    });
    const { data } = await db.from('varieties').select('*').eq('name', 'Clemson Spineless');
    expect(data).toHaveLength(1);
  });

  it('answers a refusal with a 409 and the sentence', async () => {
    const res = await call('log_spray', { crop: 'tomatos', product: 'anything' });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ ok: false, error: 'No crop is called "tomatos".' });
  });

  it('reads the harvests back without writing', async () => {
    const res = await call('get_harvests', { crop: 'okra' });
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ ok: true, crop: 'Okra', count: 0, totals: [] });
  });

  it('names an action it does not have', async () => {
    const res = await call('drop_table', {});
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('unknown action "drop_table"');
  });
});
