"""Crawl a host into a capped page inventory.

Two paths, same output:
  • katana (ProjectDiscovery) with CONSERVATIVE caps when the binary is vendored.
  • a self-contained polite Python BFS crawler otherwise — honors robots.txt,
    same-origin, depth + page caps, and a per-host rate limit.

We NEVER crawl at katana's 150 req/s default; caps come from Settings.
"""
from __future__ import annotations

import re
import time
import urllib.request
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from ...config import settings
from . import toolrunner

_BINARY_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".gz",
               ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".css", ".js", ".ico",
               ".xml", ".json", ".rss")
_SKIP = ("mailto:", "tel:", "javascript:", "/logout", "/signout", "/sign-out")
_HREF_RE = re.compile(r'href=["\']([^"\'#]+)["\']', re.IGNORECASE)


def _normalize(url: str) -> str:
    url = url.split("#")[0].split("?")[0]
    return url.rstrip("/")


def _wanted(url: str) -> bool:
    low = url.lower()
    if any(s in low for s in _SKIP):
        return False
    return not any(low.endswith(ext) for ext in _BINARY_EXT)


# ── katana ───────────────────────────────────────────────────────────────────

def _katana(base_url: str) -> list[str] | None:
    path = toolrunner.find_tool("katana")
    if not path:
        return None
    cmd = [
        path, "-silent", "-u", base_url,
        "-depth", str(settings.crawl_max_depth),
        "-field", "url",
        "-strategy", "breadth-first",
        "-crawl-scope", urlparse(base_url).netloc,   # same-origin
        "-max-domain-pages", str(settings.max_pages_per_host),
        "-host-rate-limit", str(settings.host_rate_limit_per_sec),
        "-crawl-duration", "10m",
    ]
    code, out, _ = toolrunner.run(cmd, timeout=700)
    if code != 0:
        return None
    seen, urls = set(), []
    for u in out.splitlines():
        u = _normalize(u.strip())
        if u and u not in seen and _wanted(u):
            seen.add(u)
            urls.append(u)
        if len(urls) >= settings.max_pages_per_host:
            break
    return urls or [base_url]


# ── polite Python crawler ────────────────────────────────────────────────────

def _robots(base_url: str) -> urllib.robotparser.RobotFileParser | None:
    if not settings.honor_robots_txt:
        return None
    rp = urllib.robotparser.RobotFileParser()
    parsed = urlparse(base_url)
    rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return None
    return rp


def _fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": settings.scan_user_agent})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" not in ctype:
                return None
            return resp.read(2_000_000).decode("utf-8", "ignore")
    except Exception:
        return None


def _python_crawl(base_url: str) -> list[str]:
    origin = urlparse(base_url).netloc
    rp = _robots(base_url)
    ua = settings.scan_user_agent
    delay = 1.0 / max(1, settings.host_rate_limit_per_sec)

    seen = {_normalize(base_url)}
    order = [_normalize(base_url)]
    queue = [(_normalize(base_url), 0)]

    while queue and len(order) < settings.max_pages_per_host:
        url, depth = queue.pop(0)
        if rp is not None and not rp.can_fetch(ua, url):
            continue
        html = _fetch(url)
        time.sleep(delay)
        if not html or depth >= settings.crawl_max_depth:
            continue
        for href in _HREF_RE.findall(html):
            nxt = _normalize(urljoin(url, href))
            if (nxt and nxt not in seen and _wanted(nxt)
                    and urlparse(nxt).netloc == origin):
                seen.add(nxt)
                order.append(nxt)
                queue.append((nxt, depth + 1))
                if len(order) >= settings.max_pages_per_host:
                    break
    return order


def crawl(base_url: str) -> list[str]:
    urls = _katana(base_url)
    if urls is None:
        urls = _python_crawl(base_url)
    return urls or [base_url]
