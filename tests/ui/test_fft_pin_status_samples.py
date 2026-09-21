"""Frequency pin samples: numeric FFT DTO vs explicit diagnostic status rows."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QObject

from mf4_analyzer.ui.chart_stack.cursor_display import build_fft_cursor_presentation
from mf4_analyzer.ui.chart_stack.pinning.presentation import PinPanelProjector
from mf4_analyzer.ui.chart_stack.pinning.sampling import PinSampleEvaluator
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayChannel,
    CursorDisplayOptions,
    FrequencyCursorChannel,
    PinnedCursorSample,
)
from mf4_analyzer.ui.pinned_cursor_facts import (
    UNCHECKED_TEXT,
    UNAVAILABLE_TEXT,
    _frequency_sample_channel_kind,
    _reconcile_sample,
)
from mf4_analyzer.ui.pinned_cursor_state import (
    empty_collection,
    next_record,
)


def _freq_channel(**overrides):
    data = {
        "identity": ("f0", "rpm"),
        "source_label": "eps",
        "channel_label": "rpm",
        "color": "#2563eb",
        "value": 4.0,
    }
    data.update(overrides)
    return FrequencyCursorChannel(**data)


def _status_channel(diagnostic, *, channel="rpm"):
    return CursorDisplayChannel(
        identity=("f0", channel),
        source_label="",
        channel_label=channel,
        diagnostic=diagnostic,
    )


def _intent(mode="single", **overrides):
    payload = {
        "mode": mode,
        "domain": "frequency",
        "x": 12.0,
        "x_unit": "Hz",
        "bindings": [{"fid": "f0", "channel": "rpm"}],
        "presentation": "full",
    }
    if mode == "dual":
        payload.pop("x", None)
        payload["ax"] = 10.0
        payload["bx"] = 40.0
    payload.update(overrides)
    _collection, intent = next_record(empty_collection(), payload)
    return intent


class _Ports:
    def cursor_display_options(self):
        return CursorDisplayOptions()


def _projector():
    return PinPanelProjector(QObject(), _Ports())


def test_fft_presentation_numeric_single_and_dual():
    single = build_fft_cursor_presentation(
        (_freq_channel(value=4.0),), cursor_mode="single", mini=False,
    )
    assert single.x_mode == "frequency"
    assert single.blocks[0].table_rows[0].metric_texts == ("4",)
    assert "4" in single.html

    dual = build_fft_cursor_presentation(
        (_freq_channel(value=None, a_value=1.5, b_value=2.5, delta_ab=1.0),),
        cursor_mode="dual",
        mini=False,
    )
    assert dual.metric_labels == ("A", "B", "Δ")
    assert dual.blocks[0].table_rows[0].metric_texts == ("1.5", "2.5", "1")


def test_fft_presentation_unchecked_and_unavailable_status_rows():
    unchecked = build_fft_cursor_presentation(
        (_status_channel(UNCHECKED_TEXT),), cursor_mode="single", mini=False,
    )
    assert unchecked.blocks[0].diagnostic == UNCHECKED_TEXT
    assert UNCHECKED_TEXT in unchecked.html
    assert unchecked.blocks[0].table_rows[0].metric_texts == ()

    missing = build_fft_cursor_presentation(
        (_status_channel(UNAVAILABLE_TEXT, channel="torque"),),
        cursor_mode="single",
        mini=False,
    )
    assert UNAVAILABLE_TEXT in missing.html
    assert "torque" in missing.html


def test_fft_presentation_mixed_numeric_and_unchecked():
    projection = build_fft_cursor_presentation(
        (_freq_channel(value=4.0), _status_channel(UNCHECKED_TEXT, channel="torque")),
        cursor_mode="single",
        mini=False,
    )
    assert projection.blocks[0].table_rows[0].metric_texts == ("4",)
    assert projection.blocks[1].diagnostic == UNCHECKED_TEXT
    assert UNCHECKED_TEXT in projection.html


def test_fft_presentation_dual_status_does_not_read_a_b_value():
    projection = build_fft_cursor_presentation(
        (_status_channel(UNCHECKED_TEXT),), cursor_mode="dual", mini=False,
    )
    assert projection.blocks[0].diagnostic == UNCHECKED_TEXT
    assert UNCHECKED_TEXT in projection.html


def test_fft_presentation_rejects_time_dto_without_diagnostic():
    row = CursorDisplayChannel(
        identity=("f0", "rpm"),
        source_label="",
        channel_label="rpm",
        current_value=1.0,
    )
    with pytest.raises(TypeError, match="without diagnostic"):
        build_fft_cursor_presentation((row,), cursor_mode="single", mini=False)
    with pytest.raises(TypeError, match="FrequencyCursorChannel"):
        build_fft_cursor_presentation((SimpleNamespace(label="nope"),), cursor_mode="single", mini=False)


def test_presentation_for_frequency_status_sample_does_not_raise(qapp):
    projector = _projector()
    intent = _intent()
    sample = PinnedCursorSample(
        domain="frequency",
        mode="single",
        x=12.0,
        channels=(_status_channel(UNCHECKED_TEXT),),
    )
    projection = projector.presentation_for(intent, sample)
    assert UNCHECKED_TEXT in projection.html
    assert not hasattr(sample.channels[0], "value")


def test_presentation_for_frequency_dual_mixed_sample(qapp):
    projector = _projector()
    intent = _intent(mode="dual")
    sample = PinnedCursorSample(
        domain="frequency",
        mode="dual",
        ax=10.0,
        bx=40.0,
        channels=(
            _freq_channel(value=None, a_value=1.0, b_value=2.0, delta_ab=1.0),
            _status_channel(UNCHECKED_TEXT, channel="torque"),
        ),
    )
    projection = projector.presentation_for(intent, sample)
    assert "1" in projection.html
    assert UNCHECKED_TEXT in projection.html


def test_reconcile_then_present_missing_source_and_unchecked(qapp):
    projector = _projector()
    intent = _intent(bindings=[
        {"fid": "f0", "channel": "rpm"},
        {"fid": "f0", "channel": "torque"},
    ])
    sample, next_intent, dropped = _reconcile_sample(
        intent, None, bound={("f0", "torque")}, hidden=set(),
    )
    assert dropped is False
    assert next_intent.bindings[0].channel == "rpm"
    projection = projector.presentation_for(next_intent, sample)
    assert UNCHECKED_TEXT in projection.html
    assert UNAVAILABLE_TEXT in projection.html


def _fft_canvas(qapp):
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    canvas.resize(640, 480)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _fft_entries():
    freq = np.array([1.0, 10.0, 50.0, 100.0], dtype=float)
    return [
        {
            "freq": freq,
            "amp": np.array([1.0, 2.0, 3.0, 4.0], dtype=float),
            "label": "rpm",
            "channel": "rpm",
            "fid": "f0",
            "color": "#2563eb",
            "time": np.linspace(0.0, 1.0, 8),
            "signal": np.zeros(8),
        }
    ]


def test_canvas_numeric_sample_presents_frequency_dto(qapp):
    canvas = _fft_canvas(qapp)
    canvas.plot_spectra(
        _fft_entries(), xlim=(0.0, 120.0), amp_label="Amplitude", title="FFT",
    )
    QCoreApplication.processEvents()
    ev = PinSampleEvaluator()
    sample = ev.evaluate(canvas, "frequency", mode="single", x=12.0)
    assert sample is not None
    assert isinstance(sample.channels[0], FrequencyCursorChannel)
    assert sample.channels[0].value is not None
    projection = _projector().presentation_for(_intent(x=sample.x), sample)
    assert projection.blocks
    assert projection.blocks[0].table_rows[0].metric_texts

    dual = ev.evaluate(canvas, "frequency", mode="dual", ax=10.0, bx=50.0)
    assert dual is not None
    assert isinstance(dual.channels[0], FrequencyCursorChannel)
    dual_proj = _projector().presentation_for(_intent(mode="dual"), dual)
    assert dual_proj.metric_labels == ("A", "B", "Δ")


def test_canvas_no_result_reconciles_to_status_then_presents(qapp):
    canvas = _fft_canvas(qapp)
    ev = PinSampleEvaluator()
    sample = ev.evaluate(canvas, "frequency", mode="single", x=12.0)
    assert sample is None
    intent = _intent()
    reconciled, next_intent, dropped = _reconcile_sample(
        intent, sample, bound=set(), hidden=set(),
    )
    assert dropped is False
    assert _frequency_sample_channel_kind(reconciled.channels[0]) == "status"
    assert reconciled.channels[0].diagnostic == UNCHECKED_TEXT
    projection = _projector().presentation_for(next_intent, reconciled)
    assert UNCHECKED_TEXT in projection.html
