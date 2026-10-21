# Vercel production deployment

The app is deployed at **[bhc-inventory.vercel.app](https://bhc-inventory.vercel.app)**
as of 2026-10-21. Project: `inaagapay/bhc-inventory`, connected to
`ErrolKelvinTolentino/bhc-inventory-management`, production branch `main`.
Pushing to `main` triggers production deployment automatically.

The hosted app passed **53 production checks**, including sign-in/logout,
encrypted shared sessions, live seed inventory/history, facility isolation,
all workspace pages, and CDN assets. The checks do not modify inventory or send
email. Browser sign-in and the live dashboard were also verified.

The `app` in root `app.py` is the entry point; Python 3.12 is specified in
`.python-version`. `vercel.json` selects Flask and a 60-second request limit.
The build command copies CSS, JavaScript, and icons into `public/static` for
Vercel's CDN. Local Flask development continues serving `inventory/static`.

See the official [Flask deployment guide](https://vercel.com/docs/frameworks/backend/flask)
and [Python runtime guide](https://vercel.com/docs/functions/runtimes/python).

## Environment variables

Use the repository root as Vercel's Root Directory, select the Flask preset,
leave Install Command and Output Directory at their defaults, and use the build
command committed in `vercel.json`. No database migration or seeding runs during
build or application startup.

The following are configured in Vercel's **Production** environment:

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | `https://hmapfyndwrvsapllythc.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Project publishable/anon key from the local `.env` or Supabase dashboard |
| `SUPABASE_SECRET_KEY` | Project secret key or legacy service-role key; mark Sensitive and keep server-only |
| `SECRET_KEY` | A new cryptographically random value of at least 32 characters; mark Sensitive |
| `SESSION_BACKEND` | `supabase` |
| `APP_URL` | `https://bhc-inventory.vercel.app` |
| `COOKIE_SECURE` | `1` (also enforced automatically on Vercel) |
| `APP_TIMEZONE` | `Asia/Manila` |

Generate a signing secret locally with Python's `secrets.token_hex(32)`. Use the
same `SECRET_KEY` for every instance of this deployment. It signs opaque cookies
and derives a separate session-encryption key. Replacing it signs everyone out;
never commit it. Keep production secrets out of Preview/Development environments
unless those environments are deliberately configured to use the same database.

The privileged Supabase key is used **only** by the server session module. All
facility/inventory queries still run with the signed-in administrator's JWT and
RLS. Supabase [secret keys](https://supabase.com/docs/guides/api-keys) bypass RLS,
so do not prefix this variable with `PUBLIC_` or expose it in HTML/JavaScript.

The app fails startup on Vercel if configured with SQLite, missing secrets, or a
non-HTTPS `APP_URL`. There are no runtime writes to the deployment filesystem.
`.vercelignore` and function exclusions keep `.env`, local credentials, SQLite
sessions, developer dependencies, and QA artifacts out of uploaded source/bundles.

## Supabase is prepared

These migrations are applied to the connected project:

- `20261019000100_initial_inventory.sql`: inventory schema and RLS.
- `20261021000100_administrators_only.sql`: only administrator memberships allowed.
- `20261021000200_shared_sessions.sql`: encrypted server session storage.

The former sample staff login is soft-deleted and has no facility membership.
Its historical stock/audit attribution is preserved. Seed commands create only
the sample administrator; the separate QA account is also an administrator.

`app_server_sessions` has RLS and no browser-accessible grants/policies. Only the
server role can call its lease/commit/release RPCs. Session payloads are encrypted
in Python before storage, IDs are hashed, and leases serialize requests across
independent app instances. Rotation saves the new session and invalidates the old
ID atomically. Sessions expire after 24 hours of inactivity; bounded cleanup runs
when leases are acquired. Abandoned request leases expire after 180 seconds,
longer than the Vercel request limit. A busy/unavailable store returns 503 and
never falls back to another session backend.

## Configure the actual domain when known

Supabase Auth's Site URL is `https://bhc-inventory.vercel.app`, and its
`/auth/callback/**` URL is allowed alongside the existing local callbacks. Email
verification settings and other unrelated Auth configuration were preserved.

For a future domain change, replace the origin below and update Vercel's `APP_URL`:

```powershell
.venv\Scripts\python.exe scripts/configure_auth.py --origin https://your-project.vercel.app --set-site-url
.venv\Scripts\python.exe scripts/configure_auth.py --origin https://your-project.vercel.app --set-site-url --apply
```

The flag sets Supabase Auth's Site URL to the same origin. The script preserves
existing callback URLs and unrelated Auth settings.
Use the canonical domain for login and email links; browser-bound callbacks must
return to the browser and origin that requested them. Do not use wildcard Vercel
preview domains with production authentication.

## Verify before and after deployment

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=instance/pytest-deployment
.venv\Scripts\python.exe scripts/build_vercel.py
.venv\Scripts\python.exe scripts/verify_live.py --use-cli --shared-sessions
.venv\Scripts\python.exe scripts/verify_deployed.py
npx.cmd --yes supabase db query --linked --file database/tests/verify_serverless.sql
```

The live script exercises actual shared sessions, cross-instance login,
concurrent session writes, encrypted payloads, restricted session RPCs,
administrator inventory workflows, facility isolation, password flows, and
logout. It uses labeled sample accounts, leaves inventory quantities unchanged,
and updates only the generated QA password in ignored local credentials.

Production `/health`, sign-in, page navigation, sessions, inventory/history, and
sign-out have passed. Real inbox delivery for registration/recovery still needs
checking with a real email address; no unsolicited emails were sent during setup.

For subsequent releases, push code changes to `main`, wait for the deployment to
be Ready in Vercel, and run `scripts/verify_deployed.py`. `scripts/configure_vercel.py`
can add missing variables to this linked project; it preserves existing values
and never prints secrets. The Vercel CLI link in `.vercel/` remains local and
ignored by Git.
