"""WinWert mixed-X Inspector and render ownership regression tests."""

from __future__ import annotations

import numpy as np

from mf4_analyzer.ui import hints
from mf4_analyzer.ui.inspector_sections import PersistentTop
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.time_xaxis import PER_SOURCE_NAME
from tests._helpers import wwt_factory as wwt


def test_curve_bound_xaxis_puts_reason_on_source_field_label(qtbot):
    top = PersistentTop()
    qtbot.addWidget(top)
    source_label = top._xaxis_source_label
    assert source_label.text() == "来源:"
    assert source_label.toolTip() == ""
    assert top.choice_xaxis.toolTip() == ""

    top.set_curve_bound_xaxis_summary("文件内绑定 · 2 条曲线")
    assert source_label.toolTip() == hints.XAXIS_CURVE_BOUND_HINT
    assert top.choice_xaxis.toolTip() == hints.XAXIS_CURVE_BOUND_HINT
    assert not top.choice_xaxis.isEnabled()
    assert top.choice_xaxis.buttons()[1].text() == "曲线自带"

    top.set_curve_bound_xaxis_summary("")
    assert source_label.toolTip() == ""
    assert top.choice_xaxis.toolTip() == ""
    assert top.choice_xaxis.isEnabled()
    assert top.choice_xaxis.buttons()[1].text() == "指定通道"
    assert top.curve_bound_xaxis_summary() == ""


def test_mixed_channel_x_keeps_header_x_editable_and_exact_arrays(
    qapp, qtbot, tmp_path, monkeypatch,
):
    """One exceptional evaluation X must not lock the whole ordinary View."""
    path = wwt.channel_exception_with_header_x(tmp_path / "mixed-channel-x.wwt")
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        window._wwt_import, "_ask_layout", lambda *_args, **_kwargs: True,
    )

    window._load_one(str(path))
    qapp.processEvents()

    top = window.inspector.top
    assert top.xaxis_mode() == "channel"
    assert top.choice_xaxis.buttons()[1].text() == "指定通道"
    assert top.xaxis_channel_data() == (
        PER_SOURCE_NAME, None, "Wheel input torque",
    )
    assert top.choice_xaxis.isEnabled()
    assert top.btn_apply_xaxis.isEnabled()
    assert top.curve_bound_xaxis_summary() == ""
    assert top._xaxis_source_label.toolTip() == ""

    result = window._build_time_plot_data()
    assert result.issues == []
    source = next(iter(window.files.values()))
    rows = {row[0]: np.asarray(row[2]) for row in result.rows}
    np.testing.assert_array_equal(
        rows[source.get_prefixed_channel("Diff.Limit A")],
        source.data["X_Wheel input torque"].to_numpy(copy=False),
    )
    for channel in ("Diff.Moment A", "Diff.Moment B"):
        np.testing.assert_array_equal(
            rows[source.get_prefixed_channel(channel)],
            source.data["Wheel input torque"].to_numpy(copy=False),
        )
