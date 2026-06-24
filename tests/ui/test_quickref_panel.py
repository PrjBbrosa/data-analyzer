"""Smoke + behavior tests for the QuickRefPanel widget (offscreen Qt)."""
import pytest
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.quickref_panel import QuickRefPanel
from mf4_analyzer.ui import quickref


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
    # Not pinned by default → not always-on-top.
    assert not (flags & Qt.WindowStaysOnTopHint)


def test_pin_toggles_stay_on_top(panel):
    panel.set_pinned(True)
    assert panel.is_pinned()
    assert panel.windowFlags() & Qt.WindowStaysOnTopHint
    assert panel._pin_btn.isChecked()
    panel.set_pinned(False)
    assert not panel.is_pinned()
    assert not (panel.windowFlags() & Qt.WindowStaysOnTopHint)
    assert not panel._pin_btn.isChecked()


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


def test_soon_badge_present_for_coaxis(panel):
    """The 共轴 row renders an '即将' badge label."""
    from PyQt5.QtWidgets import QLabel
    chan_card = next(
        c for c in panel._group_cards if c.group.title == "通道树（左侧）"
    )
    soon_labels = [
        w for w in chan_card.findChildren(QLabel)
        if w.objectName() == "quickrefSoon"
    ]
    assert len(soon_labels) == 1
    assert soon_labels[0].text() == "即将"
