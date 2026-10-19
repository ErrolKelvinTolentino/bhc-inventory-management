-- Facility Inventory Management: initial schema for a NEW Supabase project.
-- PostgreSQL 15+. Run once as postgres in the Supabase SQL Editor or with psql.
-- This is a transactional baseline, NOT a rerunnable reset script. See README.md.
-- Auth credentials remain in auth.users; never create a public password table.
begin;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

-- ---------------------------------------------------------------------------
-- Tables. Composite foreign keys enforce the facility boundary independently
-- of API validation and RLS. All quantities are whole base units.
-- ---------------------------------------------------------------------------
create table public.profiles (
    id uuid primary key references auth.users(id) on delete restrict,
    display_name text not null check (length(btrim(display_name)) between 1 and 120),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.facilities (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(btrim(name)) between 1 and 200),
    timezone text not null default 'Asia/Manila',
    near_expiry_days integer not null default 30 check (near_expiry_days between 1 and 365),
    created_by uuid not null references public.profiles(id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index facilities_creator_idx on public.facilities(created_by);

create table public.facility_memberships (
    facility_id uuid not null references public.facilities(id) on delete restrict,
    user_id uuid not null references public.profiles(id) on delete restrict,
    role text not null check (role in ('admin', 'staff')),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (facility_id, user_id)
);
create index memberships_user_idx on public.facility_memberships(user_id, facility_id);

create table public.categories (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null references public.facilities(id) on delete restrict,
    name text not null check (length(btrim(name)) between 1 and 120),
    item_type text not null check (item_type in ('medicine', 'supply')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (facility_id, id, item_type)
);
create unique index categories_name_key on public.categories(facility_id, item_type, lower(btrim(name)));

create table public.items (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null references public.facilities(id) on delete restrict,
    code text not null check (length(btrim(code)) between 1 and 64),
    name text not null check (length(btrim(name)) between 1 and 200),
    item_type text not null check (item_type in ('medicine', 'supply')),
    category_id uuid,
    unit text not null check (length(btrim(unit)) between 1 and 40),
    generic_name text,
    brand text,
    strength text,
    dosage_form text,
    specification text,
    description text,
    expiry_required boolean not null default true,
    low_stock_threshold bigint not null default 10 check (low_stock_threshold >= 0),
    is_archived boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (facility_id, id),
    foreign key (facility_id, category_id, item_type)
        references public.categories(facility_id, id, item_type) on delete restrict,
    check (item_type <> 'medicine' or expiry_required)
);
create unique index items_code_key on public.items(facility_id, lower(btrim(code)));
create index items_name_idx on public.items(facility_id, lower(name));
create index items_category_idx on public.items(facility_id, category_id, item_type);

create table public.inventory_batches (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null,
    item_id uuid not null,
    batch_number text not null check (length(btrim(batch_number)) between 1 and 120),
    expiry_date date,
    quantity_on_hand bigint not null default 0 check (quantity_on_hand >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (facility_id, id, item_id),
    constraint inventory_batches_lot_key unique nulls not distinct
        (facility_id, item_id, batch_number, expiry_date),
    foreign key (facility_id, item_id) references public.items(facility_id, id) on delete restrict
);
create index batches_fefo_idx on public.inventory_batches(facility_id, item_id, expiry_date, created_at, id)
    where quantity_on_hand > 0;

create table public.stock_transactions (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null,
    item_id uuid not null,
    transaction_type text not null check (transaction_type in ('receipt', 'issue', 'adjustment', 'disposal')),
    quantity_change bigint not null check (quantity_change <> 0),
    reason text,
    reference_number text,
    source_destination text,
    corrects_transaction_id uuid,
    actor_id uuid not null references public.profiles(id) on delete restrict,
    actor_name text not null,
    item_name text not null,
    item_code text not null,
    unit text not null,
    occurred_at timestamptz not null default clock_timestamp(),
    idempotency_key uuid not null,
    request_payload jsonb not null,
    unique (facility_id, id, item_id),
    unique (facility_id, idempotency_key),
    foreign key (facility_id, item_id) references public.items(facility_id, id) on delete restrict,
    foreign key (facility_id, corrects_transaction_id, item_id)
        references public.stock_transactions(facility_id, id, item_id) on delete restrict,
    check (corrects_transaction_id is null or corrects_transaction_id <> id),
    check (transaction_type not in ('adjustment', 'disposal') or nullif(btrim(reason), '') is not null),
    check (corrects_transaction_id is null or nullif(btrim(reason), '') is not null),
    check ((transaction_type = 'receipt' and quantity_change > 0)
        or (transaction_type in ('issue', 'disposal') and quantity_change < 0)
        or transaction_type = 'adjustment')
);
create index transactions_history_idx on public.stock_transactions(facility_id, occurred_at desc, id);
create index transactions_item_idx on public.stock_transactions(facility_id, item_id, occurred_at desc);
create index transactions_actor_idx on public.stock_transactions(actor_id);
create index transactions_correction_idx on public.stock_transactions(facility_id, corrects_transaction_id, item_id);

create table public.stock_transaction_lines (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null,
    transaction_id uuid not null,
    item_id uuid not null,
    batch_id uuid not null,
    batch_number text not null,
    expiry_date date,
    quantity_change bigint not null check (quantity_change <> 0),
    balance_before bigint not null check (balance_before >= 0),
    balance_after bigint not null check (balance_after >= 0),
    created_at timestamptz not null default now(),
    foreign key (facility_id, transaction_id, item_id)
        references public.stock_transactions(facility_id, id, item_id) on delete restrict,
    foreign key (facility_id, batch_id, item_id)
        references public.inventory_batches(facility_id, id, item_id) on delete restrict,
    unique (transaction_id, batch_id),
    check (balance_after = balance_before + quantity_change)
);
create index lines_batch_idx on public.stock_transaction_lines(facility_id, batch_id, item_id);

create table public.audit_events (
    id uuid primary key default gen_random_uuid(),
    facility_id uuid not null references public.facilities(id) on delete restrict,
    actor_id uuid references public.profiles(id) on delete restrict,
    actor_name text not null,
    action text not null check (action in ('INSERT', 'UPDATE', 'DELETE')),
    table_name text not null,
    record_id text not null,
    old_data jsonb,
    new_data jsonb,
    occurred_at timestamptz not null default clock_timestamp()
);
create index audit_history_idx on public.audit_events(facility_id, occurred_at desc, id);
create index audit_actor_idx on public.audit_events(actor_id);

-- ---------------------------------------------------------------------------
-- Internal helpers. Never expose the private schema through the Data API.
-- Definer helpers avoid recursive membership RLS and pin an empty search_path.
-- ---------------------------------------------------------------------------
create function private.is_member(p_facility_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (select 1 from public.facility_memberships m
        where m.facility_id = p_facility_id and m.user_id = auth.uid() and m.is_active);
$$;

create function private.is_admin(p_facility_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (select 1 from public.facility_memberships m
        where m.facility_id = p_facility_id and m.user_id = auth.uid()
          and m.is_active and m.role = 'admin');
$$;

create function private.shares_facility(p_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (select 1 from public.facility_memberships mine
        join public.facility_memberships theirs on theirs.facility_id = mine.facility_id
        where mine.user_id = auth.uid() and mine.is_active
          and theirs.user_id = p_user_id and theirs.is_active);
$$;

-- A share lock makes permission changes wait for in-flight writes. Membership
-- changes take an exclusive facility lock before checking the last admin.
create function private.require_access(p_facility_id uuid, p_admin boolean default false)
returns void language plpgsql security definer set search_path = '' as $$
begin
    if auth.uid() is null then
        raise exception 'Authentication required' using errcode = '42501';
    end if;
    perform 1 from public.facilities where id = p_facility_id for share;
    if not private.is_member(p_facility_id)
       or (p_admin and not private.is_admin(p_facility_id)) then
        raise exception 'Facility access denied' using errcode = '42501';
    end if;
end;
$$;

create function private.touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create function private.validate_timezone()
returns trigger language plpgsql set search_path = '' as $$
begin
    if not exists (select 1 from pg_catalog.pg_timezone_names where name = new.timezone) then
        raise exception 'Unknown facility timezone' using errcode = '22023';
    end if;
    return new;
end;
$$;

create function private.capture_audit()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
    v_old jsonb;
    v_new jsonb;
    v_row jsonb;
begin
    if tg_op <> 'INSERT' then v_old := to_jsonb(old); end if;
    if tg_op <> 'DELETE' then v_new := to_jsonb(new); end if;
    if tg_op = 'UPDATE' and (v_old - 'updated_at') = (v_new - 'updated_at') then
        return null;
    end if;
    v_row := coalesce(v_new, v_old);
    insert into public.audit_events(facility_id, actor_id, actor_name, action,
        table_name, record_id, old_data, new_data)
    values (
        case when tg_table_name = 'facilities' then (v_row->>'id')::uuid
             else (v_row->>'facility_id')::uuid end,
        auth.uid(),
        coalesce((select display_name from public.profiles where id = auth.uid()), 'System'),
        tg_op, tg_table_name, coalesce(v_row->>'id', v_row->>'user_id'), v_old, v_new
    );
    return null;
end;
$$;

create function private.reject_history_mutation()
returns trigger language plpgsql set search_path = '' as $$
begin
    raise exception 'History is append-only; post a linked correction instead' using errcode = '55000';
end;
$$;

create function private.create_auth_profile()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
    insert into public.profiles(id, display_name)
    values (new.id, left(coalesce(nullif(btrim(new.raw_user_meta_data->>'display_name'), ''),
        nullif(btrim(new.raw_user_meta_data->>'name'), ''), 'Staff member'), 120));
    return new;
end;
$$;
create trigger inventory_auth_profile after insert on auth.users
    for each row execute function private.create_auth_profile();
-- Also support Auth accounts created before this setup.
insert into public.profiles(id, display_name)
select id, left(coalesce(nullif(btrim(raw_user_meta_data->>'display_name'), ''),
    nullif(btrim(raw_user_meta_data->>'name'), ''), 'Staff member'), 120)
from auth.users on conflict (id) do nothing;

create trigger facilities_timezone before insert or update on public.facilities
    for each row execute function private.validate_timezone();

do $$
declare v_table text;
begin
    foreach v_table in array array['profiles', 'facilities', 'facility_memberships',
        'categories', 'items', 'inventory_batches'] loop
        execute format('create trigger touch_updated_at before update on public.%I
            for each row execute function private.touch_updated_at()', v_table);
    end loop;
    foreach v_table in array array['facilities', 'facility_memberships', 'categories', 'items'] loop
        execute format('create trigger capture_audit after insert or update or delete on public.%I
            for each row execute function private.capture_audit()', v_table);
    end loop;
    foreach v_table in array array['stock_transactions', 'stock_transaction_lines', 'audit_events'] loop
        execute format('create trigger reject_history_mutation before update or delete on public.%I
            for each row execute function private.reject_history_mutation()', v_table);
    end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- Authorized write API. No direct inventory/catalog/membership table writes
-- are granted to API roles, so auditing and stock invariants cannot be skipped.
-- ---------------------------------------------------------------------------
create function public.register_facility(p_name text, p_timezone text default 'Asia/Manila')
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_id uuid;
begin
    if auth.uid() is null or not exists (select 1 from auth.users
        where id = auth.uid() and email_confirmed_at is not null) then
        raise exception 'A verified email account is required' using errcode = '42501';
    end if;
    insert into public.facilities(name, timezone, created_by)
    values (btrim(p_name), p_timezone, auth.uid()) returning id into v_id;
    insert into public.facility_memberships(facility_id, user_id, role)
    values (v_id, auth.uid(), 'admin');
    return v_id;
end;
$$;

create function public.update_facility(p_facility_id uuid, p_name text,
    p_timezone text, p_near_expiry_days integer default 30)
returns void language plpgsql security definer set search_path = '' as $$
begin
    -- Take the strongest lock up front; avoid concurrent share-to-update upgrades.
    perform 1 from public.facilities where id = p_facility_id for update;
    perform private.require_access(p_facility_id, true);
    update public.facilities set name = btrim(p_name), timezone = p_timezone,
        near_expiry_days = p_near_expiry_days where id = p_facility_id;
end;
$$;

-- Adds an EXISTING Auth account by UUID. Invitation delivery/signup UI is a
-- later application decision. Inactivate memberships rather than deleting them.
create function public.set_facility_member(p_facility_id uuid, p_user_id uuid,
    p_role text default 'staff', p_is_active boolean default true)
returns void language plpgsql security definer set search_path = '' as $$
begin
    perform 1 from public.facilities where id = p_facility_id for update;
    perform private.require_access(p_facility_id, true);
    if p_role is null or p_role not in ('admin', 'staff') or p_is_active is null then
        raise exception 'Invalid membership settings' using errcode = '22023';
    end if;
    if exists (select 1 from public.facility_memberships where facility_id = p_facility_id
        and user_id = p_user_id and is_active and role = 'admin')
       and (p_role <> 'admin' or not p_is_active)
       and not exists (select 1 from public.facility_memberships where facility_id = p_facility_id
           and user_id <> p_user_id and is_active and role = 'admin') then
        raise exception 'The last active administrator cannot be removed or demoted' using errcode = '23514';
    end if;
    insert into public.facility_memberships(facility_id, user_id, role, is_active)
    values (p_facility_id, p_user_id, p_role, p_is_active)
    on conflict (facility_id, user_id) do update
        set role = excluded.role, is_active = excluded.is_active;
end;
$$;

create function public.save_category(p_facility_id uuid, p_name text, p_item_type text,
    p_category_id uuid default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_id uuid;
begin
    perform private.require_access(p_facility_id, true);
    if p_category_id is null then
        insert into public.categories(facility_id, name, item_type)
        values (p_facility_id, btrim(p_name), p_item_type) returning id into v_id;
    else
        update public.categories set name = btrim(p_name), item_type = p_item_type
        where facility_id = p_facility_id and id = p_category_id returning id into v_id;
        if not found then raise exception 'Category not found' using errcode = '22023'; end if;
    end if;
    return v_id;
end;
$$;

-- Full-record create/update. Omitted optional fields reset to their defaults.
-- Archive/restore separately with set_item_archived().
create function public.save_item(p_facility_id uuid, p_code text, p_name text,
    p_item_type text, p_unit text, p_category_id uuid default null,
    p_generic_name text default null, p_brand text default null, p_strength text default null,
    p_dosage_form text default null, p_specification text default null, p_description text default null,
    p_expiry_required boolean default true, p_low_stock_threshold bigint default 10,
    p_item_id uuid default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_old public.items%rowtype; v_id uuid;
begin
    perform private.require_access(p_facility_id, true);
    if p_item_id is not null then
        select * into v_old from public.items where facility_id = p_facility_id and id = p_item_id for update;
        if not found then raise exception 'Item not found' using errcode = '22023'; end if;
        if (v_old.unit is distinct from btrim(p_unit) or v_old.item_type is distinct from p_item_type)
           and exists (select 1 from public.stock_transactions where facility_id = p_facility_id and item_id = p_item_id) then
            raise exception 'Unit and item type cannot change after stock history exists' using errcode = '23514';
        end if;
        if p_expiry_required and exists (select 1 from public.inventory_batches
            where facility_id = p_facility_id and item_id = p_item_id and expiry_date is null) then
            raise exception 'Existing undated batches prevent enabling required expiry' using errcode = '23514';
        end if;
        update public.items set code = btrim(p_code), name = btrim(p_name), item_type = p_item_type,
            unit = btrim(p_unit), category_id = p_category_id, generic_name = nullif(btrim(p_generic_name), ''),
            brand = nullif(btrim(p_brand), ''), strength = nullif(btrim(p_strength), ''),
            dosage_form = nullif(btrim(p_dosage_form), ''), specification = nullif(btrim(p_specification), ''),
            description = nullif(btrim(p_description), ''), expiry_required = p_expiry_required,
            low_stock_threshold = p_low_stock_threshold
        where facility_id = p_facility_id and id = p_item_id returning id into v_id;
    else
        insert into public.items(facility_id, code, name, item_type, unit, category_id, generic_name,
            brand, strength, dosage_form, specification, description, expiry_required, low_stock_threshold)
        values (p_facility_id, btrim(p_code), btrim(p_name), p_item_type, btrim(p_unit), p_category_id,
            nullif(btrim(p_generic_name), ''), nullif(btrim(p_brand), ''), nullif(btrim(p_strength), ''),
            nullif(btrim(p_dosage_form), ''), nullif(btrim(p_specification), ''),
            nullif(btrim(p_description), ''), p_expiry_required, p_low_stock_threshold)
        returning id into v_id;
    end if;
    return v_id;
end;
$$;

create function public.set_item_archived(p_facility_id uuid, p_item_id uuid, p_is_archived boolean)
returns void language plpgsql security definer set search_path = '' as $$
begin
    perform private.require_access(p_facility_id, true);
    perform 1 from public.items where facility_id = p_facility_id and id = p_item_id for update;
    if not found then raise exception 'Item not found' using errcode = '22023'; end if;
    if p_is_archived and exists (select 1 from public.inventory_batches
        where facility_id = p_facility_id and item_id = p_item_id and quantity_on_hand > 0) then
        raise exception 'Reconcile all physical stock before archiving' using errcode = '23514';
    end if;
    update public.items set is_archived = p_is_archived where facility_id = p_facility_id and id = p_item_id;
end;
$$;

create function public.delete_unused_item(p_facility_id uuid, p_item_id uuid)
returns void language plpgsql security definer set search_path = '' as $$
begin
    perform private.require_access(p_facility_id, true);
    -- FK restrictions prevent deletion if a batch or any stock history exists.
    delete from public.items where facility_id = p_facility_id and id = p_item_id;
    if not found then raise exception 'Item not found' using errcode = '22023'; end if;
end;
$$;

-- One item per operation; issues can span multiple FEFO batches. An adjustment
-- quantity is the new absolute counted balance of ONE selected batch, including
-- zero. Other operation quantities must be positive. All changes roll back if
-- any allocation/validation fails. Never accept actor IDs from the caller.
create function public.post_stock_transaction(
    p_facility_id uuid, p_item_id uuid, p_transaction_type text,
    p_quantity bigint, p_idempotency_key uuid,
    p_batch_id uuid default null, p_batch_number text default null, p_expiry_date date default null,
    p_reason text default null, p_reference_number text default null,
    p_source_destination text default null, p_corrects_transaction_id uuid default null)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
    v_item public.items%rowtype;
    v_batch public.inventory_batches%rowtype;
    v_existing public.stock_transactions%rowtype;
    v_payload jsonb;
    v_id uuid;
    v_today date;
    v_delta bigint;
    v_take bigint;
    v_remaining bigint;
begin
    perform private.require_access(p_facility_id);
    if p_transaction_type is null or p_transaction_type not in ('receipt', 'issue', 'adjustment', 'disposal')
       or p_quantity is null or p_quantity < 0 or p_idempotency_key is null
       or (p_transaction_type <> 'adjustment' and p_quantity = 0) then
        raise exception 'Invalid transaction type, quantity, or idempotency key' using errcode = '22023';
    end if;
    if (p_transaction_type in ('adjustment', 'disposal') or p_corrects_transaction_id is not null)
       and not private.is_admin(p_facility_id) then
        raise exception 'An administrator is required for adjustments, disposal, and corrections' using errcode = '42501';
    end if;
    if (p_transaction_type in ('adjustment', 'disposal') or p_corrects_transaction_id is not null)
       and nullif(btrim(p_reason), '') is null then
        raise exception 'A reason is required' using errcode = '22023';
    end if;
    if p_transaction_type in ('adjustment', 'disposal') and p_batch_id is null then
        raise exception 'Select a batch for adjustment or disposal' using errcode = '22023';
    end if;
    if (p_transaction_type <> 'receipt' or p_batch_id is not null)
       and (p_batch_number is not null or p_expiry_date is not null) then
        raise exception 'Lot and expiry are supplied only when receiving without a batch ID' using errcode = '22023';
    end if;
    v_payload := jsonb_build_object('item_id', p_item_id, 'type', p_transaction_type,
        'quantity', p_quantity, 'batch_id', p_batch_id, 'batch_number', nullif(btrim(p_batch_number), ''),
        'expiry_date', p_expiry_date, 'reason', nullif(btrim(p_reason), ''),
        'reference_number', nullif(btrim(p_reference_number), ''),
        'source_destination', nullif(btrim(p_source_destination), ''),
        'corrects_transaction_id', p_corrects_transaction_id, 'actor_id', auth.uid());
    -- Serialize identical operation keys, even when callers submit different
    -- items. Then serialize all balance-changing operations for the same item.
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        p_facility_id::text || ':' || p_idempotency_key::text, 0));
    select * into v_existing from public.stock_transactions
        where facility_id = p_facility_id and idempotency_key = p_idempotency_key;
    if found then
        if v_existing.request_payload is distinct from v_payload then
            raise exception 'Idempotency key was already used for a different request' using errcode = '22023';
        end if;
        return v_existing.id;
    end if;
    select * into v_item from public.items where facility_id = p_facility_id and id = p_item_id for update;
    if not found then raise exception 'Item not found' using errcode = '22023'; end if;
    if v_item.is_archived then raise exception 'Item is archived' using errcode = '23514'; end if;
    select (clock_timestamp() at time zone timezone)::date into v_today from public.facilities where id = p_facility_id;

    if p_transaction_type = 'receipt' and p_batch_id is null then
        if nullif(btrim(p_batch_number), '') is null then
            raise exception 'A batch number is required' using errcode = '22023';
        end if;
        if v_item.expiry_required and p_expiry_date is null then
            raise exception 'This item requires an expiry date' using errcode = '22023';
        end if;
        insert into public.inventory_batches(facility_id, item_id, batch_number, expiry_date)
        values (p_facility_id, p_item_id, btrim(p_batch_number), p_expiry_date)
        on conflict on constraint inventory_batches_lot_key do nothing;
        select * into v_batch from public.inventory_batches where facility_id = p_facility_id
            and item_id = p_item_id and batch_number = btrim(p_batch_number)
            and expiry_date is not distinct from p_expiry_date for update;
    elsif p_batch_id is not null then
        select * into v_batch from public.inventory_batches
            where facility_id = p_facility_id and item_id = p_item_id and id = p_batch_id for update;
        if not found then raise exception 'Batch not found for this item' using errcode = '22023'; end if;
    end if;

    if p_transaction_type = 'adjustment' then
        v_delta := p_quantity - v_batch.quantity_on_hand;
        if v_delta = 0 then raise exception 'Count matches the current balance' using errcode = '22023'; end if;
    elsif p_transaction_type = 'receipt' then v_delta := p_quantity;
    else v_delta := -p_quantity;
    end if;

    insert into public.stock_transactions(facility_id, item_id, transaction_type, quantity_change,
        reason, reference_number, source_destination, corrects_transaction_id, actor_id,
        actor_name, item_name, item_code, unit, idempotency_key, request_payload)
    values (p_facility_id, p_item_id, p_transaction_type, v_delta,
        nullif(btrim(p_reason), ''), nullif(btrim(p_reference_number), ''),
        nullif(btrim(p_source_destination), ''), p_corrects_transaction_id, auth.uid(),
        (select display_name from public.profiles where id = auth.uid()),
        v_item.name, v_item.code, v_item.unit, p_idempotency_key, v_payload)
    returning id into v_id;

    if p_transaction_type = 'issue' and p_batch_id is null then
        v_remaining := p_quantity;
        for v_batch in select * from public.inventory_batches
            where facility_id = p_facility_id and item_id = p_item_id and quantity_on_hand > 0
              and (expiry_date is null or expiry_date >= v_today)
            order by expiry_date asc nulls last, created_at, id for update
        loop
            v_take := least(v_remaining, v_batch.quantity_on_hand);
            update public.inventory_batches set quantity_on_hand = quantity_on_hand - v_take
                where id = v_batch.id;
            insert into public.stock_transaction_lines(facility_id, transaction_id, item_id,
                batch_id, batch_number, expiry_date, quantity_change, balance_before, balance_after)
            values (p_facility_id, v_id, p_item_id, v_batch.id, v_batch.batch_number,
                v_batch.expiry_date, -v_take, v_batch.quantity_on_hand, v_batch.quantity_on_hand - v_take);
            v_remaining := v_remaining - v_take;
            exit when v_remaining = 0;
        end loop;
        if v_remaining <> 0 then raise exception 'Insufficient usable stock' using errcode = '23514'; end if;
    else
        if p_transaction_type = 'issue' and v_batch.expiry_date < v_today then
            raise exception 'Expired stock cannot be issued' using errcode = '23514';
        end if;
        if v_batch.quantity_on_hand + v_delta < 0 then
            raise exception 'Insufficient batch stock' using errcode = '23514';
        end if;
        update public.inventory_batches set quantity_on_hand = quantity_on_hand + v_delta where id = v_batch.id;
        insert into public.stock_transaction_lines(facility_id, transaction_id, item_id,
            batch_id, batch_number, expiry_date, quantity_change, balance_before, balance_after)
        values (p_facility_id, v_id, p_item_id, v_batch.id, v_batch.batch_number, v_batch.expiry_date,
            v_delta, v_batch.quantity_on_hand, v_batch.quantity_on_hand + v_delta);
    end if;
    return v_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- Read API: invoker views inherit the caller's RLS, including for aggregates.
-- Dates are facility-local; an expiry date remains usable through that day.
-- ---------------------------------------------------------------------------
create view public.batch_stock_status with (security_invoker = true) as
select b.*, i.name as item_name, i.code as item_code, i.item_type, i.unit, i.is_archived,
    case when b.expiry_date < (now() at time zone f.timezone)::date then 'expired'
         when b.expiry_date <= (now() at time zone f.timezone)::date + f.near_expiry_days then 'near_expiry'
         else 'usable' end as expiry_status
from public.inventory_batches b
join public.items i on i.facility_id = b.facility_id and i.id = b.item_id
join public.facilities f on f.id = b.facility_id;

create view public.inventory_summary with (security_invoker = true) as
select totals.*,
    case when usable_quantity = 0 then 'out_of_stock'
         when usable_quantity <= low_stock_threshold then 'low_stock'
         else 'in_stock' end as stock_status
from (
    select i.facility_id, i.id as item_id, i.code, i.name, i.item_type, i.category_id, i.unit,
        i.low_stock_threshold, i.is_archived,
        coalesce(sum(b.quantity_on_hand), 0)::bigint as physical_quantity,
        coalesce(sum(b.quantity_on_hand) filter (where b.expiry_date is null
            or b.expiry_date >= (now() at time zone f.timezone)::date), 0)::bigint as usable_quantity,
        coalesce(sum(b.quantity_on_hand) filter (where b.expiry_date <
            (now() at time zone f.timezone)::date), 0)::bigint as expired_quantity,
        coalesce(sum(b.quantity_on_hand) filter (where b.expiry_date between
            (now() at time zone f.timezone)::date and
            (now() at time zone f.timezone)::date + f.near_expiry_days), 0)::bigint as near_expiry_quantity
    from public.items i join public.facilities f on f.id = i.facility_id
    left join public.inventory_batches b on b.facility_id = i.facility_id and b.item_id = i.id
    group by i.facility_id, i.id, f.timezone, f.near_expiry_days
) totals;

create view public.facility_dashboard with (security_invoker = true) as
select facility_id,
    count(*) filter (where item_type = 'medicine') as medicine_items,
    count(*) filter (where item_type = 'supply') as supply_items,
    count(*) filter (where stock_status = 'low_stock') as low_stock_items,
    count(*) filter (where stock_status = 'out_of_stock') as out_of_stock_items,
    count(*) filter (where expired_quantity > 0) as items_with_expired_stock,
    count(*) filter (where near_expiry_quantity > 0) as items_with_near_expiry_stock
from public.inventory_summary where not is_archived group by facility_id;

-- ---------------------------------------------------------------------------
-- RLS and least-privilege grants. No anonymous inventory access. Authenticated
-- callers must pass their user JWT, not a service-role key that bypasses RLS.
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.facilities enable row level security;
alter table public.facility_memberships enable row level security;
alter table public.categories enable row level security;
alter table public.items enable row level security;
alter table public.inventory_batches enable row level security;
alter table public.stock_transactions enable row level security;
alter table public.stock_transaction_lines enable row level security;
alter table public.audit_events enable row level security;

create policy profiles_read on public.profiles for select to authenticated
    using (id = (select auth.uid()) or private.shares_facility(id));
create policy profiles_update_self on public.profiles for update to authenticated
    using (id = (select auth.uid())) with check (id = (select auth.uid()));
create policy facilities_read on public.facilities for select to authenticated
    using (private.is_member(id));
create policy memberships_read on public.facility_memberships for select to authenticated
    using (private.is_member(facility_id));
create policy categories_read on public.categories for select to authenticated
    using (private.is_member(facility_id));
create policy items_read on public.items for select to authenticated
    using (private.is_member(facility_id));
create policy batches_read on public.inventory_batches for select to authenticated
    using (private.is_member(facility_id));
create policy transactions_read on public.stock_transactions for select to authenticated
    using (private.is_member(facility_id));
create policy lines_read on public.stock_transaction_lines for select to authenticated
    using (private.is_member(facility_id));
create policy audit_read_admin on public.audit_events for select to authenticated
    using (private.is_admin(facility_id));

revoke all on public.profiles, public.facilities, public.facility_memberships,
    public.categories, public.items, public.inventory_batches, public.stock_transactions,
    public.stock_transaction_lines, public.audit_events,
    public.batch_stock_status, public.inventory_summary, public.facility_dashboard
    from public, anon, authenticated;
grant select on public.profiles, public.facilities, public.facility_memberships,
    public.categories, public.items, public.inventory_batches, public.stock_transactions,
    public.stock_transaction_lines, public.audit_events,
    public.batch_stock_status, public.inventory_summary, public.facility_dashboard to authenticated;
grant update (display_name) on public.profiles to authenticated;

-- Remove PostgreSQL's default PUBLIC function execution on every new function,
-- without changing privileges for unrelated application objects in public.
do $$
declare v_function record;
begin
    for v_function in select p.oid::regprocedure as signature
        from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'private' and p.proname in ('is_member', 'is_admin', 'shares_facility',
            'require_access', 'touch_updated_at', 'validate_timezone', 'capture_audit',
            'reject_history_mutation', 'create_auth_profile')
    loop
        execute format('revoke all on function %s from public, anon, authenticated', v_function.signature);
    end loop;
    for v_function in select p.oid::regprocedure as signature
        from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname in ('register_facility', 'update_facility',
            'set_facility_member', 'save_category', 'save_item', 'set_item_archived',
            'delete_unused_item', 'post_stock_transaction')
    loop
        execute format('revoke all on function %s from public, anon, authenticated', v_function.signature);
        execute format('grant execute on function %s to authenticated', v_function.signature);
    end loop;
end;
$$;
grant execute on function private.is_member(uuid), private.is_admin(uuid), private.shares_facility(uuid)
    to authenticated;

comment on table public.profiles is 'Display identity only; credentials belong to Supabase Auth. Deactivate memberships instead of deleting historical identities.';
comment on table public.audit_events is 'Append-only facility activity history; readable by facility administrators.';
comment on table public.stock_transactions is 'Append-only stock history with actor/item snapshots and retry-safe operation keys.';
comment on table public.stock_transaction_lines is 'Per-batch signed stock changes and before/after balances.';
comment on column public.stock_transactions.corrects_transaction_id is 'Optional correction link to an earlier transaction for the same facility and item; does not automatically reverse it.';
comment on view public.facility_dashboard is 'Active item counts only. An empty facility returns no row; the application should display zeroes.';

commit;
