"""FRF cache/dispatch ownership without constructing MainWindow."""
from __future__ import annotations

import threading
import time

from mf4_analyzer.ui.analysis_cache import FrfAnalysisResultCache
from mf4_analyzer.ui.analysis_jobs import AnalysisJobService
from mf4_analyzer.ui.main_window.frf_coordinator import (
    FrfCoordinator,
    frf_compute_cache_params,
)


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in tuple(self._slots):
            slot(*args)


class _FakeJobService:
    """Mirror the bookkeeping ``AnalysisJobService`` performs for callers.

    ``submit_batch(replace=True)`` calls ``cancel(section)`` internally, so a
    replacing submission is recorded as a cancel here too -- that keeps
    ``cancelled == []`` a real cross-pane guard rather than a tautology.
    ``is_running`` reports whether the section still holds physical work,
    which is what tells the coordinator a replace has anything to cancel.
    """

    def __init__(self):
        self.finished = _Signal()
        self.failed = _Signal()
        self.submissions = []
        self.cancelled = []
        self._running = set()

    def submit(self, section, job, ctx=None, *, replace=False):
        if replace:
            self.cancel(section)
        self.submissions.append((section, job, ctx, replace))
        self._running.add(section)

    def cancel(self, section):
        self.cancelled.append(section)
        self._running.discard(section)

    def is_running(self, section):
        return section in self._running

    def drain(self, section="frf"):
        """Model the section going idle once its last worker thread exits."""

        self._running.discard(section)


def _candidate(
    *, pane=0, view="analysis-view-0", output="out", job=None, display=None
):
    if job is None:
        job = lambda _worker: "computed"
    return {
        "pane_idx": pane,
        "view_id": view,
        "input_source": ("f1", "in"),
        "output_source": ("f1", output),
        "params": {
            "fs": 1000.0,
            "estimator": "h1",
            "window": "hanning",
            "periodic_window": True,
            "t_win_s": 1.0,
            "overlap": 0.5,
            "nfft_mode": "auto",
            "nfft": None,
            "detrend": "constant",
            # These must never alter the compute cache key.
            "magnitude_scale": (display or {}).get("magnitude_scale", "db"),
            "coherence_threshold": (display or {}).get(
                "coherence_threshold", 0.8
            ),
        },
        "time_range": (0.0, 4.0),
        "render_params": dict(display or {}),
        "job": job,
    }


def _make_coordinator():
    cache = FrfAnalysisResultCache(capacity=12)
    service = _FakeJobService()
    coordinator = FrfCoordinator(
        cache,
        service,
        store_result=lambda _view_id, _pane_idx, key, result: cache.put(
            key, result
        ),
    )
    return cache, service, coordinator


def test_compute_cache_params_exclude_display_only_fields():
    first = _candidate(display={"magnitude_scale": "db"})["params"]
    second = _candidate(
        display={"magnitude_scale": "linear", "coherence_threshold": 0.2}
    )["params"]

    assert frf_compute_cache_params(first) == frf_compute_cache_params(second)


def test_cache_hit_renders_without_job_submission(qapp):
    cache, service, coordinator = _make_coordinator()
    candidate = _candidate()
    key = cache.make_key(
        candidate["input_source"],
        candidate["output_source"],
        frf_compute_cache_params(candidate["params"]),
        candidate["time_range"],
    )
    cache.put(key, "cached")
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, from_cache: rendered.append(
            (ctx, result, from_cache)
        )
    )

    assert coordinator.request(candidate) is False

    assert service.submissions == []
    assert rendered[0][1:] == ("cached", True)
    assert rendered[0][0]["analysis_key"] == key


def test_cache_miss_submits_frf_with_same_lookup_and_completion_key(qapp):
    cache, service, coordinator = _make_coordinator()
    candidate = _candidate()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, from_cache: rendered.append(
            (ctx, result, from_cache)
        )
    )

    assert coordinator.request(candidate) is True
    section, _job, ctx, replace = service.submissions[0]
    assert section == "frf"
    assert replace is False

    service.finished.emit("frf", ctx, "result")

    assert cache.get(ctx["analysis_key"]) == "result"
    assert rendered[0][1:] == ("result", False)


def test_same_pane_new_request_replaces_the_superseded_worker(qapp):
    """The only outstanding work is this pane's own, so preempt it.

    Per-pane generation bookkeeping still suppresses the old completion; the
    section-level replace additionally stops it from burning a full compute.
    """

    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, _cached: rendered.append((ctx, result))
    )

    coordinator.request(_candidate(pane=0, output="old"))
    old_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=0, output="new"))
    new_ctx = service.submissions[-1][2]

    service.finished.emit("frf", old_ctx, "old-result")
    service.finished.emit("frf", new_ctx, "new-result")

    assert [submission[3] for submission in service.submissions] == [False, True]
    assert service.cancelled == ["frf"]
    assert [result for _ctx, result in rendered] == ["new-result"]
    assert cache.get(old_ctx["analysis_key"]) is None
    assert cache.get(new_ctx["analysis_key"]) == "new-result"


def test_first_request_on_an_idle_section_appends_without_cancelling(qapp):
    _cache, service, coordinator = _make_coordinator()

    coordinator.request(_candidate(pane=0))

    assert service.submissions[-1][3] is False
    assert service.cancelled == []


def test_same_pane_request_after_the_section_drained_does_not_cancel(qapp):
    """Nothing is outstanding, so there is nothing worth preempting."""

    _cache, service, coordinator = _make_coordinator()

    coordinator.request(_candidate(pane=0, output="old"))
    old_ctx = service.submissions[-1][2]
    service.finished.emit("frf", old_ctx, "old-result")
    service.drain("frf")

    coordinator.request(_candidate(pane=0, output="new"))

    assert [submission[3] for submission in service.submissions] == [False, False]
    assert service.cancelled == []


def test_pane_dropped_by_invalidate_pane_is_still_preemptible(qapp):
    """A param edit drops the pending ctx while the worker keeps running.

    ``invalidate_pane`` only makes the in-flight result stale; the following
    recompute is the click that should stop it from finishing.
    """

    _cache, service, coordinator = _make_coordinator()

    coordinator.request(_candidate(pane=0, output="old"))
    coordinator.invalidate_pane("analysis-view-0", 0)
    coordinator.request(_candidate(pane=0, output="new"))

    assert [submission[3] for submission in service.submissions] == [False, True]
    assert service.cancelled == ["frf"]


def test_same_pane_repeat_does_not_cancel_while_another_pane_is_pending(qapp):
    """A section-wide cancel here would drop pane B's queued job."""

    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, _cached: rendered.append((ctx["pane_idx"], result))
    )

    coordinator.request(_candidate(pane=0, output="left"))
    coordinator.request(_candidate(pane=1, output="right"))
    right_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=0, output="left-again"))
    left_ctx = service.submissions[-1][2]

    assert [submission[3] for submission in service.submissions] == [
        False,
        False,
        False,
    ]
    assert service.cancelled == []

    service.finished.emit("frf", right_ctx, "right-result")
    service.finished.emit("frf", left_ctx, "left-result")

    assert rendered == [(1, "right-result"), (0, "left-result")]
    assert cache.get(right_ctx["analysis_key"]) == "right-result"


def test_cache_hit_and_preflight_error_never_cancel_a_busy_section(qapp):
    cache, service, coordinator = _make_coordinator()
    coordinator.request(_candidate(pane=0, output="running"))
    assert service.is_running("frf")

    hit = _candidate(pane=1, output="cached")
    key = cache.make_key(
        hit["input_source"],
        hit["output_source"],
        frf_compute_cache_params(hit["params"]),
        hit["time_range"],
    )
    cache.put(key, "cached")
    assert coordinator.request(hit) is False

    invalid = _candidate(pane=2, output="broken")
    invalid["preflight_error"] = {"field": "timebase", "message": "不一致"}
    assert coordinator.request(invalid) is False

    assert len(service.submissions) == 1
    assert service.cancelled == []


def test_late_result_from_a_replaced_job_cannot_reach_the_cache(qapp):
    """Defence in depth for the job-id ledger.

    ``AnalysisJobService`` already suppresses the cancelled worker's terminal
    signal via its generation check, so this ctx should never arrive.  If some
    future service change let it through, ``_take_current_pending`` must still
    refuse it.
    """

    cache, service, coordinator = _make_coordinator()
    rendered = []
    failed = []
    coordinator.render_requested.connect(lambda *args: rendered.append(args))
    coordinator.failed.connect(lambda *args: failed.append(args))

    coordinator.request(_candidate(pane=0, output="old"))
    old_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=0, output="new"))

    service.finished.emit("frf", old_ctx, "stale-result")
    service.failed.emit("frf", old_ctx, "stale-error")

    assert rendered == []
    assert failed == []
    assert cache.get(old_ctx["analysis_key"]) is None


def test_replacement_announces_the_job_before_handing_it_to_the_service(qapp):
    """``job_queued`` must precede every submit, replace or not.

    The FRF mixin creates the status-bar progress token from ``job_queued``
    and reuses an existing one; emitting after ``submit`` would let a very
    short worker terminate before any token existed.
    """

    _cache, service, coordinator = _make_coordinator()
    events = []
    coordinator.job_queued.connect(lambda _ctx: events.append("queued"))
    original_submit = service.submit

    def recording_submit(section, job, ctx=None, *, replace=False):
        events.append(("submit", replace))
        original_submit(section, job, ctx=ctx, replace=replace)

    service.submit = recording_submit

    coordinator.request(_candidate(pane=0, output="old"))
    coordinator.request(_candidate(pane=0, output="new"))

    assert events == [
        "queued",
        ("submit", False),
        "queued",
        ("submit", True),
    ]


def test_real_service_stops_the_superseded_worker_and_hides_its_result(qtbot):
    """End-to-end proof over the real service, not the fake.

    Covers the whole chain the optimisation depends on: ``replace=True`` ->
    ``cancel('frf')`` -> ``worker.cancel()`` observed by the job's
    ``cancel_check``, and the cancelled run's terminal signal dropped by the
    service's generation check so no stale ctx ever reaches the coordinator.
    """

    service = AnalysisJobService()
    cache = FrfAnalysisResultCache(capacity=12)
    coordinator = FrfCoordinator(
        cache,
        service,
        store_result=lambda _view_id, _pane_idx, key, result: cache.put(
            key, result
        ),
    )
    rendered = []
    failed = []
    coordinator.render_requested.connect(
        lambda _ctx, result, _cached: rendered.append(result)
    )
    coordinator.failed.connect(lambda _ctx, issue: failed.append(issue))

    started = threading.Event()
    saw_cancel = []

    def slow_job(worker):
        started.set()
        for _ in range(3000):
            if worker.cancelled():
                saw_cancel.append(True)
                return "cancelled-result"
            time.sleep(0.001)
        return "old-result"

    try:
        coordinator.request(_candidate(pane=0, output="old", job=slow_job))
        qtbot.waitUntil(started.is_set, timeout=5000)
        assert service.is_running("frf")

        coordinator.request(
            _candidate(pane=0, output="new", job=lambda _worker: "new-result")
        )
        qtbot.waitUntil(
            lambda: not service.is_running("frf") and bool(rendered),
            timeout=10000,
        )

        assert saw_cancel == [True]
        assert rendered == ["new-result"]
        assert failed == []
        # The replacement batch owns the counters outright: the cancelled run
        # never advanced ``completed`` and the section ends exactly full, so
        # the mixin's ``done == total`` token teardown still fires once.
        assert service.progress_counts("frf") == (1, 1)
    finally:
        service.shutdown()
        service.deleteLater()


def test_cross_pane_requests_coexist_and_both_complete(qapp):
    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, _cached: rendered.append((ctx["pane_idx"], result))
    )

    coordinator.request(_candidate(pane=0, output="left"))
    left_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=1, output="right"))
    right_ctx = service.submissions[-1][2]

    service.finished.emit("frf", left_ctx, "left-result")
    service.finished.emit("frf", right_ctx, "right-result")

    assert service.cancelled == []
    assert [submission[3] for submission in service.submissions] == [False, False]
    assert rendered == [(0, "left-result"), (1, "right-result")]
    assert cache.get(left_ctx["analysis_key"]) == "left-result"
    assert cache.get(right_ctx["analysis_key"]) == "right-result"


def test_invalidate_pane_suppresses_only_that_pane_without_section_cancel(qapp):
    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, _cached: rendered.append((ctx["pane_idx"], result))
    )

    coordinator.request(_candidate(pane=0, output="left"))
    left_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=1, output="right"))
    right_ctx = service.submissions[-1][2]

    coordinator.invalidate_pane("analysis-view-0", 0)
    service.finished.emit("frf", left_ctx, "obsolete-left")
    service.finished.emit("frf", right_ctx, "right-result")

    assert service.cancelled == []
    assert rendered == [(1, "right-result")]
    assert cache.get(left_ctx["analysis_key"]) is None
    assert cache.get(right_ctx["analysis_key"]) == "right-result"


def test_same_pane_index_in_different_views_coexists(qapp):
    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, _cached: rendered.append((ctx["view_id"], result))
    )

    coordinator.request(_candidate(pane=0, view="view-a", output="left"))
    left_ctx = service.submissions[-1][2]
    coordinator.request(_candidate(pane=0, view="view-b", output="right"))
    right_ctx = service.submissions[-1][2]

    service.finished.emit("frf", left_ctx, "left-result")
    service.finished.emit("frf", right_ctx, "right-result")

    assert rendered == [("view-a", "left-result"), ("view-b", "right-result")]
    assert cache.get(left_ctx["analysis_key"]) == "left-result"
    assert cache.get(right_ctx["analysis_key"]) == "right-result"


def test_display_only_change_reuses_cached_raw_result(qapp):
    _cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(
        lambda ctx, result, cached: rendered.append((ctx, result, cached))
    )

    coordinator.request(_candidate(display={"magnitude_scale": "db"}))
    ctx = service.submissions[-1][2]
    service.finished.emit("frf", ctx, "raw-complex-result")
    assert len(service.submissions) == 1

    coordinator.request(
        _candidate(
            display={"magnitude_scale": "linear", "coherence_threshold": 0.2}
        )
    )

    assert len(service.submissions) == 1
    assert rendered[-1][1:] == ("raw-complex-result", True)
    assert rendered[-1][0]["render_params"]["magnitude_scale"] == "linear"


def test_invalidate_fid_suppresses_pending_from_either_endpoint(qapp):
    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(lambda *args: rendered.append(args))
    candidate = _candidate()
    candidate["output_source"] = ("f2", "out")
    coordinator.request(candidate)
    ctx = service.submissions[-1][2]

    coordinator.invalidate_fid("f2")
    service.finished.emit("frf", ctx, "late")

    assert rendered == []
    assert cache.get(ctx["analysis_key"]) is None


def test_preflight_issue_is_reported_without_submission(qapp):
    _cache, service, coordinator = _make_coordinator()
    failed = []
    coordinator.failed.connect(lambda ctx, issue: failed.append((ctx, issue)))
    candidate = _candidate()
    candidate["preflight_error"] = {
        "field": "timebase",
        "message": "输入与输出时间轴不一致",
    }

    assert coordinator.request(candidate) is False

    assert service.submissions == []
    assert failed[0][1]["field"] == "timebase"


def test_preflight_issue_for_new_same_pane_suppresses_older_completion(qapp):
    cache, service, coordinator = _make_coordinator()
    rendered = []
    coordinator.render_requested.connect(lambda *args: rendered.append(args))

    coordinator.request(_candidate(pane=0, output="old"))
    old_ctx = service.submissions[-1][2]
    invalid = _candidate(pane=0, output="new")
    invalid["preflight_error"] = {
        "field": "timebase",
        "message": "输入与输出时间轴不一致",
    }
    coordinator.request(invalid)

    service.finished.emit("frf", old_ctx, "obsolete")

    assert rendered == []
    assert cache.get(old_ctx["analysis_key"]) is None


def test_missing_stable_pane_identity_is_rejected(qapp):
    _cache, service, coordinator = _make_coordinator()
    candidate = _candidate()
    candidate.pop("view_id")

    import pytest

    with pytest.raises(ValueError, match="view_id or pane_key"):
        coordinator.request(candidate)
    assert service.submissions == []


def test_unhashable_explicit_pane_key_is_rejected(qapp):
    _cache, service, coordinator = _make_coordinator()
    candidate = _candidate()
    candidate["pane_key"] = []

    import pytest

    with pytest.raises(ValueError, match="pane_key must be hashable"):
        coordinator.request(candidate)
    assert service.submissions == []
