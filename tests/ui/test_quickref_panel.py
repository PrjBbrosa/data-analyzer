"""Smoke + behavior tests for the QuickRefPanel widget (offscreen Qt)."""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QVBoxLayout,
)

from mf4_analyzer.ui import quickref_panel as quickref_panel_module
from mf4_analyzer.ui.quickref_panel import QuickRefPanel
from mf4_analyzer.ui import quickref
from mf4_analyzer.ui_kit.widgets import SearchField


@pytest.fixture
def panel(qtbot):
    p = QuickRefPanel()
    qtbot.addWidget(p)
    return p


def test_constructs_with_all_groups(panel):
    # One _GroupCard per catalog group.
    assert len(panel._group_cards) == len(quickref.QUICKREF)
    titles = [c.group.title for c in panel._group_cards]
    assert titles == [g.title for g in quickref.QUICKREF]


def test_non_modal_flags(panel):
    flags = panel.windowFlags()
    assert flags & Qt.Tool
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.NoDropShadowWindowHint
    # Not pinned by default → not always-on-top.
    assert not (flags & Qt.WindowStaysOnTopHint)


def test_pin_toggles_stay_on_top(panel):
    panel.set_pinned(True)
    assert panel.is_pinned()
    assert panel.windowFlags() & Qt.WindowStaysOnTopHint
    assert panel.windowFlags() & Qt.NoDropShadowWindowHint
    assert panel._pin_btn.isChecked()
    panel.set_pinned(False)
    assert not panel.is_pinned()
    assert not (panel.windowFlags() & Qt.WindowStaysOnTopHint)
    assert panel.windowFlags() & Qt.NoDropShadowWindowHint
    assert not panel._pin_btn.isChecked()


def test_shadow_layers_stay_light_and_inside_shell_margin():
    """Keep the quickref float shadow subtle, not a thick Windows halo."""
    layers = getattr(quickref_panel_module, "_SHADOW_LAYERS", None)
    assert layers is not None, "shadow layers must be a testable visual token"
    assert len(layers) <= 2
    for grow, dy, color in layers:
        assert color.alpha() <= 24
        assert grow + dy <= quickref_panel_module._SHADOW_MARGIN


def test_search_filters_rows(panel):
    panel.show()
    # Search for a term that only appears in the 游标 group ("双游标").
    panel._on_search("双游标")
    cursor_card = next(
        c for c in panel._group_cards if c.group.title == "游标"
    )
    assert cursor_card.isVisible()
    # A group with no match (e.g. 预设) is hidden entirely.
    preset_card = next(
        c for c in panel._group_cards if c.group.title == "预设"
    )
    assert not preset_card.isVisible()
    # Clearing the filter restores everything.
    panel._on_search("")
    assert preset_card.isVisible()
    assert cursor_card.isVisible()


def test_search_matches_keyboard_chip_text(panel):
    panel.show()
    panel._on_search("ctrl+g")  # the pan shortcut chip
    visible_titles = [
        c.group.title for c in panel._group_cards if c.isVisible()
    ]
    assert "快捷键" in visible_titles


def test_toggle_show_hide(panel):
    assert not panel.isVisible()
    panel.toggle()
    assert panel.isVisible()
    panel.toggle()
    assert not panel.isVisible()


def test_escape_hides_unpinned(panel):
    from PyQt5.QtGui import QKeyEvent
    panel.show_panel()
    assert panel.isVisible()
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    panel.keyPressEvent(ev)
    assert not panel.isVisible()


def test_search_escape_clears_before_host_close(panel, qtbot, qapp):
    """SDI-A05: first Esc with search text clears and keeps the panel open."""
    opener = QLineEdit()
    qtbot.addWidget(opener)
    opener.show()
    qtbot.waitExposed(opener)
    opener.setFocus(Qt.OtherFocusReason)
    panel.set_pinned(True)
    panel.show_panel(anchor_widget=opener)
    qtbot.waitExposed(panel)
    search = panel._search
    search.setFocus(Qt.OtherFocusReason)
    qtbot.keyClicks(search, "view")
    qapp.processEvents()
    assert search.text()
    visible_before = [c.group.title for c in panel._group_cards if c.isVisible()]

    qtbot.keyClick(search, Qt.Key_Escape)
    qapp.processEvents()
    assert panel.isVisible()
    assert search.text() == ""
    assert search.hasFocus() or QApplication.focusWidget() is search
    visible_after = [c.group.title for c in panel._group_cards if c.isVisible()]
    assert visible_after == [g.title for g in quickref.QUICKREF]
    assert len(visible_after) >= len(visible_before)


def test_search_second_escape_closes_and_returns_focus_to_opener(qtbot, qapp):
    """SDI-A05: empty-search Esc closes QuickRef and restores the opener."""
    opener = QLineEdit()
    opener.setObjectName("quickrefOpener")
    opener.setText("opener")
    qtbot.addWidget(opener)
    opener.show()
    qtbot.waitExposed(opener)
    opener.setFocus(Qt.OtherFocusReason)

    panel = QuickRefPanel()
    qtbot.addWidget(panel)
    panel.set_pinned(True)
    panel.show_panel(anchor_widget=opener)
    qtbot.waitExposed(panel)
    panel._search.setFocus(Qt.OtherFocusReason)
    qtbot.keyClicks(panel._search, "view")
    qapp.processEvents()

    qtbot.keyClick(panel._search, Qt.Key_Escape)
    qapp.processEvents()
    assert panel.isVisible()
    assert panel._search.text() == ""

    qtbot.keyClick(panel._search, Qt.Key_Escape)
    qapp.processEvents()
    assert not panel.isVisible()
    assert opener.hasFocus() or QApplication.focusWidget() is opener


def test_search_return_does_not_click_dialog_default(qtbot, qapp):
    """Search Enter is consumed; empty results are a no-op, not dialog accept."""
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    field = SearchField("搜索操作…")
    layout.addWidget(field)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok = buttons.button(QDialogButtonBox.Ok)
    ok.setDefault(True)
    ok.setAutoDefault(True)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.show()
    qtbot.waitExposed(dialog)
    field.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    qtbot.keyClick(field, Qt.Key_Return)
    qapp.processEvents()
    assert dialog.isVisible()
    assert dialog.result() != QDialog.Accepted

    field.setText("no-such-match")
    qtbot.keyClick(field, Qt.Key_Enter)
    qapp.processEvents()
    assert dialog.isVisible()
    assert dialog.result() != QDialog.Accepted


def test_footer_open_guide_callback(qtbot):
    calls = []
    p = QuickRefPanel(open_guide=lambda name: calls.append(name) or True)
    qtbot.addWidget(p)
    p._on_footer_clicked(None)
    assert calls == ["manual"]


def test_card_carries_white_qss_not_translucent(panel):
    # The inner card (not the translucent outer) owns the surface, so its
    # background QSS survives. Guard the gotcha: outer is translucent, inner
    # is NOT, and the inner card has WA_StyledBackground so QSS paints.
    assert panel.testAttribute(Qt.WA_TranslucentBackground)
    assert not panel._card.testAttribute(Qt.WA_TranslucentBackground)
    assert panel._card.testAttribute(Qt.WA_StyledBackground)


def test_group_cards_use_white_surface_not_gray_fill(panel):
    sheet = panel.styleSheet()
    group_block = sheet.split("QFrame#quickrefGroup {", 1)[1].split("}", 1)[0]
    assert "background-color: #ffffff;" in group_block
    assert "background-color: #fafbfc;" not in group_block


def test_coaxis_row_renders_without_soon_badge(panel):
    """共轴组 shipped 2026-06-27: the 合并为共轴 row no longer renders an '即将'
    badge, and no card carries one (it was the catalog's only staged item)."""
    from PyQt5.QtWidgets import QLabel
    chan_card = next(
        c for c in panel._group_cards if c.group.title == "通道树（左侧）"
    )
    assert any(r.desc == "合并为共轴比幅值" for r in chan_card.group.rows)
    soon_labels = [
        w
        for card in panel._group_cards
        for w in card.findChildren(QLabel)
        if w.objectName() == "quickrefSoon"
    ]
    assert soon_labels == []


def test_quickref_compact_work_area_keeps_search_and_close(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    host = QWidget()
    host.setGeometry(0, 0, 640, 360)
    qtbot.addWidget(host)
    host.show()
    panel = QuickRefPanel()
    qtbot.addWidget(panel)
    panel._position(host)
    panel.show()
    qtbot.waitExposed(panel)
    assert panel.width() <= 640 - 2 * SCREEN_MARGIN
    assert panel.height() <= 360 - 2 * SCREEN_MARGIN
    assert panel._search.isVisible()
    assert panel._close_btn.isVisible()
    assert panel.rect().contains(panel._close_btn.geometry())
