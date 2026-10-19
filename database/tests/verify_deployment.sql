-- Read-only deployment assertions. Run as postgres, not as an application user:
-- npx supabase db query --linked --file database/tests/verify_deployment.sql
do $$
declare
    v_tables text[] := array['profiles', 'facilities', 'facility_memberships',
        'categories', 'items', 'inventory_batches', 'stock_transactions',
        'stock_transaction_lines', 'audit_events'];
    v_functions text[] := array['register_facility', 'update_facility',
        'set_facility_member', 'save_category', 'save_item', 'set_item_archived',
        'delete_unused_item', 'post_stock_transaction'];
begin
    if (select count(*) from pg_catalog.pg_class c
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname = any(v_tables)
          and c.relkind = 'r' and c.relrowsecurity) <> 9 then
        raise exception 'Expected nine inventory tables with RLS enabled';
    end if;
    if exists (select 1 from unnest(v_tables) t(name)
        where has_table_privilege('anon', format('public.%I', t.name),
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')) then
        raise exception 'An inventory table grants access to anonymous clients';
    end if;
    if exists (select 1 from unnest(v_tables) t(name)
        where has_table_privilege('authenticated', format('public.%I', t.name),
            'INSERT,UPDATE,DELETE,TRUNCATE')) then
        raise exception 'An inventory table grants direct writes to authenticated clients';
    end if;
    if not has_column_privilege('authenticated', 'public.profiles', 'display_name', 'UPDATE')
        or has_column_privilege('authenticated', 'public.profiles', 'id', 'UPDATE') then
        raise exception 'Unexpected profile update privileges';
    end if;
    if (select count(*) from pg_catalog.pg_proc p
        join pg_catalog.pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = any(v_functions)
          and p.prosecdef and p.proconfig @> array['search_path=""']
          and has_function_privilege('authenticated', p.oid, 'EXECUTE')
          and not has_function_privilege('anon', p.oid, 'EXECUTE')) <> 8 then
        raise exception 'Expected eight authenticated-only RPCs with secured search paths';
    end if;
    if (select count(*) from pg_catalog.pg_class c
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname in
            ('batch_stock_status', 'inventory_summary', 'facility_dashboard')
          and c.relkind = 'v' and c.reloptions @> array['security_invoker=true']) <> 3 then
        raise exception 'Expected three invoker-secured inventory views';
    end if;
    if (select count(*) from pg_catalog.pg_trigger t
        join pg_catalog.pg_class c on c.oid = t.tgrelid
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname in
            ('stock_transactions', 'stock_transaction_lines', 'audit_events')
          and t.tgname = 'reject_history_mutation' and t.tgenabled = 'O') <> 3 then
        raise exception 'Expected three append-only history triggers';
    end if;
    if not exists (select 1 from pg_catalog.pg_trigger t
        join pg_catalog.pg_class c on c.oid = t.tgrelid
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'auth' and c.relname = 'users'
          and t.tgname = 'inventory_auth_profile' and t.tgenabled = 'O') then
        raise exception 'Auth profile creation trigger is missing';
    end if;
end;
$$;

select 'passed' as deployment_checks,
    (select count(*) from pg_catalog.pg_tables where schemaname = 'public'
        and tablename in ('profiles', 'facilities', 'facility_memberships',
            'categories', 'items', 'inventory_batches', 'stock_transactions',
            'stock_transaction_lines', 'audit_events')) as inventory_tables,
    (select count(*) from pg_catalog.pg_policies where schemaname = 'public'
        and tablename in ('profiles', 'facilities', 'facility_memberships',
            'categories', 'items', 'inventory_batches', 'stock_transactions',
            'stock_transaction_lines', 'audit_events')) as inventory_rls_policies;
