"""Android emulator (AVD) lifecycle via the SDK command-line tools + adb.

Runs on the target host (native Windows 11 with WHPX acceleration, or a Linux CI
host with KVM). Everything shells out to the official SDK tools; a missing SDK
raises `EmulatorUnavailable`, which the pipeline surfaces honestly (job → error)
rather than fabricating a device.

WHPX note: HAXM is discontinued and AEHD sunsets 2026-12-31 — use WHPX (enable
the 'Windows Hypervisor Platform' feature). Headless launch uses
`-no-window -gpu swiftshader_indirect`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path


class EmulatorUnavailable(RuntimeError):
    pass


def _sdk_root() -> Path | None:
    for env in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        v = os.getenv(env)
        if v and Path(v).exists():
            return Path(v)
    default = Path.home() / "Android" / "Sdk"
    return default if default.exists() else None


def _tool(name: str, *subdirs: str) -> str | None:
    root = _sdk_root()
    if root:
        for sub in subdirs:
            for suffix in ("", ".exe", ".bat"):
                p = root / sub / f"{name}{suffix}"
                if p.exists():
                    return str(p)
    return shutil.which(name)


def _adb() -> str:
    p = _tool("adb", "platform-tools")
    if not p:
        raise EmulatorUnavailable("adb not found — install Android platform-tools "
                                  "and set ANDROID_SDK_ROOT.")
    return p


def _run(cmd: list[str], timeout: int = 120, input_text: str | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, "", str(e)


def adb(*args: str, timeout: int = 120) -> tuple[int, str, str]:
    return _run([_adb(), *args], timeout=timeout)


def ensure_avd(name: str, system_image: str) -> None:
    avdmanager = _tool("avdmanager", "cmdline-tools/latest/bin", "cmdline-tools/bin", "tools/bin")
    if not avdmanager:
        raise EmulatorUnavailable("avdmanager not found — install Android cmdline-tools.")
    code, out, _ = _run([avdmanager, "list", "avd"], timeout=60)
    if name in out:
        return
    # Install the system image, then create the AVD.
    sdkmanager = _tool("sdkmanager", "cmdline-tools/latest/bin", "cmdline-tools/bin", "tools/bin")
    if sdkmanager:
        _run([sdkmanager, system_image], timeout=1800, input_text="y\n")
    _run([avdmanager, "create", "avd", "-n", name, "-k", system_image, "--force"],
         timeout=300, input_text="no\n")


def boot(name: str, headless: bool = True, boot_timeout: int = 300) -> None:
    emulator = _tool("emulator", "emulator", "tools")
    if not emulator:
        raise EmulatorUnavailable("emulator not found — install the Android 'emulator' package.")
    args = [emulator, "-avd", name, "-no-audio", "-no-boot-anim", "-no-snapshot",
            "-gpu", "swiftshader_indirect", "-accel", "on"]
    if headless:
        args.append("-no-window")
    # Launch detached; adb will wait for it.
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    adb("wait-for-device", timeout=boot_timeout)
    # Poll sys.boot_completed.
    deadline = time.time() + boot_timeout
    while time.time() < deadline:
        code, out, _ = adb("shell", "getprop", "sys.boot_completed", timeout=15)
        if out.strip() == "1":
            adb("shell", "input", "keyevent", "82")  # dismiss lock
            return
        time.sleep(3)
    raise EmulatorUnavailable("emulator did not finish booting in time")


def install(apk_path: str, test: bool = False) -> None:
    if not Path(apk_path).exists():
        raise EmulatorUnavailable(f"APK not found: {apk_path}")
    args = ["install", "-r", "-g"]
    if test:
        args.append("-t")
    code, out, err = adb(*args, apk_path, timeout=300)
    if code != 0:
        raise EmulatorUnavailable(f"adb install failed: {err or out}")


def launch_app(package: str) -> None:
    adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", timeout=60)


def current_focus() -> str:
    _, out, _ = adb("shell", "dumpsys", "window", "windows", timeout=30)
    for line in out.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            return line.strip()
    return ""


def screenshot_png() -> bytes:
    p = subprocess.run([_adb(), "exec-out", "screencap", "-p"], capture_output=True, timeout=30)
    return p.stdout


def is_available() -> bool:
    try:
        return bool(_sdk_root()) or bool(shutil.which("adb"))
    except Exception:
        return False


def shutdown() -> None:
    try:
        adb("emu", "kill", timeout=30)
    except Exception:
        pass
