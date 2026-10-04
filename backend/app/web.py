"""Website mode (GV_WEB_MODE=1): the same backend serves the UI to browsers from a shared server.

- Access needs the team password (GV_WEB_PASSWORD); the browser gets a signed token that expires.
- Anything that touches the server's own disk or configuration from the UI is blocked
  (running scripts, backups, provider keys, Drive login): the server is configured only by its secrets.
- Optional persistence for free hosts with ephemeral disks: the SQLite file is restored from and
  snapshotted to a private Hugging Face dataset (GV_HF_DATASET + HF_TOKEN).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import shutil
import sqlite3
from contextlib import closing
import tempfile
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from .settings import CONFIG_PATH, DB_PATH

log = logging.getLogger("gvsupport.web")

ENABLED = os.getenv("GV_WEB_MODE", "") == "1"
WEB_DIR = Path(os.getenv("GV_WEB_DIR", "")) if os.getenv("GV_WEB_DIR") else None
TOKEN_HOURS = 12
OPEN_PATHS = {"/health", "/auth/login", "/auth/admin"}
BLOCKED = ("/tools/execute", "/backup/", "/settings/secret", "/ai/embedded/", "/drive/connect", "/drive/disconnect",
           "/logs/path")
# Administração: needs the admin password (GV_ADMIN_PASSWORD); without it these stay closed on the site.
ADMIN_ONLY = (("PUT", "/settings"), ("POST", "/sources/sync"), ("POST", "/sources/upload"), ("DELETE", "/sources/"))
_fails: dict[str, list[float]] = {}


def _key() -> bytes:
    return hashlib.sha256(("gv-web:" + os.getenv("GV_WEB_PASSWORD", "")).encode()).digest()


def issue_token(role: str = "team") -> str:
    head = f"{int(time.time()) + TOKEN_HOURS * 3600}.{role}"
    return head + "." + hmac.new(_key(), head.encode(), hashlib.sha256).hexdigest()


def token_role(token: str) -> str:
    """"team", "admin" or "" when the token is missing, forged or expired."""
    head, _, sig = (token or "").rpartition(".")
    exp, _, role = head.partition(".")
    good = hmac.new(_key(), head.encode(), hashlib.sha256).hexdigest()
    ok = exp.isdigit() and int(exp) > time.time() and role in ("team", "admin") and hmac.compare_digest(sig, good)
    return role if ok else ""


def valid_token(token: str) -> bool:
    return bool(token_role(token))


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def login(request: Request, password: str, admin: bool = False) -> dict[str, str]:
    """Constant-time check, 10 failures per 15 minutes per address (team and admin share the counter)."""
    ip, now = _client(request), time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 10:
        raise PermissionError("Muitas tentativas. Aguarde 15 minutos.")
    expected = os.getenv("GV_ADMIN_PASSWORD" if admin else "GV_WEB_PASSWORD", "")
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        _fails[ip] = recent + [now]
        time.sleep(1)
        if admin and not expected:
            raise PermissionError("Administração desativada: defina GV_ADMIN_PASSWORD no servidor.")
        raise PermissionError("Senha incorreta.")
    _fails.pop(ip, None)
    return {"token": issue_token("admin" if admin else "team"), "role": "admin" if admin else "team"}


def _static_file(path: str) -> bool:
    if not WEB_DIR:
        return False
    target = (WEB_DIR / (path.lstrip("/") or "index.html")).resolve()
    return target.is_file() and WEB_DIR.resolve() in target.parents


async def guard(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in OPEN_PATHS or (request.method == "GET" and _static_file(path)):
        return await call_next(request)
    role = token_role(request.headers.get("x-gv-token", ""))
    if not role:
        return JSONResponse({"detail": "Não autorizado"}, status_code=401)
    if path.startswith(BLOCKED):
        return JSONResponse({"detail": "Indisponível na versão web: o servidor é configurado pelo administrador."},
                            status_code=403)
    if role != "admin" and any(request.method == m and (path == p or p.endswith("/") and path.startswith(p))
                               for m, p in ADMIN_ONLY):
        return JSONResponse({"detail": "Somente a Administração pode fazer isso. Entre em Administração com a senha."},
                            status_code=403)
    request.state.role = role
    return await call_next(request)


# ---- persistence on hosts with ephemeral disks -------------------------------------
DATASET = os.getenv("GV_HF_DATASET", "")
_DB_NAME = "gv_support_ai.db"


def _dataset() -> str:
    """GV_HF_DATASET, or <hf user>/gv-support-ai-data when only HF_TOKEN is set (created private on first use)."""
    global DATASET
    if not DATASET and os.getenv("HF_TOKEN"):
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=os.environ["HF_TOKEN"])
            name = f"{api.whoami()['name']}/gv-support-ai-data"
            api.create_repo(name, repo_type="dataset", private=True, exist_ok=True)
            DATASET = name
        except Exception as exc:
            log.warning("persistence disabled: %s", type(exc).__name__)
    return DATASET


def restore_db() -> None:
    if not _dataset() or DB_PATH.exists():
        return
    try:
        from huggingface_hub import hf_hub_download

        src = hf_hub_download(DATASET, _DB_NAME, repo_type="dataset", token=os.getenv("HF_TOKEN"))
        shutil.copyfile(src, DB_PATH)
        log.info("database restored from dataset")
        try:
            shutil.copyfile(hf_hub_download(DATASET, CONFIG_PATH.name, repo_type="dataset", token=os.getenv("HF_TOKEN")),
                            CONFIG_PATH)
        except Exception:
            pass  # settings never changed in Administração yet
    except Exception as exc:  # first run: nothing saved yet
        log.warning("database not restored: %s", type(exc).__name__)


def snapshot_db() -> None:
    from huggingface_hub import HfApi

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / _DB_NAME
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
        api = HfApi(token=os.getenv("HF_TOKEN"))
        api.upload_file(path_or_fileobj=str(copy), path_in_repo=_DB_NAME, repo_id=DATASET, repo_type="dataset",
                        commit_message="snapshot")
        if CONFIG_PATH.exists():
            api.upload_file(path_or_fileobj=str(CONFIG_PATH), path_in_repo=CONFIG_PATH.name, repo_id=DATASET,
                            repo_type="dataset", commit_message="settings")


def _signature() -> tuple:
    return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in (DB_PATH, Path(f"{DB_PATH}-wal"), CONFIG_PATH))


def start_snapshots(minutes: int = 10) -> None:
    if not _dataset():
        return

    def loop():
        last = _signature()
        while True:
            time.sleep(minutes * 60)
            if (now := _signature()) != last:
                try:
                    snapshot_db()
                    last = now
                except Exception as exc:
                    log.warning("snapshot failed: %s", type(exc).__name__)

    threading.Thread(target=loop, daemon=True, name="db-snapshot").start()
