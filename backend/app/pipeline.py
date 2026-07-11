"""Job orchestration. Same code path under Celery (prod) or called directly (dev).

Web flow:  discover → crawl → sample → scan (4 engines) → normalize/reconcile →
           evidence → persist → build 9 reports (docx+xlsx[+pdf]) → done.

Every step updates the job's `step` so the UI can show live progress. Any
exception marks the job `error` with a diagnostic — a half-built report never
ships as `done`.
"""
from __future__ import annotations

import datetime
import traceback
from pathlib import Path

from .config import settings
from . import db


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def run_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    try:
        if job["target_type"] == "web":
            _run_web(job)
        elif job["target_type"] == "android":
            _run_android(job)
        elif job["target_type"] == "ios":
            _run_ios(job)
        else:
            db.update_job(job_id, status="error",
                          error_detail=f"unknown target type {job['target_type']}")
    except Exception as exc:  # noqa: BLE001
        db.update_job(job_id, status="error", step="failed",
                      error_detail=f"{exc}\n{traceback.format_exc()[-1500:]}")
        raise
    finally:
        # Purge any vaulted credentials for this job — never retain secrets.
        try:
            from .secrets_store import store as _secret_store
            _secret_store().purge(job_id)
        except Exception:
            pass


def _run_web(job: dict) -> None:
    job_id = job["job_id"]
    import os
    from .scanners.web import subdomains, crawler, sampling, engines, evidence, normalize, authsession
    from .secrets_store import resolve as resolve_secret

    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ── 1) OSINT discovery ──
    db.update_job(job_id, status="running", step="discovering subdomains (OSINT)")
    disc = subdomains.discover(job["target_ref"], job.get("scope_allowlist") or [],
                               allow_active=job.get("allow_active", False))
    live = disc["live"]
    if not live:
        db.update_job(job_id, status="error",
                      error_detail="No live, in-scope hosts. Check the domain and "
                                   "that the scope allowlist includes it.")
        return

    # ── Optional authenticated session (vaulted credentials) ──
    storage_state = None
    creds = resolve_secret(job.get("inputs") or {})
    if creds:
        login_url = (job.get("inputs") or {}).get("login_url") or live[0]
        state_path = settings.artifacts_dir / job_id / "state.json"
        storage_state = authsession.login_and_capture(
            login_url, creds.get("login_steps"), creds.get("credentials"), state_path)
        if storage_state:
            os.environ["A11Y_STORAGE_STATE"] = storage_state
            db.update_job(job_id, step="authenticated session established")

    # ── 2) Crawl each live host, then template-sample ──
    db.update_job(job_id, step=f"crawling {len(live)} host(s)")
    all_urls: list[str] = []
    for host in live:
        all_urls.extend(crawler.crawl(host))
    sample = sampling.cluster_and_sample(all_urls)
    sampled = sample["sampled"] or all_urls[: settings.max_pages_per_host]

    # ── 3) Scan every sampled page with all engines ──
    db.update_job(job_id, step=f"scanning {len(sampled)} page(s) with "
                               f"{len(settings.web_engines)} engines")
    raw_findings = []
    engine_runs = []
    from .storage import storage
    for i, url in enumerate(sampled, 1):
        raw, runs = engines.scan_url(url)
        engine_runs.extend(runs)
        # keep raw engine payloads for traceability
        try:
            import json
            storage.put_bytes(f"{job_id}/raw/{i:04d}.json",
                              json.dumps({"url": url, "raw": raw}, default=str).encode(),
                              "application/json")
        except Exception:
            pass
        raw_findings.extend(normalize.normalize_page(job_id, url, raw))
        db.update_job(job_id, step=f"scanned {i}/{len(sampled)} pages")

    findings = normalize.finalize(raw_findings)

    # ── 4) Evidence screenshots for confirmed fails ──
    db.update_job(job_id, step=f"capturing evidence for {sum(1 for f in findings if f.status.value=='fail')} findings")
    findings = evidence.capture_for_findings(job_id, findings, storage_state=storage_state)
    os.environ.pop("A11Y_STORAGE_STATE", None)   # don't leak across jobs
    db.save_findings(findings)

    # ── fail-closed gate: any engine error anywhere → auto criteria can't Pass ──
    ran = [r for r in engine_runs]
    any_error = any(r.status.value == "error" for r in ran)
    any_clean = any(r.status.value in ("clean", "violations") for r in ran)
    auto_clean = any_clean and not any_error

    engines_summary = {}
    for r in ran:
        engines_summary.setdefault(r.engine, {"clean": 0, "violations": 0, "error": 0})
        engines_summary[r.engine][r.status.value] += 1

    meta = {
        "target_ref": job["target_ref"],
        "target_type": "web",
        "scan_date": _now(),
        "auditor_org": "Accessibility Compliance Audit Platform",
        "discovery": disc["sources"],
        "hosts_live": live,
        "hosts_out_of_scope": disc.get("out_of_scope", []),
        "pages_crawled": len(all_urls),
        "pages_scanned": len(sampled),
        "templates": sample["total_templates"],
        "sampling": sample["templates"],
        "engines": engines_summary,
        "auto_clean": auto_clean,
        "unmapped_rules": dict(list(normalize.unmapped_rules.items())[:50]),
        "tool_versions": _tool_versions(),
    }

    # ── 5) Build the report matrix ──
    db.update_job(job_id, status="building", step="building reports")
    report_keys = _build_reports(job_id, findings, meta, auto_clean,
                                 reviews=db.reviews_map(job_id))
    db.update_job(job_id, status="done", step="complete", report_keys=report_keys,
                  engine_versions=meta["tool_versions"])


def rebuild_reports(job_id: str) -> None:
    """Regenerate the report matrix incorporating human-review verdicts.
    Called after a reviewer signs off criteria — this is what turns an automated
    partial scan into a defensible audit."""
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    meta = job.get("report_meta") or {}
    if not meta:
        db.update_job(job_id, status="error",
                      error_detail="No persisted scan metadata to rebuild from — "
                                   "re-run the scan first.")
        return
    findings = db.load_findings(job_id)
    reviews = db.reviews_map(job_id)
    auto_clean = bool(meta.get("auto_clean", True))
    db.update_job(job_id, status="building", step="rebuilding reports with review verdicts")
    report_keys = _build_reports(job_id, findings, meta, auto_clean, reviews=reviews)
    db.update_job(job_id, status="done", step="complete (with review)",
                  report_keys=report_keys)


def _run_android(job: dict) -> None:
    job_id = job["job_id"]
    from .scanners.android import emulator, atf, normalize as anorm
    from .scanners.android.emulator import EmulatorUnavailable
    from .scanners.android.atf import AtfUnavailable
    from .reporting import common, docx_report, xlsx_report, pdf

    inp = job.get("inputs") or {}
    package = inp.get("package") or job["target_ref"]
    app_path = inp.get("app_path")
    max_screens = int(inp.get("max_screens") or settings.android_max_screens)
    work = settings.artifacts_dir / job_id / "android"
    work.mkdir(parents=True, exist_ok=True)

    # ── 1) Boot emulator + install target ──
    db.update_job(job_id, status="running", step="booting Android emulator (WHPX/KVM)")
    try:
        emulator.ensure_avd(settings.android_avd_name, settings.android_system_image)
        emulator.boot(settings.android_avd_name, headless=True)
        if app_path:
            db.update_job(job_id, step="installing target app")
            emulator.install(app_path)
    except EmulatorUnavailable as exc:
        db.update_job(job_id, status="error",
                      error_detail=f"Android emulator host unavailable: {exc} "
                                   "Run on a WHPX (Windows) or KVM (Linux) host with "
                                   "the Android SDK installed.")
        return

    # ── 2) Run the real ATF audit (harness) across screens ──
    db.update_job(job_id, step=f"auditing up to {max_screens} screens with Google ATF")
    try:
        screens = atf.run_audit(package, max_screens, work)
    except AtfUnavailable as exc:
        db.update_job(job_id, status="error",
                      error_detail=f"ATF audit could not run: {exc}")
        emulator.shutdown()
        return

    findings = anorm.screens_to_findings(job_id, screens)
    db.save_findings(findings)
    emulator.shutdown()

    # Mobile: auto criteria are NOT auto-passed (WCAG auto criteria are web-shaped
    # and ATF mappings are informative). Everything ATF didn't flag -> Needs Manual
    # Review (recommend a TalkBack pass). This is the honest, defensible stance.
    auto_clean = False

    err_screens = sum(1 for s in screens if any(r.get("type") == "ERROR" for r in s.get("results", [])))
    meta = {
        "target_ref": package, "target_type": "android",
        "scan_date": _now(),
        "auditor_org": "Accessibility Compliance Audit Platform",
        "discovery": {}, "hosts_live": [], "hosts_out_of_scope": [],
        "pages_crawled": len(screens), "pages_scanned": len(screens),
        "templates": len(screens), "sampling": {},
        "engines": {"android-atf": {"clean": 0, "violations": err_screens,
                                    "error": 0}},
        "auto_clean": auto_clean,
        "unmapped_rules": dict(list(anorm.webnorm.unmapped_rules.items())[:50]),
        "tool_versions": {"android-atf": "via espresso-accessibility (see VERSIONS.lock)",
                          "emulator": "WHPX/KVM"},
        "note_mobile": "Automated coverage on native apps is limited (ATF static checks). "
                       "Screen-reader behaviour (TalkBack) requires manual review.",
    }

    db.update_job(job_id, status="building", step="building reports")
    report_keys = _build_reports(job_id, findings, meta, auto_clean,
                                 reviews=db.reviews_map(job_id))
    db.update_job(job_id, status="done", step="complete", report_keys=report_keys,
                  engine_versions=meta["tool_versions"])


def _build_reports(job_id: str, findings: list, meta: dict, auto_clean: bool,
                   reviews: dict | None = None) -> list[str]:
    """Shared: build the full report matrix (docx+xlsx+ACR[+pdf]) and upload.
    Persists `meta` so the reports can be rebuilt after human review."""
    from .reporting import common, docx_report, xlsx_report, pdf, acr
    from .storage import storage

    db.update_job(job_id, report_meta=meta)
    reports_dir = settings.artifacts_dir / job_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_keys: list[str] = []
    for version, level in settings.report_matrix:
        combo = common.build_combo(version, level, findings, reviews=reviews or {},
                                   auto_clean=auto_clean)
        base = f"WCAG_{version}_{level}"
        docx_path = reports_dir / f"{base}.docx"
        xlsx_path = reports_dir / f"{base}.xlsx"
        acr_path = reports_dir / f"{base}_ACR.docx"
        docx_report.build_docx(combo, meta, str(docx_path))
        xlsx_report.build_xlsx(combo, meta, str(xlsx_path))
        acr.generate_acr(combo, meta, str(acr_path))
        _docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        outputs = [
            (docx_path, _docx),
            (xlsx_path, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            (acr_path, _docx),
        ]
        pdf_path = pdf.to_pdf(str(docx_path), str(reports_dir))
        if pdf_path:
            outputs.append((Path(pdf_path), "application/pdf"))
        for path, ctype in outputs:
            key = f"{job_id}/reports/{path.name}"
            storage.put_file(key, path, ctype)
            report_keys.append(key)
        db.update_job(job_id, step=f"built {base}")
    return report_keys


def _run_ios(job: dict) -> None:
    job_id = job["job_id"]
    from .scanners.ios import simulator, driver as idriver, audit as iaudit, normalize as inorm
    from .scanners.ios.simulator import SimulatorUnavailable
    from .scanners.ios.driver import DriverUnavailable

    inp = job.get("inputs") or {}
    app_path = inp.get("app_path")
    bundle_id = inp.get("bundle_id") or job["target_ref"]
    max_screens = int(inp.get("max_screens") or settings.ios_max_screens)

    # ── macOS / Xcode guard ──
    if not simulator.available():
        db.update_job(job_id, status="error",
                      error_detail="iOS auditing requires a macOS worker with Xcode "
                                   "(Apple SLA — Simulators don't run on Windows/Linux). "
                                   "Route iOS jobs to a Mac (EC2 Mac / MacStadium / "
                                   "Mac mini / GitHub macos runner).")
        return

    db.update_job(job_id, status="running", step="booting iOS Simulator")
    try:
        udid = simulator.boot(settings.ios_simulator_device)
        if app_path:
            simulator.install(udid, app_path)
    except SimulatorUnavailable as exc:
        db.update_job(job_id, status="error", error_detail=f"iOS simulator: {exc}")
        return

    db.update_job(job_id, step=f"auditing up to {max_screens} screens "
                               "(XCUITest performAccessibilityAudit)")
    try:
        drv = idriver.start_session(app_path, bundle_id, udid)
    except DriverUnavailable as exc:
        db.update_job(job_id, status="error", error_detail=f"Appium XCUITest: {exc}")
        simulator.shutdown(udid)
        return

    try:
        screens = idriver.crawl(drv, max_screens,
                                on_screen=lambda cap: iaudit.run_for_current(drv))
    finally:
        idriver.quit(drv)
        simulator.shutdown(udid)

    findings = inorm.screens_to_findings(job_id, screens)
    db.save_findings(findings)

    any_error = any((s.get("audit") or {}).get("status") == "error" for s in screens)
    any_ran = any((s.get("audit") or {}).get("status") in ("clean", "violations") for s in screens)
    viol = sum(len((s.get("audit") or {}).get("issues", [])) for s in screens)
    meta = {
        "target_ref": bundle_id, "target_type": "ios", "scan_date": _now(),
        "auditor_org": "Accessibility Compliance Audit Platform",
        "discovery": {}, "hosts_live": [], "hosts_out_of_scope": [],
        "pages_crawled": len(screens), "pages_scanned": len(screens),
        "templates": len(screens), "sampling": {},
        "engines": {"ios-xcuitest": {"clean": 1 if any_ran and not viol else 0,
                                     "violations": viol,
                                     "error": 1 if any_error else 0}},
        "auto_clean": False,   # mobile: no auto-Pass; VoiceOver behaviour is manual
        "unmapped_rules": dict(list(inorm.webnorm.unmapped_rules.items())[:50]),
        "tool_versions": {"ios-xcuitest": "performAccessibilityAudit (iOS17+/Xcode15+)",
                          "simulator": "xcrun simctl"},
        "note_mobile": "iOS automated coverage is limited to Apple's 7 audit types. "
                       "VoiceOver rotor/gesture behaviour requires manual review.",
    }

    db.update_job(job_id, status="building", step="building reports")
    report_keys = _build_reports(job_id, findings, meta, auto_clean=False)
    db.update_job(job_id, status="done", step="complete", report_keys=report_keys,
                  engine_versions=meta["tool_versions"])


def _tool_versions() -> dict:
    from .scanners.web import toolrunner
    out = {}
    for t in ("subfinder", "httpx", "katana"):
        out[t] = toolrunner.tool_version(t)
    node = toolrunner.node_bin()
    out["node"] = "installed" if node else "not-installed"
    # Node engine versions come from js/package.json pins.
    return out
