from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QLabel

from mf4_analyzer.ui.channel_config import ChannelConfigPreview, ChannelSelectionConfig
from mf4_analyzer.ui.channel_config_transfer import parse_transfer, serialize_transfer
from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS
from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog


def _config(config_id, name, channels, units=None, updated="2026-07-21T10:00:00+00:00"):
    return ChannelSelectionConfig.create(
        config_id,
        name,
        channels,
        now=updated,
        channel_unit_hints=units or {},
    )


def _preview():
    return ChannelConfigPreview(
        target_file_count=3,
        available_names=frozenset({"EPS_CRC", "Torque"}),
        unit_hints=(("EPS_CRC", ""), ("Torque", "Nm")),
        inconsistent_unit_names=frozenset({"Torque"}),
    )


def _dialog(qtbot, configs, selected_id=None, checked=None):
    dialog = ChannelConfigManagerDialog(
        configs,
        selected_id=selected_id,
        preview=_preview(),
        checked_channel_hints=checked or {"EPS_CRC": "", "Torque": "Nm"},
        id_factory=iter(("new-1", "new-2", "new-3", "new-4", "new-5")).__next__,
    )
    qtbot.addWidget(dialog)
    # Dirty dialogs must not open a live modal during test teardown.
    dialog._confirm_discard_changes = lambda: True
    dialog.show()
    return dialog


def test_manager_matches_html_sidebar_detail_and_preview_structure(qtbot):
    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC", "Missing", "Torque"), {"Torque": "Nm"})],
        "drive",
    )

    assert dialog.objectName() == "channelConfigManagerHtml"
    assert dialog.sidebar.width() == 310
    assert dialog.config_count.text() == "1"
    assert dialog.config_row_widget("drive").name_label.text() == "动力分析"
    assert dialog.config_row_widget("drive").count_label.text() == "3 CH"
    assert dialog.channel_table.columnCount() == 5
    assert dialog.channel_table.item(0, 1).text() == "EPS_CRC"
    assert dialog.channel_table.item(1, 3).text().endswith("缺失")
    assert dialog.channel_table.item(2, 2).text() == "Nm"
    assert dialog.detail_meta.text().startswith("3 个通道 · 更新于")
    assert dialog.match_chip.text().endswith("2 个已匹配")
    assert dialog.missing_chip.text().endswith("1 个缺失")
    assert dialog.btn_close.text() == "关闭"
    assert dialog.btn_save.text() == "保存更改"
    assert not hasattr(dialog, "config_table")


def test_normal_config_switch_clears_channel_filter_and_selection(qtbot):
    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC", "Torque")), _config("thermal", "温度", ("Temp",))],
        "drive",
    )
    dialog.channel_search.setText("Torque")
    dialog._set_channel_chosen("Torque", True)

    dialog._on_config_row_clicked("thermal")

    assert dialog.active_config_id == "thermal"
    assert dialog.channel_search.text() == ""
    assert dialog._chosen_channels == set()
    assert dialog.detail_title.text() == "温度"


def test_batch_selection_is_separate_from_active_config_and_exits_cleanly(qtbot):
    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC",)), _config("thermal", "温度", ("Temp",))],
        "drive",
    )

    dialog.btn_batch.click()
    row = dialog.config_row_widget("thermal")
    assert row is not None and row.checkbox is not None
    qtbot.mouseClick(row.checkbox, Qt.LeftButton)

    assert dialog.active_config_id == "drive"
    assert dialog._batch_config_ids == {"thermal"}
    assert dialog.btn_delete_configs.text() == "删除 1 个配置"
    assert dialog.btn_batch.isHidden()
    assert not dialog.batch_actions.isHidden()

    dialog.btn_exit_batch.click()
    assert dialog._batch_config_ids == set()
    assert dialog.active_config_id == "drive"
    assert not dialog.btn_batch.isHidden()


def test_channel_selection_add_remove_and_undo_stay_in_draft(qtbot):
    original = _config("drive", "动力分析", ("EPS_CRC", "Torque"), {"Torque": "Nm"})
    dialog = _dialog(qtbot, [original], "drive", checked={"EPS_CRC": "", "Torque": "Nm", "New": "V"})

    dialog._select_visible_channels()
    assert dialog._chosen_channels == {"EPS_CRC", "Torque"}
    assert dialog.btn_remove_channels.text() == "移除所选 2"
    dialog._clear_channel_selection()
    assert dialog._chosen_channels == set()
    dialog._add_current_checked()
    assert dialog.drafts[0].channel_names == ("EPS_CRC", "Torque", "New")

    dialog._remove_channels(("EPS_CRC",))
    assert dialog.drafts[0].channel_names == ("Torque", "New")
    assert original.channel_names == ("EPS_CRC", "Torque")
    assert dialog.toast.isVisible()
    assert dialog.toast_action.isVisible()
    dialog.toast_action.click()

    assert dialog.drafts[0].channel_names == ("EPS_CRC", "Torque", "New")


def test_new_copy_rename_and_delete_are_draft_only(qtbot, monkeypatch):
    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC",)), _config("thermal", "温度", ("Temp",))],
        "drive",
    )
    monkeypatch.setattr(dialog, "_open_rename_dialog", lambda: None)

    dialog.btn_new.click()
    assert dialog.active_config_id == "new-1"
    assert dialog.drafts[0].name == "未命名配置"
    assert dialog.drafts[0].channel_names == ("EPS_CRC", "Torque")
    assert dialog._rename_active_to("转向基础") is True
    dialog.btn_copy.click()
    assert dialog.drafts[0].name == "转向基础 副本"

    dialog.btn_delete_config.click()
    assert [config.name for config in dialog.drafts] == ["转向基础", "动力分析", "温度"]
    assert dialog.is_dirty() is True


def test_import_export_and_one_save_signal_use_current_draft(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", ("EPS_CRC",))], "drive")
    imported = _config("incoming", "转向基础", ("Torque",), {"Torque": "Nm"})

    result = dialog.import_payload(serialize_transfer([imported]), conflict_mode="keep")

    assert result.imported_count == 1
    assert [config.name for config in dialog.drafts] == ["动力分析", "转向基础"]
    assert b'"config_id"' not in dialog.export_payload(current_only=False)
    with qtbot.waitSignal(dialog.save_requested, timeout=200) as saved:
        dialog.btn_save.click()
    assert [item.name for item in saved.args[0]] == ["动力分析", "转向基础"]


def test_import_preview_exposes_file_conflict_and_two_counts(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", ("EPS_CRC",))], "drive")
    incoming = _config("incoming", "动力分析", ("Torque",), {"Torque": "Nm"})

    preview, conflict_mode = dialog._build_import_preview_dialog(
        "shared.tracelab-config.json", parse_transfer(serialize_transfer([incoming]))
    )
    qtbot.addWidget(preview)

    assert preview.minimumWidth() == 460
    assert conflict_mode.currentData() == "keep"
    file_meta = preview.findChild(QLabel, "channelConfigHtmlImportFile")
    assert "shared.tracelab-config.json" in file_meta.text()
    assert "1 个同名配置" in file_meta.text()
    assert [label.text() for label in preview.findChildren(QLabel, "channelConfigHtmlImportStatValue")] == ["1", "1"]


def test_empty_draft_config_cannot_emit_save_and_uses_toast_feedback(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", ("EPS_CRC",))], "drive")
    dialog._remove_channels(("EPS_CRC",))

    with qtbot.assertNotEmitted(dialog.save_requested):
        dialog.btn_save.click()
    assert "没有通道" in dialog.toast_text.text()


def test_dirty_reject_uses_one_confirm_seam(qtbot, monkeypatch):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", ("EPS_CRC",))], "drive")
    monkeypatch.setattr(dialog, "_open_rename_dialog", lambda: None)
    dialog.btn_new.click()
    monkeypatch.setattr(dialog, "_confirm_discard_changes", lambda: False)

    dialog.reject()
    assert dialog.isVisible()

    monkeypatch.setattr(dialog, "_confirm_discard_changes", lambda: True)
    dialog.reject()
    assert not dialog.isVisible()


def test_manager_geometry_preserves_html_controls_at_minimum_size(qtbot):
    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC", "Torque", "Long_Channel_Name"))],
        "drive",
    )
    assert dialog.size().width() == 1180
    assert dialog.size().height() == 680
    assert dialog.minimumSize().width() == 940
    assert dialog.minimumSize().height() == 680

    dialog.resize(940, 680)
    qtbot.wait(20)

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
    assert dialog.CONTROL_HEIGHT == CONTROL_HEIGHTS["base"]
    assert all(control.height() == CONTROL_HEIGHTS["base"] for control in controls)
    assert dialog.config_search.height() == CONTROL_HEIGHTS["base"]
    assert dialog.channel_search.height() == CONTROL_HEIGHTS["base"]
    assert dialog.sidebar.width() == 310
    assert dialog.config_summary.height() == 28
    assert dialog.view_summary.height() == 28
    assert dialog.channel_table.columnWidth(1) >= 240
    assert dialog.channel_table.rowHeight(0) == 49
    assert dialog.btn_save.geometry().bottom() <= dialog.height() - 10


def test_manager_ordinary_controls_render_on_base_track_with_production_qss(qapp, qtbot):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        dialog = _dialog(
            qtbot,
            [_config("drive", "动力分析", ("EPS_CRC", "Torque", "Long_Channel_Name"))],
            "drive",
        )
        qtbot.wait(20)
        controls = {
            "import": dialog.btn_import,
            "new": dialog.btn_new,
            "batch": dialog.btn_batch,
            "export": dialog.btn_export,
            "rename": dialog.btn_rename,
            "copy": dialog.btn_copy,
            "delete": dialog.btn_delete_config,
            "select": dialog.btn_select_channels,
            "clear": dialog.btn_clear_channels,
            "remove": dialog.btn_remove_channels,
            "add": dialog.btn_add_current,
            "close": dialog.btn_close,
            "save": dialog.btn_save,
            "config search": dialog.config_search,
            "channel search": dialog.channel_search,
        }
        assert {name: control.height() for name, control in controls.items()} == {
            name: CONTROL_HEIGHTS["base"] for name in controls
        }
    finally:
        qapp.setStyleSheet(previous)


def test_channel_checkbox_cell_remains_centered_for_selected_rows(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", ("EPS_CRC", "Torque"))], "drive")
    dialog._set_channel_chosen("Torque", True)

    selected_cell = dialog.channel_table.cellWidget(1, 0)
    check = selected_cell.findChild(QCheckBox)
    assert check.isChecked()
    assert abs(check.geometry().center().x() - selected_cell.rect().center().x()) <= 1
    assert selected_cell.property("chosen") is True
