/**
 * The part of supabase-js this app actually used, over a request object.
 *
 * GardenRX was written against Supabase, and every screen talks to it through
 * `supabase.from(table).select().eq()…`. Inside Home Assistant there is no
 * Supabase — the data is a SQLite file in the add-on's own /data — so rather
 * than rewrite every screen, this is the same builder with a different end:
 * it collects the call into a `DbRequest` and hands that to an executor. On
 * the server the executor is SQLite itself (`server.ts`); in the browser it is
 * a POST to the app's own `/api/db` (`client.ts`). The screens cannot tell.
 *
 * Only what the app calls is here: select, insert, update, upsert, delete,
 * the comparison filters, order, limit, single and maybeSingle. Anything else
 * is a compile error rather than a silent no-op, which is the point of typing
 * it against `Database`.
 *
 * This module imports nothing that needs Node, because the browser loads it.
 */

import type { Database } from '@/lib/database.types';

type Tables = Database['public']['Tables'];
export type TableName = keyof Tables & string;

export type FilterOp = 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'is';

export interface Filter {
  column: string;
  op: FilterOp;
  value: unknown;
}

export interface DbRequest {
  table: string;
  action: 'select' | 'insert' | 'update' | 'upsert' | 'delete';
  /** Columns to return; '*' or a comma list. Absent on a write means none. */
  columns?: string;
  values?: Record<string, unknown> | Record<string, unknown>[];
  filters?: Filter[];
  order?: { column: string; ascending: boolean }[];
  limit?: number;
  /** 'one' is .single() (exactly one row), 'maybe' is .maybeSingle(). */
  single?: 'one' | 'maybe';
  /** Upsert conflict target; defaults to the table's primary key. */
  onConflict?: string;
}

export interface DbError {
  message: string;
  code: string;
  details: string | null;
  hint: string | null;
}

export interface DbResult<T> {
  data: T | null;
  error: DbError | null;
  count?: null;
  status?: number;
  statusText?: string;
}

export type Executor = (req: DbRequest) => Promise<DbResult<unknown>>;

export function dbError(message: string, code = 'GARDENRX'): DbError {
  return { message, code, details: null, hint: null };
}

export class QueryBuilder<Row, Insert, Update, Result = Row[]> implements PromiseLike<
  DbResult<Result>
> {
  private readonly req: DbRequest;

  constructor(
    private readonly exec: Executor,
    table: string
  ) {
    this.req = { table, action: 'select' };
  }

  private with(patch: Partial<DbRequest>): this {
    Object.assign(this.req, patch);
    return this;
  }

  select(columns = '*'): QueryBuilder<Row, Insert, Update, Row[]> {
    // After a write, select() means "return the rows you wrote" — PostgREST's
    // `Prefer: return=representation`.
    this.with({ columns });
    return this as unknown as QueryBuilder<Row, Insert, Update, Row[]>;
  }

  insert(values: Insert | Insert[]): QueryBuilder<Row, Insert, Update, null> {
    this.with({ action: 'insert', values: values as DbRequest['values'] });
    return this as unknown as QueryBuilder<Row, Insert, Update, null>;
  }

  upsert(
    values: Insert | Insert[],
    options?: { onConflict?: string }
  ): QueryBuilder<Row, Insert, Update, null> {
    this.with({
      action: 'upsert',
      values: values as DbRequest['values'],
      onConflict: options?.onConflict,
    });
    return this as unknown as QueryBuilder<Row, Insert, Update, null>;
  }

  update(values: Update): QueryBuilder<Row, Insert, Update, null> {
    this.with({ action: 'update', values: values as Record<string, unknown> });
    return this as unknown as QueryBuilder<Row, Insert, Update, null>;
  }

  delete(): QueryBuilder<Row, Insert, Update, null> {
    this.with({ action: 'delete' });
    return this as unknown as QueryBuilder<Row, Insert, Update, null>;
  }

  private filter(column: string, op: FilterOp, value: unknown): this {
    (this.req.filters ??= []).push({ column, op, value });
    return this;
  }

  eq<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'eq', value);
  }
  neq<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'neq', value);
  }
  gt<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'gt', value);
  }
  gte<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'gte', value);
  }
  lt<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'lt', value);
  }
  lte<K extends keyof Row & string>(column: K, value: Row[K]): this {
    return this.filter(column, 'lte', value);
  }
  in<K extends keyof Row & string>(column: K, values: readonly Row[K][]): this {
    return this.filter(column, 'in', [...values]);
  }
  is<K extends keyof Row & string>(column: K, value: null | boolean): this {
    return this.filter(column, 'is', value);
  }
  match(query: Partial<Row>): this {
    for (const [k, v] of Object.entries(query)) this.filter(k, 'eq', v);
    return this;
  }

  order(column: keyof Row & string, options?: { ascending?: boolean }): this {
    (this.req.order ??= []).push({ column, ascending: options?.ascending ?? true });
    return this;
  }

  limit(n: number): this {
    return this.with({ limit: n });
  }

  single(): QueryBuilder<Row, Insert, Update, Row> {
    this.with({ single: 'one' });
    return this as unknown as QueryBuilder<Row, Insert, Update, Row>;
  }

  maybeSingle(): QueryBuilder<Row, Insert, Update, Row> {
    this.with({ single: 'maybe' });
    return this as unknown as QueryBuilder<Row, Insert, Update, Row>;
  }

  /** The request as it stands — what the executor will be handed. */
  toRequest(): DbRequest {
    return structuredClone(this.req);
  }

  then<A = DbResult<Result>, B = never>(
    onfulfilled?: ((value: DbResult<Result>) => A | PromiseLike<A>) | null,
    onrejected?: ((reason: unknown) => B | PromiseLike<B>) | null
  ): PromiseLike<A | B> {
    return this.exec(this.toRequest())
      .catch((e: unknown) => ({
        data: null,
        error: dbError(e instanceof Error ? e.message : String(e), 'FETCH'),
      }))
      .then(onfulfilled as never, onrejected as never) as PromiseLike<A | B>;
  }
}

export interface DbClient {
  from<T extends TableName>(
    table: T
  ): QueryBuilder<Tables[T]['Row'], Tables[T]['Insert'], Tables[T]['Update']>;
}

export function makeClient(exec: Executor): DbClient {
  return {
    from(table) {
      return new QueryBuilder(exec, table);
    },
  };
}
