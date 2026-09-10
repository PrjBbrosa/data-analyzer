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


def _baseline():
    return {
        "version": 1,
        "kind": "fft",
        "slot": 2,
        "display_name": "均衡",
        "params": {"window": "hanning", "nfft": 4096},
    }


def test_capture_copies_ctx_preset_baseline_onto_state():
    ctx = _StubCtx()
    ctx.preset_baseline = _baseline()
    state = AnalysisViewState(name="v", tab_color="#fff")
    capture_params_to_state(ctx, state)
    assert state.preset_baseline == ctx.preset_baseline
    assert state.preset_baseline is not ctx.preset_baseline
    assert state.preset_baseline["params"] is not ctx.preset_baseline["params"]
    state.preset_baseline["params"]["nfft"] = 1
    assert ctx.preset_baseline["params"]["nfft"] == 4096


def test_capture_without_ctx_baseline_sets_none():
    ctx = _StubCtx()
    state = AnalysisViewState(name="v", tab_color="#fff")
    state.preset_baseline = _baseline()
    capture_params_to_state(ctx, state)
    assert state.preset_baseline is None


def test_apply_restores_ctx_preset_baseline():
    ctx = _StubCtx()
    ctx.preset_baseline = None
    state = AnalysisViewState(name="v", tab_color="#fff")
    state.params = {"nfft": 2048, "window": "hanning"}
    state.preset_baseline = _baseline()
    apply_params_from_state(ctx, state)
    assert ctx.get_params()["nfft"] == 2048
    assert ctx.preset_baseline == state.preset_baseline
    assert ctx.preset_baseline is not state.preset_baseline
    assert ctx.preset_baseline["params"] is not state.preset_baseline["params"]
    ctx.preset_baseline["params"]["nfft"] = 1
    assert state.preset_baseline["params"]["nfft"] == 4096


def test_apply_empty_params_clears_baseline_for_blank_view():
    ctx = _StubCtx()
    ctx.preset_baseline = _baseline()
    state = AnalysisViewState(name="v", tab_color="#fff")
    state.preset_baseline = {
        "version": 1,
        "kind": "order",
        "slot": 1,
        "display_name": "频率",
        "params": {"window": "hanning"},
    }
    apply_params_from_state(ctx, state)
    assert ctx.reset_calls == 1
    assert ctx.get_params()["nfft"] == 512
    assert ctx.preset_baseline is None


def test_apply_empty_params_clears_baseline_when_state_has_none():
    ctx = _StubCtx()
    ctx.preset_baseline = _baseline()
    apply_params_from_state(ctx, AnalysisViewState(name="v", tab_color="#fff"))
    assert ctx.reset_calls == 1
    assert ctx.preset_baseline is None


def test_capture_does_not_inject_baseline_into_state_params():
    ctx = _StubCtx()
    ctx.preset_baseline = _baseline()
    state = AnalysisViewState(name="v", tab_color="#fff")
    capture_params_to_state(ctx, state)
    assert state.params == {"nfft": 1024, "window": "hanning"}
    assert "preset_baseline" not in state.params
    assert "display_name" not in state.params
    assert state.preset_baseline["kind"] == "fft"


class _BarOwner:
    """Contextual-shaped owner that stores baseline on PresetBar, not ctx."""

    def __init__(self):
        self._params = {"nfft": 2048, "window": "hanning", "overlap": 50}
        self.preset_bar = _LivePresetBar()

    def current_params(self):
        return dict(self._params)

    def get_params(self):
        return self.current_params()

    def apply_params(self, d):
        self._params.update(d)


class _LivePresetBar:
    def __init__(self):
        self._baseline = None

    def baseline(self):
        return None if self._baseline is None else {
            key: (dict(value) if isinstance(value, dict) else value)
            for key, value in self._baseline.items()
        }

    def set_baseline(self, value):
        self._baseline = None if value is None else {
            key: (dict(value[key]) if isinstance(value.get(key), dict) else value[key])
            for key in value
        }


def test_capture_syncs_complete_params_and_bar_baseline():
    ctx = _BarOwner()
    ctx.preset_bar.set_baseline({
        "version": 2,
        "kind": "fft",
        "slot": 4,
        "display_name": "identical",
        "params": {"window": "hanning", "nfft": "4096"},
        "source_payload": {"window": "hanning"},
    })
    state = AnalysisViewState(name="v", tab_color="#fff")
    state.params = {"nfft": 1024, "window": "hann"}
    state.preset_baseline = _baseline()
    capture_params_to_state(ctx, state)
    assert state.params == ctx.current_params()
    assert state.preset_baseline["slot"] == 4
    assert state.preset_baseline["version"] == 2
    assert state.preset_baseline["source_payload"] == {"window": "hanning"}
    assert state.preset_baseline is not ctx.preset_bar._baseline


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
