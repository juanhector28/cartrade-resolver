-- CarTrade — columnas para el analizador visual de daño (vision_damage.py)
-- Correr UNA vez en el SQL Editor de Supabase, antes de llamar /vision/scan.
-- No borra nada; solo agrega columnas nullable (los listings sin evaluar quedan
-- con visible_damage_risk = NULL, que listing_intelligence trata como "no evaluado").

alter table scraped_listings
  add column if not exists visible_damage_risk real,        -- 0..1, riesgo probabilistico
  add column if not exists damage_signals      text,        -- JSON: ["panel desalineado", ...]
  add column if not exists vision_checked_at    timestamptz; -- cuando se evaluo (NULL = pendiente)

-- indice parcial: /vision/scan busca lo NO evaluado
create index if not exists idx_listings_vision_unchecked
  on scraped_listings (vision_checked_at)
  where vision_checked_at is null;
