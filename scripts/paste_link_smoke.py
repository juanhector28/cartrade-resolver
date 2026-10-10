"""Read-only smoke checks for individual Paste the Link URLs.

Run in an environment with reviewed source access:
  python -m scripts.paste_link_smoke --cases ops/paste_link_smoke_cases.json --output /tmp/paste_link_smoke.json

No database writes or endpoint POSTs. Never reports successful extraction
solely because a URL passed allowlisting or HTTP returned 200.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app import platforms
from app.resolvers import encuentra24, olx, facebook, mercadolibre, fallback


async def check(case: dict) -> dict:
    url = case["url"]
    platform = platforms.detect(url)
    result = {"url": url, "source_id": case["source_id"], "tested_at": datetime.now(timezone.utc).isoformat(),
              "platform": platform, "accepted": platforms.is_allowed(url),
              "listing_route": platforms.is_listing_url(url), "verified": False}
    if not result["accepted"] or not result["listing_route"]:
        result["error"] = "url_not_supported_or_not_individual_listing"
        return result
    resolver = {"encuentra24": encuentra24, "olx": olx, "facebook": facebook,
                "mercadolibre": mercadolibre}.get(platform, fallback)
    try:
        listing = await asyncio.wait_for(resolver.resolve(url), timeout=25)
        fields = listing.to_dict()
        def value(name):
            item = fields.get(name)
            return item.get("value") if isinstance(item, dict) else item
        result["observed"] = {key: value(key) for key in ("title","price_usd","year","km")}
        result["observed"]["photo_count"] = len(fields.get("photos") or [])
        result["errors"] = fields.get("errors") or []
        expected = case.get("expected") or {}
        result["checks"] = {key: result["observed"].get(key) == expected[key]
                            for key in ("price_usd", "year") if key in expected}
        result["verified"] = bool(result["checks"]) and all(result["checks"].values()) and (
            result["observed"]["photo_count"] > 0) and not result["errors"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


async def main(path: Path, output: Path):
    cases = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        results.append(await check(case))
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "cases": len(results), "verified": sum(bool(x["verified"]) for x in results),
              "results": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"cases": report["cases"], "verified": report["verified"], "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.cases, args.output))
