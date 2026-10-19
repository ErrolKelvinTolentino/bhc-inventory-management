# Incremental migrations

The deployable migration history now lives in **`supabase/migrations/`** at the
repository root, the standard location discovered by the Supabase CLI.

`supabase/migrations/20261019000100_initial_inventory.sql` was applied to
**BHC Inventory** (`hmapfyndwrvsapllythc`) on 2026-10-19. It is the migration form
of `database/supabase_setup.sql`; the CLI supplies the transaction wrapper.

Create future changes with `npx.cmd --yes supabase migration new change_name` and
edit the generated file under `supabase/migrations/`. This folder is retained for
database planning notes only; SQL files placed here are not deployed automatically.
Do not replay the standalone baseline or use a remote reset command.
