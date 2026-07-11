# Windows 11 → WSL2 environment setup

The backend + web pipeline run in **WSL2 Ubuntu** (closest to the Linux
production target; Celery prefork, Go tooling, Playwright, and Docker all work
there). The Android emulator (Phase 4) runs on the **native Windows host** with
WHPX. iOS (Phase 5) needs a **cloud/physical Mac**.

## 1. One-time host prep (Windows PowerShell, as Administrator)

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName `
  Microsoft-Windows-Subsystem-Linux, VirtualMachinePlatform, HypervisorPlatform -All
# reboot
wsl --install -d Ubuntu-24.04
wsl --update
```

- `HypervisorPlatform` = **WHPX** (Android emulator accel). `VirtualMachinePlatform` = WSL2/Docker. They coexist on the same Hyper-V stack.
- Confirm CPU virtualization is **Enabled** (Task Manager → Performance → CPU).
- HAXM is discontinued; **AEHD sunsets 2026-12-31** — use WHPX.

## 2. Inside WSL2 Ubuntu

```bash
# Toolchains
sudo apt update && sudo apt install -y python3-venv python3-pip nodejs npm golang git libreoffice-writer

# Clone into the ext4 home — NOT /mnt/c (10x+ filesystem penalty)
cd ~ && git clone <this-repo> wcag && cd wcag

# Vendored OSS tools (clones + builds Go recon + installs Node engines + Chromium)
bash scripts/setup_tools.sh

# Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
playwright install --with-deps chromium

# WCAG registry (facts from W3C + our testability enrichment)
python wcag_data/ingest_wcag.py && python wcag_data/enrich_testability.py
```

## 3. Run

```bash
# Services (Postgres, Valkey, MinIO):
cp .env.example .env
docker compose -f docker/docker-compose.yml up -d

# API + worker (two shells):
uvicorn backend.app.main:app --reload
celery -A backend.app.worker.celery_app worker -l info

# Or a standalone scan (SQLite + local files, no Docker):
python scripts/run_local_scan.py https://your-authorized-domain.example

# Or just see the report format offline:
python scripts/demo_report.py    # -> artifacts/demo/reports/
```

## 4. Gotchas
- Keep the repo + venv + node_modules + artifacts on **ext4** (`~/wcag`), not `/mnt/c`.
- `.gitattributes` forces LF; run `git config --global core.autocrlf input` in WSL.
- Cap WSL RAM in `%USERPROFILE%\.wslconfig` (`[wsl2]\nmemory=8GB`) so the Compose stack + Chromium don't thrash.
- Redis/Valkey and MinIO have **no supported native Windows server** — always run them in Docker/WSL2 (compose does this).
