"""Owner tests for the searchable recent-open popup."""
from __future__ import annotations

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHeaderView,
    QLabel,
    QTableView,
    QWidget,
)

from mf4_analyzer.ui.recent_files import RecentEntry, RecentFilesStore
from mf4_analyzer.ui.widgets.recent_open_popup import (
    RECENT_NAME_COLUMN_RATIO,
    RECENT_POPUP_MAX_WIDTH,
    RECENT_POPUP_ROW_HEIGHT,
    RECENT_POPUP_TARGET_HEIGHT,
    RecentOpenPopup,
)
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, POLICY_REDUCED
from mf4_analyzer.ui_kit.popup_shell import POPUP_SHELL_FLAGS


def _entry(path, kind="file", opened_at="2026-09-04T12:00:00"):
    return RecentEntry(path=str(path), kind=kind, opened_at=opened_at)


def _make_popup(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(80, 80, 160, 40)
    host.show()
    qtbot.waitExposed(host)
    popup = RecentOpenPopup()
    qtbot.addWidget(popup)
    return host, popup


def _large_screen(_anchor):
    return QRect(0, 0, 1600, 1100)


def test_recent_open_popup_shell_is_single_transient_instance(qtbot):
    host, popup = _make_popup(qtbot)
    assert popup.objectName() == "recentOpenPopup"
    assert popup.testAttribute(Qt.WA_TranslucentBackground)
    assert popup.testAttribute(Qt.WA_NoSystemBackground)
    assert popup.windowFlags() & Qt.Popup
    assert (popup.windowFlags() & POPUP_SHELL_FLAGS) == POPUP_SHELL_FLAGS
    assert popup.findChild(QTableView, "recentOpenTable") is not None
    assert host is not None


def test_popup_geometry_fits_thirteen_full_rows(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    entries = []
    for i in range(20):
        path = tmp_path / f"run_{i:02d}.mf4"
        path.write_text("x", encoding="utf-8")
        entries.append(_entry(path))
    popup.populate(entries)
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert abs(popup.width() - RECENT_POPUP_MAX_WIDTH) <= 1
    assert abs(popup.height() - RECENT_POPUP_TARGET_HEIGHT) <= 1
    table = popup.findChild(QTableView, "recentOpenTable")
    header = popup.findChild(QHeaderView, "recentOpenHeader")
    assert header.height() == 32
    assert table.rowHeight(0) == RECENT_POPUP_ROW_HEIGHT
    assert table.viewport().height() >= 13 * RECENT_POPUP_ROW_HEIGHT
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert table.horizontalScrollBar().maximum() == 0
    name_w = table.columnWidth(0)
    path_w = table.columnWidth(1)
    total = name_w + path_w
    assert total > 0
    assert abs(name_w - round(total * RECENT_NAME_COLUMN_RATIO)) <= 2
    assert name_w >= 260
    assert path_w >= 300
    popup.close()


def test_popup_clamps_to_narrow_short_and_negative_screens(qtbot, monkeypatch):
    host, popup = _make_popup(qtbot)
    popup.populate((_entry("/tmp/a.mf4"),))

    monkeypatch.setattr(
        RecentOpenPopup,
        "_available_geometry_for",
        staticmethod(lambda anchor: QRect(0, 0, 500, 360)),
    )
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert popup.width() <= 500 - 16
    assert popup.height() <= 360 - 16
    assert popup.geometry().left() >= 8
    popup.close()

    monkeypatch.setattr(
        RecentOpenPopup,
        "_available_geometry_for",
        staticmethod(lambda anchor: QRect(-1920, 40, 1440, 800)),
    )
    popup.show_at(host)
    qtbot.waitExposed(popup)
    avail = QRect(-1920, 40, 1440, 800)
    geom = popup.frameGeometry()
    assert geom.left() >= avail.left() + 8
    assert geom.right() <= avail.right() - 8
    assert geom.top() >= avail.top() + 8
    assert geom.bottom() <= avail.bottom() - 8
    popup.close()


def test_filename_and_path_are_independent_columns(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    path = tmp_path / "whole ±250deg_LowFri.MF4"
    path.write_text("x", encoding="utf-8")
    popup.populate((_entry(path),))
    popup.show_at(host)
    qtbot.waitExposed(popup)
    table = popup.findChild(QTableView, "recentOpenTable")
    model = table.model()
    assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "文件名"
    assert model.headerData(1, Qt.Horizontal, Qt.DisplayRole) == "所在位置"
    assert model.data(model.index(0, 0), Qt.DisplayRole) == path.name
    assert str(tmp_path) in str(model.data(model.index(0, 1), Qt.DisplayRole))
    assert "  ·  " not in str(model.data(model.index(0, 0), Qt.DisplayRole))
    pix = table.viewport().grab()
    divider_x = table.columnWidth(0)
    hit = False
    for y in range(8, min(36, pix.height())):
        color = pix.toImage().pixelColor(min(divider_x, pix.width() - 1), y)
        if color.red() < 250 or color.green() < 250 or color.blue() < 250:
            hit = True
            break
    assert hit, "column divider must be painted in the table viewport"
    popup.close()


def test_search_count_highlight_missing_empty_and_clear(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    present = tmp_path / "whole ±250deg_LowFri.MF4"
    present.write_text("x", encoding="utf-8")
    missing = tmp_path / "gone.mf4"
    popup.populate((
        _entry(present),
        _entry(missing),
        _entry(tmp_path / "P166_demo.tlproj", "project"),
    ))
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    count = popup.findChild(QWidget, "recentOpenCount")
    assert "3 条记录" in count.text()
    assert popup._header._sort_hint == "最近优先"

    popup._search.setText("lowfri")
    assert "1 / 3 条匹配" in count.text()
    assert popup._header._sort_hint == "按匹配度排序"
    assert popup._matches[0].name_spans

    popup._search.setText("zz-no-match")
    assert popup.findChild(QWidget, "recentOpenEmptyTitle").text() == "没有匹配项"
    assert popup.findChild(QWidget, "recentOpenEmpty").isVisible()

    popup._search.clear()
    opened = []
    popup.open_requested.connect(opened.append)
    table = popup.findChild(QTableView, "recentOpenTable")
    table.clicked.emit(table.model().index(1, 0))
    assert opened == []

    cleared = []
    popup.clear_requested.connect(lambda: cleared.append("clear"))
    popup.findChild(QWidget, "recentOpenClear").click()
    assert cleared == ["clear"]
    popup.populate(())
    assert popup.findChild(QWidget, "recentOpenEmptyTitle").text() == "暂无最近记录"
    assert not popup.findChild(QWidget, "recentOpenClear").isEnabled()
    popup.close()


def test_empty_state_copy_does_not_overlap_title(qtbot, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    popup.populate(())
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    title = popup.findChild(QLabel, "recentOpenEmptyTitle")
    copy = popup.findChild(QLabel, "recentOpenEmptyCopy")
    assert title.isVisible()
    assert copy.isVisible()
    assert title.text() == "暂无最近记录"
    assert copy.text() == "打开文件或项目后，会显示在这里。"
    assert not title.wordWrap()
    assert not copy.wordWrap()
    assert not title.geometry().intersects(copy.geometry()), (
        f"empty-state labels overlap: title={title.geometry()} copy={copy.geometry()}"
    )
    assert copy.height() >= copy.fontMetrics().height()
    assert title.height() >= title.fontMetrics().height()
    popup.close()


def test_long_name_and_path_elide_in_own_columns(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    folder = tmp_path
    for part in (
        "Downloads", "data analyzer", "testdoc", "LPD02T08_0526",
        "very-long-session-name-for-elide",
    ):
        folder = folder / part
    folder.mkdir(parents=True)
    name = "260417-ripple-PK2C-电机加热-对比复测-endurance-validation.hdf"
    path = folder / name
    path.write_text("x", encoding="utf-8")
    popup.populate((_entry(path),))
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    table = popup.findChild(QTableView, "recentOpenTable")
    model = table.model()
    assert model.data(model.index(0, 0), Qt.DisplayRole) == name
    tooltip = model.data(model.index(0, 0), Qt.ToolTipRole)
    assert str(path) in str(tooltip)
    name_font = QFont(table.font())
    name_font.setPixelSize(13)
    name_font.setBold(True)
    path_font = QFont(table.font())
    path_font.setPixelSize(12)
    name_px = QFontMetrics(name_font).horizontalAdvance(name)
    path_text = str(model.data(model.index(0, 1), Qt.DisplayRole))
    path_px = QFontMetrics(path_font).horizontalAdvance(path_text)
    assert name_px + 40 > table.columnWidth(0)
    assert path_px + 18 > table.columnWidth(1)
    assert table.horizontalScrollBar().maximum() == 0
    popup.close()


def test_keyboard_mouse_escape_and_lifecycle(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    first = tmp_path / "a.mf4"
    second = tmp_path / "b.mf4"
    first.write_text("x", encoding="utf-8")
    second.write_text("x", encoding="utf-8")
    popup.populate((_entry(first), _entry(second)))
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert popup._search.hasFocus()
    qtbot.keyClicks(popup._search, "b")
    assert popup._search.hasFocus()
    assert popup._search.text() == "b"

    popup._search.clear()
    opened = []
    popup.open_requested.connect(opened.append)
    qtbot.keyClick(popup._search, Qt.Key_Down)
    qtbot.keyClick(popup._search, Qt.Key_Return)
    assert opened == [str(second)]
    assert not popup.isVisible()

    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    qtbot.keyClicks(popup._search, "a")
    qtbot.keyClick(popup._search, Qt.Key_Escape)
    assert popup._search.text() == ""
    assert popup.isVisible()
    qtbot.keyClick(popup._search, Qt.Key_Escape)
    assert not popup.isVisible()

    table = popup.findChild(QTableView, "recentOpenTable")
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    opened.clear()
    index = table.model().index(0, 0)
    table.clicked.emit(index)
    table.clicked.emit(index)
    assert opened == [str(first)]


def test_exists_probe_happens_once_per_snapshot(qtbot, tmp_path, monkeypatch):
    host, popup = _make_popup(qtbot)
    path = tmp_path / "run.mf4"
    path.write_text("x", encoding="utf-8")
    entries = (_entry(path),)
    calls = {"n": 0}
    original = RecentFilesStore.exists

    def counting_exists(entry):
        calls["n"] += 1
        return original(entry)

    monkeypatch.setattr(RecentFilesStore, "exists", staticmethod(counting_exists))
    popup.populate(entries)
    first = calls["n"]
    assert first == 1
    popup._search.setText("run")
    popup._search.setText("r")
    popup.populate(entries)
    assert calls["n"] == first


def test_twenty_reopen_cycles_do_not_grow_instances(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(80, 80, 160, 40)
    host.show()
    qtbot.waitExposed(host)
    popup = RecentOpenPopup(host)
    path = tmp_path / "run.mf4"
    path.write_text("x", encoding="utf-8")
    popup.populate((_entry(path),))
    before_children = len(host.findChildren(RecentOpenPopup))
    before_top = sum(
        1 for widget in QApplication.topLevelWidgets()
        if isinstance(widget, RecentOpenPopup)
    )
    closed = []
    popup.closed.connect(lambda: closed.append("c"))
    for _ in range(20):
        popup.reset_for_show()
        popup.show_at(host)
        QApplication.processEvents()
        popup.close()
        QApplication.processEvents()
    assert len(host.findChildren(RecentOpenPopup)) == before_children
    after_top = sum(
        1 for widget in QApplication.topLevelWidgets()
        if isinstance(widget, RecentOpenPopup)
    )
    assert after_top == before_top
    assert len(closed) == 20
    assert len(host.findChildren(RecentOpenPopup)) == 1


@pytest.mark.parametrize("work", [(640, 360), (480, 320), (300, 240)])
def test_recent_popup_frame_stays_inside_compact_work_area(qapp, qtbot, monkeypatch, work):
    from mf4_analyzer.ui_kit.dialog_geometry import SCREEN_MARGIN

    width, height = work
    host, popup = _make_popup(qtbot)
    popup.populate([
        _entry("/very/long/path/to/steering_torque.mf4"),
        _entry("/tmp/project.tlproj", kind="project"),
    ])
    popup.reset_for_show()

    def _avail(_anchor):
        return QRect(0, 0, width, height)

    monkeypatch.setattr(
        RecentOpenPopup, "_available_geometry_for", staticmethod(_avail),
    )
    popup.show_at(host)
    qtbot.waitExposed(popup)
    qapp.processEvents()
    frame = popup.frameGeometry()
    assert frame.width() <= width - 2 * SCREEN_MARGIN
    assert frame.height() <= height - 2 * SCREEN_MARGIN
    assert frame.left() >= SCREEN_MARGIN
    assert frame.top() >= SCREEN_MARGIN
    assert frame.right() <= width - SCREEN_MARGIN
    assert frame.bottom() <= height - SCREEN_MARGIN


def test_first_show_at_clears_the_anchor_like_the_second_show(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen),
    )
    host, popup = _make_popup(qtbot)
    popup.populate((_entry("/tmp/steering_torque.mf4"),))
    popup.reset_for_show()
    assert popup.windowHandle() is None

    popup.show_at(host)
    qtbot.waitExposed(popup)
    qapp.processEvents()
    first = QRect(popup.frameGeometry())
    anchor = QRect(host.mapToGlobal(QPoint(0, 0)), host.size())
    assert first.top() >= anchor.top() + anchor.height()
    popup.close()
    qapp.processEvents()

    popup.show_at(host)
    qtbot.waitExposed(popup)
    qapp.processEvents()
    second = popup.frameGeometry()
    assert abs(second.top() - first.top()) <= 1
    assert abs(second.left() - first.left()) <= 1
    popup.close()


def _populate_two(popup, tmp_path):
    first = tmp_path / "a.mf4"
    second = tmp_path / "b.mf4"
    first.write_text("x", encoding="utf-8")
    second.write_text("x", encoding="utf-8")
    popup.populate((_entry(first), _entry(second)))
    return first, second


def _show_light(qtbot, monkeypatch, popup, host):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    popup.set_motion_policy(POLICY_LIGHT)
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    return popup._enter_driver


def test_motion_defaults_off_and_does_not_attach_effect(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    _populate_two(popup, tmp_path)
    assert popup.motion_policy() == POLICY_OFF
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert popup._search.hasFocus()
    assert popup._enter_driver is None or not popup._enter_driver.is_active()
    assert popup._surface.graphicsEffect() is None
    assert popup.enter_opacity_supported()
    opened, closed = [], []
    popup.open_requested.connect(opened.append)
    popup.closed.connect(lambda: closed.append("c"))
    qtbot.keyClick(popup._search, Qt.Key_Return)
    assert opened == [str(tmp_path / "a.mf4")]
    assert closed == ["c"]
    assert not popup.isVisible()


def test_enter_opacity_typing_and_internal_click(qtbot, tmp_path, monkeypatch):
    host, popup = _make_popup(qtbot)
    first, second = _populate_two(popup, tmp_path)
    driver = _show_light(qtbot, monkeypatch, popup, host)
    assert popup._search.hasFocus()
    assert driver is not None and driver.is_active()
    assert driver.current() == pytest.approx(0.0)
    driver.clock().setCurrentTime(35)
    mid = float(driver.current())
    assert 0.0 < mid < 1.0
    assert popup._enter_effect is not None
    assert popup._enter_effect.opacity() == pytest.approx(mid)

    qtbot.keyClicks(popup._search, "b")
    assert not driver.is_active()
    assert driver.current() == pytest.approx(1.0)
    assert popup._search.text() == "b"
    assert popup.isVisible()
    assert popup._search.hasFocus()

    popup._search.clear()
    popup.set_motion_policy(POLICY_LIGHT)
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    driver = popup._enter_driver
    driver.clock().setCurrentTime(40)
    opened, closed = [], []
    popup.open_requested.connect(opened.append)
    popup.closed.connect(lambda: closed.append("c"))
    table = popup.findChild(QTableView, "recentOpenTable")
    index = table.model().index(0, 0)
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualRect(index).center())
    assert opened == [str(first)]
    assert closed == ["c"]
    assert not popup.isVisible()
    assert not driver.is_active()
    assert second is not None


def test_enter_escape_outside_click_signals_and_reopen(qtbot, tmp_path, monkeypatch):
    host, popup = _make_popup(qtbot)
    first, _second = _populate_two(popup, tmp_path)
    driver = _show_light(qtbot, monkeypatch, popup, host)
    driver.clock().setCurrentTime(35)
    qtbot.keyClicks(popup._search, "a")
    assert popup._search.text() == "a"
    qtbot.keyClick(popup._search, Qt.Key_Escape)
    assert popup._search.text() == ""
    assert popup.isVisible()
    qtbot.keyClick(popup._search, Qt.Key_Escape)
    assert not popup.isVisible()
    assert not driver.is_active()

    opened, cleared, closed = [], [], []
    popup.open_requested.connect(opened.append)
    popup.clear_requested.connect(lambda: cleared.append("clear"))
    popup.closed.connect(lambda: closed.append("c"))

    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    driver = popup._enter_driver
    driver.clock().setCurrentTime(140)
    assert not driver.is_active()
    assert driver.current() == pytest.approx(1.0)
    assert popup.isVisible()
    assert closed == []
    assert opened == []

    # Qt.Popup dismisses an outside press by close/hide. Offscreen cannot grab,
    # so drive that same immediate path here.
    popup.close()
    QApplication.processEvents()
    assert not popup.isVisible()
    assert closed == ["c"]
    assert not driver.is_active()

    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    driver = popup._enter_driver
    assert driver.is_active()
    assert driver.current() == pytest.approx(0.0)
    assert popup.isVisible()
    driver.clock().setCurrentTime(50)
    popup.close()
    assert closed == ["c", "c"]

    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert popup.isVisible()
    assert popup._enter_driver.is_active()
    popup.findChild(QWidget, "recentOpenClear").click()
    assert cleared == ["clear"]
    assert popup.isVisible()
    popup.close()
    assert opened == []
    assert first is not None


def test_enter_parent_destroy_and_resize_snap(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(80, 80, 160, 40)
    host.show()
    qtbot.waitExposed(host)
    popup = RecentOpenPopup(host)
    _populate_two(popup, tmp_path)
    popup.set_motion_policy(POLICY_LIGHT)
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    driver = popup._enter_driver
    driver.clock().setCurrentTime(40)
    assert driver.is_active()
    host.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    assert sip.isdeleted(host)

    host2, popup2 = _make_popup(qtbot)
    _populate_two(popup2, tmp_path)
    driver2 = _show_light(qtbot, monkeypatch, popup2, host2)
    shown = popup2.geometry()
    driver2.clock().setCurrentTime(35)
    assert driver2.is_active()
    popup2.setFixedSize(popup2.width() - 40, popup2.height() - 40)
    QApplication.processEvents()
    assert not driver2.is_active()
    assert driver2.current() == pytest.approx(1.0)
    assert popup2.frameGeometry().width() <= shown.width()
    popup2.close()


def test_enter_skips_when_effect_blocked_or_unsupported(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(RecentOpenPopup, "_available_geometry_for", staticmethod(_large_screen))
    host, popup = _make_popup(qtbot)
    _populate_two(popup, tmp_path)
    blocker = QGraphicsOpacityEffect(popup._surface)
    blocker.setOpacity(0.8)
    popup._surface.setGraphicsEffect(blocker)
    popup.set_motion_policy(POLICY_LIGHT)
    popup.reset_for_show()
    popup.show_at(host)
    qtbot.waitExposed(popup)
    assert popup.enter_opacity_supported() is False
    assert popup._surface.graphicsEffect() is blocker
    assert blocker.opacity() == pytest.approx(0.8)
    assert popup._enter_driver is None or not popup._enter_driver.is_active()
    assert popup.isVisible()
    assert popup._search.hasFocus()
    popup.close()

    host2, popup2 = _make_popup(qtbot)
    _populate_two(popup2, tmp_path)
    monkeypatch.setattr(
        RecentOpenPopup, "_opacity_effect_supported", lambda self, host: False,
    )
    popup2.set_motion_policy(POLICY_LIGHT)
    popup2.reset_for_show()
    popup2.show_at(host2)
    qtbot.waitExposed(popup2)
    assert popup2.enter_opacity_supported() is False
    assert popup2._surface.graphicsEffect() is None
    assert popup2._enter_driver is None or not popup2._enter_driver.is_active()
    assert popup2.isVisible()
    popup2.set_motion_policy(POLICY_REDUCED)
    assert not popup2.motion_policy().interpolates()
    popup2.close()
