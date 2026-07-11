"""Celery entrypoint. Orchestration lives in `pipeline.py`; the task is a thin
wrapper so the same code path runs under Celery (prod) or directly (dev).

NOTE: the worker must run on Linux/WSL2 — Celery's default prefork pool needs
os.fork(), which native Windows lacks.
"""
from __future__ import annotations

from celery import Celery

from .config import settings

celery_app = Celery(
    "a11y",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_max_tasks_per_child=20,   # recycle browsers/tools periodically
)


@celery_app.task(name="run_job")
def run_job(job_id: str) -> str:
    # Imported here so importing this module (e.g. from the API) doesn't pull in
    # Playwright/engines, and so a missing scanner module can't break startup.
    from . import pipeline

    pipeline.run_job(job_id)
    return job_id
