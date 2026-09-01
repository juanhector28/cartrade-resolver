from __future__ import annotations

import os
from pathlib import Path

root = Path(os.getenv("RESOLVER_ROOT", "/app"))
runner_path = root / "app" / "atlas_manifest_runner.py"
main_path = root / "app" / "main.py"

s = runner_path.read_text(encoding="utf-8")
marker = "# ATLAS_FINAL_CANDIDATE_GATE_V18"
if marker not in s:
    import_anchor = "from bs4 import BeautifulSoup\n"
    if import_anchor not in s:
        raise RuntimeError("v18 runner import anchor missing")
    s = s.replace(
        import_anchor,
        import_anchor + "from .atlas_candidate_gate_v18 import filter_candidate_urls as _atlas_v18_filter_candidate_urls\n",
        1,
    )

    old_discover = '''        ordered = [u for u, _ in sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))]\n        debug.append({\n            "pages_scanned": [u for u, _ in pages],\n            "candidate_count": len(ordered),\n            "top_candidates": ordered[:10],\n        })\n        return ordered[:scan_limit], debug'''
    new_discover = '''        ordered = [u for u, _ in sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))]\n        filtered, gate_diag = _atlas_v18_filter_candidate_urls(ordered, manifest, scan_limit)\n        debug.append({\n            "pages_scanned": [u for u, _ in pages],\n            "candidate_count_raw": len(ordered),\n            "candidate_count": len(filtered),\n            "top_candidates_raw": ordered[:10],\n            "top_candidates": filtered[:10],\n            "candidate_gate": gate_diag,\n        })\n        return filtered, debug'''
    if old_discover not in s:
        raise RuntimeError("v18 discovery anchor missing")
    s = s.replace(old_discover, new_discover, 1)

    run_anchor = '''            candidates, discovery_debug = await self._discover(client, manifest, scan_limit)\n            sem = asyncio.Semaphore(self.concurrency)'''
    run_replacement = '''            candidates, discovery_debug = await self._discover(client, manifest, scan_limit)\n            candidate_gate = next(\n                (row.get("candidate_gate") for row in reversed(discovery_debug) if isinstance(row, dict) and row.get("candidate_gate")),\n                {},\n            )\n            sem = asyncio.Semaphore(self.concurrency)'''
    if run_anchor not in s:
        raise RuntimeError("v18 run anchor missing")
    s = s.replace(run_anchor, run_replacement, 1)

    return_anchor = '''            "candidate_urls": len(candidates),\n            "attempted": attempted,'''
    return_replacement = '''            "candidate_urls": len(candidates),\n            "candidate_urls_before_filter": int(candidate_gate.get("candidate_urls_before_filter") or len(candidates)),\n            "candidate_urls_after_filter": int(candidate_gate.get("candidate_urls_after_filter") or len(candidates)),\n            "candidate_urls_rejected": int(candidate_gate.get("candidate_urls_rejected") or 0),\n            "candidate_rejection_reasons": candidate_gate.get("rejection_reasons") or {},\n            "candidate_rejected_sample": candidate_gate.get("rejected_sample") or [],\n            "candidate_gate_engine": candidate_gate.get("engine") or "atlas-candidate-gate-v18",\n            "attempted": attempted,'''
    if return_anchor not in s:
        raise RuntimeError("v18 response anchor missing")
    s = s.replace(return_anchor, return_replacement, 1)
    s += "\n\n# ATLAS_FINAL_CANDIDATE_GATE_V18\n"
    runner_path.write_text(s, encoding="utf-8")

m = main_path.read_text(encoding="utf-8")
ready_marker = "# ATLAS_RUNNER_V18_READINESS"
if ready_marker not in m:
    m += r'''

# ATLAS_RUNNER_V18_READINESS
@app.get("/atlas/v18-ready")
def atlas_v18_ready():
    return {
        "ok": True,
        "version": 18,
        "contract": "final_candidate_gate_v18",
        "candidate_gate_engine": "atlas-candidate-gate-v18",
        "final_gate_before_fetch": True,
        "marketing_fail_closed": True,
        "asset_noise_fail_closed": True,
        "rental_fail_closed": True,
        "telemetry": [
            "candidate_urls_before_filter",
            "candidate_urls_after_filter",
            "candidate_urls_rejected",
            "candidate_rejection_reasons",
        ],
        "shadow_only": True,
    }
'''
    main_path.write_text(m, encoding="utf-8")

print("Applied resolver Atlas v18 final candidate gate + readiness")
