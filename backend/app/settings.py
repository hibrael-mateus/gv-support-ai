"""Paths, persistent (non-secret) configuration and secret storage.

Mutable data always lives under %LOCALAPPDATA%\\GVSupportAI, never under Program Files.
Secrets (API keys, Google OAuth token) go to the OS credential store
(Windows Credential Manager via `keyring`), never to config.json, logs or backups.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

APP_NAME = "GV Support AI"

# The authorized knowledge root. Overridable only by environment variable, never from the UI,
# so an analyst cannot point the RAG at another Drive area.
ALLOWED_GOOGLE_DRIVE_FOLDER_ID = os.getenv(
    "ALLOWED_GOOGLE_DRIVE_FOLDER_ID", "1RMbftBX58SM2PblBpw8vVaRoBF8sK_3c"
)

_local = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
DATA_DIR = Path(os.getenv("GV_SUPPORT_DATA_DIR", Path(_local) / "GVSupportAI"))
CACHE_DIR = DATA_DIR / "Cache"
LOG_DIR = DATA_DIR / "Logs"
ATTACH_DIR = DATA_DIR / "Attachments"
BACKUP_DIR = DATA_DIR / "Backups"
DB_PATH = DATA_DIR / "gv_support_ai.db"
CONFIG_PATH = DATA_DIR / "config.json"

for _d in (DATA_DIR, CACHE_DIR, LOG_DIR, ATTACH_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULTS: dict[str, Any] = {
    "setup_completed": False,
    "theme": "system",  # light | dark | system
    "llm_provider": "ollama",  # ollama | openai_compatible | gemini | groq | custom
    "ollama_url": "http://127.0.0.1:11434",
    "llm_model": "",  # empty = first installed Ollama model
    "embedding_model": "nomic-embed-text",
    "openai_base_url": "https://api.openai.com/v1",
    "custom_base_url": "",
    "temperature": 0.2,
    "google_client_secret_path": "",
    "auto_sync_minutes": 0,  # 0 = manual
    "internet_enabled": True,
    "allow_local_execution": False,  # explicit opt-in, read-only scripts only
    "update_repo": "hibrael-mateus/gv-support-ai",
    "chunk_size": 1200,
}

_lock = threading.Lock()


def load_config() -> dict[str, Any]:
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return data


def save_config(changes: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        data = load_config()
        data.update({k: v for k, v in changes.items() if k in DEFAULTS})
        CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


# ---- secrets -------------------------------------------------------------
SECRET_SERVICE = "GVSupportAI"
_memory_secrets: dict[str, str] = {}  # used only when no OS keyring backend exists (tests/CI)


def _keyring():
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
        return keyring
    except Exception:
        return None


def set_secret(name: str, value: str) -> None:
    kr = _keyring()
    if kr is None:
        _memory_secrets[name] = value
    elif value:
        kr.set_password(SECRET_SERVICE, name, value)
    else:
        try:
            kr.delete_password(SECRET_SERVICE, name)
        except Exception:
            pass


def get_secret(name: str) -> str:
    kr = _keyring()
    if kr is None:
        return _memory_secrets.get(name, "")
    try:
        return kr.get_password(SECRET_SERVICE, name) or ""
    except Exception:
        return ""
