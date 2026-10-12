-- One immutable synthetic receipt tests Netlify → Supabase without PII.
-- This does NOT authorize real buyer-intent collection.
create table if not exists public.cartrade_link_first_probe (
    probe_id uuid primary key
       check (probe_id = 'a4c3a9e4-2d7c-44ab-b53d-9b57409c2026'::uuid),
    listing_url text not null
       check (listing_url = 'https://example.org/cartrade-demo-vehicle'),
    buyer_contact text not null
       check (buyer_contact = 'TEST_ONLY_NO_PHONE'),
    is_synthetic boolean not null default true check (is_synthetic = true),
    created_at timestamptz not null default now()
);
alter table public.cartrade_link_first_probe enable row level security;
revoke all on public.cartrade_link_first_probe from public, anon, authenticated;
grant select, insert on public.cartrade_link_first_probe to service_role;
comment on table public.cartrade_link_first_probe is
'One fixed synthetic row for testing Netlify to Supabase. No real buyer PII or public data access.';
