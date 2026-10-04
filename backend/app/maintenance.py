"""Updates check, backup export/import and local (opt-in, read-only) script execution."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .db import connection, reset_for_tests
from .security import classify_powershell, mask_secrets
from .settings import ATTACH_DIR, BACKUP_DIR, CONFIG_PATH, DB_PATH, load_config


# ---- updates ---------------------------------------------------------------
def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in "".join(c for c in v.lstrip("vV") if c.isdigit() or c == ".").split(".") if x)


def check_updates() -> dict[str, Any]:
    """GitHub Releases (or a self-hosted manifest). The installer upgrades in place; user data in
    %LOCALAPPDATA% is untouched, so frontend, backend, agents and prompts are replaced without data loss."""
    cfg = load_config()
    repo = cfg.get("update_repo", "")
    info = {"current": __version__, "latest": __version__, "available": False, "url": "", "notes": "", "error": ""}
    try:
        r = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10,
                      headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        latest = data.get("tag_name", "")
        asset = next((a["browser_download_url"] for a in data.get("assets", []) if a["name"].lower().endswith("setup.exe")),
                     data.get("html_url", ""))
        info.update(latest=latest.lstrip("v"), url=asset, notes=data.get("body", "")[:4000],
                    available=_ver(latest) > _ver(__version__))
    except Exception as exc:
        info["error"] = f"Não foi possível verificar atualizações: {exc}"
    return info


# ---- backup ----------------------------------------------------------------
def export_backup(target_dir: Path = BACKUP_DIR) -> Path:
    """Database + config + attachments. Secrets live in Windows Credential Manager and are never included."""
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"GVSupportAI-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "gv_support_ai.db"
        with connection() as conn, closing(sqlite3.connect(snap)) as dst:
            conn.backup(dst)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, "gv_support_ai.db")
            if CONFIG_PATH.exists():
                zf.writestr("config.json", mask_secrets(CONFIG_PATH.read_text(encoding="utf-8")))
            for f in ATTACH_DIR.rglob("*"):
                if f.is_file():
                    zf.write(f, f"Attachments/{f.relative_to(ATTACH_DIR).as_posix()}")
            zf.writestr("manifest.json", json.dumps({"app": "GV Support AI", "version": __version__,
                                                     "created_at": datetime.now().isoformat()}))
    return out


def import_backup(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        if "gv_support_ai.db" not in names or "manifest.json" not in names:
            raise ValueError("Arquivo não é um backup do GV Support AI.")
        with tempfile.TemporaryDirectory() as tmp:
            zf.extract("gv_support_ai.db", tmp)
            src = Path(tmp) / "gv_support_ai.db"
            with closing(sqlite3.connect(src)) as check:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup corrompido.")
            safety = export_backup()
            with closing(sqlite3.connect(src)) as s, closing(sqlite3.connect(DB_PATH)) as d:
                s.backup(d)
        if "config.json" in names:
            CONFIG_PATH.write_bytes(zf.read("config.json"))
        for n in names:
            if n.startswith("Attachments/") and not n.endswith("/"):
                dest = (ATTACH_DIR / n.removeprefix("Attachments/")).resolve()
                if ATTACH_DIR.resolve() in dest.parents:  # zip-slip guard
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(n))
    reset_for_tests()
    return {"restored": True, "safety_backup": str(safety)}


# ---- local execution (explicit opt-in) ------------------------------------
def run_powershell(script: str, timeout: int = 300) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("allow_local_execution"):
        raise PermissionError("Execução local desabilitada. Habilite em Configurações > Privacidade.")
    danger = classify_powershell(script)
    if danger.dangerous:
        raise PermissionError("Execução bloqueada: o script contém comandos que alteram o ambiente ("
                              + "; ".join(danger.reasons) + "). Execute manualmente após revisão.")
    if sys.platform != "win32":
        raise RuntimeError("Execução de PowerShell disponível somente no Windows.")
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
        f.write(script)
        path = f.name
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                              capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"exit_code": proc.returncode, "stdout": mask_secrets(proc.stdout[-200_000:]),
                "stderr": mask_secrets(proc.stderr[-50_000:])}
    finally:
        Path(path).unlink(missing_ok=True)

