"""Shared SearchField contracts and approved product call-site migration."""
from __future__ import annotations

import inspect
from pathlib import Path
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QWidget


_REPO_ROOT = Path(__file__).resolve().parents[2]

# FileNavigator renders the same MultiFileChannelWidget search instance as the
# ChannelTree.  Keep every current construction in this inventory, including
# the modal Channel Editor and the normally hidden UltraView library.
_SEARCH_CALL_SITES = {
    "mf4_analyzer/ui/widgets/channel_tree.py": (
        ("self.search", "搜索通道…"),
    ),
    "mf4_analyzer/ui/quickref_panel.py": (
        ("self._search", "搜索操作…"),
    ),
    "mf4_analyzer/ui/dialogs/channel_editor.py": (
        ("self.export_search", "搜索通道…"),
    ),
    "mf4_analyzer/ui/drawers/batch/signal_picker.py": (
        ("self._search", "搜索信号…"),
    ),
    "mf4_analyzer/ui/chart_stack/ultraview/library_widgets.py": (
        ("self._search", "搜索 View、信号或分析类型…"),
    ),
    "mf4_analyzer/ui/widgets/channel_config_manager.py": (
        ("self.config_search", "搜索配置…"),
        ("self.channel_search", "搜索通道…"),
    ),
    "mf4_analyzer/acquisition_ui/widgets/left_pane.py": (
        ("self._search", "搜索测量…"),
    ),
    "mf4_analyzer/acquisition_ui/history_tab.py": (
        ("self._search_box", "搜索记录…"),
    ),
    "mf4_analyzer/ui/chart_stack/ultraview/library_widgets.py": (
        ("self._search", "搜索 View、信号或分析类型…"),
    ),
}


def _load_production_stylesheet(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    return previous


def test_search_field_has_base_height_and_crisp_leading_trailing_icons(qapp, qtbot):
    from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS
    from mf4_analyzer.ui_kit.widgets import SearchField

    previous = _load_production_stylesheet(qapp)
    try:
        assert tuple(inspect.signature(SearchField).parameters) == (
            "placeholder",
            "parent",
        )
        host = QWidget()
        layout = QVBoxLayout(host)
        field = SearchField("搜索通道…", host)
        layout.addWidget(field)
        qtbot.addWidget(host)
        host.show()
        qtbot.wait(20)

        assert field.property("role") == "search"
        assert field.placeholderText() == "搜索通道…"
        assert not field.isClearButtonEnabled()
        assert field.height() == CONTROL_HEIGHTS["base"]
        assert field.sizeHint().height() == CONTROL_HEIGHTS["base"]
        assert not field._search_button.icon().isNull()
        assert not field._clear_button.icon().isNull()
        assert not field._clear_button.isVisible()
        assert field._search_button.y() == (
            field.height() - field._search_button.height()
        ) // 2

        field.setText("tas")
        assert field._clear_button.isVisible()
        assert field._clear_button.y() == (
            field.height() - field._clear_button.height()
        ) // 2
        field._clear_button.click()
        assert field.text() == ""
        assert not field._clear_button.isVisible()
    finally:
        qapp.setStyleSheet(previous)


def test_search_field_reuses_cached_painter_icons(qapp, monkeypatch):
    from mf4_analyzer.ui_kit.widgets import search_field

    calls = {"search": 0, "clear": 0}
    search_icon = QIcon()
    clear_icon = QIcon()

    def fake_search():
        calls["search"] += 1
        return search_icon

    def fake_clear():
        calls["clear"] += 1
        return clear_icon

    monkeypatch.setattr(search_field.Icons, "search", staticmethod(fake_search))
    monkeypatch.setattr(
        search_field.Icons, "clear_field", staticmethod(fake_clear),
    )
    monkeypatch.setattr(search_field.SearchField, "_cached_search_icon", None)
    monkeypatch.setattr(search_field.SearchField, "_cached_clear_icon", None)

    first = search_field.SearchField("搜索信号…")
    second = search_field.SearchField("搜索配置…")

    assert calls == {"search": 1, "clear": 1}
    assert first._search_button.icon().cacheKey() == second._search_button.icon().cacheKey()
    assert first._clear_button.icon().cacheKey() == second._clear_button.icon().cacheKey()


def test_empty_search_escape_without_closeable_host_is_safe_noop(qapp, qtbot):
    from PyQt5.QtTest import QSignalSpy
    from mf4_analyzer.ui_kit.widgets import SearchField

    host = QWidget()
    layout = QVBoxLayout(host)
    field = SearchField("搜索通道…", host)
    destructive = QPushButton("删除", host)
    destructive.setDefault(True)
    clicks = QSignalSpy(destructive.clicked)
    layout.addWidget(field)
    layout.addWidget(destructive)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    field.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    qtbot.keyClick(field, Qt.Key_Escape)
    qapp.processEvents()

    assert host.isVisible()
    assert field.text() == ""
    assert len(clicks) == 0


def test_eight_visible_search_surfaces_render_on_the_base_track(qapp, qtbot):
    from mf4_analyzer.acquisition_ui.history_tab import HistoryTab
    from mf4_analyzer.acquisition_ui.widgets.left_pane import LeftPane
    from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from mf4_analyzer.ui.file_navigator import FileNavigator
    from mf4_analyzer.ui.quickref_panel import QuickRefPanel
    from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog
    from mf4_analyzer.ui.widgets.channel_tree import MultiFileChannelWidget
    from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS

    previous = _load_production_stylesheet(qapp)
    try:
        tree = MultiFileChannelWidget()
        navigator = FileNavigator()
        quickref = QuickRefPanel()
        picker = SignalPickerPopup(available_signals=["EPS_CRC"])
        config = ChannelSelectionConfig.create(
            "drive", "动力分析", ("EPS_CRC",), now="2026-08-09T00:00:00+00:00"
        )
        manager = ChannelConfigManagerDialog([config], selected_id="drive")
        left_pane = LeftPane()
        history = HistoryTab(resolve_async=False)

        for widget in (tree, navigator, quickref, picker, manager, left_pane, history):
            qtbot.addWidget(widget)
            widget.show()
        picker._popup.show()
        qapp.processEvents()

        visible_fields = {
            "ChannelTree": tree.search,
            "FileNavigator": navigator.channel_list.search,
            "QuickRef": quickref._search,
            "Batch SignalPicker": picker._search,
            "ChannelConfig config": manager.config_search,
            "ChannelConfig channel": manager.channel_search,
            "Cockpit LeftPane": left_pane._search,
            "Cockpit History": history._search_box,
        }
        assert len(visible_fields) == 8
        for surface, field in visible_fields.items():
            assert field.isVisible(), surface
            assert not field.isClearButtonEnabled(), surface
            assert not field._search_button.icon().isNull(), surface
            assert not field._clear_button.icon().isNull(), surface
            assert re.fullmatch(r"搜索.+…", field.placeholderText()), surface
        assert {surface: field.height() for surface, field in visible_fields.items()} == {
            surface: CONTROL_HEIGHTS["base"] for surface in visible_fields
        }
    finally:
        qapp.setStyleSheet(previous)


def test_product_search_call_sites_use_shared_search_field_and_chinese_copy():
    for relative_path, expected_calls in _SEARCH_CALL_SITES.items():
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for variable, placeholder in expected_calls:
            expression = re.compile(
                rf'{re.escape(variable)}\s*=\s*SearchField\(\s*"{placeholder}"'
            )
            assert expression.search(source), (
                f"{relative_path}: {variable} must construct SearchField({placeholder!r})"
            )
            bare_line_edit = re.compile(
                rf'{re.escape(variable)}\s*=\s*QLineEdit\('
            )
            assert not bare_line_edit.search(source), (
                f"{relative_path}: {variable} still bypasses SearchField"
            )

    navigator = (_REPO_ROOT / "mf4_analyzer/ui/file_navigator.py").read_text(
        encoding="utf-8"
    )
    assert "MultiFileChannelWidget" in navigator


def test_product_has_no_bare_line_edit_search_placeholder():
    constructor = re.compile(
        r"(?P<variable>(?:self\.)?[A-Za-z_]\w*)\s*=\s*QLineEdit\([^\n]*\)"
    )
    for source_path in (_REPO_ROOT / "mf4_analyzer").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        for match in constructor.finditer(source):
            variable = re.escape(match.group("variable"))
            following_source = source[match.end():]
            placeholder = re.compile(
                rf"{variable}\.setPlaceholderText\([^\n]*(?:搜索|Filter)"
            )
            assert not placeholder.search(following_source), (
                f"{source_path.relative_to(_REPO_ROOT)}: {match.group('variable')} "
                "must use SearchField for a search placeholder"
            )


def test_cockpit_search_details_live_in_tooltips_not_placeholders():
    left_pane = (
        _REPO_ROOT / "mf4_analyzer/acquisition_ui/widgets/left_pane.py"
    ).read_text(encoding="utf-8")
    history = (
        _REPO_ROOT / "mf4_analyzer/acquisition_ui/history_tab.py"
    ).read_text(encoding="utf-8")

    assert 'self._search.setToolTip("可搜索 name / 0x40A")' in left_pane
    assert 'self._search_box.setToolTip("可搜索 name / id")' in history
