"""Central configuration. All tunables live here; nothing is hard-coded elsewhere."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Services ──
    database_url: str = "postgresql+psycopg2://a11y:a11y@localhost:5432/a11y"
    redis_url: str = "redis://localhost:6379/0"
    # Production uses Celery (broker up). In dev/demo (no broker) jobs run inline
    # in a background thread. Set USE_CELERY=true in the deployed API service.
    use_celery: bool = False

    # ── Object storage (S3 / MinIO / Garage) ──
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "a11y-artifacts"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"

    # ── WCAG registry (read-only at runtime) + rule maps ──
    wcag_json: Path = REPO_ROOT / "wcag_data" / "wcag_criteria.json"
    rule_maps_dir: Path = REPO_ROOT / "wcag_data" / "rule_maps"

    # ── Vendored tools ──
    third_party_dir: Path = REPO_ROOT / "third_party"
    artifacts_dir: Path = REPO_ROOT / "artifacts"

    # ── Report matrix ──
    # Headline 6 = A & AAA × 3 versions (what the client asked for). We ALSO
    # compute the 3 AA cuts because AAA is cumulative and AA is the legally
    # operative level (Section 508 / EN 301 549 / ADA / EAA). Drop the AA rows
    # here to expose only the headline 6.
    report_matrix: list[tuple[str, str]] = [
        ("2.0", "A"), ("2.0", "AA"), ("2.0", "AAA"),
        ("2.1", "A"), ("2.1", "AA"), ("2.1", "AAA"),
        ("2.2", "A"), ("2.2", "AA"), ("2.2", "AAA"),
    ]
    headline_levels: tuple[str, ...] = ("A", "AAA")  # for UI emphasis

    # ── Crawl scope / politeness (safe defaults; never uncapped) ──
    max_pages_per_host: int = 100
    crawl_max_depth: int = 2
    host_rate_limit_per_sec: int = 3
    honor_robots_txt: bool = True
    scan_user_agent: str = "A11yAuditBot/1.0 (+https://your-org.example/a11y-bot)"
    pages_per_template: int = 2          # template-sampling: N reps per template

    # ── Discovery safety ──
    allow_active_dns_bruteforce: bool = False   # requires per-job attestation

    # ── Evidence / report sizing ──
    screenshot_max_width_px: int = 1100
    report_image_format: str = "PNG"     # PNG (optimize) or JPEG (quality)
    report_jpeg_quality: int = 82

    # ── Engines to run (web) ──
    web_engines: tuple[str, ...] = ("axe-core", "pa11y", "lighthouse", "ibm-equal-access")

    # ── Android (Plane B — native Windows host with WHPX, or Linux+KVM CI) ──
    android_avd_name: str = "a11y_avd"
    android_system_image: str = "system-images;android-34;google_apis;x86_64"
    android_max_screens: int = 25         # cap the screen crawl
    android_atf_harness_apk: Path = REPO_ROOT / "android_atf_harness" / "app" / "build" / \
        "outputs" / "apk" / "androidTest" / "debug" / "app-debug-androidTest.apk"
    appium_server_url: str = "http://127.0.0.1:4723"

    # ── iOS (Plane C — macOS worker only; Apple SLA) ──
    ios_simulator_device: str = "iPhone 15"
    ios_max_screens: int = 25

    # ── Secrets vault ──
    vault_addr: str | None = None
    vault_token: str | None = None

    # ── AuthN/Z (RBAC) ──
    # When disabled (dev), every request is treated as 'admin'. In production set
    # auth_enabled=true and provide api_keys as {"<key>": "<role>"} (roles:
    # viewer < reviewer < operator < admin). Parsed from JSON env A11Y_API_KEYS.
    auth_enabled: bool = False
    api_keys: dict[str, str] = {}

    # ── Privacy / retention ──
    redact_pii: bool = True
    retention_days: int = 30
    redact_selectors: tuple[str, ...] = (
        "input[type=password]", "input[type=email]", "input[name*=ssn]",
        "input[name*=card]", "input[autocomplete=cc-number]",
    )


settings = Settings()
