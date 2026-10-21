-- Staff access is removed. Preserve profiles and immutable historical attribution.
delete from public.facility_memberships where role = 'staff';
alter table public.facility_memberships drop constraint facility_memberships_role_check;
alter table public.facility_memberships add constraint facility_memberships_role_check
    check (role = 'admin');

create or replace function public.set_facility_member(p_facility_id uuid, p_user_id uuid,
    p_role text default 'admin', p_is_active boolean default true)
returns void language plpgsql security definer set search_path = '' as $$
begin
    perform 1 from public.facilities where id = p_facility_id for update;
    perform private.require_access(p_facility_id, true);
    if p_role is distinct from 'admin' or p_is_active is null then
        raise exception 'Only facility administrators are supported' using errcode = '22023';
    end if;
    if not p_is_active and exists (select 1 from public.facility_memberships
        where facility_id = p_facility_id and user_id = p_user_id and is_active)
       and not exists (select 1 from public.facility_memberships where facility_id = p_facility_id
           and user_id <> p_user_id and is_active and role = 'admin') then
        raise exception 'The last active administrator cannot be removed' using errcode = '23514';
    end if;
    insert into public.facility_memberships(facility_id, user_id, role, is_active)
    values (p_facility_id, p_user_id, 'admin', p_is_active)
    on conflict (facility_id, user_id) do update set role = 'admin', is_active = excluded.is_active;
end;
$$;

