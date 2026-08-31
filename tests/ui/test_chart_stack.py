from pathlib import Path
import logging
import re
from types import SimpleNamespace

import numpy as np
import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QSizePolicy

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP


def _cursor_settings(tmp_path, name="cursor-stack.ini"):
    from PyQt5.QtCore import QSettings

    settings = QSettings(str(tmp_path / name), QSettings.IniFormat)
    settings.clear()
    return settings


def test_apply_mdi_icons_sets_navactive_property_on_active_button(qtbot):
    from PyQt5.QtWidgets import QToolBar, QToolButton
    from mf4_analyzer.ui.chart_stack import _apply_mdi_icons, _MDI_NAV_ICONS

    assert "pan" in _MDI_NAV_ICONS and "zoom" in _MDI_NAV_ICONS
    toolbar = QToolBar()
    qtbot.addWidget(toolbar)
    pan = toolbar.addAction("Pan")
    pan.setData("pan")
    zoom = toolbar.addAction("Zoom")
    zoom.setData("zoom")

    _apply_mdi_icons(toolbar, active_key="pan")
    pan_btn = toolbar.widgetForAction(pan)
    zoom_btn = toolbar.widgetForAction(zoom)

    assert isinstance(pan_btn, QToolButton)
    assert pan_btn.property("navActive") is True
    assert zoom_btn.property("navActive") is False

    _apply_mdi_icons(toolbar, active_key="zoom")
    assert pan_btn.property("navActive") is False
    assert zoom_btn.property("navActive") is True


class _StubCanvasForToolbar:
    axes_list = []
    _overlay_mode = False
    _x_master_handle = None

    def register_replot_callback(self, *_args):
        pass


def test_set_mouse_mode_broadcast_sets_self_and_peers(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import PgNavigationToolbar

    t_main = PgNavigationToolbar(_StubCanvasForToolbar())
    t_peer = PgNavigationToolbar(_StubCanvasForToolbar())
    qtbot.addWidget(t_main)
    qtbot.addWidget(t_peer)
    t_main._peer_toolbars_provider = lambda: [t_peer]

    t_main.set_mouse_mode_broadcast("zoom")
    assert t_main.mode == "zoom"
    assert t_peer.mode == "zoom"

    t_main.set_mouse_mode_broadcast("pan")
    assert t_main.mode == "pan"
    assert t_peer.mode == "pan"


def test_mouse_mode_broadcast_uses_non_broadcast_peer_setter(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import PgNavigationToolbar

    t_main = PgNavigationToolbar(_StubCanvasForToolbar())
    t_peer = PgNavigationToolbar(_StubCanvasForToolbar())
    qtbot.addWidget(t_main)
    qtbot.addWidget(t_peer)
    t_main._peer_toolbars_provider = lambda: [t_peer]
    t_peer._peer_toolbars_provider = lambda: [t_main]

    def _forbidden(_mode):
        raise AssertionError("peer broadcast setter must not be called")

    t_peer.set_mouse_mode_broadcast = _forbidden

    t_main.set_mouse_mode_broadcast("zoom")

    assert t_main.mode == "zoom"
    assert t_peer.mode == "zoom"


def test_shared_toolbar_highlight_refreshes_on_mouse_mode_signal(qapp, qtbot):
    """mouse_mode_changed stays wired to the shared-nav highlight refresh.

    Task16 connects the bound method directly (no self-capturing lambda).
    Drive the production setter so ``_sync_shared_nav_highlight`` actually
    updates toolbar ``navActive`` — do not replace the slot with a spy.
    """
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)

    toolbar = cs._time_toolbar
    zoom_act = toolbar._actions_by_key["zoom"]
    pan_act = toolbar._actions_by_key["pan"]
    zoom_btn = toolbar.widgetForAction(zoom_act)
    pan_btn = toolbar.widgetForAction(pan_act)

    toolbar.set_pan_mode()
    qapp.processEvents()
    toolbar.set_zoom_mode()
    qapp.processEvents()

    assert zoom_btn.property("navActive") is True
    assert pan_btn.property("navActive") is False


def test_secondary_toolbar_broadcasts_mouse_mode_to_primary_in_split(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.enter_split()
    qapp.processEvents()

    secondary_toolbar = cs._secondary_card.toolbar

    secondary_toolbar.set_mouse_mode_broadcast("zoom")

    assert secondary_toolbar.mode == "zoom"
    assert cs._time_toolbar.mode == "zoom"


def test_chart_stack_has_three_canvases(qapp):
    cs = ChartStack()
    # Six stack pages: five analysis workspaces plus UltraViewPage as the
    # sheet host (not a live workspace mode).
    assert cs.count() == 6


def test_analysis_heatmap_sections_start_with_section_axis_labels(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    fft_time = cs.canvas_fft_time
    fft_time.setParent(None)
    qtbot.addWidget(fft_time)
    fft_time.show()
    qapp.processEvents()
    assert fft_time._plot.getAxis('bottom').labelText == 'Time (s)'
    assert fft_time._plot.getAxis('left').labelText == 'Frequency (Hz)'
    assert fft_time._slice_plot.getAxis('bottom').labelText == 'Frequency (Hz)'
    assert fft_time._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'

    order = cs.canvas_order
    order.setParent(None)
    qtbot.addWidget(order)
    order.show()
    qapp.processEvents()
    assert order._plot.getAxis('bottom').labelText == 'Time (s)'
    assert order._plot.getAxis('left').labelText == 'Order'
    assert order._slice_plot.getAxis('bottom').labelText == 'Time (s)'
    assert order._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'


def test_chart_stack_set_mode(qapp, caplog):
    cs = ChartStack()
    assert cs.stack.count() == 6
    cs.set_mode('fft')
    assert cs.current_mode() == 'fft'
    cs.set_mode('order')
    assert cs.current_mode() == 'order'
    cs.set_mode('frf')
    assert cs.current_mode() == 'frf'
    with caplog.at_level(logging.WARNING):
        cs.set_mode('ultraview')
    assert cs.current_mode() == 'frf'
    assert cs.stack.currentIndex() == 3
    assert any("ultraview" in rec.message.lower() for rec in caplog.records)
    cs.set_mode('not-a-mode')
    assert cs.current_mode() == 'time'
    cs.set_mode('time')
    assert cs.current_mode() == 'time'
    cs.set_annotation_enabled('ultraview', True)
    cs.mark_discovered('plot')


def test_chart_stack_registers_frf_page_manager_and_reset(qapp, qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    cs = ChartStack()
    qtbot.addWidget(cs)

    assert "frf" in cs.analysis_managers
    assert cs.page_for_mode["frf"] is cs.page_frf
    assert isinstance(cs.canvas_frf, PgFrfCanvas)
    assert cs._frf_card._chart_mode == "frf"

    cs.canvas_frf.set_state("error", "boom")
    cs.full_reset_all()
    assert cs.canvas_frf.state() == "empty"


def test_analysis_managers_share_the_product_view_cap(qapp, qtbot):
    from mf4_analyzer.ui.view_state import MAX_VIEWS, TIME_DOMAIN_MAX_VIEWS

    cs = ChartStack()
    qtbot.addWidget(cs)

    assert MAX_VIEWS == 12
    assert TIME_DOMAIN_MAX_VIEWS == 24
    assert set(cs.analysis_managers) == {"fft", "fft_time", "frf", "order"}
    for section, manager in cs.analysis_managers.items():
        assert manager.max_views == MAX_VIEWS, section


def test_frf_cursor_toolbar_reuses_the_off_single_dual_controls(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1000, 700)
    cs.show()
    cs.set_mode("frf")
    canvas = cs.canvas_frf
    canvas.set_result(
        SimpleNamespace(
            frequencies=np.array([1.0, 10.0, 100.0]),
            transfer=np.array([1 + 0j, 2 + 0j, 3 + 0j]),
            coherence=np.array([1.0, 0.95, 0.9]),
            effective=SimpleNamespace(fs=1000.0, df=1.0, segments=4),
            warnings=(),
        ),
        {"frequency_scale": "log"},
        {},
    )
    buttons = cs._frf_card._cursor_buttons

    assert buttons["off"].isChecked()
    assert not canvas.cursor_enabled()
    buttons["single"].click()
    assert buttons["single"].isChecked()
    assert canvas.cursor_mode() == "single"
    assert canvas.cursor_enabled()
    canvas.set_cursor_frequency(10.0)
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert "coherence=" in cs._pill.primary_text()

    buttons["dual"].click()
    qapp.processEvents()
    assert canvas.cursor_mode() == "dual"
    canvas.set_dual_cursor_frequencies(1.0, 100.0)
    assert cs._pill.isVisible()
    assert "Δf=" in cs._pill.primary_text()
    assert "background-color:#e8f1ff" in cs._pill.primary_text()
    assert "ΔY：Δ|H|=" in cs._pill._detail.text()
    assert cs._pill.has_detail()

    buttons["off"].click()
    qapp.processEvents()
    assert not canvas.cursor_enabled()
    assert all(not line.isVisible() for lines in (
        canvas._cursor_lines, canvas._cursor_a_lines, canvas._cursor_b_lines,
    ) for line in lines)
    assert not cs._pill.isVisible()


def test_fft_card_exposes_the_same_frequency_cursor_options(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1000, 700)
    cs.show()
    cs.set_mode("fft")
    card = cs._fft_card
    canvas = cs.canvas_fft
    canvas._entries = [{
        "freq": np.array([1.0, 10.0, 100.0]),
        "amp": np.array([2.0, 3.0, 4.0]),
        "label": "Acceleration",
    }]

    assert set(card._cursor_buttons) == {"off", "single", "dual"}
    assert card._cursor_buttons["off"].toolTip().endswith(
        f"({QKeySequence('Ctrl+3').toString(QKeySequence.NativeText)})"
    )
    assert card._cursor_buttons["single"].toolTip().endswith(
        f"({QKeySequence('Ctrl+4').toString(QKeySequence.NativeText)})"
    )
    assert card._cursor_buttons["dual"].toolTip().endswith(
        f"({QKeySequence('Ctrl+5').toString(QKeySequence.NativeText)})"
    )
    card._cursor_buttons["dual"].click()
    canvas.set_dual_cursor_frequencies(1.0, 100.0)
    qapp.processEvents()
    assert canvas.cursor_mode() == "dual"
    assert "Δf=" in cs._pill.primary_text()
    assert "background-color:#e8f1ff" in cs._pill.primary_text()
    assert cs._pill._frequency_dual_rows
    full_detail = cs._pill._detail.text()
    assert "Acceleration" in full_detail
    assert ">A</td>" in full_detail
    assert ">B</td>" in full_detail
    assert "△" in full_detail
    assert cs._pill.has_detail()
    full_right = cs._pill.x() + cs._pill.width()
    full_height = cs._pill.height()

    cs._pill._toggle_mode()
    mini_detail = cs._pill._detail.text()
    assert mini_detail != full_detail
    assert ">A</td>" not in mini_detail
    assert ">B</td>" not in mini_detail
    assert cs._pill.height() < full_height
    assert abs((cs._pill.x() + cs._pill.width()) - full_right) <= 1
    cs._pill._toggle_mode()
    assert cs._pill._detail.text() == full_detail
    assert abs((cs._pill.x() + cs._pill.width()) - full_right) <= 1


def test_fft_single_cursor_uses_the_time_style_expandable_channel_panel(
    qapp, qtbot,
):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1000, 700)
    cs.show()
    cs.set_mode("fft")
    canvas = cs.canvas_fft
    canvas.plot_spectra(
        [
            {
                "freq": np.array([1.0, 10.0, 100.0]),
                "amp": np.array([2.0, 3.0, 4.0]),
                "label": "MOTOR Y",
                "color": "#2563eb",
                "time": np.array([0.0, 1.0]),
                "signal": np.array([0.0, 1.0]),
            },
            {
                "freq": np.array([1.0, 10.0, 100.0]),
                "amp": np.array([1.0, 1.5, 2.0]),
                "label": "MOTOR X",
                "color": "#dc2626",
                "time": np.array([0.0, 1.0]),
                "signal": np.array([0.0, 1.0]),
            },
        ],
        xlim=(0.0, 100.0), amp_label="Amplitude", title="FFT",
    )
    cs._fft_card._cursor_buttons["single"].click()
    canvas.set_cursor_frequency(100.0)
    qapp.processEvents()

    assert cs._pill.primary_text().startswith('<span style="color:#111827;">f=')
    full_detail = cs._pill._detail.text()
    assert "MOTOR Y" in full_detail
    assert "MOTOR X" in full_detail
    cs._pill._toggle_mode()
    assert "MOTOR Y" not in cs._pill._detail.text()
    assert "MOTOR X" not in cs._pill._detail.text()
    cs._pill._toggle_mode()
    assert cs._pill._detail.text() == full_detail


def test_frequency_cursor_controls_are_trailing_aligned_like_time(qapp, qtbot):
    """Shown toolbars must spend spare width before, not after, the segment."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1000, 700)
    cs.show()
    qapp.processEvents()

    for mode, card in (("fft", cs._fft_card), ("frf", cs._frf_card)):
        cs.set_mode(mode)
        qapp.processEvents()
        spacer = card._frequency_controls_spacer
        buttons = tuple(card._cursor_buttons.values())
        assert spacer.width() > 0
        assert buttons[0].geometry().left() > spacer.geometry().right()
        # The last selection button reaches the toolbar's trailing content
        # edge, just as the time-domain 双游标 button does.
        assert (
            card.toolbar.contentsRect().right() - buttons[-1].geometry().right()
        ) <= 8



def test_cursor_pill_updates_on_time_signal(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.canvas_time.cursor_info.emit("t=1.0s | Speed=100")
    assert "t=1.0s" in cs.cursor_pill_text()


def test_cursor_pill_renders_transparent_rounded_corners(qapp, qtbot):
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtGui import QColor, QImage, QPainter
    from mf4_analyzer.ui.chart_stack import CursorPill

    old_sheet = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        pill = CursorPill()
        qtbot.addWidget(pill)
        pill.set_primary('<span style="color:#111827;">A</span>')
        pill.resize(max(32, pill.width()), max(32, pill.height()))
        pill.show()
        QCoreApplication.processEvents()

        img = QImage(pill.width(), pill.height(), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        pill.render(painter)
        painter.end()

        corners = [
            QColor(img.pixelColor(0, 0)).alpha(),
            QColor(img.pixelColor(img.width() - 1, 0)).alpha(),
            QColor(img.pixelColor(0, img.height() - 1)).alpha(),
            QColor(img.pixelColor(img.width() - 1, img.height() - 1)).alpha(),
        ]
        assert max(corners) <= 8, (
            "cursor pill rounded corners must stay transparent; opaque corners "
            f"make the exported/live pill look like a square popup: {corners!r}"
        )
        center = QColor(img.pixelColor(img.width() // 2, img.height() // 2)).alpha()
        assert center >= 220
    finally:
        qapp.setStyleSheet(old_sheet)


def test_cursor_pill_toggle_exposes_distinct_full_and_mini_states(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    pill = CursorPill()
    qtbot.addWidget(pill)

    assert pill._toggle_btn.text() == "−"
    assert pill._toggle_btn.toolTip() == "收起为数值"
    assert pill._toggle_btn.property("cursorPillMode") == "full"

    pill._toggle_mode()

    assert pill._toggle_btn.text() == "+"
    assert pill._toggle_btn.toolTip() == "展开通道名"
    assert pill._toggle_btn.property("cursorPillMode") == "mini"

    pill._toggle_mode()

    assert pill._toggle_btn.text() == "−"
    assert pill._toggle_btn.toolTip() == "收起为数值"
    assert pill._toggle_btn.property("cursorPillMode") == "full"


def test_single_cursor_pill_uses_vertical_channel_readout(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    sep = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
    cs.canvas_time.cursor_info.emit(
        sep.join([
            '<span style="color:#111827;">t=89.1278s</span>',
            '<span style="color:#ef4444;">[tiadodamping] Rte_=<b>424.2</b></span>',
            '<span style="color:#7c3aed;">[tiadodamping] Rte_=<b>-1.486</b></span>',
        ])
    )

    assert cs._pill.primary_text() == '<span style="color:#111827;">t=89.1278s</span>'
    assert cs._pill.has_detail()
    detail = cs._pill._detail.text()
    assert '<table' in detail
    assert 'padding-top:6px' not in detail
    assert 'padding-top:2px' in detail
    assert 'line-height:1.15' in detail
    assert '424.2' in detail
    assert '-1.486' in detail
    assert '│' not in detail


def test_single_cursor_pill_builds_mini_value_only_detail(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#ef4444;">Rte_ESChkPlausi_mESMotorTorque_xds16=<b>0 Nm</b></span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#1769e0;">Rte_InCo_mInertiaCompMotorTorque_xds16=<b>0.04395 Nm</b></span>',
    ])

    primary, full_detail, mini_detail, tooltip = (
        cs._format_single_cursor_variants_for_pill(text)
    )

    assert primary == '<span style="color:#111827;">t=35.0358s</span>'
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16' in full_detail
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16' in full_detail
    assert '0 Nm' in mini_detail
    assert '0.04395 Nm' in mini_detail
    assert '#ef4444' in mini_detail
    assert '#1769e0' in mini_detail
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16' not in mini_detail
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16' not in mini_detail
    assert '[taiyaok]' not in mini_detail
    assert '=' not in cs._strip_html(mini_detail)
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16=0 Nm' in tooltip
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16=0.04395 Nm' in tooltip


def test_single_cursor_pill_mini_detail_reescapes_html_entities(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#22c55e;">escaped=<b>1 &lt;A&gt;&amp;</b></span>',
    ])

    _primary, _full_detail, mini_detail, tooltip = (
        cs._format_single_cursor_variants_for_pill(text)
    )

    assert '1 &lt;A&gt;&amp;' in mini_detail
    assert '1 <A>&' not in mini_detail
    assert 'escaped=1 <A>&' in tooltip


def test_single_cursor_pill_toggle_shows_value_only_mini_detail(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)

    assert 'Rte_PA_mAtMotorTorque_xds16' in cs._pill._detail.text()
    cs._pill._toggle_mode()

    detail = cs._pill._detail.text()
    assert '-1.841 Nm' in detail
    assert 'Rte_PA_mAtMotorTorque_xds16' not in detail
    assert '[taiyaok]' not in detail
    assert '=' not in cs._strip_html(detail)
    assert 'Rte_PA_mAtMotorTorque_xds16=-1.841 Nm' in cs._pill._detail.toolTip()


def test_cursor_pill_empty_dual_rows_clear_single_detail_state(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    pill = CursorPill()
    qtbot.addWidget(pill)
    pill.set_single_detail_html(
        "<table><tr><td>name=<b>1 Nm</b></td></tr></table>",
        "<table><tr><td>1 Nm</td></tr></table>",
        "name=1 Nm",
    )
    pill._toggle_mode()
    assert "1 Nm" in pill._detail.text()
    assert pill._detail.toolTip() == "name=1 Nm"

    pill.set_dual_rows([])

    assert pill._detail.text() == ""
    assert pill._detail.toolTip() == ""
    assert pill.has_detail() is False


def test_cursor_pill_toggle_collapse_preserves_right_edge(qapp, qtbot):
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    parent.resize(900, 360)
    qtbot.addWidget(parent)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    pill.set_primary("<span>t=1.0000s</span>")
    pill.set_single_detail_html(
        "<table><tr><td>long_channel_name_one=<b>1 Nm</b></td></tr>"
        "<tr><td>long_channel_name_two=<b>2 Nm</b></td></tr></table>",
        "<table><tr><td>1 Nm</td></tr><tr><td>2 Nm</td></tr></table>",
        "",
    )
    pill.move(80, 40)
    pill.show()
    qapp.processEvents()

    old_x = pill.x()
    old_right = pill.x() + pill.width()

    pill._toggle_mode()

    new_right = pill.x() + pill.width()
    assert pill.x() > old_x
    assert abs(new_right - old_right) <= 1


def test_cursor_pill_toggle_expand_stays_inside_parent_right_edge(qapp, qtbot):
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    parent.resize(900, 360)
    qtbot.addWidget(parent)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    pill.set_primary("<span>t=1.0000s</span>")
    pill.set_single_detail_html(
        "<table><tr><td>very_long_channel_name_that_needs_space=<b>1 Nm</b></td></tr>"
        "<tr><td>another_very_long_channel_name=<b>2 Nm</b></td></tr></table>",
        "<table><tr><td>1 Nm</td></tr><tr><td>2 Nm</td></tr></table>",
        "",
    )
    pill._toggle_mode()
    pill.move(parent.width() - pill.width() - 8, 40)
    pill.show()
    qapp.processEvents()

    mini_x = pill.x()
    old_right = pill.x() + pill.width()

    pill._toggle_mode()

    new_right = pill.x() + pill.width()
    assert pill.x() < mini_x
    assert new_right <= parent.width()
    assert abs(new_right - old_right) <= 1


def test_cursor_pill_toggle_stays_pinned_to_top_right_corner(qapp, qtbot):
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    parent.resize(1000, 400)
    qtbot.addWidget(parent)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    # Short first line + wide detail (single-cursor-like): the toggle must stay
    # at the pill's top-right corner, not snap left beside the short readout.
    pill.set_primary("<span>t=216.2100s</span>")
    pill.set_dual_rows([
        ("very_long_dual_cursor_channel_name_to_force_width",
         -1.0, 2.0, 0.5, 1.5, " Nm", "#ef4444"),
        ("another_long_dual_cursor_channel_name_for_more_width",
         -3.0, 4.0, 0.25, -0.75, " Nm", "#1769e0"),
    ])
    pill.show()
    qapp.processEvents()

    def corner_inset():
        pill.adjustSize()
        pill.resize(pill.sizeHint())
        qapp.processEvents()
        btn = pill._toggle_btn
        return pill.width() - (btn.x() + btn.width()), btn.y()

    right_inset_full, top_full = corner_inset()
    full_width = pill.width()
    pill._toggle_mode()
    right_inset_mini, top_mini = corner_inset()
    mini_width = pill.width()

    # The scenario flips the pill width, yet the toggle hugs the top-right
    # corner in both modes (never drifts left toward the short readout).
    assert mini_width != full_width
    assert right_inset_full <= 6 and top_full <= 6
    assert right_inset_mini <= 6 and top_mini <= 6
    # Reserved first-line padding keeps the corner button off the primary text.
    assert pill._primary.contentsMargins().right() >= 20
    primary_text_right = (
        pill._primary.x()
        + pill._primary.sizeHint().width()
        - pill._primary.contentsMargins().right()
    )
    assert pill._toggle_btn.x() >= primary_text_right


def test_user_placed_primary_pill_preserves_right_edge_after_dual_rows_resize(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('dual')
    qapp.processEvents()

    cs._pill.set_primary("<span>A=1.0s │ B=2.0s</span>")
    cs._pill.set_detail_html("<table><tr><td>short</td></tr></table>")
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(cs.stack.width() - cs._pill.width() - 8, 48)
    qapp.processEvents()

    old_right = cs._pill.x() + cs._pill.width()
    rows = [
        (
            "very_long_channel_name_that_expands_the_dual_cursor_rows_width",
            -1.0,
            2.0,
            0.5,
            1.5,
            " Nm",
            "#ef4444",
        ),
        (
            "another_long_channel_name_to_force_a_wider_floating_pill",
            -3.0,
            4.0,
            0.25,
            -0.75,
            " deg",
            "#1769e0",
        ),
    ]

    cs.canvas_time.dual_cursor_rows.emit(rows)
    qapp.processEvents()

    new_right = cs._pill.x() + cs._pill.width()
    assert new_right <= cs.stack.width()
    assert abs(new_right - min(old_right, cs.stack.width())) <= 1


def test_user_placed_primary_pill_preserves_right_edge_when_content_shrinks(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('dual')
    qapp.processEvents()

    cs._pill.set_primary("<span>A=1.0s │ B=2.0s │ ΔT=1.0s</span>")
    cs._pill.set_detail_html(
        "<table><tr><td>"
        "very_long_dual_cursor_channel_name_that_makes_the_pill_wide=123 Nm"
        "</td></tr></table>"
    )
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(cs.stack.width() - cs._pill.width() - 8, 56)
    qapp.processEvents()

    old_right = cs._pill.x() + cs._pill.width()
    old_x = cs._pill.x()

    cs.set_cursor_mode('single')
    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=3.0000s</span>',
        '<span style="color:#1769e0;">speed=<b>5 rpm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)
    qapp.processEvents()

    new_right = cs._pill.x() + cs._pill.width()
    assert cs._pill.x() > old_x
    assert abs(new_right - old_right) <= 1


def test_default_primary_pill_reanchors_to_canvas_after_mode_content_resize(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('single')
    qapp.processEvents()

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=1.0000s</span>',
        '<span style="color:#ef4444;">long_name=<b>1 Nm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)
    qapp.processEvents()

    canvas_origin = cs.canvas_time.mapTo(cs.stack, cs.canvas_time.rect().topLeft())
    expected_right = canvas_origin.x() + cs.canvas_time.width() - 8
    actual_right = cs._pill.x() + cs._pill.width()
    assert abs(actual_right - expected_right) <= 2
    assert cs._pill.is_user_placed() is False


def test_cursor_pill_snapshot_restore_preserves_single_mini_variants(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)
    cs._pill._toggle_mode()

    snapshot = cs.cursor_pill_snapshot()
    cs._pill.set_detail_html("<b>clobbered</b>")
    cs._pill.set_primary("clobbered primary")

    cs.restore_cursor_pill_snapshot(snapshot)

    assert cs._pill._toggle_btn.text() == "+"
    assert cs._pill._toggle_btn.property("cursorPillMode") == "mini"
    detail = cs._pill._detail.text()
    assert "-1.841 Nm" in detail
    assert "Rte_PA_mAtMotorTorque_xds16" not in detail
    assert "[taiyaok]" not in detail
    assert "=" not in cs._strip_html(detail)
    assert "Rte_PA_mAtMotorTorque_xds16=-1.841 Nm" in cs._pill._detail.toolTip()

    cs._pill._toggle_mode()

    assert cs._pill._toggle_btn.text() == "−"
    assert "Rte_PA_mAtMotorTorque_xds16" in cs._pill._detail.text()


def test_cursor_pill_toggle_qss_has_distinct_full_and_mini_rules():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert 'QPushButton#cursorPillToggle[cursorPillMode="full"]' in qss
    assert 'QPushButton#cursorPillToggle[cursorPillMode="mini"]' in qss
    assert '#2563eb' in qss


def test_cursor_pill_hidden_in_fft_mode(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('fft')
    assert not cs.cursor_pill_visible()


def test_heatmap_cursor_info_does_not_show_pill_in_fft_time_or_order(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)

    for mode, canvas in (
        ('fft_time', cs.canvas_fft_time),
        ('order', cs.canvas_order),
    ):
        cs.set_mode(mode)
        canvas.cursor_info.emit("<div>X=1 s</div><div>Y=2 Hz</div><div>Z=3 dB</div>")

        assert not cs.cursor_pill_visible()


def test_analysis_cards_expose_annotation_toolbar_controls(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    assert hasattr(cs._time_card, '_annotation_btn')
    assert hasattr(cs._time_card, '_clear_annotation_btn')
    assert cs._time_card._clear_annotation_btn.objectName() == 'chartAnnotationClearButton'
    assert cs._time_card._clear_annotation_btn.text() == ''
    assert cs._time_card._clear_annotation_btn.toolTip()
    assert cs._time_card._annotation_btn.toolTip()
    for card in (cs._fft_card, cs._fft_time_card, cs._frf_card, cs._order_card):
        assert hasattr(card, '_annotation_btn')
        assert hasattr(card, '_clear_annotation_btn')
        assert card._annotation_btn.objectName() == 'chartAnnotationButton'
        assert card._annotation_btn.text() == ''
        assert card._annotation_btn.isCheckable()
        assert card._annotation_btn.toolTip()
        assert card._clear_annotation_btn.objectName() == 'chartAnnotationClearButton'
        assert card._clear_annotation_btn.text() == ''
        assert card._clear_annotation_btn.toolTip()


def test_time_annotation_control_follows_zoom_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    card = cs._time_card
    actions = card.toolbar.actions()
    zoom_index = next(i for i, act in enumerate(actions) if act.data() == 'zoom')
    annotation_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._annotation_btn
    )
    clear_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._clear_annotation_btn
    )
    copy_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._copy_btn
    )
    tick_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._tick_density_btn
    )
    options_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._options_btn
    )
    save_index = next(i for i, act in enumerate(actions) if act.data() == 'save')

    assert zoom_index < annotation_index < clear_index < copy_index < tick_index
    assert tick_index < options_index < save_index


def test_time_clear_annotation_button_calls_canvas_clear_remarks(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    calls = []
    cs._time_card.canvas.clear_remarks = lambda: calls.append("clear")

    cs._time_card._clear_annotation_btn.click()

    assert calls == ["clear"]


def test_frf_clear_annotation_button_calls_canvas_clear_remarks(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    calls = []
    cs._frf_card.canvas.clear_remarks = lambda: calls.append("clear")

    cs._frf_card._clear_annotation_btn.click()

    assert calls == ["clear"]


def test_clear_annotation_skips_confirm_when_no_remarks(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs._time_card

    calls = []
    card.canvas.clear_remarks = lambda: calls.append("clear")
    card.canvas.remark_count = lambda: 0
    confirmed = []
    card._confirm_clear_annotations = lambda count: confirmed.append(count) or True

    card._clear_annotation_btn.click()

    # Empty chart clears silently — no dialog on a high-frequency no-op click.
    assert confirmed == []
    assert calls == ["clear"]


def test_clear_annotation_confirms_when_remarks_present(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs._time_card

    calls = []
    card.canvas.clear_remarks = lambda: calls.append("clear")
    card.canvas.remark_count = lambda: 2

    prompts = []
    card._confirm_clear_annotations = lambda count: prompts.append(count) or False
    card._clear_annotation_btn.click()
    assert prompts == [2]
    assert calls == []  # cancelled → nothing cleared

    card._confirm_clear_annotations = lambda count: prompts.append(count) or True
    card._clear_annotation_btn.click()
    assert prompts == [2, 2]
    assert calls == ["clear"]  # accepted → cleared


def test_analysis_annotation_controls_follow_zoom_on_left(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._fft_card, cs._fft_time_card, cs._frf_card, cs._order_card):
        actions = card.toolbar.actions()
        toolbar_widgets = [card.toolbar.widgetForAction(act) for act in actions]
        assert not any(
            getattr(widget, "objectName", lambda: "")() == "chartHint"
            for widget in toolbar_widgets
            if widget is not None
        )
        assert not any(
            getattr(widget, "objectName", lambda: "")() == "chartLocLabel"
            for widget in toolbar_widgets
            if widget is not None
        )
        zoom_index = next(i for i, act in enumerate(actions) if act.data() == 'zoom')
        annotation_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._annotation_btn
        )
        clear_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._clear_annotation_btn
        )
        copy_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._copy_btn
        )

        assert zoom_index < annotation_index < clear_index < copy_index


def test_time_toolbar_controls_are_pushed_right_without_toolbar_coords(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    card = cs._time_card
    actions = card.toolbar.actions()
    toolbar_widgets = [card.toolbar.widgetForAction(act) for act in actions]
    assert not any(
        getattr(widget, "objectName", lambda: "")() == "chartHint"
        for widget in toolbar_widgets
        if widget is not None
    )
    assert not any(
        getattr(widget, "objectName", lambda: "")() == "chartLocLabel"
        for widget in toolbar_widgets
        if widget is not None
    )
    spacer_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._time_controls_spacer
    )
    subplot_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card.btn_subplot
    )
    cursor_dual_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._cursor_buttons['dual']
    )

    assert spacer_index < subplot_index < cursor_dual_index
    assert (
        card._time_controls_spacer.sizePolicy().horizontalPolicy()
        == QSizePolicy.Expanding
    )
    assert card._time_controls_spacer.testAttribute(Qt.WA_StyledBackground)


def test_chart_nav_actions_have_chart_area_shortcuts(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    expected = {
        "home": "Ctrl+R",
        "back": "Ctrl+Z",
        "forward": "Ctrl+Shift+Z",
        "pan": "Ctrl+G",
        "zoom": "Ctrl+B",
    }
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        card_action_keys = {act.data() for act in card.actions()}
        for key, shortcut in expected.items():
            action = next(act for act in card.toolbar.actions() if act.data() == key)
            assert action.shortcut().toString(QKeySequence.PortableText) == shortcut
            assert action.shortcutContext() == Qt.WidgetWithChildrenShortcut
            assert key in card_action_keys
            # Tooltip must include the shortcut in NativeText form so users
            # can discover it without consulting docs.
            assert action.toolTip()
            assert action.shortcut().toString(QKeySequence.NativeText) in action.toolTip()


def test_time_card_segmented_buttons_have_ctrl_digit_shortcuts(qapp, qtbot):
    """Ctrl+1..5 are wired to 分屏/叠加/游标关/单游标/双游标 buttons and the
    tooltip carries the shortcut in native form."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    card = cs._time_card
    expected_pairs = [
        (card.btn_subplot,                'Ctrl+1', '分屏'),
        (card.btn_overlay,                'Ctrl+2', '叠加'),
        (card._cursor_buttons['off'],     'Ctrl+3', '游标关'),
        (card._cursor_buttons['single'],  'Ctrl+4', '单游标'),
        (card._cursor_buttons['dual'],    'Ctrl+5', '双游标'),
    ]
    registered = {
        s.key().toString(): s for s in card._time_button_shortcuts
    }
    for _btn, shortcut, _label in expected_pairs:
        assert shortcut in registered, f"Missing shortcut {shortcut}"
        sc = registered[shortcut]
        assert sc.context() == Qt.WidgetWithChildrenShortcut
    for btn, shortcut, label in expected_pairs:
        native = QKeySequence(shortcut).toString(QKeySequence.NativeText)
        tip = btn.toolTip()
        assert label in tip
        assert native in tip

    annotation_shortcut = card._time_annotation_shortcut
    assert annotation_shortcut.key().toString() == 'Ctrl+M'
    assert annotation_shortcut.context() == Qt.WidgetWithChildrenShortcut
    native = QKeySequence('Ctrl+M').toString(QKeySequence.NativeText)
    assert '标注' in card._annotation_btn.toolTip()
    assert native in card._annotation_btn.toolTip()


def test_time_toolbar_has_no_loc_label_to_jostle_right_controls(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1500, 520)
    cs.show()
    qtbot.waitExposed(cs)
    # Production QSS can reflow the toolbar one tick after expose
    # (1420 → 1436). Read ``before`` only after that settle.
    qapp.processEvents()
    qapp.processEvents()

    card = cs._time_card
    loc_label = getattr(card.toolbar, 'locLabel', None)
    assert loc_label is None or not loc_label.isVisible()
    assert not any(
        card.toolbar.widgetForAction(act) is loc_label
        for act in card.toolbar.actions()
    )
    before = card._cursor_buttons['dual'].geometry().topLeft()

    if loc_label is not None:
        loc_label.setText("(x, y) = (-19.0, 1.153)")
    qapp.processEvents()
    after = card._cursor_buttons['dual'].geometry().topLeft()

    assert after == before


def test_chart_toolbar_keeps_back_forward_actions_visible(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(820, 500)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()
    card = cs._time_card

    actions = {act.data(): act for act in card.toolbar.actions() if act.data()}
    assert {'back', 'forward'} <= set(actions)
    for key in ('back', 'forward'):
        widget = card.toolbar.widgetForAction(actions[key])
        assert widget is not None
        assert widget.isVisible()
        assert not widget.icon().isNull()


def test_pg_navigation_toolbar_pan_zoom_sets_all_subplot_viewboxes(qapp, qtbot):
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ], mode="subplot")
    cs.canvas_time.draw()
    qapp.processEvents()

    handles = list(cs.canvas_time.axes_list)
    assert len(handles) == 3
    view_boxes = [handle.view_box for handle in handles]

    cs._time_card.toolbar.zoom()
    assert str(cs._time_card.toolbar.mode).lower() == 'zoom'
    assert [vb.state['mouseMode'] for vb in view_boxes] == [
        pg.ViewBox.RectMode,
        pg.ViewBox.RectMode,
        pg.ViewBox.RectMode,
    ]

    cs._time_card.toolbar.pan()
    assert str(cs._time_card.toolbar.mode).lower() == 'pan'
    assert [vb.state['mouseMode'] for vb in view_boxes] == [
        pg.ViewBox.PanMode,
        pg.ViewBox.PanMode,
        pg.ViewBox.PanMode,
    ]


def test_pg_zoom_mode_reapplied_to_subplot_viewboxes_after_replot(qapp, qtbot):
    """Bug 3: after activating zoom then re-plotting (e.g. toggling a
    channel rebuilds the ViewBoxes), every subplot ViewBox must STILL be
    RectMode. The toolbar mode stays 'zoom' but plot_channels builds fresh
    PanMode ViewBoxes, so the mode must be re-applied on rebuild."""
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    rows = [
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    cs._time_card.toolbar.zoom()
    assert str(cs._time_card.toolbar.mode).lower() == "zoom"

    # REPLOT — rebuilds every ViewBox at PanMode default.
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    assert str(cs._time_card.toolbar.mode).lower() == "zoom", (
        "replot must not change the toolbar mode"
    )
    modes = [h.view_box.state["mouseMode"] for h in cs.canvas_time.axes_list]
    assert modes == [pg.ViewBox.RectMode] * len(modes), (
        f"zoom mode not re-applied to rebuilt subplot ViewBoxes; got {modes}"
    )


def test_pg_zoom_mode_reaches_overlay_x_master_viewbox(qapp, qtbot):
    """Bug 3: in overlay mode the aux ViewBoxes are mouse-disabled; the
    real mouse-capture surface is the X-master ViewBox. Activating zoom must
    set the X-master ViewBox to RectMode."""
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    rows = [
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ]
    cs.canvas_time.plot_channels(rows, mode="overlay")
    qapp.processEvents()

    cs._time_card.toolbar.zoom()
    qapp.processEvents()

    master_vb = cs.canvas_time._x_master_handle.view_box
    assert master_vb.state["mouseMode"] == pg.ViewBox.RectMode, (
        "zoom mode did not reach the overlay X-master ViewBox"
    )

    # Toggling back to pan must reach it too.
    cs._time_card.toolbar.pan()
    qapp.processEvents()
    assert master_vb.state["mouseMode"] == pg.ViewBox.PanMode


class _FakeMenuEvent:
    """Minimal pyqtgraph mouse-event stand-in for ``raiseContextMenu``."""

    def __init__(self, accepted_item):
        self.acceptedItem = accepted_item

    def screenPos(self):
        from PyQt5.QtCore import QPointF

        return QPointF(0.0, 0.0)


def _open_redesigned_menu(canvas, view_box, monkeypatch):
    """Drive the real ``raiseContextMenu`` path (assemble + reshape per design
    A–D) without showing a window; return the reshaped QMenu."""
    from PyQt5.QtWidgets import QMenu

    captured = {}

    def _fake_popup(self, *_a, **_k):
        captured["menu"] = self

    monkeypatch.setattr(QMenu, "popup", _fake_popup, raising=True)
    view_box.raiseContextMenu(_FakeMenuEvent(view_box))
    return captured.get("menu")


def test_pg_context_menu_keeps_top_mouse_mode_shortcuts(
    qapp, qtbot, monkeypatch
):
    """The right-click menu keeps the compact top shortcuts while the axis
    form itself owns only coordinate operations."""
    import pyqtgraph as pg
    from PyQt5.QtWidgets import QToolButton, QWidgetAction

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="subplot")
    qapp.processEvents()

    toolbar = cs._time_card.toolbar
    vb = cs.canvas_time.axes_list[0].view_box
    view_boxes = [h.view_box for h in cs.canvas_time.axes_list]

    # Default card start is pan.
    assert str(toolbar.mode).lower() == "pan"

    toolbar.zoom()
    qapp.processEvents()
    assert str(toolbar.mode).lower() == "zoom"
    assert [b.state["mouseMode"] for b in view_boxes] == [pg.ViewBox.RectMode] * len(view_boxes)

    menu = _open_redesigned_menu(cs.canvas_time, vb, monkeypatch)
    inline_panel = next(
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "pgContextInlinePanel"
    )
    buttons = [
        inline_panel.findChild(QToolButton, "pgContextZoomButton"),
        inline_panel.findChild(QToolButton, "pgContextPanButton"),
    ]
    assert [btn.toolTip() for btn in buttons] == ["框选", "平移"]

    buttons[1].click()
    qapp.processEvents()

    assert str(toolbar.mode).lower() == "pan"
    assert [b.state["mouseMode"] for b in view_boxes] == [pg.ViewBox.PanMode] * len(view_boxes)


def _flush_history_debounce(toolbar, qapp):
    """Fire the toolbar's coalesce timer immediately so a simulated gesture
    is committed to the history stack without waiting wall-clock ms."""
    timer = getattr(toolbar, "_history_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        toolbar._commit_pending_view()
    qapp.processEvents()


def _simulate_pan(canvas, toolbar, qapp, lo, hi):
    """Drive a user pan: set the primary range then emit the ViewBox's
    manual-range signal (what a real drag emits) and flush the debounce."""
    primary = canvas._primary_xaxis_ax
    primary.set_xlim(lo, hi)
    vb = primary.view_box
    vb.sigRangeChangedManually.emit(vb.state["mouseEnabled"])
    _flush_history_debounce(toolbar, qapp)


def test_pg_toolbar_back_forward_tracks_pan_history(qapp, qtbot):
    """Task 1: a completed pan/zoom gesture appends the resulting view; back()
    steps to the previous view, forward() returns, and a new gesture after
    back() truncates the forward history. matplotlib-toolbar parity."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 200)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, np.cos(t), "#ef4444", "Nm"),
    ], mode="subplot")
    qapp.processEvents()
    toolbar = cs._time_card.toolbar
    canvas = cs.canvas_time
    primary = canvas._primary_xaxis_ax

    baseline = primary.get_xlim()

    # Gesture 1: pan to a sub-window.
    _simulate_pan(canvas, toolbar, qapp, 2.0, 4.0)
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))

    # Gesture 2: pan to another window.
    _simulate_pan(canvas, toolbar, qapp, 6.0, 8.0)
    assert primary.get_xlim() == pytest.approx((6.0, 8.0))

    # back() → previous view (2,4); back() again → baseline.
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx(baseline)

    # forward() walks back to (2,4) then (6,8).
    toolbar.forward()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    toolbar.forward()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((6.0, 8.0))

    # back() once, then a NEW gesture must truncate the forward history.
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    _simulate_pan(canvas, toolbar, qapp, 1.0, 3.0)
    toolbar.forward()  # no-op: forward truncated by the new gesture
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((1.0, 3.0))


def test_pg_toolbar_back_survives_plot_channels_rebuild(qapp, qtbot):
    """Task 1: history is keyed by channel name + range, not by a live axis
    handle, so a back() target still restores after a plot_channels rebuild
    swaps the underlying ViewBoxes for fresh objects."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 200)
    rows = [
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, np.cos(t), "#ef4444", "Nm"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    toolbar = cs._time_card.toolbar
    canvas = cs.canvas_time

    baseline = canvas._primary_xaxis_ax.get_xlim()
    _simulate_pan(canvas, toolbar, qapp, 3.0, 5.0)

    # Rebuild — fresh ViewBoxes; the stale-handle snapshot would no-op here.
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    # The rebuilt primary handle is a NEW object.
    new_primary = canvas._primary_xaxis_ax

    toolbar.back()
    qapp.processEvents()
    assert new_primary.get_xlim() == pytest.approx(baseline), (
        "back() after rebuild must restore the pre-pan range on the fresh handle"
    )


def test_pg_toolbar_home_keeps_subplot_x_ranges_identical_after_auto_range(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode("time")
    t1 = np.linspace(0.0, 1.0, 50)
    t2 = np.linspace(2.0, 4.0, 50)
    cs.canvas_time.plot_channels([
        ("a", True, t1, np.sin(t1), "#1769e0", "u"),
        ("b", True, t2, np.cos(t2), "#ef4444", "u"),
    ], mode="subplot")
    for handle in cs.canvas_time.axes_list:
        handle.set_xlim(0.25, 0.75)

    cs._time_card.toolbar.home()

    ranges = [handle.get_xlim() for handle in cs.canvas_time.axes_list]
    assert ranges[0] == pytest.approx((0.0, 4.0))
    assert ranges[1] == pytest.approx(ranges[0])


def test_pg_toolbar_home_restores_global_x_and_y_from_raw_data(qapp, qtbot):
    """Bug 4: Home must restore BOTH X (raw union) and Y (raw full min/max
    per channel) in one click. The hot-path PlotDataItem holds only the
    viewport-clipped envelope, so an autoRange()-based home read Y from the
    clipped window and left Y stuck near the previous zoom."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 4000)
    rows = [
        ("a", True, t, 100.0 * np.sin(t), "#1769e0", "u", "fid"),
        ("b", True, t, 5.0 + 2.0 * np.cos(t), "#ef4444", "u", "fid"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    # Zoom into a narrow X window and drive a real envelope refresh so each
    # PlotDataItem holds ONLY the clipped envelope for [4.0, 4.5].
    for h in cs.canvas_time.axes_list:
        h.set_xlim(4.0, 4.5)
    cs.canvas_time._flush_pending_refresh()
    qapp.processEvents()
    # Also pin a tiny Y window far from the data extents.
    for h in cs.canvas_time.axes_list:
        h.set_ylim(0.0, 0.01)
    qapp.processEvents()

    cs._time_card.toolbar.home()
    qapp.processEvents()

    # X must be the raw union for every axis.
    for h in cs.canvas_time.axes_list:
        xlo, xhi = h.get_xlim()
        assert xlo <= 0.05, f"X low not restored to ~0.0; got {xlo}"
        assert xhi >= 9.95, f"X high not restored to ~10.0; got {xhi}"

    # Y must span each channel's RAW full min/max (pyqtgraph adds a little
    # padding, so the restored range must CONTAIN the raw extents).
    handle0 = cs.canvas_time.axes_list[0]
    raw_a = cs.canvas_time.channel_data["a"][1]
    ylo0, yhi0 = handle0.get_ylim()
    assert ylo0 <= float(raw_a.min()) and yhi0 >= float(raw_a.max()), (
        f"Home left channel 'a' Y at ({ylo0}, {yhi0}); raw extents are "
        f"({raw_a.min()}, {raw_a.max()}) — Y was read from the clipped envelope"
    )

    handle1 = cs.canvas_time.axes_list[1]
    raw_b = cs.canvas_time.channel_data["b"][1]
    ylo1, yhi1 = handle1.get_ylim()
    assert ylo1 <= float(raw_b.min()) and yhi1 >= float(raw_b.max())


def test_chart_choice_checked_qss_uses_shared_selection_signature():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    selector = 'QWidget#chartToolbar QPushButton[role="chart-choice"]:checked'
    try:
        start = qss.index(selector)
        body = qss[start:qss.index("\n}", start)]
    except ValueError as exc:
        raise AssertionError(selector) from exc

    assert 'background-color: {{CONTROL_SURFACE_TOP}};' in body
    assert 'border-color: {{CONTROL_SELECT_LINE}};' in body
    assert 'color: {{CONTROL_TEXT_ON_SELECT}};' in body
    assert '#e8efff' not in body
    assert '#2563eb' not in body


def test_time_toolbar_controls_fit_when_inspector_narrows_chart(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(820, 500)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()

    card = cs._time_card
    controls = [
        card.btn_subplot,
        card.btn_overlay,
        card._cursor_buttons['off'],
        card._cursor_buttons['single'],
        card._cursor_buttons['dual'],
    ]
    right_edge = card.toolbar.rect().right()
    for button in controls:
        assert button.isVisible()
        assert button.geometry().right() <= right_edge


def test_time_card_quality_indicator_sits_on_canvas_lower_right(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()

    card = cs._time_card
    indicator = card._quality_indicator
    assert indicator.objectName() == "chartQualityIndicator"
    assert indicator.parent() is card

    canvas_rect = card.canvas.geometry()
    dot_rect = indicator.geometry()
    assert canvas_rect.contains(dot_rect.center())
    assert dot_rect.right() <= canvas_rect.right()
    assert dot_rect.bottom() <= canvas_rect.bottom()
    assert canvas_rect.right() - dot_rect.right() <= 12
    assert canvas_rect.bottom() - dot_rect.bottom() <= 12


def test_time_quality_indicator_updates_from_canvas_status_signal(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs._time_card

    cs.canvas_time.quality_status_changed.emit({
        "state": "green",
        "tooltip": "抗锯齿已完成",
    })
    qapp.processEvents()

    assert card._quality_indicator.property("qualityState") == "green"
    assert card._quality_indicator.toolTip() == "抗锯齿已完成"


def test_fft_card_quality_indicator_present_like_time_card(qapp, qtbot):
    """The FFT analysis card shows the same bottom-right AA traffic light the
    time-domain card does — PgLineCanvas now exposes quality_status* so
    _ChartCard wires the dot for the FFT pane too."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()

    card = cs._fft_card
    indicator = card._quality_indicator
    assert indicator is not None, "FFT card should host an AA quality dot"
    assert indicator.objectName() == "chartQualityIndicator"
    assert indicator.parent() is card

    cs.canvas_fft.quality_status_changed.emit({
        "state": "green", "tooltip": "抗锯齿已完成",
    })
    qapp.processEvents()
    assert card._quality_indicator.property("qualityState") == "green"


def test_flush_quality_indicator_swallows_dead_canvas(qapp, monkeypatch):
    """Queued quality-dot placement must tolerate a deleted canvas/card."""
    cs = ChartStack()
    card = cs._time_card
    card._quality_indicator_position_pending = True

    def _dead_canvas():
        raise RuntimeError("wrapped C/C++ object of type QWidget has been deleted")

    with monkeypatch.context() as scoped:
        scoped.setattr(card, "_position_quality_indicator", _dead_canvas)
        card._flush_quality_indicator_position()

    assert card._quality_indicator_position_pending is False


def test_cursor_off_clears_dual_cursor_pill(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    cs.set_cursor_mode('dual')
    cs.canvas_time.cursor_info.emit("A=1.0s")
    cs.canvas_time.dual_cursor_info.emit("<b>stats</b>")
    assert cs.cursor_pill_visible()

    cs._time_card.set_cursor_mode('off')

    assert not cs.cursor_pill_visible()
    assert cs.cursor_pill_text() == ""


def test_dual_cursor_primary_update_preserves_existing_detail(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('dual')

    cs.canvas_time.cursor_info.emit("A=1.0s")
    cs.canvas_time.dual_cursor_info.emit("<b>stats</b>")
    cs.canvas_time.cursor_info.emit("A=1.5s")

    assert cs._pill.primary_text() == "A=1.5s"
    assert "stats" in cs._pill._detail.text()


def test_cursor_pill_formats_single_cursor_details_for_mode(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span>t=1.0000s</span>',
        '<span style="color:#1769e0;">speed=<b>1 rpm</b></span>',
        '<span style="color:#ef4444;">torque=<b>2 Nm</b></span>',
    ])

    primary, detail = cs._format_cursor_info_for_pill(text)

    assert primary == '<span>t=1.0000s</span>'
    assert '<table' in detail
    assert 'padding-top:6px' not in detail
    assert 'padding-top:2px' in detail
    assert 'line-height:1.15' in detail
    assert 'speed=' in detail and 'torque=' in detail


def test_copy_card_image_renders_at_hidpi_scale(qapp, qtbot):
    """Spec §E: the toolbar copy path must request a hi-DPI render (scale
    > 1) of the canvas so the clipboard bitmap is crisp. Geometry gate:
    the copied pixmap is magnified vs a 1× grab of the same canvas."""
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    t = np.linspace(0, 1, 200)
    cs.canvas_time.plot_channels(
        [("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")]
    )
    QApplication.processEvents()

    base = cs.canvas_time.grab_pixmap(scale=1.0)
    assert not base.isNull()

    captured = []
    cs.image_captured.connect(captured.append)

    cs._copy_card_image(cs._time_card)
    QApplication.processEvents()
    assert captured, "copy path did not emit captured pixmap"
    pix = captured[-1]
    assert pix is not None and not pix.isNull(), "clipboard pixmap is null"
    # Hi-DPI: clipboard bitmap is wider than a 1× grab of the same canvas.
    assert pix.width() > base.width(), (
        f"copy pixmap width {pix.width()} not magnified vs 1x base {base.width()}"
    )


@pytest.mark.parametrize("mode, card_attr", [
    ("fft_time", "_fft_time_card"),
    ("order", "_order_card"),
])
def test_analysis_copy_image_includes_slice_panel(qapp, qtbot, mode, card_attr):
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode(mode)
    QApplication.processEvents()
    card = getattr(cs, card_attr)
    canvas = card.canvas
    y_coords = np.linspace(0, 20, 40)
    x_coords = np.linspace(0, 90, 60)
    matrix = np.random.RandomState(5).rand(40, 60)
    canvas.plot_or_update_heatmap(
        matrix=matrix, x_extent=(0, 90), y_extent=(0, 20),
        x_label='Time (s)',
        y_label='Order' if mode == 'order' else 'Frequency (Hz)',
        cbar_label='Amplitude', x_coords=x_coords, y_coords=y_coords,
        z_auto=True,
    )
    canvas._seed_slice()
    for _ in range(5):
        QApplication.processEvents()
    canvas._slice_panel.setStyleSheet(
        "QWidget#slicePanel { background-color: #ff00ff; }"
        "QLabel#sliceHint { background-color: #ff00ff; color: #ff00ff; }"
    )
    QApplication.processEvents()

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(card)
    QApplication.processEvents()

    assert captured, "copy path did not emit an analysis pixmap"
    pix = captured[-1]
    img = pix.toImage()
    geo = canvas._slice_panel.geometry()
    scale_x = img.width() / max(1, canvas.width())
    scale_y = img.height() / max(1, canvas.height())
    samples = []
    for fx, fy in ((0.50, 0.50), (0.35, 0.35), (0.65, 0.65)):
        px = int(round((geo.x() + geo.width() * fx) * scale_x))
        py = int(round((geo.y() + geo.height() * fy) * scale_y))
        px = min(max(px, 0), img.width() - 1)
        py = min(max(py, 0), img.height() - 1)
        samples.append(img.pixelColor(px, py).name().lower())
    assert "#ff00ff" in samples, (
        f"{mode} copy image did not include the slice info panel; "
        f"sampled colors={samples!r}"
    )


def test_copy_card_image_composites_scaled_cursor_pill(qapp, qtbot, monkeypatch):
    """Spec §E: the copy path must still composite the cursor pill, and
    BOTH its position and size must scale by the same factor so it lines
    up on the magnified bitmap. We intercept the QPainter.drawPixmap call
    to capture the scaled pill rect actually drawn."""
    from PyQt5.QtGui import QPainter
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    t = np.linspace(0, 1, 200)
    cs.canvas_time.plot_channels(
        [("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")]
    )
    QApplication.processEvents()

    # Make the pill visible and place it well inside the canvas so the
    # overlap branch fires.
    cs._pill.set_primary('<span style="color:#111827;">t=0.5s</span>')
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(40, 40)
    QApplication.processEvents()

    drawn = []
    real_draw = QPainter.drawPixmap

    def _spy_draw(self, *args):
        # signature used by the copy path: drawPixmap(QRect, QPixmap)
        drawn.append(args)
        return real_draw(self, *args)

    monkeypatch.setattr(QPainter, "drawPixmap", _spy_draw)

    captured = []
    cs.image_captured.connect(captured.append)

    cs._copy_card_image(cs._time_card)
    QApplication.processEvents()

    assert captured, "copy path did not emit captured pixmap"
    assert drawn, "copy path did not composite the cursor pill"
    rect = drawn[-1][0]
    pill = cs._pill
    # The composited pill rect must be scaled (> 1×) relative to the
    # unscaled pill geometry so it lines up on the magnified bitmap.
    assert rect.width() > pill.width(), (
        f"composited pill width {rect.width()} not scaled vs {pill.width()}"
    )
    assert rect.height() > pill.height(), (
        f"composited pill height {rect.height()} not scaled vs {pill.height()}"
    )


def test_copy_card_image_composites_cursor_pill_inside_hidpi_pixmap(
    qapp, qtbot, monkeypatch
):
    """On macOS Retina, QPixmap painting uses logical DPR coordinates. The
    copied image is normalized before pill compositing so the pill is painted
    inside the final pixel buffer rather than off the right edge."""
    from PyQt5.QtGui import QColor, QPixmap
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    QApplication.processEvents()

    source = QPixmap(1000, 600)
    source.fill(QColor("#ffffff"))
    source.setDevicePixelRatio(2.0)

    def _fake_grab(scale=1.0):
        return QPixmap(source)

    red_pill = QPixmap(120, 60)
    red_pill.fill(QColor("#ff0000"))

    monkeypatch.setattr(cs.canvas_time, "grab_pixmap", _fake_grab)
    monkeypatch.setattr(cs, "_grab_pill_scaled", lambda *args, **kwargs: red_pill)

    cs._pill.resize(80, 40)
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    canvas_origin = cs.canvas_time.mapTo(cs.stack, cs.canvas_time.rect().topLeft())
    cs._pill.move(canvas_origin.x() + 400, canvas_origin.y() + 20)

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(cs._time_card)

    assert captured
    pix = captured[-1]
    assert pix.devicePixelRatioF() == 1.0
    img = pix.toImage()
    red_samples = 0
    for x in range(0, img.width(), 10):
        for y in range(0, img.height(), 10):
            color = img.pixelColor(x, y)
            if color.red() > 200 and color.green() < 80 and color.blue() < 80:
                red_samples += 1
    assert red_samples > 0


def test_grab_presentation_pixmap_composites_pill_at_unit_scale(qapp, qtbot):
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    t = np.linspace(0, 1, 200)
    cs.canvas_time.plot_channels(
        [("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")]
    )
    QApplication.processEvents()

    cs._pill.set_primary('<span style="color:#111827;">t=0.5s</span>')
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    canvas_origin = cs.canvas_time.mapTo(cs.stack, cs.canvas_time.rect().topLeft())
    cs._pill.move(canvas_origin.x() + 40, canvas_origin.y() + 40)
    QApplication.processEvents()

    pix = cs.grab_presentation_pixmap(cs.canvas_time, scale=1.0)
    assert pix is not None and not pix.isNull()
    base = cs.canvas_time.grab_pixmap(scale=1.0)
    assert pix.width() == base.width()
    assert pix.height() == base.height()


def test_save_figure_uses_hidpi_scale(qapp, qtbot, monkeypatch, tmp_path):
    """Spec §E: save_figure must request a hi-DPI render (scale > 1)."""
    from PyQt5.QtWidgets import QFileDialog

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    cs.canvas_time.plot_channels(
        [("speed", True, np.linspace(0, 1, 100), np.zeros(100), "#1769e0", "rpm", "f")]
    )

    out = str(tmp_path / "out.png")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "PNG (*.png)"))
    )
    captured = {}
    real_grab = cs._time_card.canvas.grab_pixmap

    def _spy_grab(scale=1.0):
        captured["scale"] = scale
        return real_grab(scale=scale)

    monkeypatch.setattr(cs._time_card.canvas, "grab_pixmap", _spy_grab)
    cs._time_card.toolbar.save_figure()

    assert captured.get("scale", 1.0) > 1.0, (
        f"save_figure used scale={captured.get('scale')}, expected hi-DPI > 1"
    )
    assert Path(out).exists(), "save_figure did not write the file"


def test_save_image_failure_warns(qapp, qtbot, monkeypatch, tmp_path):
    """pix.save() returning False must surface a failure warning."""
    import mf4_analyzer.ui.chart_stack as chart_stack_pkg
    import mf4_analyzer.ui.chart_stack.toolbar as toolbar_mod

    class _FailingPixmap:
        def isNull(self):
            return False

        def save(self, _path):
            return False

    cs = ChartStack()
    qtbot.addWidget(cs)
    toolbar = cs._time_card.toolbar

    out = str(tmp_path / "blocked.png")
    monkeypatch.setattr(
        chart_stack_pkg.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (out, "PNG (*.png)")),
    )
    calls = []

    class _MessageBoxSpy:
        @staticmethod
        def warning(*args):
            calls.append(args)

    monkeypatch.setattr(toolbar_mod, "QMessageBox", _MessageBoxSpy, raising=False)
    toolbar._save_pixmap_provider = lambda: _FailingPixmap()

    toolbar.save_figure()

    assert calls, "save failure must raise a warning dialog"
    assert calls[0][0] is toolbar
    assert calls[0][1] == "保存失败"
    assert out in calls[0][2]


def test_overlay_curve_drag_leaves_toolbar_idle_during_selection(qapp, qtbot):
    """Selecting a curve in overlay mode must drop pan (so blank clicks can
    later deselect), and a Y-drag on the selected curve must shift its ylim
    while X stays pinned. The pyqtgraph canvas has no pixel curve-select
    gesture, so we drive selection via the public ``select_overlay_channel``
    seam (established PG-test convention); the toolbar pan-drop and Y-drag
    are the real observable user outcomes."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    # Pin xlim explicitly so the Y-drag X-stability assertion is byte-exact
    # (an unset xlim leaves pyqtgraph X auto-range on, which would drift).
    primary.set_xlim(0.0, 1.0)
    primary.set_ylim(-2.0, 8.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()
    before_primary_ylim = primary.get_ylim()

    # Frame A → B: selecting 'torque' fires overlay_channel_selected, which
    # TimeChartCard wires to drop the nav toolbar out of pan.
    cs.canvas_time.select_overlay_channel("torque")
    qapp.processEvents()
    assert cs.canvas_time._overlay_axes.selected_channel == "torque"
    selected_axis = cs.canvas_time._channel_lines["torque"][0]
    before_selected_ylim = selected_axis.get_ylim()
    # Selection must have dropped pan so a subsequent blank click can
    # reach the deselect gate without being eaten by a pan press.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()

    # Y-drag on the selected curve: 40 px downward shifts ylim; X must not
    # move (Fix 2 captures+restores the primary xlim around set_ylim).
    cs.canvas_time._begin_overlay_y_drag_at(start_y_px=100.0)
    moved = cs.canvas_time._apply_overlay_y_drag_at(current_y_px=140.0)
    qapp.processEvents()

    assert moved is True
    assert selected_axis.get_ylim() != pytest.approx(before_selected_ylim)
    assert primary.get_ylim() == pytest.approx(before_primary_ylim)
    # X is byte-stable after a Y-only drag (Fix 2).
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)
    # Drag does not auto-restore pan.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()


def test_overlay_blank_click_clears_selection_after_curve_drag(qapp, qtbot):
    """After a curve selection, a deselect interaction clears the selection
    (emitting overlay_channel_selected(None)) and X stays unchanged. The PG
    canvas has no wired blank-click gesture, so deselect is driven via the
    public ``select_overlay_channel(None)`` seam (PG-test convention)."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()

    events = []
    cs.canvas_time.overlay_channel_selected.connect(events.append)

    cs.canvas_time.select_overlay_channel("torque")
    qapp.processEvents()
    assert cs.canvas_time._overlay_axes.selected_channel == "torque"
    assert events[-1] == "torque"
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()

    before_xlim = primary.get_xlim()

    # Deselect (the blank-click outcome): selection clears, X unchanged.
    cs.canvas_time.select_overlay_channel(None)
    qapp.processEvents()

    assert cs.canvas_time._overlay_axes.selected_channel is None
    assert events[-1] is None
    assert len(events) == 2  # exactly select + deselect
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)
    # Deselect does not re-engage pan.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()


def test_dblclick_chart_options_does_not_leave_pan_drag_active(qapp, qtbot, monkeypatch):
    """A native double-click over a subplot opens the chart-options dialog
    for THAT subplot's axis handle (Fix 1), and leaves no stuck drag: xlim
    is unchanged and the ViewBox is back at its default (PanMode) mouse
    mode. Driven with QTest.mouseDClick now that the gesture is wired via a
    viewport event filter; the dialog open is observed by monkeypatching
    the handle-aware entry point."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    # Pin xlim so the post-double-click X-stability check is byte-exact.
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()

    from mf4_analyzer.ui import _axis_interaction

    captured = []

    def fake_edit(parent, handle):
        # The dialog must be opened for an axis handle the canvas owns.
        assert handle in cs.canvas_time.axes_list
        captured.append(handle)
        return True

    monkeypatch.setattr(
        _axis_interaction, 'edit_chart_options_dialog', fake_edit, raising=False
    )

    viewport = cs.canvas_time._glw.viewport()
    center = viewport.rect().center()
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    qapp.processEvents()

    # The chart-options open path fired exactly once for a real axis handle.
    assert len(captured) == 1
    # No stuck pan-drag: the canvas's overlay-drag bookkeeping is cleared
    # and the ViewBox is back at its default PanMode mouse mode.
    assert cs.canvas_time._overlay_axes.drag_start is None
    assert not cs.canvas_time._chart_options_opening
    import pyqtgraph as pg
    assert primary.view_box.state['mouseMode'] == pg.ViewBox.PanMode
    # xlim byte-stable across the double-click.
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)


def test_dblclick_chart_options_restores_pan_without_starting_span_selector(
    qapp, qtbot, monkeypatch
):
    """A double-click opens the chart-options dialog AND must not arm a span
    selector. The PG design keeps ``span_selector`` None by contract
    (enable_span_selector stores the callback but never installs a widget),
    so we assert the double-click opens options while span_selector stays
    None and the view returns to its default interactive mouse mode."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
    ], mode="subplot")
    # enable_span_selector stores the callback but installs NO widget — the
    # always-on SpanSelector was retired (design §4.2). span_selector is None.
    cs.canvas_time.enable_span_selector(lambda _xmin, _xmax: None)
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()
    assert cs.canvas_time.span_selector is None

    primary = cs.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()

    from mf4_analyzer.ui import _axis_interaction

    captured = []
    monkeypatch.setattr(
        _axis_interaction,
        'edit_chart_options_dialog',
        lambda parent, handle: (captured.append(handle), True)[1],
        raising=False,
    )

    viewport = cs.canvas_time._glw.viewport()
    center = viewport.rect().center()
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    qapp.processEvents()

    # Options opened for the subplot axis.
    assert len(captured) == 1
    assert captured[-1] in cs.canvas_time.axes_list
    # Double-click did NOT create a span selector (PG design keeps it None).
    assert cs.canvas_time.span_selector is None
    # View returned to default interactive state, no stuck drag.
    import pyqtgraph as pg
    assert primary.view_box.state['mouseMode'] == pg.ViewBox.PanMode
    assert not cs.canvas_time._chart_options_opening
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)


def test_dblclick_second_subplot_opens_options_for_that_axis(qapp, qtbot, monkeypatch):
    """Targeting test (per signal-processing/2026-05-19-branch-reached-is-not-
    behavior-correct): with ≥3 subplots, double-clicking the SECOND subplot's
    plot face must open chart-options for THAT subplot's ``PgAxisHandle`` — by
    object identity, not membership in ``axes_list`` — and double-clicking the
    THIRD must open the third's, proving the viewport→scene hit-test really
    discriminates subplots rather than always returning the primary/index-1.

    Geometry is computed from real ViewBox ``sceneBoundingRect()`` centers
    mapped back to viewport pixels via the GraphicsView's ``mapFromScene``
    (the exact inverse of the production ``mapToScene`` path), so the pixel
    coords are derived from live pyqtgraph geometry, not guessed."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    # subplot mode requires len(vis) > 1; plot 3 channels so axes_list has 3
    # distinct PgAxisHandles each with its own ViewBox.
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ], mode="subplot")
    cs.canvas_time.draw()
    qapp.processEvents()

    handles = list(cs.canvas_time.axes_list)
    assert len(handles) == 3, "expected one PgAxisHandle per subplot channel"
    # Each subplot must own a distinct ViewBox with a distinct scene region,
    # otherwise the targeting assertion below would be vacuous.
    rects = [h.view_box.sceneBoundingRect() for h in handles]
    centers = [r.center() for r in rects]
    ys = sorted(c.y() for c in centers)
    assert ys[0] < ys[1] < ys[2], "subplot ViewBox centers must be vertically distinct"

    from mf4_analyzer.ui import _axis_interaction

    glw = cs.canvas_time._glw
    viewport = glw.viewport()

    def dblclick_subplot_center(idx):
        """Double-click at the viewport pixel for the center of subplot idx's
        ViewBox, mapping the live scene center back through the GraphicsView."""
        scene_center = handles[idx].view_box.sceneBoundingRect().center()
        viewport_pt = glw.mapFromScene(scene_center)
        QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport_pt)
        qapp.processEvents()

    captured = []
    monkeypatch.setattr(
        _axis_interaction,
        'edit_chart_options_dialog',
        lambda parent, handle: (captured.append(handle), True)[1],
        raising=False,
    )

    # --- Double-click the SECOND subplot --------------------------------
    dblclick_subplot_center(1)
    assert len(captured) == 1
    # Identity, not membership: it must be the SAME handle (and same
    # underlying ViewBox) as the second subplot, not merely "a handle".
    assert captured[-1] is handles[1]
    assert captured[-1].view_box is handles[1].view_box
    # And explicitly NOT the primary/first or third.
    assert captured[-1] is not handles[0]
    assert captured[-1] is not handles[2]

    # --- Double-click the THIRD subplot ---------------------------------
    # Repeat for a third subplot so we know the resolver is not just always
    # returning index 1.
    dblclick_subplot_center(2)
    assert len(captured) == 2
    assert captured[-1] is handles[2]
    assert captured[-1].view_box is handles[2].view_box
    assert captured[-1] is not handles[1]

    # --- And the FIRST subplot for completeness -------------------------
    dblclick_subplot_center(0)
    assert len(captured) == 3
    assert captured[-1] is handles[0]
    assert captured[-1].view_box is handles[0].view_box


def test_time_controls_spacer_has_toolbar_background_rule():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    match = re.search(
        r"QWidget#chartToolbar QWidget#chartTimeControlsSpacer\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    assert "background-color: transparent;" in match.group("body")


def test_frequency_controls_spacer_has_toolbar_background_rule():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    match = re.search(
        r"QWidget#chartToolbar QWidget#chartFrequencyControlsSpacer\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    assert "background-color: transparent;" in match.group("body")


def test_chart_toolbar_disabled_nav_buttons_have_visible_style():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    assert "QWidget#chartToolbar QToolButton:disabled" in qss
    assert "border: 1px solid #e5eaf2;" in qss


def test_chart_cards_have_chart_options_toolbar_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        assert hasattr(card, '_options_btn')
        assert card._options_btn.objectName() == 'chartOptionsButton'
        assert card._options_btn.toolTip() == '图表选项'
        assert card._options_btn.autoRaise()


def test_chart_cards_have_tick_density_popout_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        assert hasattr(card, "_tick_density_btn")
        assert hasattr(card, "_tick_density_popover")
        assert card._tick_density_btn.objectName() == "chartTickDensityButton"
        assert card._tick_density_btn.text() == ""
        assert not card._tick_density_btn.icon().isNull()
        assert card._tick_density_btn.width() == 32
        assert card._tick_density_btn.focusPolicy() == Qt.NoFocus

        pop = card._tick_density_popover
        assert pop.objectName() == "TickDensityPopover"
        assert pop._PRESETS == {
            "疏": (6, 5),
            "标准": (10, 10),
            "密": (20, 15),
        }
        assert pop._DEFAULT == (20, 15)
        assert pop.density() == (20, 15)
        assert pop._preset_buttons["密"].isChecked()
        assert not pop._preset_buttons["疏"].isChecked()
        assert not pop._preset_buttons["标准"].isChecked()
        assert pop._reset_btn.text() == "恢复默认 20 / 15"
        assert card._tick_density_btn.toolTip() == "刻度密度 X20 / Y15"
        # Checked preset must look activated (blue select chrome), not the
        # muted white pill that used to read as "nothing selected".
        assert pop._preset_buttons["密"].isChecked() is True
        layout = pop._surface.layout()
        assert layout.indexOf(pop._preset_host) < layout.indexOf(pop._x_row)
        assert layout.indexOf(pop._preset_host) < layout.indexOf(pop._y_row)


def test_chart_cards_keep_copy_button_contract(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        assert card._copy_btn.text() == ""
        assert not card._copy_btn.icon().isNull()
        assert card._copy_btn.width() == 32
        assert card._copy_btn.height() == 32
        assert card._copy_btn.toolTip() == "复制为图片（含游标线和读数）"
        with qtbot.waitSignal(card.copy_image_requested, timeout=200):
            card._copy_btn.click()


def test_analysis_tick_density_and_config_precede_save_on_left(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._fft_card, cs._fft_time_card, cs._order_card):
        actions = card.toolbar.actions()
        copy_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._copy_btn
        )
        tick_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._tick_density_btn
        )
        options_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._options_btn
        )
        save_index = next(i for i, act in enumerate(actions) if act.data() == 'save')
        annotation_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._annotation_btn
        )
        clear_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._clear_annotation_btn
        )

        assert annotation_index < clear_index < copy_index
        assert copy_index < tick_index < options_index < save_index


def test_tick_density_popout_preset_emits_and_updates_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs._time_card
    pop = card._tick_density_popover

    with qtbot.waitSignal(card.tick_density_changed, timeout=200) as blocker:
        pop._preset_buttons["密"].click()

    assert blocker.args == [20, 15]
    assert pop.density() == (20, 15)
    assert card._tick_density_btn.text() == ""
    assert card._tick_density_btn.toolTip() == "刻度密度 X20 / Y15"


def test_chart_stack_relays_tick_density_popout_signal(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    with qtbot.waitSignal(cs.tick_density_changed, timeout=200) as blocker:
        cs._order_card._tick_density_popover.set_density(6, 5, emit=True)

    assert blocker.args == [6, 5]


def test_chart_options_toolbar_button_delegates_to_canvas(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    called = []

    def fake_open():
        called.append(True)
        return True

    cs.canvas_fft.open_chart_options_dialog = fake_open
    cs._fft_card._options_btn.click()

    assert called == [True]


def test_pg_analysis_chart_options_buttons_open_axis_dialog(
    qapp, qtbot, monkeypatch,
):
    from mf4_analyzer.ui import _axis_interaction

    cs = ChartStack()
    qtbot.addWidget(cs)
    opened = []

    def fake_edit(parent, handle):
        opened.append((parent, handle))
        return True

    monkeypatch.setattr(
        _axis_interaction, "edit_chart_options_dialog", fake_edit,
        raising=True,
    )

    for card in (cs._fft_card, cs._fft_time_card, cs._order_card):
        card._options_btn.click()

    assert len(opened) == 3
    assert [handle.get_xlabel() for _parent, handle in opened] == [
        "Frequency (Hz)",
        "Time (s)",
        "Time (s)",
    ]


def test_chart_toolbar_removes_native_customize_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        for act in card.toolbar.actions():
            assert (act.text() or '').strip().lower() != 'customize'
            assert 'edit axis, curve and image parameters' not in (
                act.toolTip() or ''
            ).lower()


def test_annotation_toolbar_toggles_canvas_modes(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    seen = []
    cs.annotation_enabled_changed.connect(lambda mode, enabled: seen.append((mode, enabled)))

    cs._time_card._annotation_btn.click()
    assert cs.canvas_time._annotations.enabled is True
    assert cs._time_card._annotation_btn.isChecked()

    cs._fft_card._annotation_btn.click()
    assert cs.canvas_fft._remark_enabled is True
    assert cs._fft_card._annotation_btn.isChecked()

    cs._fft_time_card._annotation_btn.click()
    assert cs.canvas_fft_time._remark_enabled is True
    assert cs._fft_time_card._annotation_btn.isChecked()

    cs._order_card._annotation_btn.click()
    assert cs.canvas_order._remark_enabled is True
    assert cs._order_card._annotation_btn.isChecked()

    cs._frf_card._annotation_btn.click()
    assert cs.canvas_frf._remark_enabled is True
    assert cs._frf_card._annotation_btn.isChecked()

    assert ('time', True) in seen
    assert ('fft', True) in seen
    assert ('fft_time', True) in seen
    assert ('frf', True) in seen
    assert ('order', True) in seen


def test_stats_strip_update(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.stats_strip.update_stats({
        'ch1': {'min': 0, 'max': 10, 'mean': 5, 'rms': 6, 'std': 2, 'p2p': 10, 'unit': 'V'}
    })
    assert 'ch1' in cs.stats_strip._lbl_summary.text()


def test_stats_strip_toggle(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.stats_strip.setVisible(True)
    assert not cs.stats_strip._panel.isVisible()
    cs.stats_strip.toggle()
    qapp.processEvents()
    assert cs.stats_strip._panel.isVisible()


# ---- TimeChartCard (2026-04-24 UI cleanup) ----

def test_chart_stack_exposes_plot_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.plot_mode() == 'subplot'
    with qtbot.waitSignal(cs.plot_mode_changed, timeout=200) as bl:
        cs.set_plot_mode('overlay')
    assert bl.args == ['overlay']
    assert cs.plot_mode() == 'overlay'


def test_chart_stack_exposes_cursor_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default must be 'off' per spec §8
    assert cs.cursor_mode() == 'off'
    with qtbot.waitSignal(cs.cursor_mode_changed, timeout=200) as bl:
        cs.set_cursor_mode('single')
    assert bl.args == ['single']
    assert cs.cursor_mode() == 'single'


def test_time_chart_card_has_segmented_controls(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, TimeChartCard
    cs = ChartStack()
    qtbot.addWidget(cs)
    # The time-domain card keeps the control objects, but its toolbar is now
    # shared above the splitter instead of inside the left pane.
    card = cs._time_card
    assert isinstance(card, TimeChartCard)
    assert card.toolbar is cs._time_toolbar
    assert card.toolbar.parentWidget() is cs._time_page
    # Five segmented buttons on the shared toolbar (post-i18n labels):
    # 分屏 / 叠加 / 游标关 / 单游标 / 双游标
    texts = {b.text() for b in cs._time_toolbar.findChildren(type(card.btn_subplot))}
    assert {'分屏', '叠加', '游标关', '单游标', '双游标'} <= texts


def test_time_toolbar_segment_labels_stay_full_when_narrow(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)

    card = cs._time_card
    card.toolbar.resize(640, max(card.toolbar.height(), 40))
    card._time_toolbar_compact = None
    card._sync_responsive_toolbar()

    buttons = [
        card.btn_subplot,
        card.btn_overlay,
        card._cursor_buttons['off'],
        card._cursor_buttons['single'],
        card._cursor_buttons['dual'],
    ]
    assert [button.text() for button in buttons] == [
        '分屏',
        '叠加',
        '游标关',
        '单游标',
        '双游标',
    ]
    assert all(button.maximumWidth() > 44 for button in buttons)
    assert all(not sep.isHidden() for sep in card._time_separators)


def test_time_chart_card_removes_subplots_config_button(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # The time-domain card now lives inside a QSplitter at stack index 0;
    # reach the real card directly (== cs.stack.widget(0).widget(0)).
    card = cs._time_card
    # No QAction on the native nav toolbar should map to 'configure_subplots'.
    native_tb = card.toolbar
    for act in native_tb.actions():
        # The action object name / icon text varies; check both.
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_fft_card_also_strips_subplots_button(qapp, qtbot):
    """Subplots action is stripped from every card since tight_layout is the default."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # V7: stack.widget(1) is now the FFT AnalysisSectionPage; the card lives at
    # pane 0 (aliased as cs._fft_card).
    fft_card = cs._fft_card
    for act in fft_card.toolbar.actions():
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_set_plot_mode_noop_does_not_emit(qapp, qtbot):
    """set_plot_mode with the current mode should not re-emit."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default is 'subplot'; calling with 'subplot' again should not emit.
    assert cs.plot_mode() == 'subplot'
    # qtbot.waitSignal with timeout=50 and check=[] — use a different approach:
    received = []
    cs.plot_mode_changed.connect(lambda m: received.append(m))
    cs.set_plot_mode('subplot')
    assert received == []
    # sanity: a real change does still emit
    cs.set_plot_mode('overlay')
    assert received == ['overlay']


def test_set_cursor_mode_noop_does_not_emit(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.cursor_mode() == 'off'
    received = []
    cs.cursor_mode_changed.connect(lambda m: received.append(m))
    cs.set_cursor_mode('off')
    assert received == []
    cs.set_cursor_mode('dual')
    assert received == ['dual']


def test_chart_stack_exposes_fft_time_card(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.set_mode('fft_time')

    assert stack.current_mode() == 'fft_time'
    assert stack.canvas_fft_time is not None
    # V7: the stacked widget is the FFT-vs-Time AnalysisSectionPage; the card is
    # pane 0 of that page (cs._fft_time_card).
    assert stack.stack.currentWidget() is stack.page_fft_time
    assert stack._fft_time_card is stack.page_fft_time._cards[0]


# M9 retired the matplotlib SpectrogramCanvas (FFT-vs-Time moved to
# PgHeatmapCanvas with_slice=True). The Task-5/Task-9 rendering, cursor,
# and export-pixmap tests below drove matplotlib internals
# (canvas.fig.axes, _ax_spec.images[0].get_clim(), MouseEvent ->
# canvas._on_motion) on the now-deleted class. Their behaviour is
# covered for the pyqtgraph canvas in tests/ui/test_pg_heatmap_canvas.py
# (slice plot/update, _img.getLevels() == explicit dB window, freq-range
# Y limits, passive hover suppression, grab_full_view/grab_main_chart),
# so they were removed rather than stubbed (see
# pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap).


# ---- Task 2.7: Chinese segmented buttons ----

def test_time_card_segmented_buttons_chinese(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    card = cs._time_card
    assert card.btn_subplot.text() == '分屏'
    assert card.btn_overlay.text() == '叠加'
    assert card._cursor_buttons['off'].text() == '游标关'
    assert card._cursor_buttons['single'].text() == '单游标'
    assert card._cursor_buttons['dual'].text() == '双游标'


# ---- Bottom hint bar (Persistent + Context layers) ----

def test_bottom_hint_bar_anchor_leads_each_section(qapp):
    """The static persistent label is retired; each section's rotating row now
    LEADS with its base-gesture anchor (line sections show the Ctrl/Shift wheel
    anchor, heatmap sections show the slice/colorbar anchor)."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    cs.show()
    qapp.processEvents()
    anchors = {
        "time": "Ctrl / Shift + 滚轮 缩放 X / Y",
        "fft": "Ctrl / Shift + 滚轮 缩放 X / Y",
        "fft_time": "点击谱图取切片 · 拖 colorbar 调色阶",
        "order": "点击谱图取切片 · 拖 colorbar 调色阶",
    }
    for mode, card in (
        ("time", cs._time_card),
        ("fft", cs._fft_card),
        ("fft_time", cs._fft_time_card),
        ("order", cs._order_card),
    ):
        cs.set_mode(mode)
        qapp.processEvents()
        assert card._hint_bar is not None
        assert card._hint_bar.isVisible() is True
        # The retired static persistent label no longer exists.
        assert not hasattr(card, "_hint_persistent")
        # The rotating row's first hint is the section base-gesture anchor.
        pool = card._rotation_candidates()
        assert pool, mode
        assert pool[0].text == anchors[mode], (mode, pool[0].id)


def test_bottom_hint_bar_hugs_left_and_right_edges(qapp):
    """The quickref affordance hugs the LEFT edge, the rotating row follows it,
    and the discovery hint hugs the RIGHT edge."""
    from PyQt5.QtCore import QPoint
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    try:
        cs.resize(900, 520)
        cs.show()
        cs.set_mode("fft")
        qapp.processEvents()
        card = cs._fft_card
        bar = card._hint_bar
        card._hint_context.setText("Ctrl / Shift + 滚轮 缩放 X / Y")
        card._hint_discovery.setText("复制按钮导出带游标读数的图片并标注")
        bar.layout().activate()
        qapp.processEvents()

        # The retired centered group + separator are gone.
        assert not hasattr(card, "_hint_group")
        assert not hasattr(card, "_hint_separator")

        def _bar_left(w):
            return w.mapTo(bar, QPoint(0, 0)).x()

        quickref_left = _bar_left(card._hint_quickref_btn)
        ctx_left = _bar_left(card._hint_context)
        disc_right = _bar_left(card._hint_discovery) + card._hint_discovery.width()
        # The visible help affordance leads the bar; context text follows it.
        assert quickref_left <= 6, quickref_left
        assert ctx_left > quickref_left, (quickref_left, ctx_left)
        assert disc_right >= bar.width() - 6, (disc_right, bar.width())
        # A real gap sits between them (the two are not glued in the middle).
        ctx_right = ctx_left + card._hint_context.width()
        disc_left = _bar_left(card._hint_discovery)
        assert ctx_right <= disc_left, (ctx_right, disc_left)
    finally:
        cs.deleteLater()


def test_bottom_hint_bar_context_stays_left_when_discovery_empty(qapp):
    """When discovery is empty the quickref button stays left and the lone
    rotating row remains immediately after it instead of recentering."""
    from PyQt5.QtCore import QPoint
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    try:
        cs.resize(900, 520)
        cs.show()
        cs.set_mode("fft")
        qapp.processEvents()
        card = cs._fft_card
        card._hint_context.setText("Ctrl / Shift + 滚轮 缩放 X / Y")
        card._hint_discovery.setText("")
        bar = card._hint_bar
        bar.layout().activate()
        qapp.processEvents()

        quickref_left = card._hint_quickref_btn.mapTo(bar, QPoint(0, 0)).x()
        ctx_left = card._hint_context.mapTo(bar, QPoint(0, 0)).x()
        assert quickref_left <= 6, quickref_left
        assert ctx_left > quickref_left, (quickref_left, ctx_left)
    finally:
        cs.deleteLater()


def test_bottom_hint_bar_left_yields_width_right_stays_firm(qapp):
    """Under a narrow bar the LEFT rotating row is the slot that yields width
    (stretch=1, eliding _ElidedLabel) while the RIGHT discovery row is firm
    (stretch=0, a non-shrinking policy) and keeps its full text — so a long left
    hint can never push the right one off the bar.

    Pixel-level eliding can't be asserted under the headless offscreen platform,
    whose font metrics report 0-width for CJK text; we assert the layout
    invariant that *produces* eliding instead, plus that the discovery text is
    preserved in full and stays within the bar."""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QSizePolicy
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    try:
        cs.resize(900, 520)
        cs.show()
        cs.set_mode("fft")
        qapp.processEvents()
        card = cs._fft_card
        bar = card._hint_bar
        long_text = "这是一条很长的轮播提示，用来确认窄窗下左条让位而右条不被挤掉"
        discovery_text = "复制按钮导出带游标读数的图片并标注"
        card._hint_context.setText(long_text)
        card._hint_discovery.setText(discovery_text)
        bar.setFixedWidth(260)
        bar.layout().activate()
        qapp.processEvents()

        lay = bar.layout()
        # The left rotating row owns the stretch (it absorbs the shrink and
        # elides); the right discovery row takes none.
        assert lay.stretch(0) == 0   # quickref button (left affordance)
        assert lay.stretch(1) == 1   # context (left, yields width)
        assert lay.stretch(2) == 0   # discovery (right)
        # The discovery policy never shrinks below its full text, so it is never
        # clipped — the left row yields instead.
        assert card._hint_discovery.sizePolicy().horizontalPolicy() in (
            QSizePolicy.Minimum, QSizePolicy.Fixed,
        )
        # The left row is an eliding label (its width is what yields).
        assert hasattr(card._hint_context, "full_text")
        assert card._hint_context.full_text() == long_text
        # Discovery keeps its full text and stays within the bar at the right.
        assert card._hint_discovery.text() == discovery_text
        disc_left = card._hint_discovery.mapTo(bar, QPoint(0, 0)).x()
        disc_right = disc_left + card._hint_discovery.width()
        assert disc_right <= bar.width() + 1
    finally:
        cs.deleteLater()


def test_bottom_hint_bar_context_subplot_default_comes_from_registry(qapp):
    """Default TimeDomain state is subplot; the rotating row leads with the line
    base-gesture anchor and the subplot wheel tip is next in the lap."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    # full_text(): the rotating row elides for display, so assert the logical value.
    assert card._hint_context.full_text() == "Ctrl / Shift + 滚轮 缩放 X / Y"
    pool_ids = [h.id for h in card._rotation_candidates()]
    assert pool_ids[0] == "anchor.line_wheel"
    assert "subplot.wheel_target" in pool_ids


def test_flash_hint_shows_transient_context_text(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    card = _ChartCard(canvas)
    card.resize(640, 360)
    card.show()
    qapp.processEvents()

    card.flash_hint("先选中一个通道，再用 Shift+滚轮缩放纵向")

    # full_text(): the centered rotating row elides for display (and collapses to
    # '' in a zero-width unshown card), so assert the logical value.
    assert "先选中一个通道" in card._hint_context.full_text()


def test_card_transient_zoom_hint_shows_and_clears(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    card = _ChartCard(canvas, chart_mode="fft")
    card.show()
    qapp.processEvents()

    card.set_transient_zoom_hint(True)
    assert "临时缩放" in card._hint_context.full_text()

    card.set_transient_zoom_hint(False)
    assert "临时缩放" not in card._hint_context.full_text()
    card.deleteLater()


def test_card_wires_canvas_manual_zoom_to_hint(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    card = _ChartCard(canvas, chart_mode="fft")
    card.show()
    qapp.processEvents()

    canvas.manual_zoom_changed.emit(True)
    qapp.processEvents()

    assert "临时缩放" in card._hint_context.full_text()
    card.deleteLater()


def test_overlay_needs_selection_signal_flashes_hint(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    card = _ChartCard(canvas)
    card.show()
    qapp.processEvents()

    canvas.overlay_y_needs_selection.emit()
    qapp.processEvents()

    # full_text(): see test_flash_hint_shows_transient_context_text.
    assert "先选中一个通道" in card._hint_context.full_text()


def test_heatmap_slice_hint_signal_flashes_hint(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    canvas = PgHeatmapCanvas(with_slice=True)
    card = _ChartCard(canvas)
    card.show()
    qapp.processEvents()

    canvas.slice_hint_requested.emit("点击位置超出谱图范围")
    qapp.processEvents()

    assert "点击位置超出谱图范围" in card._hint_context.full_text()
    card.deleteLater()


def test_heatmap_slice_hint_disconnects_when_card_is_deleted(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    canvas = PgHeatmapCanvas(with_slice=True)
    card = _ChartCard(canvas)
    card.show()
    qapp.processEvents()

    card.deleteLater()
    qapp.processEvents()

    canvas.slice_hint_requested.emit("点击位置超出谱图范围")
    canvas.slice_picked.emit()
    canvas.levels_changed.emit(0.0, 1.0)
    qapp.processEvents()

    canvas.deleteLater()


def test_bottom_hint_bar_context_uses_registry(qapp, monkeypatch):
    from mf4_analyzer.ui import hints
    from mf4_analyzer.ui.chart_stack import ChartStack
    from mf4_analyzer.ui.hints import Hint

    cs = ChartStack()
    card = cs._time_card

    # The rotating row now reads the merged anchor+context pool from the
    # registry (hints.rotation_hints); no context strings are hard-coded in
    # the card.
    def fake_rotation_hints(state, scope="chart"):
        assert state.mode == "time"
        assert state.plot_mode == "subplot"
        return (Hint(id="test.registry", text="registry controlled", surface="anchor"),)

    monkeypatch.setattr(hints, "rotation_hints", fake_rotation_hints)
    card._refresh_bottom_hint()

    assert card._hint_context.full_text() == "registry controlled"


def test_bottom_hint_bar_discovery_slot_advances_when_marked(qapp):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.chart_stack import ChartStack

    settings = QSettings(".pytmp/test_hints/chart-stack.ini", QSettings.IniFormat)
    settings.clear()
    cs = ChartStack()
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        card.set_hint_settings(settings)

    card = cs._time_card
    assert card._hint_discovery.text() == "顶部按钮支持快捷键，悬停按钮即可查看"

    card.mark_discovered("toolbar.shortcuts_exist")
    assert card._hint_discovery.text() == "复制按钮导出带游标读数的图片并标注"


def test_copy_button_marks_copy_image_discovered(qapp):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui import hints
    from mf4_analyzer.ui.chart_stack import ChartStack

    settings = QSettings(".pytmp/test_hints/chart-copy.ini", QSettings.IniFormat)
    settings.clear()
    cs = ChartStack()
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        card.set_hint_settings(settings)

    cs._time_card.copy_image_requested.emit()

    assert "chart.copy_image" in hints.load_discovered(settings)


def test_shortcut_action_marks_shortcuts_discovered(qapp):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui import hints
    from mf4_analyzer.ui.chart_stack import ChartStack

    settings = QSettings(".pytmp/test_hints/chart-shortcut.ini", QSettings.IniFormat)
    settings.clear()
    cs = ChartStack()
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        card.set_hint_settings(settings)

    pan_action = next(act for act in cs._time_card.toolbar.actions() if act.data() == "pan")
    pan_action.trigger()

    assert "toolbar.shortcuts_exist" in hints.load_discovered(settings)


def test_context_hint_rotation_advances_and_pause_holds(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    card = cs._time_card

    # Subplot rotation pool: anchor leads, then subplot tips, single lap.
    # full_text(): the rotating row elides for display, assert the logical value.
    assert card._hint_context.full_text() == "Ctrl / Shift + 滚轮 缩放 X / Y"
    card._advance_context_hint()
    assert card._hint_context.full_text() == "滚轮作用于鼠标所在分屏图"
    card._advance_context_hint()
    assert card._hint_context.full_text() == "Shift + 滚轮：缩放鼠标所在分屏图 Y 轴"

    # Paused: an advance is a no-op (the footer freezes during interaction).
    card.set_hint_rotation_paused(True)
    held = card._hint_context.full_text()
    card._advance_context_hint()
    assert card._hint_context.full_text() == held


def test_rotation_timer_uses_variable_dwell(qapp):
    """The single-shot rotation timer re-arms with the CURRENT hint's dwell, not
    a fixed 10s interval."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    from mf4_analyzer.ui import hints

    cs = ChartStack()
    card = cs._time_card
    # The timer is single-shot (variable re-arm), never a fixed repeating timer.
    assert card._hint_rotation_timer.isSingleShot() is True

    # Drive a deterministic refresh so the timer is armed to the lead hint's
    # dwell regardless of any construction-time event-loop timing.
    card.set_hint_rotation_paused(False)
    card._set_context_hint(reset=True)
    pool = card._rotation_candidates()
    lead = pool[0]
    assert card._hint_rotation_timer.isActive() is True
    # Armed interval is exactly the lead hint's variable dwell (anchor = 12000),
    # not the legacy fixed 10000.
    assert card._hint_rotation_timer.interval() == hints.rotation_dwell_ms(lead)
    assert hints.rotation_dwell_ms(lead) == 12000  # anchor.line_wheel dwell
    assert card._hint_rotation_timer.interval() != 10000


def test_mark_context_hint_used_suppresses_it_for_session(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    card = cs._time_card

    card.mark_context_hint_used("subplot.wheel_target")

    # The used tip drops out of the lap; the anchor still leads, and the other
    # subplot tip remains.
    pool_ids = [h.id for h in card._rotation_candidates()]
    assert "subplot.wheel_target" not in pool_ids
    assert pool_ids[0] == "anchor.line_wheel"
    assert "subplot.shift_y" in pool_ids


def test_bottom_hint_bar_context_switches_with_cursor_mode(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card

    def pool_ids():
        return [h.id for h in card._rotation_candidates()]

    # cursor=single currently has no curated bar hint; the anchor still leads.
    card.set_cursor_mode('single')
    assert pool_ids()[0] == "anchor.line_wheel"
    assert "cursor.dual_ab" not in pool_ids()
    # cursor=dual → the dual cursor hint joins the lap (anchor still leads).
    card.set_cursor_mode('dual')
    assert "cursor.dual_ab" in pool_ids()
    # cursor=off → the dual hint leaves the lap.
    card.set_cursor_mode('off')
    assert "cursor.dual_ab" not in pool_ids()


def test_bottom_hint_bar_spectrogram_hint(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    fft_time = cs._fft_time_card
    fft_time._refresh_bottom_hint()
    # The heatmap anchor leads; the slice hint is the next tip in the lap.
    pool_ids = [h.id for h in fft_time._rotation_candidates()]
    assert pool_ids[0] == "anchor.heatmap_gesture"
    assert "spectrogram.slice" in pool_ids


def test_bottom_hint_bar_base_card_anchor_persists_with_no_mode(qapp, tmp_path):
    """Plain _ChartCard (fft) keeps its base-gesture anchor reachable even with
    no toolbar mouse mode — the base gesture is mode-independent and always
    leads the rotation pool. (The lap now *enters* at a persisted round-robin
    start offset so a fresh open isn't always the anchor; pin offset 0 here so
    the deterministic head — the anchor — is what shows.)"""
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui import hints
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._fft_card
    settings = QSettings(str(tmp_path / "hint.ini"), QSettings.IniFormat)
    settings.setValue(hints.ROTATION_START_KEY, 0)  # lead with the pool head
    settings.sync()
    card.set_hint_settings(settings)
    card.toolbar.mode = ''  # type: ignore[attr-defined]
    card._refresh_bottom_hint()
    # Anchor still leads the pool and stays reachable regardless of mouse mode…
    assert card._rotation_candidates()[0].id == "anchor.line_wheel"
    # …and at start offset 0 it is the hint shown.
    assert card._hint_context.full_text() == "Ctrl / Shift + 滚轮 缩放 X / Y"


def test_bottom_hint_bar_constants_exposed():
    """Legacy module constants are now registry-derived compatibility values."""
    from mf4_analyzer.ui.chart_stack import _BOTTOM_HINT_PERSISTENT
    from mf4_analyzer.ui.hints import persistent_hints

    assert _BOTTOM_HINT_PERSISTENT == "    ·    ".join(persistent_hints())


def test_toolbar_hint_removed_but_bottom_hint_bar_stays(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    cs.show()
    qapp.processEvents()
    card = cs._time_card
    toolbar_widgets = [card.toolbar.widgetForAction(act) for act in card.toolbar.actions()]
    assert not any(
        getattr(widget, "objectName", lambda: "")() == "chartHint"
        for widget in toolbar_widgets
        if widget is not None
    )
    assert card._hint_bar is not None
    assert card._hint_bar.isVisible() is True
    # The rotating row is populated (the retired static persistent label is gone).
    # full_text() is the logical value; text() may elide/collapse when centered.
    assert card._hint_context.full_text()
    assert not hasattr(card, "_hint_persistent")


def test_custom_x_dual_rows_route_to_primary_and_clear_on_empty_emit(qapp, qtbot):
    from mf4_analyzer.ui.plot_helpers import DualCursorBranch, DualCursorRow
    from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('dual')
    qapp.processEvents()

    rows = [
        DualCursorRow(
            channel_name="Rack Force",
            min_value=1.0,
            max_value=3.0,
            avg=2.0,
            delta=None,
            unit_suffix=" N",
            color="#1769e0",
            mode=CHANNEL_MODE,
            branches=(
                DualCursorBranch(1, 1.0, 3.0, 2.0),
                DualCursorBranch(-1, 0.0, 2.0, 1.0),
            ),
        )
    ]
    cs.canvas_time.dual_cursor_rows.emit(rows)
    qapp.processEvents()
    assert "X↑" in cs._pill.detail_text()
    assert "△" not in cs._pill.detail_text()

    cs.canvas_time.dual_cursor_rows.emit([])
    qapp.processEvents()
    assert "X↑" not in (cs._pill.detail_text() or "")

    cs.enter_split()
    qapp.processEvents()
    secondary = cs.secondary_canvas()
    assert secondary is not None
    secondary.dual_cursor_rows.emit(rows)
    qapp.processEvents()
    assert cs._pill_secondary is not None
    assert "X↑" in cs._pill_secondary.detail_text()


def test_cursor_display_options_round_trip_and_sync_existing_and_future_panes(
    qapp, qtbot, tmp_path
):
    from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayOptions

    settings = _cursor_settings(tmp_path)
    cs = ChartStack(cursor_settings=settings)
    qtbot.addWidget(cs)
    wanted = CursorDisplayOptions(
        show_max_point=False,
        show_min_point=True,
        show_max_value=False,
        show_min_value=True,
        show_avg_value=False,
    )

    cs._time_card.cursor_display_options_changed.emit(wanted)

    assert cs.cursor_display_options() is wanted
    assert cs._time_card.cursor_display_options() is wanted
    assert cs.canvas_time.cursor_display_options() is wanted
    cs.enter_split()
    secondary = cs.secondary_canvas()
    assert cs._secondary_card.cursor_display_options() is wanted
    assert secondary.cursor_display_options() is wanted

    restored = ChartStack(cursor_settings=settings)
    qtbot.addWidget(restored)
    assert restored.cursor_display_options() == wanted


def test_split_single_cursor_rows_share_options_without_crossing_results(
    qapp, qtbot, tmp_path
):
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        CursorDisplayBranch,
        CursorDisplayChannel,
    )

    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    cs.enter_split()
    secondary = cs.secondary_canvas()
    cs.set_cursor_mode_for_canvas(secondary, "single")
    qapp.processEvents()
    left = (CursorDisplayChannel(
        identity=("left", "force"),
        source_label="left-source",
        channel_label="force",
        branches=(CursorDisplayBranch("X↑", current_value=4.0),),
    ),)
    right = (CursorDisplayChannel(
        identity=("right", "force"),
        source_label="right-source",
        channel_label="force",
        branches=(CursorDisplayBranch("X↓", current_value=104.0),),
    ),)

    cs.canvas_time.single_cursor_rows.emit(left)
    secondary.single_cursor_rows.emit(right)
    qapp.processEvents()

    assert "left-source" in cs._pill.detail_text()
    assert "right-source" not in cs._pill.detail_text()
    assert "right-source" in cs._pill_secondary.detail_text()
    assert "left-source" not in cs._pill_secondary.detail_text()
    assert cs._pill._display_projection.blocks[0].identity == ("left", "force")
    assert cs._pill_secondary._display_projection.blocks[0].identity == (
        "right", "force"
    )


def test_cursor_off_closes_popovers_clears_results_and_keeps_preferences(
    qapp, qtbot, tmp_path
):
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        CursorDisplayChannel,
        CursorDisplayOptions,
    )

    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    wanted = CursorDisplayOptions(show_avg_value=False)
    cs._time_card.cursor_display_options_changed.emit(wanted)
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    cs.canvas_time.single_cursor_rows.emit((CursorDisplayChannel(
        identity=("fid", "speed"),
        source_label="source",
        channel_label="speed",
        current_value=12.0,
    ),))
    cs._time_card.cursor_display_settings_button().click()
    qapp.processEvents()
    assert cs._time_card.cursor_display_popover().isVisible()
    assert cs._pill.isVisible()

    cs.set_cursor_mode("off")
    qapp.processEvents()

    assert not cs._time_card.cursor_display_popover().isVisible()
    assert not cs._pill.isVisible()
    assert cs._pill._display_projection is None
    assert cs.cursor_display_options() is wanted


def test_structured_cursor_pill_stays_in_safe_rect_in_narrow_chart_stack(
    qapp, qtbot, tmp_path
):
    from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayChannel

    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(340, 180)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    channels = tuple(
        CursorDisplayChannel(
            identity=(f"source-{index}", "Speed"),
            source_label=f"long-source-{index}-capture",
            channel_label="Speed",
            current_value=12.5 + index,
            unit_suffix=" rpm",
        )
        for index in range(3)
    )

    cs.canvas_time.single_cursor_rows.emit(channels)
    qapp.processEvents()

    assert cs._pill.safe_rect().contains(cs._pill.geometry())


def _plot_live_custom_x_diagnostic_case(canvas, case):
    from tests._helpers import wwt_factory as wwt

    if case == "ambiguous":
        series = wwt.sfns_like_hysteresis_arrays("two_cycles")
        x = np.asarray(series.x, dtype=float)
        y = np.asarray(series.y, dtype=float)
        single_x = wwt.SFNS_CURSOR_A
        dual_x = (wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    else:
        x = np.linspace(0.0, 10.0, 101)
        y = 2.0 * x + 1.0
        single_x = 20.0 if case == "out_of_range" else 4.0
        dual_x = (20.0, 30.0) if case == "out_of_range" else (2.0, 8.0)
    name = "[source-a] Rack Force"
    canvas.plot_channels(
        [(name, True, x, y, "#1769e0", "N", "fid-a")],
        mode="overlay",
        x_axis_context=SimpleNamespace(
            mode="channel",
            identity=("fid-a", "travel"),
            label="travel",
            unit="mm",
        ),
    )
    if case == "incompatible_shape":
        canvas.channel_data[name] = (x, y[:-1], "#1769e0", "N")
    return single_x, dual_x


@pytest.mark.parametrize("cursor_mode", ("single", "dual"))
@pytest.mark.parametrize("pill_mode", ("full", "mini"))
@pytest.mark.parametrize(
    "case,expected_single,expected_dual",
    (
        ("out_of_range", "当前 X 不在有效路径内", "区间内无数据"),
        ("incompatible_shape", "X/Y 形状不兼容", "X/Y 形状不兼容"),
        ("ambiguous", "无法可靠区分升程/回程", "无法可靠区分升程/回程"),
    ),
)
def test_live_custom_x_diagnostic_survives_legacy_then_structured_projection(
    qapp, qtbot, tmp_path, cursor_mode, pill_mode, case,
    expected_single, expected_dual,
):
    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, cursor_mode)
    if pill_mode == "mini":
        cs._pill._toggle_mode()
    single_x, (ax, bx) = _plot_live_custom_x_diagnostic_case(
        cs.canvas_time, case
    )
    legacy_seen = []
    structured_seen = []
    cs.canvas_time.cursor_info.connect(legacy_seen.append)
    if cursor_mode == "single":
        cs.canvas_time.single_cursor_rows.connect(structured_seen.append)
        cs.canvas_time._emit_single_cursor_html(single_x)
        expected = expected_single
    else:
        cs.canvas_time.dual_cursor_rows.connect(structured_seen.append)
        cs.canvas_time._cursor.ax = ax
        cs.canvas_time._cursor.bx = bx
        cs.canvas_time._emit_dual_cursor_html()
        expected = expected_dual
    qapp.processEvents()

    assert legacy_seen
    assert structured_seen
    assert expected in cs._pill.detail_text()
    assert expected in cs._pill._detail.toolTip()
    assert "fid-a / Rack Force" in cs._pill._detail.toolTip()


def test_direct_canvas_clear_clears_legacy_and_structured_cursor_pill(
    qapp, qtbot, tmp_path
):
    import numpy as np

    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    cs.canvas_time.plot_channels([
        ("speed", True, np.asarray([0.0, 0.5, 1.0]),
         np.asarray([1.0, 2.0, 3.0]), "#1769e0", "rpm", "fid-a"),
    ], mode="overlay")
    cs.canvas_time._emit_single_cursor_html(0.5)
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert "t=0.5000s" in cs._pill.primary_text()
    assert cs._pill.has_detail()

    cs.canvas_time.clear()
    qapp.processEvents()

    assert not cs._pill.isVisible()
    assert cs._pill.primary_text() == ""
    assert not cs._pill.has_detail()


def test_secondary_off_and_split_exit_clear_pills_through_update_seam(
    qapp, qtbot, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayChannel

    cs = ChartStack(cursor_settings=_cursor_settings(tmp_path))
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.enter_split()
    secondary = cs.secondary_canvas()
    cs.set_cursor_mode_for_canvas(secondary, "single")
    channel = CursorDisplayChannel(
        identity=("secondary", "speed"),
        source_label="secondary",
        channel_label="speed",
        current_value=2.0,
    )
    secondary.single_cursor_rows.emit((channel,))
    qapp.processEvents()
    assert cs._pill_secondary.isVisible()

    calls = []
    original = cs._update_pill_content

    def record(pill, card, update):
        calls.append((pill, card))
        return original(pill, card, update)

    monkeypatch.setattr(cs, "_update_pill_content", record)
    cs.set_cursor_mode_for_canvas(secondary, "off")
    qapp.processEvents()
    assert not cs._pill_secondary.isVisible()
    assert any(pill is cs._pill_secondary for pill, _card in calls)

    cs.set_cursor_mode_for_canvas(secondary, "single")
    secondary.single_cursor_rows.emit((channel,))
    qapp.processEvents()
    calls.clear()
    cs.exit_split()

    assert not cs._pill_secondary.isVisible()
    assert any(pill is cs._pill_secondary for pill, _card in calls)
