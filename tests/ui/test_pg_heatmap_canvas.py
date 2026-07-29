"""PgHeatmapCanvas: levels/extent math + API-parity tests (offscreen)."""
import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
    PgHeatmapCanvas,
    _apply_target_bottom_ticks,
    _make_analysis_plot,
    time_axis_display_extent,
)
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult


class _FakeSceneClick:
    """Stand-in for a GraphicsScene MouseClickEvent (scenePos + button)."""

    def __init__(self, scene_pos, button):
        self._scene_pos = scene_pos
        self._button = button
        self.accepted = False

    def scenePos(self):
        return self._scene_pos

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True


class _FakeMenuEvent:
    def __init__(self, accepted_item):
        self.acceptedItem = accepted_item

    def screenPos(self):
        return QPointF(0.0, 0.0)


class _FakeMouseModeController:
    def __init__(self):
        self.mode = "pan"

    def current_mouse_mode(self):
        return self.mode

    def set_pan_mode(self):
        self.mode = "pan"

    def set_zoom_mode(self):
        self.mode = "zoom"


def _mouse_press(point, button):
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.MouseButtonPress, point, button, button, Qt.NoModifier,
    )


def _mouse_move(point, held_button):
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.MouseMove, point, Qt.NoButton, held_button, Qt.NoModifier,
    )


def _mouse_release(point, button):
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.MouseButtonRelease, point, button, Qt.NoButton, Qt.NoModifier,
    )


def _send_viewport_wheel(canvas, view_box, *, pixel_y=0, angle_y=0,
                         modifiers=Qt.NoModifier):
    scene_pos = view_box.mapViewToScene(QPointF(1.0, 1.0))
    pos = QPointF(canvas._glw.mapFromScene(scene_pos))
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    event = QWheelEvent(
        pos,
        global_pos,
        QPoint(0, pixel_y),
        QPoint(0, angle_y),
        Qt.NoButton,
        modifiers,
        Qt.ScrollUpdate,
        False,
    )
    return QApplication.sendEvent(canvas._glw.viewport(), event)


def _open_context_menu(view_box, monkeypatch):
    from PyQt5.QtWidgets import QMenu

    captured = {}

    def _fake_popup(self, *_args, **_kwargs):
        captured["menu"] = self

    monkeypatch.setattr(QMenu, "popup", _fake_popup, raising=True)
    view_box.raiseContextMenu(_FakeMenuEvent(view_box))
    return captured.get("menu")


def _menu_texts(menu):
    return [
        action.text().replace("&", "").strip()
        for action in menu.actions()
        if not action.isSeparator() and action.text().replace("&", "").strip()
    ]


def _inline_panel(menu):
    from PyQt5.QtWidgets import QWidgetAction

    panels = [
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    ]
    assert len(panels) == 1
    return panels[0]


def _panel_button(panel, object_name):
    from PyQt5.QtWidgets import QPushButton, QToolButton

    button = panel.findChild((QPushButton, QToolButton), object_name)
    assert button is not None
    return button


def _panel_edit(panel, object_name):
    from PyQt5.QtWidgets import QLineEdit

    edit = panel.findChild(QLineEdit, object_name)
    assert edit is not None
    return edit


@pytest.fixture
def canvas(qapp):
    c = PgHeatmapCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _mat():
    # 4 rows (Y) x 5 cols (X), peak = 100 at [2, 3]
    m = np.ones((4, 5))
    m[2, 3] = 100.0
    return m


def _axis_font_family_size(axis):
    font = axis.style.get("tickFont")
    label = getattr(axis, "label", None)
    label_font = label.font() if label is not None else None
    return (
        font.family() if font is not None else None,
        font.pointSizeF() if font is not None else None,
        label_font.family() if label_font is not None else None,
        label_font.pointSizeF() if label_font is not None else None,
    )


def _bottom_tick_labels(axis):
    levels = getattr(axis, "_tickLevels", None)
    if not levels:
        return []
    return [str(label) for _value, label in levels[0]]


def _bottom_tick_values(axis):
    levels = getattr(axis, "_tickLevels", None)
    if not levels:
        return []
    return [float(value) for value, _label in levels[0]]


def test_linear_mode_levels_auto(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    lo, hi = canvas._img.getLevels()
    assert lo == pytest.approx(1.0) and hi == pytest.approx(100.0)


def test_fresh_heatmap_canvas_defaults_to_gnuplot2(canvas):
    assert canvas._cmap_name == "gnuplot2"
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas._cmap_name == "gnuplot2"


def test_linear_mode_manual_levels_drive_image_and_colorbar(canvas):
    matrix = np.linspace(0.1, 1.6, 20, dtype=float).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=matrix, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=False,
        z_floor=0.0, z_ceiling=0.2,
    )

    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.0), pytest.approx(0.2))
    blo, bhi = canvas._cbar.levels()
    assert (blo, bhi) == (pytest.approx(0.0), pytest.approx(0.2))


def test_heatmap_hides_title_row_and_disables_axis_si_prefix(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        x_label='Frequency (Hz)', y_label='Order',
        title='Order · 3 条曲线',
        amplitude_mode='amplitude', z_auto=True,
    )

    assert not canvas._plot.titleLabel.isVisible()
    assert canvas._plot.titleLabel.maximumHeight() == 0
    assert canvas._plot.getAxis('left').autoSIPrefix is False
    assert canvas._plot.getAxis('bottom').autoSIPrefix is False


def test_heatmap_grid_is_major_only(canvas):
    """Heatmap canvas defaults to a major-only grid (no minor sub-grid lines):
    maxTickLevel=0 on the bottom/left axes, matching the time-domain canvas."""
    for side in ('bottom', 'left'):
        assert canvas._plot.getAxis(side).style.get('maxTickLevel') == 0, (
            f"{side} axis should be major-grid-only (maxTickLevel=0)"
        )


def test_heatmap_empty_state_has_default_main_axis_labels(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.show()
        qapp.processEvents()
        assert c._plot.getAxis('bottom').labelText == 'Time (s)'
        assert c._plot.getAxis('left').labelText == 'Frequency (Hz)'
        assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
        assert c._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'
    finally:
        c.deleteLater()


def test_heatmap_full_reset_restores_empty_state_axis_labels(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.show()
        qapp.processEvents()
        c.plot_or_update_heatmap(
            matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
            x_label='Custom X', y_label='Custom Y',
            amplitude_mode='amplitude', z_auto=True,
        )
        c.full_reset()
        qapp.processEvents()
        assert c._plot.getAxis('bottom').labelText == 'Time (s)'
        assert c._plot.getAxis('left').labelText == 'Frequency (Hz)'
        assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
        assert c._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'
    finally:
        c.deleteLater()


def test_heatmap_plots_hide_native_auto_fit_buttons(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        for plot in (c._plot, c._slice_plot):
            assert getattr(plot, "buttonsHidden", False) is True
    finally:
        c.deleteLater()


def test_image_rect_matches_extents(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(2.0, 12.0), y_extent=(1.0, 9.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    r = canvas._img.boundingRect()
    mapped = canvas._img.mapRectToParent(r)
    assert mapped.left() == pytest.approx(2.0)
    assert mapped.right() == pytest.approx(12.0)
    assert mapped.top() == pytest.approx(1.0)
    assert mapped.bottom() == pytest.approx(9.0)


def test_wheel_dispatch_locks_axis_with_modifier(canvas):
    """Ctrl+wheel zooms X only, Shift+wheel zooms Y only, so the spectrogram
    matches the chart-card footer hint and the line canvases. A plain wheel is
    NOT consumed (pyqtgraph keeps its native both-axis zoom)."""
    vb = canvas._plot.vb
    vb.setXRange(0.0, 100.0, padding=0)
    vb.setYRange(0.0, 50.0, padding=0)
    x0, y0 = vb.viewRange()

    # Ctrl + wheel-up → X shrinks (zoom in), Y unchanged.
    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier,
        x_pos=50.0, y_pos=25.0, view_box=vb,
    )
    x1, y1 = vb.viewRange()
    assert consumed is True
    assert (x1[1] - x1[0]) < (x0[1] - x0[0])
    assert (y1[1] - y1[0]) == pytest.approx(y0[1] - y0[0])

    # Shift + wheel-up → Y shrinks, X unchanged.
    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ShiftModifier,
        x_pos=50.0, y_pos=25.0, view_box=vb,
    )
    x2, y2 = vb.viewRange()
    assert consumed is True
    assert (y2[1] - y2[0]) < (y1[1] - y1[0])
    assert (x2[1] - x2[0]) == pytest.approx(x1[1] - x1[0])

    # Plain wheel (no modifier) → not consumed (native fallback preserved).
    assert canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.NoModifier,
        x_pos=50.0, y_pos=25.0, view_box=vb,
    ) is False


def test_viewport_shift_wheel_zooms_heatmap_y_only(canvas, qapp):
    """A real wheel event reaches the heatmap ViewBox and keeps X fixed."""
    canvas.show()
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 100.0), y_extent=(0.0, 50.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    vb = canvas._plot.vb
    vb.setXRange(0.0, 100.0, padding=0)
    vb.setYRange(0.0, 50.0, padding=0)
    qapp.processEvents()
    before_x, before_y = vb.viewRange()
    scene_pos = vb.mapViewToScene(QPointF(50.0, 25.0))
    pos = QPointF(canvas._glw.mapFromScene(scene_pos))
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    event = QWheelEvent(
        pos, global_pos, QPoint(), QPoint(0, 120), Qt.NoButton,
        Qt.ShiftModifier, Qt.ScrollUpdate, False,
    )

    assert QApplication.sendEvent(canvas._glw.viewport(), event)
    qapp.processEvents()
    after_x, after_y = vb.viewRange()

    assert after_x == pytest.approx(before_x)
    assert (after_y[1] - after_y[0]) < (before_y[1] - before_y[0])


@pytest.mark.parametrize("plot_name", ["_plot", "_slice_plot"])
@pytest.mark.parametrize(
    "modifier", [Qt.ControlModifier, Qt.ShiftModifier],
)
@pytest.mark.parametrize(
    ("pixel_delta", "expect_zoom_in"), [(15, True), (-15, False)],
)
def test_pixel_only_modifier_wheel_zooms_each_heatmap_viewbox(
        qapp, plot_name, modifier, pixel_delta, expect_zoom_in):
    canvas = PgHeatmapCanvas(with_slice=True)
    try:
        canvas.resize(640, 480)
        canvas.show()
        view_box = getattr(canvas, plot_name).vb
        view_box.setXRange(0.0, 100.0, padding=0)
        view_box.setYRange(0.0, 50.0, padding=0)
        qapp.processEvents()
        before = view_box.viewRange()

        assert _send_viewport_wheel(
            canvas, view_box, pixel_y=pixel_delta, modifiers=modifier,
        )
        qapp.processEvents()
        after = view_box.viewRange()

        axis_index = 0 if modifier == Qt.ControlModifier else 1
        other_index = 1 - axis_index
        before_span = before[axis_index][1] - before[axis_index][0]
        after_span = after[axis_index][1] - after[axis_index][0]
        assert after[other_index] == pytest.approx(before[other_index])
        assert (after_span < before_span) is expect_zoom_in
    finally:
        canvas.deleteLater()


def test_has_result_lifecycle(canvas):
    assert not canvas.has_result()
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 1.0), y_extent=(0.0, 1.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas.has_result()


def test_manual_axis_ranges(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        x_auto=False, x_min=1.0, x_max=5.0,
        y_auto=False, y_min=2.0, y_max=6.0,
    )
    (x0, x1), (y0, y1) = canvas._plot.vb.viewRange()
    assert (x0, x1) == (pytest.approx(1.0), pytest.approx(5.0))
    assert (y0, y1) == (pytest.approx(2.0), pytest.approx(6.0))


def test_update_path_reuses_colorbar_and_relabels_left_axis(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        cmap='turbo', cbar_label='Amplitude',
    )
    first_cbar = canvas._cbar
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        cmap='viridis', cbar_label='Order Amp',
    )
    assert canvas._cbar is first_cbar  # reused, not rebuilt
    # Vertical ColorBarItem applies ``label=`` to the LEFT axis
    # (pg 0.14.0 ColorBarItem.__init__:143); the right axis only
    # carries tick values.
    assert canvas._cbar.getAxis('left').labelText == 'Order Amp'


def test_heatmap_chart_options_dialog_exposes_axis_and_color_scale(
    canvas, monkeypatch,
):
    from mf4_analyzer.ui import _axis_interaction

    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        x_label="Time (s)",
        y_label="Frequency (Hz)",
        amplitude_mode='amplitude',
        z_auto=False,
        z_floor=-2.0,
        z_ceiling=4.0,
        cmap='turbo',
        cbar_label='Amplitude',
    )
    captured = {}

    def fake_edit(parent, handle):
        captured["parent"] = parent
        captured["handle"] = handle
        return True

    monkeypatch.setattr(
        _axis_interaction, "edit_chart_options_dialog", fake_edit,
        raising=True,
    )

    assert canvas.open_chart_options_dialog(parent=canvas) is True

    handle = captured["handle"]
    assert captured["parent"] is canvas
    assert handle.get_xlabel() == "Time (s)"
    assert handle.get_ylabel() == "Frequency (Hz)"
    mappables = handle.get_mappables()
    assert len(mappables) == 1
    mappable = mappables[0]
    assert mappable.get_cmap().name == "turbo"
    assert mappable.get_clim() == pytest.approx((-2.0, 4.0))

    mappable.set_clim(1.0, 3.0)

    assert canvas._img.getLevels() == pytest.approx((1.0, 3.0))
    assert canvas._cbar.levels() == pytest.approx((1.0, 3.0))


def test_set_tick_density_accepts_inspector_counts(canvas):
    # Inspector PersistentTop passes integer tick COUNTS (x spinbox
    # 3-30, y spinbox 3-20; defaults 10/10) — the same values the mpl
    # canvases fed into MaxNLocator(nbins=...). NOT pg density factors.
    canvas.set_tick_density(10, 8)
    bottom = canvas._plot.getAxis('bottom')
    left = canvas._plot.getAxis('left')
    # Without realized geometry, bottom X falls back to the count->density
    # convention from pg_canvas/tick_density.py (x_n/10.0, clamped to
    # [0.35, 3.0]). Left Y always keeps density behavior.
    assert bottom._tickDensity == pytest.approx(10 / 10.0)
    assert left._tickDensity == pytest.approx(8 / 6.0)
    for density in (bottom._tickDensity, left._tickDensity):
        assert 0.35 <= density <= 3.0
        assert density != pytest.approx(3.0)  # default counts must not clamp


def test_set_tick_density_clamps_at_spinbox_maxima(canvas):
    # Spinbox maxima (30, 20) hit the density ceiling, never beyond it.
    canvas.set_tick_density(30, 20)
    bottom = canvas._plot.getAxis('bottom')
    levels = getattr(bottom, "_tickLevels", None)
    if levels:
        assert 3 <= len(levels[0]) <= 30
    else:
        assert bottom._tickDensity == pytest.approx(3.0)
    assert canvas._plot.getAxis('left')._tickDensity == pytest.approx(3.0)


def test_set_tick_density_also_applies_to_slice_subplot(qapp):
    # FFT-vs-Time renders a freq/amplitude slice subplot with its OWN bottom/
    # left axes. The density control must reach those too — previously it only
    # touched the main map axes, so the slice grid silently ignored the setting.
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.set_tick_density(10, 8)
        sb = c._slice_plot.getAxis('bottom')
        sl = c._slice_plot.getAxis('left')
        # Unshown slice bottom X uses fallback density.
        assert sb._tickDensity == pytest.approx(10 / 10.0)  # x → bottom
        assert sl._tickDensity == pytest.approx(8 / 6.0)    # y → left
    finally:
        c.deleteLater()


def test_interp_bilinear_enables_smooth_image_paint(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='bilinear',
    )
    assert canvas._img.smooth_transform_enabled() is True

    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='nearest',
    )
    assert canvas._img.smooth_transform_enabled() is False


def test_heatmap_default_interpolation_is_smooth(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )

    assert canvas._img.smooth_transform_enabled() is True


def test_heatmap_main_manual_zoom_emits_transient_true(canvas):
    seen = []
    canvas.manual_zoom_changed.connect(seen.append)

    canvas._on_main_manual_zoom()

    assert seen == [True]


def test_heatmap_slice_zoom_does_not_emit_transient(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        seen = []
        c.manual_zoom_changed.connect(seen.append)

        c._on_interactive_range_changed()

        assert seen == []
    finally:
        c.deleteLater()


def test_heatmap_reset_clears_transient_without_extents(canvas):
    seen = []
    canvas.manual_zoom_changed.connect(seen.append)

    canvas.reset_view_to_data_extents()

    assert seen and seen[-1] is False


def test_heatmap_replot_clears_transient_zoom(canvas):
    seen = []
    canvas.manual_zoom_changed.connect(seen.append)

    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )

    assert seen and seen[-1] is False


def test_heatmap_context_menu_is_chinese_and_hides_plot_options(canvas, monkeypatch):
    from PyQt5.QtWidgets import QToolButton

    controller = _FakeMouseModeController()
    canvas.register_mouse_mode_controller(controller)
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )

    menu = _open_context_menu(canvas._plot.vb, monkeypatch)

    assert menu is not None
    top = _menu_texts(menu)
    assert "绘图选项" not in top  # hidden for now in fft_time / order
    assert "Plot Options" not in top
    assert "查看全部" not in top
    assert "X 轴范围" not in top
    assert "Y 轴范围" not in top
    assert "网格" not in top
    assert "Mouse Mode" not in top
    panel = _inline_panel(menu)
    buttons = [
        panel.findChild(QToolButton, "pgContextZoomButton"),
        panel.findChild(QToolButton, "pgContextPanButton"),
    ]
    assert [btn.toolTip() for btn in buttons] == ["框选", "平移"]
    assert panel.findChild(QToolButton, "pgContextGridXChip").text() == "X"
    assert panel.findChild(QToolButton, "pgContextGridYChip").text() == "Y"
    buttons[0].click()
    assert controller.mode == "zoom"


def test_heatmap_context_menu_view_all_button_restores_full_extents(
    canvas, monkeypatch, qapp
):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )
    canvas._plot.setXRange(2.0, 4.0, padding=0)
    canvas._plot.setYRange(1.0, 3.0, padding=0)
    qapp.processEvents()

    menu = _open_context_menu(canvas._plot.vb, monkeypatch)
    panel = _inline_panel(menu)
    _panel_button(panel, "pgContextViewAllButton").click()
    qapp.processEvents()

    (x0, x1), (y0, y1) = canvas._plot.vb.viewRange()
    assert (x0, x1) == pytest.approx((0.0, 10.0))
    assert (y0, y1) == pytest.approx((0.0, 8.0))


def test_heatmap_context_menu_range_edits_apply_valid_and_restore_invalid(
    canvas, monkeypatch, qapp
):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )
    qapp.processEvents()

    panel = _inline_panel(_open_context_menu(canvas._plot.vb, monkeypatch))
    x_min = _panel_edit(panel, "pgContextXMinEdit")
    x_max = _panel_edit(panel, "pgContextXMaxEdit")
    y_min = _panel_edit(panel, "pgContextYMinEdit")
    y_max = _panel_edit(panel, "pgContextYMaxEdit")

    x_min.setText("1.5")
    x_max.setText("6.5")
    x_max.editingFinished.emit()
    qapp.processEvents()
    assert canvas._plot.vb.viewRange()[0] == pytest.approx([1.5, 6.5])

    y_min.setText("2")
    y_max.setText("7")
    y_max.editingFinished.emit()
    qapp.processEvents()
    assert canvas._plot.vb.viewRange()[1] == pytest.approx([2.0, 7.0])

    x_min.setText("not-a-number")
    x_max.editingFinished.emit()
    qapp.processEvents()
    assert canvas._plot.vb.viewRange()[0] == pytest.approx([1.5, 6.5])
    assert (x_min.text(), x_max.text()) == ("1.5", "6.5")

    y_min.setText("9")
    y_max.setText("3")
    y_max.editingFinished.emit()
    qapp.processEvents()
    assert canvas._plot.vb.viewRange()[1] == pytest.approx([2.0, 7.0])
    assert (y_min.text(), y_max.text()) == ("2", "7")


def test_heatmap_context_menu_grid_chips_keep_top_right_grid_disabled(
    canvas, monkeypatch, qapp
):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )
    qapp.processEvents()

    panel = _inline_panel(_open_context_menu(canvas._plot.vb, monkeypatch))
    x_chip = _panel_button(panel, "pgContextGridXChip")
    y_chip = _panel_button(panel, "pgContextGridYChip")

    assert x_chip.text() == "X"
    assert y_chip.text() == "Y"
    assert x_chip.isChecked()
    assert y_chip.isChecked()
    assert canvas._plot.getAxis('top').grid is False
    assert canvas._plot.getAxis('right').grid is False

    x_chip.click()
    y_chip.click()
    qapp.processEvents()
    assert canvas._plot.getAxis('bottom').grid is False
    assert canvas._plot.getAxis('left').grid is False
    assert canvas._plot.getAxis('top').grid is False
    assert canvas._plot.getAxis('right').grid is False

    x_chip.click()
    y_chip.click()
    qapp.processEvents()
    assert canvas._plot.getAxis('bottom').grid is not False
    assert canvas._plot.getAxis('left').grid is not False
    assert canvas._plot.getAxis('top').grid is False
    assert canvas._plot.getAxis('right').grid is False


def test_remark_add_and_clear(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1
    # Label text carries the full X/Y/Z coordinate contract. (5.0, 4.0) maps
    # to cell [row 2, col 2] = 1.0, all rendered via %.4g.
    label = canvas._remarks[0]['text'].textItem.toPlainText()
    assert 'X=5' in label
    assert 'Y=5.333' in label
    assert 'Z=1' in label
    assert canvas._remarks[0]['label'] is canvas._remarks[0]['text']
    assert canvas._remarks[0]['leader'] is not None
    assert canvas._remarks[0]['text'].flags() & canvas._remarks[0]['text'].ItemIsMovable
    # Dot color matches the time-domain annotation dots
    # (pg_canvas/annotations.py:221) and the mpl DANGER token
    # (canvases.py:34), not an ad hoc red.
    assert canvas._remarks[0]['dot'].opts['brush'].color().name() == '#dc2626'
    canvas.clear_remarks()
    assert canvas._remarks == []


def test_replot_clears_stale_remarks(canvas):
    # Unlike the mpl labels (x, y only), pg remark labels embed the z
    # value — surviving a replot would display stale data. The mpl
    # rebuild path (self.clear()) dropped annotations on every replot.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert 'Z=1' in canvas._remarks[0]['text'].textItem.toPlainText()
    canvas.plot_or_update_heatmap(
        matrix=_mat() * 7.0, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # Value at (5, 4) is now 7 — the retained label would still say 1.
    assert canvas._remarks == []


def test_right_click_on_colorbar_region_keeps_remarks(canvas, qapp):
    # ``insert_in`` puts the ColorBarItem inside the PlotItem layout, so
    # _plot.sceneBoundingRect() INCLUDES the colorbar column. A
    # remark-mode right-click there maps to view x beyond the heatmap
    # extent and must NOT delete the nearest remark.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.show()
    qapp.processEvents()  # realize the GraphicsLayout geometry
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1
    # x=11 is outside extent (0, 10) but inside the plot's scene rect
    # (the colorbar column) — the precondition assert pins the scenario.
    sp = canvas._plot.vb.mapViewToScene(QPointF(11.0, 4.0))
    assert canvas._plot.sceneBoundingRect().contains(sp)
    canvas._on_scene_click(_FakeSceneClick(sp, Qt.RightButton))
    assert len(canvas._remarks) == 1
    canvas.hide()


def test_remove_remark_near_deletes_nearest(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(2.0, 2.0)
    canvas.add_remark_at(8.0, 6.0)
    canvas.remove_remark_near(7.5, 5.5)  # nearest is (8, 6)
    assert len(canvas._remarks) == 1
    xs, ys = canvas._remarks[0]['dot'].getData()
    assert (xs[0], ys[0]) == (pytest.approx(2.5), pytest.approx(8.0 / 3.0))


def test_remark_mode_gates_viewbox_menu(canvas):
    # Right-click delete only works because the ViewBox context menu is
    # suppressed while annotating (menuEnabled() is checked BEFORE the
    # menu is raised; sigMouseClicked fires too late to block it).
    canvas.set_remark_enabled(True)
    assert canvas._plot.vb.menuEnabled() is False
    canvas.set_remark_enabled(False)
    assert canvas._plot.vb.menuEnabled() is True


def test_remark_mode_uses_bitmap_pen_cursor(canvas):
    canvas.set_remark_enabled(True)

    assert canvas._glw.viewport().cursor().shape() == Qt.BitmapCursor


def test_annotation_left_click_adds_on_release_not_press(canvas, monkeypatch):
    from PyQt5.QtCore import QPoint

    canvas.set_remark_enabled(True)
    point = QPoint(80, 90)
    added = []
    monkeypatch.setattr(
        canvas,
        "_add_remark_at_viewport_pos",
        lambda pos: added.append(pos),
        raising=False,
    )

    press_consumed = canvas.eventFilter(
        canvas._glw.viewport(),
        _mouse_press(point, Qt.LeftButton),
    )
    release_consumed = canvas.eventFilter(
        canvas._glw.viewport(),
        _mouse_release(point, Qt.LeftButton),
    )

    assert press_consumed is False
    assert release_consumed is True
    assert added == [point]


def test_annotation_left_drag_does_not_add_remark(canvas, monkeypatch):
    from PyQt5.QtCore import QPoint

    canvas.set_remark_enabled(True)
    start = QPoint(80, 90)
    end = QPoint(140, 120)
    added = []
    monkeypatch.setattr(
        canvas,
        "_add_remark_at_viewport_pos",
        lambda pos: added.append(pos),
        raising=False,
    )

    canvas.eventFilter(canvas._glw.viewport(), _mouse_press(start, Qt.LeftButton))
    move_consumed = canvas.eventFilter(
        canvas._glw.viewport(),
        _mouse_move(end, Qt.LeftButton),
    )
    release_consumed = canvas.eventFilter(
        canvas._glw.viewport(),
        _mouse_release(end, Qt.LeftButton),
    )

    assert move_consumed is False
    assert release_consumed is False
    assert added == []


def test_annotation_right_press_deletes_nearest_remark(canvas, monkeypatch):
    from PyQt5.QtCore import QPoint

    canvas.set_remark_enabled(True)
    point = QPoint(80, 90)
    removed = []
    monkeypatch.setattr(
        canvas,
        "_remove_remark_at_viewport_pos",
        lambda pos: removed.append(pos),
        raising=False,
    )

    consumed = canvas.eventFilter(
        canvas._glw.viewport(),
        _mouse_press(point, Qt.RightButton),
    )

    assert consumed is True
    assert removed == [point]


def test_remark_disabled_noop(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(False)
    canvas.add_remark_at(5.0, 4.0)
    assert canvas._remarks == []


def test_value_at_maps_extent_to_cell(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # peak cell [row 2, col 3]: col 3 of 5 → x ∈ [6,8); row 2 of 4 → y ∈ [4,6)
    assert canvas._value_at(7.0, 5.0) == pytest.approx(100.0)


def test_grab_pixmap_scaled_nonnull(canvas, qapp):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # Force a layout pass so the inner GraphicsLayoutWidget has real
    # geometry under offscreen Qt (same precedent as the time-domain
    # _pg_canvas helper, test_pg_timedomain_canvas.py:535).
    canvas.show()
    qapp.processEvents()
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None and not pix.isNull()
    assert pix.width() >= canvas.width() * 2 - 2
    canvas.hide()


def test_grab_pixmap_export_center_pixels_not_all_white(canvas, qapp):
    # This repo has an OpenGL all-white-export history (time-domain
    # canvas); export tests must verify PIXELS, not just geometry
    # (pattern: test_pg_timedomain_canvas.py:1228 writes the rendered
    # offscreen output to /tmp for human inspection).
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True, cmap='turbo',
    )
    canvas.show()
    qapp.processEvents()
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None and not pix.isNull()
    out_path = "/tmp/pg_heatmap_grab_pixmap.png"
    assert pix.save(out_path), f"failed to write screenshot to {out_path!r}"
    # The heatmap fill spans the plot area; sample a 3x3 grid around the
    # image center — at least one sample must be a non-white colormap
    # pixel (turbo's low end is dark blue, its peak red; the white
    # GraphicsLayoutWidget background would mean a blank export).
    img = pix.toImage()
    w, h = img.width(), img.height()
    samples = [
        img.pixelColor(int(w * fx), int(h * fy))
        for fx in (0.35, 0.45, 0.55)
        for fy in (0.35, 0.45, 0.55)
    ]
    assert any(
        (c.red(), c.green(), c.blue()) != (255, 255, 255) for c in samples
    ), "center region of the exported heatmap is all white"
    canvas.hide()


def test_grab_pixmap_degenerate_fallback_is_unscaled_1x1(canvas, monkeypatch):
    # Lesson 2026-04-25-tightbbox-survives-offscreen-qt: the 1x1
    # degenerate fallback must stay 1x1 regardless of requested scale
    # (precedent: test_hidpi_grab_preserves_offscreen_fallback,
    # test_pg_timedomain_canvas.py:4301 — force grab() null).
    from PyQt5.QtGui import QPixmap

    monkeypatch.setattr(canvas, "grab", lambda *a, **k: QPixmap())
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None
    assert not pix.isNull(), "fallback pixmap must not be null"
    assert (pix.width(), pix.height()) == (1, 1), (
        f"expected un-scaled 1x1 fallback, got {pix.width()}x{pix.height()}"
    )


def test_full_reset_clears_state(canvas):
    # File-close contract (ChartStack.full_reset_all): every trace of the
    # previous result must go — remarks, result flag, colorbar, matrix.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1  # precondition pins the scenario
    canvas.full_reset()
    assert canvas._remarks == []
    assert not canvas.has_result()
    assert canvas._cbar is None
    assert canvas._matrix_disp is None


def test_full_reset_clears_empty_hint(canvas):
    canvas.show_empty_hint("点击『计算』生成")
    assert canvas._empty_hint_item is not None
    assert canvas._empty_hint_item.scene() is not None
    assert canvas._empty_hint_item.isVisible()

    canvas.full_reset()

    assert canvas._empty_hint_text == ""
    assert canvas._empty_hint_item is None


def test_full_reset_then_replot_rebuilds_colorbar(canvas):
    # full_reset detaches the ColorBarItem from the host PlotItem's
    # QGraphicsGridLayout (pg 0.14.0 ColorBarItem.py:225 nests it via
    # ``insert_in.layout.addItem(self, 2, 5)``). This path couples to pg
    # internals, so pin the layout item count across reset+replot: a pg
    # upgrade that breaks the detach would leak an orphaned colorbar
    # column on every file-close/replot cycle.
    baseline = canvas._plot.layout.count()
    m1 = np.linspace(0.0, 10.0, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m1, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.0), pytest.approx(10.0))
    assert canvas._plot.layout.count() == baseline + 1  # bar inserted
    canvas.full_reset()
    assert canvas._plot.layout.count() == baseline  # no orphan item left
    m2 = np.linspace(0.5, 4.5, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m2, x_extent=(0.0, 5.0), y_extent=(0.0, 4.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas._cbar is not None
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.5), pytest.approx(4.5))
    blo, bhi = canvas._cbar.levels()
    assert (blo, bhi) == (pytest.approx(lo), pytest.approx(hi))
    # Rebuilt bar occupies exactly one layout slot again — count is
    # restored, not accumulated.
    assert canvas._plot.layout.count() == baseline + 1


def test_colorbar_rounding_adapts_to_level_span(canvas):
    # Default ColorBarItem rounding=1 snaps drags to whole units and
    # enforces a minimum 1-unit span — unusable when the full linear
    # span is 0.5. Rounding must scale with the level span.
    m = np.linspace(0.0, 0.5, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas._cbar.rounding == pytest.approx(0.5 / 1000.0)


@pytest.mark.parametrize("with_slice", [False, True])
def test_heatmap_plots_draw_full_neutral_axis_frame_without_viewbox_overlap(
    qapp, with_slice
):
    from mf4_analyzer.ui._axis_handle import (
        PG_AXIS_NEUTRAL_COLOR,
        PG_AXIS_NEUTRAL_WIDTH,
    )

    c = PgHeatmapCanvas(with_slice=with_slice)
    try:
        plots = [c._plot]
        if with_slice:
            plots.append(c._slice_plot)

        for plot in plots:
            assert getattr(plot.getViewBox(), "border", None) is None
            for side in ("left", "bottom", "top", "right"):
                axis = plot.getAxis(side)
                assert axis.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
                assert axis.pen().widthF() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH)
            assert plot.getAxis("top").isVisible()
            assert plot.getAxis("right").isVisible()
            assert plot.getAxis("top").style.get("showValues") is False
            assert plot.getAxis("right").style.get("showValues") is False
            assert float(plot.getAxis("top").height()) <= 4.0
            assert float(plot.getAxis("right").width()) <= 4.0
    finally:
        c.deleteLater()


# ----------------------------------------------------------------------
# FFT-vs-Time slice row (with_slice=True). Task 7.
# ----------------------------------------------------------------------
def _spec_result():
    freqs = np.linspace(0, 500, 64)
    times = np.linspace(0, 2.0, 10)
    amp = np.random.RandomState(7).rand(64, 10).astype(np.float32) + 0.01
    return SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=128),
        channel_name='vib', unit='g', metadata={'frames': 10},
    )


def _make_spec(channel, amplitude):
    freqs = np.linspace(0, 500, 16)
    times = np.linspace(0, 1.0, 4)
    return SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amplitude,
        params=SpectrogramParams(fs=1000.0, nfft=32),
        channel_name=channel, unit='g', metadata={'frames': 4},
    )


def test_plot_result_db_reference_comes_from_kwarg_not_params(qapp):
    """db_reference is a render-time kwarg (display-only), NOT a field on
    result.params.

    The dB matrix must use the value passed to ``plot_result(db_reference=...)``.
    With reference=2.0, a unit-amplitude matrix becomes 20*log10(1/2) ~= -6.02 dB
    everywhere; with the default reference=1.0 it would be 0 dB. Proving the
    kwarg drives the conversion confirms db_reference left the compute contract
    (SpectrogramParams) and travels render-side only.
    """
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo',
                  z_auto=False, z_floor=-80.0, z_ceiling=0.0,
                  db_reference=2.0)
    md = c._matrix_disp
    np.testing.assert_allclose(md, 20.0 * np.log10(1.0 / 2.0), atol=1e-4)
    # Colorbar label reflects the kwarg reference.
    assert 'dB re 2' in c._cbar.getAxis('left').labelText
    c.deleteLater()


def test_plot_result_db_reference_defaults_to_one(qapp):
    """Omitting the kwarg keeps the historical ``db re 1`` behaviour so existing
    call sites (and tests) that never passed a reference are unchanged."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo',
                  z_auto=False, z_floor=-80.0, z_ceiling=0.0)
    md = c._matrix_disp
    np.testing.assert_allclose(md, 0.0, atol=1e-4)
    c.deleteLater()



# ----------------------------------------------------------------------
# dB-reference-defaults Task 7 (spec §15 C2/C3, §8.3.1): explicit label
# context + manual-color-level reference-change shift.
# ----------------------------------------------------------------------
def test_plot_result_amplitude_label_overrides_default_and_drives_slice_axis(qapp):
    """Explicit ``amplitude_label``/``colorbar_label`` (spec §15 C2 label
    context) drive BOTH the colorbar and the slice's left axis with the
    SAME text -- not two independently hard-coded strings."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))
    label = "Amplitude (dBA re 1×10⁻⁶ m/s²)"
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-80.0, z_ceiling=0.0,
        amplitude_label=label, colorbar_label=label,
    )
    assert c._cbar.getAxis('left').labelText == label
    assert c._slice_plot.getAxis('left').labelText == label
    c.deleteLater()


def test_plot_result_z_unit_suffix_drives_remark_and_readout_unit(qapp):
    """Explicit ``z_unit_suffix`` (spec §15 C2) is what ``_readout_unit`` /
    ``_z_unit`` return -- the same reference-aware phrase the colorbar/slice
    show, instead of the bare historical ``'dB'`` literal."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))
    suffix = "dBA re 1×10⁻⁶ m/s²"
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-80.0, z_ceiling=0.0,
        z_unit_suffix=suffix,
    )
    assert c._readout_unit() == suffix
    assert c._z_unit() == suffix
    c.deleteLater()


def test_heatmap_remark_z_unit_includes_db_or_dba_reference_context(qapp):
    """A point remark's Z= value must carry the SAME reference-aware suffix
    as the colorbar/slice, not the bare 'dB' literal (spec §15 C2/C3)."""
    from mf4_analyzer.ui.pg_canvas.remarks import format_remark_label

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    suffix = "dBA re 1×10⁻⁶ m/s²"
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True,
                  z_unit_suffix=suffix)
    point = c._remark_point_at(1.0, 250.0)
    assert point is not None
    msg = format_remark_label(point)
    assert suffix in msg, f"remark Z= must carry the reference suffix, got {msg!r}"
    c.hide()
    c.deleteLater()


def test_heatmap_linear_a_weighted_label_never_says_dba(qapp):
    """A-weighted LINEAR output must say 'A-weighted amplitude (unit)',
    never 'dBA' -- dBA is reserved for weighting=='A' AND a logarithmic (dB)
    output scale (spec §14.2)."""
    from mf4_analyzer import db_reference as dbref

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))
    resolution = dbref.DbReferenceResolution(
        value=1e-6, unit='m/s²', quantity='acceleration', source='system')
    label = dbref.format_amplitude_label(
        resolution, weighting='A', output_scale='linear')
    assert 'dBA' not in label
    c.plot_result(
        r, amplitude_mode='amplitude', cmap='turbo', z_auto=True,
        amplitude_label=label, colorbar_label=label,
    )
    assert 'dBA' not in c._cbar.getAxis('left').labelText
    assert 'dBA' not in c._slice_plot.getAxis('left').labelText
    c.deleteLater()


def test_heatmap_manual_levels_shift_with_reference_delta(qapp):
    """Spec §8.3.1: when the effective reference changes between two renders
    while a MANUAL z-window (``z_auto=False``) is active, ``plot_result``
    shifts the applied levels by ``delta = 20*log10(ref_old/ref_new)`` -- the
    SAME delta the (unclipped) dB matrix itself shifts by."""
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))

    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=False,
                  z_floor=-40.0, z_ceiling=0.0, db_reference=1.0)
    levels_before = c._img.getLevels()
    assert tuple(levels_before) == pytest.approx((-40.0, 0.0))
    assert c._last_manual_levels_shifted is None, (
        "no prior render on this canvas -> nothing to shift yet")

    # Reference shrinks 1.0 -> 1e-6: delta = 20*log10(1.0/1e-6) = 120 dB.
    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=False,
                  z_floor=-40.0, z_ceiling=0.0, db_reference=1e-6)
    delta = 20.0 * np.log10(1.0 / 1e-6)
    levels_after = c._img.getLevels()
    assert tuple(levels_after) == pytest.approx((-40.0 + delta, 0.0 + delta))
    assert c._last_manual_levels_shifted == pytest.approx(tuple(levels_after))
    c.deleteLater()


def test_heatmap_auto_levels_rederive_after_reference_change(qapp):
    """Spec §8.3.1: AUTO z-levels simply re-derive from the new matrix on a
    reference change -- no extra delta shift on top of what
    ``_auto_db_window`` already computes from the (naturally-shifted)
    matrix, and the manual-shift bookkeeping stays untouched."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _auto_db_window

    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    r = _make_spec('ref', np.ones((16, 4), dtype=np.float32))

    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True, db_reference=1.0)
    levels_before = c._img.getLevels()
    assert tuple(levels_before) == pytest.approx(_auto_db_window(c._matrix_disp))

    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True, db_reference=1e-6)
    levels_after = c._img.getLevels()
    assert tuple(levels_after) == pytest.approx(_auto_db_window(c._matrix_disp))
    assert c._last_manual_levels_shifted is None
    c.deleteLater()


def test_heatmap_level_shift_never_clips_matrix(qapp):
    """Spec §8.3.1 red line (2026-06-21 colour-scale incident): the
    reference-change shift touches ONLY the display levels, never the
    stored matrix -- the matrix must still span its true (unclipped) range
    after a manual-window shift."""
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    amp = np.array([[0.001, 1.0], [0.01, 10.0]], dtype=np.float32)
    r = _make_spec('ref', amp)

    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=False,
                  z_floor=-5.0, z_ceiling=5.0, db_reference=1.0)
    expected_first = 20.0 * np.log10(amp.astype(float) / 1.0)
    np.testing.assert_allclose(c._matrix_disp, expected_first, atol=1e-3)

    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=False,
                  z_floor=-5.0, z_ceiling=5.0, db_reference=1e-6)
    expected_second = 20.0 * np.log10(amp.astype(float) / 1e-6)
    np.testing.assert_allclose(c._matrix_disp, expected_second, atol=1e-3)
    # The matrix must NOT be clamped to the (shifted) [vmin, vmax] window --
    # cells both below the floor and above the ceiling must survive intact.
    vmin, vmax = c._img.getLevels()
    assert c._matrix_disp.min() < vmin
    assert c._matrix_disp.max() > vmax
    c.deleteLater()


def test_db_memo_keys_on_epoch_token_not_id(qapp):
    """Regression for V7 commit 6d539d1c: the dB memo keys on a stamped
    monotonic epoch token, NOT ``id(result)``.

    After an ``AnalysisResultCache`` LRU eviction frees a SpectrogramResult,
    CPython can reuse that id() for the NEXT result; an ``id()``-keyed dB memo
    would then serve result A's dB matrix for result B (silent stale image).

    We make the bug DETERMINISTIC by simulating an id() collision directly:
    plot A (caches A's dB under A's token), then HAND-INJECT a fake cache
    entry keyed on A's ``id()`` (what the old code would have produced) and
    verify the current code does NOT read it for a distinct B — because B
    carries its own distinct epoch token. We also assert the two results get
    different tokens, which is the property the fix guarantees.
    """
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)

    result_a = _make_spec('A', np.ones((16, 4), dtype=np.float32))
    c.plot_result(result_a, amplitude_mode='amplitude_db', z_auto=True)
    token_a = result_a._pg_db_epoch
    disp_a = c._matrix_disp.copy()

    # Result B: DIFFERENT amplitude (a ramp). Stamp B's token first so we can
    # assert it differs from A's even when their id()s would collide.
    ramp = np.tile(
        np.linspace(0.01, 100.0, 16, dtype=np.float32)[:, None], (1, 4))
    result_b = _make_spec('B', ramp)
    token_b = c._result_db_token(result_b)
    # The stamped tokens MUST differ — this is the whole fix. (Two live
    # objects always get distinct monotonic epoch tokens; an id()-keyed token
    # could collide once the first object is freed and its id() reused.)
    assert token_b != ('epoch', token_a), "epoch token collided"
    assert result_b._pg_db_epoch != token_a

    # Poison the memo with an entry keyed on result_b's CPython id() and a
    # dB ref of 1.0 — the exact shape the OLD ``(id(result), db_ref)`` key
    # produced. If the current memo still consulted id(), plotting B would
    # return this poisoned (A's flat) matrix instead of B's ramp.
    c._db_cache = ((('id', id(result_b)), 1.0), disp_a)
    c.plot_result(result_b, amplitude_mode='amplitude_db', z_auto=True)
    disp_b = c._matrix_disp.copy()

    # B's displayed dB matrix reflects B's ramp, not A's poisoned flat matrix.
    assert not np.allclose(disp_b, disp_a), (
        "B rendered A's stale dB matrix — id()-keyed memo bug regressed"
    )
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
    expected_b = SpectrogramAnalyzer.amplitude_to_db(ramp, 1.0)
    np.testing.assert_allclose(disp_b, expected_b, rtol=1e-5)
    c.deleteLater()


def test_slice_updates_on_select(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    c.select_time_index(3)
    xs, ys = c._slice_curve.getData()
    assert len(xs) == 64
    # slice shows the SAME display-space (dB) values as column 3
    expected = c._matrix_disp[:, 3]
    np.testing.assert_allclose(ys, expected, rtol=1e-6)
    c.deleteLater()


def test_slice_hint_emits_when_scene_click_has_no_slice_data(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    hints = []
    c.slice_hint_requested.connect(hints.append)

    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 1.0))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))

    assert hints == ["先点计算生成谱图"]
    c.hide()
    c.deleteLater()


def test_slice_out_of_range_emits_hint(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    hints = []
    picks = []
    c.slice_hint_requested.connect(hints.append)
    c.slice_picked.connect(lambda: picks.append(True))

    x0, _x1, y0, y1 = c._extents
    c._select_slice_at(x0 - 1.0, (y0 + y1) / 2.0)

    assert hints == ["点击位置超出谱图范围"]
    assert picks == []
    c.deleteLater()


def test_slice_hint_not_emitted_for_in_range_pick(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    hints = []
    picks = []
    c.slice_hint_requested.connect(hints.append)
    c.slice_picked.connect(lambda: picks.append(True))

    x0, x1, y0, y1 = c._extents
    c._select_slice_at((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    assert hints == []
    assert picks == [True]
    c.deleteLater()


def test_y_slice_scene_click_hint_and_pick_paths(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    c.set_slice_direction('y')
    hints = []
    picks = []
    c.slice_hint_requested.connect(hints.append)
    c.slice_picked.connect(lambda: picks.append(True))

    x0, x1, y0, y1 = c._extents
    x_mid = (x0 + x1) / 2.0
    y_out = y0 - max((y1 - y0) * 0.1, 1.0)
    c._plot.setYRange(y_out, y1, padding=0)
    qapp.processEvents()

    sp = c._plot.vb.mapViewToScene(QPointF(x_mid, y_out))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))

    assert hints == ["点击位置超出谱图范围"]
    assert picks == []

    hints.clear()
    y_pick = float(r.frequencies[10])
    sp = c._plot.vb.mapViewToScene(QPointF(x_mid, y_pick))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))

    assert hints == []
    assert picks == [True]
    assert c._slice_marker.value() == pytest.approx(y_pick)
    c.hide()
    c.deleteLater()


def test_slice_uses_relevant_axis_only(qapp):
    """y-slice: only y must be in range; x out-of-range is fine (and vice versa)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    hints = []
    picks = []
    c.slice_hint_requested.connect(hints.append)
    c.slice_picked.connect(lambda: picks.append(True))

    x0, x1, y0, y1 = c._extents

    # --- y-slice: x out-of-range but y valid → should succeed (not emit hint) ---
    c.set_slice_direction('y')
    x_out = x1 + max((x1 - x0) * 0.1, 1.0)
    y_valid = (y0 + y1) / 2.0
    c._select_slice_at(x_out, y_valid)
    assert hints == [], f"y-slice with x out-of-range should NOT emit hint, got: {hints}"
    assert picks == [True], "y-slice with x out-of-range but y valid should emit slice_picked"
    hints.clear()
    picks.clear()

    # --- y-slice: y out-of-range → should emit hint ---
    y_out = y0 - max((y1 - y0) * 0.1, 1.0)
    c._select_slice_at((x0 + x1) / 2.0, y_out)
    assert hints == ["点击位置超出谱图范围"], "y-slice with y out-of-range should emit range hint"
    assert picks == []
    hints.clear()

    # --- x-slice: y out-of-range but x valid → should succeed ---
    c.set_slice_direction('x')
    x_valid = (x0 + x1) / 2.0
    y_out2 = y1 + max((y1 - y0) * 0.1, 1.0)
    c._select_slice_at(x_valid, y_out2)
    assert hints == [], f"x-slice with y out-of-range should NOT emit hint, got: {hints}"
    assert picks == [True], "x-slice with y out-of-range but x valid should emit slice_picked"
    hints.clear()
    picks.clear()

    # --- x-slice: x out-of-range → should emit hint ---
    x_out2 = x0 - max((x1 - x0) * 0.1, 1.0)
    c._select_slice_at(x_out2, (y0 + y1) / 2.0)
    assert hints == ["点击位置超出谱图范围"], "x-slice with x out-of-range should emit range hint"
    assert picks == []

    c.deleteLater()


def _slice_curve_aa_enabled(canvas):
    curve = canvas._slice_curve
    child = getattr(curve, "curve", None)
    assert child is not None
    return (
        bool(curve.opts.get("antialias", False)),
        bool(child.opts.get("antialias", False)),
    )


def test_heatmap_slice_curve_aa_drops_until_idle(qapp, monkeypatch):
    """The 1D slice curve should mirror TimeDomain/FFT interaction quality:
    crisp at rest, non-AA while the user pans/drags, then crisp again after
    a hands-off idle tick."""
    from PyQt5.QtWidgets import QApplication

    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(640, 480)
        c.show()
        qapp.processEvents()
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)

        assert _slice_curve_aa_enabled(c) == (True, True)

        vb = c._slice_plot.vb
        vb.sigRangeChangedManually.emit(vb.state['mouseEnabled'])

        assert c._slice_aa_on is False
        assert c._slice_aa_idle_timer.isActive()
        assert _slice_curve_aa_enabled(c) == (False, False)

        monkeypatch.setattr(
            QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton))
        c._slice_aa_idle_timer.stop()
        c.try_enable_idle_quality()

        assert c._slice_aa_on is True
        assert _slice_curve_aa_enabled(c) == (True, True)
    finally:
        c.deleteLater()


def test_heatmap_slice_ctrl_wheel_drops_curve_aa(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(640, 480)
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)

        assert _slice_curve_aa_enabled(c) == (True, True)
        consumed = c._handle_wheel_dispatch(
            delta=120,
            modifiers=Qt.ControlModifier,
            x_pos=250.0,
            y_pos=-30.0,
            view_box=c._slice_plot.vb,
        )

        assert consumed is True
        assert c._slice_aa_on is False
        assert c._slice_aa_idle_timer.isActive()
        assert _slice_curve_aa_enabled(c) == (False, False)
    finally:
        c.deleteLater()


def test_heatmap_slice_marker_drag_drops_curve_aa(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(640, 480)
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)

        assert _slice_curve_aa_enabled(c) == (True, True)
        c._slice_marker.setValue(float(c._slice_marker.value()) + 0.2)

        assert c._slice_aa_on is False
        assert c._slice_aa_idle_timer.isActive()
        assert _slice_curve_aa_enabled(c) == (False, False)
    finally:
        c.deleteLater()


def test_heatmap_slice_marker_hover_pen_highlights_line(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(640, 480)
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)

        marker = c._slice_marker
        assert marker.pen.widthF() <= 1.5
        assert marker.hoverPen.widthF() >= 3.0

        marker.setMouseHover(True)
        assert marker.currentPen.widthF() == pytest.approx(
            marker.hoverPen.widthF())

        marker.setMouseHover(False)
        assert marker.currentPen.widthF() == pytest.approx(marker.pen.widthF())

        c.set_slice_direction('y')
        assert marker.angle == 0
        assert marker.hoverPen.widthF() >= 3.0
    finally:
        c.deleteLater()


def test_plot_result_without_slice_flag_has_no_slice_row(qapp):
    c = PgHeatmapCanvas(with_slice=False)
    assert not hasattr(c, '_slice_curve') or c._slice_curve is None
    c.deleteLater()


def test_heatmap_axes_use_time_domain_chart_font(canvas):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    for side in ("left", "bottom"):
        family, size, label_family, label_size = _axis_font_family_size(
            canvas._plot.getAxis(side)
        )
        assert family == expected.family()
        assert size == pytest.approx(9.0)
        assert label_family == expected.family()
        assert label_size == pytest.approx(9.0)


def test_heatmap_slice_and_colorbar_axes_use_chart_font(qapp):
    from mf4_analyzer.ui.pg_canvas.fonts import _pg_chart_font

    expected = _pg_chart_font(9)
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.plot_or_update_heatmap(
            matrix=_mat(),
            x_extent=(0.0, 1.0),
            y_extent=(10.0, 50.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.select_time_index(2)

        axes = [
            c._slice_plot.getAxis("left"),
            c._slice_plot.getAxis("bottom"),
            c._cbar.getAxis("left"),
            c._cbar.getAxis("right"),
        ]
        for axis in axes:
            family, size, label_family, label_size = _axis_font_family_size(axis)
            assert family == expected.family()
            assert size == pytest.approx(9.0)
            assert label_family == expected.family()
            assert label_size == pytest.approx(9.0)
    finally:
        c.deleteLater()


def test_heatmap_narrow_bottom_ticks_are_pinned_and_fit(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(220, 620)
        c.show()
        qapp.processEvents()
        c.plot_or_update_heatmap(
            matrix=_mat(),
            x_extent=(0.0, 30.0),
            y_extent=(10.0, 50.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.select_time_index(2)
        c.set_tick_density(10, 8)
        qapp.processEvents()

        for plot in (c._plot, c._slice_plot):
            axis = plot.getAxis("bottom")
            labels = _bottom_tick_labels(axis)
            assert 3 <= len(labels) <= 10
            assert getattr(axis, "_tickLevels", None), "bottom axis should be pinned"
    finally:
        c.deleteLater()


def test_heatmap_bottom_ticks_recompute_after_x_range_change(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(360, 620)
        c.show()
        qapp.processEvents()
        c.plot_or_update_heatmap(
            matrix=_mat(),
            x_extent=(0.0, 30.0),
            y_extent=(10.0, 50.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.select_time_index(2)
        c.set_tick_density(10, 8)
        qapp.processEvents()

        c._plot.setXRange(10.0, 20.0, padding=0)
        qapp.processEvents()

        values = _bottom_tick_values(c._plot.getAxis("bottom"))
        assert values
        assert min(values) >= 10.0 - 1e-6
        assert max(values) <= 20.0 + 1e-6
    finally:
        c.deleteLater()


def test_heatmap_tick_density_preserves_manual_x_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(360, 620)
        c.show()
        qapp.processEvents()
        c.plot_or_update_heatmap(
            matrix=_mat(),
            x_extent=(0.0, 30.0),
            y_extent=(10.0, 50.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c._plot.setXRange(10.0, 20.0, padding=0)
        qapp.processEvents()

        c.set_tick_density(10, 8)
        qapp.processEvents()

        x_range, _ = c._plot.vb.viewRange()
        assert x_range[0] == pytest.approx(10.0)
        assert x_range[1] == pytest.approx(20.0)
    finally:
        c.deleteLater()


def test_heatmap_unshown_bottom_ticks_fall_back_to_density():
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.plot_or_update_heatmap(
            matrix=_mat(),
            x_extent=(0.0, 30.0),
            y_extent=(10.0, 50.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            cbar_label="Amplitude",
        )
        c.select_time_index(2)
        c.set_tick_density(10, 8)

        for plot in (c._plot, c._slice_plot):
            axis = plot.getAxis("bottom")
            assert not getattr(axis, "_tickLevels", None)
    finally:
        c.deleteLater()


def _target_bottom_ticks_for(qapp, lo, hi, *, width, target=10):
    """Run ``_apply_target_bottom_ticks`` against a real axis of ``width`` px
    over the view range ``[lo, hi]`` and return the pinned tick values."""
    glw = pg.GraphicsLayoutWidget()
    glw.resize(int(width) + 80, 400)
    plot = _make_analysis_plot(glw, 0, 0, pg.ViewBox())
    glw.show()
    qapp.processEvents()
    axis = plot.getAxis("bottom")
    plot.vb.setXRange(lo, hi, padding=0)
    # Pin the axis to the exact width the regression depends on.
    axis.setWidth(float(width))
    qapp.processEvents()
    ok = _apply_target_bottom_ticks(axis, plot.vb, target, glw)
    try:
        return ok, _bottom_tick_values(axis)
    finally:
        glw.deleteLater()


def test_bottom_ticks_span_to_right_edge_for_nonround_range(qapp):
    # Regression: an FFT spectrum auto-x range like [0, 7.162] must not leave a
    # large blank gap at the right. The over-fine-step candidate (e.g. 0.01)
    # used to win by thinning down to exactly the target count, stopping near
    # 4.57 and leaving ~36% of the axis tickless.
    ok, values = _target_bottom_ticks_for(qapp, 0.0, 7.162, width=505)
    assert ok and len(values) >= 3
    spacing = min(
        b - a for a, b in zip(values, values[1:]) if b > a
    )
    gap = 7.162 - max(values)
    assert gap <= 1.5 * spacing, (
        f"rightmost tick {max(values):.3f} leaves a {gap:.3f} blank "
        f"(> 1.5x spacing {spacing:.3f}) before the edge 7.162; ticks={values}"
    )


def test_bottom_ticks_use_round_grid_for_nonround_range(qapp):
    # The pinned ticks should sit on a clean grid anchored at 0 (e.g. 1,2,3,…)
    # rather than arbitrary thinned positions (0.21, 0.69, 1.16, …).
    _ok, values = _target_bottom_ticks_for(qapp, 0.0, 7.162, width=505)
    spacing = min(
        b - a for a, b in zip(values, values[1:]) if b > a
    )
    for value in values:
        ratio = value / spacing
        assert abs(ratio - round(ratio)) <= 0.05, (
            f"tick {value:.3f} is off the {spacing:.3f} grid; ticks={values}"
        )


def test_heatmap_canvas_uses_compact_outer_pg_layout(canvas):
    layout = canvas._glw.ci.layout
    assert layout.getContentsMargins() == pytest.approx((2.0, 2.0, 2.0, 2.0))
    assert layout.horizontalSpacing() == pytest.approx(2.0)
    assert layout.verticalSpacing() == pytest.approx(2.0)


def test_heatmap_slice_canvas_preserves_split_gap(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        layout = c._glw.ci.layout
        assert layout.getContentsMargins() == pytest.approx((2.0, 2.0, 2.0, 2.0))
        assert layout.horizontalSpacing() == pytest.approx(2.0)
        assert layout.verticalSpacing() == pytest.approx(18.0)
    finally:
        c.deleteLater()


def test_slice_direction_toggle_switches_axis(qapp):
    """The X/Y switch flips the slice between a fixed-time cut (amp vs freq,
    vertical marker) and a fixed-frequency cut (amp vs time, horizontal
    marker)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()  # 64 freqs × 10 times
    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True)

    # Default = X slice: amp vs frequency (64), vertical marker.
    xs, _ = c._slice_curve.getData()
    assert len(xs) == 64
    assert c._slice_marker.angle == 90

    # Switch to Y slice: amp vs time (10), horizontal marker.
    c.set_slice_direction('y')
    xs, _ = c._slice_curve.getData()
    assert len(xs) == 10
    assert c._slice_marker.angle == 0
    assert c._slice_plot.getAxis('bottom').labelText == 'Time (s)'
    c.deleteLater()


def test_order_style_slice_works_without_result(qapp):
    """The Order map renders via plot_or_update_heatmap (no SpectrogramResult);
    the slice still works off the supplied x/y coords in both directions."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.set_slice_button_labels('按时间', '按阶次')
    c.set_slice_direction('y')
    orders = np.linspace(0, 10, 32)
    times = np.linspace(0, 3, 20)
    mat = np.random.RandomState(4).rand(32, 20)
    c.plot_or_update_heatmap(
        matrix=mat, x_extent=(0, 3), y_extent=(0, 10),
        x_label='Time (s)', y_label='Order', x_coords=times, y_coords=orders)
    c._seed_slice()

    # Y slice (按阶次): amp vs time (20 frames).
    xs, _ = c._slice_curve.getData()
    assert len(xs) == 20
    assert c._slice_marker.angle == 0

    # Switch to X slice (按时间): amp vs order (32).
    c.set_slice_direction('x')
    xs, _ = c._slice_curve.getData()
    assert len(xs) == 32
    assert c._slice_marker.angle == 90
    # Toggle reads the order-specific captions.
    assert c._slice_toggle._btn_y.text() == '按阶次'
    c.deleteLater()


def test_slice_aligns_with_heatmap_and_panel_in_colorbar_column(qapp):
    """The slice plot's right edge is pulled in to match the heatmap (whose
    right edge is inset by the colorbar), so their time axes line up; the X/Y
    info panel sits in the freed colorbar column to the right of the slice."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(620, 470)
    c.set_slice_button_labels('按时间', '按阶次')
    c.set_slice_direction('y')
    orders = np.linspace(0, 20, 40)
    times = np.linspace(0, 90, 60)
    mat = np.random.RandomState(5).rand(40, 60)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=mat, x_extent=(0, 90), y_extent=(0, 20),
        x_label='Time (s)', y_label='Order', cbar_label='Amplitude',
        x_coords=times, y_coords=orders, z_auto=True)
    c._seed_slice()
    for _ in range(5):
        qapp.processEvents()
    main_r = float(c._plot.vb.sceneBoundingRect().right())
    slice_r = float(c._slice_plot.vb.sceneBoundingRect().right())
    assert abs(slice_r - main_r) <= 3, (
        f"slice time axis not aligned with heatmap: {slice_r} vs {main_r}")
    assert not c._slice_panel.isHidden()
    # panel begins at/after the aligned slice's right edge (the freed column)
    assert c._slice_panel.geometry().x() >= int(slice_r) - 6
    c.deleteLater()


def test_grab_pixmap_includes_slice_info_panel(qapp):
    """Copy/export should include the right-side slice panel, not only _glw.

    The panel is a QWidget child over the GraphicsLayoutWidget (not a pg scene
    item), so grabbing only ``_glw`` drops the Time/Frequency/Order readout the
    user sees at bottom-right.
    """
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(620, 470)
    c.set_slice_button_labels('时间', '阶次')
    c.set_slice_direction('y')
    orders = np.linspace(0, 20, 40)
    times = np.linspace(0, 90, 60)
    mat = np.random.RandomState(5).rand(40, 60)
    try:
        c.show()
        qapp.processEvents()
        c.plot_or_update_heatmap(
            matrix=mat, x_extent=(0, 90), y_extent=(0, 20),
            x_label='Time (s)', y_label='Order', cbar_label='Amplitude',
            x_coords=times, y_coords=orders, z_auto=True)
        c._seed_slice()
        for _ in range(5):
            qapp.processEvents()
        c._slice_panel.setStyleSheet(
            "QWidget#slicePanel { background-color: #ff00ff; }"
            "QLabel#sliceHint { background-color: #ff00ff; color: #ff00ff; }"
        )
        c._slice_panel.update()
        qapp.processEvents()

        pix = c.grab_pixmap(scale=2.0)
        assert pix is not None and not pix.isNull()
        img = pix.toImage()
        scale_x = img.width() / max(1, c.width())
        scale_y = img.height() / max(1, c.height())
        geo = c._slice_panel.geometry()
        samples = []
        for fx, fy in ((0.50, 0.50), (0.35, 0.35), (0.65, 0.65)):
            px = int(round((geo.x() + geo.width() * fx) * scale_x))
            py = int(round((geo.y() + geo.height() * fy) * scale_y))
            px = min(max(px, 0), img.width() - 1)
            py = min(max(py, 0), img.height() - 1)
            samples.append(img.pixelColor(px, py).name().lower())
        assert "#ff00ff" in samples, (
            "grab_pixmap dropped the QWidget slice panel; sampled colors="
            f"{samples!r} at panel geometry={geo}"
        )
    finally:
        c.deleteLater()


def test_slice_right_frame_visible_after_colorbar_reserve(qapp):
    """The slice (下方图) keeps a VISIBLE right frame line even though the right
    axis reserves the colorbar-column spacer, so the plot box closes on the
    right (aligned with the heatmap). Regression: the width>0 branch previously
    set a fully-transparent pen, leaving the box open on the right."""
    from mf4_analyzer.ui._axis_handle import (
        PG_AXIS_NEUTRAL_COLOR,
        PG_AXIS_NEUTRAL_WIDTH,
    )

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(620, 470)
    c.set_slice_button_labels('按时间', '按阶次')
    c.set_slice_direction('y')
    orders = np.linspace(0, 20, 40)
    times = np.linspace(0, 90, 60)
    mat = np.random.RandomState(5).rand(40, 60)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=mat, x_extent=(0, 90), y_extent=(0, 20),
        x_label='Time (s)', y_label='Order', cbar_label='Amplitude',
        x_coords=times, y_coords=orders, z_auto=True)
    c._seed_slice()
    for _ in range(5):
        qapp.processEvents()
    # _align_slice_to_main has run with a real (colorbar-inset) reserve.
    ax = c._slice_plot.getAxis('right')
    assert ax.isVisible()
    # Pen must NOT be transparent — the frame line is what closes the box.
    assert ax.pen().color().alpha() > 0
    assert ax.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
    assert ax.pen().widthF() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH)
    # Tick text stays hidden; the right axis is a frame line only.
    assert ax.style.get('showValues') is False
    # The colorbar-column reserve is still in place (right edge inset).
    main_r = float(c._plot.vb.sceneBoundingRect().right())
    slice_r = float(c._slice_plot.vb.sceneBoundingRect().right())
    assert abs(slice_r - main_r) <= 3
    # Right-axis grid stays off (tests elsewhere assert right.grid is False).
    assert ax.grid is False
    c.deleteLater()


def test_slice_right_frame_visible_without_colorbar_reserve(qapp):
    """The slice right frame remains visible when the colorbar column is absent."""
    from mf4_analyzer.ui._axis_handle import (
        PG_AXIS_NEUTRAL_COLOR,
        PG_AXIS_NEUTRAL_WIDTH,
    )

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(620, 470)
    c.show()
    qapp.processEvents()

    # Force the colorbar-less/no-reserve geometry path. The constructor builds a
    # colorbar for normal FFT-vs-Time use, but _align_slice_to_main must still
    # leave the slice box closed if a future caller has no colorbar reserve.
    assert c._cbar is not None
    try:
        c._plot.layout.removeItem(c._cbar)
    except Exception:
        pass
    scene = c._cbar.scene()
    if scene is not None:
        scene.removeItem(c._cbar)
    c._cbar = None
    for _ in range(3):
        qapp.processEvents()

    c._align_slice_to_main()
    qapp.processEvents()

    ax = c._slice_plot.getAxis('right')
    assert ax.isVisible()
    assert ax.pen().color().alpha() > 0
    assert ax.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
    assert ax.pen().widthF() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH)
    assert ax.style.get('showValues') is False
    assert ax.width() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH, abs=0.5)
    assert ax.grid is False
    c.deleteLater()


def test_heatmap_drag_near_bottom_collapses_and_rail_expands(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(900, 520); c.show(); qapp.processEvents()
    c._on_split_drag_started()
    c._on_split_drag_delta(-100000)
    assert c._bottom_collapsed is True
    assert not c._slice_plot.isVisible()
    assert c._collapsed_rail.isVisible()
    assert not c._split_divider.isVisible()
    if c._slice_panel is not None:
        assert not c._slice_panel.isVisible()
    c._collapsed_rail.expand_requested.emit()
    assert c._bottom_collapsed is False
    assert c._slice_plot.isVisible()
    assert not c._collapsed_rail.isVisible()
    c.hide()
    c.deleteLater()


def test_heatmap_no_slice_has_no_rail(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(with_slice=False)
    assert c._collapsed_rail is None
    assert c._split_divider is None
    c.deleteLater()


def test_heatmap_collapse_divider_folds_slice(qapp):
    """The collapse control on a with_slice heatmap folds the map or the slice;
    a no-slice heatmap has no rail."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(560, 460)
    c._on_collapse_changed('bottom')
    assert not c._slice_plot.isVisible()
    assert c._plot.isVisible()
    c._on_collapse_changed('none')
    assert c._slice_plot.isVisible()
    c.deleteLater()

    c2 = PgHeatmapCanvas(with_slice=False)
    assert c2._collapsed_rail is None
    c2.deleteLater()


def test_heatmap_split_divider_spans_full_canvas_width(qapp):
    """Shared divider widget reaches both canvas edges (Order / FFT-vs-Time)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(600, 480)
    c.show()
    qapp.processEvents()
    c._position_collapse_ctrl()
    c._position_collapse_ctrl()
    div = c._split_divider
    assert div is not None
    assert div.x() <= 1
    assert div.x() + div.width() >= c.width() - 1
    c.hide()
    c.deleteLater()


def test_heatmap_collapse_restores_default_height(qapp):
    """Fold-then-restore ALWAYS returns the slice to its default height
    (confirmed product decision), not the last dragged height — a near-collapse
    drag floor-clamps the remembered value, so restoring it would bring the
    slice back at half size; expand resets to the default (140) instead."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(600, 480)
    c.show()
    qapp.processEvents()
    c._on_split_drag_started()
    c._on_split_drag_delta(25)               # slice dragged to 165
    assert c._bottom_split_h == pytest.approx(165)
    c._on_collapse_changed('bottom')
    assert not c._slice_plot.isVisible()
    c._on_collapse_changed('none')
    assert c._slice_plot.isVisible()
    # Expand restores the DEFAULT (140), NOT the last dragged 165.
    assert c._bottom_split_h == pytest.approx(140)
    assert c._slice_plot.maximumHeight() == 140
    c.hide()
    c.deleteLater()


def test_heatmap_drag_collapse_then_expand_restores_default_height(qapp):
    """Fix 1: a near-collapse drag floor-clamps _bottom_split_h to
    _SPLIT_MIN_BOTTOM in its final pre-fold step; expand must restore the slice
    at the DEFAULT height, not that clamped half-height."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        PgHeatmapCanvas, _SPLIT_MIN_BOTTOM)
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(900, 520); c.show(); qapp.processEvents()
    default = c._bottom_split_default
    c._on_split_drag_started()
    c._on_split_drag_delta(int(_SPLIT_MIN_BOTTOM - default) - 5)  # below floor
    assert c._bottom_split_h == pytest.approx(_SPLIT_MIN_BOTTOM)  # clamped
    c._on_split_drag_started()
    c._on_split_drag_delta(-100000)   # past collapse threshold → fold
    assert c._bottom_collapsed is True
    assert c._bottom_split_h == pytest.approx(_SPLIT_MIN_BOTTOM)
    # Expand: always returns to the default, NOT the clamped floor.
    c._set_bottom_collapsed(False)
    assert c._bottom_collapsed is False
    assert c._bottom_split_h == pytest.approx(default)
    assert c._slice_plot.maximumHeight() == int(default)
    c.hide()
    c.deleteLater()


def test_heatmap_single_pane_unifies_stacked_left_axis_widths(qapp):
    """Fix 2: in single-pane mode the heatmap and slice left axes must share one
    width so the two plot areas line up on the left (previously each kept its
    own natural width → misaligned left edges)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    for _ in range(5):
        qapp.processEvents()
    c.reset_split_layout_alignment()
    for _ in range(5):
        qapp.processEvents()
    main_w = float(c._plot.getAxis('left').width())
    slice_w = float(c._slice_plot.getAxis('left').width())
    assert main_w == pytest.approx(slice_w, abs=0.5), (
        f"stacked left axes not unified: main={main_w} slice={slice_w}")
    main_left = float(c._plot.vb.sceneBoundingRect().left())
    slice_left = float(c._slice_plot.vb.sceneBoundingRect().left())
    assert abs(main_left - slice_left) <= 2.0, (
        f"left edges misaligned: main={main_left} slice={slice_left}")
    c.hide()
    c.deleteLater()


def test_heatmap_empty_state_unifies_stacked_left_axis_widths(qapp):
    """Fix 2, empty state: the bare panel (no result) still shares one left-axis
    width across the map and the slice."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.reset_split_layout_alignment()
    for _ in range(3):
        qapp.processEvents()
    main_w = float(c._plot.getAxis('left').width())
    slice_w = float(c._slice_plot.getAxis('left').width())
    assert main_w == pytest.approx(slice_w, abs=0.5)
    c.hide()
    c.deleteLater()


def test_heatmap_axes_are_boundary_grid_axis_items(qapp):
    """Fix 3: the left+bottom axes of the map and slice use the boundary-grid-
    suppressing AxisItem subclass; top/right stay default (no grid)."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _BoundaryGridAxisItem
    c = PgHeatmapCanvas(with_slice=True)
    for plot in (c._plot, c._slice_plot):
        assert isinstance(plot.getAxis('left'), _BoundaryGridAxisItem)
        assert isinstance(plot.getAxis('bottom'), _BoundaryGridAxisItem)
    c.deleteLater()


def test_boundary_grid_axis_drops_only_edge_grid_lines(qapp, monkeypatch):
    """Fix 3 (filter logic): given a tickSpec list whose first/last lines sit on
    the linked-view rect edges and the rest are interior, the override drops
    exactly the two boundary lines and keeps every interior one — driven through
    a stubbed parent generateDrawSpecs so the filter is tested in isolation (no
    fake-painter text measurement, which crashes Qt's QPicture path)."""
    import pyqtgraph as pg
    from pyqtgraph import Point
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _BoundaryGridAxisItem, _BOUNDARY_GRID_EPS_PX)

    glw = pg.GraphicsLayoutWidget()
    # A real linked ViewBox so linkedView()/mapRectToItem return a real rect.
    plot = glw.addPlot(
        row=0, col=0,
        axisItems={'left': _BoundaryGridAxisItem(orientation='left')},
    )
    left = plot.getAxis('left')
    left.setGrid(120)
    glw.resize(400, 300)
    glw.show()
    qapp.processEvents()
    plot.setYRange(0.0, 1.0, padding=0.08)
    for _ in range(3):
        qapp.processEvents()

    rect = left.linkedView().mapRectToItem(left, left.linkedView().boundingRect())
    lo, hi = rect.top(), rect.bottom()
    interior = [lo + (hi - lo) * f for f in (0.25, 0.5, 0.75)]
    pen = pg.mkPen('#9ca3af')
    # Left axis → axis index 0 → value coordinate is p[1] (Y). Build specs whose
    # value-position sits at the boundary (lo, hi) and at the interior points.
    fake = []
    for vpos in [lo, hi, *interior]:
        p1 = Point(rect.right(), vpos)
        p2 = Point(rect.left(), vpos)
        fake.append((pen, p1, p2))
    axis_spec = (pen, Point(0, lo), Point(0, hi))

    monkeypatch.setattr(
        pg.AxisItem, 'generateDrawSpecs',
        lambda self, p: (axis_spec, list(fake), []))

    _ax, kept, _text = left.generateDrawSpecs(None)
    kept_vpos = sorted(round(p1[1], 3) for _pen, p1, _p2 in kept)
    # Both boundary lines dropped; all three interior lines survive.
    assert len(kept) == 3
    for v in kept_vpos:
        assert abs(v - lo) > _BOUNDARY_GRID_EPS_PX
        assert abs(v - hi) > _BOUNDARY_GRID_EPS_PX
    np.testing.assert_allclose(kept_vpos, sorted(round(v, 3) for v in interior))
    glw.hide()
    glw.deleteLater()


def test_boundary_grid_axis_passthrough_when_grid_off(qapp, monkeypatch):
    """Fix 3 guard: when the grid is off (self.grid is False) the override must
    NOT filter — short ticks at the edges (top/right axes) stay intact."""
    import pyqtgraph as pg
    from pyqtgraph import Point
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _BoundaryGridAxisItem

    axis = _BoundaryGridAxisItem(orientation='left')
    assert axis.grid is False  # default: no grid
    pen = pg.mkPen('#9ca3af')
    fake = [(pen, Point(10.0, 0.0), Point(0.0, 0.0)),
            (pen, Point(10.0, 50.0), Point(0.0, 50.0))]
    monkeypatch.setattr(
        pg.AxisItem, 'generateDrawSpecs',
        lambda self, p: ((pen, Point(0, 0), Point(0, 1)), list(fake), []))
    _ax, kept, _text = axis.generateDrawSpecs(None)
    assert len(kept) == 2  # untouched when grid is off
    axis.deleteLater()


def test_heatmap_split_reset_returns_to_default(qapp):
    """Double-click reset restores the heatmap's default slice height (140)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(600, 480)
    c.show()
    qapp.processEvents()
    c._on_split_drag_started()
    c._on_split_drag_delta(30)
    assert c._bottom_split_h == pytest.approx(170)
    c._on_split_reset()
    assert c._bottom_split_h == pytest.approx(140)
    assert c._slice_plot.maximumHeight() == 140
    c.hide()
    c.deleteLater()


def test_slice_marker_drag_reslices(qapp):
    """Dragging the marker snaps to the nearest cell and re-renders the slice."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()  # times 0..2 over 10 frames
    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True)
    c.select_time_index(0)  # X slice at t=0
    # Move the vertical marker to ~t=2.0 → should select the last frame.
    c._slice_marker.setValue(2.0)
    _xs, ys = c._slice_curve.getData()
    np.testing.assert_allclose(ys, c._matrix_disp[:, c._slice_x_idx], rtol=1e-6)
    assert c._slice_x_idx == 9
    c.deleteLater()


def test_plot_result_defaults_to_smooth_image_paint(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', cmap='turbo')

        assert c._img.smooth_transform_enabled() is True
    finally:
        c.deleteLater()


def test_plot_result_linear_manual_levels_not_overridden_by_auto_data(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude', cmap='turbo',
        z_auto=False, z_floor=0.0, z_ceiling=0.2,
    )

    lo, hi = c._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.0), pytest.approx(0.2))
    assert (float(np.nanmin(r.amplitude)), float(np.nanmax(r.amplitude))) != (
        pytest.approx(0.0), pytest.approx(0.2)
    )
    blo, bhi = c._cbar.levels()
    assert (blo, bhi) == (pytest.approx(0.0), pytest.approx(0.2))
    c.deleteLater()


def test_plot_result_uses_window_coverage_extent_when_available(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = SpectrogramResult(
        times=np.array([5.0, 7.0]),
        frequencies=np.array([0.0, 50.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=50.0, nfft=512),
        channel_name='vib',
        metadata={
            'frames': 2,
            'hop': 100,
            'freq_bins': 2,
            'coverage_start': 0.0,
            'coverage_end': 12.0,
        },
    )

    c.plot_result(r, amplitude_mode='amplitude', z_auto=True)

    x0, x1, _y0, _y1 = c._extents
    assert (x0, x1) == (pytest.approx(0.0), pytest.approx(12.0))
    (vx0, vx1), _ = c._plot.vb.viewRange()
    assert (vx0, vx1) == (pytest.approx(0.0), pytest.approx(12.0))
    c.deleteLater()


def test_time_axis_display_extent_clamps_nonnegative_fallback_start():
    lo, hi = time_axis_display_extent(
        np.array([0.0, 1.0]),
        params=SpectrogramParams(fs=1000.0, nfft=128),
        metadata={},
    )

    assert lo == pytest.approx(0.0)
    assert hi > 1.0


def test_plot_result_db_vmin_vmax_not_overridden_by_internal_auto(qapp):
    # The dB matrix + clip + levels are computed in plot_result; the
    # explicit vmin/vmax it hands to plot_or_update_heatmap must survive
    # (amplitude_mode='amplitude' + non-None vmin/vmax → no nanmin/nanmax
    # override). With z_auto=False the levels are exactly (z_floor,
    # z_ceiling), NOT the data's nanmin/nanmax.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-60.0, z_ceiling=-3.0, freq_range=None,
    )
    lo, hi = c._img.getLevels()
    assert (lo, hi) == (pytest.approx(-60.0), pytest.approx(-3.0))
    # If plot_or_update_heatmap's linear branch had re-derived levels from
    # the display matrix (nanmin/nanmax), it would NOT equal the explicit
    # (-60, -3) window — confirm the two differ so the test bites.
    clipped = c._matrix_disp
    auto_lo, auto_hi = float(np.nanmin(clipped)), float(np.nanmax(clipped))
    assert (auto_lo, auto_hi) != (pytest.approx(-60.0), pytest.approx(-3.0))
    # The colorbar mirrors the same explicit window, not a re-derived one.
    blo, bhi = c._cbar.levels()
    assert (blo, bhi) == (pytest.approx(-60.0), pytest.approx(-3.0))
    c.deleteLater()


def test_plot_result_db_auto_span_tracks_robust_ceiling(qapp):
    """Auto color-scale uses a fixed _AUTO_SPAN_DB span anchored at a robust
    high-percentile ceiling — NOT the z_floor spin value, and NOT the literal
    data max.

    Old contract (peak-offset): z_floor was treated as a *peak offset*, so the
    auto and manual windows used different semantics (peak-relative vs absolute),
    causing a 30+ dB jump when the user toggled auto off.

    Current contract: hi = _robust_db_ceiling(matrix) (the _AUTO_CEILING_PCT
    percentile) and lo = hi - _AUTO_SPAN_DB ALWAYS, regardless of z_floor.
    z_floor/z_ceiling have a single meaning: absolute dB values used in MANUAL
    mode only.  Anchoring on a percentile (not np.nanmax) keeps a lone transient
    peak from dragging the window up — see
    test_plot_result_db_auto_ceiling_ignores_outlier_peak.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _AUTO_CEILING_PCT, _AUTO_SPAN_DB, _robust_db_ceiling)

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = SpectrogramResult(
        times=np.array([0.0, 1.0]),
        frequencies=np.array([0.0, 10.0]),
        amplitude=np.array([[1e-16, 1e-15], [1e-12, 1e-10]], dtype=float),
        params=SpectrogramParams(fs=100.0, nfft=64),
        channel_name='quiet',
        metadata={'frames': 2},
    )

    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-50.0, z_ceiling=0.0,
    )

    ceiling = _robust_db_ceiling(c._matrix_disp, _AUTO_CEILING_PCT)
    lo, hi = c._img.getLevels()
    assert hi == pytest.approx(ceiling)
    # Fixed-span contract: lo = ceiling - _AUTO_SPAN_DB, regardless of z_floor.
    assert lo == pytest.approx(ceiling - _AUTO_SPAN_DB)
    assert hi < -100.0
    # Auto window is stored for the inspector write-back (auto→manual no jump).
    assert c._last_auto_levels == pytest.approx((ceiling - _AUTO_SPAN_DB, ceiling))
    c.deleteLater()


def test_auto_db_window_default_span_is_30(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    matrix = np.linspace(-50.0, 10.0, 6001).reshape(1, -1)

    vmin, vmax = hc._auto_db_window(matrix)

    ceiling = hc._robust_db_ceiling(matrix, hc._AUTO_CEILING_PCT)
    assert vmax == pytest.approx(ceiling)
    assert (vmax - vmin) == pytest.approx(30.0)


def test_plot_result_db_z_auto_window_uses_30db_span(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = SpectrogramResult(
        times=np.array([0.0, 1.0]),
        frequencies=np.array([0.0, 10.0]),
        amplitude=np.array([[1e-3, 1e-2], [1e-1, 1.0]], dtype=float),
        params=SpectrogramParams(fs=100.0, nfft=64),
        channel_name='wide',
        metadata={'frames': 2},
    )

    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0,
    )

    vmin, vmax = c._last_auto_levels
    assert (vmax - vmin) == pytest.approx(30.0)
    assert c._img.getLevels() == pytest.approx((vmin, vmax))
    c.deleteLater()


def test_plot_result_db_auto_ceiling_ignores_outlier_peak(qapp):
    """Regression (2026-06-21): a lone transient peak must NOT drag the auto
    ceiling up and bury the informative bulk below the floor.

    Real measurement spectra have sharp peaks tens of dB above the bulk.  The
    pre-fix auto window anchored the ceiling on np.nanmax, so the ceiling sat
    on the outlier and the whole field fell below the floor → an all-dark image
    the user had to drag down ~38 dB to read (the "拖色阶 vs 重算图不一样"
    report).  The robust percentile ceiling tracks the bulk top instead, so the
    outlier is clipped (saturated) and the bulk maps across the colormap.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _AUTO_CEILING_PCT, _AUTO_SPAN_DB, _robust_db_ceiling)

    rng = np.random.default_rng(0)
    # Bulk spread around -30 dB; ONE +30 dB transient outlier (a 1e3x spike).
    bulk_db = rng.normal(-30.0, 5.0, (64, 64))
    amp = 10.0 ** (bulk_db / 20.0)
    amp[0, 0] = 10.0 ** (30.0 / 20.0)

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    r = SpectrogramResult(
        times=np.arange(64, dtype=float),
        frequencies=np.arange(64, dtype=float),
        amplitude=amp,
        params=SpectrogramParams(fs=128.0, nfft=64),
        channel_name='spiky',
        metadata={'frames': 64},
    )
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-40.0, z_ceiling=0.0,
    )

    peak = float(np.nanmax(c._matrix_disp))
    ceiling = _robust_db_ceiling(c._matrix_disp, _AUTO_CEILING_PCT)
    lo, hi = c._img.getLevels()
    assert peak == pytest.approx(30.0, abs=0.5)         # outlier present
    assert hi == pytest.approx(ceiling)                 # ceiling = robust pct
    assert hi < peak - 25.0                             # NOT pinned to the peak
    assert -40.0 <= hi <= 0.0                           # sits in the bulk band
    assert lo == pytest.approx(hi - _AUTO_SPAN_DB)      # fixed span preserved
    # Old (buggy) behaviour would have put hi == peak (~+30 dB); guard it.
    assert hi != pytest.approx(peak)
    c.deleteLater()


def test_plot_result_db_manual_does_not_bake_color_range_into_matrix(qapp):
    """Regression (2026-06-21): manual color scale must be DISPLAY-only.

    Computing with a manual [z_floor, z_ceiling] must NOT clip the stored
    display matrix to that window.  Clipping destroyed every value outside
    the window, so a later colorbar drag (display-only) could not recover the
    detail and the user was forced to recompute inside the right range — the
    "set [27,67] → all black; drag to [-33,6.72] → all red; recompute → image"
    report.  The matrix must stay full-range; only the display LEVELS carry
    [z_floor, z_ceiling].
    """
    rng = np.random.default_rng(3)
    bulk_db = rng.uniform(-47.0, 6.0, (60, 40))   # data lives in [-47, 6]
    amp = 10.0 ** (bulk_db / 20.0)
    r = SpectrogramResult(
        times=np.arange(40, dtype=float),
        frequencies=np.linspace(0.0, 3000.0, 60),
        amplitude=amp,
        params=SpectrogramParams(fs=129500.0, nfft=8192),
        channel_name='L', metadata={'frames': 40},
    )

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)
    # Compute with a window ABOVE all the data ([27, 67] vs data in [-47, 6]).
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo',
                  z_auto=False, z_floor=27.0, z_ceiling=67.0)

    md = c._matrix_disp
    # Stored matrix must remain the FULL dB data, NOT flattened to the floor.
    assert float(np.nanstd(md)) > 1.0, "matrix was baked/flattened by the clip"
    assert float(np.nanmin(md)) < 0.0          # real lows preserved
    assert float(np.nanmax(md)) <= 6.5         # not pushed up into the window
    # Display levels still carry the manual window.
    lo, hi = c._img.getLevels()
    assert (lo, hi) == pytest.approx((27.0, 67.0))

    # A colorbar drag to a sane window recovers detail WITHOUT a recompute.
    c._img.setLevels((-33.28, 6.72))
    assert float(np.nanstd(c._matrix_disp)) > 1.0
    c.deleteLater()


def test_left_click_selects_frame_when_remark_off(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True,
    )
    # Click near the frame at ~1.11s. Avoid the exact midpoint between two
    # frames (1.0s), where 1px layout/frame changes can legitimately flip the
    # nearest-bin tie.
    click_t = float(r.times[5])
    sp = c._plot.vb.mapViewToScene(QPointF(click_t, 250.0))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))
    xs, ys = c._slice_curve.getData()
    expected_idx = int(np.argmin(np.abs(r.times - click_t)))
    np.testing.assert_allclose(ys, c._matrix_disp[:, expected_idx], rtol=1e-6)
    # Marker follows the selected time.
    assert c._slice_marker.value() == pytest.approx(float(r.times[expected_idx]))
    assert c._slice_marker.isVisible()
    c.hide()
    c.deleteLater()


def test_left_click_adds_remark_when_remark_on_not_slice(qapp):
    # When remark mode is on, left-click annotates (does NOT select a
    # frame); the two left-click behaviors are mutually exclusive.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    # plot_result selected frame 0; record its slice for comparison.
    _, ys0 = c._slice_curve.getData()
    c.set_remark_enabled(True)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))
    assert len(c._remarks) == 1  # annotated, not frame-selected
    _, ys1 = c._slice_curve.getData()
    np.testing.assert_allclose(ys1, ys0)  # slice unchanged
    c.hide()
    c.deleteLater()


def test_heatmap_hover_does_not_emit_xyz_readout(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_hover(sp)
    assert received == ['']
    c.hide()
    c.deleteLater()


def test_full_reset_clears_slice_state(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    assert c._slice_marker.isVisible()  # precondition
    c.full_reset()
    assert c._result is None
    assert c._db_cache is None
    assert not c._slice_marker.isVisible()
    xs, ys = c._slice_curve.getData()
    # cleared curve has no data
    assert xs is None or len(xs) == 0
    # slice widgets survive the reset (row not orphaned)
    assert c._slice_curve is not None and c._slice_plot is not None
    c.deleteLater()


def test_select_time_index_noop_without_slice(qapp):
    # Order mode (with_slice=False): select_time_index must be inert and
    # never build a slice row or marker.
    c = PgHeatmapCanvas(with_slice=False)
    c.select_time_index(2)  # no result, no slice → silent no-op
    assert c._slice_curve is None
    assert c._slice_plot is None
    assert c._slice_marker is None
    c.deleteLater()


def test_remark_point_db_mode_labels_value_db_not_channel_unit(qapp):
    # dB mode: _matrix_disp holds dB numbers, so the annotation label MUST label the
    # value 'dB' — labeling it the channel unit 'g' is a unit error. Parity
    # with SpectrogramCanvas._on_motion (canvases.py:2028).
    from mf4_analyzer.ui.pg_canvas.remarks import format_remark_label

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()  # unit='g'
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    point = c._remark_point_at(1.0, 250.0)
    assert point is not None
    msg = format_remark_label(point)
    assert 'Z=' in msg and ' dB' in msg, (
        f"dB-mode annotation must label Z in dB, got {msg!r}"
    )
    # The channel unit 'g' must NOT trail the value in dB mode. Guard a
    # naive substring 'g' (which appears in any value via %.4g) by anchoring
    # on the trailing token only.
    assert ' g' not in msg, f"dB-mode annotation wrongly labeled 'g': {msg!r}"
    c.hide()
    c.deleteLater()


def test_remark_point_linear_mode_labels_value_channel_unit(qapp):
    # Linear mode: value is in the channel unit, so the annotation trails the
    # result unit ('g'), NOT 'dB'.
    from mf4_analyzer.ui.pg_canvas.remarks import format_remark_label

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()  # unit='g'
    c.plot_result(r, amplitude_mode='amplitude', cmap='turbo', z_auto=True)
    point = c._remark_point_at(1.0, 250.0)
    assert point is not None
    msg = format_remark_label(point)
    assert 'Z=' in msg and ' g' in msg, (
        f"linear-mode annotation must label Z with channel unit, got {msg!r}"
    )
    assert ' dB' not in msg, f"linear-mode annotation must not say 'dB': {msg!r}"
    c.hide()
    c.deleteLater()


def test_order_style_heatmap_hover_clears_without_xyz_readout(qapp):
    c = PgHeatmapCanvas()
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c._amplitude_mode = 'amplitude_db'
    matrix = np.arange(12, dtype=float).reshape(3, 4)
    c.plot_or_update_heatmap(
        matrix=matrix,
        x_extent=(0.0, 3.0),
        y_extent=(0.0, 2.0),
        x_label='Time (s)',
        y_label='Order',
        x_coords=np.array([0.0, 1.0, 2.0, 3.0]),
        y_coords=np.array([0.0, 1.0, 2.0]),
        amplitude_mode='amplitude',
        z_auto=True,
    )
    assert c._result is None
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.1, 1.2))
    c._on_scene_hover(sp)

    assert received == ['']
    c.hide()
    c.deleteLater()


def test_remark_point_and_value_at_read_same_value_in_slice_mode(qapp):
    # Caliber unification (裁决 3): in with_slice mode the remark formatter and
    # _value_at must resolve the SAME cell value at the same
    # coordinate. Pick a boundary coordinate where floor-fraction and
    # argmin-nearest would otherwise disagree, so the test bites.
    from mf4_analyzer.ui.pg_canvas.remarks import format_remark_label

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    # Pick a frequency coordinate where the floor-fraction picker (extent
    # mapping) and the argmin-nearest picker (over result.frequencies)
    # DISAGREE, so a regression to a floor-fraction _value_at would make
    # this test fail. Search the bins for such a point and pin it.
    freqs = r.frequencies
    y0, y1 = float(freqs[0]), float(freqs[-1])
    rows = len(freqs)

    def _floor_row(yy):
        return min(int((yy - y0) / max(y1 - y0, 1e-12) * rows), rows - 1)

    x = float(r.times[3])
    y = None
    for k in range(1, rows - 1):
        cand = float(freqs[k]) + 0.45 * float(freqs[k + 1] - freqs[k])
        if _floor_row(cand) != int(np.argmin(np.abs(freqs - cand))):
            y = cand
            break
    assert y is not None, "no diverging coordinate found — test would not bite"
    assert _floor_row(y) != int(np.argmin(np.abs(freqs - y)))  # precondition
    # Annotation value: parse the trailing numeric token of the same formatter
    # used for persistent annotation labels.
    point = c._remark_point_at(x, y)
    assert point is not None
    remark_token = format_remark_label(point).split('Z=', 1)[-1].strip().split()[0]
    # Remark value: _value_at is the remark取值器; it must agree with the
    # annotation formatter.
    remark_val = c._value_at(x, y)
    # The annotation label formats the value via %.4g; _value_at reads the same
    # cell at full precision. Agreement means _value_at formats to the
    # identical %.4g token (same cell, not the same string rounding artifact).
    assert f"{remark_val:.4g}" == remark_token, (
        f"annotation token {remark_token!r} vs value {remark_val} disagree on the cell"
    )
    # And both must equal the argmin-nearest cell in the display matrix.
    t_idx = int(np.argmin(np.abs(r.times - x)))
    f_idx = int(np.argmin(np.abs(r.frequencies - y)))
    assert remark_val == pytest.approx(float(c._matrix_disp[f_idx, t_idx]))
    c.hide()
    c.deleteLater()


def test_value_at_keeps_floor_fraction_in_order_mode(qapp):
    # Order mode (with_slice=False, no _result): _value_at MUST keep the
    # floor-fraction mapping. The caliber unification is scoped to slice
    # mode only — changing Order's picker would regress the existing Order
    # remark tests and silently shift Order annotation values.
    c = PgHeatmapCanvas(with_slice=False)
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert c._result is None  # precondition: Order mode never sets _result
    # (8.0, 6.0) is a boundary point: floor-fraction → cell [row 3, col 4]
    # = 1.0; argmin-nearest would round to the peak cell (100.0). The Order
    # picker must stay on floor-fraction.
    assert c._value_at(8.0, 6.0) == pytest.approx(1.0)
    c.deleteLater()


def test_slice_y_label_switches_with_amplitude_mode(qapp):
    # M1: the slice subplot's left (amplitude) axis must be labeled, and the
    # label switches dB vs linear with amplitude_mode (mpl _plot_slice,
    # canvases.py:1878-1880).
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    assert c._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'
    c.plot_result(r, amplitude_mode='amplitude', cmap='turbo', z_auto=True)
    assert c._slice_plot.getAxis('left').labelText == 'Amplitude'
    c.deleteLater()


# ----------------------------------------------------------------------
# full/main export modes (FFT-vs-Time copy: full view vs main chart). M8.
# ----------------------------------------------------------------------
def test_grab_full_vs_main(qapp):
    # full = whole widget (heatmap + slice row); main = heatmap + colorbar
    # only (slice row cropped out). Parity with SpectrogramCanvas
    # grab_full_view / grab_main_chart (canvases.py:2053/2064).
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()  # realize the GraphicsLayout geometry
    c.plot_result(
        _spec_result(), amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    full = c.grab_full_view()
    main = c.grab_main_chart()
    assert not full.isNull() and not main.isNull()
    # main excludes the slice row → strictly shorter
    assert main.height() < full.height()
    c.hide()
    c.deleteLater()


def test_grab_main_chart_order_mode_no_slice_does_not_crash(qapp):
    # with_slice=False (Order map): no slice row exists, so grab_main_chart
    # must not crash and main ≈ full height (nothing to crop). The export
    # button is wired for both sections.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True, cmap='turbo',
    )
    full = c.grab_full_view()
    main = c.grab_main_chart()
    assert not full.isNull() and not main.isNull()
    # No slice row to crop → main spans essentially the whole height (allow
    # a small slack for the heatmap-vs-widget rect difference).
    assert main.height() >= full.height() * 0.5
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# Toolbar pan/box-zoom parity via axes_list shim (M-heatmap, parity with
# PgLineCanvas M11). PgHeatmapCanvas only got reset_view_to_data_extents
# at M6 (Home), so PgNavigationToolbar's pan/zoom buttons — which walk
# canvas.axes_list → ax.view_box and setMouseMode on each ViewBox — were
# silent no-ops on the order map AND the FFT-vs-Time map (mouseMode stuck
# at PanMode=3, box-zoom dead, _view_boxes() returned []).
# ----------------------------------------------------------------------
def test_axes_list_exposes_primary_viewbox_shim(qapp):
    # Both forms expose at least the main heatmap ViewBox via a shim with a
    # .view_box attribute (the contract PgNavigationToolbar._view_boxes /
    # _primary_view_box read).
    for with_slice in (False, True):
        c = PgHeatmapCanvas(with_slice=with_slice)
        assert hasattr(c, 'axes_list')
        assert len(c.axes_list) >= 1
        view_boxes = [getattr(ax, 'view_box', None) for ax in c.axes_list]
        assert c._plot.vb in view_boxes, (
            f"main heatmap vb missing from axes_list (with_slice={with_slice})"
        )
        c.deleteLater()


@pytest.mark.parametrize("with_slice", [False, True])
def test_toolbar_zoom_mode_flips_heatmap_to_rectmode(qapp, with_slice):
    # The exact production failure: toolbar.set_zoom_mode() walks axes_list
    # and must flip the main heatmap ViewBox into RectMode (box-select zoom).
    # Before the shim, _view_boxes() was empty so the mode never reached the
    # ViewBox — it stayed PanMode=3 and box-zoom was dead.
    c = PgHeatmapCanvas(with_slice=with_slice)
    c.resize(640, 480)
    if with_slice:
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db',
                      cmap='turbo', z_auto=True)
    else:
        c.plot_or_update_heatmap(
            matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
            amplitude_mode='amplitude', z_auto=True,
        )
    toolbar = PgNavigationToolbar(c)
    toolbar.set_zoom_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.RectMode
    toolbar.set_pan_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.PanMode
    toolbar.deleteLater()
    c.deleteLater()


def test_toolbar_view_boxes_nonempty_and_primary_resolves(qapp):
    # PgNavigationToolbar._view_boxes() must return a non-empty list and
    # _primary_view_box() a real ViewBox for BOTH forms — these feed
    # rebind_history_capture (back/forward) and _set_all_mouse_modes.
    for with_slice in (False, True):
        c = PgHeatmapCanvas(with_slice=with_slice)
        toolbar = PgNavigationToolbar(c)
        boxes = toolbar._view_boxes()
        assert boxes, f"_view_boxes() empty (with_slice={with_slice})"
        assert c._plot.vb in boxes
        primary = toolbar._primary_view_box()
        assert primary is c._plot.vb
        toolbar.deleteLater()
        c.deleteLater()


def test_toolbar_home_resets_to_exact_data_extents(qapp):
    # The M6 Home fix (reset_view_to_data_extents) must keep working after
    # the axes_list addition: zoom in, then Home restores the view. The image
    # rect spans EXACTLY the data extents, so Home must reset to those exact
    # extents (no visual padding) — a 1.5%/side margin would over-expand the
    # ViewBox past the image and expose the white background as an edge band.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)
    # Zoom into a sub-region, then Home.
    c._plot.setXRange(2.0, 4.0, padding=0)
    c._plot.setYRange(1.0, 3.0, padding=0)
    toolbar.home()
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    # Flush to the exact data extents — mirrors the initial render
    # (plot_or_update_heatmap setXRange/setYRange(padding=0)).
    assert x0 == pytest.approx(0.0)
    assert x1 == pytest.approx(10.0)
    assert y0 == pytest.approx(0.0)
    assert y1 == pytest.approx(8.0)
    toolbar.deleteLater()
    c.deleteLater()


@pytest.mark.parametrize("with_slice", [False, True])
def test_toolbar_home_keeps_heatmap_flush_to_extents(qapp, with_slice):
    """Order and FFT-vs-Time Home/查看全部 must restore the view flush to the
    image rect — no white margin band at the edges.

    Regression: reset_view_to_data_extents previously added a 1.5%/side
    visual margin, over-expanding the ViewBox past the image so the white
    ViewBox background showed as an edge band after Home (initial open was
    flush; only Home introduced the margin). Home must reproduce the flush
    initial render on BOTH sections.
    """
    c = PgHeatmapCanvas(with_slice=with_slice)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)

    c._plot.setXRange(2.0, 4.0, padding=0)
    c._plot.setYRange(1.0, 3.0, padding=0)
    toolbar.home()
    qapp.processEvents()

    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    # Exact extents (no padding) so the image meets the frame flush.
    assert x0 == pytest.approx(0.0)
    assert x1 == pytest.approx(10.0)
    assert y0 == pytest.approx(0.0)
    assert y1 == pytest.approx(8.0)

    toolbar.deleteLater()
    c.hide()
    c.deleteLater()


def test_toolbar_box_zoom_drag_actually_zooms(qapp):
    # End-to-end: with the toolbar in zoom mode, a programmatic box-zoom
    # gesture on the heatmap ViewBox must shrink the view to the dragged
    # rectangle (NOT a no-op). RectMode is the precondition for ViewBox to
    # interpret a left-drag as a zoom rectangle rather than a pan.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)
    toolbar.set_zoom_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.RectMode  # precondition
    # ViewBox.showAxRect is the call RectMode dragging ultimately makes;
    # exercising it through the RectMode-configured ViewBox proves the box
    # zoom path is live (the toolbar wired the mode that gates it).
    from PyQt5.QtCore import QRectF
    c._plot.vb.showAxRect(QRectF(2.0, 1.0, 3.0, 3.0))
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    # The view collapses to roughly the 3×3 box (showAxRect adds a small
    # suggestPadding, so assert it shrank and is centered on the box rather
    # than matching the exact corners).
    assert x1 - x0 < 6.0 and y1 - y0 < 6.0, "box zoom did not shrink the view"
    assert (x0 + x1) / 2 == pytest.approx(3.5, abs=0.5)  # box center x = 3.5
    assert (y0 + y1) / 2 == pytest.approx(2.5, abs=0.5)  # box center y = 2.5
    toolbar.deleteLater()
    c.hide()
    c.deleteLater()


def test_split_drag_finish_self_aligns_single_but_delegates_in_split(qapp, monkeypatch):
    """Single pane (standalone): drag-finish self-aligns the slice. Split mode
    (page-managed): drag-finish must NOT run single-pane align (it fights the
    page) but must still emit layout_geometry_changed so the page re-syncs."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(600, 480)
    c.show()
    qapp.processEvents()
    align = []
    geo = []
    monkeypatch.setattr(c, '_align_slice_to_main', lambda: align.append(1))
    c.layout_geometry_changed.connect(lambda: geo.append(1))

    # Measure the delta around each drag-finish (apply/reset themselves also
    # touch align/geo, so cumulative counts would be noisy).
    # Single-pane / standalone (default): drag-finish self-aligns + notifies.
    assert c._split_aligned is False
    a0, g0 = len(align), len(geo)
    c._on_split_drag_finished()
    assert len(align) == a0 + 1     # self-aligned
    assert len(geo) == g0 + 1       # notified the page

    # Page took over split alignment → flag True; drag-finish skips self-align,
    # still notifies the page.
    c.apply_split_layout_alignment(left_axis_width=40.0)
    assert c._split_aligned is True
    a0, g0 = len(align), len(geo)
    c._on_split_drag_finished()
    assert len(align) == a0         # did NOT self-align (page owns it)
    assert len(geo) == g0 + 1       # still notified

    # Page reset to single → flag False again; self-align resumes.
    c.reset_split_layout_alignment()
    assert c._split_aligned is False
    a0 = len(align)
    c._on_split_drag_finished()
    assert len(align) == a0 + 1     # self-align resumes
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX 2 — empty-state heatmap axes are non-negative (time/freq/order never < 0).
# ----------------------------------------------------------------------
def test_empty_state_main_axes_are_non_negative_on_construct(qapp):
    """A fresh PgHeatmapCanvas must NOT inherit pyqtgraph's default symmetric
    [-0.5, 0.5] view: time/frequency/order are all non-negative, so the blank
    map's X and Y view minima must be >= 0."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _EMPTY_X_RANGE, _EMPTY_Y_RANGE)
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    assert x0 >= 0.0, f"empty X min must be >= 0, got {x0}"
    assert y0 >= 0.0, f"empty Y min must be >= 0, got {y0}"
    # The fixed module-level defaults are honored exactly (padding=0).
    assert (x0, x1) == pytest.approx(_EMPTY_X_RANGE)
    assert (y0, y1) == pytest.approx(_EMPTY_Y_RANGE)
    c.hide()
    c.deleteLater()


def test_empty_state_main_axes_are_non_negative_after_full_reset(qapp):
    """After plotting real data and then full_reset (file-close), the map must
    return to the SAME non-negative empty-state range — never leaving negative
    time/freq ticks behind."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _EMPTY_X_RANGE, _EMPTY_Y_RANGE)
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)
    qapp.processEvents()
    c.full_reset()
    qapp.processEvents()
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    assert x0 >= 0.0, f"post-reset X min must be >= 0, got {x0}"
    assert y0 >= 0.0, f"post-reset Y min must be >= 0, got {y0}"
    assert (x0, x1) == pytest.approx(_EMPTY_X_RANGE)
    assert (y0, y1) == pytest.approx(_EMPTY_Y_RANGE)
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX 3 — 'y' slice direction aligns its time X range to the map exactly so the
# top/bottom gridlines line up by time. The default 'x' direction is untouched.
# ----------------------------------------------------------------------
def test_y_slice_x_range_matches_map_x_range(qapp):
    """In 'y' slice mode (fixed freq/order → amp-vs-time), the slice plot's X
    view must equal the map's X view so their time gridlines align vertically."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)
    qapp.processEvents()
    c.set_slice_direction('y')
    qapp.processEvents()
    (mx0, mx1), _ = c._plot.vb.viewRange()
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    # Both are the displayed heatmap time extent, not just first/last centers.
    assert sx0 == pytest.approx(mx0, abs=1e-6)
    assert sx1 == pytest.approx(mx1, abs=1e-6)
    # The slice bottom axis is the time axis in this direction.
    assert c._slice_plot.getAxis('bottom').labelText == 'Time (s)'
    c.hide()
    c.deleteLater()


def test_x_slice_uses_visible_frequency_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', z_auto=True,
        y_auto=False, y_min=100.0, y_max=300.0,
    )
    qapp.processEvents()

    assert c._slice_dir == 'x'
    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 100.0 - 1e-6
    assert np.nanmax(xs) <= 300.0 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(100.0, abs=1e-6)
    assert sx1 == pytest.approx(300.0, abs=1e-6)
    c.hide()
    c.deleteLater()


def test_y_slice_uses_visible_time_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', z_auto=True,
        x_auto=False, x_min=0.5, x_max=1.5,
    )
    c.set_slice_direction('y')
    qapp.processEvents()

    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 0.5 - 1e-6
    assert np.nanmax(xs) <= 1.5 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(0.5, abs=1e-6)
    assert sx1 == pytest.approx(1.5, abs=1e-6)
    c.hide()
    c.deleteLater()


def test_order_x_slice_uses_visible_order_range(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    times = np.linspace(0.0, 4.0, 5)
    orders = np.array([0.0, 1.0, 2.0, 5.0, 10.0])
    matrix = np.arange(
        orders.size * times.size, dtype=float
    ).reshape(orders.size, times.size)
    c.plot_or_update_heatmap(
        matrix, (0.0, 4.0), (0.0, 10.0),
        x_label='Time (s)', y_label='Order',
        x_coords=times, y_coords=orders,
        y_auto=False, y_min=1.0, y_max=5.0,
    )
    c._seed_slice()
    qapp.processEvents()

    assert c._slice_dir == 'x'
    xs, _ = c._slice_curve.getData()
    assert np.nanmin(xs) >= 1.0 - 1e-6
    assert np.nanmax(xs) <= 5.0 + 1e-6
    (sx0, sx1), _ = c._slice_plot.vb.viewRange()
    assert sx0 == pytest.approx(1.0, abs=1e-6)
    assert sx1 == pytest.approx(5.0, abs=1e-6)
    c.hide()
    c.deleteLater()


def test_x_slice_direction_unchanged_by_fix3(qapp):
    """The default 'x' direction (fixed time → amp vs frequency) must keep its
    own visible frequency X axis. Switching x→y→x restores the x slice domain
    and keeps the freq-labelled bottom axis."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)
    qapp.processEvents()
    # Default 'x' direction: amp vs frequency (64 bins), freq-labelled axis.
    assert c._slice_dir == 'x'
    assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
    xs_x, _ = c._slice_curve.getData()
    assert len(xs_x) == 64
    # x -> y -> x must restore the 'x' behaviour exactly.
    c.set_slice_direction('y')
    qapp.processEvents()
    c.set_slice_direction('x')
    qapp.processEvents()
    assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
    xs_xx, _ = c._slice_curve.getData()
    assert len(xs_xx) == 64
    np.testing.assert_allclose(xs_x, xs_xx)
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX 4 — showGrid(x,y) lights ALL four built-in axes; top/right are plain
# AxisItems that re-draw the boundary line the left/bottom axes suppress, so
# during zoom sub-pixel offsets double every grid line. top/right grid must be
# disabled on BOTH plots (mirrors line_canvas.py:145-146).
# ----------------------------------------------------------------------
def test_top_and_right_grid_disabled_on_both_plots(qapp):
    """``ax.grid is False`` on the top+right axes of the map AND the slice — the
    only axes carrying grid are the boundary-suppressing left+bottom. Asserted
    on ``ax.grid`` (per the cited lesson: driving the real generateDrawSpecs with
    QPainter(QPicture()) access-violates)."""
    c = PgHeatmapCanvas(with_slice=True)
    for plot in (c._plot, c._slice_plot):
        assert plot.getAxis('top').grid is False
        assert plot.getAxis('right').grid is False
        # The boundary-suppressing axes DO carry the grid.
        assert plot.getAxis('left').grid is not False
        assert plot.getAxis('bottom').grid is not False
    c.deleteLater()


def test_left_and_right_grid_line_counts_match_no_extra_boundary(qapp):
    """The extra/duplicate gridlines came from the right (plain) AxisItem
    re-drawing the boundary line the left (_BoundaryGridAxisItem) suppresses.
    With the right grid disabled, the right axis emits ZERO horizontal grid
    lines while the left emits its (boundary-filtered) interior set — so the
    right axis can no longer add a doubled boundary line.

    Tested via ax.grid state (cheap + stable), NOT by driving the real
    generateDrawSpecs through a QPainter(QPicture()) which access-violates in
    the text boundingRect path (cited lesson)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)
    qapp.processEvents()
    for plot in (c._plot, c._slice_plot):
        # right grid OFF means it contributes no gridlines at all; left grid
        # ON (and boundary-filtered) is the single source of horizontal lines.
        assert plot.getAxis('right').grid is False
        assert plot.getAxis('left').grid is not False
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX A — first-show left-axis re-alignment. On first entry the eager
# showEvent align runs before the GraphicsLayout geometry is realized, so the
# two stacked left axes settle to DIFFERENT natural widths with nothing
# re-unifying them. showEvent now schedules a deferred re-alignment
# (QTimer.singleShot(0)) that runs after the first paint. Offscreen the two
# widths happen to measure EQUAL (geometry not fully realized headless), so a
# pure width-equality assertion is weak — SPY the show path instead.
# ----------------------------------------------------------------------
def test_first_show_schedules_deferred_left_axis_realign(qapp):
    """A single-pane (page-less) canvas must self-re-align after the first
    paint: showEvent schedules QTimer.singleShot(0, _deferred_first_show_align),
    and processing events fires it. We wrap reset_split_layout_alignment to
    count calls and assert the deferred show path triggered a re-alignment;
    we also assert no exception and the two left axes end equal-width."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    calls = {'n': 0}
    orig = c.reset_split_layout_alignment

    def _counting_reset():
        calls['n'] += 1
        return orig()

    c.reset_split_layout_alignment = _counting_reset
    # Plot a result so the left axes carry real (differently wide) tick labels.
    c.plot_result(_spec_result(), amplitude_mode='amplitude_db', z_auto=True)
    before = calls['n']
    c.show()
    # singleShot(0) is queued on show; draining the event loop fires it.
    for _ in range(5):
        qapp.processEvents()
    assert calls['n'] > before, (
        "first-show did not schedule/run a deferred left-axis re-alignment"
    )
    # The two stacked left axes end equal-width (single shared left edge).
    main_w = float(c._plot.getAxis('left').width())
    slice_w = float(c._slice_plot.getAxis('left').width())
    assert main_w == pytest.approx(slice_w, abs=0.5), (
        f"stacked left axes not unified after first show: "
        f"main={main_w} slice={slice_w}"
    )
    c.hide()
    c.deleteLater()


def test_first_show_deferred_align_is_split_pane_safe(qapp):
    """The deferred first-show handler must NOT self-reset alignment when the
    page already drives split alignment (_split_aligned True) — that would set
    _split_aligned False and fight the page. It must still emit
    layout_geometry_changed so the page re-syncs. And the emit chain must
    terminate (no infinite layout_geometry_changed loop)."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    # Simulate a page having taken over split alignment.
    c.apply_split_layout_alignment(left_axis_width=40.0)
    assert c._split_aligned is True
    reset_calls = {'n': 0}
    orig = c.reset_split_layout_alignment

    def _counting_reset():
        reset_calls['n'] += 1
        return orig()

    c.reset_split_layout_alignment = _counting_reset
    geo = {'n': 0}
    c.layout_geometry_changed.connect(lambda: geo.__setitem__('n', geo['n'] + 1))
    c._deferred_first_show_align()
    # Page-managed: must NOT self-reset (would flip _split_aligned False).
    assert reset_calls['n'] == 0, "deferred align fought the page's split alignment"
    assert c._split_aligned is True
    # Must still notify the page to re-sync.
    assert geo['n'] >= 1, "deferred align did not notify the page"
    # Emit chain terminates: a bounded number of emits (no runaway loop).
    assert geo['n'] < 50, "layout_geometry_changed appears to loop"
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX B — right-click "查看全部" / toolbar Home on the EMPTY map must restore
# the non-negative empty default, not pg's autoRange() origin-recenter (which
# went negative: X=[-15,15], Y=[-500,500]).
# ----------------------------------------------------------------------
def test_view_all_on_empty_map_keeps_non_negative_range(qapp):
    """reset_view_to_data_extents() with no data must apply the non-negative
    empty default (NOT pg autoRange, which recenters on the origin → negative
    time/freq/order). Both the toolbar Home and the menu "查看全部" route here."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _EMPTY_X_RANGE, _EMPTY_Y_RANGE)
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    assert not c.has_result()  # precondition: empty map
    c.reset_view_to_data_extents()
    qapp.processEvents()
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    assert x0 >= 0.0, f"empty View-All X min went negative: {x0}"
    assert y0 >= 0.0, f"empty View-All Y min went negative: {y0}"
    assert (x0, x1) == pytest.approx(_EMPTY_X_RANGE)
    assert (y0, y1) == pytest.approx(_EMPTY_Y_RANGE)
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# FIX C — the slice X-range lock must not leak from 'y' (time-pin) into 'x'
# (freq spectrum). FIX3's setXRange in the 'y' branch DISABLES the slice's X
# auto-range; the 'x' branch must re-enable it so the spectrum re-fits the
# frequency/order extent instead of staying squished in the time extent.
# ----------------------------------------------------------------------
def test_x_slice_reranges_to_freq_after_y_slice(qapp):
    """y→x: the 'x' slice (amp vs frequency) must re-range its X to the FREQUENCY
    visible range, NOT stay pinned to the time extent the prior 'y' slice set."""
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()  # times 0..2 over 10 frames; freqs 0..500 over 64 bins
    c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True)
    qapp.processEvents()
    time_lo, time_hi = c._extents[0], c._extents[1]
    freq_lo, freq_hi = float(r.frequencies[0]), float(r.frequencies[-1])

    # Default 'x' = amp vs frequency; X pinned to the visible frequency extent.
    assert c._slice_dir == 'x'
    assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
    (x0_x, x1_x), _ = c._slice_plot.vb.viewRange()
    assert x0_x == pytest.approx(freq_lo, abs=1e-6)
    assert x1_x == pytest.approx(freq_hi, abs=1e-6)
    # And NOT the (much narrower) time extent.
    assert x1_x > time_hi * 2

    # 'y' = amp vs time; X pinned to the TIME extent (padding=0).
    c.set_slice_direction('y')
    qapp.processEvents()
    assert c._slice_plot.getAxis('bottom').labelText == 'Time (s)'
    (sy0, sy1), _ = c._slice_plot.vb.viewRange()
    assert sy0 == pytest.approx(time_lo, abs=1e-6)
    assert sy1 == pytest.approx(time_hi, abs=1e-6)

    # Back to 'x': X must re-range to the FREQUENCY extent, NOT stay at [0,2].
    c.set_slice_direction('x')
    qapp.processEvents()
    assert c._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
    (x0_b, x1_b), _ = c._slice_plot.vb.viewRange()
    # The bug left this stuck at the time extent (~[0,2]); the fix re-fits the
    # visible frequency/order coordinate domain.
    assert x0_b == pytest.approx(freq_lo, abs=1e-6)
    assert x1_b == pytest.approx(freq_hi, abs=1e-6), (
        f"x-after-y did not re-range to freq extent: X=({x0_b},{x1_b}), "
        f"time_hi={time_hi}, freq_hi={freq_hi}"
    )
    assert x1_b > time_hi * 2, (
        f"x-after-y slice X stuck at time extent: ({x0_b},{x1_b})"
    )
    c.hide()
    c.deleteLater()


# ---- Task 6: boundary tests (Home / View All does not emit levels_changed) ----

def test_heatmap_view_all_does_not_emit_levels_changed(qapp):
    """reset_view_to_data_extents must not emit levels_changed."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    c = PgHeatmapCanvas()
    seen = []
    c.levels_changed.connect(lambda *_args: seen.append(True))
    c.plot_or_update_heatmap(
        np.arange(9, dtype=float).reshape(3, 3),
        x_extent=(0.0, 3.0),
        y_extent=(0.0, 3.0),
        z_auto=False,
        z_floor=0.0,
        z_ceiling=8.0,
    )

    c.reset_view_to_data_extents()

    assert seen == []


# -----------------------------------------------------------------------
# Invariant tests: FFT-vs-Time auto/manual color-scale consistency
# (TDD: these MUST fail before the fix, and pass after)
# -----------------------------------------------------------------------

def _real_spec_result():
    """Construct a SpectrogramResult via the actual compute path so the
    absolute dB matrix has a peak that is NOT 0 dB (typical audio signal).
    Peak will be around -34 dB for the 0.02 Pa sine used here."""
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

    fs = 2000.0
    rng = np.random.default_rng(0)
    t = np.arange(0, 2.0, 1.0 / fs)
    sig = 0.02 * np.sin(2 * np.pi * 200 * t) + 0.002 * rng.standard_normal(t.size)

    params = SpectrogramParams(fs=fs, nfft=256, window='hann', overlap=0.75,
                               remove_mean=True, weighting='None')
    return SpectrogramAnalyzer.compute(sig, t, params, channel_name='ch', unit='Pa')


def test_plot_result_auto_manual_no_jump(qapp):
    """Invariant 1 (no jump): auto-mode vmin/vmax must equal what manual
    mode produces after the inspector spin values have been written back to
    the values the canvas computed automatically.

    Before the fix: z_auto=True gives [peak-40, peak] ≈ (-74.65, -34.65),
    while z_auto=False with the same spin values (-40/0) gives (-40, 0) —
    a 34.65 dB shift.  After the fix both must agree within 0.5 dB.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _AUTO_SPAN_DB

    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    result = _real_spec_result()

    # Step 1: render in auto mode.
    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=True, z_floor=-40.0, z_ceiling=0.0)
    auto_lo, auto_hi = (float(x) for x in c._img.getLevels())

    # Step 2: render in manual mode — BUT the spin values are already the
    # values that the auto render wrote back (simulating the write-back).
    # After the fix, _last_auto_levels must be set and equal (auto_lo, auto_hi).
    written_lo = float(c._last_auto_levels[0])
    written_hi = float(c._last_auto_levels[1])
    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=False, z_floor=written_lo, z_ceiling=written_hi)
    man_lo, man_hi = (float(x) for x in c._img.getLevels())

    assert auto_lo == pytest.approx(man_lo, abs=0.5), (
        f"auto→manual jump on lo: auto={auto_lo:.3f} man={man_lo:.3f}")
    assert auto_hi == pytest.approx(man_hi, abs=0.5), (
        f"auto→manual jump on hi: auto={auto_hi:.3f} man={man_hi:.3f}")
    c.deleteLater()


def test_plot_result_manual_reproducible(qapp):
    """Invariant 2 (reproducible): manual mode with the same z_floor/z_ceiling
    called twice must produce bit-identical levels."""
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    result = _real_spec_result()

    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=False, z_floor=-50.0, z_ceiling=-10.0)
    lo1, hi1 = (float(x) for x in c._img.getLevels())

    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=False, z_floor=-50.0, z_ceiling=-10.0)
    lo2, hi2 = (float(x) for x in c._img.getLevels())

    assert lo1 == lo2 and hi1 == hi2, (
        f"manual levels not reproducible: ({lo1},{hi1}) vs ({lo2},{hi2})")
    c.deleteLater()


def test_plot_result_auto_decoupled_from_spin_values(qapp):
    """Invariant 3 (decoupled): in auto mode the displayed window's SPAN
    and upper edge must be data-driven, NOT affected by z_floor/z_ceiling.

    Before the fix, z_auto=True used z_floor/z_ceiling as peak offsets,
    so different spin values produced different windows.  After the fix,
    [ceiling - AUTO_SPAN_DB, ceiling] is always used regardless of spin
    values, where ceiling is the robust _AUTO_CEILING_PCT percentile.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _AUTO_CEILING_PCT, _AUTO_SPAN_DB, _robust_db_ceiling)

    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)
    result = _real_spec_result()

    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=True, z_floor=-40.0, z_ceiling=0.0)
    lo_a, hi_a = (float(x) for x in c._img.getLevels())

    # Different spin values — must produce the SAME window.
    c.plot_result(result, amplitude_mode='amplitude_db',
                  z_auto=True, z_floor=-80.0, z_ceiling=-10.0)
    lo_b, hi_b = (float(x) for x in c._img.getLevels())

    assert lo_a == pytest.approx(lo_b, abs=0.5), (
        f"auto window lo changed with spin values: {lo_a:.3f} vs {lo_b:.3f}")
    assert hi_a == pytest.approx(hi_b, abs=0.5), (
        f"auto window hi changed with spin values: {hi_a:.3f} vs {hi_b:.3f}")

    # Also verify the window is [ceiling - AUTO_SPAN_DB, ceiling] where
    # ceiling is the robust percentile (NOT np.nanmax).
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
    m_db = SpectrogramAnalyzer.amplitude_to_db(result.amplitude, 1.0)
    expected_hi = _robust_db_ceiling(m_db, _AUTO_CEILING_PCT)
    expected_lo = expected_hi - _AUTO_SPAN_DB
    assert hi_a == pytest.approx(expected_hi, abs=0.5), (
        f"auto hi should be robust ceiling={expected_hi:.3f}, got {hi_a:.3f}")
    assert lo_a == pytest.approx(expected_lo, abs=0.5), (
        f"auto lo should be ceiling-SPAN={expected_lo:.3f}, got {lo_a:.3f}")
    c.deleteLater()


# ---------------------------------------------------------------------------
# Task-2 invariant-guard tests (structural measure B)
# ---------------------------------------------------------------------------

def test_plot_or_update_heatmap_rejects_amplitude_db_mode(canvas):
    """Invariant: amplitude_db mode has been removed from plot_or_update_heatmap.

    All callers pre-convert to dB and pass amplitude_mode='amplitude'.
    Passing 'amplitude_db' must raise ValueError so dead-branch regressions are
    caught immediately at the call site.

    TDD: RED before dead branch is deleted; GREEN after.
    """
    with pytest.raises(ValueError, match="amplitude_db"):
        canvas.plot_or_update_heatmap(
            matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
            amplitude_mode='amplitude_db',
        )


def test_plot_result_matrix_invariant_across_window_rerenders(qapp):
    """Invariant: _matrix_disp is byte-identical across two plot_result calls
    with different z_floor/z_ceiling windows (manual mode, same result object).

    The display LEVELS must differ; only the image colour mapping changes.
    If the dead amplitude_db branch's np.clip were re-introduced, the matrix
    would differ between calls — this test catches the regression.

    TDD: currently GREEN (plot_result already doesn't clip); remains a
    regression guard after the dead branch deletion.
    """
    rng = np.random.default_rng(42)
    amp = rng.uniform(1e-4, 1.0, (32, 20)).astype(np.float32)
    r = SpectrogramResult(
        times=np.linspace(0.0, 2.0, 20),
        frequencies=np.linspace(0.0, 500.0, 32),
        amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=64),
        channel_name='inv_test', metadata={'frames': 20},
    )

    c = PgHeatmapCanvas(with_slice=True)
    c.resize(320, 240)

    # First render: a narrow high window (will show mostly dark)
    c.plot_result(r, amplitude_mode='amplitude_db',
                  z_auto=False, z_floor=-10.0, z_ceiling=0.0)
    matrix_first = c._matrix_disp.copy()
    levels_first = c._img.getLevels()

    # Second render: a wide low window (will show different colours)
    c.plot_result(r, amplitude_mode='amplitude_db',
                  z_auto=False, z_floor=-80.0, z_ceiling=-20.0)
    matrix_second = c._matrix_disp.copy()
    levels_second = c._img.getLevels()

    # The STORED matrix must be byte-identical: only the display levels differ.
    assert np.array_equal(matrix_first, matrix_second), (
        "plot_result baked the color window into _matrix_disp: "
        f"first_min={matrix_first.min():.2f} second_min={matrix_second.min():.2f}"
    )
    # Sanity: the levels MUST differ (otherwise the test is trivial).
    # getLevels() returns a tuple-like; compare element-wise.
    lf0, lf1 = float(levels_first[0]), float(levels_first[1])
    ls0, ls1 = float(levels_second[0]), float(levels_second[1])
    assert (lf0, lf1) != (ls0, ls1), (
        "levels should differ between the two manual windows"
    )

    c.deleteLater()


def test_heatmap_context_menu_custom_slot_item_availability(canvas, monkeypatch):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QToolButton, QWidget
    settings = QSettings("MF4AnalyzerTest", "HeatmapCustomSlot")
    settings.clear()
    canvas.register_copy_image_handler(lambda: None)
    menu = _open_context_menu(canvas._plot.vb, monkeypatch)
    panel = _inline_panel(menu)
    custom = panel.findChild(QWidget, "pgContextCustomActionButton")
    custom.findChild(QToolButton, "pgContextCustomActionCaret").click()
    # list host parents to the panel after expand; query items via the panel.
    # copy usable (handler injected); export disabled (bare canvas has no
    # mouse-mode controller, so controller-backed actions resolve to None).
    assert panel.findChild(QToolButton, "pgContextActionItem_copy_image").isEnabled()
    assert not panel.findChild(QToolButton, "pgContextActionItem_export").isEnabled()
    settings.clear()
