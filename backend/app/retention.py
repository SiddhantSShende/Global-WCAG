"""Artifact retention — delete job artifacts older than the retention window.

Authenticated scans can capture personal data in screenshots, so short retention
+ access-controlled storage are part of the privacy posture. Run on a schedule
(cron / Celery beat):  python -m backend.app.retention
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .config import settings

_KEEP = {"demo", ".secrets", "_cache"}


def purge_expired(days: int | None = None) -> dict:
    days = settings.retention_days if days is None else days
    cutoff = time.time() - days * 86400
    root = settings.artifacts_dir
    removed = []
    if not root.exists():
        return {"removed": [], "count": 0, "days": days}
    for child in root.iterdir():
        if child.name in _KEEP or not child.is_dir():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)
        except Exception:
            continue
    return {"removed": removed, "count": len(removed), "days": days}


if __name__ == "__main__":
    result = purge_expired()
    print(f"Retention purge: removed {result['count']} job artifact dir(s) "
          f"older than {result['days']} days.")
