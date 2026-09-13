-- DRAFT ONLY. DO NOT APPLY DURING DEMO FREEZE.
-- Goal: make atlas_shadow -> staging impossible through ordinary table writes,
-- even for backend clients using service_role. Publisher must go through the
-- narrow RPC below. This complements, rather than replaces, HTTP auth.

begin;

create or replace function public.guard_atlas_shadow_to_staging()
returns trigger
language plpgsql
as $$
begin
  if old.status = 'atlas_shadow' and new.status = 'staging' then
    if coalesce(current_setting('app.atlas_publisher_capability', true), '') <> 'publisher' then
      raise exception 'atlas_shadow_to_staging_requires_publisher_capability'
        using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

-- Idempotent installation shape for the eventual migration.
drop trigger if exists trg_guard_atlas_shadow_to_staging on public.scraped_listings;
create trigger trg_guard_atlas_shadow_to_staging
before update of status on public.scraped_listings
for each row
execute function public.guard_atlas_shadow_to_staging();

create or replace function public.atlas_publisher_promote_rows(
  p_ids bigint[],
  p_source_id text,
  p_manifest_version integer,
  p_updated_at timestamptz default now()
)
returns setof public.scraped_listings
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_source_id is null or length(trim(p_source_id)) < 3 then
    raise exception 'source_id_required' using errcode = '22023';
  end if;
  if p_manifest_version is null or p_manifest_version < 1 then
    raise exception 'manifest_version_required' using errcode = '22023';
  end if;
  if p_ids is null or cardinality(p_ids) = 0 or cardinality(p_ids) > 5000 then
    raise exception 'invalid_publish_id_batch' using errcode = '22023';
  end if;

  perform set_config('app.atlas_publisher_capability', 'publisher', true);

  return query
  update public.scraped_listings s
     set status = 'staging',
         listing_state = 'indexed',
         updated_at = p_updated_at
   where s.id = any(p_ids)
     and s.status = 'atlas_shadow'
     and s.raw_payload @> jsonb_build_object(
       'atlas', jsonb_build_object(
         'source_id', p_source_id,
         'manifest_version', p_manifest_version
       )
     )
  returning s.*;
end;
$$;

revoke all on function public.atlas_publisher_promote_rows(bigint[], text, integer, timestamptz) from public, anon, authenticated;
grant execute on function public.atlas_publisher_promote_rows(bigint[], text, integer, timestamptz) to service_role;

-- Migration acceptance tests, to be run in a disposable/dev DB first:
-- A. direct service_role UPDATE atlas_shadow->staging => SQLSTATE 42501
-- B. anon/authenticated direct transition => denied
-- C. RPC with wrong source/manifest => 0 rows
-- D. RPC with exact owner/source/manifest => only requested rows promoted
-- E. ordinary updates not changing atlas_shadow->staging remain unaffected
-- F. Publisher adversarial suite remains 5/5 PASS after application

rollback;
