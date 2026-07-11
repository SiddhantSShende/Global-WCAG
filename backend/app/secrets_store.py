"""Secret store — app credentials & authenticated-scan logins never touch the DB
in plaintext and are purged after the job.

Two backends behind one interface:
  • VaultStore        — HashiCorp Vault (KV v2) when VAULT_ADDR is set (prod).
  • LocalEncryptedStore — Fernet-encrypted blobs on disk (dev / single host).

Flow: the API stores the caller's credentials → gets a HANDLE → only the handle
is persisted on the job. The worker fetches the secret by handle at runtime and
`purge()`s it when the job finishes. Secrets are never logged.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .config import settings


class SecretUnavailable(RuntimeError):
    pass


# ── Local encrypted store ────────────────────────────────────────────────────

class LocalEncryptedStore:
    backend = "local-fernet"

    def __init__(self) -> None:
        self.dir = settings.artifacts_dir / ".secrets"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fernet = self._load_fernet()

    def _load_fernet(self):
        try:
            from cryptography.fernet import Fernet
        except Exception as exc:  # noqa: BLE001
            raise SecretUnavailable(
                "cryptography not installed and no Vault configured — cannot store "
                f"credentials securely: {exc}")
        key = os.getenv("A11Y_SECRET_KEY")
        if not key:
            key_file = self.dir / "fernet.key"
            if key_file.exists():
                key = key_file.read_text().strip()
            else:
                key = Fernet.generate_key().decode()
                key_file.write_text(key)
                try:
                    os.chmod(key_file, 0o600)
                except Exception:
                    pass
        return Fernet(key.encode() if isinstance(key, str) else key)

    def put(self, job_id: str, data: dict) -> str:
        handle = f"{job_id}/{uuid.uuid4().hex}"
        blob = self._fernet.encrypt(json.dumps(data).encode())
        (self.dir / f"{handle.replace('/', '_')}.enc").write_bytes(blob)
        return handle

    def get(self, handle: str) -> dict:
        p = self.dir / f"{handle.replace('/', '_')}.enc"
        if not p.exists():
            raise SecretUnavailable(f"secret {handle} not found (purged or expired)")
        return json.loads(self._fernet.decrypt(p.read_bytes()).decode())

    def purge(self, job_id: str) -> int:
        n = 0
        for p in self.dir.glob(f"{job_id}_*.enc"):
            p.unlink(missing_ok=True)
            n += 1
        return n


# ── Vault store ──────────────────────────────────────────────────────────────

class VaultStore:
    backend = "vault"

    def __init__(self) -> None:
        import hvac  # noqa: F401
        self._hvac = __import__("hvac")
        self.client = self._hvac.Client(url=settings.vault_addr, token=settings.vault_token)
        self.mount = "secret"

    def _path(self, handle: str) -> str:
        return f"a11y/{handle}"

    def put(self, job_id: str, data: dict) -> str:
        handle = f"{job_id}/{uuid.uuid4().hex}"
        self.client.secrets.kv.v2.create_or_update_secret(
            path=self._path(handle), secret=data, mount_point=self.mount)
        return handle

    def get(self, handle: str) -> dict:
        resp = self.client.secrets.kv.v2.read_secret_version(
            path=self._path(handle), mount_point=self.mount)
        return resp["data"]["data"]

    def purge(self, job_id: str) -> int:
        # Best-effort: delete metadata for the job's secrets.
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=self._path(job_id), mount_point=self.mount)
        except Exception:
            pass
        return 1


def _make_store():
    if settings.vault_addr and settings.vault_token:
        try:
            return VaultStore()
        except Exception as exc:  # noqa: BLE001
            print(f"[secrets] Vault unavailable ({exc}); using local encrypted store.")
    return LocalEncryptedStore()


_store = None


def store():
    global _store
    if _store is None:
        _store = _make_store()
    return _store


# Fields that must NEVER be persisted on the job in plaintext.
SENSITIVE_KEYS = ("credentials", "password", "secret", "token", "login_steps")


def externalize(job_id: str, inputs: dict) -> dict:
    """Move sensitive fields out of `inputs` into the secret store; return a copy
    of inputs with those fields replaced by a single `secret_handle`."""
    sensitive = {k: inputs[k] for k in SENSITIVE_KEYS if k in inputs}
    if not sensitive:
        return dict(inputs)
    handle = store().put(job_id, sensitive)
    clean = {k: v for k, v in inputs.items() if k not in SENSITIVE_KEYS}
    clean["secret_handle"] = handle
    return clean


def resolve(inputs: dict) -> dict:
    """Fetch the secret bundle referenced by inputs['secret_handle'] (or {})."""
    handle = (inputs or {}).get("secret_handle")
    if not handle:
        return {}
    try:
        return store().get(handle)
    except SecretUnavailable:
        return {}
