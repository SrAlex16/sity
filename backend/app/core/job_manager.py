"""job_manager.py — background job execution with session SSE notifications."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

_singleton: "JobManager | None" = None
_singleton_lock = threading.Lock()


@dataclass
class Job:
    job_id: str
    tool_name: str
    session_id: str
    status: str  # "running" | "done" | "error"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result_text: str = ""
    error: str = ""


class JobManager:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sity-bg"
        )
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        tool_name: str,
        session_id: str,
        fn: Callable[..., Any],
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        on_done: Callable[[Job], None] | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, tool_name=tool_name, session_id=session_id, status="running")
        with self._lock:
            self._jobs[job_id] = job

        def _run() -> None:
            try:
                result = fn(*args, **(kwargs or {}))
                with self._lock:
                    job.status = "done"
                    job.result_text = str(result) if result is not None else ""
            except Exception as exc:
                with self._lock:
                    job.status = "error"
                    job.error = str(exc)
            finally:
                if on_done is not None:
                    try:
                        on_done(job)
                    except Exception:
                        pass

        self._executor.submit(_run)
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_session(self, session_id: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.session_id == session_id]

    def active_count(self, session_id: str) -> int:
        with self._lock:
            return sum(
                1 for j in self._jobs.values()
                if j.session_id == session_id and j.status == "running"
            )


def get_job_manager() -> JobManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from app.settings.config_loader import load_default_config
                cfg = load_default_config()
                max_workers = int(
                    cfg.get("ai", {}).get("background", {}).get("max_workers", 2)
                )
                _singleton = JobManager(max_workers=max_workers)
    return _singleton
