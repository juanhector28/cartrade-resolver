"""Carly v36: cached visual-damage gate for recommendation finalists.

P0 trust fix:
- treat persisted `visible_damage_risk` as the numeric 0..1 column it actually is;
- before surfacing a shortlist, visually inspect at most a tiny number of previously
  unchecked finalists, one photo each, in parallel;
- persist the result so the same listing is never charged again;
- rerank after enrichment so a visibly risky car cannot remain in Top 3/Explore.

The JIT path is intentionally bounded. It does not scan the whole inventory.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from . import main_v35 as v35

app = v35.app
v34 = v35.v34
v31 = v34.v31
v28 = v34.v28
legacy = v31.legacy

_ORIG_HARD_RISK = v28._hard_risk
_ORIG_RANK_ROWS = v31._rank_rows

DAMAGE_RISK_THRESHOLD = 0.50
JIT_MAX_LISTINGS = max(0, min(3, int(os.environ.get("CARLY_VISION_JIT_MAX", "3") or 3)))
JIT_ENABLED = os.environ.get("CARLY_VISION_JIT_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
JIT_MODEL = os.environ.get("CARLY_VISION_JIT_MODEL") or getattr(legacy, "CARLY_MODEL", "claude-sonnet-4-6")

try:
    v31.v29.v28.v27.v26.v25.v20.commercial.RUNTIME_COMPOSITION = "commercial-v36-vision-gate"
except Exception:
    pass

_VISION_SYSTEM = """You review ONE photo from a used-car listing as a conservative safety screen.
Do not infer accident history or salvage status. Only judge visible exterior/body damage.
Return JSON only: {"visible_damage_risk":0.0,"signals":[]}.
Use risk >= 0.50 only when there is a concrete visible sign such as a deformed/misaligned
body panel, broken or detached bumper/light/glass, clearly abnormal wheel position, a
missing exterior part, or similarly meaningful impact/reparation evidence. Small scratches,
dirt, shadows and reflections are not enough. If the image is unhelpful, use a low risk.
"""


def _risk(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _hard_risk(card: dict, enriched: dict | None = None) -> bool:
    """Honor the persisted float risk before the legacy textual quality gate."""
    for source in (enriched, card):
        if isinstance(source, dict):
            risk = _risk(source.get("visible_damage_risk"))
            if risk is not None and risk >= DAMAGE_RISK_THRESHOLD:
                return True
    return _ORIG_HARD_RISK(card, enriched)


def _photo(row: dict) -> str | None:
    primary = row.get("primary_photo")
    if isinstance(primary, str) and primary.startswith(("http://", "https://")):
        return primary
    photos = row.get("photos")
    if isinstance(photos, str):
        try:
            parsed = json.loads(photos)
            photos = parsed if isinstance(parsed, list) else [photos]
        except Exception:
            photos = [photos]
    for value in photos or []:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    raw = row.get("raw_payload")
    if isinstance(raw, dict):
        for key in ("photo", "thumb"):
            value = raw.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


def _parse_result(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    risk = _risk(data.get("visible_damage_risk"))
    if risk is None:
        return None
    signals = data.get("signals") if isinstance(data.get("signals"), list) else []
    signals = [str(s).strip()[:100] for s in signals if str(s).strip()][:4]
    # Never persist a damaging score without a concrete signal.
    if risk >= DAMAGE_RISK_THRESHOLD and not signals:
        risk = 0.49
    return {"visible_damage_risk": round(risk, 3), "signals": signals}


def _vision_result(row: dict) -> dict | None:
    if not JIT_ENABLED or JIT_MAX_LISTINGS <= 0:
        return None
    client = getattr(legacy, "_anthropic", None)
    photo = _photo(row)
    if client is None or not photo:
        return None
    try:
        resp = client.messages.create(
            model=JIT_MODEL,
            max_tokens=180,
            system=_VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "url", "url": photo}},
                    {"type": "text", "text": "Screen this single vehicle photo. Return only JSON."},
                ],
            }],
        )
        text = "".join(
            getattr(block, "text", "") for block in getattr(resp, "content", [])
            if getattr(block, "type", "") == "text"
        )
        return _parse_result(text)
    except Exception:
        return None


def _persist(row: dict, result: dict) -> None:
    risk = _risk(result.get("visible_damage_risk"))
    if risk is None:
        return
    payload = {
        "visible_damage_risk": risk,
        "damage_signals": json.dumps(result.get("signals") or [], ensure_ascii=False),
        "vision_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    row.update(payload)
    client = getattr(legacy, "supabase", None)
    if client is None:
        return
    try:
        query = client.table("scraped_listings").update(payload)
        if row.get("id") is not None:
            query = query.eq("id", row["id"])
        elif row.get("url"):
            query = query.eq("url", row["url"])
        else:
            return
        query.execute()
    except Exception:
        # Cache write failure must not break recommendations. The in-memory row is
        # still screened for this response.
        pass


def _scan_uncached_finalists(ranked: list[dict]) -> int:
    if not JIT_ENABLED or JIT_MAX_LISTINGS <= 0:
        return 0
    pending = [
        row for row in ranked[:8]
        if isinstance(row, dict)
        and not row.get("vision_checked_at")
        and _risk(row.get("visible_damage_risk")) is None
        and _photo(row)
    ][:JIT_MAX_LISTINGS]
    if not pending:
        return 0

    completed = 0
    with ThreadPoolExecutor(max_workers=len(pending)) as pool:
        futures = {pool.submit(_vision_result, row): row for row in pending}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None
            if result is not None:
                _persist(row, result)
                completed += 1
    return completed


def _rank_rows(rows: list[dict], c: dict[str, Any]):
    """Rank, inspect only likely finalists, then rank again with cached vision."""
    ranked, filtered = _ORIG_RANK_ROWS(rows, c)
    scanned = _scan_uncached_finalists(ranked)
    if scanned:
        ranked2, filtered2 = _ORIG_RANK_ROWS(rows, c)
        return ranked2, max(filtered, filtered2)
    return ranked, filtered


# v31 resolves these globals dynamically from its module namespace.
v28._hard_risk = _hard_risk
v31._rank_rows = _rank_rows
