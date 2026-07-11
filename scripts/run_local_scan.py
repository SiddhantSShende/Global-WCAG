#!/usr/bin/env python3
"""Run a REAL web audit end-to-end without Docker/Celery.

Uses local filesystem storage and a local SQLite DB so you can run a full scan
from a single command. Requires network access to the target; produces richer
results when the vendored tools + Playwright are installed (scripts/setup_tools.sh).

Usage:
    python scripts/run_local_scan.py https://example.com
    python scripts/run_local_scan.py https://example.com --allow sub.example.com
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Configure a standalone, dependency-light environment BEFORE importing the app.
os.environ.setdefault("A11Y_STORAGE", "local")
os.environ.setdefault("PYTHONUTF8", "1")
(ROOT / "artifacts").mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'artifacts' / 'a11y.db').as_posix()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--allow", action="append", default=[],
                    help="extra in-scope hosts (repeatable)")
    args = ap.parse_args()

    host = urlparse(args.url if "://" in args.url else f"https://{args.url}").netloc
    allowlist = [host] + args.allow

    from backend.app import db, pipeline
    from backend.app.models import Job, TargetType

    db.init_db()
    job = Job(target_type=TargetType.web, target_ref=args.url, authorized=True,
              scope_allowlist=allowlist, created_by="run_local_scan")
    db.save_job(job)
    print(f"Job {job.job_id} — scanning {args.url} (scope: {allowlist})")
    print("This drives the real pipeline; engines that aren't installed will be "
          "reported as errors and their criteria marked 'Needs Manual Review'.\n")

    pipeline.run_job(job.job_id)

    result = db.get_job(job.job_id)
    print(f"\nStatus: {result['status']}  ({result.get('step')})")
    if result.get("error_detail"):
        print("Error:", result["error_detail"][:500])
    reports = ROOT / "artifacts" / job.job_id / "reports"
    if reports.exists():
        print(f"\nReports in {reports}:")
        for p in sorted(reports.iterdir()):
            print(f"  {p.name}  ({p.stat().st_size // 1024} KB)")
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
