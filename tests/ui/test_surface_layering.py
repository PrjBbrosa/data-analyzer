from pathlib import Path
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QStatusBar

from mf4_analyzer.ui.main_window import MainWindow


QSS_PATH = Path("mf4_analyzer/ui_kit/style.qss")


def _apply_app_qss(qapp):
    old = qapp.styleSheet()
    qapp.setStyleSheet(QSS_PATH.read_text(encoding="utf-8"))
    return old


def _qss_block(qss, selector):
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
    match = re.search(pattern, qss, flags=re.S)
    assert match is not None, f"missing QSS block for {selector}"
    return match.group("body")


def test_surface_shell_uses_porcelain_tray_and_real_statusbar(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        root = win.centralWidget().layout()
        assert win.centralWidget().objectName() == "centralTray"
        assert root.contentsMargins().left() == 5
        assert root.contentsMargins().top() == 5
        assert root.spacing() == 5

        assert win.toolbar.objectName() == "surfaceTopBar"
        assert win.toolbar.minimumHeight() == 50
        assert win.toolbar.maximumHeight() == 50

        assert win.navigator.channel_list.objectName() == "channelCard"
        assert win.navigator.channel_list.testAttribute(Qt.WA_StyledBackground)

        assert isinstance(win.statusBar, QStatusBar)
        assert win.statusBar.objectName() == "surfaceStatusBar"
        assert win.statusBar.parentWidget() is win.centralWidget()
        assert win.statusBar.minimumHeight() == 40
        assert win.statusBar.maximumHeight() == 40
        assert win.findChildren(QStatusBar).count(win.statusBar) == 1

        win.statusBar.clearMessage()
        win.statusBar.showMessage("surface ok")
        assert win.statusBar.currentMessage() == "surface ok"
    finally:
        qapp.setStyleSheet(old)


def test_surface_qss_contract_has_porcelain_bars_and_flat_chart_toolbar():
    qss = QSS_PATH.read_text(encoding="utf-8")

    assert "QMainWindow { background-color: #f2f4f7;" in qss
    assert "QWidget#centralTray { background-color: #f2f4f7;" in qss
    assert "Toolbar#surfaceTopBar" in qss
    assert "QStatusBar#surfaceStatusBar" in qss

    match = re.search(
        r"QToolBar#chartToolbar,\s*"
        r"QWidget#chartToolbar,\s*"
        r"NavigationToolbar2QT#chartToolbar,\s*"
        r"NavigationToolbar2QT\s*\{(?P<body>[^}]*)\}",
        qss,
        flags=re.S,
    )
    assert match is not None
    toolbar_block = match.group("body")
    assert "background-color: transparent;" in toolbar_block
    assert "border: none;" in toolbar_block
    assert "border-radius" not in toolbar_block

    assert "background-color: #e8ecf2;" not in qss


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


def _corner_alphas(widget):
    img = QImage(widget.width(), widget.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    painter = QPainter(img)
    widget.render(painter)
    painter.end()
    w = img.width() - 1
    h = img.height() - 1
    return [
        QColor(img.pixelColor(0, 0)).alpha(),
        QColor(img.pixelColor(w, 0)).alpha(),
        QColor(img.pixelColor(0, h)).alpha(),
        QColor(img.pixelColor(w, h)).alpha(),
    ]


def test_surface_version_affordance_is_transparent_icon_text(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)
        qapp.processEvents()

        btn = win._update_btn
        assert btn.objectName() == "surfaceVersionButton"
        assert btn.autoRaise()
        assert btn.text() == "v7.0"
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
        qapp.setStyleSheet(old)


def test_surface_panel_children_leave_outer_shell_visible(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
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
        qapp.setStyleSheet(old)


def test_surface_top_bottom_and_panels_render_rounded_corners(qapp, qtbot):
    old = _apply_app_qss(qapp)
    try:
        win = MainWindow()
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
    finally:
        qapp.setStyleSheet(old)
