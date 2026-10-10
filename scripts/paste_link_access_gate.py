"""Fail-closed authorization gate for live Paste the Link source audits."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from urllib.parse import urlparse


def validate(case_path: Path, access_path: Path) -> tuple[bool, list[str]]:
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    register = json.loads(access_path.read_text(encoding="utf-8"))
    grants = {entry["source_id"]: entry for entry in register["sources"]}
    issues: list[str] = []
    for case in cases:
        source_id = case.get("source_id", "")
        source = grants.get(source_id)
        host = (urlparse(case.get("url", "")).hostname or "").lower().removeprefix("www.")
        if not source:
            issues.append(f"{source_id}: no source access review")
        elif not source.get("authorized") or source.get("status") != "authorized":
            issues.append(f"{source_id}: commercial network access not authorized")
        elif host != source.get("domain"):
            issues.append(f"{source_id}: approved domain mismatch")
        elif not source.get("agreement_reference") or not source.get("price_collection_permitted"):
            issues.append(f"{source_id}: missing documented permission for price collection")
    return not issues, issues


if __name__ == "__main__":
    ok, problems = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    for issue in problems:
        print(issue)
    if not ok:
        sys.exit(1)
    print("All source permissions verified for the requested test set.")
