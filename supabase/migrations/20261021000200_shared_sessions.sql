-- Server-only encrypted session storage. Browsers cannot read the table or RPCs.
create table public.app_server_sessions (
    sid_hash text primary key check (sid_hash ~ '^[a-f0-9]{64}$'),
    payload text,
    expires_at timestamptz not null,
    lease_owner uuid,
    lease_until timestamptz
);
create index app_sessions_expiry_idx on public.app_server_sessions(expires_at);
alter table public.app_server_sessions enable row level security;
revoke all on public.app_server_sessions from public, anon, authenticated;
grant select, insert, update, delete on public.app_server_sessions to service_role;

-- A short lease serializes one browser session across independent workers.
-- Lease duration (180s) exceeds the configured Vercel function limit (60s).
create function public.lease_app_session(p_sid_hash text, p_owner uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_payload text; v_expires timestamptz;
begin
    insert into public.app_server_sessions as s(sid_hash, expires_at, lease_owner, lease_until)
    values (p_sid_hash, clock_timestamp() + interval '24 hours', p_owner, clock_timestamp() + interval '180 seconds')
    on conflict (sid_hash) do update
        set lease_owner = p_owner, lease_until = clock_timestamp() + interval '180 seconds',
            payload = case when s.expires_at > clock_timestamp() then s.payload else null end
        where s.lease_until is null or s.lease_until < clock_timestamp()
    returning payload, expires_at into v_payload, v_expires;
    if not found then return jsonb_build_object('acquired', false); end if;
    -- Bounded opportunistic cleanup never touches a live request's lease.
    delete from public.app_server_sessions where sid_hash in
        (select sid_hash from public.app_server_sessions where expires_at < clock_timestamp()
         and (lease_until is null or lease_until < clock_timestamp()) and sid_hash <> p_sid_hash limit 100);
    return jsonb_build_object('acquired', true, 'payload', v_payload);
end;
$$;

create function public.commit_app_session(p_sid_hash text, p_owner uuid, p_new_sid_hash text, p_payload text)
returns void language plpgsql security invoker set search_path = '' as $$
begin
    perform 1 from public.app_server_sessions where sid_hash = p_sid_hash and lease_owner = p_owner
        and lease_until > clock_timestamp() for update;
    if not found then raise exception 'Session lease expired' using errcode = '40001'; end if;
    if p_new_sid_hash = p_sid_hash then
        update public.app_server_sessions set payload = p_payload, expires_at = clock_timestamp() + interval '24 hours',
            lease_owner = null, lease_until = null where sid_hash = p_sid_hash;
    else
        insert into public.app_server_sessions(sid_hash, payload, expires_at)
        values (p_new_sid_hash, p_payload, clock_timestamp() + interval '24 hours');
        delete from public.app_server_sessions where sid_hash = p_sid_hash;
    end if;
end;
$$;

create function public.release_app_session(p_sid_hash text, p_owner uuid)
returns void language sql security invoker set search_path = '' as $$
    update public.app_server_sessions set lease_owner = null, lease_until = null
    where sid_hash = p_sid_hash and lease_owner = p_owner;
$$;

revoke all on function public.lease_app_session(text, uuid) from public, anon, authenticated;
revoke all on function public.commit_app_session(text, uuid, text, text) from public, anon, authenticated;
revoke all on function public.release_app_session(text, uuid) from public, anon, authenticated;
grant execute on function public.lease_app_session(text, uuid) to service_role;
grant execute on function public.commit_app_session(text, uuid, text, text) to service_role;
grant execute on function public.release_app_session(text, uuid) to service_role;

