"""Shared frequency controls and real P-key ownership across analysis Views."""

import numpy as np
import pytest
from mf4_analyzer.ui.analysis_result_state import bind_result, snapshot_request
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from .test_analysis_view_comparison_regressions import win, prep
from .test_analysis_view_comparison import _frf_result
from .test_analysis_comparison_interaction_contract import click_plot
from .test_pinned_cursor_panels import _aim, _press_p, _records


def _ready_pair(win, section, qtbot):
    page, _manager, host, peer = prep(win, section)
    for state in (host, peer):
        state.panes[0].cursor_mode = 'off'
        if section == 'frf':
            fid = state.panes[0].sources[0][0]
            state.panes[0].input_source = (fid, 'speed')
            state.panes[0].output_source = (fid, 'torque')
            state.panes[0].effective_time_range = (0.0, 1.0)
    win.resize(1500, 950)
    win.show()
    win.activateWindow()
    assert win.open_comparison(section, host.view_id, peer.view_id)
    for ordinal, state in enumerate((host, peer), 1):
        pane = state.panes[0]
        if section == 'frf':
            key = win._frf_cache_key_for_pane(state, pane)
            assert key is not None
            result = _frf_result(float(ordinal))
        else:
            fid, channel = pane.sources[0]
            key = win._analysis_cache_key_for_view_source(section, state, pane, 0, fid, channel)
            frequencies = np.linspace(0.0, 200.0, 101)
            result = (frequencies, np.full(101, ordinal), np.full(101, ordinal))
        win.analysis_caches[section].put(key, result)
        bind_result(pane, snapshot_request(state, pane), (key,))
        win._render_comparison_view(section, state)
    qtbot.wait(150)
    return page, host, peer


@pytest.mark.parametrize('section', ['fft', 'frf'])
def test_shared_frequency_control_edits_only_clicked_view(win, section, qtbot):
    page, host, peer = _ready_pair(win, section, qtbot)
    host_card, peer_card = page.all_cards()
    click_plot(peer_card)
    QTest.mouseClick(host_card._cursor_buttons['single'], Qt.LeftButton)
    assert peer_card.cursor_mode() == 'single'
    assert host_card.cursor_mode() == 'off'
    assert peer.panes[0].cursor_mode == 'single'
    assert host.panes[0].cursor_mode == 'off'
    click_plot(host_card)
    assert host_card._cursor_buttons['off'].isChecked()
    QTest.mouseClick(host_card._cursor_buttons['dual'], Qt.LeftButton)
    assert host_card.cursor_mode() == 'dual'
    assert peer_card.cursor_mode() == 'single'
    click_plot(peer_card)
    assert host_card._cursor_buttons['single'].isChecked()
    win.close_comparison(section)
    assert host_card.cursor_mode() == 'dual'
    assert win.open_comparison(section, host.view_id, peer.view_id)
    click_plot(page.peer_cards()[0])
    assert page.peer_cards()[0].cursor_mode() == 'single'
    assert host_card.cursor_mode() == 'dual'
    assert host_card._cursor_buttons['single'].isChecked()


@pytest.mark.parametrize('section', ['fft', 'frf'])
def test_peer_p_key_pin_keeps_owner_and_survives_comparison_reopen(win, section, qtbot):
    page, host, peer = _ready_pair(win, section, qtbot)
    host_card, peer_card = page.all_cards()
    stack = win.chart_stack
    click_plot(peer_card)
    QTest.mouseClick(host_card._cursor_buttons['single'], Qt.LeftButton)
    _aim(qtbot, peer_card.canvas, 0.5, stack._pinned_cursors)
    stack.setFocus()
    QApplication.processEvents()
    assert stack._pinned_cursors._router.pin_eligible()
    override = _press_p(peer_card.canvas._glw.viewport())
    assert override.isAccepted()
    records = _records(stack, peer_card.canvas)
    assert len(records) == 1
    assert not _records(stack, host_card.canvas)
    record = records[0]
    assert record.domain == ('frf' if section == 'frf' else 'frequency')
    peer_fid = peer.panes[0].sources[0][0]
    assert {binding.fid for binding in record.bindings} == {peer_fid}
    assert np.isfinite(record.x)
    # Ordinary cache repaint / remount of an existing canvas must not replay
    # an older PaneState collection over newly created, uncaptured live pins.
    win._render_comparison_view(section, peer)
    assert _records(stack, peer_card.canvas) == records
    win._present_comparison(section, host.view_id, peer.view_id)
    assert page.peer_cards()[0].canvas is peer_card.canvas
    assert _records(stack, peer_card.canvas) == records
    win.close_comparison(section)
    QApplication.processEvents()
    assert peer.panes[0].pinned_cursors.records == records
    assert not host.panes[0].pinned_cursors.records
    assert win.open_comparison(section, host.view_id, peer.view_id)
    qtbot.wait(100)
    reopened = page.peer_cards()[0].canvas
    assert reopened is not peer_card.canvas
    assert _records(stack, reopened) == records
    assert not _records(stack, page.peek_cards()[0].canvas)
