"""Durable ingestion rotation and bounded renewal of existing CRAutos listings."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
PREFIX = "inventory_maintenance:"


def now():
    return datetime.now(timezone.utc).isoformat()


def read_states(db):
    rows = db.table("registry_private_config").select("name,value").like("name", PREFIX + "%").execute().data or []
    return {r["name"][len(PREFIX):]: json.loads(r["value"]) for r in rows}


def write_state(db, key, value):
    db.table("registry_private_config").upsert({"name": PREFIX + key,
        "value": json.dumps(value), "updated_at": now()}, on_conflict="name").execute()


def next_country(countries, states):
    # Failed attempts advance rotation too; records survive application restarts.
    return min(countries, key=lambda c: states.get(c, {}).get("last_attempt_at") or "")


def completion(summary, error=None):
    if error:
        return "failed"
    if not summary or int(summary.get("saved_count", 0)) <= 0:
        return "failed"
    return "partial" if summary.get("error_count") else "succeeded"


def valid_crautos_detail(detail):
    # A removed detail often returns the search form with HTTP 200 and its
    # unrelated prices. Never renew a record on HTTP status alone.
    return bool(detail.get("marca") and detail.get("modelo")
        and isinstance(detail.get("anio"), int) and 1900 <= detail["anio"] <= 2030
        and detail.get("precio_usd") and detail["precio_usd"] > 0
        and detail.get("n_fotos", 0) > 0)


def crautos_batch(main, size=100):
    from .scrapers.crautos import crautos_scraper as scraper
    db = main.supabase
    state = read_states(db).get("crautos", {})
    started = now()
    state.update(last_attempt_at=started, state="running", error=None)
    write_state(db, "crautos", state)
    cursor = int(state.get("cursor_id") or 0)
    query = db.table("scraped_listings").select("id,url").eq("source", "crautos").eq("status", "staging").eq("listing_state", "indexed")
    rows = query.gt("id", cursor).order("id").limit(size).execute().data or []
    if not rows and cursor:
        state["cursor_id"] = 0
        rows = db.table("scraped_listings").select("id,url").eq("source", "crautos").eq("status", "staging").eq("listing_state", "indexed").order("id").limit(size).execute().data or []
    saved = errors = rejected = 0
    session = scraper.make_session()
    try:
        # Current public catalogue also finds replacements for removed ads.
        # Keep the historical cursor independent of these new candidates.
        catalogue = session.get(scraper.INDEX_URL, timeout=20)
        catalogue.raise_for_status()
        ids = sorted(scraper.extract_ids(catalogue.text))[:20]
        current = [{"url": scraper.DETAIL_URL + "?c=" + cid} for cid in ids]
        current_urls = {row["url"] for row in current}
        work = current + [r for r in rows if r["url"] not in current_urls]
        for row in work:
            match = re.fullmatch(r"https://(?:www\.)?crautos\.com/autosusados/cardetail\.cfm\?c=(\d+)", row["url"])
            try:
                if not match:
                    rejected += 1
                    continue
                response = session.get(row["url"], timeout=20)
                response.raise_for_status()
                detail = scraper.parse_detail(response.text, match.group(1))
                full_model = " ".join([detail.get("marca") or "", detail.get("modelo") or ""]).strip()
                make = main.parsers.extract_make(full_model)
                if make and full_model.lower().startswith(make[0].lower() + " "):
                    detail["marca"] = make[0]
                    detail["modelo"] = full_model[len(make[0]):].strip()
                if not valid_crautos_detail(detail):
                    rejected += 1
                    continue
                record = main._crautos_record_from_detail(detail, "staging")
                # Update existing publication only. Generated DB columns are
                # omitted by the mapper; no resurrection or mass re-dating.
                if row.get("id"):
                    for key in ("url", "source", "country", "status"):
                        record.pop(key, None)
                    written = db.table("scraped_listings").update(record).eq("id", row["id"]).eq("source", "crautos").eq("status", "staging").eq("listing_state", "indexed").execute().data
                else:
                    existing = db.table("scraped_listings").select("id,status,listing_state").eq("url", row["url"]).limit(1).execute().data or []
                    if existing:
                        if existing[0].get("status") != "staging" or existing[0].get("listing_state") != "indexed":
                            rejected += 1
                            continue
                        for key in ("url", "source", "country", "status"):
                            record.pop(key, None)
                        written = db.table("scraped_listings").update(record).eq("id", existing[0]["id"]).eq("status", "staging").eq("listing_state", "indexed").execute().data
                    else:
                        record["listing_state"] = "indexed"
                        written = db.table("scraped_listings").insert(record).execute().data
                if not written:
                    raise RuntimeError("database_did_not_confirm_vehicle_write")
                saved += 1
            except Exception as exc:
                errors += 1
                state["error"] = str(exc)[:240]
                # Do not repeatedly hit a denied source during this batch.
                if getattr(getattr(exc, "response", None), "status_code", None) in (403, 429):
                    if row.get("id"):
                        state["cursor_id"] = row["id"]
                    break
            finally:
                if row.get("id"):
                    state["cursor_id"] = row["id"]
                time.sleep(1)
        state.update(state="partial" if saved and (errors or rejected) else "succeeded" if saved else "failed",
            completed_at=now(), saved_count=saved, error_count=errors, rejected_count=rejected)
        if saved:
            state["last_success_at"] = now()
        if not saved and not state.get("error"):
            state["error"] = "No current vehicle detail was verified; freshness unchanged"
        write_state(db, "crautos", state)
        return state
    finally:
        session.close()


def install(main):
    original_one = main._run_one
    original_all = main._run_all_ca

    async def pick():
        if not main.supabase:
            raise RuntimeError("supabase_not_connected")
        return next_country(main.CA_COUNTRIES, read_states(main.supabase))

    async def run_one(country, pages):
        states = read_states(main.supabase)
        state = states.get(country, {})
        state.update(last_attempt_at=now(), state="running", error=None)
        write_state(main.supabase, country, state)
        await original_one(country, pages)
        result = main.INVENTORY_JOB_STATUS["results"].get(country, {})
        error = main.INVENTORY_JOB_STATUS.get("last_error")
        summary = {"saved_count": result.get("saved", 0), "error_count": result.get("errors", 0)}
        status = completion(summary, error)
        state.update(state=status, completed_at=now(), saved_count=summary["saved_count"],
            error_count=summary["error_count"], error=str(error)[:300] if error else None)
        if status == "failed" and not error:
            state["error"] = "No listings saved; source refresh did not succeed"
        if summary["saved_count"]:
            state["last_success_at"] = now()
        write_state(main.supabase, country, state)
        main.INVENTORY_JOB_STATUS["outcome"] = status
        log.info("INVENTORY_REFRESH_RESULT country=%s state=%s saved=%s", country, status, summary["saved_count"])

    main._pick_next_country = pick
    main._run_one = run_one

    async def run_all(pages):
        # The batch endpoint gets the same persisted outcome as rotation.
        for country in main.CA_COUNTRIES:
            state = read_states(main.supabase).get(country, {})
            state.update(last_attempt_at=now(), state="running", error=None)
            write_state(main.supabase, country, state)
        await original_all(pages)
        for country in main.CA_COUNTRIES:
            result = main.INVENTORY_JOB_STATUS["results"].get(country, {})
            state = read_states(main.supabase).get(country, {})
            summary = {"saved_count": result.get("saved", 0), "error_count": result.get("errors", 0)}
            state.update(state=completion(summary, result.get("error")), completed_at=now(),
                saved_count=summary["saved_count"], error_count=summary["error_count"],
                error=str(result.get("error") or "No listings saved")[:300] if not summary["saved_count"] else None)
            if summary["saved_count"]:
                state["last_success_at"] = now()
            write_state(main.supabase, country, state)
    main._run_all_ca = run_all

    @main.app.get("/inventory-maintenance/status")
    async def status():
        if not main.supabase:
            return JSONResponse({"ok": False, "error": "supabase_not_connected"}, status_code=503)
        states = read_states(main.supabase)
        countries = {c: states.get(c, {"state": "not_checked"}) for c in main.CA_COUNTRIES}
        ok = all(v.get("state") == "succeeded" for v in countries.values())
        return JSONResponse({"ok": ok, "countries": countries, "crautos": states.get("crautos"),
            "next_country": next_country(main.CA_COUNTRIES, states)}, status_code=200 if ok else 503)

    @main.app.on_event("startup")
    async def startup():
        if not main.supabase or os.getenv("INVENTORY_CRAUTOS_REFRESH_ENABLED", "1") != "1":
            return
        async def loop():
            await asyncio.sleep(10)
            while True:
                try:
                    result = await asyncio.to_thread(crautos_batch, main)
                    log.info("CRAUTOS_REFRESH_RESULT state=%s saved=%s rejected=%s errors=%s cursor=%s",
                        result["state"], result["saved_count"], result["rejected_count"], result["error_count"], result.get("cursor_id"))
                except Exception:
                    log.exception("CRAUTOS_REFRESH_FAILED")
                await asyncio.sleep(300)
        main.app.state.crautos_refresh_task = asyncio.create_task(loop())

    @main.app.on_event("shutdown")
    async def shutdown():
        task = getattr(main.app.state, "crautos_refresh_task", None)
        if task:
            task.cancel()
