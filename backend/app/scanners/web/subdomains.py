"""OSINT subdomain discovery — the results-generation front door.

Passive by default. Deny-by-default scoping: every discovered host is validated
against the job's allowlist before it can be crawled. Active DNS brute-force is
gated behind an explicit per-job attestation.

Sources (union, best-effort — a source being down never fails the job):
  • subfinder (ProjectDiscovery, passive)     — if vendored/on PATH
  • SSLMate Cert Spotter API                   — primary CT source (if token)
  • crt.sh                                     — cached best-effort CT fallback
Liveness via httpx (if present) else a light Python HEAD/GET probe.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from urllib.parse import urlparse

from ...config import settings
from . import toolrunner


def _bare_host(value: str) -> str:
    """Normalize any scope/host value to a bare, lowercased hostname.

    Tolerates bare hosts, ``*.wildcards``, ``host:port``, ``user@host`` and full
    URLs (``https://host/path``) — a user who pastes a URL into the scope field
    still gets a usable host. Returns ``""`` for empty/garbage input.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "://" in v:
        v = urlparse(v).netloc or v          # full URL → netloc
    else:
        v = v.split("/", 1)[0]               # bare host[:port]/path → host[:port]
    v = v.split("@")[-1]                      # drop any userinfo
    v = v.lstrip("*.")                        # wildcard cert entries
    v = v.split(":", 1)[0]                    # drop port
    return v.strip(".")


def host_in_scope(host: str, allowlist: list[str]) -> bool:
    h = _bare_host(host)
    if not h:
        return False
    for allowed in allowlist:
        a = _bare_host(allowed)
        if a and (h == a or h.endswith("." + a)):
            return True
    return False


# ── Sources ──────────────────────────────────────────────────────────────────

def _subfinder(domain: str) -> set[str]:
    path = toolrunner.find_tool("subfinder")
    if not path:
        return set()
    code, out, _ = toolrunner.run([path, "-silent", "-d", domain], timeout=180)
    if code != 0:
        return set()
    return {h.strip() for h in out.splitlines() if h.strip()}


def _certspotter(domain: str) -> set[str]:
    token = os.getenv("CERTSPOTTER_API_TOKEN", "")
    url = (f"https://api.certspotter.com/v1/issuances?domain={domain}"
           f"&include_subdomains=true&expand=dns_names")
    hdrs = {"User-Agent": settings.scan_user_agent}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hosts: set[str] = set()
    try:
        req = urllib.request.Request(url, headers=hdrs)
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        for row in data:
            for name in row.get("dns_names", []):
                hosts.add(name.lstrip("*."))
    except Exception:
        pass
    return hosts


def _crtsh(domain: str, retries: int = 2) -> set[str]:
    """crt.sh is rate-limited (~5/min/IP) and flaky — best-effort with backoff."""
    hosts: set[str] = set()
    url = f"https://crt.sh/?q=%25.{domain}&output=json"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": settings.scan_user_agent})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            for row in data:
                for name in (row.get("name_value", "") or "").split("\n"):
                    name = name.strip().lstrip("*.")
                    if name.endswith(domain):
                        hosts.add(name)
            break
        except Exception:
            time.sleep(2 * (attempt + 1))
    return hosts


# ── Liveness ─────────────────────────────────────────────────────────────────

def _httpx_live(hosts: list[str]) -> list[str]:
    path = toolrunner.find_tool("httpx")
    if not path:
        return _python_live(hosts)
    rl = str(settings.host_rate_limit_per_sec * 5)
    code, out, _ = toolrunner.run(
        [path, "-silent", "-json", "-rl", rl, "-timeout", "10"],
        timeout=240, input_text="\n".join(hosts),
    )
    live = []
    for line in out.splitlines():
        try:
            live.append(json.loads(line)["url"])
        except Exception:
            continue
    return live


def _python_live(hosts: list[str]) -> list[str]:
    live = []
    for h in hosts:
        for scheme in ("https", "http"):
            url = f"{scheme}://{h}"
            try:
                req = urllib.request.Request(
                    url, method="HEAD", headers={"User-Agent": settings.scan_user_agent}
                )
                urllib.request.urlopen(req, timeout=8)
                live.append(url)
                break
            except Exception:
                continue
    return live


# ── Entry point ──────────────────────────────────────────────────────────────

def discover(domain: str, allowlist: list[str], allow_active: bool = False) -> dict:
    """Returns {'live': [urls], 'discovered': [hosts], 'out_of_scope': [hosts],
    'sources': {name: count}}. `allow_active` is reserved for a future gated
    brute-force source; passive-only today."""
    # Preserve the full authority (host[:port]) and scheme for probing/crawling —
    # only SCOPE MATCHING is port-agnostic (via _bare_host). Dropping the port here
    # would make a target on a non-standard port unreachable.
    raw = (domain or "").strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    scheme = parsed.scheme or "https"
    authority = (parsed.netloc or "").split("@")[-1].lower()   # host[:port]
    host_only = _bare_host(authority)                          # bare host for CT lookups

    sources: dict[str, int] = {}
    if not authority:
        return {"live": [], "discovered": [], "in_scope": [],
                "out_of_scope": [], "sources": sources}

    hosts: set[str] = {authority}
    sf = _subfinder(host_only); sources["subfinder"] = len(sf); hosts |= sf
    cs = _certspotter(host_only); sources["certspotter"] = len(cs); hosts |= cs
    ct = _crtsh(host_only); sources["crt.sh"] = len(ct); hosts |= ct

    # Deny-by-default scoping — BUT the entered target is always in scope: it's the
    # thing the user explicitly asked to audit. Extra allowlist entries only ADD
    # sibling subdomains. Mirrors scripts/run_local_scan.py ([host] + allow).
    effective_allow = [authority] + list(allowlist or [])

    in_scope = sorted(h for h in hosts if host_in_scope(h, effective_allow))
    out_of_scope = sorted(h for h in hosts if not host_in_scope(h, effective_allow))

    live = _httpx_live(in_scope) if in_scope else []
    if not live and host_in_scope(authority, effective_allow):
        live = [f"{scheme}://{authority}"]

    return {
        "live": live,
        "discovered": sorted(hosts),
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "sources": sources,
    }
