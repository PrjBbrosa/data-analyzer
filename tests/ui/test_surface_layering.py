from pathlib import Path
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QScrollArea, QStatusBar, QWidget

from mf4_analyzer import app_meta
from mf4_analyzer.ui.pg_canvas._split_mixin import _CollapsedRail
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.side_panels import SidePanelStrip
from mf4_analyzer.ui_kit.control_style import CONTROL_QSS_TOKENS
from mf4_analyzer.ui_kit.icons import render_qss_template


QSS_PATH = Path("mf4_analyzer/ui_kit/style.qss")


def _apply_widget_qss(widget):
    """Apply production QSS only to the visual tree under test.

    Reapplying it to ``QApplication`` late in the full UI suite forces Qt to
    repolish every earlier, unowned widget tree.  These tests render a single
    root widget, so an ancestor stylesheet has the same relevant cascade
    without mutating global application state.
    """
    # ``style.qss`` is a template now.  Keep this test's local-root cascade
    # (rather than repolishing every live qapp widget), but resolve the shared
    # control tokens exactly as the production stylesheet loader does.
    widget.setStyleSheet(render_qss_template(
        QSS_PATH.read_text(encoding="utf-8"), CONTROL_QSS_TOKENS,
    ))
    return widget


def _qss_block(qss, selector):
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
    match = re.search(pattern, qss, flags=re.S)
    assert match is not None, f"missing QSS block for {selector}"
    return match.group("body")


def test_surface_shell_uses_porcelain_tray_and_real_statusbar(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        root = win.centralWidget().layout()
        assert win.centralWidget().objectName() == "centralTray"
        assert root.contentsMargins().left() == 5
        assert root.contentsMargins().top() == 3
        assert root.contentsMargins().bottom() == 5
        assert root.spacing() == 3

        assert win.toolbar.objectName() == "surfaceTopBar"
        assert win.toolbar.minimumHeight() == 44
        assert win.toolbar.maximumHeight() == 44
        assert win._strip_row.geometry().top() == 50

        assert win.navigator.channel_list.objectName() == "channelCard"
        assert win.navigator.channel_list.testAttribute(Qt.WA_StyledBackground)

        assert isinstance(win.statusBar, QStatusBar)
        assert win.statusBar.objectName() == "surfaceStatusBar"
        assert win.statusBar.parentWidget() is win.centralWidget()
        assert win.statusBar.minimumHeight() == 32
        assert win.statusBar.maximumHeight() == 32
        assert win.findChildren(QStatusBar).count(win.statusBar) == 1

        win.statusBar.clearMessage()
        win.statusBar.showMessage("surface ok")
        assert win.statusBar.currentMessage() == "surface ok"
    finally:
        win.setStyleSheet("")


def test_surface_qss_contract_has_porcelain_bars_and_flat_chart_toolbar():
    qss = QSS_PATH.read_text(encoding="utf-8")

    assert "QMainWindow { background-color: #f2f4f7;" in qss
    assert "QWidget#centralTray { background-color: #f2f4f7;" in qss
    assert "Toolbar#surfaceTopBar" in qss
    assert "QStatusBar#surfaceStatusBar" in qss

    match = re.search(
        r"QToolBar#chartToolbar,\s*"
        r"QWidget#chartToolbar\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    toolbar_block = match.group("body")
    assert "background-color: transparent;" in toolbar_block
    assert "border: none;" in toolbar_block
    assert "border-radius" not in toolbar_block

    assert "background-color: #e8ecf2;" not in qss


def test_surface_global_scrollbars_are_slim_and_quiet():
    qss = QSS_PATH.read_text(encoding="utf-8")

    vertical = _qss_block(qss, "QScrollBar:vertical")
    horizontal = _qss_block(qss, "QScrollBar:horizontal")
    vertical_handle = _qss_block(qss, "QScrollBar::handle:vertical")
    horizontal_handle = _qss_block(qss, "QScrollBar::handle:horizontal")
    vertical_hover = _qss_block(qss, "QScrollBar::handle:vertical:hover")
    horizontal_hover = _qss_block(qss, "QScrollBar::handle:horizontal:hover")

    assert "width: 8px;" in vertical
    assert "height: 8px;" in horizontal
    assert "margin: 1px;" in vertical
    assert "margin: 1px;" in horizontal
    assert "border-radius: 4px;" in vertical_handle
    assert "border-radius: 4px;" in horizontal_handle
    assert "background: #d7dee8;" in vertical_handle
    assert "background: #d7dee8;" in horizontal_handle
    assert "background: #aeb9c8;" in vertical_hover
    assert "background: #aeb9c8;" in horizontal_hover


def test_surface_mode_segment_has_no_outer_border():
    qss = QSS_PATH.read_text(encoding="utf-8")
    block = _qss_block(qss, "QWidget#modeSegment")

    assert "border:" not in block
    assert "background-color: transparent;" in block


def test_surface_mode_buttons_use_readable_centered_type():
    qss = QSS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'Toolbar QPushButton\[segment="time"\],\s*'
        r'Toolbar QPushButton\[segment="fft"\],\s*'
        r'Toolbar QPushButton\[segment="fft_time"\],\s*'
        r'Toolbar QPushButton\[segment="frf"\],\s*'
        r'Toolbar QPushButton\[segment="order"\]\s*\{(?P<body>[^}]*)\}',
        qss,
        flags=re.S,
    )
    assert match is not None
    block = match.group("body")

    assert "min-height: 24px;" in block
    assert "font-size: 13px;" in block
    assert "font-weight: 700;" in block


def test_surface_mode_buttons_are_vertically_centered_in_topbar(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        toolbar_center_y = win.toolbar.rect().center().y()
        for button in (
            win.toolbar.btn_mode_time,
            win.toolbar.btn_mode_fft,
            win.toolbar.btn_mode_fft_time,
            win.toolbar.btn_mode_order,
            win.toolbar.btn_mode_frf,
        ):
            button_center = button.mapTo(win.toolbar, button.rect().center()).y()
            assert abs(button_center - toolbar_center_y) <= 1, button.text()
    finally:
        win.setStyleSheet("")


def test_surface_file_area_is_outer_card_aligned_with_channel_card(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        file_area = win.navigator.findChild(QWidget, "fileArea")
        file_scroll = win.navigator.findChild(QScrollArea, "fileScroll")
        channel_card = win.navigator.channel_list
        assert file_area is not None
        assert file_scroll is not None

        assert file_area.testAttribute(Qt.WA_StyledBackground)
        assert file_area.parentWidget() is channel_card.parentWidget()
        assert file_area.geometry().x() == channel_card.geometry().x()
        assert file_area.geometry().width() == channel_card.geometry().width()

        qss = QSS_PATH.read_text(encoding="utf-8")
        file_area_block = _qss_block(qss, "QWidget#fileArea")
        assert "background-color: #ffffff;" in file_area_block
        assert "border: 1px solid #dbe2eb;" in file_area_block
        assert "border-radius: 6px;" in file_area_block

        file_scroll_block = _qss_block(qss, "QScrollArea#fileScroll")
        assert "background-color: transparent;" in file_scroll_block
        assert "border: none;" in file_scroll_block
        assert "border-radius" not in file_scroll_block
    finally:
        win.setStyleSheet("")


def test_surface_collapsed_rails_use_compact_affordance_widths():
    assert SidePanelStrip.WIDTH_PX == 10
    assert _CollapsedRail.HEIGHT_PX == 10


def test_surface_side_panel_strip_is_transparent_host_for_pill():
    qss = QSS_PATH.read_text(encoding="utf-8")

    block = _qss_block(qss, "QFrame#sidePanelStrip")
    hover = _qss_block(qss, "QFrame#sidePanelStrip:hover")
    right = _qss_block(qss, 'QFrame#sidePanelStrip[side="right"]')

    assert "background-color: transparent;" in block
    assert "border: none;" in block
    assert "background-color: transparent;" in hover
    assert "border: none;" in right
    assert "#f3f5f8" not in block
    assert "#e7ecf2" not in hover


def test_surface_qss_uses_compact_radius_scale():
    qss = QSS_PATH.read_text(encoding="utf-8")

    topbar_block = _qss_block(qss, "QWidget#surfaceTopBar")
    status_block = _qss_block(qss, "QStatusBar#surfaceStatusBar")
    file_block = _qss_block(qss, "FileNavigator")
    inspector_block = _qss_block(qss, "Inspector")
    chart_match = re.search(r"ChartStack\s*\{(?P<body>[^}]*)\}", qss, flags=re.S)
    assert chart_match is not None
    chart_block = chart_match.group("body")

    assert "border-radius: 8px;" in topbar_block
    assert "border-radius: 8px;" in status_block
    assert "border-radius: 7px;" in file_block
    assert "border-radius: 7px;" in chart_block
    assert "border-radius: 7px;" in inspector_block

    assert "border-radius: 13px;" not in topbar_block
    assert "border-radius: 13px;" not in status_block
    assert "border-radius: 10px;" not in file_block
    assert "border-radius: 10px;" not in chart_block
    assert "border-radius: 10px;" not in inspector_block


def _render_widget(widget):
    img = QImage(widget.width(), widget.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    widget.render(painter)
    painter.end()
    return img


def _render_widget_at_dpr(widget, dpr: int):
    """Render a real Qt widget at a logical DPR without token-only checks."""
    img = QImage(
        widget.width() * dpr, widget.height() * dpr,
        QImage.Format_ARGB32_Premultiplied,
    )
    img.setDevicePixelRatio(float(dpr))
    img.fill(0)
    painter = QPainter(img)
    widget.render(painter)
    painter.end()
    return img


def _is_visible_border_ink(color: QColor) -> bool:
    """Recognize the anti-aliased blue-grey border against the white fill."""
    return color.alpha() > 200 and min(color.red(), color.green(), color.blue()) < 250


def _assert_continuous_rounded_border_arc(img: QImage, dpr: int) -> None:
    """Verify every corner contains a connected visible inner border profile.

    Checking only the extreme corner alpha misses the real regression: a
    rectangular child can leave that pixel alone while painting white over the
    anti-aliased inner arc.  Six samples cross the arc from each straight edge.
    """
    extent = 9 * dpr
    width = img.width()
    height = img.height()

    def has_ink(points) -> bool:
        return any(_is_visible_border_ink(QColor(img.pixelColor(x, y))) for x, y in points)

    for logical_offset in range(1, 7):
        offset = logical_offset * dpr
        assert has_ink((x, offset) for x in range(extent + 1))
        assert has_ink(
            (width - 1 - x, offset) for x in range(extent + 1)
        )
        assert has_ink(
            (x, height - 1 - offset) for x in range(extent + 1)
        )
        assert has_ink(
            (width - 1 - x, height - 1 - offset)
            for x in range(extent + 1)
        )

    assert has_ink(((width // 2, 0),))
    assert has_ink(((width // 2, height - 1),))
    assert has_ink(((0, height // 2),))
    assert has_ink(((width - 1, height // 2),))


def _corner_alphas(widget):
    img = _render_widget(widget)
    w = img.width() - 1
    h = img.height() - 1
    return [
        QColor(img.pixelColor(0, 0)).alpha(),
        QColor(img.pixelColor(w, 0)).alpha(),
        QColor(img.pixelColor(0, h)).alpha(),
        QColor(img.pixelColor(w, h)).alpha(),
    ]


def _has_opaque_white_body(widget):
    img = _render_widget(widget)
    w = img.width() - 1
    h = img.height() - 1
    points = [
        (min(8, w), min(8, h)),
        (max(0, w - 8), min(8, h)),
        (img.width() // 2, img.height() // 2),
        (img.width() // 3, img.height() // 3),
        ((img.width() * 2) // 3, (img.height() * 2) // 3),
    ]
    for x, y in points:
        color = QColor(img.pixelColor(x, y))
        if (
            color.alpha() > 240
            and color.red() > 245
            and color.green() > 245
            and color.blue() > 245
        ):
            return True
    return False


def test_batch_inline_file_manager_keeps_rounded_border_arcs_with_real_children(
    qapp, qtbot,
):
    """The inline body/list viewport must never overpaint the parent arc."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = _apply_widget_qss(InputPanel())
    try:
        qtbot.addWidget(panel)
        panel.resize(360, 700)
        panel.show()
        qtbot.wait(20)

        for row_count in (0, 4, 8):
            while panel._file_list._list.count() < row_count:
                index = panel._file_list._list.count()
                panel._file_list.add_loaded_file(
                    f"source-{index}", f"/tmp/source-{index}.mf4", frozenset({"A"}),
                )
            qapp.processEvents()
            if row_count == 8:
                assert (
                    panel._file_list._list.verticalScrollBar().maximum()
                    > panel._file_list._list.verticalScrollBar().minimum()
                )
                panel._file_list._list.verticalScrollBar().setValue(
                    panel._file_list._list.verticalScrollBar().maximum()
                )
                qapp.processEvents()

            host = panel._file_manager_host
            assert host.height() == 250
            for dpr in (1, 2):
                image = _render_widget_at_dpr(host, dpr)
                _assert_continuous_rounded_border_arc(image, dpr)
                center = QColor(image.pixelColor(
                    image.width() // 2, image.height() // 2,
                ))
                assert center.alpha() > 245
                assert min(center.red(), center.green(), center.blue()) > 245
    finally:
        panel.setStyleSheet("")


def test_surface_version_affordance_is_transparent_icon_text(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        btn = win._update_btn
        assert btn.objectName() == "surfaceVersionButton"
        assert btn.autoRaise()
        assert btn.text() == app_meta.APP_VERSION
        assert btn.styleSheet() == ""

        qss = QSS_PATH.read_text(encoding="utf-8")
        block = _qss_block(qss, "QStatusBar#surfaceStatusBar QToolButton#surfaceVersionButton")
        assert "background-color: transparent;" in block
        assert "border: none;" in block
        assert "border-radius: 5px;" in block

        btn_rect = btn.geometry()
        bar_rect = win.statusBar.rect()
        assert bar_rect.right() - btn_rect.right() >= 4
        assert bar_rect.bottom() - btn_rect.bottom() >= 2
    finally:
        win.setStyleSheet("")


def test_surface_panel_children_leave_outer_shell_visible(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        nav_margins = win.navigator.layout().contentsMargins()
        assert nav_margins.left() >= 3
        assert nav_margins.right() >= 3
        assert nav_margins.bottom() >= 3

        inspector_margins = win.inspector.layout().contentsMargins()
        assert inspector_margins.left() >= 3
        assert inspector_margins.right() >= 3
        assert inspector_margins.bottom() >= 3

        scroll = win.inspector.findChild(type(win.inspector._scroll), "inspectorScroll")
        assert scroll is win.inspector._scroll
        assert not scroll.autoFillBackground()
        assert not scroll.viewport().autoFillBackground()
    finally:
        win.setStyleSheet("")


def test_surface_top_bottom_and_panels_render_rounded_corners(qapp, qtbot):
    win = _apply_widget_qss(MainWindow())
    try:
        qtbot.addWidget(win)
        win.resize(1450, 850)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        for widget in (
            win.toolbar,
            win.statusBar,
            win.navigator,
            win.chart_stack,
            win.inspector,
        ):
            alphas = _corner_alphas(widget)
            label = widget.objectName() or type(widget).__name__
            assert max(alphas) < 12, f"{label} has opaque corner pixels: {alphas}"
            assert _has_opaque_white_body(widget), f"{label} lost its opaque body"
    finally:
        win.setStyleSheet("")
