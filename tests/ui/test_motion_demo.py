"""Host and S07 contracts for the native interaction-motion demo."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel, QLineEdit, QPushButton

from mf4_analyzer.ui.view_tabbar import ViewTabBar
from mf4_analyzer.ui.widgets.pill_switch import PillSwitch
from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice

from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, POLICY_REDUCED
from mf4_analyzer.ui_kit.motion import duration_ms

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = REPO_ROOT / "mf4_analyzer" / "ui" / "motion_demo.py"


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _advance(driver, ms: int) -> None:
    driver.clock().setCurrentTime(int(ms))


@pytest.fixture
def restore_stylesheet(qapp):
    previous = qapp.styleSheet()
    previous_style = qapp.style().objectName()
    try:
        yield previous
    finally:
        qapp.setStyleSheet(previous)
        if qapp.style().objectName() != previous_style:
            qapp.setStyle(previous_style)
        assert qapp.styleSheet() == previous


@pytest.fixture
def demo_window(qtbot):
    from mf4_analyzer.ui.motion_demo import MotionDemoWindow

    window = MotionDemoWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def _live_widget_cpp_ids():
    from PyQt5 import sip
    from PyQt5.QtCore import QEvent

    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    ids = set()
    for widget in QApplication.allWidgets():
        if sip.isdeleted(widget):
            continue
        ids.add(sip.unwrapinstance(widget))
    return ids


def test_import_has_no_app_window_or_qss_side_effects(qapp, restore_stylesheet):
    before_sheet = qapp.styleSheet()
    before_widgets = _live_widget_cpp_ids()
    module = importlib.import_module("mf4_analyzer.ui.motion_demo")
    module = importlib.reload(module)

    assert module._APP_BOOTSTRAPPED is False
    assert QApplication.instance() is qapp
    assert qapp.styleSheet() == before_sheet
    created = _live_widget_cpp_ids() - before_widgets
    assert created == set()

    source = DEMO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "QApplication",
        "MotionDemoWindow",
        "LightPageSample",
        "load_stylesheet",
        "apply_demo_chrome",
        "setup_chinese_font",
        "install_isolated_qsettings",
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                assert _call_name(child) not in forbidden


def test_demo_source_has_no_page_snapshot_cache():
    source = DEMO_PATH.read_text(encoding="utf-8")
    assert "QPixmap" not in source
    assert ".grab(" not in source
    assert "grab_pixmap" not in source


def test_two_arg_and_native_settings_stay_in_temp_dir(tmp_path):
    from mf4_analyzer.ui import motion_demo

    settings_dir = tmp_path / "demo-settings"
    canary = f"motion-demo-{tmp_path.name}"
    motion_demo.install_isolated_qsettings(settings_dir)
    try:
        assert motion_demo.verify_settings_isolated(settings_dir)
        two = QSettings("MF4Analyzer", "DataAnalyzer")
        two.setValue("isolation_probe", canary)
        two.sync()
        two_path = Path(str(two.fileName())).resolve()
        assert two_path.is_relative_to(settings_dir.resolve())

        native = QSettings(
            QSettings.NativeFormat,
            QSettings.UserScope,
            "MF4Analyzer",
            "DataAnalyzer",
        )
        native.setValue("isolation_probe_native", canary)
        native.sync()
        native_path = Path(str(native.fileName())).resolve()
        assert native_path.is_relative_to(settings_dir.resolve())
        written = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in settings_dir.rglob("*")
            if path.is_file()
        )
        assert canary in written
    finally:
        motion_demo.restore_isolated_qsettings()


def test_apply_demo_chrome_restores_stylesheet(qapp, restore_stylesheet):
    from mf4_analyzer.ui.motion_demo import apply_demo_chrome

    previous = qapp.styleSheet()
    apply_demo_chrome(qapp)
    assert qapp.styleSheet()
    qapp.setStyleSheet(previous)
    assert qapp.styleSheet() == previous


def test_placeholders_and_toolbar_exist(demo_window):
    for sample_id in ("S01", "S02", "S03", "S04", "S05", "S06"):
        widget = demo_window.findChild(QGroupBox, f"motionSample{sample_id}")
        assert widget is not None, sample_id
    assert demo_window.findChild(QPushButton, "motionPolicyOff") is not None
    assert demo_window.findChild(QPushButton, "motionPolicyLight") is not None
    assert demo_window.findChild(QPushButton, "motionPolicyReduced") is not None
    assert demo_window.findChild(QPushButton, "motionDemoReset") is not None
    assert demo_window.sample_s07.objectName() == "motionSampleS07"
    assert "轻量页面示例" in demo_window.sample_s07.title_label.text()
    size = demo_window.sample_s07.viewport.size()
    assert size.width() <= 640
    assert size.height() <= 420


def test_policy_switch_snaps_and_does_not_emit_sample_business(demo_window):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    s07.request_page("b")
    _advance(s07.driver, 40)
    assert s07.driver.is_active()
    assert s07.signal_count == 1
    mid = s07.displayed_opacity()
    assert 0.0 < mid < 1.0

    demo_window._policy_reduced.click()
    assert demo_window.motion_policy() == POLICY_REDUCED
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)
    assert s07.current_page_id == "b"
    assert s07.signal_count == 1
    assert "sample_id=host" in demo_window.log_text()
    assert "signals=0" in demo_window.log_text()

    s07.request_page("a")
    assert s07.current_page_id == "a"
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)
    assert s07.signal_count == 2

    demo_window._policy_off.click()
    assert demo_window.motion_policy() == POLICY_OFF
    s07.request_page("b")
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)


def test_s07_fast_switch_continues_from_new_page_and_keeps_fields(demo_window, qtbot):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    s07.page_a.findChild(QLineEdit, "motionPageANote").setText("keep-a")
    s07.request_page("b")
    s07.page_b.findChild(QLineEdit, "motionPageBFilter").setText("keep-b")
    assert s07.title_label.text() == "轻量页面示例 · 页面 B"
    assert s07.page_b.isVisible()
    assert not s07.page_a.isVisible()
    _advance(s07.driver, 35)
    assert s07.driver.is_active()
    mid = s07.displayed_opacity()
    assert 0.0 < mid < 1.0

    s07.request_page("a")
    assert s07.current_page_id == "a"
    assert s07.title_label.text() == "轻量页面示例 · 页面 A"
    assert s07.page_a.isVisible()
    assert not s07.page_b.isVisible()
    assert s07.signal_count == 2
    assert s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(0.0)
    _advance(s07.driver, duration_ms("page_enter", POLICY_LIGHT))
    assert s07.displayed_opacity() == pytest.approx(1.0)
    assert s07.page_a.findChild(QLineEdit, "motionPageANote").text() == "keep-a"
    assert s07.page_b.findChild(QLineEdit, "motionPageBFilter").text() == "keep-b"
    log = demo_window.log_text()
    assert "sample_id=S07" in log
    assert "target=a" in log
    assert "/" not in log.split("sample_id=S07", 1)[-1].splitlines()[0]


def test_s07_same_page_is_noop(demo_window):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    s07.request_page("a")
    assert s07.signal_count == 0
    assert not s07.driver.is_active()


def test_s07_input_finishes_fade(demo_window, qtbot):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    s07.request_page("b")
    _advance(s07.driver, 40)
    assert s07.driver.is_active()
    field = s07.page_b.findChild(QLineEdit, "motionPageBFilter")
    qtbot.keyClick(field, "x")
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)
    assert "x" in field.text()


def test_s07_reduced_motion_and_reset(demo_window):
    s07 = demo_window.sample_s07
    demo_window._policy_light.click()
    s07.request_page("b")
    _advance(s07.driver, 40)
    demo_window._policy_reduced.click()
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)

    demo_window.reset_demo()
    assert demo_window.motion_policy() == POLICY_OFF
    assert s07.current_page_id == "a"
    assert s07.signal_count == 0
    assert s07.page_a.findChild(QLineEdit, "motionPageANote").text() == ""
    assert not s07.driver.is_active()


def test_s07_hide_reshow_and_close_stop_motion(demo_window):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    s07.page_a.findChild(QLineEdit, "motionPageANote").setText("persist")
    s07.request_page("b")
    _advance(s07.driver, 40)
    assert s07.driver.is_active()

    demo_window.hide()
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)
    demo_window.show()
    assert s07.current_page_id == "b"
    assert s07.page_a.findChild(QLineEdit, "motionPageANote").text() == "persist"
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)

    s07.request_page("a")
    _advance(s07.driver, 40)
    assert s07.driver.is_active()
    demo_window.close()
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)


def test_s07_resize_snaps_and_keeps_tab_order(demo_window, qtbot):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    note = s07.page_a.findChild(QLineEdit, "motionPageANote")
    note.setText("tab-keep")
    s07.request_page("b")
    _advance(s07.driver, 40)
    assert s07.driver.is_active()
    demo_window.resize(demo_window.width() + 80, demo_window.height() + 40)
    assert not s07.driver.is_active()
    assert s07.displayed_opacity() == pytest.approx(1.0)
    assert note.text() == "tab-keep"

    s07.request_page("a")
    s07.snap_to_end()
    note.setFocus()
    qtbot.keyClick(note, Qt.Key_Tab)
    focused = QApplication.focusWidget()
    assert focused is not None
    assert s07.page_a.isAncestorOf(focused) or focused is s07.page_a
    assert note.text() == "tab-keep"


def test_single_click_does_not_drive_other_samples(demo_window):
    s07 = demo_window.sample_s07
    demo_window.set_motion_policy(POLICY_LIGHT)
    demo_window._placeholders["S01"].setFocus()
    assert s07.current_page_id == "a"
    assert s07.signal_count == 0
    demo_window.sample_s07._btn_page_b.click()
    assert s07.current_page_id == "b"
    assert s07.signal_count == 1
    assert demo_window.sample_s02.isChecked() is False
    assert demo_window._placeholders["S02"].objectName() == "motionSampleS02"


def test_s02_policy_follows_host_and_logs_only_own_toggle(demo_window):
    switch = demo_window.findChild(PillSwitch, "motionSampleS02Switch")
    assert switch is demo_window.sample_s02
    assert switch.motion_policy() == POLICY_OFF

    demo_window.set_motion_policy(POLICY_LIGHT)
    assert switch.motion_policy() == POLICY_LIGHT
    s07_signals = demo_window.sample_s07.signal_count
    switch.click()
    assert switch.isChecked() is True
    log = demo_window.log_text()
    assert "sample_id=S02" in log
    assert "target=1" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s07.current_page_id == "a"

    demo_window.reset_demo()
    assert demo_window.sample_s02.isChecked() is False
    assert demo_window.sample_s02.motion_policy() == POLICY_OFF
    assert demo_window.sample_s07.signal_count == 0


def test_s03_policy_follows_host_and_logs_only_own_index(demo_window):
    host = demo_window.findChild(QGroupBox, "motionSampleS03")
    choice = host.findChild(SegmentedChoice)
    assert choice is demo_window.sample_s03
    assert choice.objectName() == "segmentedChoice"
    assert choice.motion_policy() == POLICY_OFF
    assert choice.currentIndex() == 0

    demo_window.set_motion_policy(POLICY_LIGHT)
    assert choice.motion_policy() == POLICY_LIGHT
    s07_signals = demo_window.sample_s07.signal_count
    s02_checked = demo_window.sample_s02.isChecked()
    choice.buttons()[1].click()
    assert choice.currentIndex() == 1
    assert choice.bound_combo().currentData() == "manual"
    log = demo_window.log_text()
    assert "sample_id=S03" in log
    assert "target=1" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s02.isChecked() is s02_checked

    demo_window.reset_demo()
    assert demo_window.sample_s03.currentIndex() == 0
    assert demo_window.sample_s03.motion_policy() == POLICY_OFF


def test_s04_marker_follows_confirmed_manager_not_other_samples(demo_window):
    host = demo_window.findChild(QGroupBox, "motionSampleS04")
    bar = host.findChild(ViewTabBar)
    manager = demo_window.sample_s04_manager
    assert bar is demo_window.sample_s04
    assert bar.motion_policy() == POLICY_OFF
    assert manager.active == 0
    assert len(manager.views) == 3

    demo_window.set_motion_policy(POLICY_LIGHT)
    assert bar.motion_policy() == POLICY_LIGHT
    pending = []
    bar.switch_requested.connect(pending.append)
    s07_signals = demo_window.sample_s07.signal_count
    tabs = bar.tabBar()
    QTest.mouseClick(tabs, Qt.LeftButton, pos=tabs.tabRect(1).center())
    assert pending == [1]
    assert manager.active == 1
    assert bar._marker_view_id == manager.get(1).view_id
    log = demo_window.log_text()
    assert "sample_id=S04" in log
    assert f"target={manager.get(1).view_id}" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s02.isChecked() is False
    assert demo_window.sample_s03.currentIndex() == 0

    demo_window.reset_demo()
    assert demo_window.sample_s04_manager.active == 0
    assert len(demo_window.sample_s04_manager.views) == 3
    assert demo_window.sample_s04.motion_policy() == POLICY_OFF


def test_s05_uses_injected_settings_and_logs_own_expand(demo_window):
    host = demo_window.findChild(QGroupBox, "motionSampleS05")
    section = demo_window.sample_s05
    assert section is host.findChild(type(section))
    assert section.objectName() == "inspectorParamSection"
    assert section.motion_policy() == POLICY_OFF
    assert section.is_expanded() is False
    settings_path = Path(str(demo_window.sample_s05_settings.fileName())).resolve()
    assert settings_path.suffix == ".ini"
    assert "DataAnalyzer" not in str(settings_path)

    demo_window.set_motion_policy(POLICY_LIGHT)
    assert section.motion_policy() == POLICY_LIGHT
    s07_signals = demo_window.sample_s07.signal_count
    persistent = host.findChild(QLabel, "motionSampleS05Persistent")
    section.btn_collapser.click()
    assert section.is_expanded() is True
    assert bool(demo_window.sample_s05_settings.value("motion_demo/s05_expanded"))
    assert persistent is not None and persistent.isVisible()
    log = demo_window.log_text()
    assert "sample_id=S05" in log
    assert "target=1" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s02.isChecked() is False

    demo_window.reset_demo()
    assert demo_window.sample_s05.is_expanded() is False
    assert demo_window.sample_s05.motion_policy() == POLICY_OFF


def test_s01_sample_buttons_follow_host_and_log_own_click(demo_window):
    from mf4_analyzer.ui_kit.widgets.motion_button import MotionButton

    primary = demo_window.findChild(MotionButton, "motionSampleS01Primary")
    icon24 = demo_window.findChild(MotionButton, "motionSampleS01Icon24")
    assert primary is demo_window.sample_s01_buttons[0]
    assert primary.motion_policy() == POLICY_OFF
    assert icon24 is not None
    assert icon24.width() == icon24.height() == 24

    demo_window.set_motion_policy(POLICY_LIGHT)
    assert primary.motion_policy() == POLICY_LIGHT
    s07_signals = demo_window.sample_s07.signal_count
    primary.click()
    log = demo_window.log_text()
    assert "sample_id=S01" in log
    assert "target=primary" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s02.isChecked() is False

    demo_window.reset_demo()
    assert demo_window.sample_s01_buttons[0].motion_policy() == POLICY_OFF


def test_s06_logs_open_intent_without_touching_other_samples(demo_window, qtbot):
    from PyQt5.QtWidgets import QTableView

    from mf4_analyzer.ui.widgets.recent_open_popup import RECENT_POPUP_MAX_WIDTH

    popup = demo_window.sample_s06
    assert popup.motion_policy() == POLICY_OFF
    demo_window.set_motion_policy(POLICY_LIGHT)
    assert popup.motion_policy() == POLICY_LIGHT
    s07_signals = demo_window.sample_s07.signal_count
    demo_window.sample_s06_anchor.click()
    qtbot.waitExposed(popup)
    assert popup.isVisible()
    assert popup.width() <= RECENT_POPUP_MAX_WIDTH
    table = popup.findChild(QTableView, "recentOpenTable")
    index = table.model().index(0, 0)
    QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualRect(index).center())
    log = demo_window.log_text()
    assert "sample_id=S06" in log
    assert "target=open:" in log
    assert demo_window.sample_s07.signal_count == s07_signals
    assert demo_window.sample_s02.isChecked() is False

    demo_window.reset_demo()
    assert not demo_window.sample_s06.isVisible()
    assert demo_window.sample_s06.motion_policy() == POLICY_OFF
