from pathlib import Path

p = Path("/app/app/main.py")
s = p.read_text(encoding="utf-8")
marker = "# CARLY_GT_DEMO_BREADTH_V23"

if marker not in s:
    s += r'''

# CARLY_GT_DEMO_BREADTH_V23
# Read-only demo lane for Guatemala. Production /carly/search and /carly/chat
# remain unchanged and continue to exclude atlas_shadow inventory.
class CarlyGtDemoSearchRequest(BaseModel):
    q: str = ""
    country: str = "gt"
    limit: int = 30
    per_source: int = 2


def _gt_demo_atlas_meta(row: dict) -> dict:
    raw = row.get("raw_payload")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    atlas = raw.get("atlas")
    return atlas if isinstance(atlas, dict) else {}


def _gt_demo_source_id(row: dict) -> str:
    atlas = _gt_demo_atlas_meta(row)
    sid = str(atlas.get("source_id") or "").strip()
    if sid:
        return sid
    source = str(row.get("source") or "").strip()
    if source:
        return source
    try:
        from urllib.parse import urlparse
        return urlparse(str(row.get("url") or "")).netloc.lower() or "unknown"
    except Exception:
        return "unknown"


@app.post("/carly/demo/gt-breadth")
async def carly_gt_demo_breadth(body: CarlyGtDemoSearchRequest):
    """Return a source-diverse GT sample from real staging + Atlas shadow rows.

    This endpoint is deliberately read-only and demo-only. It never changes
    addressability, promotion state, manifest state, or the production Carly
    search contract.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not connected.")

    country = str(body.country or "gt").lower().strip()
    if country != "gt":
        raise HTTPException(status_code=400, detail="GT demo lane only.")

    limit = max(1, min(int(body.limit or 30), 60))
    per_source = max(1, min(int(body.per_source or 2), 5))

    it = parse_intent(body.q or "")
    q = (
        supabase.table("scraped_listings")
        .select(CARLY_COLS + ",status")
        .eq("country", "gt")
        .in_("status", ["staging", "atlas_shadow"])
        .not_.is_("price_usd", "null")
        .not_.is_("make", "null")
        .not_.is_("model", "null")
        .not_.is_("year", "null")
    )

    if it.body_types:
        q = q.in_("body_type", it.body_types)
    if it.transmission:
        q = q.eq("transmission", it.transmission)
    if it.make:
        q = q.ilike("make", f"%{it.make}%")
    if it.price_max:
        q = q.lte("price_usd", it.price_max)
    if it.price_min:
        q = q.gte("price_usd", it.price_min)

    try:
        pool = (
            q.order("quality_score", desc=True)
            .limit(600)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Supabase query failed: {exc!s}")

    # Bucket by provenance first. Pool is already quality-ordered, so round-robin
    # across buckets maximizes visible source variety before adding depth.
    buckets: dict[str, list[dict]] = {}
    seen_urls: set[str] = set()
    for row in pool:
        url = str(row.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sid = _gt_demo_source_id(row)
        buckets.setdefault(sid, []).append(row)

    chosen: list[dict] = []
    ordered_sources = list(buckets.keys())
    for seat in range(per_source):
        for sid in ordered_sources:
            rows = buckets.get(sid) or []
            if seat >= len(rows):
                continue
            row = rows[seat]
            atlas = _gt_demo_atlas_meta(row)
            chosen.append({
                **{k: row.get(k) for k in (
                    "id", "country", "url", "make", "model", "year", "km",
                    "price_usd", "monthly_est", "transmission", "location",
                    "body_type", "quality_score", "primary_photo",
                )},
                "source_id": sid,
                "source_status": row.get("status"),
                "manifest_version": atlas.get("manifest_version"),
                "demo_only": True,
            })
            if len(chosen) >= limit:
                break
        if len(chosen) >= limit:
            break

    return {
        "demo_only": True,
        "country": "gt",
        "query": body.q,
        "intent": it.model_dump(),
        "candidate_rows": len(pool),
        "distinct_sources_available": len(buckets),
        "distinct_sources_returned": len({r["source_id"] for r in chosen}),
        "count": len(chosen),
        "per_source_cap": per_source,
        "includes_statuses": ["staging", "atlas_shadow"],
        "results": chosen,
    }
'''

p.write_text(s, encoding="utf-8")
print("Installed Carly GT demo breadth v23")
