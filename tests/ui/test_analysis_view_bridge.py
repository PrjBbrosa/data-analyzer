"""analysis_view_bridge: capture/apply between Contextual and view state.

Uses a stub contextual (duck-typed get_params/apply_params) so the test
doesn't need the full Inspector; wiring to real Contextuals is covered
by V7's integration test.
"""
from mf4_analyzer.ui.analysis_view_bridge import (
    apply_params_from_state, capture_params_to_state,
)
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState


class _StubCtx:
    def __init__(self):
        self._p = {"nfft": 1024, "window": "hanning"}
        self.reset_calls = 0

    def get_params(self):
        return dict(self._p)

    def apply_params(self, d):
        self._p.update(d)

    def reset_to_defaults(self):
        self.reset_calls += 1
        self._p = {"nfft": 512, "window": "hanning"}


def test_capture_then_apply_round_trip():
    ctx = _StubCtx()
    state = AnalysisViewState(name="v", tab_color="#fff")
    capture_params_to_state(ctx, state)
    assert state.params["nfft"] == 1024
    state.params["nfft"] = 4096
    apply_params_from_state(ctx, state)
    assert ctx.get_params()["nfft"] == 4096


def test_apply_with_empty_params_resets_to_defaults():
    ctx = _StubCtx()
    apply_params_from_state(ctx, AnalysisViewState(name="v", tab_color="#fff"))
    assert ctx.reset_calls == 1
    assert ctx.get_params()["nfft"] == 512
