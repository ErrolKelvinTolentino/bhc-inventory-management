-- Read-only assertions after the two 2026-10-21 migrations.
do $$
declare v_name text;
begin
    if exists (select 1 from public.facility_memberships where role <> 'admin') then
        raise exception 'Non-administrator memberships remain';
    end if;
    if not exists (select 1 from pg_catalog.pg_constraint
        where conrelid = 'public.facility_memberships'::regclass and conname = 'facility_memberships_role_check'
        and pg_get_constraintdef(oid) like '%admin%' and pg_get_constraintdef(oid) not like '%staff%') then
        raise exception 'Administrator-only role constraint is missing';
    end if;
    if not (select relrowsecurity from pg_catalog.pg_class where oid = 'public.app_server_sessions'::regclass) then
        raise exception 'Server session RLS is missing';
    end if;
    if has_table_privilege('anon', 'public.app_server_sessions', 'SELECT,INSERT,UPDATE,DELETE')
        or has_table_privilege('authenticated', 'public.app_server_sessions', 'SELECT,INSERT,UPDATE,DELETE') then
        raise exception 'Session table is exposed to browser roles';
    end if;
    foreach v_name in array array['lease_app_session(text,uuid)',
        'commit_app_session(text,uuid,text,text)', 'release_app_session(text,uuid)'] loop
        if has_function_privilege('anon', 'public.' || v_name, 'EXECUTE')
            or has_function_privilege('authenticated', 'public.' || v_name, 'EXECUTE')
            or not has_function_privilege('service_role', 'public.' || v_name, 'EXECUTE') then
            raise exception 'Invalid session function privileges: %', v_name;
        end if;
    end loop;
end;
$$;
select 'passed' as administrator_and_serverless_checks;
