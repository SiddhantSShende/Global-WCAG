"""Run the four web engines against a URL via their Node runners.

Every engine returns a raw payload + an EngineRun status. A missing tool, crash,
or timeout yields `EngineStatus.error` — which the combo builder treats as
fail-closed (an auto criterion cannot Pass if an engine that decides it errored).
"""
from __future__ import annotations

import json
from pathlib import Path

from ...config import settings
from ...models import EngineRun, EngineStatus
from . import toolrunner

JS_DIR = Path(__file__).parent / "js"
MARK = "__A11Y_RESULT__"

RUNNERS = {
    "axe-core": "run_axe.mjs",
    "pa11y": "run_pa11y.mjs",
    "lighthouse": "run_lighthouse.mjs",
    "ibm-equal-access": "run_ibm.mjs",
}


def _parse_envelope(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        idx = line.find(MARK)
        if idx != -1:
            try:
                return json.loads(line[idx + len(MARK):])
            except Exception:
                return None
    return None


def run_engine(engine: str, url: str, timeout: int = 150) -> tuple[object | None, EngineRun]:
    node = toolrunner.node_bin()
    if not node:
        return None, EngineRun(engine=engine, ref=url, status=EngineStatus.error,
                               error="node not installed")
    script = JS_DIR / RUNNERS[engine]
    if not (JS_DIR / "node_modules").exists() or not script.exists():
        return None, EngineRun(engine=engine, ref=url, status=EngineStatus.error,
                               error="engine runner or node_modules missing "
                                     "(run scripts/setup_tools.sh)")

    code, out, err = toolrunner.run([node, str(script), url], timeout=timeout, cwd=JS_DIR)
    env = _parse_envelope(out)
    if env is None:
        detail = (err or f"exit {code}, no result envelope").strip()[:500]
        return None, EngineRun(engine=engine, ref=url, status=EngineStatus.error, error=detail)
    if env.get("error"):
        return None, EngineRun(engine=engine, ref=url, status=EngineStatus.error,
                               error=str(env["error"])[:500])
    status_str = env.get("status", "error")
    status = EngineStatus(status_str) if status_str in ("clean", "violations", "error") else EngineStatus.error
    return env.get("data"), EngineRun(engine=engine, ref=url, status=status)


def scan_url(url: str, engines: tuple[str, ...] | None = None) -> tuple[dict, list[EngineRun]]:
    """Returns ({engine: raw_data|None}, [EngineRun, ...]) for one URL."""
    engines = engines or settings.web_engines
    raw: dict[str, object | None] = {}
    runs: list[EngineRun] = []
    for eng in engines:
        data, run = run_engine(eng, url)
        raw[eng] = data
        runs.append(run)
    return raw, runs
