"""Characterization tests for the TimeDomainCanvasPG render/export chain.

These pin pixel-content behavior before later decomposition phases touch the
renderer path. They intentionally assert visible content instead of only
non-null geometry.
"""

from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QColor, QImage

pytest.importorskip("pyqtgraph")


@pytest.fixture
def pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    yield canvas
    canvas.close()
    canvas.deleteLater()
    QCoreApplication.processEvents()


def _rows(*specs):
    """Return rows sharing one 2000-point time base."""
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    rows = []
    for index, (name, color) in enumerate(specs):
        sig = 1000.0 * np.sin(2 * np.pi * (3 + index) * t)
        rows.append((name, True, t, sig, color, "u", "fid-1"))
    return rows


def _to_rgb(pix):
    return pix.toImage().convertToFormat(QImage.Format_RGB32)


def _nonwhite_count(pix, near_white=245, stride=3):
    img = _to_rgb(pix)
    count = 0
    for y in range(0, img.height(), stride):
        for x in range(0, img.width(), stride):
            color = img.pixelColor(x, y)
            if (
                color.red() < near_white
                or color.green() < near_white
                or color.blue() < near_white
            ):
                count += 1
    return count


def _color_present(pix, hex_color, tol=70, stride=1):
    target = QColor(hex_color)
    img = _to_rgb(pix)
    for y in range(0, img.height(), stride):
        for x in range(0, img.width(), stride):
            color = img.pixelColor(x, y)
            if (
                abs(color.red() - target.red()) <= tol
                and abs(color.green() - target.green()) <= tol
                and abs(color.blue() - target.blue()) <= tol
            ):
                return True
    return False


class TestExportPixelCharacterization:
    def test_single_channel_export_is_not_blank(self, pg_canvas):
        pg_canvas.plot_channels(_rows(("speed", "#1769e0")))
        QCoreApplication.processEvents()

        pix = pg_canvas.grab_pixmap()

        assert not pix.isNull()
        assert _nonwhite_count(pix) > 200, "export looks blank"

    def test_empty_canvas_export_is_safe(self, pg_canvas):
        pix = pg_canvas.grab_pixmap()

        assert pix is not None and not pix.isNull()
        assert pix.width() >= 1 and pix.height() >= 1

    def test_overlay_each_curve_color_is_visible(self, pg_canvas):
        pg_canvas.plot_channels(
            _rows(("a", "#1769e0"), ("b", "#ef4444")),
            mode="overlay",
        )
        QCoreApplication.processEvents()

        pix = pg_canvas.grab_pixmap()

        assert _color_present(pix, "#1769e0"), "blue curve missing from export"
        assert _color_present(pix, "#ef4444"), "red curve missing from export"

    def test_2x_export_is_not_blank_and_doubles_geometry(self, pg_canvas):
        pg_canvas.plot_channels(_rows(("speed", "#1769e0")))
        QCoreApplication.processEvents()

        one = pg_canvas.grab_pixmap(scale=1.0)
        two = pg_canvas.grab_pixmap(scale=2.0)

        assert _nonwhite_count(two) > 200, "2x export looks blank"
        assert two.width() >= one.width() * 2 - 4

    def test_export_after_setxlim_is_not_blank(self, pg_canvas):
        pg_canvas.plot_channels(_rows(("speed", "#1769e0")))
        pg_canvas.set_xlim(0.2, 0.7)
        pg_canvas._flush_pending_refresh()
        QCoreApplication.processEvents()

        pix = pg_canvas.grab_pixmap()

        assert _nonwhite_count(pix) > 100, "export blank after xlim refresh"


class TestCollaboratorStateOwnership:
    def test_annotation_state_lives_on_annotation_manager(self, pg_canvas):
        annotations = pg_canvas._annotations

        assert annotations.remarks == []
        assert annotations.enabled is False
        assert annotations.press_pos is None
        assert annotations.press_dragged is False
        for name in (
            "_remarks",
            "_annotation_enabled",
            "_annotation_press_pos",
            "_annotation_press_dragged",
        ):
            assert name not in pg_canvas.__dict__

    def test_idle_quality_state_lives_on_quality_manager(self, pg_canvas):
        quality = pg_canvas._quality

        assert quality.timer.isSingleShot()
        assert quality.timer.interval() == 150
        assert quality.aa_on is False
        assert quality.density_allowed is False
        assert quality.density_seeded is False
        for name in (
            "_idle_aa_timer",
            "_idle_aa_on",
            "_idle_aa_density_allowed",
            "_idle_aa_density_seeded",
        ):
            assert name not in pg_canvas.__dict__

    def test_tick_density_state_lives_on_tick_density_controller(self, pg_canvas):
        from mf4_analyzer.ui.chart_defaults import DEFAULT_CHART_TICK_DENSITY

        controller = pg_canvas._tick_density_controller

        # C6: controller seeds from the product default (20, 15), not a
        # collaborator-local (10, 10) literal.
        assert controller.density == DEFAULT_CHART_TICK_DENSITY
        assert "_tick_density" not in pg_canvas.__dict__

    def test_cursor_state_lives_on_cursor_controller(self, pg_canvas):
        cursor = pg_canvas._cursor

        assert cursor.visible is False
        assert cursor.dual is False
        assert cursor.ax is None
        assert cursor.bx is None
        assert cursor.placing == "A"
        assert cursor.last_t == 0
        assert cursor.line_items == []
        assert cursor.a_items == []
        assert cursor.b_items == []
        assert cursor.extreme_markers == []
        for name in (
            "_cursor_visible",
            "_dual",
            "_ax",
            "_bx",
            "_placing",
            "_last_t",
            "_cursor_line_items",
            "_cursor_a_items",
            "_cursor_b_items",
            "_dual_cursor_extreme_markers",
        ):
            assert name not in pg_canvas.__dict__

    def test_overlay_state_lives_on_overlay_axis_manager(self, pg_canvas):
        from mf4_analyzer.ui.chart_defaults import DEFAULT_CHART_TICK_DENSITY

        overlay = pg_canvas._overlay_axes

        assert overlay.selected_channel is None
        assert overlay.drag_start is None
        assert overlay.dragging is False
        assert overlay.snap_anim is None
        assert overlay.snap_anim_ms == 150
        assert overlay.aux_viewboxes == []
        assert overlay.aux_axes == []
        assert overlay.view_sync_connections == []
        assert overlay.divisions == DEFAULT_CHART_TICK_DENSITY[1]
        assert overlay.grid_lines == []
        assert overlay.default_lw == 1.5
        assert overlay.default_alpha == 1.0
        assert overlay.selected_lw == 2.6
        assert overlay.selected_alpha == 1.0
        assert overlay.de_emphasised_lw == 1.35
        assert overlay.de_emphasised_alpha == 0.42
        assert overlay.pick_radius_px == 12.0
        assert overlay.axis_column_spacing == 12
        for name in (
            "_selected_overlay_channel",
            "_overlay_y_drag_start",
            "_overlay_dragging",
            "_snap_anim",
            "_snap_anim_ms",
            "_overlay_aux_viewboxes",
            "_overlay_aux_axes",
            "_overlay_view_sync_conns",
            "_overlay_divisions",
            "_overlay_grid_lines",
            "_overlay_default_lw",
            "_overlay_default_alpha",
            "_overlay_selected_lw",
            "_overlay_selected_alpha",
            "_overlay_de_emphasised_lw",
            "_overlay_de_emphasised_alpha",
            "_overlay_pick_radius_px",
            "_overlay_axis_column_spacing",
        ):
            assert name not in pg_canvas.__dict__
