-- Individual operator accounts are provisioned in Supabase Auth separately.
-- Apply after buyer_intents migration. No accounts are automatically authorized.
create table if not exists public.buyer_ops_staff (
    user_id uuid primary key references auth.users(id) on delete cascade,
    role text not null check (role in ('admin','operator')),
    active boolean not null default false,
    created_at timestamptz not null default now()
);
alter table public.buyer_ops_staff add column if not exists email text;
create unique index if not exists buyer_ops_staff_email_unique
    on public.buyer_ops_staff(lower(email)) where email is not null;
alter table public.buyer_ops_staff enable row level security;
revoke all on table public.buyer_ops_staff from public, anon, authenticated;
grant select, insert, update, delete on table public.buyer_ops_staff to service_role;
comment on table public.buyer_ops_staff is 'Authorization gate for individually authenticated CarTrade staff. New staff disabled by default.';
