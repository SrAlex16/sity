"""Tests for JobManager — background job execution and tracking."""
import threading
import time

import pytest

from app.core.job_manager import Job, JobManager


def _manager() -> JobManager:
    return JobManager(max_workers=2)


def test_submit_and_status_done() -> None:
    """submit() returns a job_id and the job eventually reaches 'done'."""
    mgr = _manager()
    done_event = threading.Event()

    def _work() -> str:
        return "resultado"

    job_id = mgr.submit(
        tool_name="test_tool",
        session_id="sess_1",
        fn=_work,
        on_done=lambda _j: done_event.set(),
    )

    assert done_event.wait(timeout=3), "Job did not complete in time"
    job = mgr.get(job_id)
    assert job is not None
    assert job.status == "done"
    assert job.result_text == "resultado"


def test_on_done_callback_receives_job() -> None:
    """on_done callback is called with the completed Job object."""
    mgr = _manager()
    received: list[Job] = []
    ev = threading.Event()

    def _work() -> None:
        pass

    def _on_done(job: Job) -> None:
        received.append(job)
        ev.set()

    job_id = mgr.submit(tool_name="callback_tool", session_id="sess_cb", fn=_work, on_done=_on_done)

    assert ev.wait(timeout=3)
    assert len(received) == 1
    assert received[0].job_id == job_id
    assert received[0].status == "done"


def test_list_for_session_filters_by_session() -> None:
    """list_for_session returns only jobs for the given session."""
    mgr = _manager()
    events = [threading.Event() for _ in range(3)]

    for i, ev in enumerate(events):
        sid = "sess_a" if i < 2 else "sess_b"
        mgr.submit(
            tool_name=f"tool_{i}",
            session_id=sid,
            fn=lambda: None,
            on_done=lambda _j, e=ev: e.set(),
        )

    for ev in events:
        ev.wait(timeout=3)

    sess_a = mgr.list_for_session("sess_a")
    sess_b = mgr.list_for_session("sess_b")
    assert len(sess_a) == 2
    assert len(sess_b) == 1
    assert all(j.session_id == "sess_a" for j in sess_a)


def test_active_count_decrements_when_done() -> None:
    """active_count reflects running jobs; drops to 0 after completion."""
    mgr = _manager()
    barrier = threading.Barrier(2)  # main thread + worker thread
    released = threading.Event()

    def _slow_work() -> None:
        barrier.wait()   # signal main thread that we're running
        released.wait()  # wait for main thread to read active count

    job_id = mgr.submit(tool_name="slow", session_id="sess_slow", fn=_slow_work)

    barrier.wait()  # wait until worker is running
    assert mgr.active_count("sess_slow") == 1

    released.set()

    # Poll until done (max 3s)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if mgr.get(job_id) and mgr.get(job_id).status == "done":  # type: ignore[union-attr]
            break
        time.sleep(0.05)

    assert mgr.active_count("sess_slow") == 0
