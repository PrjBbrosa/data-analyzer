"""Left-pane right-click menu tests (Cockpit polish Stage 5)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from can_logger.p0.a2l_probe import MeasurementSummary
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
            available_events=("event_20ms",),
        ),
    )


def _action(menu, text: str):
    for action in menu.actions():
        if action.text() == text:
            return action
    raise AssertionError(f"missing action {text!r}; got {[a.text() for a in menu.actions()]}")


def test_left_pane_single_row_menu_actions(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)

    menu = pane._build_context_menu([_pool()[0]])
    assert [action.text() for action in menu.actions()] == [
        "复制名字",
        "复制地址",
        "跳到 A2L 源行",
    ]
    _action(menu, "复制名字").trigger()
    assert QApplication.clipboard().text() == "EngSpdAvg"

    _action(menu, "复制地址").trigger()
    assert QApplication.clipboard().text() == "0x40000000"


def test_left_pane_multi_row_menu_intersection_disabled_when_empty(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)
    for i in range(pane._list.count()):
        pane._list.item(i).setCheckState(Qt.Checked)

    menu = pane._build_context_menu(list(_pool()))
    assert "批量设 raster ..." not in [action.text() for action in menu.actions()]

    _action(menu, "复制为列表").trigger()
    assert QApplication.clipboard().text() == (
        "EngSpdAvg\trpm\t0x40000000\n"
        "EngTrqAct\tNm\t0x40000004"
    )
