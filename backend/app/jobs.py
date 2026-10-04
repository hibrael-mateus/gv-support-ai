"""Tiny background job runner so indexing never blocks the UI."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


class JobContext:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def progress(self, done: int, total: int, message: str = "") -> None:
        with _lock:
            job = _jobs[self.job_id]
            job.update(done=done, total=total, message=message,
                       percent=round(100 * done / total, 1) if total else 0)

    def log(self, line: str) -> None:
        with _lock:
            logs = _jobs[self.job_id]["log"]
            logs.append(line)
            del logs[:-200]


def start(kind: str, fn: Callable[[JobContext], Any]) -> dict[str, Any]:
    with _lock:
        running = next((j for j in _jobs.values() if j["kind"] == kind and j["state"] == "running"), None)
        if running:
            return dict(running)
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"id": job_id, "kind": kind, "state": "running", "done": 0, "total": 0, "percent": 0,
                         "message": "Iniciando…", "log": [], "result": None, "error": "", "started_at": time.time()}

    def run():
        ctx = JobContext(job_id)
        try:
            result = fn(ctx)
            with _lock:
                _jobs[job_id].update(state="done", result=result, percent=100, message="Concluído")
        except Exception as exc:
            with _lock:
                _jobs[job_id].update(state="error", error=str(exc), message="Falhou")
                _jobs[job_id]["log"].append(traceback.format_exc(limit=3))

    threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
    return get(job_id)


def get(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        return {**job, "log": list(job["log"])} if job else {}


def latest(kind: str) -> dict[str, Any]:
    with _lock:
        jobs = [j for j in _jobs.values() if j["kind"] == kind]
    return get(max(jobs, key=lambda j: j["started_at"])["id"]) if jobs else {}
