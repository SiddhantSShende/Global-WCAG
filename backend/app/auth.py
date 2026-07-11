"""RBAC — API-key → role, with a role hierarchy and FastAPI dependencies.

Roles (ascending): viewer < reviewer < operator < admin.
  • viewer   — read status, download reports, view metrics
  • reviewer — + submit review verdicts, rebuild reports
  • operator — + create scan jobs
  • admin    — + read the audit log / manage

When `auth_enabled` is False (dev default), every request is 'admin' so the
platform runs out of the box; production sets `auth_enabled=true` + `api_keys`.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from .config import settings

ROLE_LEVEL = {"viewer": 1, "reviewer": 2, "operator": 3, "admin": 4}


def resolve_role(api_key: str | None) -> str:
    if not settings.auth_enabled:
        return "admin"
    if not api_key or api_key not in settings.api_keys:
        raise HTTPException(401, "invalid or missing X-API-Key")
    role = settings.api_keys[api_key]
    if role not in ROLE_LEVEL:
        raise HTTPException(403, f"unknown role '{role}' for key")
    return role


def _actor(api_key: str | None, role: str) -> str:
    tag = (api_key or "dev")[:6]
    return f"{role}:{tag}"


def require_role(min_role: str):
    def dependency(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
        role = resolve_role(x_api_key)
        if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL[min_role]:
            raise HTTPException(403, f"this action requires the '{min_role}' role")
        return {"role": role, "actor": _actor(x_api_key, role)}
    return dependency
