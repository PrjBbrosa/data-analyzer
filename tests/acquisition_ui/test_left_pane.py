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

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QComboBox, QLabel, QToolButton, QWidget

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


def _multi_event_pool() -> tuple[MeasurementSummary, ...]:
    return (
        MeasurementSummary(
            name="EngSpdAvg",
            address=0x40000000,
            datatype="UWORD",
            unit="rpm",
            conversion="",
            available_events=("event_100ms", "event_10ms", "event_1ms"),
        ),
        MeasurementSummary(
            name="EngTrqAct",
            address=0x40000004,
            datatype="SWORD",
            unit="Nm",
            conversion="",
            available_events=("event_100ms", "event_10ms"),
        ),
    )


def _make_pool(n: int) -> tuple[MeasurementSummary, ...]:
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}",
            address=0x40000000 + 4 * i,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=("event_10ms", "event_100ms"),
        )
        for i in range(n)
    )


def _row_event_combo(pane: LeftPane, name: str) -> QComboBox:
    for combo in pane.findChildren(QComboBox, "measurementEventSelect"):
        if combo.property("measurementName") == name:
            return combo
    raise AssertionError(f"missing row event combo for {name!r}")


def _row_widget(pane: LeftPane, index: int) -> QWidget:
    widget = pane._list.itemWidget(pane._list.item(index))
    assert widget is not None
    return widget


def test_pool_shows_with_daq_filter_default_on(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    assert pane._header.text() == "A2L Measurement"
    assert pane._search.placeholderText() == "搜索 name / 0x40A..."
    # 有 DAQ defaults on ⇒ OnlyCal (no available_events) is filtered.
    assert pane._list.count() == 2
    first_row = _row_widget(pane, 0)
    assert first_row.findChild(QLabel, "measurementName").text() == "EngSpdAvg"
    assert "rpm" in first_row.findChild(QLabel, "measurementDetail").text()
    assert _row_event_combo(pane, "EngSpdAvg").currentText() == "10ms"


def test_disabled_daq_chip_on_no_daq_a2l(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=False)
    assert pane._has_daq_chip.isChecked() is False
    assert pane._has_daq_chip.isEnabled() is False
    assert pane._has_daq_chip.toolTip() == "该 A2L 不含 DAQ_EVENT 信息"
    # All rows visible.
    assert pane._list.count() == 3


def test_search_uses_match_spans_from_hit(qapp):
    from mf4_analyzer.acquisition_ui.widgets.left_pane import _highlight_name_html

    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    # Drive the search.
    pane._search.setText("Spd")
    pane._refresh_list()
    # Only EngSpdAvg matches.
    assert pane._list.count() == 1
    item = pane._list.item(0)
    row = pane._list.itemWidget(item)
    name_label = row.findChild(QLabel, "measurementName")
    # The visible label carries the match spans we got from search_measurements.
    pool = [m for m in _pool() if m.available_events]
    hits = search_measurements("Spd", pool)
    assert hits, "expected at least one hit"
    spans = hits[0].match_spans
    assert name_label.text() == _highlight_name_html("EngSpdAvg", spans)
    assert name_label.textFormat() == Qt.RichText


def test_selection_change_emits_signal(qapp):
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


def test_filter_chip_row_hides_unfinished_filters(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    pane.show()
    qapp.processEvents()

    chip_texts = [
        chip.text()
        for chip in pane.findChildren(QToolButton, "filterChip")
        if chip.isVisible()
    ]
    assert chip_texts == ["只看已选", "有 DAQ"]
    assert pane.minimumWidth() == 320
    assert pane.maximumWidth() == 460


def test_summary_updates_total_visible_selected_counts(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    summary = pane.findChild(QLabel, "leftPaneSummary")

    assert summary is not None
    assert summary.text() == "3 · 显示 2 · 选 0"
    pane._list.item(0).setCheckState(Qt.Checked)
    assert summary.text() == "3 · 显示 2 · 选 1"


def test_batch_event_selector_applies_to_all_selected_rows(qapp):
    pane = LeftPane()
    pane.set_pool(_multi_event_pool(), a2l_has_daq_events=True)
    pane.show()
    qapp.processEvents()
    batch_combo = pane.findChild(QComboBox, "batchEventSelect")

    assert batch_combo is not None
    assert batch_combo.isVisible() is False

    pane._list.item(0).setCheckState(Qt.Checked)
    pane._list.item(1).setCheckState(Qt.Checked)
    qapp.processEvents()

    assert batch_combo.isVisible() is True
    assert batch_combo.isEnabled() is True
    assert batch_combo.minimumWidth() >= 112
    assert [batch_combo.itemText(i) for i in range(batch_combo.count())] == [
        "100ms",
        "10ms",
    ]

    batch_combo.setCurrentText("10ms")
    qapp.processEvents()

    assert {m.name: m.event for m in pane.current_selection()} == {
        "EngSpdAvg": "event_10ms",
        "EngTrqAct": "event_10ms",
    }
    assert "事件 10ms × 2" in pane._footer.text()


def test_row_event_selector_overrides_one_selected_channel(qapp):
    pane = LeftPane()
    pane.set_pool(_multi_event_pool(), a2l_has_daq_events=True)
    pane.show()
    qapp.processEvents()
    pane._list.item(0).setCheckState(Qt.Checked)
    pane._list.item(1).setCheckState(Qt.Checked)
    qapp.processEvents()

    _row_event_combo(pane, "EngSpdAvg").setCurrentText("1ms")
    qapp.processEvents()
    selected = {m.name: m.event for m in pane.current_selection()}
    assert selected == {
        "EngSpdAvg": "event_1ms",
        "EngTrqAct": "event_100ms",
    }

    batch_combo = pane.findChild(QComboBox, "batchEventSelect")
    assert batch_combo is not None
    assert batch_combo.currentText() == "混合"
    assert "选 2" in pane._footer.text()
    assert "CAN 估算" in pane._footer.text()
    assert "事件 1ms × 1" in pane._footer.text()
    assert "100ms × 1" in pane._footer.text()


def test_checkbox_toggle_preserves_scroll_and_widgets(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(50))
    pane.resize(420, 400)
    pane.show()
    qtbot.waitExposed(pane)
    sb = pane._list.verticalScrollBar()
    sb.setValue(sb.maximum())
    anchor = sb.value()
    assert anchor > 0
    last_item = pane._list.item(pane._list.count() - 1)
    widget_before = pane._list.itemWidget(last_item)
    checkbox = widget_before.findChild(QCheckBox, "measurementCheckBox")
    checkbox.click()
    assert sb.value() == anchor
    assert pane._list.itemWidget(pane._list.item(pane._list.count() - 1)) is widget_before
    assert [m.name for m in pane.current_selection()] == ["Sig_49"]


def test_batch_event_change_updates_rows_in_place(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    for name in ("Sig_00", "Sig_01"):
        pane._set_measurement_selected(name, True)
    item = pane._row_items["Sig_01"]
    widget_before = pane._list.itemWidget(item)
    combo = pane._batch_bar.event_combo
    idx = combo.findData("event_100ms")
    combo.setCurrentIndex(idx)
    assert pane._list.itemWidget(pane._row_items["Sig_01"]) is widget_before
    row_combo = widget_before.findChild(QComboBox, "measurementEventSelect")
    assert row_combo.currentData() == "event_100ms"


def test_set_frozen_disables_row_controls_in_place(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(3))
    pane.set_frozen(True)
    for item in pane._row_items.values():
        row = pane._list.itemWidget(item)
        assert not row.findChild(QCheckBox, "measurementCheckBox").isEnabled()
        assert not row.findChild(QComboBox, "measurementEventSelect").isEnabled()
    pane.set_frozen(False)
    row = pane._list.itemWidget(pane._row_items["Sig_00"])
    assert row.findChild(QCheckBox, "measurementCheckBox").isEnabled()


def test_only_selected_rebuild_restores_scroll(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(50))
    pane.resize(420, 400)
    pane.show()
    qtbot.waitExposed(pane)
    for i in range(40, 50):
        pane._set_measurement_selected(f"Sig_{i}", True)
    pane._only_selected_chip.setChecked(True)
    sb = pane._list.verticalScrollBar()
    sb.setValue(sb.maximum())
    anchor = sb.value()
    pane._set_measurement_selected("Sig_49", False)
    assert sb.value() == min(anchor, sb.maximum())


def test_search_highlight_renders_in_name_label(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    pane._search.setText("Sig_00")
    item = pane._row_items["Sig_00"]
    row = pane._list.itemWidget(item)
    name_label = row.findChild(QLabel, "measurementName")
    assert "<span" in name_label.text()
    pane._search.setText("")
    row = pane._list.itemWidget(pane._row_items["Sig_00"])
    assert "<span" not in row.findChild(QLabel, "measurementName").text()


def test_highlight_name_html_escapes_and_wraps():
    from mf4_analyzer.acquisition_ui.widgets.left_pane import _highlight_name_html

    out = _highlight_name_html("a<b", [(0, 1)])
    assert out == '<span style="color:#1769E0;font-weight:600;">a</span>&lt;b'
    assert _highlight_name_html("abc", []) == "abc"
