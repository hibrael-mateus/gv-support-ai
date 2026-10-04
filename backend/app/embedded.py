"""Embedded AI engine: llama.cpp's `llama-server` ships inside the installer and runs a GGUF model
downloaded once into the user's data folder. Nothing else to install, no external service, no API key:
it runs on the analyst's own computer, on the CPU (a GPU is not required).
"""
from __future__ import annotations

import atexit
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .settings import DATA_DIR, LOG_DIR

MODEL_DIR = DATA_DIR / "Models"
HF = "https://huggingface.co"
MODELS: dict[str, dict[str, Any]] = {
    "qwen2.5-3b": {"label": "Qwen2.5 3B (recomendado · ~2 GB · 8 GB de RAM)",
                   "url": f"{HF}/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"},
    "qwen2.5-7b": {"label": "Qwen2.5 7B (mais preciso · ~4,7 GB · 16 GB de RAM)",
                   "url": f"{HF}/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"},
    "qwen2.5-0.5b": {"label": "Qwen2.5 0.5B (leve · ~0,4 GB · máquinas antigas)",
                     "url": f"{HF}/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"},
}
DEFAULT_MODEL = "qwen2.5-3b"
CTX = 8192  # RAG prompts carry several evidence excerpts; one slot gets the whole context


def model_path(key: str) -> Path:
    return MODEL_DIR / MODELS.get(key, MODELS[DEFAULT_MODEL])["url"].rsplit("/", 1)[1]


def is_gguf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def server_binary() -> Path | None:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    for p in (os.getenv("GV_LLAMA_SERVER", ""), base / "llama" / name):
        if p and Path(p).is_file():
            return Path(p)
    return None


def download(key: str, ctx=None) -> str:
    """Download a catalog model, checking it against the SHA-256 Hugging Face publishes for the file."""
    if key not in MODELS:
        raise ValueError("Modelo desconhecido")
    dest = model_path(key)
    if is_gguf(dest):
        return str(dest)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    digest = hashlib.sha256()
    # ponytail: restarts from zero if interrupted; add Range resume if slow links make that painful.
    with httpx.stream("GET", MODELS[key]["url"], follow_redirects=True, timeout=httpx.Timeout(60, read=300)) as r:
        r.raise_for_status()
        first = r.history[0].headers if r.history else r.headers
        expected = first.get("x-linked-etag", "").strip('"').lower()
        total = int(first.get("x-linked-size") or r.headers.get("content-length") or 0)
        done = 0
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if ctx:
                    ctx.progress(done, total, f"Baixando modelo: {done >> 20} de {total >> 20} MB")
    if len(expected) == 64 and digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError("O arquivo baixado não confere com a assinatura publicada. Tente novamente.")
    if not is_gguf(part):
        part.unlink(missing_ok=True)
        raise RuntimeError("O arquivo baixado não é um modelo GGUF válido.")
    part.replace(dest)
    return str(dest)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill_with_parent(proc: subprocess.Popen) -> None:
    """Windows job object: if the backend dies (even killed), the engine dies with it."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(proc._handle))
    _Engine.job = job  # keep the handle open for the backend's lifetime


class _Engine:
    lock = threading.Lock()
    proc: subprocess.Popen | None = None
    model = ""
    url = ""
    key = ""
    job = None

    @classmethod
    def ensure(cls, model: Path) -> tuple[str, str]:
        with cls.lock:
            if cls.proc and cls.proc.poll() is None and cls.model == str(model):
                return cls.url, cls.key
            cls.stop_locked()
            binary = server_binary()
            if not binary:
                raise RuntimeError("Motor de IA embutido não encontrado nesta instalação. Reinstale o GV Support AI.")
            port, key = _free_port(), secrets.token_urlsafe(24)
            log = open(LOG_DIR / "ia-embutida.log", "ab")
            cmd = [str(binary), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", str(CTX),
                   "-np", "1", "--no-webui", "--api-key", key]
            flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            cls.proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags,
                                        cwd=binary.parent)
            _kill_with_parent(cls.proc)
            cls.model, cls.url, cls.key = str(model), f"http://127.0.0.1:{port}/v1", key
            deadline = time.time() + 180
            while time.time() < deadline:
                if cls.proc.poll() is not None:
                    raise RuntimeError("O motor de IA embutido encerrou ao carregar o modelo. Veja Logs/ia-embutida.log "
                                       "(memória RAM insuficiente é a causa mais comum: escolha um modelo menor).")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                        return cls.url, cls.key
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            cls.stop_locked()
            raise RuntimeError("O motor de IA embutido demorou demais para carregar o modelo.")

    @classmethod
    def stop_locked(cls) -> None:
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        cls.proc = None

    @classmethod
    def stop(cls) -> None:
        with cls.lock:
            cls.stop_locked()


ensure = _Engine.ensure
stop = _Engine.stop
atexit.register(stop)
