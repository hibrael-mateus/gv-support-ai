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
import tempfile
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from .settings import DB_PATH

log = logging.getLogger("gvsupport.web")

ENABLED = os.getenv("GV_WEB_MODE", "") == "1"
WEB_DIR = Path(os.getenv("GV_WEB_DIR", "")) if os.getenv("GV_WEB_DIR") else None
TOKEN_HOURS = 12
OPEN_PATHS = {"/health", "/auth/login"}
BLOCKED = ("/tools/execute", "/backup/", "/settings/secret", "/ai/embedded/", "/drive/connect", "/drive/disconnect",
           "/logs/path")
_fails: dict[str, list[float]] = {}


def _key() -> bytes:
    return hashlib.sha256(("gv-web:" + os.getenv("GV_WEB_PASSWORD", "")).encode()).digest()


def issue_token() -> str:
    exp = str(int(time.time()) + TOKEN_HOURS * 3600)
    return exp + "." + hmac.new(_key(), exp.encode(), hashlib.sha256).hexdigest()


def valid_token(token: str) -> bool:
    exp, _, sig = (token or "").partition(".")
    good = hmac.new(_key(), exp.encode(), hashlib.sha256).hexdigest()
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, good)


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def login(request: Request, password: str) -> dict[str, str]:
    """Constant-time check, 10 failures per 15 minutes per address."""
    ip, now = _client(request), time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 10:
        raise PermissionError("Muitas tentativas. Aguarde 15 minutos.")
    expected = os.getenv("GV_WEB_PASSWORD", "")
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        _fails[ip] = recent + [now]
        time.sleep(1)
        raise PermissionError("Senha incorreta.")
    _fails.pop(ip, None)
    return {"token": issue_token()}


def _static_file(path: str) -> bool:
    if not WEB_DIR:
        return False
    target = (WEB_DIR / (path.lstrip("/") or "index.html")).resolve()
    return target.is_file() and WEB_DIR.resolve() in target.parents


async def guard(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in OPEN_PATHS or (request.method == "GET" and _static_file(path)):
        return await call_next(request)
    if not valid_token(request.headers.get("x-gv-token", "")):
        return JSONResponse({"detail": "Não autorizado"}, status_code=401)
    if path.startswith(BLOCKED) or (path == "/settings" and request.method != "GET"):
        return JSONResponse({"detail": "Indisponível na versão web: o servidor é configurado pelo administrador."},
                            status_code=403)
    return await call_next(request)


# ---- persistence on hosts with ephemeral disks -------------------------------------
DATASET = os.getenv("GV_HF_DATASET", "")
_DB_NAME = "gv_support_ai.db"


def restore_db() -> None:
    if not DATASET or DB_PATH.exists():
        return
    try:
        from huggingface_hub import hf_hub_download

        src = hf_hub_download(DATASET, _DB_NAME, repo_type="dataset", token=os.getenv("HF_TOKEN"))
        shutil.copyfile(src, DB_PATH)
        log.info("database restored from dataset")
    except Exception as exc:  # first run: nothing saved yet
        log.warning("database not restored: %s", type(exc).__name__)


def snapshot_db() -> None:
    from huggingface_hub import HfApi

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / _DB_NAME
        with sqlite3.connect(DB_PATH) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        HfApi(token=os.getenv("HF_TOKEN")).upload_file(path_or_fileobj=str(copy), path_in_repo=_DB_NAME,
                                                       repo_id=DATASET, repo_type="dataset",
                                                       commit_message="snapshot")


def _signature() -> tuple:
    return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in (DB_PATH, Path(f"{DB_PATH}-wal")))


def start_snapshots(minutes: int = 10) -> None:
    if not DATASET:
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
