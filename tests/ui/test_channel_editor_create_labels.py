"""Channel editor create-button copy + sliding-average param semantics."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd

from mf4_analyzer.io import FileData
from mf4_analyzer.ui.dialogs import ChannelEditorDialog


def _files(tmp_path):
    path = tmp_path / "demo.csv"
    frame = pd.DataFrame({"rpm": np.linspace(0.0, 10.0, 200)})
    path.write_text("rpm\n" + "\n".join(str(v) for v in frame["rpm"]), encoding="utf-8")
    fd = FileData(str(path), frame, list(frame.columns), {}, fs=100.0)
    fd.time_array = np.arange(len(frame), dtype=float) / 100.0
    return {"f0": fd}


def test_create_buttons_both_say_create_channel(qapp, qtbot, tmp_path):
    dlg = ChannelEditorDialog(None, _files(tmp_path), "f0")
    qtbot.addWidget(dlg)
    assert dlg.btn_create_single.text() == "✚ 创建通道"
    assert dlg.btn_create_dual.text() == "✚ 创建通道"


def test_sliding_average_param_row_is_window_length(qapp, qtbot, tmp_path):
    dlg = ChannelEditorDialog(None, _files(tmp_path), "f0")
    qtbot.addWidget(dlg)
    # Default op is d/dt — parameter unused.
    assert dlg.combo_op.currentIndex() == 0
    assert not dlg.spin_p.isEnabled()

    dlg.combo_op.setCurrentIndex(4)  # 滑动平均
    assert dlg.lbl_param.text() == "窗长"
    assert dlg.spin_p.isEnabled()
    assert dlg.spin_p.value() == 50.0
    assert "样点" in dlg.spin_p.toolTip()

    dlg.combo_src.setCurrentText("rpm")
    dlg._create_single()
    assert any(name.startswith("mavg_") for name in dlg.new_channels)
