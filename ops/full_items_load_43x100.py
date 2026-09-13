#!/usr/bin/env python3
"""Read-only 43x100 production load harness for the Atlas Resolver.

This script NEVER persists listings. It requires exactly 43 distinct source
payloads and forcibly overrides each request to mode=shadow, limit=100 and
persist=False. It emits one JSON receipt per source plus a final summary.

Usage:
  RESOLVER_URL=https://... ATLAS_BRIDGE_TOKEN=... \
    python ops/full_items_load_43x100.py gt43_payloads.json

Input is a JSON array of 43 objects containing the normal /atlas/run-source
request fields (source_id, country, domain, manifest_version, manifest).
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

EXPECTED_SOURCES = 43
EXPECTED_LIMIT = 100
DEFAULT_CONCURRENCY = 4


def _load(path: str) -> list[dict[str, Any]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("payload file must be a JSON array")
    if len(rows) != EXPECTED_SOURCES:
        raise SystemExit(f"expected exactly {EXPECTED_SOURCES} payloads; got {len(rows)}")
    ids = [str(r.get("source_id") or "").strip() for r in rows if isinstance(r, dict)]
    if len(ids) != EXPECTED_SOURCES or any(not x for x in ids):
        raise SystemExit("all 43 payloads must have non-empty source_id")
    if len(set(ids)) != EXPECTED_SOURCES:
        raise SystemExit("43x100 gate requires 43 distinct source_id values")
    return rows


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    required = ["source_id", "country", "manifest_version", "manifest"]
    missing = [k for k in required if row.get(k) in (None, "")]
    if missing:
        raise ValueError(f"missing required fields: {missing}")
    return {
        "source_id": str(row["source_id"]),
        "country": str(row["country"]).lower(),
        "domain": row.get("domain"),
        "manifest_version": int(row["manifest_version"]),
        "manifest": row["manifest"],
        "mode": "shadow",
        "limit": EXPECTED_LIMIT,
        "scan_limit": 500,
        "persist": False,
    }


async def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: full_items_load_43x100.py <43-payloads.json>")
    base = (os.environ.get("RESOLVER_URL") or "").rstrip("/")
    token = os.environ.get("ATLAS_BRIDGE_TOKEN") or ""
    if not base or not token:
        raise SystemExit("RESOLVER_URL and ATLAS_BRIDGE_TOKEN are required")
    concurrency = max(1, min(int(os.environ.get("LOAD_CONCURRENCY", DEFAULT_CONCURRENCY)), 8))
    timeout_s = float(os.environ.get("LOAD_REQUEST_TIMEOUT_SECONDS", "240"))
    rows = _load(sys.argv[1])
    sem = asyncio.Semaphore(concurrency)
    receipts: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        async def run(row: dict[str, Any]) -> None:
            req = _payload(row)
            source_id = req["source_id"]
            async with sem:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        base + "/atlas/run-source",
                        headers={"X-Atlas-Token": token},
                        json=req,
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    body: Any
                    try:
                        body = response.json()
                    except Exception:
                        body = {"raw": response.text[:1000]}
                    items = body.get("items") if isinstance(body, dict) else None
                    items = items if isinstance(items, list) else []
                    valid = int(body.get("valid_listings") or len(items)) if isinstance(body, dict) else 0
                    attempted = int(body.get("attempted") or 0) if isinstance(body, dict) else 0
                    receipt = {
                        "source_id": source_id,
                        "http": response.status_code,
                        "elapsed_ms": round(elapsed, 1),
                        "attempted": attempted,
                        "valid_listings": valid,
                        "items_count": len(items),
                        "persist": False,
                        "limit": EXPECTED_LIMIT,
                        "ok": response.status_code < 400 and len(items) == valid and len(items) <= EXPECTED_LIMIT,
                    }
                    if response.status_code >= 400:
                        receipt["error"] = str(body)[:1500]
                except Exception as exc:
                    receipt = {
                        "source_id": source_id,
                        "http": None,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                        "attempted": 0,
                        "valid_listings": 0,
                        "items_count": 0,
                        "persist": False,
                        "limit": EXPECTED_LIMIT,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
                    }
                receipts.append(receipt)
                print(json.dumps({"type": "source_receipt", **receipt}, sort_keys=True), flush=True)

        await asyncio.gather(*(run(row) for row in rows))

    receipts.sort(key=lambda x: x["source_id"])
    latencies = [float(r["elapsed_ms"]) for r in receipts]
    failures = [r for r in receipts if not r["ok"]]
    target_closed = [r for r in receipts if "TargetClosed" in str(r.get("error") or "")]
    summary = {
        "contract": "resolver-full-items-43x100-v1",
        "sources_expected": EXPECTED_SOURCES,
        "sources_completed": len(receipts),
        "request_limit": EXPECTED_LIMIT,
        "persist": False,
        "concurrency": concurrency,
        "failures": len(failures),
        "target_closed": len(target_closed),
        "latency_ms": {
            "min": round(min(latencies), 1),
            "median": round(statistics.median(latencies), 1),
            "max": round(max(latencies), 1),
        },
        "resolver_contract_pass": len(receipts) == EXPECTED_SOURCES and not failures and not target_closed,
        "failed_sources": [r["source_id"] for r in failures],
    }
    print(json.dumps({"type": "load_summary", **summary}, sort_keys=True), flush=True)
    out = Path(os.environ.get("LOAD_RECEIPT_PATH", "full_items_43x100_receipt.json"))
    out.write_text(json.dumps({"summary": summary, "receipts": receipts}, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if summary["resolver_contract_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
