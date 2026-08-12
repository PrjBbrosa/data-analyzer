"""Unit contracts for the QtWidgets-free FFT-vs-Time coordinator."""
from __future__ import annotations

import inspect

import pytest

from mf4_analyzer.ui.analysis_cache import AnalysisResultCache
from mf4_analyzer.ui.main_window.fft_time_coordinator import FftTimeCoordinator


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeJobService:
    def __init__(self):
        self.finished = _Signal()
        self.failed = _Signal()
        self.submissions = []

    def submit_batch(self, section, jobs, *, replace=False):
        self.submissions.append((section, list(jobs), replace))


def _key_builder(fid, channel, params, time_range):
    return (
        str(fid),
        str(channel),
        tuple(time_range) if time_range is not None else None,
        tuple(sorted(params.items())),
    )


_DEFAULT_JOB = object()


def _candidate(*, fid="f1", channel="speed", pane_idx=0,
               time_range=(0.0, 1.0), job=_DEFAULT_JOB):
    if job is _DEFAULT_JOB:
        job = lambda _worker: object()
    return {
        "fid": fid,
        "channel": channel,
        "params": {"fs": 100.0, "nfft": 128, "weighting": "None"},
        "pane_idx": pane_idx,
        "time_range": time_range,
        "job": job,
        "render_params": {"amplitude_mode": "amplitude", "cmap": "turbo"},
        "source": (fid, channel),
    }


@pytest.fixture
def coordinator():
    cache = AnalysisResultCache(12)
    service = _FakeJobService()
    subject = FftTimeCoordinator(
        cache,
        service,
        _key_builder,
        store_result=lambda _view_id, _pane_idx, key, result: cache.put(
            key, result
        ),
    )
    return subject, cache, service


def test_coordinator_module_has_no_qtwidgets_import():
    import mf4_analyzer.ui.main_window.fft_time_coordinator as module

    source = inspect.getsource(module)
    assert "QtWidgets" not in source
    assert "QWidget" not in source


def test_cache_hit_emits_render_event_and_submits_nothing(coordinator):
    subject, cache, service = coordinator
    candidate = _candidate()
    key = _key_builder(
        candidate["fid"], candidate["channel"], candidate["params"],
        candidate["time_range"],
    )
    cached = object()
    cache.put(key, cached)
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    subject.request_batch([candidate])

    assert service.submissions == []
    assert len(rendered) == 1
    ctx, result, cache_hit = rendered[0]
    assert result is cached
    assert cache_hit is True
    assert ctx["analysis_key"] == key
    assert ctx["pane_idx"] == 0


def test_job_factory_is_lazy_for_cache_hit_and_runs_for_miss(coordinator):
    subject, cache, service = coordinator
    candidate = _candidate()
    candidate.pop("job")
    factory_calls = []

    def job_factory():
        factory_calls.append("called")
        return lambda _worker: object()

    candidate["job_factory"] = job_factory
    key = _key_builder(
        candidate["fid"], candidate["channel"], candidate["params"],
        candidate["time_range"],
    )
    cached = object()
    cache.put(key, cached)
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    submitted = subject.request_batch([candidate])

    assert submitted == 0
    assert factory_calls == []
    assert service.submissions == []
    assert rendered == [(rendered[0][0], cached, True)]

    cache.clear()
    rendered.clear()
    submitted = subject.request_batch([candidate])

    assert submitted == 1
    assert factory_calls == ["called"]
    _section, jobs, _replace = service.submissions[-1]
    assert callable(jobs[0][0])
    assert rendered == []


def test_skip_candidate_bypasses_cache_and_submits_skip_slot(
    coordinator, monkeypatch
):
    subject, cache, service = coordinator
    candidate = _candidate(job=None)
    key = _key_builder(
        candidate["fid"], candidate["channel"], candidate["params"],
        candidate["time_range"],
    )
    cache.put(key, object())
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    def unexpected_cache_probe(_key):
        pytest.fail("skip candidates must not probe the result cache")

    monkeypatch.setattr(cache, "get", unexpected_cache_probe)
    subject.request_batch([candidate])

    assert rendered == []
    assert len(service.submissions) == 1
    _section, jobs, _replace = service.submissions[0]
    job, ctx = jobs[0]
    assert job is None
    assert ctx["source"] == ("f1", "speed")
    assert "analysis_key" not in ctx


def test_cache_miss_submits_job_and_puts_result_on_finish(coordinator):
    subject, cache, service = coordinator
    candidate = _candidate()
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    subject.request_batch([candidate])

    assert len(service.submissions) == 1
    section, jobs, replace = service.submissions[0]
    assert section == "fft_time"
    assert replace is False
    job, ctx = jobs[0]
    assert callable(job)
    assert ctx["source"] == ("f1", "speed")
    result = object()
    service.finished.emit("fft_time", ctx, result)

    assert cache.get(ctx["analysis_key"]) is result
    assert rendered == [(ctx, result, False)]


def test_batch_started_precedes_submit_and_skips_cache_only_batch(coordinator):
    subject, cache, service = coordinator
    events = []
    original_submit = service.submit_batch

    def recording_submit(section, jobs, *, replace=False):
        jobs = list(jobs)
        events.append(("submit", section, jobs, replace))
        original_submit(section, jobs, replace=replace)

    service.submit_batch = recording_submit
    subject.batch_started.connect(
        lambda count, first_ctx: events.append(("started", count, first_ctx))
    )

    subject.request_batch([_candidate()])

    assert [event[0] for event in events] == ["started", "submit"]
    assert events[0][1] == 1
    assert events[0][2] is events[1][2][0][1]

    cache_only = _candidate(time_range=(2.0, 3.0))
    cache_only_key = _key_builder(
        cache_only["fid"], cache_only["channel"], cache_only["params"],
        cache_only["time_range"],
    )
    cache.put(cache_only_key, object())
    events.clear()

    subject.request_batch([cache_only])

    assert events == []


def test_superseded_pending_result_is_dropped_not_cached(coordinator):
    subject, cache, service = coordinator
    old = _candidate(time_range=(0.0, 1.0))
    new = _candidate(time_range=(1.0, 2.0))
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    subject.request_batch([old])
    old_ctx = service.submissions[-1][1][0][1]
    subject.request_batch([new], replace=True)
    new_ctx = service.submissions[-1][1][0][1]

    stale = object()
    service.finished.emit("fft_time", old_ctx, stale)
    assert cache.get(old_ctx["analysis_key"]) is None
    assert rendered == []

    fresh = object()
    service.finished.emit("fft_time", new_ctx, fresh)
    assert cache.get(new_ctx["analysis_key"]) is fresh
    assert rendered == [(new_ctx, fresh, False)]


def test_two_panes_produce_distinct_keys_and_do_not_cross_pollute(coordinator):
    subject, cache, service = coordinator
    first = _candidate(pane_idx=0, time_range=(0.0, 1.0))
    second = _candidate(pane_idx=1, time_range=(2.0, 3.0))
    rendered = []
    subject.render_requested.connect(
        lambda ctx, result, cache_hit: rendered.append((ctx, result, cache_hit))
    )

    subject.request_batch([first, second])

    _section, jobs, _replace = service.submissions[0]
    first_ctx = jobs[0][1]
    second_ctx = jobs[1][1]
    assert first_ctx["analysis_key"] != second_ctx["analysis_key"]
    first_result, second_result = object(), object()
    service.finished.emit("fft_time", first_ctx, first_result)
    service.finished.emit("fft_time", second_ctx, second_result)

    assert cache.get(first_ctx["analysis_key"]) is first_result
    assert cache.get(second_ctx["analysis_key"]) is second_result
    assert [ctx["pane_idx"] for ctx, _result, _hit in rendered] == [0, 1]


def test_invalidate_fid_delegates_to_single_store(coordinator):
    subject, cache, _service = coordinator
    first = _candidate(fid="f1")
    second = _candidate(fid="f2")
    first_key = _key_builder(
        first["fid"], first["channel"], first["params"], first["time_range"]
    )
    second_key = _key_builder(
        second["fid"], second["channel"], second["params"], second["time_range"]
    )
    cache.put(first_key, object())
    retained = object()
    cache.put(second_key, retained)

    subject.invalidate_fid("f1")

    assert cache.get(first_key) is None
    assert cache.get(second_key) is retained
