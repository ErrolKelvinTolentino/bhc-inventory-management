# Facility Inventory

A working local MVP draft built with **Python / Flask, HTML, CSS, JavaScript, and
Supabase**. The initial database is already deployed to BHC Inventory. This change
adds the application and interface; it does not publish a hosted website.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000**. The initial screen is a clearly labeled, interactive
demo workspace. There is no need to create an account to review the draft.

For a fresh checkout, copy `.env.example` to `.env` and add the project's public
Supabase publishable/anon key to enable live sign-in. The current machine's ignored
`.env` has already been configured with the public key. No administrative key is
used by the application. `requirements-lock.txt` records the exact installed
versions, including developer test tools.

## What is in the draft

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
- Category creation, team access management for existing accounts, and facility
  name/timezone/expiry-window settings.
- Global inventory search, keyboard shortcuts, native modal focus handling,
  responsive navigation, and compact phone inventory/history lists.
- Sign-in, account registration, email-verification messaging, and facility
  onboarding through Supabase Auth and the deployed database functions.

## Demo versus live inventory

The demo is a **separate, session-scoped sample**. Its changes are persisted in
the local, ignored `instance/sessions.sqlite3` file and expire after 24 hours of
inactivity. Another browser session gets its own preview. No sample facilities,
accounts, or inventory are created in Supabase.

Use **Open your facility** or `/login` to sign in to a real account. A verified
account without a facility is guided through facility registration. Users with
several memberships can select a facility from the sidebar. Live data is loaded
through each user's own JWT, and all stock changes use the authorized database
RPCs. A failed live request never silently falls back to demo data.

Team management currently adds an **existing account by its account ID**. The
person can find their ID in the account menu. Email invitations remain a separate
onboarding decision. In the preview, team members are sample records and cannot
be invited or have their permissions changed.

Configure Supabase Auth's Site URL and allowed redirect URLs for the intended
application origin before real onboarding. This task did not change remote Auth
settings or send verification emails. Real account registration is available for
the user to exercise; it was not tested by creating unsolicited accounts.

## Design direction

The interface takes its restraint from [Apple's Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/):
clear hierarchy, familiar controls, generous space, and content before decoration.
It uses system typography, a warm neutral palette, one muted green accent, thin
dividers, and locally authored SVG icons. There are no external font, icon, or
image services. The sign-in illustration is built in CSS.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check inventory/static/app.js
node --check inventory/static/auth.js
```

The Python integration tests cover isolated sessions, CSRF/origin validation,
stock changes and retry behavior, rollback, expired-stock protection, disposal,
archival, activity history, staff permissions, and no silent live/demo fallback.

Browser checks cover desktop and phone breakpoints, receiving and issuing sample
stock, history filtering, item drawers, navigation, and account screens. The live
Supabase Auth endpoint was checked for connectivity without creating users or
inventory. Full live account-to-facility integration and concurrent production
sessions still require environment-level testing.

Database migration and deployment checks are described in `database/README.md`.

## Structure

```text
app.py                    Flask entry point
inventory/__init__.py     Routes, validation, CSRF, server-side session storage
inventory/services.py     Per-request Supabase clients and live data queries
inventory/demo.py         Isolated sample stock and its consistent movement ledger
inventory/templates/     Workspace and sign-in/onboarding layouts
inventory/static/        Interface styling, interactions, icons
tests/                    Python application integration tests
database/                 Standalone database baseline, notes, verification
supabase/migrations/      Applied database migration history
```

## Before operational deployment

This draft uses Flask's local development server and a small SQLite-backed session
store designed for a single local application process. Supabase tokens stay on
the server; browser cookies contain only a signed opaque session ID. CSRF checks,
same-site/HTTP-only cookies, a restrictive content security policy, and RLS are
already in place.

For deployment, use a production Python runtime, HTTPS with `COOKIE_SECURE=1`, a
managed persistent session store, and an explicit `SECRET_KEY`. Finish password
recovery/change screens, confirm staff invitation behavior, and validate the full
live Auth/RLS workflow. The stock history draft loads the latest 200 transactions
and latest 100 activity events; older records remain in the database. Complete
server-side history pagination/search before using this as a long-term clinic log.
