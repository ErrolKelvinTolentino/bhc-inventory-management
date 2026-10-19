// Isolated PostgreSQL smoke/integration tests; NEVER connects to Supabase.
// Usage: node database/tests/verify.mjs <path-to-@electric-sql/pglite-package>
// The Auth schema below is a minimal test double, not a Supabase Auth emulator.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

const require = createRequire(import.meta.url);
const { PGlite } = require(process.argv[2] ? resolve(process.argv[2]) : '@electric-sql/pglite');
const db = new PGlite();
let checks = 0;
const ids = { alice: randomUUID(), bob: randomUUID(), staff: randomUUID(), unverified: randomUUID() };
const query = async (sql, params = []) => (await db.query(sql, params)).rows;
const scalar = async (sql, params = []) => Object.values((await query(sql, params))[0])[0];
const equal = (actual, expected, label) => { assert.deepEqual(actual, expected, label); checks++; };
async function fails(fn, code, label) {
  try { await fn(); } catch (error) {
    assert.ok([code].flat().includes(error.code), `${label}: expected ${code}, got ${error.code}: ${error.message}`);
    checks++; return;
  }
  assert.fail(`${label}: expected SQLSTATE ${code}`);
}
async function actor(user, role = 'authenticated') {
  await db.exec('reset role');
  await query("select set_config('request.jwt.claim.sub', $1, false)", [user ?? '']);
  await db.exec(`set role ${role}`); // Only fixed test role names, never user input.
}
async function stock(facility, item, type, quantity, options = {}) {
  return scalar(`select public.post_stock_transaction(
    p_facility_id => $1, p_item_id => $2, p_transaction_type => $3,
    p_quantity => $4, p_idempotency_key => $5, p_batch_id => $6,
    p_batch_number => $7, p_expiry_date => $8, p_reason => $9,
    p_reference_number => $10, p_source_destination => $11,
    p_corrects_transaction_id => $12)`, [facility, item, type, quantity,
    options.key ?? randomUUID(), options.batch ?? null, options.lot ?? null,
    options.expiry ?? null, options.reason ?? null, options.reference ?? null,
    options.destination ?? null, options.corrects ?? null]);
}
async function item(facility, code, name, type = 'medicine', options = {}) {
  return scalar(`select public.save_item(p_facility_id => $1, p_code => $2, p_name => $3,
    p_item_type => $4, p_unit => $5, p_category_id => $6, p_expiry_required => $7,
    p_item_id => $8)`, [facility, code, name, type, options.unit ?? 'tablet',
    options.category ?? null, options.expiryRequired ?? true, options.id ?? null]);
}
const balance = (batch) => scalar('select quantity_on_hand from public.inventory_batches where id = $1', [batch]);

try {
  await db.exec(`
    create role anon nologin;
    create role authenticated nologin;
    create schema auth;
    create table auth.users (
      id uuid primary key, email_confirmed_at timestamptz, raw_user_meta_data jsonb default '{}'
    );
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    grant usage on schema auth to authenticated, anon;
    grant execute on function auth.uid() to authenticated, anon;
    -- Simulate projects with broad Supabase defaults: the baseline must revoke
    -- these privileges rather than merely relying on a clean PostgreSQL default.
    alter default privileges in schema public grant all on tables to anon, authenticated;
    alter default privileges in schema public grant execute on functions to anon, authenticated;
  `);
  // Existing accounts are backfilled, newly created accounts use the trigger.
  await query(`insert into auth.users values ($1, now(), '{"display_name":"Alice"}')`, [ids.alice]);
  const baseline = (await readFile(new URL('../supabase_setup.sql', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
  const migration = (await readFile(new URL('../../supabase/migrations/20261019000100_initial_inventory.sql', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
  equal(migration === baseline.replace('\nbegin;\n', '\n').replace(/commit;\n$/, ''), true,
    'CLI baseline matches standalone setup without transaction wrappers');
  await db.exec(migration);
  await db.exec(await readFile(new URL('./verify_deployment.sql', import.meta.url), 'utf8'));
  checks++;
  equal(await scalar('select count(*)::integer from public.profiles'), 1, 'existing Auth account backfilled');
  for (const [name, id] of Object.entries(ids).filter(([name]) => name !== 'alice')) {
    await query(`insert into auth.users(id, email_confirmed_at, raw_user_meta_data)
      values ($1, case when $2 then now() else null end, jsonb_build_object('display_name', $3::text))`,
      [id, name !== 'unverified', name]);
  }
  equal(await scalar('select count(*)::integer from public.profiles'), 4, 'new Auth accounts create profiles');
  equal(await scalar(`select count(*)::integer from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relkind='r' and c.relrowsecurity`), 9, 'all tables enable RLS');
  for (const table of ['facilities', 'facility_memberships', 'categories', 'items', 'inventory_batches',
    'stock_transactions', 'stock_transaction_lines', 'audit_events']) {
    equal(await scalar("select has_table_privilege('authenticated', $1, 'INSERT,UPDATE,DELETE,TRUNCATE')",
      [`public.${table}`]), false, `${table}: no direct authenticated writes`);
    equal(await scalar("select has_table_privilege('anon', $1, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
      [`public.${table}`]), false, `${table}: no anonymous access`);
  }
  equal(await scalar("select has_function_privilege('authenticated','private.require_access(uuid,boolean)','EXECUTE')"),
    false, 'internal write helper not callable by clients');
  equal(await scalar("select has_column_privilege('authenticated','public.profiles','created_at','UPDATE')"),
    false, 'profile creation timestamps protected');

  await actor(null, 'anon');
  await fails(() => query('select * from public.items'), '42501', 'anonymous reads denied');
  await fails(() => query("select public.register_facility('No')"), '42501', 'anonymous RPC denied');
  await actor(ids.unverified);
  await fails(() => query("select public.register_facility('No')"), '42501', 'unverified onboarding denied');
  await actor(null);
  await fails(() => query("select public.register_facility('No')"), '42501', 'missing identity denied');

  await actor(ids.alice);
  const facilityA = await scalar("select public.register_facility('Clinic A')");
  await fails(() => query("select public.register_facility('   ')"), '23514', 'blank facility denied');
  equal(await scalar('select count(*)::integer from public.facilities'), 1, 'failed registration atomic');
  await fails(() => query("select public.register_facility('Invalid timezone', 'Bogus/Zone')"),
    '22023', 'invalid timezone denied');
  await actor(ids.bob);
  const facilityB = await scalar("select public.register_facility('Clinic B')");
  const catB = await scalar("select public.save_category($1, 'Pain relief', 'medicine')", [facilityB]);
  const itemB = await item(facilityB, 'MED-01', 'Paracetamol', 'medicine', { category: catB });

  await actor(ids.alice);
  equal(await scalar('select count(*)::integer from public.facilities'), 1, 'facility RLS');
  equal(await scalar('select count(*)::integer from public.items where id = $1', [itemB]), 0, 'item RLS');
  equal(await scalar('select count(*)::integer from public.profiles where id = $1', [ids.bob]), 0, 'profile RLS');
  await fails(() => query('select public.update_facility($1,$2,$3)', [facilityB, 'Hijacked', 'UTC']),
    '42501', 'foreign facility update denied');
  await query('select public.set_facility_member($1,$2)', [facilityA, ids.staff]);
  const catA = await scalar("select public.save_category($1, 'Pain relief', 'medicine')", [facilityA]);
  const itemA = await item(facilityA, 'MED-01', 'Paracetamol', 'medicine', { category: catA });
  await fails(() => item(facilityA, 'FOREIGN-EDIT', 'Foreign edit', 'medicine', { id: itemB }),
    '22023', 'foreign item update denied');
  await fails(() => item(facilityA, 'FOREIGN', 'Bad category', 'medicine', { category: catB }),
    '23503', 'composite category facility FK');
  await fails(() => item(facilityA, 'med-01', 'Duplicate code'), '23505', 'case-insensitive item codes');
  equal(await scalar('select stock_status from public.inventory_summary where item_id=$1', [itemA]),
    'out_of_stock', 'empty item out of stock');
  await query('select public.update_facility($1,$2,$3)', [facilityA, 'Renamed Clinic A', 'Asia/Manila']);
  equal(await scalar(`select count(*)::integer from public.audit_events where table_name='facilities'
    and action='UPDATE' and old_data->>'name'='Clinic A' and new_data->>'name'='Renamed Clinic A'`),
    1, 'facility activity records old and new values');
  await fails(() => query('select public.set_facility_member($1,$2,$3,$4)',
    [facilityA, ids.alice, 'staff', true]), '23514', 'last administrator protected');

  await actor(ids.staff);
  equal(await scalar('select count(*)::integer from public.profiles where id=$1', [ids.alice]), 1, 'shared staff identity');
  equal(await scalar('select count(*)::integer from public.audit_events'), 0, 'staff cannot read admin activity');
  await fails(() => item(facilityA, 'STAFF', 'Unauthorized'), '42501', 'staff catalog writes denied');
  await fails(() => query('select public.set_facility_member($1,$2,$3)', [facilityA, ids.staff, 'admin']),
    '42501', 'self-promotion denied');
  await fails(() => query('select public.set_facility_member($1,$2)', [facilityB, ids.staff]),
    '42501', 'self-joining foreign facility denied');
  await fails(() => query('update public.inventory_batches set quantity_on_hand=999'), '42501', 'direct balances denied');
  await fails(() => query('insert into public.facility_memberships(facility_id,user_id,role) values($1,$2,$3)',
    [facilityB, ids.staff, 'admin']), '42501', 'direct membership writes denied');
  await fails(() => query('update public.profiles set id=$1 where id=$2', [ids.bob, ids.staff]),
    '42501', 'profile identity changes denied');
  await query('update public.profiles set display_name=$1 where id=$2', ['Casey', ids.staff]);
  const today = await scalar("select (now() at time zone 'Asia/Manila')::date::text");
  const early = await scalar("select ((now() at time zone 'Asia/Manila')::date+10)::text");
  const late = await scalar("select ((now() at time zone 'Asia/Manila')::date+60)::text");
  const expired = await scalar("select ((now() at time zone 'Asia/Manila')::date-1)::text");
  await fails(() => stock(facilityA, itemA, 'receipt', 10, { lot: 'NO-EXPIRY' }),
    '22023', 'medicines require expiry');
  const key = randomUUID();
  const receipt = await stock(facilityA, itemA, 'receipt', 100, { key, lot: 'EARLY', expiry: early });
  equal(await stock(facilityA, itemA, 'receipt', 100, { key, lot: 'EARLY', expiry: early }), receipt, 'idempotent receipt');
  await fails(() => stock(facilityA, itemA, 'receipt', 101, { key, lot: 'EARLY', expiry: early }),
    '22023', 'idempotency key payload mismatch');
  await fails(() => stock(facilityA, itemB, 'receipt', 100, { key, lot: 'EARLY', expiry: early }),
    '22023', 'idempotency key cannot be reused for another item');
  await stock(facilityA, itemA, 'receipt', 50, { lot: 'LATE', expiry: late });
  await stock(facilityA, itemA, 'receipt', 15, { lot: 'EXPIRED', expiry: expired });
  const batchEarly = await scalar("select id from public.inventory_batches where batch_number='EARLY'");
  const batchLate = await scalar("select id from public.inventory_batches where batch_number='LATE'");
  const batchExpired = await scalar("select id from public.inventory_batches where batch_number='EXPIRED'");
  const summary = (await query(`select physical_quantity,usable_quantity,expired_quantity,near_expiry_quantity
    from public.inventory_summary where item_id=$1`, [itemA]))[0];
  equal(summary, { physical_quantity: 165, usable_quantity: 150, expired_quantity: 15, near_expiry_quantity: 100 },
    'physical/usable/expired/near-expiry quantities');
  const issue = await stock(facilityA, itemA, 'issue', 120, { destination: 'Clinic use' });
  equal(await balance(batchEarly), 0, 'FEFO consumes earliest batch');
  equal(await balance(batchLate), 30, 'FEFO allocates remainder to later batch');
  equal(await scalar('select count(*)::integer from public.stock_transaction_lines where transaction_id=$1', [issue]),
    2, 'multi-batch issue history');
  equal(await scalar('select actor_name from public.stock_transactions where id=$1', [issue]), 'Casey', 'actor snapshot');
  const transactionCount = await scalar('select count(*)::integer from public.stock_transactions');
  await fails(() => stock(facilityA, itemA, 'issue', 40), '23514', 'insufficient usable stock');
  equal(await balance(batchLate), 30, 'failed FEFO allocation rolls back balances');
  equal(await scalar('select count(*)::integer from public.stock_transactions'), transactionCount, 'failed history rolls back');
  await fails(() => stock(facilityA, itemA, 'issue', 1, { batch: batchExpired }), '23514', 'expired batch issue denied');
  await fails(() => stock(facilityA, itemA, 'adjustment', 28, { batch: batchLate, reason: 'Count' }),
    '42501', 'staff adjustment denied');
  await fails(() => stock(facilityA, itemA, 'disposal', 15, { batch: batchExpired, reason: 'Expired' }),
    '42501', 'staff disposal denied');
  await fails(() => stock(facilityB, itemB, 'receipt', 1, { lot: 'X', expiry: late }),
    '42501', 'foreign stock mutation denied');
  await fails(() => query('delete from public.stock_transactions where id=$1', [issue]), '42501', 'direct history deletion denied');

  await actor(ids.alice);
  await fails(() => stock(facilityA, itemA, 'adjustment', 28, { batch: batchLate }), '22023', 'adjustment requires reason');
  const adjustment = await stock(facilityA, itemA, 'adjustment', 28, { batch: batchLate, reason: 'Physical count' });
  equal(await balance(batchLate), 28, 'absolute count adjustment');
  equal(await scalar('select quantity_change from public.stock_transactions where id=$1', [adjustment]), -2, 'adjustment delta history');
  await stock(facilityA, itemA, 'receipt', 2, { batch: batchLate, reason: 'Count correction', corrects: adjustment });
  equal(await balance(batchLate), 30, 'linked correction adds a compensating entry');
  await fails(() => stock(facilityA, itemA, 'receipt', 1,
    { batch: batchLate, reason: 'Wrong item correction', corrects: randomUUID() }), '23503', 'invalid correction FK');
  await fails(() => query('select public.set_item_archived($1,$2,true)', [facilityA, itemA]),
    '23514', 'cannot archive physical stock');
  await stock(facilityA, itemA, 'disposal', 15, { batch: batchExpired, reason: 'Expired stock removed' });
  equal(await balance(batchExpired), 0, 'disposal removes expired physical stock');
  await fails(() => item(facilityA, 'MED-01', 'Paracetamol', 'medicine', { id: itemA, unit: 'box' }),
    '23514', 'unit cannot change after transactions');
  await item(facilityA, 'MED-01', 'Paracetamol renamed', 'medicine', { id: itemA, category: catA });
  equal(await scalar('select item_name from public.stock_transactions where id=$1', [receipt]), 'Paracetamol', 'history item snapshot preserved');
  await fails(() => query('select public.delete_unused_item($1,$2)', [facilityA, itemA]),
    ['23001', '23503'], 'used item deletion denied');
  const unused = await item(facilityA, 'UNUSED', 'Unused');
  await query('select public.delete_unused_item($1,$2)', [facilityA, unused]);
  equal(await scalar('select count(*)::integer from public.items where id=$1', [unused]), 0, 'unused item deletion');

  // Date boundary and non-expiring supply batches.
  await stock(facilityA, itemA, 'receipt', 1, { lot: 'TODAY', expiry: today });
  const todayBatch = await scalar("select id from public.inventory_batches where batch_number='TODAY'");
  await stock(facilityA, itemA, 'issue', 1, { batch: todayBatch });
  equal(await balance(todayBatch), 0, 'expiry date usable through today');
  const supply = await item(facilityA, 'SUP-01', 'Gloves', 'supply', { unit: 'piece', expiryRequired: false });
  await stock(facilityA, supply, 'receipt', 10, { lot: 'UNDATED' });
  await stock(facilityA, supply, 'receipt', 5, { lot: 'UNDATED' });
  equal(await scalar('select count(*)::integer from public.inventory_batches where item_id=$1', [supply]), 1, 'undated lot deduplicates');
  const supplyBatch = await scalar('select id from public.inventory_batches where item_id=$1', [supply]);
  await fails(() => stock(facilityA, itemA, 'receipt', 1, { batch: supplyBatch }), '22023', 'wrong-item batch rejected');
  await stock(facilityA, supply, 'adjustment', 0, { batch: supplyBatch, reason: 'Full loss' });
  equal(await balance(supplyBatch), 0, 'zero count allowed');
  await query('select public.set_item_archived($1,$2,true)', [facilityA, supply]);
  await fails(() => stock(facilityA, supply, 'receipt', 1, { batch: supplyBatch }), '23514', 'archived item stock denied');
  equal(await scalar('select supply_items::integer from public.facility_dashboard where facility_id=$1', [facilityA]),
    0, 'dashboard excludes archived items');

  // Revocation is effective immediately, including RPCs and invoker views.
  await query('select public.set_facility_member($1,$2,$3,$4)', [facilityA, ids.staff, 'staff', false]);
  await actor(ids.staff);
  equal(await scalar('select count(*)::integer from public.items'), 0, 'revoked inventory reads');
  equal(await scalar('select count(*)::integer from public.inventory_summary'), 0, 'revoked aggregate reads');
  equal(await scalar('select count(*)::integer from public.stock_transactions'), 0, 'revoked stock history reads');
  await fails(() => stock(facilityA, itemA, 'issue', 1), '42501', 'revoked stock writes');
  await actor(ids.bob);
  equal(await scalar('select count(*)::integer from public.stock_transactions'), 0, 'foreign transaction history hidden');
  equal(await scalar('select count(*)::integer from public.stock_transaction_lines'), 0, 'foreign batch history hidden');
  equal(await scalar('select count(*)::integer from public.inventory_summary'), 1, 'foreign summary hidden');

  await actor(ids.alice);
  await query('select public.set_facility_member($1,$2,$3)', [facilityA, ids.staff, 'admin']);
  await query('select public.set_facility_member($1,$2,$3)', [facilityA, ids.alice, 'staff']);
  equal(await scalar('select private.is_admin($1)', [facilityA]), false, 'demotion allowed with another admin');
  await fails(() => query('select public.set_facility_member($1,$2,$3)', [facilityA, ids.alice, 'admin']),
    '42501', 'demoted admin loses member management');

  await actor(null, 'postgres');
  await fails(() => query('update public.stock_transactions set reason=$1 where id=$2', ['Tamper', issue]),
    '55000', 'history trigger blocks privileged update');
  await fails(() => query('delete from public.stock_transaction_lines where transaction_id=$1', [issue]),
    '55000', 'history trigger blocks privileged line deletion');
  await fails(() => query('delete from public.audit_events'), '55000', 'audit trigger blocks privileged deletion');
  equal(await scalar(`select count(*)::integer from public.inventory_batches b where b.quantity_on_hand <>
    coalesce((select sum(l.quantity_change) from public.stock_transaction_lines l where l.batch_id=b.id),0)`),
    0, 'every batch reconciles to its ledger');
  equal(await scalar(`select count(*)::integer from public.stock_transactions t where t.quantity_change <>
    coalesce((select sum(l.quantity_change) from public.stock_transaction_lines l where l.transaction_id=t.id),0)`),
    0, 'every header reconciles to its lines');
  equal(await scalar(`select count(*)::integer from public.audit_events
    where table_name='items' and action='DELETE' and record_id=$1`, [unused]), 1, 'deleted unused item retains audit history');
  console.log(`PASS: ${checks} database checks (isolated PGlite PostgreSQL runtime).`);
  console.log('Concurrency locks and real Supabase Auth/PostgREST integration still need deployment-environment tests.');
} finally {
  await db.close();
}
