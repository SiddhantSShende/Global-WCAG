"""Drive the ATF harness: install it, run the instrumentation, pull results.

Returns a list of screens, each with the ATF results and a local screenshot path.
If the harness APKs aren't built or the emulator is unavailable, raises
`AtfUnavailable` — the pipeline then records an engine error (fail-closed) so no
criterion can be marked Pass on the basis of an audit that never ran.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ...config import settings
from . import emulator

HARNESS_ROOT = Path(__file__).resolve().parents[4] / "android_atf_harness"
DEBUG_APK = HARNESS_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
TEST_APK = settings.android_atf_harness_apk
HARNESS_PKG = "com.a11yaudit.harness"
REMOTE_DIR = f"/sdcard/Android/data/{HARNESS_PKG}/files/a11y"


class AtfUnavailable(RuntimeError):
    pass


def _build_harness() -> bool:
    gradlew = HARNESS_ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    cmd = None
    if gradlew.exists():
        cmd = [str(gradlew)]
    elif shutil.which("gradle"):
        cmd = ["gradle"]
    if not cmd:
        return False
    try:
        subprocess.run(cmd + ["assembleDebug", "assembleDebugAndroidTest"],
                       cwd=str(HARNESS_ROOT), capture_output=True, text=True, timeout=1800)
    except Exception:
        return False
    return DEBUG_APK.exists() and TEST_APK.exists()


def run_audit(package: str, max_screens: int, work_dir: Path) -> list[dict]:
    if not emulator.is_available():
        raise AtfUnavailable("No Android SDK/emulator on this host. Android auditing "
                             "requires a WHPX (Windows) or KVM (Linux) emulator host.")
    if not (DEBUG_APK.exists() and TEST_APK.exists()):
        if not _build_harness():
            raise AtfUnavailable(
                "ATF harness APKs not built. Run: cd android_atf_harness && "
                "./gradlew assembleDebug assembleDebugAndroidTest")

    emulator.install(str(DEBUG_APK), test=True)
    emulator.install(str(TEST_APK), test=True)
    emulator.adb("shell", "rm", "-rf", REMOTE_DIR)

    code, out, err = emulator.adb(
        "shell", "am", "instrument", "-w",
        "-e", "targetPackage", package,
        "-e", "maxScreens", str(max_screens),
        f"{HARNESS_PKG}.test/androidx.test.runner.AndroidJUnitRunner",
        timeout=900,
    )
    if "INSTRUMENTATION_RESULT" not in out and "OK" not in out and code != 0:
        raise AtfUnavailable(f"instrumentation failed: {(err or out)[:400]}")

    work_dir.mkdir(parents=True, exist_ok=True)
    emulator.adb("pull", REMOTE_DIR, str(work_dir), timeout=180)

    results_path = work_dir / "a11y" / "results.json"
    if not results_path.exists():
        raise AtfUnavailable("harness produced no results.json (audit did not run)")

    screens = json.loads(results_path.read_text(encoding="utf-8"))
    # Rewrite device screenshot paths to the pulled local files (by basename).
    pulled = work_dir / "a11y"
    for s in screens:
        base = Path(s.get("screenshot", "")).name
        local = pulled / base
        s["screenshot_local"] = str(local) if local.exists() else None
    return screens


def harness_ready() -> bool:
    return DEBUG_APK.exists() and TEST_APK.exists()
