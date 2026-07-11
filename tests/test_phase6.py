"""Phase 6: secrets, RBAC, audit, ACR export, PII redaction, retention."""
import time

import pytest

from backend.app import secrets_store as ss
from backend.app import auth
from backend.app.config import settings
from backend.app.models import Status
from backend.app.reporting import acr, common
from backend.app.scanners import redact


# ── Secrets ──────────────────────────────────────────────────────────────────

def test_secret_externalize_hides_and_resolves_and_purges():
    inputs = {"package": "com.x",
              "credentials": {"username": "u", "password": "p"},
              "login_steps": [{"action": "tap"}]}
    clean = ss.externalize("jobP6", inputs)
    assert "credentials" not in clean and "login_steps" not in clean
    assert clean["package"] == "com.x" and "secret_handle" in clean
    resolved = ss.resolve(clean)
    assert resolved["credentials"]["username"] == "u"
    ss.store().purge("jobP6")
    assert ss.resolve(clean) == {}        # purged


# ── RBAC ─────────────────────────────────────────────────────────────────────

def test_role_hierarchy():
    assert auth.ROLE_LEVEL["admin"] > auth.ROLE_LEVEL["operator"] \
        > auth.ROLE_LEVEL["reviewer"] > auth.ROLE_LEVEL["viewer"]


def test_auth_disabled_is_admin():
    assert auth.resolve_role(None) == "admin"


def test_rbac_via_api():
    from fastapi.testclient import TestClient
    from backend.app.main import app

    settings.auth_enabled = True
    settings.api_keys = {"k-view": "viewer", "k-op": "operator"}
    try:
        with TestClient(app) as c:
            assert c.get("/health").status_code == 200          # open
            assert c.get("/metrics").status_code == 401         # no key
            assert c.get("/metrics", headers={"X-API-Key": "k-view"}).status_code == 200
            # viewer cannot create a job (needs operator) -> 403 before any work
            r = c.post("/jobs", json={"target_type": "web", "target_ref": "https://x",
                                      "authorized": True, "scope_allowlist": ["x"]},
                       headers={"X-API-Key": "k-view"})
            assert r.status_code == 403
            # audit requires admin
            assert c.get("/audit", headers={"X-API-Key": "k-op"}).status_code == 403
    finally:
        settings.auth_enabled = False
        settings.api_keys = {}


# ── ACR export ───────────────────────────────────────────────────────────────

def test_acr_term_mapping():
    assert acr.acr_term(Status.pass_) == "Supports"
    assert acr.acr_term(Status.partial) == "Partially Supports"
    assert acr.acr_term(Status.fail) == "Does Not Support"
    assert acr.acr_term(Status.not_applicable) == "Not Applicable"
    assert acr.acr_term(Status.needs_manual_review) == "Not Evaluated"   # never silent Supports


def test_acr_generates_docx(finding_factory, tmp_path):
    combo = common.build_combo("2.2", "AA", [finding_factory("1.4.3", Status.fail)],
                               auto_clean=True)
    out = tmp_path / "acr.docx"
    acr.generate_acr(combo, {"target_ref": "https://ex.com",
                             "scan_date": "2026-07-12T00:00:00+00:00",
                             "auditor_org": "Test"}, str(out))
    assert out.exists() and out.stat().st_size > 4000
    from docx import Document
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "Accessibility Conformance Report" in text
    assert "Not Evaluated" in text


# ── PII redaction ────────────────────────────────────────────────────────────

def test_redact_text_masks_pii():
    s = redact.redact_text("email a@b.com card 4111 1111 1111 1111 token=abc123 id 12345678")
    assert "a@b.com" not in s and "[redacted-email]" in s
    assert "4111" not in s
    assert "12345678" not in s


def test_redact_image_blacks_box():
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 100), "#ffffff")
    buf = io.BytesIO(); img.save(buf, "PNG")
    out = redact.redact_image(buf.getvalue(), [{"left": 10, "top": 10, "right": 40, "bottom": 40}])
    masked = Image.open(io.BytesIO(out))
    assert masked.getpixel((25, 25)) == (0, 0, 0)     # box blacked out
    assert masked.getpixel((90, 90)) == (255, 255, 255)


# ── Retention ────────────────────────────────────────────────────────────────

def test_retention_purges_old_dirs(tmp_path, monkeypatch):
    from backend.app import retention
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    old = tmp_path / "oldjob"; old.mkdir()
    (old / "f.txt").write_text("x")
    import os
    old_time = time.time() - 40 * 86400
    os.utime(old, (old_time, old_time))
    keep = tmp_path / "demo"; keep.mkdir()
    result = retention.purge_expired(days=30)
    assert "oldjob" in result["removed"]
    assert not old.exists() and keep.exists()   # demo is preserved
