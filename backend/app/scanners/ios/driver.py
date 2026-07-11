"""Appium XCUITest driver: install, walk screens, capture — on the macOS worker.

Unlike Android (which needs a separate on-device ATF harness), the iOS audit runs
in THIS same Appium session via `mobile: performAccessibilityAudit` (see audit.py),
so the driver just navigates + captures and calls the audit hook per screen.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

from ...config import settings


class DriverUnavailable(RuntimeError):
    pass


def _appium():
    try:
        from appium import webdriver
        from appium.options.ios import XCUITestOptions
        from appium.webdriver.common.appiumby import AppiumBy
        return webdriver, XCUITestOptions, AppiumBy
    except Exception as exc:  # noqa: BLE001
        raise DriverUnavailable(
            "Appium-Python-Client not installed or import failed: %s" % exc)


def start_session(app_path: str | None, bundle_id: str | None, udid: str | None,
                  server_url: str | None = None):
    webdriver, XCUITestOptions, _ = _appium()
    opts = XCUITestOptions()
    opts.platform_name = "iOS"
    opts.automation_name = "XCUITest"
    opts.new_command_timeout = 300
    if udid:
        opts.udid = udid
    if app_path:
        opts.app = app_path
    if bundle_id:
        opts.bundle_id = bundle_id
    return webdriver.Remote(server_url or settings.appium_server_url, options=opts)


def capture(driver) -> dict:
    try:
        info = driver.execute_script("mobile: activeAppInfo") or {}
        bundle = info.get("bundleId", "")
    except Exception:
        bundle = ""
    page_source = driver.page_source
    png = driver.get_screenshot_as_png()
    sig = hashlib.sha1((bundle + "|" + str(len(page_source))).encode()).hexdigest()[:16]
    return {"activity": bundle, "package": bundle, "page_source": page_source,
            "screenshot": png, "signature": sig}


def _back(driver) -> None:
    _, _, AppiumBy = _appium()
    try:
        bars = driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeNavigationBar")
        if bars:
            btns = bars[0].find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton")
            if btns:
                btns[0].click()
                return
    except Exception:
        pass


def crawl(driver, max_screens: int, on_screen: Callable[[dict], object]) -> list[dict]:
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

    visit()

    try:
        tappable = (driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeButton")
                    + driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeCell"))
    except Exception:
        tappable = []

    for el in tappable:
        if len(screens) >= max_screens:
            break
        try:
            el.click()
            time.sleep(1.2)
            if visit():
                _back(driver)
                time.sleep(0.8)
        except Exception:
            continue

    return screens


def quit(driver) -> None:
    try:
        driver.quit()
    except Exception:
        pass
