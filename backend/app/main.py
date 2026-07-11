"""FastAPI service: job intake (with the authorization gate), status, downloads."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, wcag
from .auth import require_role
from .config import settings
from .models import Job, Review, Status, TargetType
from .storage import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
    except Exception as exc:  # noqa: BLE001 — API still serves status if DB late
        print(f"[startup] DB init deferred: {exc}")
    yield


app = FastAPI(title="Accessibility Compliance Audit Platform", version="1.0.0",
              lifespan=lifespan)

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_DIST = _FRONTEND_DIR / "dist"

# Serve the built React app (Vite output). Run `npm --prefix frontend run build`.
if (_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


def _spa() -> Response:
    index = _DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("Frontend not built. Run: npm --prefix frontend install && "
                    "npm --prefix frontend run build", media_type="text/plain", status_code=503)


@app.get("/")
def index() -> Response:
    return _spa()


@app.get("/review")
def review_ui() -> Response:
    return _spa()


class CreateJobRequest(BaseModel):
    target_type: TargetType
    target_ref: str
    authorized: bool = False
    scope_allowlist: list[str] = []
    allow_active: bool = False
    created_by: str = "system"
    # Mobile: {app_path|app_ref, package, credentials:{username,password},
    #          login_steps:[...], device_profile}
    inputs: dict = {}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "report_matrix": settings.report_matrix}


@app.post("/jobs")
def create_job(req: CreateJobRequest, actor: dict = Depends(require_role("operator"))) -> dict:
    # ── Authorization gate (Part G / TECHNICAL_GUIDE §10) ──
    if req.target_type == TargetType.web:
        if not req.authorized:
            raise HTTPException(400, "Web scans require an authorization attestation "
                                     "that you own or are permitted to test the target.")
        if not req.scope_allowlist:
            raise HTTPException(400, "A scope allowlist is required — discovery is "
                                     "deny-by-default; we never touch a host that "
                                     "isn't explicitly in scope.")
    elif req.target_type in (TargetType.android, TargetType.ios):
        if not req.authorized:
            raise HTTPException(400, "Mobile scans require an attestation that you own "
                                     "or are permitted to test the application.")

    from .secrets_store import externalize
    job = Job(
        target_type=req.target_type,
        target_ref=req.target_ref,
        created_by=req.created_by,
        authorized=req.authorized,
        scope_allowlist=req.scope_allowlist,
        allow_active=req.allow_active and settings.allow_active_dns_bruteforce,
    )
    # Credentials/login steps go to the secret store; only a handle is persisted.
    job.inputs = externalize(job.job_id, req.inputs)
    db.save_job(job)

    db.add_audit(actor["actor"], "create_job", job.job_id,
                 f"{req.target_type.value} {req.target_ref}")

    # Production: enqueue to Celery. Dev/demo (no broker): run inline in a
    # background thread so the platform works out of the box.
    if settings.use_celery:
        try:
            from .worker import run_job
            run_job.delay(job.job_id)
        except Exception as exc:  # noqa: BLE001
            db.update_job(job.job_id, status="error", error_detail=f"enqueue failed: {exc}")
            raise HTTPException(503, f"Job queue unavailable: {exc}")
    else:
        import threading
        from . import pipeline
        threading.Thread(target=pipeline.run_job, args=(job.job_id,), daemon=True).start()

    return {"job_id": job.job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, actor: dict = Depends(require_role("viewer"))) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/jobs/{job_id}/reports")
def list_reports(job_id: str, actor: dict = Depends(require_role("viewer"))) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    keys = job.get("report_keys") or []
    return {"job_id": job_id, "reports": [{"key": k, "url": storage.url(k)} for k in keys]}


@app.get("/reports/{key:path}")
def download_report(key: str, actor: dict = Depends(require_role("viewer"))) -> Response:
    try:
        data = storage.get_bytes(key)
    except Exception:
        raise HTTPException(404, "report not found")
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if key.endswith(".docx") else
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
             if key.endswith(".xlsx") else
             "application/pdf" if key.endswith(".pdf") else "application/octet-stream")
    filename = key.rsplit("/", 1)[-1]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── Human-review workbench ───────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    sc_num: str
    verdict: str                          # pass | fail | partial | not_applicable
    rationale: str
    reviewer: str = "reviewer"
    at_technique: str | None = None       # e.g. "NVDA 2024.x", "VoiceOver iOS 17"


@app.get("/jobs/{job_id}/review-queue")
def review_queue(job_id: str, actor: dict = Depends(require_role("viewer"))) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    findings = db.load_findings(job_id)
    reviews = db.reviews_map(job_id)
    auto_clean = bool((job.get("report_meta") or {}).get("auto_clean", True))

    queue = []
    for c in wcag.registry()["criteria"]:
        rv = reviews.get(c["num"])
        verdict = Status(rv["verdict"]) if rv else None
        status, _ = wcag.derive_status(c, findings, verdict, auto_clean)
        fs = [f for f in findings if f.sc_num == c["num"]]
        queue.append({
            "sc_num": c["num"], "name": c["name"], "level": c["level"],
            "principle": c["principle"], "testability": c["testability"],
            "status": status.value, "needs_review": status.value == "needs_manual_review",
            "review": rv,
            "hints": [{"engine": f.engine, "rule": f.engine_rule_id,
                       "description": f.description, "screenshot_key": f.screenshot_key,
                       "url": storage.url(f.screenshot_key) if f.screenshot_key else None}
                      for f in fs[:5]],
        })
    open_count = sum(1 for q in queue if q["needs_review"])
    return {"job_id": job_id, "open_review": open_count, "queue": queue}


@app.post("/jobs/{job_id}/reviews")
def add_review(job_id: str, req: ReviewRequest,
               actor: dict = Depends(require_role("reviewer"))) -> dict:
    if db.get_job(job_id) is None:
        raise HTTPException(404, "job not found")
    if req.verdict not in ("pass", "fail", "partial", "not_applicable"):
        raise HTTPException(400, "verdict must be pass|fail|partial|not_applicable")
    if not req.rationale.strip():
        raise HTTPException(400, "a rationale is required — bulk/blank sign-off is "
                                 "not allowed (that would reintroduce fabrication).")
    try:
        wcag.criterion(req.sc_num)
    except StopIteration:
        raise HTTPException(400, f"unknown criterion {req.sc_num}")

    review = Review(job_id=job_id, sc_num=req.sc_num, reviewer=req.reviewer,
                    verdict=Status(req.verdict), rationale=req.rationale,
                    at_technique=req.at_technique)
    db.save_review(review)
    db.add_audit(actor["actor"], "review", f"{job_id}:{req.sc_num}",
                 f"{req.verdict} by {req.reviewer}")
    return {"ok": True, "review_id": review.review_id}


@app.get("/jobs/{job_id}/reviews")
def list_reviews(job_id: str, actor: dict = Depends(require_role("reviewer"))) -> dict:
    if db.get_job(job_id) is None:
        raise HTTPException(404, "job not found")
    return {"job_id": job_id, "reviews": db.get_reviews(job_id)}


@app.post("/jobs/{job_id}/rebuild-reports")
def rebuild_reports(job_id: str, actor: dict = Depends(require_role("reviewer"))) -> dict:
    if db.get_job(job_id) is None:
        raise HTTPException(404, "job not found")
    from . import pipeline
    pipeline.rebuild_reports(job_id)
    db.add_audit(actor["actor"], "rebuild_reports", job_id, "")
    return {"ok": True, "status": db.get_job(job_id)["status"]}


@app.get("/metrics")
def metrics(actor: dict = Depends(require_role("viewer"))) -> dict:
    return {"jobs_by_status": db.job_status_counts(),
            "report_matrix_size": len(settings.report_matrix)}


@app.get("/audit")
def audit_log(limit: int = 200, actor: dict = Depends(require_role("admin"))) -> dict:
    return {"audit": db.get_audit(limit)}
