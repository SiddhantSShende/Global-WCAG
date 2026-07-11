"""Locate vendored/OS tools and run them safely.

Resolution order for a tool binary:
  1) third_party/bin/<name>            (setup_tools.sh symlinks/builds here)
  2) third_party/<name>/<name>          (cloned repo build output)
  3) PATH (shutil.which)

Everything degrades HONESTLY: if a tool is missing, callers record an engine
`error` status (fail-closed) rather than pretending a clean result.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...config import settings


def find_tool(name: str, exe_suffixes: tuple[str, ...] = ("", ".exe")) -> str | None:
    tp = settings.third_party_dir
    candidates = [tp / "bin" / name, tp / name / name]
    for base in candidates:
        for suf in exe_suffixes:
            p = Path(str(base) + suf)
            if p.exists():
                return str(p)
    return shutil.which(name)


def run(cmd: list[str], timeout: int = 300, input_text: str | None = None,
        cwd: str | Path | None = None) -> tuple[int, str, str]:
    """Run a command, capturing output. Returns (returncode, stdout, stderr).
    A timeout or launch failure returns a non-zero code with the reason in stderr."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_text, cwd=str(cwd) if cwd else None,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError as exc:
        return 127, "", f"tool not found: {exc}"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"launch error: {exc}"


def node_bin() -> str | None:
    return shutil.which("node")


def tool_version(name: str, version_arg: str = "-version") -> str:
    path = find_tool(name)
    if not path:
        return "not-installed"
    code, out, err = run([path, version_arg], timeout=20)
    text = (out or err).strip().splitlines()
    return text[0] if text else "unknown"
