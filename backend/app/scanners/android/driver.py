"""Appium (UiAutomator2) driver: install, log in, and walk the app's screens.

IMPORTANT (validated correction): Appium UiAutomator2 does NOT run Google's ATF.
This module handles NAVIGATION, login, screenshots, and the UiAutomator view
hierarchy only. The ATF audit itself is produced by the on-device harness in
`atf.py` (UiAutomation → AccessibilityHierarchy → AccessibilityCheckPreset),
which is triggered per screen via the `on_screen` callback while that screen is
in the foreground.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Callable

from ...config import settings


class DriverUnavailable(RuntimeError):
    pass


def _appium():
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        from appium.webdriver.common.appiumby import AppiumBy
        return webdriver, UiAutomator2Options, AppiumBy
    except Exception as exc:  # noqa: BLE001
        raise DriverUnavailable(
            "Appium-Python-Client not installed (pip install Appium-Python-Client) "
            f"or import failed: {exc}")


def start_session(app_path: str | None, package: str | None,
                  server_url: str | None = None):
    webdriver, UiAutomator2Options, _ = _appium()
    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    opts.new_command_timeout = 300
    opts.auto_grant_permissions = True
    if app_path:
        opts.app = app_path
    if package:
        opts.set_capability("appPackage", package)
        opts.set_capability("appWaitActivity", "*")
    return webdriver.Remote(server_url or settings.appium_server_url, options=opts)


# ── scripted login / steps ───────────────────────────────────────────────────

def execute_steps(driver, steps: list[dict], credentials: dict | None) -> None:
    _, _, AppiumBy = _appium()
    creds = credentials or {}
    by_map = {"id": AppiumBy.ID, "xpath": AppiumBy.XPATH,
              "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
              "class": AppiumBy.CLASS_NAME}
    for step in steps or []:
        action = step.get("action")
        try:
            if action == "wait":
                time.sleep(step.get("ms", 1000) / 1000)
            elif action == "back":
                driver.back()
            elif action in ("type", "tap"):
                el = driver.find_element(by_map[step.get("by", "id")], step["value"])
                if action == "tap":
                    el.click()
                else:
                    text = step.get("text", "")
                    text = text.replace("$username", creds.get("username", "")) \
                               .replace("$password", creds.get("password", ""))
                    el.send_keys(text)
            time.sleep(0.6)
        except Exception as exc:  # noqa: BLE001
            print(f"[android.login] step {step} failed: {exc}")


def login(driver, credentials: dict | None, login_steps: list[dict] | None) -> None:
    if login_steps:
        execute_steps(driver, login_steps, credentials)


# ── capture + crawl ──────────────────────────────────────────────────────────

_RESID = re.compile(r'resource-id="([^"]*)"')


def _signature(activity: str, page_source: str) -> str:
    ids = sorted(set(_RESID.findall(page_source or "")))
    return hashlib.sha1((activity + "|" + "|".join(ids)).encode()).hexdigest()[:16]


def capture(driver) -> dict:
    try:
        activity = driver.current_activity or ""
    except Exception:
        activity = ""
    page_source = driver.page_source
    png = driver.get_screenshot_as_png()
    return {"activity": activity, "page_source": page_source, "screenshot": png,
            "signature": _signature(activity, page_source)}


def crawl(driver, max_screens: int, on_screen: Callable[[dict], object]) -> list[dict]:
    """DFS one level from the entry screen: capture each new screen, run the ATF
    audit (via on_screen) while it's foreground, then back out. A scripted
    click-path (login_steps-style) can extend this for deeper flows."""
    _, _, AppiumBy = _appium()
    screens: list[dict] = []
    visited: set[str] = set()

    def visit() -> dict | None:
        cap = capture(driver)
        if cap["signature"] in visited:
            return None
        visited.add(cap["signature"])
        try:
            cap["audit"] = on_screen(cap)
        except Exception as exc:  # noqa: BLE001
            cap["audit"] = {"status": "error", "error": str(exc)}
        cap["index"] = len(screens)
        screens.append(cap)
        return cap

    visit()  # entry screen

    try:
        clickables = driver.find_elements(AppiumBy.XPATH, "//*[@clickable='true']")
    except Exception:
        clickables = []

    for el in clickables:
        if len(screens) >= max_screens:
            break
        try:
            el.click()
            time.sleep(1.2)
            if visit():
                driver.back()
                time.sleep(0.8)
        except Exception:
            continue

    return screens


def quit(driver) -> None:
    try:
        driver.quit()
    except Exception:
        pass
