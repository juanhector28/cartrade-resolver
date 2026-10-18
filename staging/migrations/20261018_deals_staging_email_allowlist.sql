-- CarTrade Deals staging access policy, applied on 2026-10-18
-- Temporary allowlist. Replace with tenant/team membership before production.
-- Only the authenticated JWT email and authenticated subject are trusted.
drop policy if exists ct_deals_owner_select on public.ct_deals;
create policy ct_deals_owner_select on public.ct_deals for select to authenticated
using (
  created_by=(select auth.uid())
  and lower(coalesce((select auth.jwt()->>'email'),'')) in
    ('juan@trustplus.online','juan@nordelia.ca')
);
drop policy if exists ct_deals_owner_insert on public.ct_deals;
create policy ct_deals_owner_insert on public.ct_deals for insert to authenticated
with check (
  created_by=(select auth.uid()) and status='discovery'
  and lower(coalesce((select auth.jwt()->>'email'),'')) in
    ('juan@trustplus.online','juan@nordelia.ca')
);
drop policy if exists ct_deal_events_owner_select on public.ct_deal_events;
create policy ct_deal_events_owner_select on public.ct_deal_events for select to authenticated
using (
  lower(coalesce((select auth.jwt()->>'email'),'')) in
    ('juan@trustplus.online','juan@nordelia.ca')
  and exists(select 1 from public.ct_deals d
    where d.id=deal_id and d.created_by=(select auth.uid()))
);
