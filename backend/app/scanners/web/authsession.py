"""Authenticated web scanning — Playwright storage-state login.

Logs in once with vaulted credentials, captures the browser storage state
(cookies + localStorage), and hands it to the engines/evidence so they scan the
authenticated app. Credentials come from the secret store (never the DB/logs) and
are purged after the job.

Login steps (list of dicts), with $username/$password substitution:
  {"action": "goto",  "url": "https://app/login"}
  {"action": "fill",  "selector": "#user", "text": "$username"}
  {"action": "fill",  "selector": "#pass", "text": "$password"}
  {"action": "click", "selector": "button[type=submit]"}
  {"action": "wait",  "ms": 2000}
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def login_and_capture(login_url: str | None, steps: list[dict] | None,
                      credentials: dict | None, out_path: Path) -> str | None:
    """Run the login flow and write storage state to `out_path`. Returns the path,
    or None if login can't run (Playwright missing / no steps) — the scan then
    proceeds UNAUTHENTICATED and the report notes it."""
    if not steps and not (login_url and credentials):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[auth] Playwright not installed — scanning unauthenticated.")
        return None

    creds = credentials or {}

    def sub(t: str) -> str:
        return (t or "").replace("$username", creds.get("username", "")) \
                        .replace("$password", creds.get("password", ""))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            ctx = browser.new_context()
            page = ctx.new_page()
            if login_url:
                page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
            for step in steps or []:
                action = step.get("action")
                if action == "goto":
                    page.goto(step["url"], wait_until="domcontentloaded", timeout=45000)
                elif action == "fill":
                    page.fill(step["selector"], sub(step.get("text", "")))
                elif action == "click":
                    page.click(step["selector"])
                elif action == "wait":
                    time.sleep(step.get("ms", 1000) / 1000)
                time.sleep(0.4)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            state = ctx.storage_state()
            out_path.write_text(json.dumps(state))
            browser.close()
            return str(out_path)
    except Exception as exc:  # noqa: BLE001 — never leak credentials in the message
        print(f"[auth] login flow failed ({type(exc).__name__}) — scanning unauthenticated.")
        return None
