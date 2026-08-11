"""Direct coverage for the small ``ui.widgets`` members that so far only had
indirect smoke via the main window: ``Toast``, ``StatsStrip`` and
``StatisticsPanel``.

These three are the pieces the A1 split moves out of
``ui/widgets/__init__.py``; locking their observable behaviour here means the
move is guarded by assertions on text/visibility rather than by "it still
imports".

The Toast cases deliberately drive the fade timers by hand instead of waiting
out the real 3.5s hold: ``_hide_timer.timeout`` is the exact signal the live
timer emits, so triggering it exercises the production path without making the
suite sleep.
"""
import pytest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.widgets import StatisticsPanel, StatsStrip, Toast


def _stats(**over):
    """One channel's stats dict in the shape canvas.get_statistics emits."""
    base = {'min': -1.0, 'max': 2.0, 'mean': 0.5, 'rms': 1.25, 'std': 0.75,
            'p2p': 3.0}
    base.update(over)
    return base


@pytest.fixture
def host(qtbot):
    """A shown parent so child widgets report isVisible() truthfully.

    Must be a fixture rather than a helper call: pytest keeps the returned
    widget referenced for the whole test, whereas an inline
    ``Toast(_make_parent())`` would let the parent be collected and take its
    C++ children (the Toast) down with it.
    """
    w = QWidget()
    w.resize(400, 300)
    qtbot.addWidget(w)
    w.show()
    return w


# --------------------------------------------------------------------------
# Toast
# --------------------------------------------------------------------------

def test_toast_starts_hidden(qapp, qtbot, host):
    toast = Toast(host)
    assert not toast.isVisible()


def test_toast_show_message_sets_text_and_shows(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("已保存工程")
    assert toast.isVisible()
    assert toast._msg.text() == "已保存工程"


def test_toast_level_sets_property_and_glyph(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("磁盘将满", level='warning')
    assert toast.property('level') == 'warning'
    assert toast._icon.text() == Toast._GLYPHS['warning']


def test_toast_unknown_level_falls_back_to_info(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("未知等级", level='not-a-level')
    assert toast.property('level') == 'info'
    assert toast._icon.text() == Toast._GLYPHS['info']


def test_toast_hold_duration_is_level_specific(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("出错了", level='error')
    # error holds longest so the user can actually read it
    assert toast._hide_timer.isActive()
    assert Toast._HOLD_MS['error'] > Toast._HOLD_MS['info']


def test_toast_auto_hides_when_hold_timer_fires(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("稍后自动消失")
    assert toast.isVisible()
    # Fire the hold timer exactly as the real single-shot timer would.
    toast._hide_timer.timeout.emit()
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=3000)


def test_toast_second_message_replaces_instead_of_stacking(qapp, qtbot, host):
    toast = Toast(host)
    toast.show_message("第一条")
    toast.show_message("第二条")
    assert toast._msg.text() == "第二条"
    assert toast.isVisible()
    # One toast per parent: no extra Toast widgets were spawned.
    assert len(host.findChildren(Toast)) == 1


def test_toast_default_margin_clears_view_tab_strip(qapp, qtbot, host):
    """Default toast sits above status + ViewTabBar (+ hint), with breathing."""
    assert Toast.DEFAULT_BOTTOM_MARGIN >= 100
    toast = Toast(host)
    toast.show_message("已保存工程")
    assert toast.isVisible()
    clearance = host.height() - (toast.y() + toast.height())
    assert clearance == Toast.DEFAULT_BOTTOM_MARGIN
    # Status (40) + ViewTabBar (28) + hint (20) still fit under the toast.
    assert clearance >= 40 + 28 + 20


def test_toast_custom_bottom_margin_is_honored(qapp, qtbot, host):
    toast = Toast(host, bottom_margin=50)
    toast.show_message("预览不可用")
    assert host.height() - (toast.y() + toast.height()) == 50


def test_toast_reshow_cancels_pending_fade_out(qapp, qtbot, host):
    """Regression: a fade-out in flight must not auto-hide the next message.

    ``_fade_out`` connects ``_anim.finished`` to ``hide``; without the
    disconnect in ``show_message`` the *fade-in* of the replacement message
    would reach full opacity and immediately hide itself.
    """
    toast = Toast(host)
    toast.show_message("第一条")
    toast._fade_out()            # fade-out now in flight, finished->hide armed
    toast.show_message("第二条")  # must drop that stale connection
    qtbot.wait(400)              # comfortably longer than the 180ms animation
    assert toast.isVisible()
    assert toast._msg.text() == "第二条"


# --------------------------------------------------------------------------
# StatsStrip
# --------------------------------------------------------------------------

def test_stats_strip_starts_collapsed_with_placeholder(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    assert strip._lbl_summary.text() == "— 无通道 —"
    assert not strip._panel.isVisible()


def test_stats_strip_empty_dict_shows_placeholder(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    strip.update_stats({'spd': _stats()})
    strip.update_stats({})
    assert strip._lbl_summary.text() == "— 无通道 —"
    assert strip._panel.tree.topLevelItemCount() == 0


def test_stats_strip_none_does_not_raise(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    strip.update_stats(None)
    assert strip._lbl_summary.text() == "— 无通道 —"


def test_stats_strip_summary_lists_each_channel(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    strip.update_stats({'MotorSpeed': _stats(), 'SteerTorque': _stats(max=9.0)})
    text = strip._lbl_summary.text()
    assert 'MotorSpeed' in text and 'SteerTorque' in text
    assert 'min=-1' in text and 'rms=1.25' in text
    assert '9' in text                    # the overridden max made it through
    assert text.count('●') == 2           # one bullet per channel
    assert ' │ ' in text                  # channels joined, not concatenated


def test_stats_strip_toggle_expands_and_collapses_panel(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    strip.show()
    assert not strip._panel.isVisible()
    strip.toggle()
    assert strip._expanded and strip._panel.isVisible()
    strip.toggle()
    assert not strip._expanded and not strip._panel.isVisible()


def test_stats_strip_update_feeds_expanded_panel(qapp, qtbot):
    strip = StatsStrip()
    qtbot.addWidget(strip)
    strip.update_stats({'MotorSpeed': _stats()})
    assert strip._panel.tree.topLevelItemCount() == 1


# --------------------------------------------------------------------------
# StatisticsPanel
# --------------------------------------------------------------------------

def test_statistics_panel_headers(qapp, qtbot):
    panel = StatisticsPanel()
    qtbot.addWidget(panel)
    header = panel.tree.headerItem()
    labels = [header.text(i) for i in range(panel.tree.columnCount())]
    assert labels == ['Channel', 'Min', 'Max', 'Mean', 'RMS', 'Std', 'P-P']


def test_statistics_panel_populates_row_values(qapp, qtbot):
    panel = StatisticsPanel()
    qtbot.addWidget(panel)
    panel.update_stats({'MotorSpeed': _stats()})
    assert panel.tree.topLevelItemCount() == 1
    item = panel.tree.topLevelItem(0)
    assert item.text(0) == 'MotorSpeed'
    assert item.text(1) == '-1'      # min, %.3g
    assert item.text(2) == '2'       # max
    assert item.text(4) == '1.25'    # rms
    assert item.text(6) == '3'       # p2p


def test_statistics_panel_prefers_display_label(qapp, qtbot):
    """Composite (data_id, name) keys must render their human-readable label."""
    panel = StatisticsPanel()
    qtbot.addWidget(panel)
    key = ('fid-1', 'MotorSpeed')
    panel.update_stats({key: _stats(display_label='MotorSpeed [run1]')})
    assert panel.tree.topLevelItem(0).text(0) == 'MotorSpeed [run1]'


def test_statistics_panel_update_replaces_previous_rows(qapp, qtbot):
    panel = StatisticsPanel()
    qtbot.addWidget(panel)
    panel.update_stats({'a': _stats(), 'b': _stats()})
    assert panel.tree.topLevelItemCount() == 2
    panel.update_stats({'c': _stats()})
    assert panel.tree.topLevelItemCount() == 1
    assert panel.tree.topLevelItem(0).text(0) == 'c'


def test_statistics_panel_empty_stats_clears(qapp, qtbot):
    panel = StatisticsPanel()
    qtbot.addWidget(panel)
    panel.update_stats({'a': _stats()})
    panel.update_stats({})
    assert panel.tree.topLevelItemCount() == 0
