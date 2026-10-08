"""UI contracts for catalog identities, default selection and unknown requests."""
import numpy as np
import pytest

from mf4_analyzer.ui.dialogs import ChartOptionsDialog
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas, _HeatmapAxisHandle


HEAD_STYLE = "tracelab.head-style.v1"


@pytest.fixture
def heatmap(qtbot):
    canvas = PgHeatmapCanvas(with_slice=False)
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(
        np.arange(9, dtype=float).reshape(3, 3), (0., 2.), (10., 30.),
        amplitude_mode="amplitude", z_auto=False, z_floor=0., z_ceiling=8.,
    )
    return canvas


def test_default_is_head_and_combo_identity_survives_label_change(heatmap, qtbot):
    assert heatmap._cmap_name == HEAD_STYLE
    dialog = ChartOptionsDialog(heatmap, _HeatmapAxisHandle(heatmap))
    qtbot.addWidget(dialog)
    assert dialog.combo_cmap.currentData() == HEAD_STYLE
    idx = dialog.combo_cmap.findData("gnuplot2")
    dialog.combo_cmap.setItemText(idx, "Localized legacy palette")
    matrix = heatmap._matrix_disp.copy()
    levels = tuple(heatmap._img.getLevels())
    dialog.combo_cmap.setCurrentIndex(idx)
    dialog.apply_changes()
    assert heatmap._cmap_name == "gnuplot2"
    np.testing.assert_array_equal(heatmap._matrix_disp, matrix)
    assert tuple(heatmap._img.getLevels()) == levels
    dialog.restore_opened()
    assert heatmap._cmap_name == HEAD_STYLE
    np.testing.assert_array_equal(heatmap._matrix_disp, matrix)


def test_unknown_request_survives_title_edit_and_restore(heatmap, qtbot):
    unknown = "third-party.palette.v9"
    heatmap._apply_live_colormap(unknown)
    dialog = ChartOptionsDialog(heatmap, _HeatmapAxisHandle(heatmap))
    qtbot.addWidget(dialog)
    assert dialog.combo_cmap.currentData() == unknown
    assert "不可用" in dialog.combo_cmap.currentText()
    dialog.edit_title.setText("Unrelated title")
    dialog.apply_changes()
    assert heatmap._cmap_name == unknown
    dialog.combo_cmap.setCurrentIndex(dialog.combo_cmap.findData(HEAD_STYLE))
    dialog.apply_changes()
    assert heatmap._cmap_name == HEAD_STYLE
    dialog.restore_opened()
    assert heatmap._cmap_name == unknown


def test_cmap_change_invalidates_retained_presentation(heatmap, monkeypatch):
    invalidations = []
    monkeypatch.setattr(heatmap, "_note_presentation_content_invalidated", lambda: invalidations.append(True))
    _HeatmapAxisHandle(heatmap).get_mappables()[0].set_cmap("turbo")
    assert invalidations


def test_shown_main_window_colormap_apply_restore(qtbot, tmp_path, qapp):
    """Also runnable with QT_QPA_PLATFORM=cocoa as an app-start exercise."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(qapp)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1440, 900)
    win.show()
    qtbot.waitExposed(win)
    win.toolbar._set_mode("fft_time")
    canvas = win._analysis_page("fft_time").pane_canvas(0)
    matrix = np.tile(np.linspace(0., 50., 256), (48, 1))
    canvas.plot_or_update_heatmap(
        matrix, (0., 50.), (0., 2000.), amplitude_mode="amplitude",
        z_auto=False, z_floor=0., z_ceiling=50.,
    )
    qtbot.wait(150)
    assert win.grab().save(str(tmp_path / "head-main-window.png"))
    dialog = ChartOptionsDialog(win, _HeatmapAxisHandle(canvas))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qtbot.mouseClick(dialog.tabs.tabBar(), Qt.LeftButton,
                     pos=dialog.tabs.tabBar().tabRect(1).center())
    qtbot.wait(100)
    assert dialog.combo_cmap.isVisible()
    assert dialog.combo_cmap.currentData() == HEAD_STYLE
    assert dialog.grab().save(str(tmp_path / "head-chart-options.png"))
    dialog.combo_cmap.setCurrentIndex(dialog.combo_cmap.findData("gnuplot2"))
    qtbot.mouseClick(dialog.btn_apply, Qt.LeftButton)
    assert canvas._cmap_name == "gnuplot2"
    qtbot.mouseClick(dialog.btn_reset, Qt.LeftButton)
    assert canvas._cmap_name == HEAD_STYLE
    for lo, hi in ((10., 40.), (20., 50.), (0., 50.)):
        canvas.apply_color_policy(False, lo, hi)
        assert tuple(canvas._img.getLevels()) == (lo, hi)
        assert canvas._cmap_name == HEAD_STYLE
        np.testing.assert_array_equal(canvas._matrix_disp, matrix)
    dialog.close()
    canvas._apply_live_colormap("third-party.palette.v9")
    unavailable = ChartOptionsDialog(win, _HeatmapAxisHandle(canvas))
    qtbot.addWidget(unavailable)
    unavailable.show()
    qtbot.waitExposed(unavailable)
    unavailable.tabs.setCurrentIndex(1)
    qtbot.wait(100)
    assert "不可用" in unavailable.combo_cmap.currentText()
    assert unavailable.grab().save(str(tmp_path / "unavailable-chart-options.png"))
    unavailable.edit_title.setText("Keep unavailable color request")
    qtbot.mouseClick(unavailable.btn_apply, Qt.LeftButton)
    assert canvas._cmap_name == "third-party.palette.v9"
    unavailable.close()
    print(f"platform={QApplication.platformName()} screenshots={tmp_path}")
