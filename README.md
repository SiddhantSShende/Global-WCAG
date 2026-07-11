# Accessibility Compliance Audit Platform

Enterprise-grade, evidence-backed **WCAG 2.0 / 2.1 / 2.2** auditing for **Websites, Android apps, and iOS apps**, producing detailed `.docx` + `.xlsx` (+ `.pdf`) reports with **real screenshot evidence** and **zero fabricated data**.

> **The accuracy contract.** The platform emits **`Pass`** for a criterion only when **(a)** the criterion is machine-`auto`-decidable *and* every engine returned clean with no error/timeout, **or (b)** a qualified human reviewer signed off. Everything else is **`Needs Manual Review`** — never a silent Pass. This is enforced in code (`backend/app/wcag.py:derive_status` + `backend/app/reporting/common.py:validate`), and a **contradiction validator aborts the build** if any report row would violate it.

See the design docs in **`MD files/`** (`TECHNICAL_GUIDE.md`, `IMPLEMENTATION_PLAYBOOK.md`) and the consolidated build plan in `~/.claude/plans/`.

---

## What it does

1. User picks a **target type**: `web` (built), `android` (built — needs an emulator host), `ios` (built — runs on a macOS worker).
2. Provides inputs (for web: a domain + an ownership/authorization attestation).
3. The pipeline runs: **OSINT discovery → crawl → multi-engine scan → screenshot evidence → normalize/reconcile → report build**.
4. User downloads the report matrix — for each `(version, level)`, a `.docx` **and** `.xlsx`:

   | WCAG 2.0 | WCAG 2.1 | WCAG 2.2 |
   |---|---|---|
   | A · (AA) · AAA | A · (AA) · AAA | A · (AA) · AAA |

   Your headline request is the **6** A & AAA reports; because AAA is cumulative (A+AA+AAA) the platform also computes the **3 AA cuts** (9 combos total — a one-line `REPORT_MATRIX` change). AA is the legally operative level (Section 508, EN 301 549, ADA Title II, EAA).

## Open-source engines & OSINT tools (cloned/vendored)

All third-party tools are cloned into `third_party/` by `scripts/setup_tools.sh`, pinned and version-stamped into `third_party/VERSIONS.lock` (which is stamped into every report's methodology). We drive the **real upstream tools** — nothing is reimplemented or faked.

- **Accessibility engines:** axe-core (Deque), Pa11y + HTML_CodeSniffer (AAA), Lighthouse, IBM Equal Access. **All four are integration-verified end-to-end** against a fixture page — they run, map to WCAG criteria, reconcile across engines, and produce the reports (see "Verifying the engines" below). Lighthouse needs a discoverable Chrome/Chromium (`CHROME_PATH`); the tools image installs it.
- **OSINT / recon:** subfinder, httpx, katana, urlfinder (ProjectDiscovery), optional amass (OWASP); SSLMate Cert Spotter + crt.sh certificate-transparency logs.
- **Mobile:** Google Accessibility Test Framework (Android — wired via the black-box `UiAutomation`→ATF harness in `android_atf_harness/`); Apple XCUITest `performAccessibilityAudit` (iOS — driven via Appium on a macOS worker); Appium for navigation. iOS jobs run on Apple hardware (EC2 Mac / MacStadium / Mac mini / GitHub macos runner) — architected as a network-attached worker; nothing about iOS is faked on non-macOS hosts.

---

## Architecture (three isolation planes)

```
Frontend (wizard)  ──REST/WS──►  FastAPI (intake · auth gate · status · downloads)
                                       │ enqueue
                                       ▼
                              Celery + Redis/Valkey  ◄──►  PostgreSQL (jobs, findings)
                                       │
        ┌──────────────────────────────┼───────────────────────────────┐
        ▼ Plane A (WSL2/Linux)          ▼ Plane B (Windows host, WHPX)   ▼ Plane C (macOS, deferred)
  Web: OSINT → crawl → axe/pa11y/    Android: AVD + Appium (nav) +    iOS: Simulator + Appium
       lighthouse/IBM → evidence     Espresso+ATF (audit)             XCUITest performAccessibilityAudit
        └───────────── canonical Finding schema ─────────────┘
                                       ▼
                          Object store (S3/MinIO/Garage): raw engine JSON,
                          screenshots, generated reports
```

- **Plane A** (this repo's built pipeline) runs entirely in **WSL2 Ubuntu / Docker Compose**.
- **Plane B** (Android) runs the emulator on the **native Windows host** (WHPX), driven over adb/HTTP.
- **Plane C** (iOS) is **architected but deferred** — iOS Simulators run only on macOS (Apple SLA). Wire a cloud Mac when ready; nothing about iOS is faked.

---

## Quickstart (WSL2 Ubuntu 24.04 — recommended)

```bash
# 0) One-time host prep in Windows PowerShell (Admin), then reboot:
#    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux,VirtualMachinePlatform,HypervisorPlatform -All
#    wsl --install -d Ubuntu-24.04 ; wsl --update
#    (full details: scripts/setup_wsl.md)

# 1) Clone into the WSL2 ext4 home (NOT /mnt/c — 10x filesystem penalty):
cd ~ && git clone <this-repo> wcag && cd wcag

# 2) Vendor the open-source tools (clones + pins + builds into third_party/):
bash scripts/setup_tools.sh

# 3) Python env + browser:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

# 4) Build the WCAG registry (facts ingested from W3C + our testability enrichment):
python wcag_data/ingest_wcag.py && python wcag_data/enrich_testability.py

# 5) Build the React (Vite) frontend — FastAPI serves it from frontend/dist:
npm --prefix frontend install && npm --prefix frontend run build

# 6) Bring up services (Postgres, Valkey, MinIO) and the API + worker:
cp .env.example .env
docker compose -f docker/docker-compose.yml up -d
uvicorn backend.app.main:app --reload            # API + UI at http://localhost:8000
celery -A backend.app.worker.celery_app worker -l info   # worker (separate shell)

# Frontend dev server (hot reload, proxies the API to :8000):
#   npm --prefix frontend run dev      # http://localhost:5173

# 6) Submit a web audit you are authorized to run:
curl -X POST localhost:8000/jobs \
  -H 'content-type: application/json' \
  -d '{"target_type":"web","target_ref":"https://example.com","authorized":true,"scope_allowlist":["example.com"]}'
```

### Run a scan without the full stack (dev)
`python scripts/run_local_scan.py https://example.com` runs discovery → crawl → scan → reports against a local artifacts dir, using whatever vendored tools are present (degrades honestly to `Needs Manual Review` when a tool is missing).

### Verifying the engines
```bash
# serve a deliberately-broken fixture, then scan it with all four engines:
python -m http.server 8099 --directory artifacts/testsite &
python scripts/run_local_scan.py http://127.0.0.1:8099 --allow 127.0.0.1:8099
```
A real run against the fixture yields all four engines reporting, ~24 reconciled
findings (incl. cross-engine agreement raising confidence), embedded highlighted
screenshots, and the full 9×(docx+xlsx+ACR) matrix — with unproven criteria
honestly marked "Needs Manual Review".

---

## Repo layout

```
wcag_data/      ingest_wcag.py · enrich_testability.py · wcag_criteria.json · rule_maps/
backend/app/    config · models · wcag (derive_status) · db · storage · worker · main (API)
  scanners/web/ subdomains · crawler · sampling · engines · evidence · normalize · js/ (node runners)
  reporting/    common (scope+validator) · remediation_kb · docx_report · xlsx_report · pdf · templates/
frontend/       React (Vite) SPA — TopBar · AuditWizard · ReviewWorkbench · design system (src/styles.css)
docker/         docker-compose.yml · Dockerfile.api (multi-stage: builds UI) · Dockerfile.tools
scripts/        setup_tools.sh · setup_wsl.md · run_local_scan.py · demo_report.py
tests/          derive_status · validator · registry counts · normalizers · phase6 (RBAC/secrets/ACR)
third_party/    (populated by setup_tools.sh; git-ignored) + VERSIONS.lock
```

## Legal & safety (enforced from day one)

Every job requires an **authorization attestation** and an explicit **in-scope allowlist**; discovery is **passive by default** and **deny-by-default** — a discovered host is never touched unless it is on the validated allowlist. See `MD files/TECHNICAL_GUIDE.md §10` and the plan's Part G.

## License

Application code: choose your license. Vendored tools retain their own licenses (see `third_party/VERSIONS.lock`); note **MPL-2.0** (axe-core), **LGPL-3.0** (Pa11y), **Apache-2.0** (Lighthouse, amass, ATF, Appium), **BSD-3** (HTML_CodeSniffer), **MIT** (ProjectDiscovery tools). Review AGPL exposure if you swap in MinIO/Redis (prefer Valkey + a maintained S3 store).
#   G l o b a l - W C A G  
 