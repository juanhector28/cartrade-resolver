# Inventory renewal operations

The country cron at `/inventory-run-next` now rotates by **last attempt**, persisted in `registry_private_config` under `inventory_maintenance:<country>`. Failed countries therefore do not monopolize subsequent runs. The existing external cron can keep its URL; the endpoint returns HTTP 202 for an accepted background job, which does not certify completion.

Use `/inventory-maintenance/status` to inspect completed outcomes, confirmed write counts and the next country. It returns HTTP 503 until every country has a successful latest run. `failed`, `partial` and `not_checked` are explicit. Country history survives process restarts. `/inventory-status` also exposes the latest outcome. Operators can trigger a country with the existing cron token in `X-Inventory-Token`, avoiding token-bearing URLs.

CRAutos maintenance starts with the application, unless `INVENTORY_CRAUTOS_REFRESH_ENABLED=0`. It verifies up to 20 current catalogue listings and 100 existing indexed listings per batch, then waits five minutes. A persisted ID cursor walks the existing inventory independently of the current catalogue. This is bounded work, not a promise to refresh the entire catalogue in 24 hours. Fetches are sequential with a one-second pause; a 403 or 429 stops the batch. Removed detail URLs can redirect to the search page with HTTP 200: these are rejected without changing `last_seen_at`. Publication states and generated database columns are preserved.

The current public catalogue can add verified new listings or refresh existing indexed staging rows. It cannot resurrect expired, contacted or shadow rows. A successful write must be confirmed by Supabase before it is counted. Diagnostic rows expose counts, not credentials or seller contact information.

Encuentra24 was observed returning HTTP 403 / error 1010 on 2026-10-04. Rotation and diagnostics do not remove a source owner's access restriction. An authorized feed/API or access allowed by the source is required to restore that source; no synthetic refresh timestamps are applied. See https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/

Run `pytest -q tests/test_inventory_maintenance.py` for failed-country rotation, restart persistence, zero-write outcomes and rejection of search pages as vehicle evidence. Build with the Dockerfile, which applies all production patches before launching `app.main_v51:app`.
