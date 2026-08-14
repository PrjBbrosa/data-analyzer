"""Contracts for the UltraView View-rail dock chip and measured compact fit."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPalette
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from mf4_analyzer.ui.widgets.ultraview_entry import (
    ACCESSIBLE_NAME,
    COMPACT_WIDTH,
    EDITED_TOOLTIP,
    ENTRY_HEIGHT,
    LABEL_TEXT,
    PORTAL_SIZE,
    SEPARATOR_HEIGHT,
    SPECTRUM_STOPS,
    TILE_COLORS,
    TOOLTIP,
    UltraViewEntryButton,
    UltraViewRailFitter,
    dock_compact_required,
    make_ultraview_separator,
)

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "widgets"
    / "ultraview_entry.py"
)
_HOST_FILL = "#7A9B6A"
_WHITE = "#FFFFFF"
_RAIL = "#FBFCFF"
_MAGENTA = "#BD299F"


def _srgb_linear(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: str) -> float:
    parsed = QColor(color)
    return (
        0.2126 * _srgb_linear(parsed.red())
        + 0.7152 * _srgb_linear(parsed.green())
        + 0.0722 * _srgb_linear(parsed.blue())
    )


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _channel_distance(actual: QColor, expected: QColor) -> int:
    return max(
        abs(actual.red() - expected.red()),
        abs(actual.green() - expected.green()),
        abs(actual.blue() - expected.blue()),
    )


def _make_button(qtbot, *, compact: bool = False) -> UltraViewEntryButton:
    button = UltraViewEntryButton()
    button.set_compact(compact)
    qtbot.addWidget(button)
    button.resize(button.sizeHint())
    button.show()
    qtbot.waitExposed(button)
    QApplication.processEvents()
    return button


def _imported_module_names(source: str) -> list[str]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_entry_height_is_at_most_view_rail() -> None:
    from mf4_analyzer.ui.view_tabbar import RAIL_HEIGHT

    button = UltraViewEntryButton()
    assert button.sizeHint().height() == ENTRY_HEIGHT == RAIL_HEIGHT
    assert button.minimumSizeHint().height() <= RAIL_HEIGHT
    button.set_compact(True)
    assert button.sizeHint().height() == ENTRY_HEIGHT


def test_full_mode_is_wider_than_compact_and_shows_brand_label(qtbot) -> None:
    button = _make_button(qtbot)
    assert button.is_compact() is False
    full = button.sizeHint()
    button.set_compact(True)
    compact = button.sizeHint()
    assert button.is_compact() is True
    assert full.width() > compact.width()
    assert full.height() == compact.height() == ENTRY_HEIGHT
    assert compact.width() == COMPACT_WIDTH
    assert compact.width() < full.width()
    button.set_compact(False)
    assert button.is_compact() is False
    assert button.sizeHint().width() == full.width()


def test_portal_is_smaller_than_plus_and_vertically_centered(qtbot) -> None:
    button = _make_button(qtbot)
    portal = button._portal_rect()
    assert PORTAL_SIZE == 20
    assert portal.height() == PORTAL_SIZE
    # ViewTabBar "+" is 22px; the portal sits 1px below geometric mid so the
    # rail hairlines (not the widget box) are the visual anchors.
    assert portal.height() <= 22
    geometric = (float(button.height()) - float(PORTAL_SIZE)) / 2.0
    assert portal.y() == pytest.approx(geometric + 1.0)
    assert portal.y() >= 3.0
    button.set_compact(True)
    button.resize(button.sizeHint())
    compact = button._portal_rect()
    assert compact.height() == PORTAL_SIZE
    assert abs(compact.center().x() - button.width() / 2.0) <= 0.51
    assert compact.y() == pytest.approx(geometric + 1.0)


def test_compact_keeps_accessible_name_and_tooltip(qtbot) -> None:
    button = _make_button(qtbot)
    assert button.accessibleName() == ACCESSIBLE_NAME
    assert button.toolTip() == TOOLTIP
    button.set_compact(True)
    assert button.is_compact() is True
    assert button.accessibleName() == ACCESSIBLE_NAME
    assert button.toolTip() == TOOLTIP
    assert button.objectName() == "ultraViewEntry"
    assert button.isCheckable() is False


def test_content_marker_changes_tooltip_without_changing_rail_size(qtbot) -> None:
    button = _make_button(qtbot)
    before = button.sizeHint()

    button.set_has_content(True)

    assert button.has_content() is True
    assert button.toolTip() == EDITED_TOOLTIP
    assert button.sizeHint() == before
    button.set_has_content(False)
    assert button.has_content() is False
    assert button.toolTip() == TOOLTIP


def test_content_marker_renders_as_a_visible_green_dot(qtbot) -> None:
    button = _make_button(qtbot)
    button.set_has_content(True)
    QApplication.processEvents()

    center = button._edited_dot_rect(button._portal_rect()).center()
    pixel = button.grab().toImage().pixelColor(int(center.x()), int(center.y()))
    assert _channel_distance(pixel, QColor("#18A861")) <= 8


def test_mouse_space_and_enter_each_emit_clicked_once(qtbot) -> None:
    button = _make_button(qtbot)
    spy = QSignalSpy(button.clicked)

    qtbot.mouseClick(button, Qt.LeftButton)
    assert len(spy) == 1

    button.setFocus()
    qtbot.keyClick(button, Qt.Key_Space)
    assert len(spy) == 2

    button.setFocus()
    qtbot.keyClick(button, Qt.Key_Return)
    assert len(spy) == 3

    button.setFocus()
    qtbot.keyClick(button, Qt.Key_Enter)
    assert len(spy) == 4


@pytest.mark.parametrize("stop", SPECTRUM_STOPS)
@pytest.mark.parametrize("background", (_WHITE, _RAIL))
def test_spectrum_stops_meet_wcag_contrast(stop, background) -> None:
    _position, color = stop
    assert _contrast_ratio(color, background) >= 4.5


def test_grab_contains_spectrum_and_keeps_quiet_chrome(qtbot) -> None:
    host = QWidget()
    host.setObjectName("ultraViewEntryHost")
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.Window, QColor(_HOST_FILL))
    host.setPalette(palette)
    host.setStyleSheet(f"background-color: {_HOST_FILL};")
    row = QHBoxLayout(host)
    row.setContentsMargins(16, 16, 16, 16)
    row.setSpacing(0)
    button = UltraViewEntryButton()
    button.set_compact(False)
    row.addWidget(button, 0, Qt.AlignVCenter)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    QApplication.processEvents()
    button.resize(button.sizeHint())
    host.adjustSize()
    QApplication.processEvents()

    pixmap = host.grab()
    assert pixmap.devicePixelRatio() == pytest.approx(1.0)
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    origin = button.mapTo(host, button.rect().topLeft())
    dpr = int(round(pixmap.devicePixelRatio()))
    gx = origin.x() * dpr
    gy = origin.y() * dpr
    gw = button.width() * dpr
    gh = button.height() * dpr

    def pixel(x: int, y: int) -> QColor:
        return QColor(image.pixelColor(x, y))

    found = {color: False for _stop, color in SPECTRUM_STOPS}
    magenta_hits = 0
    sampled = 0
    for y in range(gy, gy + gh):
        for x in range(gx, gx + gw):
            color = pixel(x, y)
            sampled += 1
            if _channel_distance(color, QColor(_MAGENTA)) <= 36:
                magenta_hits += 1
            for hex_color, already in list(found.items()):
                if already:
                    continue
                if _channel_distance(color, QColor(hex_color)) <= 48:
                    found[hex_color] = True
    assert sampled > 0
    missing = [color for color, ok in found.items() if not ok]
    assert not missing, f"spectrum neighborhood missing {missing!r}"
    assert magenta_hits / sampled < 0.28, (
        "background/border must not be flooded with magenta; "
        f"got {magenta_hits}/{sampled}"
    )

    pad = pixel(gx + 3 * dpr, gy + gh // 2)
    assert _channel_distance(pad, QColor(_MAGENTA)) > 80

    host_fill = QColor(_HOST_FILL)
    white = QColor(_WHITE)
    for lx, ly in (
        (0, 0),
        (button.width() - 1, 0),
        (0, button.height() - 1),
        (button.width() - 1, button.height() - 1),
    ):
        corner = pixel(gx + lx * dpr, gy + ly * dpr)
        assert _channel_distance(corner, host_fill) <= 24, corner.name()
        assert _channel_distance(corner, host_fill) < _channel_distance(corner, white)


def _grab_entry_on_host(qtbot, *, compact: bool = False):
    host = QWidget()
    host.setObjectName("ultraViewEntryHost")
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.Window, QColor(_HOST_FILL))
    host.setPalette(palette)
    host.setStyleSheet(f"background-color: {_HOST_FILL};")
    row = QHBoxLayout(host)
    row.setContentsMargins(16, 16, 16, 16)
    row.setSpacing(0)
    button = UltraViewEntryButton()
    button.set_compact(compact)
    row.addWidget(button, 0, Qt.AlignVCenter)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    QApplication.processEvents()
    button.resize(button.sizeHint())
    host.adjustSize()
    QApplication.processEvents()
    pixmap = host.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    origin = button.mapTo(host, button.rect().topLeft())
    dpr = int(round(pixmap.devicePixelRatio()))
    return host, button, image, origin, dpr


def _pixel(image: QImage, x: int, y: int) -> QColor:
    return QColor(image.pixelColor(x, y))


def test_portal_mark_matches_option_a_board_not_capsule(qtbot) -> None:
    host, button, image, origin, dpr = _grab_entry_on_host(qtbot)
    assert dpr == 1
    gx = origin.x() * dpr
    gy = origin.y() * dpr
    gw = button.width() * dpr
    gh = button.height() * dpr
    host_fill = QColor(_HOST_FILL)
    portal_rect = button._portal_rect()
    portal = int(round(portal_rect.width() * dpr))
    pad = int(round(portal_rect.x() * dpr))

    blue_hits: list[tuple[int, int]] = []
    violet_hits: list[tuple[int, int]] = []
    magenta_hits: list[tuple[int, int]] = []
    for y in range(gy, gy + gh):
        for x in range(gx, gx + pad + portal):
            color = _pixel(image, x, y)
            if _channel_distance(color, QColor(TILE_COLORS[0])) <= 36:
                blue_hits.append((x, y))
            elif _channel_distance(color, QColor(TILE_COLORS[1])) <= 36:
                violet_hits.append((x, y))
            elif _channel_distance(color, QColor(TILE_COLORS[3])) <= 36:
                magenta_hits.append((x, y))
    assert blue_hits and violet_hits and magenta_hits

    def _centroid(hits: list[tuple[int, int]]) -> tuple[float, float]:
        return (
            sum(x for x, _y in hits) / len(hits),
            sum(y for _x, y in hits) / len(hits),
        )

    blue_c = _centroid(blue_hits)
    magenta_c = _centroid(magenta_hits)
    assert blue_c[0] < magenta_c[0]
    assert blue_c[1] < magenta_c[1]
    assert any(x > blue_c[0] and y < magenta_c[1] for x, y in violet_hits)
    assert any(x < magenta_c[0] and y > blue_c[1] for x, y in violet_hits)

    portal_center = _pixel(image, gx + pad + portal // 2, gy + gh // 2)
    assert _channel_distance(portal_center, host_fill) > 8
    assert _channel_distance(portal_center, QColor(TILE_COLORS[0])) > 60
    assert _channel_distance(portal_center, QColor(TILE_COLORS[3])) > 60

    gap = _pixel(image, gx + pad + portal + 3 * dpr, gy + gh // 2)
    assert _channel_distance(gap, host_fill) <= 28
    right_edge = _pixel(image, gx + gw - 1, gy + gh // 2)
    assert _channel_distance(right_edge, host_fill) <= 24
    left_edge = _pixel(image, gx, gy + gh // 2)
    assert _channel_distance(left_edge, host_fill) <= 24

    underline_hits = 0
    scanned = 0
    band_top = gy + int(gh * 0.72)
    for y in range(band_top, gy + gh):
        for x in range(gx + pad + portal, gx + gw):
            scanned += 1
            color = _pixel(image, x, y)
            if _channel_distance(color, host_fill) < 12:
                continue
            # Rest-state underline is 54% opaque over the rail; require a
            # chromatic stroke, not a match to the raw spectrum hex.
            if color.blue() > color.green() or color.red() > color.green():
                underline_hits += 1
    assert scanned > 0
    assert underline_hits >= 8, f"wordmark underline missing: {underline_hits}/{scanned}"

    del host


def test_compact_portal_keeps_quad_and_drops_wordmark(qtbot) -> None:
    host, button, image, origin, dpr = _grab_entry_on_host(qtbot, compact=True)
    assert button.width() == COMPACT_WIDTH
    gx = origin.x() * dpr
    gy = origin.y() * dpr
    gw = button.width() * dpr
    gh = button.height() * dpr
    found = {color: False for color in TILE_COLORS}
    for y in range(gy, gy + gh):
        for x in range(gx, gx + gw):
            color = _pixel(image, x, y)
            for hex_color, already in list(found.items()):
                if already:
                    continue
                if _channel_distance(color, QColor(hex_color)) <= 36:
                    found[hex_color] = True
    assert all(found.values()), found
    host_fill = QColor(_HOST_FILL)
    for lx, ly in ((0, 0), (button.width() - 1, 0)):
        corner = _pixel(image, gx + lx * dpr, gy + ly * dpr)
        assert _channel_distance(corner, host_fill) <= 24
    del host


def test_mouse_focus_does_not_draw_capsule_ring(qtbot) -> None:
    host, button, image, origin, dpr = _grab_entry_on_host(qtbot)
    gx = origin.x() * dpr
    gy = origin.y() * dpr
    gw = button.width() * dpr
    host_fill = QColor(_HOST_FILL)
    top_center = (gx + gw // 2, gy + 2 * dpr)

    button.clearFocus()
    QApplication.processEvents()
    button.setFocus(Qt.MouseFocusReason)
    QApplication.processEvents()
    image = host.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    mouse_ring = _pixel(image, *top_center)
    mouse_corner = _pixel(image, gx, gy)
    assert _channel_distance(mouse_corner, host_fill) <= 24
    assert _channel_distance(mouse_ring, host_fill) <= 24

    button.clearFocus()
    QApplication.processEvents()
    button.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    image = host.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    tab_ring = _pixel(image, *top_center)
    assert _channel_distance(tab_ring, host_fill) > 12
    del host


def test_transparent_render_has_no_square_backing(qtbot) -> None:
    button = _make_button(qtbot)
    image = QImage(button.width(), button.height(), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(1.0)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.render(painter)
    painter.end()
    corners = [
        QColor(image.pixelColor(0, 0)).alpha(),
        QColor(image.pixelColor(image.width() - 1, 0)).alpha(),
        QColor(image.pixelColor(0, image.height() - 1)).alpha(),
        QColor(image.pixelColor(image.width() - 1, image.height() - 1)).alpha(),
    ]
    assert max(corners) <= 8, corners


def test_separator_is_quiet_hairline(qtbot) -> None:
    host = QWidget()
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.Window, QColor(_HOST_FILL))
    host.setPalette(palette)
    host.setStyleSheet(f"background-color: {_HOST_FILL};")
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    sep = make_ultraview_separator(host)
    row.addWidget(sep, 0, Qt.AlignVCenter)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    QApplication.processEvents()
    host.adjustSize()
    QApplication.processEvents()

    assert sep.objectName() == "ultraViewEntrySeparator"
    assert sep.width() == 1
    assert sep.height() == SEPARATOR_HEIGHT
    assert sep.minimumSize() == QSize(1, SEPARATOR_HEIGHT)
    assert "border:" not in (sep.styleSheet() or "")

    pixmap = host.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    origin = sep.mapTo(host, sep.rect().topLeft())
    dpr = int(round(pixmap.devicePixelRatio()))
    mid = _pixel(
        image,
        origin.x() * dpr,
        origin.y() * dpr + (sep.height() * dpr) // 2,
    )
    # Global QFrame { background:#fff } must not win; the dock hairline
    # has to stay a gray rule on the rail, as in the Option A mock.
    assert _channel_distance(mid, QColor(_WHITE)) > 40
    assert _channel_distance(mid, QColor(_HOST_FILL)) > 40


def test_dock_compact_required_uses_intrinsic_hints_not_window_width() -> None:
    source = inspect.getsource(dock_compact_required)
    assert "760" not in source
    assert "1100" not in source
    assert "520" not in source
    assert "583" not in source
    assert "if width" not in source
    full_required = 80 + 40 + 8 + 6
    assert (
        dock_compact_required(
            available_width=full_required,
            non_dock_minimum=80,
            full_dock_hint=40,
            compact_dock_hint=22,
            margins=8,
            spacing=6,
        )
        is False
    )
    assert (
        dock_compact_required(
            available_width=full_required - 1,
            non_dock_minimum=80,
            full_dock_hint=40,
            compact_dock_hint=22,
            margins=8,
            spacing=6,
        )
        is True
    )
    # Hysteresis is a small extra on the same intrinsic full_required, not a
    # window breakpoint: stay compact until the host recovers the deadband.
    assert (
        dock_compact_required(
            available_width=full_required + 3,
            non_dock_minimum=80,
            full_dock_hint=40,
            compact_dock_hint=22,
            margins=8,
            spacing=6,
            hysteresis=4,
            currently_compact=True,
        )
        is True
    )
    assert (
        dock_compact_required(
            available_width=full_required + 4,
            non_dock_minimum=80,
            full_dock_hint=40,
            compact_dock_hint=22,
            margins=8,
            spacing=6,
            hysteresis=4,
            currently_compact=True,
        )
        is False
    )


def test_dock_compact_source_has_no_window_breakpoint_literals() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    for banned in ("width < 760", "width < 520", "available_width < 760", "< 1100"):
        assert banned not in source


class _StretchBar(QWidget):
    """Host-row stand-in with a stable minimum, optional refresh_fit hook."""

    def __init__(self, minimum_width: int, parent=None):
        super().__init__(parent)
        self._minimum_width = int(minimum_width)
        self.fit_calls = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(ENTRY_HEIGHT)
        self.setMinimumWidth(self._minimum_width)

    def sizeHint(self):
        return QSize(self._minimum_width, ENTRY_HEIGHT)

    def minimumSizeHint(self):
        return QSize(self._minimum_width, ENTRY_HEIGHT)

    def refresh_fit(self) -> None:
        self.fit_calls += 1


def _measured_full_required(host, bar, extra, sep, entry) -> int:
    layout = host.layout()
    margins = layout.contentsMargins()
    visible = [widget for widget in (bar, extra, sep, entry) if not widget.isHidden()]
    spacing = max(0, len(visible) - 1) * layout.spacing()
    non_dock = bar.minimumSizeHint().width()
    if extra is not None and not extra.isHidden():
        non_dock += extra.sizeHint().width()
    was_compact = entry.is_compact()
    entry.set_compact(False)
    full_dock = sep.sizeHint().width() + entry.sizeHint().width()
    entry.set_compact(was_compact)
    return non_dock + full_dock + margins.left() + margins.right() + spacing


def test_rail_fitter_shrinks_to_compact_and_restores_full(qtbot) -> None:
    host = QWidget()
    host.setObjectName("ultraViewRailHost")
    layout = QHBoxLayout(host)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(6)
    bar = _StretchBar(160, host)
    extra = QPushButton("联动缩放", host)
    extra.setFixedSize(72, 22)
    sep = make_ultraview_separator(host)
    entry = UltraViewEntryButton(host)
    layout.addWidget(bar, 1)
    layout.addWidget(extra, 0)
    layout.addWidget(sep, 0, Qt.AlignVCenter)
    layout.addWidget(entry, 0, Qt.AlignVCenter)
    qtbot.addWidget(host)

    fitter = UltraViewRailFitter(host, bar, entry, extra_widgets=(extra,))
    required = _measured_full_required(host, bar, extra, sep, entry)
    wide = required + 48
    narrow = required - 12

    host.resize(wide, 40)
    host.show()
    qtbot.waitExposed(host)
    fitter.schedule()
    qtbot.waitUntil(lambda: entry.is_compact() is False, timeout=2000)
    assert entry.is_compact() is False
    fits_before = bar.fit_calls

    host.resize(narrow, 40)
    fitter.schedule()
    qtbot.waitUntil(lambda: entry.is_compact() is True, timeout=2000)
    assert entry.is_compact() is True
    assert bar.fit_calls >= fits_before

    host.resize(wide, 40)
    fitter.schedule()
    qtbot.waitUntil(lambda: entry.is_compact() is False, timeout=2000)
    assert entry.is_compact() is False


def test_entry_module_does_not_import_window_or_numeric_owners() -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    assert "mf4_analyzer.ui.main_window" not in imported
    assert "mf4_analyzer.ui.chart_stack" not in imported
    assert "mf4_analyzer.signal" not in imported
    assert not any(name == "numpy" or name.startswith("numpy.") for name in imported)
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "MainWindow" not in names
    imported_blob = " ".join(imported)
    assert "ultraview_coordinator" not in imported_blob
    assert "chart_stack" not in imported_blob


def test_visual_states_paint_without_raising(qtbot) -> None:
    button = _make_button(qtbot)
    QApplication.sendEvent(button, QEvent(QEvent.Enter))
    QApplication.processEvents()
    button.grab()
    QTest.mousePress(button, Qt.LeftButton)
    QApplication.processEvents()
    button.grab()
    QTest.mouseRelease(button, Qt.LeftButton)
    button.setFocus()
    QApplication.processEvents()
    button.grab()
    button.setEnabled(False)
    QApplication.processEvents()
    button.grab()
    button.setEnabled(True)
    QApplication.sendEvent(button, QEvent(QEvent.Leave))
    QApplication.processEvents()
    button.grab()
