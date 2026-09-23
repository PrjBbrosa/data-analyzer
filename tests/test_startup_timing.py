"""Focused probes for opt-in startup timing (Task 0)."""
from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _reload_timing(monkeypatch, **env):
    for key in (
        "TRACELAB_STARTUP_TIMING",
        "TRACELAB_STARTUP_RUN_ID",
        "TRACELAB_STARTUP_PERF_DIR",
        "TRACELAB_STARTUP_PROBE_HOST",
        "TRACELAB_STARTUP_PROBE_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))
    sys.modules.pop("mf4_analyzer.startup_timing", None)
    return importlib.import_module("mf4_analyzer.startup_timing")


def test_disabled_mark_has_zero_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _reload_timing(monkeypatch)
    assert st.enabled() is False
    st.mark("python_entry")
    st.mark_page_ready("fft")
    st.mark_preload_complete()
    assert list(tmp_path.iterdir()) == []
    assert st.recorded_stages() == ()


def test_enabled_mark_writes_under_run_id_and_keeps_process_mono(
    tmp_path, monkeypatch
):
    run_id = "run-unit-1"
    perf_dir = tmp_path / "startup-perf"
    st = _reload_timing(
        monkeypatch,
        TRACELAB_STARTUP_TIMING="1",
        TRACELAB_STARTUP_RUN_ID=run_id,
        TRACELAB_STARTUP_PERF_DIR=str(perf_dir),
    )
    assert st.enabled() is True
    st.mark("python_entry")
    st.mark("gui_modules_imported")
    run_dir = perf_dir / run_id
    marks_path = run_dir / "marks.jsonl"
    assert marks_path.is_file()
    lines = [
        json.loads(line)
        for line in marks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["stage"] for row in lines] == [
        "python_entry",
        "gui_modules_imported",
    ]
    assert lines[0]["mono_ns"] <= lines[1]["mono_ns"]
    assert all("mono_ns" in row for row in lines)
    assert st.recorded_stages() == ("python_entry", "gui_modules_imported")


def test_mark_write_failure_is_diagnosable(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("nope", encoding="utf-8")
    st = _reload_timing(
        monkeypatch,
        TRACELAB_STARTUP_TIMING="1",
        TRACELAB_STARTUP_RUN_ID="run-fail-write",
        TRACELAB_STARTUP_PERF_DIR=str(blocker),
    )
    with pytest.raises(st.StartupTimingError) as raised:
        st.mark("python_entry")
    assert "run-fail-write" in str(raised.value)
    assert st.last_write_error() is not None


def test_page_ready_and_preload_apis_exist_but_are_not_auto_claimed(
    tmp_path, monkeypatch
):
    """Task 0 only exposes mark APIs; startup must not pretify them as done."""
    st = _reload_timing(
        monkeypatch,
        TRACELAB_STARTUP_TIMING="1",
        TRACELAB_STARTUP_RUN_ID="run-api",
        TRACELAB_STARTUP_PERF_DIR=str(tmp_path / "perf"),
    )
    assert callable(st.mark_page_ready)
    assert callable(st.mark_preload_complete)
    assert "preload_complete" not in st.recorded_stages()
    assert not any(s.startswith("page_ready") for s in st.recorded_stages())


def test_measure_tool_rejects_missing_marks_timeout_and_nonzero_exit(
    tmp_path, monkeypatch
):
    from tools import measure_windows_startup as measure

    missing = measure.evaluate_run_outcome(
        exit_code=0,
        timed_out=False,
        marks=[],
        interactive_received=False,
        run_id="r1",
        marks_run_id=None,
    )
    assert missing["ok"] is False
    assert "mark" in missing["error"].lower() or "missing" in missing["error"].lower()

    timeout = measure.evaluate_run_outcome(
        exit_code=0,
        timed_out=True,
        marks=[{"stage": "python_entry"}],
        interactive_received=False,
        run_id="r1",
        marks_run_id="r1",
    )
    assert timeout["ok"] is False
    assert "timed out" in timeout["error"].lower() or "timeout" in timeout["error"].lower()

    crashed = measure.evaluate_run_outcome(
        exit_code=3,
        timed_out=False,
        marks=[{"stage": "python_entry"}],
        interactive_received=False,
        run_id="r1",
        marks_run_id="r1",
    )
    assert crashed["ok"] is False
    assert "exit" in crashed["error"].lower()


def test_measure_tool_requires_matching_run_id(tmp_path, monkeypatch):
    from tools import measure_windows_startup as measure

    mismatch = measure.evaluate_run_outcome(
        exit_code=0,
        timed_out=False,
        marks=[
            {"stage": "python_entry", "run_id": "other"},
            {"stage": "gui_modules_imported", "run_id": "other"},
            {"stage": "qapplication_ready", "run_id": "other"},
            {"stage": "mainwindow_constructed", "run_id": "other"},
            {"stage": "first_frame", "run_id": "other"},
        ],
        interactive_received=True,
        run_id="expected",
        marks_run_id="other",
    )
    assert mismatch["ok"] is False
    assert "run" in mismatch["error"].lower()


def test_measure_tool_records_probe_on_tool_clock_not_child_subtraction(
    tmp_path, monkeypatch
):
    """Interactive ready uses the tool mono clock at response receipt."""
    from tools import measure_windows_startup as measure

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    child_mono_ns = 10**15  # deliberately absurd vs parent

    def _child():
        conn, _addr = server.accept()
        with conn:
            # Pretend the app handled the probe after first_frame.
            payload = conn.recv(4096)
            assert payload
            # Child would stamp its own mono; tool must not subtract it.
            conn.sendall(
                json.dumps(
                    {
                        "ok": True,
                        "token": json.loads(payload.decode()).get("token"),
                        "child_mono_ns": child_mono_ns,
                    }
                ).encode("utf-8")
                + b"\n"
            )

    thread = threading.Thread(target=_child, daemon=True)
    thread.start()
    t0 = time.perf_counter_ns()
    result = measure.send_interactive_probe(
        host, port, token="tok-1", timeout_s=2.0
    )
    t1 = time.perf_counter_ns()
    thread.join(timeout=2.0)
    server.close()

    assert result["ok"] is True
    assert t0 <= result["tool_mono_ns_sent"] <= result["tool_mono_ns_received"] <= t1
    # Must not claim interactive from child mono arithmetic.
    assert "interactive_mono_ns" not in result or result.get(
        "interactive_clock"
    ) == "tool"
    assert result["observation_overhead_ns"] >= 0


def test_wait_for_input_idle_is_auxiliary_and_absent_on_macos():
    from tools import measure_windows_startup as measure

    info = measure.probe_wait_for_input_idle(pid=os.getpid(), timeout_ms=10)
    assert info["available"] is False or sys.platform.startswith("win")
    if not sys.platform.startswith("win"):
        assert info["available"] is False
        assert info.get("ok") is not True
        assert "windows" in info.get("reason", "").lower() or "unavailable" in info.get(
            "reason", ""
        ).lower()


def test_splash_events_write_parent_marks_when_enabled(tmp_path, monkeypatch):
    run_id = "run-splash-marks"
    perf_dir = tmp_path / "startup-perf"
    st = _reload_timing(
        monkeypatch,
        TRACELAB_STARTUP_TIMING="1",
        TRACELAB_STARTUP_RUN_ID=run_id,
        TRACELAB_STARTUP_PERF_DIR=str(perf_dir),
    )
    st.record_splash_event(
        st.STAGE_SPLASH_PAINTED,
        session="sess-1",
        detail={"child_mono_ns": 10**15, "frames": 3},
    )
    st.record_splash_event(st.STAGE_SPLASH_CLOSED, session="sess-1")
    marks_path = perf_dir / run_id / "marks.jsonl"
    rows = [
        json.loads(line)
        for line in marks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["stage"] for row in rows] == ["splash_painted", "splash_closed"]
    assert rows[0]["detail"]["session"] == "sess-1"
    assert rows[0]["detail"]["child_detail"]["child_mono_ns"] == 10**15
    # Parent mono is process-local and must not equal the absurd child value.
    assert rows[0]["mono_ns"] != 10**15
    assert rows[0]["mono_ns"] <= rows[1]["mono_ns"]


def test_splash_events_are_noop_when_timing_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = _reload_timing(monkeypatch)
    st.record_splash_event(st.STAGE_SPLASH_PAINTED, session="s")
    st.forward_feedback_event(st.STAGE_SPLASH_CLOSED, session="s")
    assert list(tmp_path.iterdir()) == []
    assert st.recorded_stages() == ()


def test_feedback_forward_uses_tool_clock_not_cross_process_mono(
    tmp_path, monkeypatch
):
    from tools import measure_windows_startup as measure

    run_id = "run-feedback-fwd"
    st = _reload_timing(
        monkeypatch,
        TRACELAB_STARTUP_TIMING="1",
        TRACELAB_STARTUP_RUN_ID=run_id,
        TRACELAB_STARTUP_PERF_DIR=str(tmp_path / "perf"),
    )
    server = measure._ProbeServer(expected_run_id=run_id)
    monkeypatch.setenv("TRACELAB_STARTUP_PROBE_HOST", server.host)
    monkeypatch.setenv("TRACELAB_STARTUP_PROBE_PORT", str(server.port))

    absurd_child_mono = 99 * 10**15

    def _push():
        # Simulate controller I/O thread: mark + push with opaque child detail.
        st.record_splash_event(
            st.STAGE_SPLASH_PAINTED,
            session="sess-fwd",
            detail={"child_mono_ns": absurd_child_mono},
        )

    thread = threading.Thread(target=_push, daemon=True)
    t0 = time.perf_counter_ns()
    thread.start()
    deadline = time.perf_counter() + 2.0
    event = None
    while time.perf_counter() < deadline:
        server.poll()
        drained = server.drain_feedback()
        if drained:
            event = drained[0]
            break
        time.sleep(0.01)
    thread.join(timeout=2.0)
    server.close()
    t1 = time.perf_counter_ns()

    assert event is not None
    assert event["ok"] is True
    assert event["role"] == "feedback"
    assert event["event"] == "splash_painted"
    assert event["feedback_clock"] == "tool"
    assert t0 <= event["tool_mono_ns_accepted"] <= event["tool_mono_ns_received"] <= t1
    assert event["transport_overhead_ns"] >= 0
    # Must not claim splash timing from parent−child mono arithmetic.
    assert event["tool_mono_ns_received"] != absurd_child_mono
    assert "splash_from_child_mono" not in event


def test_feedback_and_interactive_roles_are_validated_separately():
    from tools import measure_windows_startup as measure

    painted = measure.stamp_feedback_message(
        {
            "role": "feedback",
            "event": "splash_painted",
            "run_id": "r-ok",
            "session": "s1",
            "parent_mono_ns": 123,
        },
        expected_run_id="r-ok",
        accepted_ns=1000,
        received_ns=1500,
    )
    assert painted["ok"] is True
    assert painted["transport_overhead_ns"] == 500
    assert painted["role"] == "feedback"

    bad_run = measure.stamp_feedback_message(
        {
            "role": "feedback",
            "event": "splash_painted",
            "run_id": "other",
            "session": "s1",
        },
        expected_run_id="r-ok",
        accepted_ns=1,
        received_ns=2,
    )
    assert bad_run["ok"] is False

    # Interactive-shaped payload must not pass the feedback validator.
    interactive_shaped = measure.stamp_feedback_message(
        {"ok": True, "token": "tok", "cmd": "interactive_probe", "run_id": "r-ok"},
        expected_run_id="r-ok",
        accepted_ns=1,
        received_ns=2,
    )
    assert interactive_shaped["ok"] is False

    required = measure.evaluate_run_outcome(
        exit_code=0,
        timed_out=False,
        marks=[
            {"stage": name, "run_id": "r-ok"}
            for name in measure.REQUIRED_APP_STAGES
        ],
        interactive_received=True,
        run_id="r-ok",
        marks_run_id="r-ok",
        splash_required=True,
        splash_events=[painted],
    )
    assert required["ok"] is True

    missing_splash = measure.evaluate_run_outcome(
        exit_code=0,
        timed_out=False,
        marks=[
            {"stage": name, "run_id": "r-ok"}
            for name in measure.REQUIRED_APP_STAGES
        ],
        interactive_received=True,
        run_id="r-ok",
        marks_run_id="r-ok",
        splash_required=True,
        splash_events=[],
    )
    assert missing_splash["ok"] is False
    assert "splash_painted" in missing_splash["error"]
