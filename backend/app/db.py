"""SQLAlchemy persistence — mirrors the Pydantic canonical schema in models.py."""
from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings
from .models import Finding as PFinding
from .models import Job as PJob

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    step: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128), default="system")
    created_at: Mapped[str] = mapped_column(String(32), default="")
    authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    scope_allowlist: Mapped[Any] = mapped_column(JSON, default=list)
    allow_active: Mapped[bool] = mapped_column(Boolean, default=False)
    inputs: Mapped[Any] = mapped_column(JSON, default=dict)
    engine_versions: Mapped[Any] = mapped_column(JSON, default=dict)
    report_keys: Mapped[Any] = mapped_column(JSON, default=list)
    report_meta: Mapped[Any] = mapped_column(JSON, default=dict)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class FindingRow(Base):
    __tablename__ = "findings"
    finding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    sc_num: Mapped[str] = mapped_column(String(12), index=True)
    status: Mapped[str] = mapped_column(String(24))
    impact: Mapped[str] = mapped_column(String(16))
    engine: Mapped[str] = mapped_column(String(32))
    engine_rule_id: Mapped[str] = mapped_column(String(128))
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[Any] = mapped_column(JSON)   # full Finding.model_dump()


class EngineRunRow(Base):
    __tablename__ = "engine_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class ReviewRow(Base):
    __tablename__ = "reviews"
    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    sc_num: Mapped[str] = mapped_column(String(12), index=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    verdict: Mapped[str] = mapped_column(String(24))
    rationale: Mapped[str] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSON)


def init_db() -> None:
    Base.metadata.create_all(engine)


# ── Job helpers ──────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def save_job(job: PJob) -> None:
    with SessionLocal() as s:
        row = s.get(JobRow, job.job_id)
        data = job.model_dump()
        data["target_type"] = job.target_type.value
        if not data.get("created_at"):
            data["created_at"] = _now()
        if row is None:
            s.add(JobRow(**data))
        else:
            for k, v in data.items():
                setattr(row, k, v)
        s.commit()


def get_job(job_id: str) -> dict | None:
    with SessionLocal() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            return None
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def update_job(job_id: str, **fields: Any) -> None:
    with SessionLocal() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


# ── Finding helpers ──────────────────────────────────────────────────────────

def save_findings(findings: list[PFinding]) -> None:
    with SessionLocal() as s:
        for f in findings:
            s.merge(FindingRow(
                finding_id=f.finding_id, job_id=f.job_id, sc_num=f.sc_num,
                status=f.status.value, impact=f.impact.value, engine=f.engine,
                engine_rule_id=f.engine_rule_id, occurrences=f.occurrences,
                payload=f.model_dump(mode="json"),
            ))
        s.commit()


def get_findings(job_id: str) -> list[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(FindingRow).where(FindingRow.job_id == job_id)).all()
        return [r.payload for r in rows]


def load_findings(job_id: str):
    """Reconstruct canonical Finding objects (for report rebuild)."""
    from .models import Finding
    return [Finding(**p) for p in get_findings(job_id)]


# ── Review helpers ───────────────────────────────────────────────────────────

def save_review(review) -> None:
    """Persist a reviewer verdict. `review` is a models.Review."""
    with SessionLocal() as s:
        if not review.created_at:
            review.created_at = _now()
        s.merge(ReviewRow(
            review_id=review.review_id, job_id=review.job_id, sc_num=review.sc_num,
            reviewer=review.reviewer, verdict=review.verdict.value
            if hasattr(review.verdict, "value") else review.verdict,
            rationale=review.rationale, payload=review.model_dump(mode="json"),
        ))
        s.commit()


def get_reviews(job_id: str) -> list[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(ReviewRow).where(ReviewRow.job_id == job_id)).all()
        return [r.payload for r in rows]


def reviews_map(job_id: str) -> dict[str, dict]:
    """Latest review per criterion → {sc_num: {verdict, reviewer, at_technique, rationale}}."""
    latest: dict[str, dict] = {}
    for r in get_reviews(job_id):
        latest[r["sc_num"]] = r      # last write wins (rows ordered by insert)
    return latest


# ── Audit log + metrics ──────────────────────────────────────────────────────

def add_audit(actor: str, action: str, target: str = "", detail: str = "") -> None:
    with SessionLocal() as s:
        s.add(AuditRow(ts=_now(), actor=actor, action=action, target=target, detail=detail))
        s.commit()


def get_audit(limit: int = 200) -> list[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
        return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]


def job_status_counts() -> dict[str, int]:
    with SessionLocal() as s:
        rows = s.scalars(select(JobRow)).all()
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts
