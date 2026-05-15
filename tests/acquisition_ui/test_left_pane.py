"""Left-pane tests (Stage 4).

Verifies:

- Pool seeding shows rows.
- Search uses ``SearchHit.match_spans`` (the pane never re-runs a
  substring match).
- ``有 DAQ`` chip fallback: when ``a2l_has_daq_events`` is False the
  chip flips off + disabled with the spec tooltip.
- Selection mutations emit ``selection_changed``.
- Recording freeze blocks new selections.
"""

from __future__ import annotations

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.search import search_measurements
from mf4_analyzer.acquisition_ui.widgets.left_pane import LeftPane


def _pool() -> tuple[MeasurementSummary, ...]:
    return (
        MeasurementSummary(
            name="EngSpdAvg",
            address=0x40000000,
            datatype="UWORD",
            unit="rpm",
            conversion="",
            available_events=("event_10ms",),
        ),
        MeasurementSummary(
            name="EngTrqAct",
            address=0x40000004,
            datatype="SWORD",
            unit="Nm",
            conversion="",
            available_events=("event_10ms",),
        ),
        MeasurementSummary(
            name="OnlyCal",
            address=0x40000010,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=(),
        ),
    )


def test_pool_shows_with_daq_filter_default_on(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    # 有 DAQ defaults on ⇒ OnlyCal (no available_events) is filtered.
    assert pane._list.count() == 2


def test_disabled_daq_chip_on_no_daq_a2l(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=False)
    assert pane._has_daq_chip.isChecked() is False
    assert pane._has_daq_chip.isEnabled() is False
    assert pane._has_daq_chip.toolTip() == "该 A2L 不含 DAQ_EVENT 信息"
    # All rows visible.
    assert pane._list.count() == 3


def test_search_uses_match_spans_from_hit(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    # Drive the search.
    pane._search.setText("Spd")
    pane._refresh_list()
    # Only EngSpdAvg matches.
    assert pane._list.count() == 1
    item = pane._list.item(0)
    # Tooltip carries the match spans we got from search_measurements.
    pool = [m for m in _pool() if m.available_events]
    hits = search_measurements("Spd", pool)
    assert hits, "expected at least one hit"
    spans = hits[0].match_spans
    expected_tt = "匹配: " + ", ".join(f"{s}:{e}" for s, e in spans)
    assert item.toolTip() == expected_tt


def test_selection_change_emits_signal(qapp):
    from PyQt5.QtCore import Qt

    pane = LeftPane()
    fired = []
    pane.selection_changed.connect(lambda: fired.append(True))
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    fired_so_far = len(fired)
    # Toggle one item.
    item = pane._list.item(0)
    item.setCheckState(Qt.Checked)
    assert len(fired) == fired_so_far + 1
    assert len(pane.current_selection()) == 1


def test_freeze_blocks_selection_changes(qapp):
    from PyQt5.QtCore import Qt

    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    item = pane._list.item(0)
    pane.set_frozen(True)
    item.setCheckState(Qt.Checked)
    # Frozen pane reverts the check state; nothing is selected.
    assert pane.current_selection() == []
    pane.set_frozen(False)
    item.setCheckState(Qt.Checked)
    assert len(pane.current_selection()) == 1
