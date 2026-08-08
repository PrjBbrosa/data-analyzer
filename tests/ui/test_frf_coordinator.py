"""FRF cache/dispatch ownership without constructing MainWindow."""
from __future__ import annotations

from mf4_analyzer.ui.analysis_cache import FrfAnalysisResultCache
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
    def __init__(self):
        self.finished = _Signal()
        self.failed = _Signal()
        self.submissions = []
        self.cancelled = []

    def submit(self, section, job, ctx=None, *, replace=False):
        self.submissions.append((section, job, ctx, replace))

    def cancel(self, section):
        self.cancelled.append(section)


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
    coordinator = FrfCoordinator(cache, service)
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


def test_same_pane_new_request_suppresses_old_result_without_section_cancel(qapp):
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

    assert service.cancelled == []
    assert all(submission[3] is False for submission in service.submissions)
    assert [result for _ctx, result in rendered] == ["new-result"]
    assert cache.get(old_ctx["analysis_key"]) is None
    assert cache.get(new_ctx["analysis_key"]) == "new-result"


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
