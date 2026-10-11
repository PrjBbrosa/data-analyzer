"""Cross-view peers participate in stack-wide presentation routing."""
import pytest

from mf4_analyzer.ui.chart_stack import ChartStack
from .test_analysis_view_comparison_regressions import win, prep


@pytest.mark.parametrize("section", ["fft", "fft_time", "order", "frf"])
def test_peer_card_owns_its_canvas_and_receives_shared_tick_controls(qtbot, section):
    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.set_mode(section)
    page = stack.page_for_mode[section]
    page.ensure_ready()
    manager = page.manager
    manager.new_view(activate=False)
    host, peer = manager.get(0), manager.get(1)
    page.show_comparison_peer(host.view_id, peer.view_id, 2)
    cards = page.peer_cards()

    # A missing peer used to resolve to the time card, misplacing cursor chrome.
    for card in cards:
        assert stack._card_for_canvas(card.canvas) is card
    stack.set_tick_density_controls(7, 9)
    for card in cards:
        assert card._tick_density_popover.density() == (7, 9)

    # View-specific getters must remain host-only for capture/export callers.
    assert not any(card in page.peek_cards() for card in cards)
    page.hide_comparison_peer()
    assert not any(card in stack._all_cards() for card in cards)


@pytest.mark.parametrize("section", ["fft", "fft_time", "order", "frf"])
def test_annotation_setter_and_relay_follow_peer_focus(win, section):
    page, _manager, a, b = prep(win, section)
    win.open_comparison(section, a.view_id, b.view_id)
    win.focus_comparison(section, b.view_id, 0)
    host, peer = page.peek_cards()[0], page.peer_cards()[0]
    changes = []
    win.chart_stack.annotation_enabled_changed.connect(
        lambda mode, enabled: changes.append((mode, enabled)))
    win.chart_stack.set_annotation_enabled(section, True, notify=True)
    assert peer.annotation_enabled()
    assert not host.annotation_enabled()
    assert changes == [(section, True)]
    peer.set_annotation_enabled(False, notify=True)
    assert changes[-1] == (section, False)


@pytest.mark.parametrize("section", ["fft", "fft_time", "order", "frf"])
def test_global_tick_density_reaches_all_visible_analysis_canvases(win, section, monkeypatch):
    page, _manager, a, b = prep(win, section)
    win.open_comparison(section, a.view_id, b.view_id)
    received = []
    monkeypatch.setattr(page.peer_cards()[0].canvas, "set_tick_density",
                        lambda x, y: received.append((x, y)))
    win._update_all_tick_density_pair(7, 9)
    assert received == [(7, 9)]
