# Accessibility Compliance Audit Platform — Complete Phased Implementation Playbook

**Companion to:** `TECHNICAL_GUIDE.md` (architecture & rationale)
**Purpose:** A step-by-step, code-level build plan covering every phase from empty repo to production. Each phase has: goal, prerequisites, task-by-task implementation with real code, definition of done, tests, and pitfalls.

> **Ground rule carried through every phase:** the platform never emits `Pass` for a criterion it did not actually verify. Unverifiable criteria are `needs_manual_review`. This is enforced in code (Phase 0 `derive_status`, Phase 1 contradiction validator) and is the reason the reports are legitimate.

---

## Table of contents

- [How to use this document](#how-to-use-this-document)
- [Global prerequisites](#global-prerequisites)
- [Phase 0 — Foundations](#phase-0--foundations)
- [Phase 1 — Web MVP (single engine, end-to-end report)](#phase-1--web-mvp)
- [Phase 2 — Multi-engine + screenshot evidence](#phase-2--multi-engine--screenshot-evidence)
- [Phase 3 — Human-review workbench](#phase-3--human-review-workbench)
- [Phase 4 — Android scanning](#phase-4--android-scanning)
- [Phase 5 — iOS scanning (macOS node)](#phase-5--ios-scanning-macos-node)
- [Phase 6 — Scale, security & polish](#phase-6--scale-security--polish)
- [Cross-cutting: testing, CI/CD, observability](#cross-cutting-concerns)
- [Appendix A — rule→criterion map format](#appendix-a--rulecriterion-map-format)
- [Appendix B — acceptance checklist per phase](#appendix-b--acceptance-checklists)

---

## How to use this document

Work the phases **in order**. Phase 1 alone produces shippable, legitimate web reports; each later phase adds coverage or a target type without rewriting earlier work, because everything talks through the **canonical Findings schema** (Phase 0). Estimated effort assumes a small team (2–3 engineers); treat them as relative, not contractual.

| Phase | Outcome | Rough effort |
|---|---|---|
| 0 | Repo, WCAG registry, data models, DB, queue, storage skeleton | 1–2 weeks |
| 1 | Web scan → 6 reports (docx+xlsx), single engine (axe), validator | 2–3 weeks |
| 2 | 4 engines + highlighted screenshots + reconciliation | 2–3 weeks |
| 3 | Human-review workbench that closes `needs_manual_review` rows | 2–4 weeks |
| 4 | Android app scanning (AVD + Appium + Google ATF) | 3–4 weeks |
| 5 | iOS app scanning (macOS node + XCUITest audits) | 3–4 weeks |
| 6 | Warm pools, auth scanning, PII redaction, PDF, hardening | ongoing |

---

## Global prerequisites

**Developer machines / CI runners**
- Linux (Ubuntu 22.04+) for API + web + Android workers. `/dev/kvm` required on the Android host.
- **A macOS machine** (Mac mini, EC2 Mac, or MacStadium) for Phase 5. Non-negotiable — iOS simulators do not run on Linux.
- Python 3.11+, Node 18+, Go 1.21+, Docker + Docker Compose.

**Runtime services**
- PostgreSQL 15+, Redis 7+, S3-compatible object store (MinIO locally, S3 in prod).

**One-time tool install** (see `TECHNICAL_GUIDE.md §12` for the full list):
```bash
# recon
go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install github.com/projectdiscovery/httpx/cmd/httpx@latest
go install github.com/projectdiscovery/katana/cmd/katana@latest
go install github.com/owasp-amass/amass/v4/...@master
# web a11y engines
npm i -g pa11y lighthouse
npm i @axe-core/playwright axe-core accessibility-checker
# browser automation
pip install playwright && playwright install --with-deps chromium
# python backend
pip install fastapi uvicorn "celery[redis]" redis sqlalchemy psycopg2-binary \
            python-docx openpyxl pillow boto3 pydantic pydantic-settings hvac httpx
```

---

## Phase 0 — Foundations

**Goal:** a running skeleton — repo layout, the WCAG registry as source of truth, the canonical data models, config, DB schema, object storage, and a queue that can accept and dispatch a no-op job. No scanning yet.

### 0.1 Repository layout
Create the tree from `TECHNICAL_GUIDE.md §13`. Initialize git, add `.gitignore` (venv, `__pycache__`, `.env`, `*.docx`, `*.xlsx`, `node_modules`, `frontend/dist`).

### 0.2 Build the WCAG registry (already done)
`wcag_data/build_wcag_json.py` emits `wcag_criteria.json` (87 SC, each tagged `level`, `versions`, `testability`). Run it in CI so the JSON is never hand-edited:
```bash
python wcag_data/build_wcag_json.py   # regenerates + prints the scope matrix
```
Commit both the builder and the generated JSON. **The JSON is read-only at runtime.**

### 0.3 Config (`backend/app/config.py`)
```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://a11y:a11y@localhost:5432/a11y"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "a11y-artifacts"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    vault_addr: str | None = None

    wcag_json: Path = Path(__file__).parents[2] / "wcag_data" / "wcag_criteria.json"

    # The 6 report combinations. Add ("2.x","AA") tuples to expose AA cuts.
    report_matrix: list[tuple[str, str]] = [
        ("2.0", "A"), ("2.0", "AAA"),
        ("2.1", "A"), ("2.1", "AAA"),
        ("2.2", "A"), ("2.2", "AAA"),
    ]
    max_pages_per_host: int = 100
    crawl_max_depth: int = 3

    class Config:
        env_file = ".env"

settings = Settings()
```

### 0.4 Canonical models (`backend/app/models.py`)
Two layers: Pydantic (validation/serialization) + SQLAlchemy (persistence). Pydantic shown; mirror the fields in a SQLAlchemy `Finding` table with a JSONB `computed`/`locations`.
```python
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field
import uuid

class TargetType(str, Enum):
    web = "web"; android = "android"; ios = "ios"

class Status(str, Enum):
    fail = "fail"; partial = "partial"
    needs_manual_review = "needs_manual_review"
    pass_ = "pass"; not_applicable = "not_applicable"

class Impact(str, Enum):
    blocker = "blocker"; serious = "serious"
    moderate = "moderate"; minor = "minor"

class Confidence(str, Enum):
    high = "high"; medium = "medium"; low = "low"

class Location(BaseModel):
    ref: str            # url or screen id
    count: int = 1

class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    target_type: TargetType
    # WCAG mapping
    sc_num: str
    sc_name: str
    level: str
    principle: str
    wcag_versions: list[str]
    # verdict
    status: Status
    confidence: Confidence
    auto_decidable: bool
    # provenance
    engine: str
    engine_rule_id: str
    impact: Impact
    # evidence
    selector: str | None = None
    html_snippet: str | None = None
    computed: dict = {}
    screenshot_key: str | None = None
    page_screenshot_key: str | None = None
    occurrences: int = 1
    locations: list[Location] = []
    description: str = ""
    remediation: str = ""
    raw_engine_payload_key: str | None = None

class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_type: TargetType
    target_ref: str
    status: str = "queued"        # queued|running|review|building|done|error
    created_by: str
    engine_versions: dict = {}
    authorized: bool = False       # legal attestation (web)
```

### 0.5 WCAG service (`backend/app/wcag.py`) — the ONE place status is decided
```python
import json
from functools import lru_cache
from .config import settings
from .models import Finding, Status, Confidence

@lru_cache
def registry() -> dict:
    return json.loads(settings.wcag_json.read_text())

def _level_scope(level: str) -> set[str]:
    return {"A": {"A"}, "AA": {"A", "AA"}, "AAA": {"A", "AA", "AAA"}}[level]

def criteria_in_scope(version: str, level: str) -> list[dict]:
    lv = _level_scope(level)
    return [c for c in registry()["criteria"]
            if version in c["versions"] and c["level"] in lv]

def criterion(sc_num: str) -> dict:
    return next(c for c in registry()["criteria"] if c["num"] == sc_num)

def derive_status(crit: dict,
                  findings: list[Finding],
                  reviewer_verdict: Status | None = None) -> tuple[Status, Confidence]:
    """The single source of truth for a criterion's row status.
    ANTI-FABRICATION: never returns `pass` for a non-`auto` criterion
    unless a human reviewer signed off."""
    mine = [f for f in findings if f.sc_num == crit["num"]]
    fails = [f for f in mine if f.status == Status.fail]
    if fails:
        return Status.fail, Confidence.high
    if reviewer_verdict is not None:
        return reviewer_verdict, Confidence.high
    if crit["testability"] == "auto":
        # auto criterion, no violations found -> a clean scan IS evidence
        return Status.pass_, Confidence.high
    # semi / manual with no confirmed violation -> we simply don't know
    return Status.needs_manual_review, Confidence.low
```

### 0.6 Storage + queue skeleton
- Object storage helper (`storage.py`) wrapping boto3 `put_object`/`get_object` against MinIO/S3.
- Celery app (`worker.py`) with a `run_job(job_id)` task that, for now, just marks the job `done`. Wire Redis as broker/result backend.
- `docker/docker-compose.yml` brings up Postgres, Redis, MinIO for local dev.

### 0.7 Minimal API (`backend/app/main.py`)
```python
from fastapi import FastAPI, HTTPException
from .models import Job, TargetType
from .worker import run_job
from . import db   # your SQLAlchemy session/helpers

app = FastAPI(title="A11y Audit Platform")

@app.post("/jobs")
def create_job(target_type: TargetType, target_ref: str,
               authorized: bool = False, user: str = "system"):
    if target_type == TargetType.web and not authorized:
        raise HTTPException(400, "Web scans require an authorization attestation.")
    job = Job(target_type=target_type, target_ref=target_ref,
              created_by=user, authorized=authorized)
    db.save_job(job)
    run_job.delay(job.job_id)     # async
    return {"job_id": job.job_id}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return db.get_job(job_id)
```

**Definition of done (Phase 0):** `docker compose up` brings the stack up; `POST /jobs` enqueues and a worker flips the job to `done`; `wcag_criteria.json` loads and `criteria_in_scope("2.2","AAA")` returns 87 rows.

**Pitfalls:** don't let anyone hand-edit the WCAG JSON; don't scatter status logic — everything routes through `derive_status`.

---

## Phase 1 — Web MVP

**Goal:** user submits a domain → platform discovers hosts, crawls, scans with **axe-core only**, normalizes, and produces all **6 reports in docx + xlsx**, passing the contradiction validator. This is your first shippable, legitimate product.

### 1.1 Subdomain discovery (`scanners/web/subdomains.py`)
```python
import json, subprocess, urllib.request

def _run(cmd: list[str], timeout=300) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout

def discover(domain: str) -> list[str]:
    hosts: set[str] = {domain}
    # subfinder (passive)
    out = _run(["subfinder", "-silent", "-d", domain])
    hosts.update(h.strip() for h in out.splitlines() if h.strip())
    # crt.sh certificate transparency
    try:
        url = f"https://crt.sh/?q=%25.{domain}&output=json"
        data = json.loads(urllib.request.urlopen(url, timeout=30).read())
        for row in data:
            for name in row.get("name_value", "").split("\n"):
                if name.endswith(domain):
                    hosts.add(name.lstrip("*."))
    except Exception:
        pass
    return live_hosts(sorted(hosts))

def live_hosts(hosts: list[str]) -> list[str]:
    """Probe with httpx; keep responsive hosts (JSON lines)."""
    proc = subprocess.run(["httpx", "-silent", "-json"],
                          input="\n".join(hosts), capture_output=True, text=True)
    live = []
    for line in proc.stdout.splitlines():
        try:
            live.append(json.loads(line)["url"])
        except Exception:
            continue
    return live or [f"https://{hosts[0]}"]
```
Respect the authorization gate before calling this.

### 1.2 Crawler (`scanners/web/crawler.py`)
Use katana for speed, or Playwright when you need JS routes/auth. Katana version:
```python
import subprocess
from ..config import settings

def crawl(base_url: str) -> list[str]:
    out = subprocess.run(
        ["katana", "-silent", "-u", base_url,
         "-depth", str(settings.crawl_max_depth),
         "-field", "url", "-strategy", "breadth-first",
         "-crawl-scope", "strict"],   # same-origin
        capture_output=True, text=True, timeout=600).stdout
    seen, urls = set(), []
    for u in out.splitlines():
        u = u.split("?")[0].rstrip("/")          # normalize
        if u and u not in seen and _wanted(u):
            seen.add(u); urls.append(u)
        if len(urls) >= settings.max_pages_per_host:
            break
    return urls or [base_url]

def _wanted(u: str) -> bool:
    bad = (".pdf", ".jpg", ".png", ".zip", "mailto:", "tel:", "/logout")
    return not any(b in u.lower() for b in bad)
```
**Template sampling:** if a site has thousands of near-identical pages, sample representative templates and record it in the report methodology (issues are template-driven).

### 1.3 axe scan (`scanners/web/engines.py`)
Inject axe-core into a live Playwright page. Node runner is the most robust; call it via subprocess and read JSON, or use Python Playwright + the axe-core dist file. Python approach:
```python
from playwright.sync_api import sync_playwright
from pathlib import Path
import importlib.resources, json

AXE_JS = Path("node_modules/axe-core/axe.min.js").read_text()

def scan_axe(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.add_script_tag(content=AXE_JS)
        # run all WCAG rulesets incl. AAA-capable tags
        result = page.evaluate("""async () => await axe.run(document, {
            runOnly: { type: 'tag',
              values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa',
                       'wcag2aaa','best-practice'] } })""")
        browser.close()
        return result   # {violations, passes, incomplete, inapplicable}
```
Store the full `result` in object storage (`raw_engine_payload_key`). `incomplete` = axe's own "needs review" — route these to `needs_manual_review`, never drop them.

### 1.4 Normalization (`scanners/web/normalize.py`)
```python
from ..models import Finding, Status, Impact, Confidence, TargetType, Location
from .. import wcag

IMPACT_MAP = {"critical": Impact.blocker, "serious": Impact.serious,
              "moderate": Impact.moderate, "minor": Impact.minor, None: Impact.moderate}

def axe_to_findings(job_id: str, url: str, axe_result: dict,
                    rule_map: dict) -> list[Finding]:
    out = []
    for v in axe_result.get("violations", []):
        sc = rule_map.get(v["id"])         # rule -> "1.4.3"
        if not sc:
            continue
        crit = wcag.criterion(sc)
        for node in v["nodes"]:
            out.append(Finding(
                job_id=job_id, target_type=TargetType.web,
                sc_num=sc, sc_name=crit["name"], level=crit["level"],
                principle=crit["principle"], wcag_versions=crit["versions"],
                status=Status.fail, confidence=Confidence.high,
                auto_decidable=(crit["testability"] == "auto"),
                engine="axe-core", engine_rule_id=v["id"],
                impact=IMPACT_MAP.get(v.get("impact")),
                selector=", ".join(node.get("target", [])),
                html_snippet=node.get("html", "")[:600],
                computed=_extract_computed(node),
                description=v.get("help", ""),
                remediation=_remediation(sc, v["id"]),
                locations=[Location(ref=url, count=1)],
            ))
    return dedupe(out)

def dedupe(findings: list[Finding]) -> list[Finding]:
    """Merge by (sc_num, engine_rule_id, selector) → roll up occurrences/locations."""
    bucket: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.sc_num, f.engine_rule_id, f.selector)
        if key in bucket:
            b = bucket[key]
            b.occurrences += 1
            _merge_location(b, f.locations[0])
        else:
            f.occurrences = 1
            bucket[key] = f
    return list(bucket.values())
```
Keep the rule→criterion map in `wcag_data/rule_maps/axe.json` (Appendix A). `_remediation` pulls from a **fixed remediation KB** keyed by criterion/rule — never LLM-invented.

### 1.5 Combo scoping + contradiction validator (`reporting/common.py`)
```python
from .. import wcag
from ..models import Finding, Status

def build_combo(version: str, level: str, findings: list[Finding],
                reviews: dict[str, Status] | None = None) -> dict:
    reviews = reviews or {}
    rows, issues = [], []
    for crit in wcag.criteria_in_scope(version, level):
        status, conf = wcag.derive_status(crit, findings, reviews.get(crit["num"]))
        rows.append({"crit": crit, "status": status, "confidence": conf})
        if status == Status.fail:
            issues += [f for f in findings if f.sc_num == crit["num"]]
    combo = {"version": version, "level": level, "rows": rows, "issues": issues}
    validate(combo, findings)          # abort on contradiction
    return combo

def validate(combo: dict, findings: list[Finding]) -> None:
    for row in combo["rows"]:
        c, st = row["crit"], row["status"]
        fails = [f for f in findings if f.sc_num == c["num"] and f.status == Status.fail]
        assert not (st == Status.pass_ and fails), \
            f"CONTRADICTION: {c['num']} marked Pass but has {len(fails)} failures"
        assert not (st == Status.pass_ and c["testability"] != "auto"), \
            f"CONTRADICTION: {c['num']} Pass but not auto-testable"
    for f in combo["issues"]:
        assert f.occurrences == sum(l.count for l in f.locations), \
            f"CONTRADICTION: {f.sc_num} occurrence count != sum(locations)"
```

### 1.6 DOCX report (`reporting/docx_report.py`)
python-docx, sections mapped 1:1 to the sample (`TECHNICAL_GUIDE.md §8.1`). Skeleton:
```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor

GLYPH = {"fail": ("● Fail", RGBColor(0xC0,0x1A,0x1A)),
         "partial": ("▲ Partial", RGBColor(0xB8,0x86,0x00)),
         "pass": ("✔ Pass", RGBColor(0x1A,0x7A,0x2E)),
         "needs_manual_review": ("⚠ Needs Manual Review", RGBColor(0x8A,0x6D,0x00)),
         "not_applicable": ("— N/A", RGBColor(0x66,0x66,0x66))}

def build_docx(combo, meta, out_path):
    doc = Document()
    _cover(doc, combo, meta)
    _document_control(doc, combo, meta)
    _confidentiality(doc)          # INCLUDE automation-limits disclaimer
    _scope(doc, combo, meta)
    _methodology(doc, meta)        # list engines that actually ran
    _executive_summary(doc, combo) # coverage table from registry + severity tally
    _full_checklist(doc, combo)    # every in-scope criterion, grouped by principle
    _detailed_observations(doc, combo)   # per-issue cards + embedded screenshots
    _risk_conclusion(doc, combo)
    _recommendations(doc, combo)
    doc.save(out_path)

def _detailed_observations(doc, combo):
    doc.add_heading("Detailed Observations", level=1)
    for i, f in enumerate(combo["issues"], 1):
        t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
        _kv(t, f"Issue {i} │ {f.description}", "")
        _kv(t, "WCAG Criterion", f"{f.sc_num} {f.sc_name}")
        _kv(t, "Conformance Level", f.level)
        _kv(t, "Impact Rating", f.impact.value.title())
        _kv(t, "Total Occurrences", str(f.occurrences))
        _kv(t, "Element Location", "\n".join(f"{l.ref} ({l.count})" for l in f.locations))
        _kv(t, "Description", f.description)
        # Visual evidence — embed the real screenshot
        if f.screenshot_key:
            png = download(f.screenshot_key)     # Phase 2 fills this in
            doc.add_picture(png, width=Inches(6))
        _kv(t, "Remediation Steps", f.remediation)
```
Downscale evidence images (Phase 2) so files don't hit the sample's 15 MB.

### 1.7 XLSX report (`reporting/xlsx_report.py`)
openpyxl workbook: **Summary**, **Checklist** (conditional formatting by status), **Findings** (one row per finding + thumbnail). Freeze panes + autofilter.

### 1.8 Wire the worker
`run_job` for web: `discover → for each host crawl → for each page scan_axe → normalize → for combo in REPORT_MATRIX: build_combo → build_docx + build_xlsx → upload`. Update job status at each step for the UI.

**Definition of done (Phase 1):** submit a domain, receive 12 files (6 combos × 2 formats); every `Fail` has an engine rule + computed values; every non-`auto` unverified criterion reads `Needs Manual Review`; the validator passes; coverage tables match the registry counts (2.2/AAA shows 87 criteria).

**Tests:** golden-file test on a fixture site with known issues; unit tests on `derive_status` (all three testability classes) and `validate` (must raise on a planted contradiction).

**Pitfalls:** don't drop axe `incomplete` items; don't let a page timeout kill the whole job (catch per-page, record `error` locations); normalize URLs before dedup or occurrence counts drift.

---

## Phase 2 — Multi-engine + screenshot evidence

**Goal:** raise recall and add the highlighted screenshots that make the report look and prove like the sample.

### 2.1 Add engines behind the common interface
- **Pa11y** (`runner: htmlcs`, standard `WCAG2AAA`) — the main source of automated AAA checks. Call `pa11y --reporter json --standard WCAG2AAA <url>`; each result code embeds the SC → map it.
- **Lighthouse** — `lighthouse <url> --only-categories=accessibility --output=json`; harvest failing audits + score.
- **IBM Equal Access** — `accessibility-checker` Node API; ACT-aligned, good cross-check.

Each engine → its own `*_to_findings` normalizer → append to the finding pool. Store each engine's raw JSON.

### 2.2 Reconciliation (`normalize.py`)
When multiple engines hit the same `(sc_num, selector)`:
- agreement → bump `confidence` to `high`, keep one finding, list contributing engines.
- disagreement (one fails, another passes) → keep the `fail` (precedence in `TECHNICAL_GUIDE.md §4`) but tag `confidence=medium` and flag for review.
Never let engine silence upgrade another engine's `fail`.

### 2.3 Evidence capture (`scanners/web/evidence.py`)
For every `fail`, during the Playwright session: screenshot the page, draw a highlight box over the element, crop with padding, downscale, upload. (Full code in `TECHNICAL_GUIDE.md §5.4`.) Set `screenshot_key` + `page_screenshot_key` on the finding. Downscale to ≤1600px and JPEG/PNG-optimize with Pillow to control report size.

### 2.4 Wire evidence into reports
`_detailed_observations` already embeds `screenshot_key`. Add a "full-page context" thumbnail link. The xlsx **Findings** sheet embeds a small thumbnail per row.

**Definition of done (Phase 2):** each combo report shows highlighted screenshots under Visual Evidence; AAA reports now contain real Pa11y AAA findings; disagreements are visible in a "confidence" column; report file sizes stay reasonable.

**Pitfalls:** engines disagree constantly on contrast at anti-aliased edges — trust axe/IBM computed ratios over screenshot guesses; some elements are off-screen or in shadow DOM — `scroll_into_view_if_needed` and handle `bounding_box() is None`.

---

## Phase 3 — Human-review workbench

**Goal:** turn "automated partial scan" into a **defensible audit** by letting qualified reviewers close `needs_manual_review` rows. This is what makes AAA and the `semi`/`manual` majority meaningful.

### 3.1 Data model additions
```python
class Review(BaseModel):
    review_id: str
    job_id: str
    sc_num: str
    reviewer: str
    verdict: Status               # pass | fail | partial | not_applicable
    rationale: str                # required — why
    evidence_keys: list[str] = [] # reviewer-attached screenshots/notes
    at_technique: str | None = None   # e.g. "NVDA 2024.x", "VoiceOver iOS 17"
    created_at: str
```
Persist reviews; `build_combo` already accepts a `reviews` dict → feeds `derive_status`.

### 3.2 Review API + queue
- `GET /jobs/{id}/review-queue` → all criteria whose derived status is `needs_manual_review`, with the automated hints (axe `incomplete`, heuristic flags) attached to guide the reviewer.
- `POST /jobs/{id}/reviews` → record a verdict (rationale required; block empty).
- A criterion can only become `Pass`/`Partial` via a review record — enforced because `derive_status` only upgrades on `reviewer_verdict`.

### 3.3 Reviewer UI (frontend)
Split view: rendered page/screenshot on the left, criterion + AT-testing checklist on the right, verdict buttons + rationale box. Track reviewer identity and AT used (goes into the report's methodology + each closed row's provenance).

### 3.4 Report changes
- Closed rows show the reviewer verdict + are stamped "Manually verified (NVDA/VoiceOver, <reviewer>)" in the notes column.
- Executive summary distinguishes **automated fails** vs **manual fails** vs **still-open review** counts.

**Definition of done (Phase 3):** a reviewer can walk the queue and sign off; signed-off criteria flip to their verdict in all affected combos; unreviewed non-auto criteria still read `Needs Manual Review`; the report shows who verified what with which AT.

**Pitfalls:** don't allow bulk "mark all pass" — that reintroduces fabrication; require rationale; scope a review to a `(job, criterion)` so it doesn't leak across scans of different builds.

---

## Phase 4 — Android scanning

**Goal:** user uploads an APK/AAB (+ optional test credentials) → platform drives it on an emulator and audits each screen with Google's Accessibility Test Framework.

### 4.1 Emulator host
KVM Linux worker. Install Android `cmdline-tools`, `platform-tools`, `emulator`, a system image. Create a headless AVD:
```bash
echo "no" | avdmanager create avd -n a11y -k "system-images;android-34;google_apis;x86_64"
emulator -avd a11y -no-window -no-audio -gpu swiftshader_indirect -no-snapshot &
adb wait-for-device
```
Snapshot a clean state to reset between jobs quickly. One AVD per job for isolation.

### 4.2 Install + drive (`scanners/android/scanner.py`)
- `adb install app.apk`; launch main activity.
- **Appium (UiAutomator2)** logs in with provided credentials and walks screens: either a user-provided click-path, or a BFS crawler that taps focusable/clickable nodes with visited-state + loop detection and back-navigation.
- At each meaningful screen, dump the view hierarchy (`uiautomator dump` / Appium `page_source`) and screenshot (`driver.get_screenshot_as_png()`).

### 4.3 Audit with ATF
Run Google's **Accessibility Test Framework for Android** checks over the hierarchy. Options:
- Drive via an Espresso/UIAutomator test target that calls `AccessibilityCheckPreset` and returns results, **or**
- Parse Accessibility Scanner-style output.

ATF flags: missing `contentDescription` (SpeakableTextPresentCheck), low text/image contrast (TextContrastCheck, ImageContrastCheck), touch targets < 48dp (TouchTargetSizeCheck), duplicate descriptions, clickable-span issues, editable-label issues, traversal-order problems.

### 4.4 Map + evidence
- Map each ATF check class → WCAG criterion via `wcag_data/rule_maps/android_atf.json` (e.g. `TouchTargetSizeCheck→2.5.8/2.5.5`, `TextContrastCheck→1.4.3/1.4.6`, `SpeakableTextPresentCheck→1.1.1/4.1.2`).
- Evidence: crop the screenshot to the node's `bounds` rect + highlight, same as web.
- Everything ATF can't judge → `needs_manual_review` (recommend a manual **TalkBack** pass in the report).

**Definition of done (Phase 4):** upload an APK, get the same 6×2 reports with real ATF findings, node-highlighted screenshots, and honest manual-review rows.

**Pitfalls:** login walls and captchas block crawlers — support a scripted login step; dynamic/game-like UIs defeat hierarchy dumps — cap crawl and record coverage; keep emulator + system-image versions pinned and in the report.

---

## Phase 5 — iOS scanning (macOS node)

**Goal:** same outcome for iOS, on Apple hardware, using XCUITest's built-in accessibility audit.

### 5.1 macOS worker
Mac mini / EC2 Mac / MacStadium joined to the same Celery queue. Pin Xcode + simulator runtimes. Boot a simulator:
```bash
xcrun simctl boot "iPhone 15"
xcrun simctl install booted App.app
xcrun simctl launch booted <bundle-id>
```

### 5.2 Drive + audit (`scanners/ios/scanner.py`)
- **Appium (XCUITest driver)** or a native XCUITest UI-test target logs in and walks screens.
- At each screen call **`performAccessibilityAudit()`**:
  ```swift
  let app = XCUIApplication()
  try app.performAccessibilityAudit()   // throws with aggregated issues
  ```
  It audits contrast, element description, hit-region size (44×44), clipped text, trait conflicts, dynamic-type support. Capture the structured issues.
- Evidence: `XCUIScreen.main.screenshot()` + element `frame` → crop + highlight.

### 5.3 Map + report
- `wcag_data/rule_maps/ios_xcuitest.json` maps audit issue types → WCAG criteria.
- Note physical-device-only aspects (real VoiceOver rotor/gestures) as manual review.

**Provisioning requirement:** automated simulator audits need a **simulator build** (`.app`) or a resigned dev `.ipa`. A store `.ipa` alone may not install on a simulator — make this an intake requirement.

**Definition of done (Phase 5):** upload a simulator build, get 6×2 reports with XCUITest audit findings + highlighted screenshots + honest manual rows.

**Pitfalls:** the audit API is iOS 17+/Xcode 15+ — older targets get manual-only; simulator ≠ device for some a11y behaviors — say so.

---

## Phase 6 — Scale, security & polish

**Goal:** production hardening.

- **Warm pools** of browsers/AVDs/simulators — boot time dominates mobile jobs.
- **Authenticated web scanning** — Playwright storage-state login; secrets from the vault, injected at runtime, never logged, purged after (`TECHNICAL_GUIDE.md §10`).
- **PII redaction** in screenshots from authenticated scans; short retention; access-controlled report storage.
- **Rate limiting / polite mode**; honor robots + client-set limits.
- **PDF export** — render docx→pdf (LibreOffice headless) for stakeholders.
- **Report theming** — brand cover, logo, color; a `DocxTheme` shared by all 6 reports.
- **Reproducibility** — stamp every report with engine + tool versions used.
- **Audit log + RBAC** — who scanned what, when; role-gated downloads.
- **Observability** — per-engine timing, per-page error rate, queue depth dashboards.

**Definition of done (Phase 6):** concurrent jobs don't contend; authenticated scans work with vaulted secrets; reports carry versions + branding; nothing sensitive is logged.

---

## Cross-cutting concerns

**Testing strategy**
- Unit: `derive_status` (all testability classes), `validate` (must raise on planted contradictions), each engine normalizer against captured raw JSON fixtures.
- Golden-file: a deliberately-broken fixture site/app with known issues → assert findings + report rows.
- Contract: every engine normalizer must emit valid `Finding` objects (Pydantic validates).
- Regression: keep raw engine payloads so you can re-normalize without re-scanning.

**CI/CD**
- Regenerate `wcag_criteria.json` and fail CI if it drifts from committed.
- Lint + type-check (mypy) the status/validator code hardest — it's the legitimacy core.
- Build + smoke-run a scan against a local fixture on every PR.

**Observability**
- Structured logs per job/page/engine; metrics on coverage %, review-queue size, engine agreement rate. A rising "review queue" is expected, not a failure — it's honesty made visible.

---

## Appendix A — rule→criterion map format

`wcag_data/rule_maps/axe.json` (excerpt):
```json
{
  "color-contrast": "1.4.3",
  "color-contrast-enhanced": "1.4.6",
  "image-alt": "1.1.1",
  "link-name": "2.4.4",
  "html-has-lang": "3.1.1",
  "frame-title": "4.1.2",
  "select-name": "4.1.2",
  "meta-viewport": "1.4.4",
  "target-size": "2.5.8"
}
```
Maintain one file per engine. Unmapped rules are logged (so you can extend the map) but never silently dropped into a report.

---

## Appendix B — acceptance checklists

**Every report, every phase — must be true before it ships:**
- [ ] No criterion is `Pass` while a `Fail` finding exists for it.
- [ ] No non-`auto` criterion is `Pass` without a reviewer sign-off.
- [ ] Every `Fail` has: engine, rule id, computed values or snippet, and (Phase 2+) a screenshot.
- [ ] `occurrences == sum(locations.count)` for every finding.
- [ ] Coverage table counts equal the registry counts for that (version, level).
- [ ] The confidentiality section states the automation limits.
- [ ] Engine + tool versions are stamped in the report.
- [ ] `needs_manual_review` rows are present and labelled (not hidden as Pass).

If any box is unchecked, the contradiction validator should already have aborted the build. That gate is the difference between a real audit and a fabricated one.
