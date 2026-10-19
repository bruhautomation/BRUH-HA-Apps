/**
 * The executor that runs a `DbRequest` against SQLite. Server only.
 *
 * The database is one file — `/data/gardenrx.db` in the add-on, which Home
 * Assistant's backups already include — opened through Node's built-in
 * `node:sqlite`, so the image needs no native module compiled for musl.
 * It is loaded with `process.getBuiltinModule` rather than an import: the
 * bundler has no business resolving it, and a builtin that a bundler does not
 * recognise is a build that fails for a reason nothing to do with the code.
 *
 * Every identifier that reaches SQL is checked against `SCHEMA` first and then
 * quoted; every value is a bound parameter. The request arrives over HTTP from
 * the browser half, so nothing in it is trusted.
 */

import fs from 'node:fs';
import path from 'node:path';
import { SCHEMA, TABLE_ORDER, primaryKeyOf, tableOf, type Column, type Table } from './schema';
import { dbError, type DbRequest, type DbResult, type Filter } from './query';

// The slice of node:sqlite this file uses. @types/node for the Node version
// the app is checked against predates the module, and a hand-written
// interface over three methods is cheaper than chasing it.
type SqlValue = null | number | bigint | string | Uint8Array;
interface Statement {
  all(...params: SqlValue[]): Record<string, unknown>[];
  run(...params: SqlValue[]): unknown;
}
export interface SqliteDb {
  exec(sql: string): void;
  prepare(sql: string): Statement;
  close(): void;
}

const MAX_LIMIT = 10000;
const SEED_KEY = 'catalog_seed_version';

const q = (ident: string) => `"${ident.replace(/"/g, '""')}"`;

function openDatabase(file: string): SqliteDb {
  const getBuiltin = (process as unknown as { getBuiltinModule?: (id: string) => unknown })
    .getBuiltinModule;
  const mod = getBuiltin?.('node:sqlite') as
    | { DatabaseSync: new (file: string) => SqliteDb }
    | undefined;
  if (!mod) {
    throw new Error('node:sqlite is not available — GardenRX needs Node 22.13 or newer');
  }
  if (file !== ':memory:') fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
  const db = new mod.DatabaseSync(file);
  db.exec('PRAGMA foreign_keys = ON');
  db.exec('PRAGMA busy_timeout = 5000');
  if (file !== ':memory:') db.exec('PRAGMA journal_mode = WAL');
  return db;
}

function columnSql(name: string, col: Column, table: Table): string {
  if (!table.primaryKey && name === 'id') return `${q('id')} INTEGER PRIMARY KEY AUTOINCREMENT`;
  const type =
    col.type === 'real' ? 'REAL' : col.type === 'int' || col.type === 'bool' ? 'INTEGER' : 'TEXT';
  let sql = `${q(name)} ${type}`;
  if (col.required) sql += ' NOT NULL';
  if (col.default !== undefined) sql += ` DEFAULT ${col.default}`;
  if (col.references) {
    sql += ` REFERENCES ${q(col.references.table)}(${q(col.references.column ?? 'id')})`;
    sql += ` ON DELETE ${col.references.onDelete}`;
  }
  return sql;
}

/** Create what is missing, and add any column a newer release introduced. */
export function migrate(db: SqliteDb): void {
  db.exec('CREATE TABLE IF NOT EXISTS "gardenrx_meta" ("key" TEXT PRIMARY KEY, "value" TEXT)');
  for (const name of TABLE_ORDER) {
    const table = SCHEMA[name];
    const cols = Object.entries(table.columns).map(([c, col]) => columnSql(c, col, table));
    if (table.primaryKey) cols.push(`PRIMARY KEY (${table.primaryKey.map(q).join(', ')})`);
    db.exec(`CREATE TABLE IF NOT EXISTS ${q(name)} (${cols.join(', ')})`);
    const have = new Set(
      db
        .prepare(`PRAGMA table_info(${q(name)})`)
        .all()
        .map((r) => r.name)
    );
    for (const [c, col] of Object.entries(table.columns)) {
      if (have.has(c)) continue;
      // SQLite cannot add a NOT NULL column without a default to a table that
      // has rows, so such a column arrives nullable rather than not at all.
      const loose = col.default === undefined ? { ...col, required: false } : col;
      db.exec(`ALTER TABLE ${q(name)} ADD COLUMN ${columnSql(c, loose, table)}`);
    }
  }
}

interface Seed {
  version: number;
  tables: Record<string, Record<string, unknown>[]>;
}

/**
 * The reference catalog — products, ingredients, label uses, crop groups,
 * phenology, tank-mix rules — that the app is useless without. Loaded once
 * per catalog version, and only ever ADDED: a row somebody edited keeps their
 * edit, because INSERT OR IGNORE never overwrites.
 */
export function seed(db: SqliteDb, seedFile: string): void {
  db.exec('INSERT OR IGNORE INTO "app_settings" ("id") VALUES (1)');
  if (!fs.existsSync(/*turbopackIgnore: true*/ seedFile)) return;
  const data = JSON.parse(fs.readFileSync(/*turbopackIgnore: true*/ seedFile, 'utf8')) as Seed;
  const row = db.prepare('SELECT "value" FROM "gardenrx_meta" WHERE "key" = ?').all(SEED_KEY)[0];
  const have = row ? Number(row.value) : 0;
  if (have >= data.version) return;
  db.exec('BEGIN');
  try {
    for (const name of TABLE_ORDER) {
      const rows = data.tables[name];
      const table = tableOf(name);
      if (!rows || !table) continue;
      for (const r of rows) {
        const cols = Object.keys(r).filter((c) => c in table.columns);
        if (!cols.length) continue;
        const sql = `INSERT OR IGNORE INTO ${q(name)} (${cols.map(q).join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`;
        db.prepare(sql).run(...cols.map((c) => encode(table.columns[c], r[c])));
      }
    }
    db.prepare('INSERT OR REPLACE INTO "gardenrx_meta" ("key", "value") VALUES (?, ?)').run(
      SEED_KEY,
      String(data.version)
    );
    db.exec('COMMIT');
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
}

function encode(col: Column, value: unknown): SqlValue {
  if (value === null || value === undefined) return null;
  if (col.type === 'json') return JSON.stringify(value);
  if (col.type === 'bool') return value ? 1 : 0;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number' || typeof value === 'string' || typeof value === 'bigint') {
    return value;
  }
  throw new Error(`a ${typeof value} cannot be stored in a ${col.type} column`);
}

function decode(table: Table, row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    const col = table.columns[k];
    if (v === null || !col) out[k] = v;
    else if (col.type === 'bool') out[k] = Boolean(v);
    else if (col.type === 'json') {
      try {
        out[k] = JSON.parse(String(v));
      } catch {
        out[k] = v;
      }
    } else if (typeof v === 'bigint') out[k] = Number(v);
    else out[k] = v;
  }
  return out;
}

class Refused extends Error {}

function needColumn(table: Table, name: string, tableName: string): Column {
  const col = typeof name === 'string' ? table.columns[name] : undefined;
  if (!col || !Object.prototype.hasOwnProperty.call(table.columns, name)) {
    throw new Refused(`column ${tableName}.${String(name)} does not exist`);
  }
  return col;
}

function whereSql(
  table: Table,
  tableName: string,
  filters: Filter[] | undefined,
  params: SqlValue[]
): string {
  if (!filters?.length) return '';
  const parts = filters.map((f) => {
    const col = needColumn(table, f.column, tableName);
    const c = q(f.column);
    switch (f.op) {
      case 'eq':
      case 'neq': {
        if (f.value === null || f.value === undefined) {
          return `${c} IS ${f.op === 'eq' ? '' : 'NOT '}NULL`;
        }
        params.push(encode(col, f.value));
        return `${c} ${f.op === 'eq' ? '=' : '!='} ?`;
      }
      case 'gt':
      case 'gte':
      case 'lt':
      case 'lte': {
        params.push(encode(col, f.value));
        const sym = { gt: '>', gte: '>=', lt: '<', lte: '<=' }[f.op];
        return `${c} ${sym} ?`;
      }
      case 'in': {
        if (!Array.isArray(f.value)) throw new Refused(`in() on ${f.column} needs a list`);
        if (!f.value.length) return '0';
        for (const v of f.value) params.push(encode(col, v));
        return `${c} IN (${f.value.map(() => '?').join(', ')})`;
      }
      case 'is': {
        if (f.value === null) return `${c} IS NULL`;
        if (typeof f.value === 'boolean') return `${c} = ${f.value ? 1 : 0}`;
        throw new Refused(`is() on ${f.column} takes null, true or false`);
      }
      default:
        throw new Refused(`unknown filter ${String(f.op)}`);
    }
  });
  return ` WHERE ${parts.join(' AND ')}`;
}

function project(
  table: Table,
  tableName: string,
  columns: string | undefined,
  rows: Record<string, unknown>[]
) {
  const decoded = rows.map((r) => decode(table, r));
  const spec = (columns ?? '*').trim();
  if (spec === '*' || spec === '') return decoded;
  const wanted = spec
    .split(',')
    .map((c) => c.trim())
    .filter(Boolean);
  for (const c of wanted) needColumn(table, c, tableName);
  return decoded.map((r) => Object.fromEntries(wanted.map((c) => [c, r[c]])));
}

function valuesOf(table: Table, tableName: string, v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v))
    throw new Refused('values must be an object');
  const out = new Map<string, unknown>();
  for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
    if (val === undefined) continue;
    needColumn(table, k, tableName);
    out.set(k, val);
  }
  return Object.fromEntries(out);
}

/** Run one request. Never throws: a refusal or a SQLite error is `error`. */
export function execute(db: SqliteDb, req: DbRequest): DbResult<unknown> {
  try {
    if (!req || typeof req !== 'object') throw new Refused('empty request');
    const table = tableOf(String(req.table));
    if (!table) throw new Refused(`relation "${String(req.table)}" does not exist`);
    const name = String(req.table);
    const params: SqlValue[] = [];
    let rows: Record<string, unknown>[];

    switch (req.action) {
      case 'select': {
        let sql = `SELECT * FROM ${q(name)}`;
        sql += whereSql(table, name, req.filters, params);
        if (req.order?.length) {
          sql +=
            ' ORDER BY ' +
            req.order
              .map((o) => {
                needColumn(table, o.column, name);
                return `${q(o.column)} ${o.ascending === false ? 'DESC' : 'ASC'}`;
              })
              .join(', ');
        }
        if (req.limit !== undefined) {
          const n = Number(req.limit);
          if (!Number.isInteger(n) || n < 0 || n > MAX_LIMIT) throw new Refused('bad limit');
          sql += ` LIMIT ${n}`;
        }
        rows = db.prepare(sql).all(...params);
        break;
      }
      case 'insert':
      case 'upsert': {
        const list = Array.isArray(req.values) ? req.values : [req.values];
        if (!list.length) throw new Refused('nothing to insert');
        const pk = req.onConflict
          ? req.onConflict.split(',').map((c) => c.trim())
          : primaryKeyOf(table);
        for (const c of pk) needColumn(table, c, name);
        rows = [];
        db.exec('BEGIN');
        try {
          for (const raw of list) {
            const vals = valuesOf(table, name, raw);
            const cols = Object.keys(vals);
            let sql = cols.length
              ? `INSERT INTO ${q(name)} (${cols.map(q).join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`
              : `INSERT INTO ${q(name)} DEFAULT VALUES`;
            if (req.action === 'upsert' && cols.length) {
              const rest = cols.filter((c) => !pk.includes(c));
              sql += ` ON CONFLICT (${pk.map(q).join(', ')}) DO ${
                rest.length
                  ? 'UPDATE SET ' + rest.map((c) => `${q(c)} = excluded.${q(c)}`).join(', ')
                  : 'NOTHING'
              }`;
            }
            sql += ' RETURNING *';
            rows.push(
              ...db.prepare(sql).all(...cols.map((c) => encode(table.columns[c], vals[c])))
            );
          }
          db.exec('COMMIT');
        } catch (e) {
          db.exec('ROLLBACK');
          throw e;
        }
        break;
      }
      case 'update': {
        const vals = valuesOf(table, name, req.values);
        const cols = Object.keys(vals);
        if (!cols.length) throw new Refused('nothing to update');
        if (!req.filters?.length) throw new Refused('an update needs a filter');
        for (const c of cols) params.push(encode(table.columns[c], vals[c]));
        const sql = `UPDATE ${q(name)} SET ${cols.map((c) => `${q(c)} = ?`).join(', ')}${whereSql(table, name, req.filters, params)} RETURNING *`;
        rows = db.prepare(sql).all(...params);
        break;
      }
      case 'delete': {
        if (!req.filters?.length) throw new Refused('a delete needs a filter');
        const sql = `DELETE FROM ${q(name)}${whereSql(table, name, req.filters, params)} RETURNING *`;
        rows = db.prepare(sql).all(...params);
        break;
      }
      default:
        throw new Refused(`unknown action ${String(req.action)}`);
    }

    const isWrite = req.action !== 'select';
    if (isWrite && req.columns === undefined) return { data: null, error: null, status: 201 };
    const data = project(table, name, req.columns, rows);
    if (req.single) {
      if (data.length === 1) return { data: data[0], error: null, status: 200 };
      if (data.length === 0 && req.single === 'maybe')
        return { data: null, error: null, status: 200 };
      return {
        data: null,
        error: dbError(
          `JSON object requested, ${data.length ? 'multiple' : 'no'} rows returned`,
          'PGRST116'
        ),
        status: 406,
      };
    }
    return { data, error: null, status: 200 };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return {
      data: null,
      error: dbError(message, e instanceof Refused ? 'PGRST100' : 'SQLITE'),
      status: 400,
    };
  }
}

// ── The process-wide connection ──

const KEY = Symbol.for('gardenrx.sqlite');
type Holder = { [KEY]?: SqliteDb };

/** Where the database lives. `/data/gardenrx.db` in the add-on. */
export function databasePath(): string {
  return process.env.GARDENRX_DB_PATH || path.join(process.cwd(), 'gardenrx.db');
}

export function seedPath(): string {
  return process.env.GARDENRX_SEED_PATH || path.join(process.cwd(), 'seed', 'catalog.json');
}

export function getDatabase(): SqliteDb {
  const holder = globalThis as unknown as Holder;
  if (!holder[KEY]) {
    const db = openDatabase(databasePath());
    migrate(db);
    seed(db, seedPath());
    holder[KEY] = db;
  }
  return holder[KEY]!;
}

/** For tests: a fresh in-memory database, migrated and seeded. */
export function openForTest(seedFile?: string): SqliteDb {
  const db = openDatabase(':memory:');
  migrate(db);
  if (seedFile) seed(db, seedFile);
  else db.exec('INSERT OR IGNORE INTO "app_settings" ("id") VALUES (1)');
  return db;
}
