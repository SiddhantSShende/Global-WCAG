"""iOS Simulator lifecycle via `xcrun simctl`.

macOS ONLY — Xcode + iOS Simulators are licensed to Apple hardware (Apple SLA)
and do not run on Windows/Linux. On a non-macOS host every call raises
`SimulatorUnavailable`, which the pipeline surfaces honestly (job → error). This
module is the pluggable macOS worker's device layer.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path


class SimulatorUnavailable(RuntimeError):
    pass


def is_macos() -> bool:
    return platform.system() == "Darwin"


def _xcrun() -> str:
    if not is_macos():
        raise SimulatorUnavailable(
            "iOS auditing requires macOS + Xcode (Apple SLA). This host is "
            f"{platform.system()}. Route iOS jobs to a macOS worker "
            "(Mac mini / EC2 Mac / MacStadium / GitHub macos runner).")
    x = shutil.which("xcrun")
    if not x:
        raise SimulatorUnavailable("xcrun not found — install Xcode + command-line tools.")
    return x


def _run(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run([_xcrun(), *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def available() -> bool:
    return is_macos() and shutil.which("xcrun") is not None


def find_device(preferred: str) -> str:
    """Return a booted-or-bootable device UDID matching `preferred` (name or UDID)."""
    code, out, _ = _run(["simctl", "list", "devices", "available", "--json"])
    data = json.loads(out or "{}")
    for _runtime, devices in (data.get("devices") or {}).items():
        for d in devices:
            if preferred in (d.get("name"), d.get("udid")):
                return d["udid"]
    # fall back to the first available iPhone
    for _runtime, devices in (data.get("devices") or {}).items():
        for d in devices:
            if "iPhone" in d.get("name", ""):
                return d["udid"]
    raise SimulatorUnavailable(f"no available simulator matching '{preferred}'")


def boot(device: str, timeout: int = 240) -> str:
    udid = find_device(device)
    _run(["simctl", "boot", udid], timeout=timeout)
    _run(["simctl", "bootstatus", udid, "-b"], timeout=timeout)
    return udid


def install(udid: str, app_path: str) -> None:
    if not Path(app_path).exists():
        raise SimulatorUnavailable(f"app not found: {app_path}")
    if app_path.endswith(".ipa"):
        raise SimulatorUnavailable(
            "A store/distribution .ipa cannot run on a Simulator — a Simulator "
            "build (.app, x86_64/arm64 simulator slice) is required.")
    code, _out, err = _run(["simctl", "install", udid, app_path], timeout=300)
    if code != 0:
        raise SimulatorUnavailable(f"simctl install failed: {err}")


def launch(udid: str, bundle_id: str) -> None:
    _run(["simctl", "launch", udid, bundle_id], timeout=120)


def screenshot_png(udid: str) -> bytes:
    p = subprocess.run([_xcrun(), "simctl", "io", udid, "screenshot", "--type=png", "-"],
                       capture_output=True, timeout=30)
    return p.stdout


def shutdown(udid: str) -> None:
    try:
        _run(["simctl", "shutdown", udid], timeout=60)
    except Exception:
        pass
