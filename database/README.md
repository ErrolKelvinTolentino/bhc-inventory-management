# Supabase database setup

`supabase_setup.sql` is the initial database baseline. It creates the tables,
indexes, constraints, policies, triggers, read views, and authorized write functions
for the facility inventory application. It does not create a Supabase project,
change Auth settings, insert sample facilities, or deploy the Python application.

The 2026-10-21 incremental migrations make access **administrator-only** and add
private encrypted server sessions for Vercel. The historical baseline below is
unchanged; apply all files under `supabase/migrations/` to a fresh project. The
sample staff login was removed while keeping its historical attribution. See
[DEPLOYMENT.md](../DEPLOYMENT.md) for deployment configuration.

## Deployment and future updates

The initial schema was applied on **2026-10-19** to **BHC Inventory**
(`hmapfyndwrvsapllythc`) using migration `20261019000100_initial_inventory.sql`.
Live deployment checks passed for nine tables, ten RLS policies, eight secured
write functions, three invoker views, and history/Auth triggers. The local and
remote migration histories match.

The repository now has standard Supabase configuration in `supabase/config.toml`
and the deployable baseline in `supabase/migrations/`. The baseline migration
contains the same SQL as `database/supabase_setup.sql`, excluding its standalone
transaction wrapper because the CLI manages that transaction. Keep applied
migrations immutable and create a new migration for future schema changes.

```powershell
npx.cmd --yes supabase link --project-ref hmapfyndwrvsapllythc
npx.cmd --yes supabase migration new describe_your_change
# Edit and verify the newly created supabase/migrations/*.sql file.
npx.cmd --yes supabase db push --linked --dry-run --skip-vault
npx.cmd --yes supabase db push --linked --skip-vault
npx.cmd --yes supabase migration list --linked
npx.cmd --yes supabase db query --linked --file database/tests/verify_deployment.sql
```

The generated CLI config describes local development defaults. No remote Auth
configuration, Vault secrets, or seed data was changed by this deployment.
Link metadata is excluded from Git by `supabase/.gitignore`; a fresh checkout must
link explicitly. Do not rerun the standalone setup file on this deployed project.

## Alternative: apply once to a different fresh project

1. Select the intended Supabase project. This script needs PostgreSQL 15 or newer
   and the standard Supabase `auth.users`, `auth.uid()`, `anon`, and `authenticated` objects.
2. Open its SQL Editor as the database administrator (`postgres`).
3. Run the complete contents of `supabase_setup.sql`. The transaction commits only
   if the entire setup succeeds.
4. Configure Supabase Auth email verification and recovery/redirect URLs for the
   application when those URLs are known. Facility registration requires a
   verified email account.

The baseline is deliberately **not rerunnable** and does not drop existing data.
Do not execute it on an existing application schema without reviewing conflicts.
Use incremental migrations after the first application; see `migrations/README.md`.
Being logged in to the Supabase CLI does not select a target project or apply this
file. Choose either the CLI migration workflow or the standalone SQL route for a
fresh project, never both. If applying through SQL Editor, account for that
baseline in migration history before adopting CLI deployment later.

## Data and access model

| Object | Purpose |
| --- | --- |
| `profiles` | Display names associated with Supabase Auth identities; no credentials |
| `facilities` | Registered facility name, timezone, and near-expiry window |
| `facility_memberships` | Active/inactive administrator access (`admin` only after the incremental migration) |
| `categories` | Facility-owned medicine or supply categories |
| `items` | Medicine and supply catalog, base units, thresholds, and archival status |
| `inventory_batches` | Item lot, exact expiry date, and physical quantity on hand |
| `stock_transactions` | Immutable receipt/issue/adjustment/disposal headers and actor/item snapshots |
| `stock_transaction_lines` | Immutable batch allocations, signed changes, and before/after balances |
| `audit_events` | Immutable administrative activity with old/new record values |

Facilities have separate data even if their display names or item codes match.
Item codes and category names are case-insensitively unique within their facility
(categories are also separated by item type). A profile can belong to multiple
facilities; the future interface can decide whether to expose a workspace switcher.

All nine tables have RLS. Members can read their facility's inventory and stock
history; only administrators can read its administrative activity history.
Profiles are visible to their owner and active colleagues. The only direct table
write granted to an authenticated client is updating its own `display_name`.
Catalog, membership, settings, and stock writes must use the functions below.

Pass the signed-in user's JWT with ordinary API calls. A Supabase service-role
key bypasses RLS and is for trusted server administration only. Never expose the
`private` schema through the Data API or put a service-role key in the browser.
Definer functions use a fixed empty `search_path` and explicit authorization checks.

## RPC functions

Use the Supabase client's `rpc(function_name, parameters)` method with a user
session. For example, the `register_facility` parameters are:

```json
{"p_name": "Barangay Sample Health Center", "p_timezone": "Asia/Manila"}
```

The SQL Editor runs as an administrator without an application user's JWT;
`auth.uid()` will normally be null there. Create application users through
Supabase Auth, not by inserting rows into the Auth schema manually.

| Function | Allowed caller | Behavior |
| --- | --- | --- |
| `register_facility` | Verified account | Creates facility and first admin atomically; returns facility UUID |
| `update_facility` | Facility admin | Sets name, timezone, near-expiry days |
| `set_facility_member` | Facility admin | Adds/updates an existing Auth account's role and active status |
| `save_category` | Facility admin | Creates or updates a category; returns category UUID |
| `save_item` | Facility admin | Creates or fully updates an item; returns item UUID |
| `set_item_archived` | Facility admin | Archives/restores an item; archival requires zero physical stock |
| `delete_unused_item` | Facility admin | Deletes only an item without batches or stock history |
| `post_stock_transaction` | Member, with admin restrictions | Posts atomic stock operation and returns transaction UUID |

`save_category` and `save_item` create when their optional ID parameter is null,
and update when it is supplied. `save_item` is a full-record update: supply the
complete desired record, since omitted optional fields reset to their defaults.
Medicine expiry tracking is always required. Stock unit and item type cannot
change once transactions exist.

The application has no staff/team-management interface. The retained
`set_facility_member` RPC now accepts only administrator roles and still protects
the last active administrator. The historical initial migration contains the old
role definition; the applied administrators-only migration supersedes it.
The last active administrator cannot be demoted or disabled. Historical profile
references deliberately restrict deleting Auth users; deactivate access instead.

### Posting stock

Required parameters: `p_facility_id`, `p_item_id`, `p_transaction_type`,
`p_quantity`, and a client-generated UUID `p_idempotency_key`.

| Type | Quantity meaning | Batch parameters | Permission |
| --- | --- | --- | --- |
| `receipt` | Positive units received | Existing `p_batch_id`, OR `p_batch_number` plus `p_expiry_date` when required | Admin |
| `issue` | Positive units issued | Optional `p_batch_id`; omit for automatic FEFO allocation | Admin |
| `adjustment` | New absolute counted balance, including zero | Required `p_batch_id` and `p_reason` | Admin |
| `disposal` | Positive units physically removed | Required `p_batch_id` and `p_reason` | Admin |

Optional shared parameters: `p_reason`, `p_reference_number`,
`p_source_destination`, and `p_corrects_transaction_id`.

- One transaction covers one item and may allocate an issue across several batches.
- Reuse the same operation key on a retry with the same inputs and account. It
  returns the original transaction without changing stock again. Reusing it with
  different inputs or a different account is rejected.
- Supply either an existing batch ID or new-lot parameters, never both. An item,
  batch number, and expiry date identify a lot within a facility. Identical undated
  supply lots also merge into one batch.
- FEFO uses the earliest usable expiry date, followed by undated supplies, with
  deterministic tie breaking. Expired stock cannot be issued.
- Item row locks serialize stock operations for an item. Facility locks serialize
  permission changes against in-flight writes and protect the last administrator.
- Opening balances are receipts. Adjustments require a reason and reject a count
  that matches the current balance. Nothing silently overwrites quantities.
- Expired receipts are allowed for recording opening/physical stock; those units
  remain unavailable until disposal. Expiration does not automatically dispose stock.
- Corrections require an administrator and reason. The optional correction link
  must point to a transaction for the same facility and item. It is a reference,
  **not an automatic reversal**: choose the compensating quantity/operation explicitly.
- Posted stock and activity history cannot be edited or deleted through the API;
  triggers additionally reject SQL updates/deletes on those history tables.
- Actor, item name/code/unit, batch number, and expiry are snapshotted for history.
- Integer quantities are base units only; pack/unit conversions are not implemented.
- Transactions use their server posting time; no backdating parameter is exposed.

Example receipt RPC parameters (replace example UUIDs):

```json
{
  "p_facility_id": "00000000-0000-0000-0000-000000000001",
  "p_item_id": "00000000-0000-0000-0000-000000000002",
  "p_transaction_type": "receipt",
  "p_quantity": 100,
  "p_idempotency_key": "00000000-0000-0000-0000-000000000003",
  "p_batch_number": "LOT-001",
  "p_expiry_date": "2027-12-31",
  "p_source_destination": "Municipal health office",
  "p_reference_number": "DELIVERY-001"
}
```

## Read views and date defaults

- `inventory_summary`: physical, usable, expired, and near-expiry quantities per
  item, with `in_stock` / `low_stock` / `out_of_stock` status. Includes archived
  items so the application can explicitly filter them.
- `batch_stock_status`: batch details and `usable` / `near_expiry` / `expired`
  status. Filter `quantity_on_hand > 0` for actionable expiry lists.
- `facility_dashboard`: active item counts by type and stock/expiry status.
  Empty facilities return no row; the application should display zero counts.

All views use `security_invoker` so their aggregates respect the user's RLS.
Do not sum unrelated stock units (e.g. tablets plus bottles) into a meaningful
overall quantity; dashboard figures are item counts.

Defaults chosen for this initial implementation:

- Facility timezone: **Asia/Manila**, configurable at registration and in settings.
- Near expiry: today through **30 days ahead**, inclusive and configurable.
- Exact expiry date remains usable through that facility-local calendar day;
  it is expired starting the following day. Store a full date. The database does
  not guess dates from month/year-only labels.
- Low stock: positive usable quantity at or below the threshold; out of stock:
  zero usable quantity. Expired stock is excluded from both usable calculations.
- One inventory location per facility; no cross-facility transfers.

These date/unit defaults can be revisited before rollout. Scheduled notifications,
patient records, branding beyond the name, and billing are outside this baseline.

## Verification

`tests/verify.mjs` runs the complete baseline and permission/inventory checks in
an in-memory PostgreSQL instance using **PGlite**. It creates a minimal Auth test
double and never connects to Supabase. Node is needed only for this developer
test tool; the planned application backend remains Python.

Install PGlite in a temporary directory, then point the test runner at its package.
Example in PowerShell (tested with `@electric-sql/pglite` 0.5.10):

```powershell
$taskDbTestRoot = Join-Path $env:TEMP 'bhc-inventory-db-verification'
npm.cmd install --prefix $taskDbTestRoot --ignore-scripts --no-audit --no-fund @electric-sql/pglite@0.5.10
node database/tests/verify.mjs "$taskDbTestRoot/node_modules/@electric-sql/pglite"
```

The checks cover schema execution, Auth profile creation, isolation, least-privilege
grants, last-admin protection, history snapshots/immutability, idempotency,
multi-batch FEFO, expiry boundaries, adjustments/disposal, failed-operation rollback,
membership revocation, archival, and reconciliation of every balance to its ledger.
This runtime does not verify simultaneous transactions on separate server sessions,
real Supabase Auth, or PostgREST behavior. Test those on a development Supabase
project before production use.

`tests/verify_deployment.sql` additionally checks the actual deployed schema's
RLS, grants, function execution permissions/search paths, views, and history/Auth
triggers using read-only catalog assertions. It does not create test users or
inventory records in the remote database.

References: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security),
[database functions](https://supabase.com/docs/guides/database/functions).
