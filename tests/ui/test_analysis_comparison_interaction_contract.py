"""Real viewport/shared-action contracts for independent analysis Views."""
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from pyqtgraph import ViewBox

from .test_analysis_view_comparison_regressions import win, prep

SECTIONS = ['fft', 'fft_time', 'order', 'frf']


def click_plot(card):
    canvas = card.canvas
    boxes = [item for item in canvas._glw.scene().items()
             if isinstance(item, ViewBox) and item.isVisible()]
    box = min(boxes, key=lambda item: item.sceneBoundingRect().top())
    pos = canvas._glw.mapFromScene(box.sceneBoundingRect().center())
    QTest.mouseClick(canvas._glw.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()


def open_pair(win, section, qtbot):
    page, manager, host, peer = prep(win, section)
    host.tab_color = '#ef4444'
    peer.tab_color = '#22aa66'
    win.resize(1500, 950)
    win.show()
    win.open_comparison(section, host.view_id, peer.view_id)
    qtbot.wait(150)
    return page, host, peer


@pytest.mark.parametrize('section', SECTIONS)
def test_comparison_only_shows_shared_toolbar_and_no_hint_bands(win, section, qtbot):
    page, host, peer = open_pair(win, section, qtbot)
    cards = page.peek_cards() + page.peer_cards()
    assert page._toolbar.isVisible()
    assert all(not card.toolbar.isVisible() for card in cards[1:])
    assert all(not card._hint_bar.isVisible() for card in cards)
    assert cards[0].canvas.mapTo(page, cards[0].canvas.rect().topLeft()).y() == cards[1].canvas.mapTo(page, cards[1].canvas.rect().topLeft()).y()


@pytest.mark.parametrize('section', SECTIONS)
def test_shared_home_and_annotation_follow_real_peer_click(win, section, qtbot, monkeypatch):
    page, host_view, peer_view = open_pair(win, section, qtbot)
    host, peer = page.peek_cards()[0], page.peer_cards()[0]
    click_plot(peer)
    assert win._comparison().focused(section) == (peer_view.view_id, 0)
    hits = []
    monkeypatch.setattr(host.toolbar, 'home', lambda: hits.append('host'))
    monkeypatch.setattr(peer.toolbar, 'home', lambda: hits.append('peer'))
    page._toolbar._actions_by_key['home'].trigger()
    assert hits == ['peer']
    QTest.mouseClick(host._annotation_btn, Qt.LeftButton)
    assert peer.annotation_enabled()
    assert not host.annotation_enabled()
    click_plot(host)
    assert not host._annotation_btn.isChecked()
    click_plot(peer)
    assert host._annotation_btn.isChecked()


@pytest.mark.parametrize('section', SECTIONS)
def test_shared_mode_broadcasts_both_directions(win, section, qtbot):
    page, host, peer = open_pair(win, section, qtbot)
    cards = page.peek_cards() + page.peer_cards()
    page._toolbar._actions_by_key['zoom'].trigger()
    assert [card.toolbar.mode for card in cards] == ['zoom', 'zoom']
    cards[1].toolbar.set_mouse_mode_broadcast('pan')
    assert [card.toolbar.mode for card in cards] == ['pan', 'pan']


@pytest.mark.parametrize('section', SECTIONS)
def test_peer_focus_marker_uses_peer_color(win, section, qtbot):
    page, host, peer = open_pair(win, section, qtbot)
    card = page.peer_cards()[0]
    click_plot(card)
    assert peer.tab_color in card._focus_bar.styleSheet()
    assert card._focus_bar.height() == 3
    peer.tab_color = '#8844cc'
    page.manager.views_changed.emit()
    assert peer.tab_color in card._focus_bar.styleSheet()


@pytest.mark.parametrize('section', SECTIONS)
@pytest.mark.parametrize('host_count,peer_count', [(1, 2), (2, 1), (2, 2)])
def test_dynamic_panes_share_chrome_and_mode(win, section, qtbot, host_count, peer_count):
    from mf4_analyzer.ui.analysis_view_state import PaneState
    page, manager, host, peer = prep(win, section)
    for state, count in ((host, host_count), (peer, peer_count)):
        if count == 2:
            state.panes.append(PaneState())
    win.resize(1500, 950)
    win.show()
    win.open_comparison(section, host.view_id, peer.view_id)
    qtbot.wait(100)
    cards = page.all_cards()
    assert len(cards) == host_count + peer_count
    assert page.peek_cards() == cards[:host_count]
    assert all(not card.toolbar.isVisible() for card in cards[1:])
    assert all(not card._hint_bar.isVisible() for card in cards)
    page._toolbar._actions_by_key['zoom'].trigger()
    assert all(card.toolbar.mode == 'zoom' for card in cards)
    removed = page.peer_cards()[-1]
    win.close_comparison(section)
    assert removed.toolbar._peer_toolbars_provider is None
    assert not removed.toolbar._history_timer.isActive()
    win.open_comparison(section, host.view_id, peer.view_id)
    qtbot.wait(50)
    assert all(card.toolbar.mode == 'zoom' for card in page.all_cards())
    assert all(not card.toolbar.isVisible() for card in page.all_cards()[1:])


@pytest.mark.parametrize('section', ['fft_time', 'order'])
def test_peer_only_gesture_enables_shared_back_and_restores_peer(win, section, qtbot):
    from .test_toolbar_section_contract import _plot_heatmap
    page, host, peer = open_pair(win, section, qtbot)
    host_card, peer_card = page.all_cards()
    _plot_heatmap(host_card)
    _plot_heatmap(peer_card)
    QApplication.processEvents()
    host_base = host_card.canvas.capture_xy_viewport()
    peer_base = peer_card.canvas.capture_xy_viewport()
    click_plot(peer_card)
    peer_card.canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ShiftModifier, x_pos=5.0, y_pos=4.0,
        view_box=peer_card.canvas._plot.vb,
    )
    assert peer_card.canvas.capture_xy_viewport()[1] != pytest.approx(peer_base[1])
    assert page._toolbar._actions_by_key['back'].isEnabled()
    page._toolbar._actions_by_key['back'].trigger()
    assert peer_card.canvas.capture_xy_viewport()[1] == pytest.approx(peer_base[1])
    assert host_card.canvas.capture_xy_viewport()[1] == pytest.approx(host_base[1])
    assert not peer_card.toolbar._history_timer.isActive()
    page._toolbar._actions_by_key['forward'].trigger()
    assert peer_card.canvas.capture_xy_viewport()[1] != pytest.approx(peer_base[1])


@pytest.mark.parametrize('section', SECTIONS)
def test_clear_confirmation_cannot_clear_replaced_peer(win, section, qtbot, monkeypatch):
    page, host_view, peer_view = open_pair(win, section, qtbot)
    host, peer = page.all_cards()
    click_plot(peer)
    hits = []
    monkeypatch.setattr(peer.canvas, 'remark_count', lambda: 1)
    monkeypatch.setattr(peer.canvas, 'clear_remarks', lambda: hits.append('peer'))
    monkeypatch.setattr(host.canvas, 'clear_remarks', lambda: hits.append('host'))
    def close_during_confirmation(count):
        win.close_comparison(section)
        # Closing legitimately renders the host. Observe only the clear action
        # after its confirmation resumes, not that independent render cleanup.
        hits.clear()
        return True
    monkeypatch.setattr(host, '_confirm_clear_annotations', close_during_confirmation)
    QTest.mouseClick(host._clear_annotation_btn, Qt.LeftButton)
    assert hits == []


@pytest.mark.parametrize('section', ['fft_time', 'order'])
def test_shared_home_restores_real_peer_camera_only(win, section, qtbot):
    from .test_toolbar_section_contract import _plot_heatmap
    page, host, peer = open_pair(win, section, qtbot)
    host_card, peer_card = page.all_cards()
    for card in (host_card, peer_card):
        _plot_heatmap(card)
    QApplication.processEvents()
    peer_base = peer_card.canvas.capture_xy_viewport()
    for card in (host_card, peer_card):
        card.canvas._handle_wheel_dispatch(
            delta=120, modifiers=Qt.ShiftModifier, x_pos=5.0, y_pos=4.0,
            view_box=card.canvas._plot.vb,
        )
    host_zoom = host_card.canvas.capture_xy_viewport()
    click_plot(peer_card)
    page._toolbar._actions_by_key['home'].trigger()
    assert peer_card.canvas.capture_xy_viewport()[1] == pytest.approx(peer_base[1])
    assert host_card.canvas.capture_xy_viewport()[1] == pytest.approx(host_zoom[1])


@pytest.mark.parametrize('section', SECTIONS)
def test_shared_clear_uses_peer_after_real_click(win, section, qtbot, monkeypatch):
    page, host_view, peer_view = open_pair(win, section, qtbot)
    host, peer = page.all_cards()
    click_plot(peer)
    hits = []
    monkeypatch.setattr(peer.canvas, 'remark_count', lambda: 1)
    monkeypatch.setattr(peer.canvas, 'clear_remarks', lambda: hits.append('peer'))
    monkeypatch.setattr(host.canvas, 'clear_remarks', lambda: hits.append('host'))
    monkeypatch.setattr(host, '_confirm_clear_annotations', lambda count: True)
    QTest.mouseClick(host._clear_annotation_btn, Qt.LeftButton)
    assert hits == ['peer']


def test_detaching_peer_clears_shared_history_availability(win, qtbot):
    from .test_toolbar_section_contract import _plot_heatmap
    page, host, peer = open_pair(win, 'fft_time', qtbot)
    host_card, peer_card = page.all_cards()
    _plot_heatmap(host_card)
    _plot_heatmap(peer_card)
    QApplication.processEvents()
    peer_card.canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ShiftModifier, x_pos=5.0, y_pos=4.0,
        view_box=peer_card.canvas._plot.vb,
    )
    assert page._toolbar._actions_by_key['back'].isEnabled()
    # Exercise the page's unmount boundary before any MainWindow re-render.
    page.hide_comparison_peer()
    assert not page._toolbar._actions_by_key['back'].isEnabled()
