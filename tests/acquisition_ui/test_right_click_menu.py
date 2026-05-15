"""Left-pane right-click menu tests (Cockpit polish Stage 5)."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.config_store import load_or_default
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


def _write_min_config(path: Path) -> None:
    path.write_text(
        """version: 1
a2l_path: "demo.a2l"
favorites: []
selected: []
filter_state:
  has_daq: true
  show_selected_only: false
  group: null
  datatype: null
threshold_overrides: {}
""",
        encoding="utf-8",
    )


def test_left_pane_single_row_menu_actions(qapp):
    pane = LeftPane()
    pane.set_pool(_pool(), a2l_has_daq_events=True)

    menu = pane._build_context_menu([_pool()[0]])
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
    raster_action = _action(menu, "批量设 raster ...")
    assert raster_action.isEnabled() is False

    _action(menu, "复制为列表").trigger()
    assert QApplication.clipboard().text() == (
        "EngSpdAvg\trpm\t0x40000000\n"
        "EngTrqAct\tNm\t0x40000004"
    )


def test_left_pane_favorite_toggle_writes_acquisition_config(qapp, tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    _write_min_config(cfg)

    pane = LeftPane()
    pane.set_config_path(cfg)
    pane.set_pool(_pool(), a2l_has_daq_events=True)

    menu = pane._build_context_menu([_pool()[0]])
    _action(menu, "⭐ 收藏").trigger()

    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.favorites == [
        {"name": "EngSpdAvg", "address_hex": "0x40000000"}
    ]

    menu = pane._build_context_menu([_pool()[0]])
    _action(menu, "取消收藏").trigger()
    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.favorites == []
