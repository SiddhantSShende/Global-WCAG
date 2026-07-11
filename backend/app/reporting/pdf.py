"""docx → PDF via LibreOffice headless.

Server-safe: each conversion uses an isolated `-env:UserInstallation` profile so
concurrent workers don't collide (docx2pdf/Word-COM is NOT used — it needs Word
and is single-threaded). Returns None (no crash) if LibreOffice isn't installed;
PDF is a nice-to-have on top of the required docx + xlsx.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def to_pdf(docx_path: str, out_dir: str, timeout: int = 180) -> str | None:
    soffice = _soffice()
    if not soffice:
        return None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    profile = out / f"_lo_profile_{uuid.uuid4().hex}"
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation=file://{profile.as_posix()}",
             "--convert-to", "pdf", "--outdir", str(out), docx_path],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except Exception:
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    pdf = out / (Path(docx_path).stem + ".pdf")
    return str(pdf) if pdf.exists() else None
