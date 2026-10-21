# Facility Inventory

A working local MVP built with **Python / Flask, HTML, CSS, JavaScript, and
Supabase**. Authentication, facility onboarding, catalogs, stock workflows, and
history connect to the deployed BHC Inventory database.
**Live app: [bhc-inventory.vercel.app](https://bhc-inventory.vercel.app)**.
See [DEPLOYMENT.md](DEPLOYMENT.md) for production configuration and verification.

New to the repository? Follow [GETTING_STARTED.md](GETTING_STARTED.md) for a fresh
checkout, local configuration, account setup, and troubleshooting.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000** to sign in. A verified account without a facility is
guided through facility registration. `/demo` opens an isolated, interactive
preview without an account.

For a fresh checkout, copy `.env.example` to `.env` and add the project's public
Supabase publishable/anon key to enable live sign-in. The current machine's ignored
`.env` has already been configured with the public key. Local SQLite mode needs
no administrative key; shared sessions use a server-only Supabase secret. `requirements-lock.txt` records the exact installed
versions, including developer test tools.

## What works

- Overview with actionable stock alerts, expiry reminders, a movement chart, and
  an inventory snapshot. Charts count movements, not a sum of unrelated stock units.
- Medicine and medical supply lists with search, stock status filtering, category
  navigation, pagination, and an archived-items filter.
- Item creation/editing and a detail drawer for quantities, batches, and recent
  movements. Archive/restore preserves history.
- Receive and issue forms, automatic earliest-expiry allocation, counted stock
  adjustments, expired stock disposal, and linked counted corrections.
- Searchable/filterable stock history with original actor/item snapshots and
  per-batch before/after balances. Administrative activity is a separate view.
- Expiry watch with near-expiry/expired filters.
- Category creation and facility name/timezone/expiry-window settings.
- Global inventory search, keyboard shortcuts, native modal focus handling,
  responsive navigation, and compact phone inventory/history lists.
- Sign-in/logout, registration, email verification and resend, password recovery,
  signed-in password changes with current-password verification, and facility
  onboarding through Supabase Auth and the deployed database functions.

## Sample facility and accounts

The connected project has a separate **Sample Health Center (Seed)** with
19 items, 10 categories, and 31 initial stock transactions. The sample
administrator uses `admin@seed.bhc-inventory.test`. Its generated
password is in the ignored `instance/seed-credentials.json`. It is a confirmed
test account and cannot receive email. The former sample staff login has been
removed; historical stock entries remain attributed to their original actors.

```powershell
.venv\Scripts\python.exe scripts/seed_supabase.py --use-cli
```

This uses the logged-in Supabase CLI to obtain an administrative key in memory
for test-account creation only. All inventory writes use the sample
administrator's normal JWT and database RPCs. Inventory requests use the public
key and user JWTs; shared session storage uses a server-only secret. The script
reuses accounts, category/item codes, and deterministic
stock-operation keys; rerunning it does not duplicate the initial inventory.
Keep the ignored credential file to retain the generated passwords and seed date.
Existing sample edits are preserved; this command is not a reset.

The live verification script also creates an empty **Integration Check Facility
(Seed)** and an `onboarding@seed.bhc-inventory.test` account to test onboarding,
facility isolation, and password changes. Its generated credentials are stored in
the same ignored file. The sample movement history contains four clearly marked
`LIVE-CHECK` entries with zero combined effect on stock.

## Demo versus live inventory

The demo is a **separate, session-scoped sample**. Its changes are persisted in
the configured session backend (ignored SQLite locally, encrypted Supabase
sessions on Vercel) and expire after 24 hours of inactivity. Another browser session gets its own preview. Using `/demo` never
creates facilities, accounts, or inventory in Supabase. The live seed script is a
separate, explicit operation.

Use **Open your facility** or `/login` to sign in to a real account. A verified
account without a facility is guided through facility registration. Users with
several memberships can select a facility from the sidebar. Live data is loaded
through each user's own JWT, and all stock changes use the authorized database
RPCs. A failed live request never silently falls back to demo data.

The application supports facility administrators only. Team/staff-management
screens and actions have been removed, and the database rejects staff roles.

Email links are bound to the requesting browser and expire after one hour. Open
the verification/reset link in that browser. Tokens return in the URL fragment,
which the callback page clears before submitting them over the local same-origin
API. Tokens are verified by Supabase and kept in the server-side session.

Local callback URLs for `localhost` and `127.0.0.1`, ports 5000 and 5001, are already
allowed in this Supabase project. Other Auth settings were preserved. To prepare a
future HTTPS origin, inspect the dry run first, then apply it:

```powershell
.venv\Scripts\python.exe scripts/configure_auth.py --origin https://your-app.example
.venv\Scripts\python.exe scripts/configure_auth.py --origin https://your-app.example --apply
```

Set `APP_URL` to that canonical origin in deployment. Registration, verification
resend, and recovery send email only when requested through their forms. Live
verification generated a test recovery link without sending email; inbox delivery
with a real address still needs checking before public onboarding.

## Design direction

The interface takes its restraint from [Apple's Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/):
clear hierarchy, familiar controls, generous space, and content before decoration.
It uses system typography, a warm neutral palette, one muted green accent, thin
dividers, and locally authored SVG icons. There are no external font, icon, or
image services. The sign-in illustration is built in CSS.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=instance/pytest-run
node --check inventory/static/app.js
node --check inventory/static/auth.js
node --check inventory/static/callback.js
node --check inventory/static/password.js
```

The 36 offline Python tests cover isolated sessions, CSRF/origin validation,
stock changes and retry behavior, rollback, expired-stock protection, disposal,
archival, activity history, administrator-only access, session rotation/invalidation,
browser-bound email callbacks, expired authentication, password validation, and
closed SQLite handles. On Windows, use a fresh `--basetemp` path if a previous
test directory has restrictive permissions.

Run the live checks after seeding (requires the connected test project):

```powershell
.venv\Scripts\python.exe scripts/verify_live.py --use-cli
```

The latest shared-session run passed 67 live checks. They exercise actual Supabase authentication, inventory reads,
receipts/issues and duplicate retries, rollback, catalog edits/archival,
facility isolation, recovery redirects and token callbacks, both password-change
paths, and logout with cookie-replay rejection. Add `--shared-sessions` to verify
cross-instance sessions, concurrent session updates, encrypted stored payloads,
and session RPC isolation. First-time onboarding was verified on the initial run.
Checks leave stock quantities unchanged and preserve annotated audit/history
entries. Only the generated QA account's password changes, and its local
credential record is updated automatically.

The draft's browser checks covered desktop and phone layouts, stock forms,
history filtering, item drawers, and navigation. Live browser verification also
confirmed administrator sign-in, live inventory/history, account controls, and
sign-out returning to the login page.

Database migration and deployment checks are described in `database/README.md`.

## Structure

```text
app.py                    Flask entry point
inventory/__init__.py     Routes, validation, CSRF, server-side session storage
inventory/auth.py         Account flows, email callbacks, session rotation
inventory/shared_sessions.py  Encrypted, leased serverless session storage
inventory/services.py     Per-request Supabase clients and live data queries
inventory/demo.py         Isolated sample stock and its consistent movement ledger
inventory/templates/     Workspace and sign-in/onboarding layouts
inventory/static/        Interface styling, interactions, icons
tests/                    Python application integration tests
scripts/                  Repeatable seeding, Auth URL configuration, live checks
database/                 Standalone database baseline, notes, verification
supabase/migrations/      Applied database migration history
```

## Deployment status

[Vercel preparation and required environment variables](DEPLOYMENT.md) are
included. Shared sessions are available through `SESSION_BACKEND=supabase`; local
development defaults to SQLite. Vercel enforces shared sessions, explicit secrets,
secure cookies, and a canonical HTTPS origin. No session tokens reach browser
cookies or localStorage. Auth and inventory reads keep the user's RLS context.

The shared-session and administrator-only migrations are applied. Vercel project
`inaagapay/bhc-inventory` is connected to this GitHub repository's `main` branch;
future pushes deploy automatically. Production secrets and the Supabase Auth
Site URL/callbacks are configured. The hosted app passed 53 read-only checks for
login/logout, secure sessions, live seed data/history, facility isolation, and
assets. Run `.venv\Scripts\python.exe scripts/verify_deployed.py` to repeat them.
Real inbox delivery remains to be checked with a real email address.

The stock history currently loads the latest 200 transactions and latest 100
activity events; older records remain in the database. Complete server-side
history pagination/search before using this as a long-term clinic log.
