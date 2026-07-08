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


def _make_pool(n: int = 3) -> tuple[MeasurementSummary, ...]:
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}",
            address=0x40000000 + 4 * i,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=("event_10ms",),
        )
        for i in range(n)
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


def test_context_menu_offers_pin_toggle_for_selected(qtbot):
    """spec 2026-07-08 §G6: provider 存在且已选中时出 pin 开关项。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(3))
    pane._set_measurement_selected("Sig_00", True)
    pane.set_pin_state_provider(lambda name: name == "Sig_00")
    fired = []
    pane.pin_toggle_requested.connect(fired.append)

    menu = pane._build_context_menu([pane._pool[0]])
    labels = [a.text() for a in menu.actions()]
    assert "取消固定实时显示" in labels
    next(a for a in menu.actions() if a.text() == "取消固定实时显示").trigger()
    assert fired == ["Sig_00"]

    # 未选中的测量不出 pin 项。
    menu2 = pane._build_context_menu([pane._pool[1]])
    assert all("固定" not in a.text() for a in menu2.actions())
