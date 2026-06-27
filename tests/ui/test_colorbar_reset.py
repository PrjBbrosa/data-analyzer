"""Double-click the colorbar to reset the colour scale to the rendered window.

The footer/quickref hints have long advertised "拖 colorbar 调色阶 · 双击重置",
but no handler ever implemented the double-click reset (pyqtgraph 0.14.0's
ColorBarItem only wires a right-click colour-map menu). These tests pin the
behaviour: a double-click on the colorbar restores the levels the last render
set, and it signals as a *programmatic* rebase — never as a user drag, so the
analysis-page locked-levels linkage (which listens on ``levels_changed``) is not
falsely triggered.
"""
import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


def _plot(canvas):
    m = np.linspace(-60.0, 0.0, 100).reshape(10, 10)
    canvas.plot_or_update_heatmap(m, (0.0, 1.0), (0.0, 1.0), z_auto=True)
    return canvas


def test_reset_colorbar_levels_restores_rendered_window(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    _plot(canvas)
    rendered = canvas._cbar.levels()

    # Simulate a user dragging the colorbar to a narrow off-window.
    canvas._cbar.setLevels((-20.0, -10.0))
    canvas._img.setLevels((-20.0, -10.0))
    assert canvas._cbar.levels() != pytest.approx(rendered)

    assert canvas.reset_colorbar_levels() is True
    assert canvas._cbar.levels() == pytest.approx(rendered)
    assert tuple(canvas._img.getLevels()) == pytest.approx(rendered)


def test_reset_is_noop_before_any_render(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    # No plot_or_update_heatmap yet → nothing to reset to.
    assert canvas.reset_colorbar_levels() is False


def test_double_click_on_colorbar_dispatches_reset(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    _plot(canvas)
    rendered = canvas._cbar.levels()
    canvas._cbar.setLevels((-20.0, -10.0))
    canvas._img.setLevels((-20.0, -10.0))

    # Pin the hit-test to the colorbar (real geometry needs an on-screen layout,
    # verified on-device); here we exercise the eventFilter dispatch + reset.
    canvas._pos_on_colorbar = lambda _pos: True
    ev = QMouseEvent(
        QEvent.MouseButtonDblClick, QPointF(5.0, 5.0),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    handled = canvas.eventFilter(canvas._glw.viewport(), ev)

    assert handled is True
    assert canvas._cbar.levels() == pytest.approx(rendered)


def test_double_click_off_colorbar_does_not_reset(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    _plot(canvas)
    canvas._cbar.setLevels((-20.0, -10.0))
    canvas._img.setLevels((-20.0, -10.0))

    canvas._pos_on_colorbar = lambda _pos: False
    ev = QMouseEvent(
        QEvent.MouseButtonDblClick, QPointF(5.0, 5.0),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    handled = canvas.eventFilter(canvas._glw.viewport(), ev)

    assert handled is not True  # not consumed
    assert canvas._cbar.levels() == pytest.approx((-20.0, -10.0))  # untouched


def test_reset_signals_rebased_not_user_drag(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    _plot(canvas)
    changed, rebased = [], []
    canvas.levels_changed.connect(lambda lo, hi: changed.append((lo, hi)))
    canvas.levels_rebased.connect(lambda: rebased.append(True))

    canvas._cbar.setLevels((-20.0, -10.0))
    canvas._img.setLevels((-20.0, -10.0))
    canvas.reset_colorbar_levels()

    assert rebased, "reset must emit levels_rebased (programmatic reset)"
    assert not changed, "reset must NOT emit levels_changed (locked-levels linkage)"
