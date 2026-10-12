-- Pending operator authorization is separate from Auth identities and actual
-- permissions. Approving an email here NEVER gives access to buyer contacts.
-- Do not commit enrolled email addresses or other personal data to the repo.
create table if not exists public.buyer_ops_enrollments (
  email text primary key check (email = lower(trim(email)) and length(email) between 5 and 254),
  role text not null check (role in ('admin','operator')),
  status text not null default 'pending_auth' check (status in ('pending_auth','active','revoked')),
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  auth_user_id uuid unique references auth.users(id) on delete set null,
  constraint buyer_ops_enrollments_active_require_identity
    check (status <> 'active' or (auth_user_id is not null and activated_at is not null))
);
alter table public.buyer_ops_enrollments enable row level security;
revoke all on public.buyer_ops_enrollments from public, anon, authenticated;
grant select, insert, update, delete on public.buyer_ops_enrollments to service_role;
comment on table public.buyer_ops_enrollments is 'Pending authorization for verified operator email. Does not grant access until authenticated staff membership exists.';
