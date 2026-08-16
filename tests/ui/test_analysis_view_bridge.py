"""analysis_view_bridge: capture/apply between Contextual and view state.

Uses a stub contextual (duck-typed get_params/apply_params) so the test
doesn't need the full Inspector; wiring to real Contextuals is covered
by V7's integration test.
"""
from mf4_analyzer.ui.analysis_view_bridge import (
    apply_overlay_to_canvas,
    apply_params_from_state,
    capture_overlay_from_canvas,
    capture_params_to_state,
)
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


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


class _CurrentParamsCtx(_StubCtx):
    def current_params(self):
        return {**self._p, "amp_y": "dB", "avg_mode": "线性平均"}


def test_capture_then_apply_round_trip():
    ctx = _StubCtx()
    state = AnalysisViewState(name="v", tab_color="#fff")
    capture_params_to_state(ctx, state)
    assert state.params["nfft"] == 1024
    state.params["nfft"] = 4096
    apply_params_from_state(ctx, state)
    assert ctx.get_params()["nfft"] == 4096


def test_capture_prefers_complete_current_params_when_available():
    ctx = _CurrentParamsCtx()
    state = AnalysisViewState(name="v", tab_color="#fff")

    capture_params_to_state(ctx, state)

    assert state.params == {
        "nfft": 1024,
        "window": "hanning",
        "amp_y": "dB",
        "avg_mode": "线性平均",
    }


def test_apply_with_empty_params_resets_to_defaults():
    ctx = _StubCtx()
    apply_params_from_state(ctx, AnalysisViewState(name="v", tab_color="#fff"))
    assert ctx.reset_calls == 1
    assert ctx.get_params()["nfft"] == 512


class _StubOverlayCanvas:
    def __init__(self):
        self.remarks = []
        self.placement = {"ax": 9.0, "bx": 11.0}

    def snapshot_remarks(self):
        return list(self.remarks)

    def snapshot_cursor_placement(self):
        return self.placement

    def restore_remarks(self, payload):
        self.remarks = list(payload or [])

    def restore_cursor_placement(self, payload):
        self.placement = payload


class _HeatmapStubCanvas:
    def snapshot_remarks(self):
        return [{
            "source": ["fid-a", "rpm"],
            "x": 1.5,
            "y": 40.0,
            "panel": "heatmap",
        }]


def test_capture_overlay_from_canvas_writes_pane_remarks_and_placement():
    pane = PaneState(cursor_mode="dual")
    canvas = _StubOverlayCanvas()
    canvas.remarks = [{
        "source": ["fid-a", "rpm"],
        "x": 12.0,
        "y": 0.4,
        "panel": "amp",
    }]
    canvas.placement = {"ax": 12.0, "bx": 40.0}
    capture_overlay_from_canvas(canvas, pane)
    assert pane.remarks == [{
        "source": ["fid-a", "rpm"],
        "x": 12.0,
        "y": 0.4,
        "panel": "amp",
    }]
    assert pane.cursor_placement == {"ax": 12.0, "bx": 40.0}


def test_capture_overlay_skips_missing_cursor_api_and_keeps_heatmap_panel():
    pane = PaneState(cursor_placement={"ax": 1.0, "bx": 2.0})
    capture_overlay_from_canvas(_HeatmapStubCanvas(), pane)
    assert pane.remarks[0]["panel"] == "heatmap"
    assert pane.cursor_placement == {"ax": 1.0, "bx": 2.0}


def test_apply_overlay_to_canvas_restores_pane_overlay():
    pane = PaneState(
        remarks=[{
            "source": ["fid-a", "rpm"],
            "x": 12.0,
            "y": 0.4,
            "panel": "amp",
        }],
        cursor_placement={"ax": 12.0, "bx": 40.0},
    )
    canvas = _StubOverlayCanvas()
    apply_overlay_to_canvas(canvas, pane)
    assert canvas.remarks == pane.remarks
    assert canvas.placement == {"ax": 12.0, "bx": 40.0}
