# Facility Inventory Management — Requirements Draft

Status: Flask/Supabase MVP deployed at https://bhc-inventory.vercel.app with encrypted shared sessions. Login/logout, live seed inventory/history, facility isolation, page navigation, and assets passed 53 hosted checks. Account recovery/change and stock workflows also passed the live integration checks. See README.md and DEPLOYMENT.md for evidence and remaining work. The confirmed access model is administrators only, with no staff accounts or team-management interface.

## 1. Confirmed requirements and source boundaries

- Python must be part of the application backend.
- The proposed technologies are HTML, CSS, JavaScript, Python, and Supabase.
- The Supabase CLI is authenticated and this repository is linked to BHC Inventory (`hmapfyndwrvsapllythc`).
- Multiple facilities register their own facility name and receive separate workspaces.
- White labeling in version 1 means the facility name only. All facilities share the application design.
- The supplied photos describe medicine and medical supply inventory, accounts, dashboard, stock movements, expiry monitoring, and search/filtering.
- Covered or unreadable lines in the photos are unspecified; no features are inferred from them.
- The recommendations below extend the photographed features where needed for reliable operation. They are proposals unless explicitly marked confirmed.

## 2. Product scope

A web application where each registered facility manages its own medicines, consumable medical supplies, administrators, and stock history. Facility names appear in the workspace header, dashboard, and settings.

Proposed version 1 boundary: one stock location per facility, internet required, and no patient records. Multiple facilities are supported from the start; branches and transfers between facilities are deferred.

## 3. Proposed technology and architecture

| Layer | Proposal | Responsibility |
| --- | --- | --- |
| Pages | HTML rendered with Jinja templates | Forms, lists, details, navigation |
| Styling | CSS | Shared responsive interface |
| Interaction | JavaScript | Search, filters, dialogs, form feedback |
| Backend | Python + Flask | Routes, validation, sessions, permissions, inventory workflows |
| Identity | Supabase Auth | Accounts, sign-in, password changes and recovery |
| Database | Supabase Postgres | Facilities, memberships, inventory, movement history |
| Database changes | Supabase CLI migrations | Reproducible schema, constraints, policies, database functions |

Request flow: browser -> Flask -> Supabase Auth / Postgres.

Flask renders pages and owns the application workflows. Ordinary data requests retain the signed-in user's authorization context so database policies can enforce facility membership. User sessions must remain isolated between requests and users.

Stock mutation workflows call a restricted Postgres function to validate and commit balances and movement records together. This small SQL layer complements the Python backend.

The application runs on Vercel, with Supabase supplying the database, authentication, and encrypted shared server sessions. GitHub pushes to `main` trigger production deployment.

## 4. Facility onboarding and access

### Facility registration

Proposed flow: create account -> verify email -> register facility name -> become facility administrator -> open empty dashboard -> add inventory.

- A facility uses an internal unique ID; its display name is not an access credential.
- Facility creation and the creator's administrator membership succeed together or roll back together.
- A newly created workspace starts with no other facility's data.
- A facility administrator can update the displayed facility name.
- Joining an existing facility requires authorization from that facility; knowing its name is insufficient.
- The initial administrator is the facility creator. Staff access is excluded from this version.

### Confirmed access model

- Facility administrators are the only supported role. Each facility remains isolated.
- Administrators manage inventory, stock movements, corrections, history, categories, and settings.
- Include login, logout, change password, password recovery, and email verification.
- Remove staff accounts and the team-management interface. The database rejects staff roles.
- Preserve original attribution for historical records created before staff access was removed.
- Facility creators become administrators atomically during registration; users cannot choose another facility during signup.
- Memberships remain separate from accounts. Multiple authorized administrator memberships and the facility switcher are supported.
- A platform-wide administration console is outside the first version.

## 5. Functional requirements

| ID | Module | Required behavior |
| --- | --- | --- |
| FR-01 | Accounts | Account onboarding, login/logout, change password; proposed password recovery and role controls |
| FR-02 | Facility workspace | Self-service facility registration, facility name display, isolated records and membership access |
| FR-03 | Dashboard | Medicine and supply item counts, usable stock status, low/out-of-stock items, expired stock; proposed near-expiry list |
| FR-04 | Medicines | Add, edit, search, view details, categorize, and remove from active inventory |
| FR-05 | Medical supplies | Add, update, categorize, search, view details, and remove from active inventory |
| FR-06 | Stock in | Receive an item into a batch with quantity, received date, lot/batch reference, expiry where applicable, source/reference, and actor |
| FR-07 | Stock out | Record item, batch allocations, quantity, issue date, purpose/destination, reference, and actor |
| FR-08 | History | Display receipts, issues, adjustments, and proposed disposal/correction entries with dates, quantities, and responsible users |
| FR-09 | Adjustments | Record physical count differences with old balance, counted balance, resulting change, actor, and mandatory reason |
| FR-10 | Expiry | Record expiry per batch, list expired batches, filter by expiry date; proposed near-expiry window |
| FR-11 | Search and filters | Search medicine/supply names and category; filter by stock status and expiry date; combine search and filters |

The photographed delete requirement is proposed as archival for items with history. Archival removes the item from active selection while retaining its transactions. An unused item with no stock or history may be permanently deleted by an administrator.

### Catalog fields

Shared fields: facility, internal item code, name, type (medicine or supply), category, base stock unit, low-stock threshold, description, and active/archived state.

Medicine fields: generic name, optional brand, strength, and dosage form. Different strengths/forms are separate items.

Supply fields: supply name, optional size/specification, and whether expiry tracking applies. Version 1 covers consumable supplies; equipment loans, maintenance, and serial-number tracking are deferred.

### Batch fields

Facility, item, lot/batch reference, expiry date when applicable, and current quantity on hand. Receive the same item into separate batches when lot or expiry differs. Opening balances are recorded through stock-in entries.

Proposed unit rule: one base unit per item with positive whole-number movement quantities. Automatic conversion between boxes, strips, tablets, bottles, and milliliters is deferred. Users enter quantities in the chosen base unit.

## 6. Inventory rules

1. Every stock change creates a movement record. Users cannot directly overwrite the item total.
2. Each batch balance equals its opening receipts plus all subsequent signed movements.
3. Balances cannot become negative. Concurrent issues must not overspend the same stock.
4. Balance changes, batch allocations, and movement records commit in one database transaction.
5. Repeated submission of the same operation must not create duplicate movements.
6. The proposed allocation rule is first-expiry-first-out: suggest usable batches with the earliest expiry first. Non-expiring batches follow dated batches.
7. Expired stock is unavailable for ordinary issue. It remains physically on hand until a disposal or other authorized removal is recorded.
8. Proposed definitions: out of stock = zero usable units; low stock = positive usable units at or below the item's threshold; in stock = above that threshold. Exclude archived items from active dashboard totals.
9. Show usable quantity and expired quantity separately. Expiry is a batch status and may coexist with an item's low/out-of-stock status.
10. Proposed near-expiry window: 30 days, configurable per facility. Alerts are calculated when pages are loaded; scheduled notifications are deferred.
11. Expiry boundary, facility timezone, and treatment of month/year-only labels must be decided before implementing expiry calculations.
12. Posted movements cannot be edited or deleted. Corrections require authorized, linked compensating entries with a reason and the same balance validation.
13. Proposed version 1 uses the current posting date for movements; backdated adjustments are deferred.
14. Archive only after remaining stock has been issued, disposed of, or otherwise reconciled. Archived records retain their history.

## 7. Facility isolation and application requirements

- Every facility-owned record carries a facility ID, including categories, items, batches, movements, memberships, and audit events.
- Database constraints prevent relationships between records from different facilities.
- Enforce permissions in Python and in database grants/Row Level Security (RLS). Check the authenticated account's current membership; do not trust a submitted facility ID alone.
- Stock functions enforce membership and role checks and do not leave alternate direct-write paths that bypass inventory rules.
- Dashboard aggregates, search, detail pages, and history must all respect the same facility boundary.
- Keep administrative Supabase credentials on the server and out of source control. Ordinary requests should not depend on credentials that bypass RLS.
- Protect cookie-authenticated writes against CSRF; validate input on the server and escape rendered content.
- Record who performed stock and administrative changes, with timestamps. Preserve historical attribution when a membership is removed.
- Provide clear validation, empty, loading, and failure states. An unsuccessful stock operation must leave balances unchanged.
- Support desktop and mobile layouts, labeled forms, and keyboard navigation.
- Keep secrets in environment variables and provide an example configuration without credentials.
- Define backup/restore operations and deployment monitoring before any daily operational rollout; target service levels depend on whether this is a demo or production tool.

## 8. Proposed data model

| Entity | Purpose |
| --- | --- |
| Supabase Auth users | Identity and credentials |
| profiles | Account display information |
| facilities | Facility name, timezone, near-expiry settings |
| facility_memberships | Administrator-to-facility access and active status |
| categories | Facility-owned medicine/supply categories |
| items | Facility-owned medicine and supply catalog |
| inventory_batches | Lot, expiry, item, and current physical balance |
| stock_transactions | Receipt/issue/adjustment/disposal headers, actor, reference, reason, idempotency key |
| stock_transaction_lines | Batch-level signed changes, linked to a transaction |
| audit_events | Facility settings, membership, and catalog change history |

Keep catalog records facility-owned in version 1 rather than maintaining a shared editable global medicine catalog.

## 9. Proposed pages

1. Login, account registration, email verification, password recovery/change.
2. Register facility.
3. Facility dashboard.
4. Medicines list, item form, and item details with batches.
5. Medical supplies list, item form, and item details with batches.
6. Receive stock.
7. Issue stock.
8. Inventory adjustment and disposal.
9. Transaction history and transaction details.
10. Expired and near-expiry stock.
11. Category management.
12. Facility settings.

## 10. Acceptance examples

- Facility A and Facility B can each create an item with the same name/code. Neither can read or change the other's records, including by guessing an ID or calling an endpoint directly.
- Registering a facility creates its workspace and initial administrator without a partial/orphaned facility on failure.
- Receive 100 usable units, issue 20: usable and physical balance become 80, with both transactions visible.
- Two concurrent requests try to issue 60 each from a batch containing 100: at most one succeeds; no negative balance occurs.
- Retrying a successful receipt with the same operation key creates no second receipt.
- One batch contains 20 usable units and another contains 15 expired units: usable stock is 20, expired stock is 15, physical stock is 35, and the expired batch cannot be issued.
- Disposing of those 15 expired units leaves physical stock at 20 and retains a disposal record.
- Counting 18 units where a batch shows 20 creates an administrator-authorized adjustment of -2 with its reason.
- Only facility administrators can access their own workspace; another facility remains inaccessible.
- Removing a membership prevents further access to that facility without deleting historical transaction attribution.
- Changing a facility name changes only that facility's displayed name.
- Search and combined category/stock/expiry filters return only records from the current facility.

## 11. Delivery sequence

1. Resolve open scope questions and agree on administrator-only access, stock units, and expiry rules.
2. Create schema migrations, facility constraints, RLS policies, and automated facility-isolation checks.
3. Implement authentication, facility onboarding, and membership authorization.
4. Implement medicine/supply catalogs, categories, and batches.
5. Implement transactional stock-in/out, adjustments, disposal, and history; verify concurrency and duplicate-submission handling.
6. Implement dashboard, expiry views, search, and filters.
7. Verify complete workflows with two sample facilities, responsive layouts, and failure states; deploy to the chosen environment.

## 12. Open decisions and deferred scope

Open decisions:

- Intended use: school/demo, daily operation, or demo followed by real use.
- Confirm base-unit restrictions, near-expiry window, facility timezone, and exact expiry-date interpretation.
- Expected number of facilities/items/users and operating budget. Vercel is the requested hosting target for the next phase.

Deferred unless requested: logos, per-facility colors, custom domains, billing/subscriptions, cross-facility stock transfers, multiple warehouses per facility, patient records, prescriptions, purchase orders, barcode scanning, offline synchronization, scheduled email/SMS alerts, advanced reports, CSV/PDF exports, bulk imports, and equipment asset tracking.

## 13. Technical references

- Supabase Python/Flask quickstart: https://supabase.com/docs/guides/getting-started/quickstarts/flask
- Flask documentation: https://flask.palletsprojects.com/en/stable/quickstart/
- Supabase Auth: https://supabase.com/docs/guides/auth
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase database functions: https://supabase.com/docs/guides/database/functions
