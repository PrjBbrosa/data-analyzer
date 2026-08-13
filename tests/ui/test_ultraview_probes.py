"""Task 0 probe helpers: they count explicit calls, not UltraView operations."""
from __future__ import annotations

from tests.ui.ultraview_fakes import ComputeProbe, snapshot_source_state


class _FakeCache:
    def __init__(self):
        self._store = {("f0", "rpm", "{}"): object()}


class _FakeView:
    def __init__(self, view_id, name):
        self.view_id = view_id
        self.name = name
        self.checked = [("f0", "MotorSpeed")]

    def to_dict(self):
        return {
            "view_id": self.view_id,
            "name": self.name,
            "checked": [list(key) for key in self.checked],
        }


class _FakeManager:
    def __init__(self, view_id):
        self.views = [_FakeView(view_id, "View 1")]
        self.active = 0


class _FakeJobs:
    def submit(self, *args, **kwargs):
        return None

    def submit_batch(self, *args, **kwargs):
        return None


class _FakePins:
    def __init__(self):
        self._slots = {("fft", "v1", 0): {("f0", "rpm", "{}")}}


class _FakeWindow:
    def __init__(self):
        self._analysis_jobs = _FakeJobs()
        self._analysis_restore_pending = {("fft", "v1")}
        self._analysis_pins = _FakePins()
        self.view_manager = _FakeManager("time-1")
        self.analysis_managers = {
            "fft": _FakeManager("fft-1"),
            "fft_time": _FakeManager("ft-1"),
            "frf": _FakeManager("frf-1"),
            "order": _FakeManager("ord-1"),
        }
        self.analysis_caches = {"fft": _FakeCache()}
        self.fft_calls = 0
        self.store_calls = 0

    def do_fft(self):
        self.fft_calls += 1

    def do_fft_time(self):
        return None

    def do_frf(self):
        return None

    def do_order_time(self):
        return None

    def _store_analysis_result(self, section, view_id, pane_idx, key, result):
        self.store_calls += 1
        self.analysis_caches[section]._store[key] = result


def test_compute_probe_counts_explicit_entrypoint_calls():
    window = _FakeWindow()
    probe = ComputeProbe().install(window)

    window.do_fft()
    window.do_fft()
    window.do_frf()
    window._analysis_jobs.submit("fft", lambda: None)
    window._analysis_jobs.submit_batch("order", [])
    window._store_analysis_result("fft", "v1", 0, ("k",), object())
    window._store_analysis_result("fft", "v1", 0, ("k",), object())
    window._store_analysis_result("fft", "v1", 0, ("k2",), object())

    assert probe.compute_calls["do_fft"] == 2
    assert probe.compute_calls["do_frf"] == 1
    assert probe.compute_total == 3
    assert probe.job_calls["submit"] == 1
    assert probe.job_calls["submit_batch"] == 1
    assert probe.store_calls == 3
    assert probe.store_new_key_writes == 2
    assert probe.restore_pending_unchanged(window)
    window._analysis_restore_pending.add(("order", "v2"))
    assert not probe.restore_pending_unchanged(window)
    probe.restore()
    assert window.fft_calls == 2


def test_snapshot_source_state_keeps_composite_channel_identity():
    window = _FakeWindow()
    snap = snapshot_source_state(window)
    assert snap["managers"]["time"]["view_ids"] == ("time-1",)
    assert snap["managers"]["fft"]["views"][0]["payload"]["checked"] == [
        ["f0", "MotorSpeed"]
    ]
    assert snap["active_indices"]["order"] == 0
    assert ("fft", "v1", 0) in snap["pins"]
    assert snap["cache_keys"]["fft"] == (("f0", "rpm", "{}"),)
    assert snap["restore_pending"] == frozenset({("fft", "v1")})
