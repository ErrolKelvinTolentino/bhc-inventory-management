# Set up a fresh GitHub checkout

For someone who already cloned this repository and wants to run or develop the
app locally. The live website is [bhc-inventory.vercel.app](https://bhc-inventory.vercel.app)
if you only want to use the app without installing anything.

## 1. Install Python and open the project

Install **Python 3.12** from [python.org](https://www.python.org/downloads/).
Open PowerShell or the VS Code terminal inside `bhc-inventory-management`.
The commands below are for Windows PowerShell; no virtual environment activation
or PowerShell execution-policy change is needed.

```powershell
git pull
py -3.12 --version
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If `py` is unavailable but `python --version` reports Python 3.12, use
`python -m venv .venv` for the environment-creation command. Each developer creates
their own `.venv`; it is not downloaded from GitHub.

On macOS/Linux, the equivalent commands are:

```bash
git pull
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env with your text editor before starting the app.
.venv/bin/python app.py
```

## 2. Create your local configuration

```powershell
Copy-Item .env.example .env
notepad .env
```

Copy the example only if you do not already have a `.env`, to avoid overwriting
your existing configuration. For the shared project, the important settings are:

```dotenv
SUPABASE_URL=https://hmapfyndwrvsapllythc.supabase.co
SUPABASE_PUBLISHABLE_KEY=PASTE_THE_PROJECT_PUBLIC_KEY_HERE
SUPABASE_SECRET_KEY=
SESSION_BACKEND=sqlite
SECRET_KEY=
APP_TIMEZONE=Asia/Manila
PORT=5000
APP_URL=
COOKIE_SECURE=0
```

Ask the project owner for **only the Supabase publishable/anon key**, or obtain
it from the project's API settings if you already have access. The project URL
is included above. The public key connects the app to Supabase; access to
inventory still requires signing in and belonging to the correct facility.

Leave `SUPABASE_SECRET_KEY`, `SECRET_KEY`, and `APP_URL` empty for normal local
development. The app creates its own local signing secret and stores browser
sessions in ignored `instance/sessions.sqlite3`. SQLite stores sessions only;
the actual live inventory remains in Supabase. Do not copy production/Vercel
environment settings into your local setup.

`.env`, `.venv`, and `instance/` are intentionally excluded from GitHub. You do
not need the owner's `.env`, service-role key, Vercel credentials, or Supabase CLI
login. Node.js is optional for JavaScript syntax checks and deployment tooling;
it is not required to start Flask.

## 3. Start the app

```powershell
.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000** in your browser. Leave the terminal running.
Press **Ctrl+C** in that terminal when you want to stop the server. Restart it
after Python or template changes; the development entry point disables hot reload.

For an immediate preview, open **http://127.0.0.1:5000/demo**. The demo works even
without a Supabase public key. Demo edits are isolated from live inventory and
from other browser sessions.

## 4. Use live inventory

Create your own account, verify your email, then register your facility name.
The account becomes that facility's administrator, and its inventory starts
empty. The application has no staff role or team-management screen.

Open verification/reset links in the **same browser and on the same computer**
where you requested them. During a local session, keep using the same address
(`127.0.0.1:5000` rather than switching between it and `localhost`). The callback
must return to that browser's local server. Local callback URLs for both hosts
on ports 5000 and 5001 are already allowed for the shared project.

Real inbox delivery still needs to be verified with your address. If signup or
email delivery fails, give the project owner the error text so they can check
Supabase Auth/email settings. You can continue using `/demo` meanwhile.

The existing 19-item sample inventory belongs to **Sample Health Center (Seed)**.
It appears only when signing in with its authorized sample administrator account;
new accounts do not automatically join it. The owner's generated sample password
is in their ignored `instance/seed-credentials.json`, so it will not be in your
clone. Ask the owner for access if you need to test that exact sample facility.

Live edits from your local app use the **same Supabase database as the deployed
website**. Use your own test facility for development. The shared database is
already migrated and seeded: do not replay `supabase_setup.sql`, reset it, or run
the seed scripts as part of ordinary setup. A separate Supabase project requires
its own migrations, keys, and callback configuration; see `database/README.md`.

## Common setup problems

| Problem | Fix |
| --- | --- |
| `py` or `python` is not found | Install Python 3.12, reopen the terminal, and check the version. |
| `ModuleNotFoundError` | Run the install command with `.venv\Scripts\python.exe`, then start with that same executable. |
| Live sign-in is not configured | Fill `SUPABASE_PUBLISHABLE_KEY` in `.env` and restart Flask. |
| Port 5000 is already in use | Set `PORT=5001` in `.env`, restart, and open `http://127.0.0.1:5001`. |
| Verification link belongs to another browser | Request a new link from the local app and open it in that same browser. |
| Browser page/form has expired | Reload the page before submitting again. |
| Database is empty after registering | A new facility starts empty; this is expected. |

## Optional development checks

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=instance/pytest-fresh-setup
```

Use a new `--basetemp` path if an earlier Windows test folder has permission
issues. These offline tests do not need a live Supabase account. Do not run the
live/deployed verification scripts as a normal onboarding step: those scripts
use the owner's ignored test credentials.

When ready to contribute, create a branch and open a pull request. Pushes to
`main` automatically deploy to the live Vercel app.

References: [Python virtual environments](https://docs.python.org/3.12/tutorial/venv.html)
and [Supabase public versus secret keys](https://supabase.com/docs/guides/api-keys).
