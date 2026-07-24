"""Render the approved HTML-parity configuration manager without settings I/O.

The probe intentionally constructs only the draft dialog, applies the shipped
stylesheet, and asserts the geometry that was approved in the HTML prototype.
Run with ``QT_QPA_PLATFORM=offscreen``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.channel_config import ChannelConfigPreview, ChannelSelectionConfig
from mf4_analyzer.ui.channel_config_transfer import parse_transfer, serialize_transfer
from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog
from mf4_analyzer.ui_kit import load_stylesheet


def _configs() -> list[ChannelSelectionConfig]:
    return [
        ChannelSelectionConfig.create(
            "steering",
            "转向基础信号",
            ("EPS_1_CRC", "EPS_DrvrSteerTq", "EPS_DrvrSteerTqVld", "EPS_TqCtrlAvl"),
            now="2026-07-24T10:00:00+00:00",
            channel_unit_hints={"EPS_DrvrSteerTq": "Nm"},
        ),
        ChannelSelectionConfig.create(
            "safety",
            "安全状态与计数器",
            ("EPS_1_CRC", "EPS_RollgCntr1", "EPS_Resd1", "EPS_Sts"),
            now="2026-07-24T10:00:00+00:00",
        ),
        ChannelSelectionConfig.create(
            "thermal",
            "温度与电压核查",
            ("MotorTemp", "SupplyVoltage", "PowerStageTemp"),
            now="2026-07-24T10:00:00+00:00",
            channel_unit_hints={"MotorTemp": "°C", "SupplyVoltage": "V"},
        ),
        ChannelSelectionConfig.create(
            "long",
            "长名称配置用于验证侧栏省略与通道表可读宽度",
            ("Very_Long_Steering_Channel_Name_For_Width_Validation",),
            now="2026-07-24T10:00:00+00:00",
        ),
    ]


def _preview() -> ChannelConfigPreview:
    return ChannelConfigPreview(
        target_file_count=3,
        available_names=frozenset(
            {
                "EPS_1_CRC",
                "EPS_DrvrSteerTq",
                "EPS_DrvrSteerTqVld",
                "EPS_RollgCntr1",
                "EPS_Resd1",
                "MotorTemp",
                "SupplyVoltage",
            }
        ),
        unit_hints=(
            ("EPS_DrvrSteerTq", "Nm"),
            ("MotorTemp", "°C"),
            ("SupplyVoltage", "V"),
        ),
        inconsistent_unit_names=frozenset({"EPS_DrvrSteerTq"}),
    )


def _render(dialog: ChannelConfigManagerDialog, path: Path) -> None:
    dialog.show()
    QApplication.processEvents()
    QApplication.processEvents()
    if not dialog.grab().save(str(path)):
        raise RuntimeError(f"failed to save {path}")


def _render_popover(dialog, path: Path) -> None:
    dialog.show()
    QApplication.processEvents()
    QApplication.processEvents()
    if not dialog.grab().save(str(path)):
        raise RuntimeError(f"failed to save {path}")


def _assert_geometry(dialog: ChannelConfigManagerDialog) -> None:
    controls = (
        dialog.btn_import,
        dialog.btn_new,
        dialog.btn_batch,
        dialog.btn_export,
        dialog.btn_rename,
        dialog.btn_copy,
        dialog.btn_delete_config,
        dialog.btn_select_channels,
        dialog.btn_clear_channels,
        dialog.btn_remove_channels,
        dialog.btn_add_current,
        dialog.btn_close,
        dialog.btn_save,
    )
    if any(control.height() != dialog.CONTROL_HEIGHT for control in controls):
        raise AssertionError("HTML manager controls do not share the fixed 36px height")
    if dialog.sidebar.width() != 310:
        raise AssertionError(f"sidebar is {dialog.sidebar.width()}px instead of 310px")
    if dialog.config_summary.height() != 28 or dialog.view_summary.height() != 28:
        raise AssertionError("header summary tokens were stretched beyond 28px")
    if dialog.channel_table.columnWidth(1) < 240:
        raise AssertionError("channel-name column is narrower than the approved 240px")
    if dialog.btn_save.geometry().bottom() > dialog.height() - 10:
        raise AssertionError("footer save control is clipped")
    if dialog.channel_table.rowHeight(0) != 49:
        raise AssertionError("channel rows do not retain their approved 49px height")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(
            REPO_ROOT
            / "docs"
            / "analyzer"
            / "verify"
            / "2026-07-24-channel-config-manager-v2"
        ),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)
    dialog = ChannelConfigManagerDialog(
        _configs(),
        selected_id="steering",
        preview=_preview(),
        checked_channel_hints={"EPS_1_CRC": "", "EPS_DrvrSteerTq": "Nm"},
        id_factory=iter(("draft-1", "draft-2")).__next__,
    )
    dialog.resize(1180, 790)
    _render(dialog, out_dir / "channel-config-manager-html-default-1180x790.png")
    _assert_geometry(dialog)

    dialog._set_channel_chosen("EPS_DrvrSteerTq", True)
    _render(dialog, out_dir / "channel-config-manager-html-selected-1180x790.png")
    _assert_geometry(dialog)
    dialog._clear_channel_selection()

    import_source = ChannelSelectionConfig.create(
        "transfer",
        "转向基础信号",
        ("ImportedSignal", "Torque"),
        now="2026-07-24T10:00:00+00:00",
        channel_unit_hints={"Torque": "Nm"},
    )
    import_dialog, import_combo = dialog._build_import_preview_dialog(
        "incoming.tracelab-config.json",
        parse_transfer(serialize_transfer([import_source])),
    )
    _render_popover(import_dialog, out_dir / "channel-config-manager-html-import-preview.png")
    if import_dialog.width() < 460 or import_combo.height() != dialog.CONTROL_HEIGHT:
        raise AssertionError("import preview no longer retains its approved compact geometry")
    import_dialog.reject()

    dialog._remove_channels(("EPS_TqCtrlAvl",))
    dialog._enter_batch_mode()
    row = dialog.config_row_widget("safety")
    if row is None or row.checkbox is None:
        raise AssertionError("batch configuration row did not expose its checkbox")
    row.checkbox.setChecked(True)
    dialog.resize(940, 680)
    _render(dialog, out_dir / "channel-config-manager-html-dirty-batch-940x680.png")
    _assert_geometry(dialog)
    print(f"saved: {out_dir}")
    print(
        "geometry: "
        f"default=1180x790 minimum=940x680 sidebar={dialog.sidebar.width()} "
        f"channel_width={dialog.channel_table.columnWidth(1)} "
        f"row_height={dialog.channel_table.rowHeight(0)} "
        f"control_height={dialog.CONTROL_HEIGHT}"
    )
    dialog._closing = True
    dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
