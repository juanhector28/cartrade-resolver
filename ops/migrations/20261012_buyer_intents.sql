-- Separate buyer requests from Atlas inventory. Apply only after security/privacy review.
-- Service-role writes only; never expose buyer contact via public table APIs.
create table if not exists public.buyer_intents (
    request_id uuid primary key,
    created_at timestamptz not null default now(),
    buyer_contact text not null check (buyer_contact ~ '^[0-9]{8,15}$'),
    contact_channel text not null default 'whatsapp' check (contact_channel = 'whatsapp'),
    listing_url text not null,
    car_name text not null,
    price_usd integer check (price_usd between 500 and 200000),
    country text not null check (country in ('sv','gt','cr','hn','ni','pa')),
    source text not null check (source = 'paste_link'),
    consent_to_contact boolean not null check (consent_to_contact = true),
    consent_recorded_at timestamptz not null default now(),
    status text not null default 'received' check (status in ('received','in_review','contacted','closed'))
);

create index if not exists buyer_intents_created_at_idx on public.buyer_intents (created_at desc);
alter table public.buyer_intents enable row level security;
revoke all on table public.buyer_intents from public, anon, authenticated;
grant select, insert, update, delete on table public.buyer_intents to service_role;
-- No public RLS policies. Supabase service_role has bypass RLS.
-- Configure retention/deletion workflow and privacy disclosures before enabling intake.
