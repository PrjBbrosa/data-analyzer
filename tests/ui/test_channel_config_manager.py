from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog


def _config(config_id, name, channels, updated="2026-07-21T10:00:00+00:00"):
    return ChannelSelectionConfig.create(
        config_id, name, [f"Channel_{index}" for index in range(channels)], now=updated
    )


def _dialog(qtbot, configs, selected_id=None):
    dialog = ChannelConfigManagerDialog(configs, selected_id=selected_id)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_manager_lists_aligned_config_fields_and_selected_detail(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", 4)], "drive")

    assert dialog.table.columnCount() == 4
    assert dialog.table.item(0, 1).text() == "动力分析"
    assert dialog.table.item(0, 2).text() == "4 个"
    assert dialog.detail_title.text() == "动力分析"
    assert dialog.name_edit.text() == "动力分析"
    assert dialog.btn_rename.isEnabled()
    assert dialog.btn_copy.isEnabled()


def test_manager_searches_channel_names_and_preserves_selected_ids(qtbot):
    configs = [
        _config("drive", "动力分析", 4),
        ChannelSelectionConfig.create(
            "thermal", "温度核查", ["OilTemp"], now="2026-07-21T10:00:00+00:00"
        ),
    ]
    dialog = _dialog(qtbot, configs, "drive")

    dialog.search_edit.setText("oiltemp")

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "温度核查"
    assert dialog.selected_ids() == ("drive",)


def test_manager_emits_single_item_rename_and_copy(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", 4)], "drive")

    dialog.name_edit.setText("动力分析 v2")
    with qtbot.waitSignal(dialog.rename_requested, timeout=200) as renamed:
        dialog.btn_rename.click()
    with qtbot.waitSignal(dialog.copy_requested, timeout=200) as copied:
        dialog.btn_copy.click()

    assert renamed.args == ["drive", "动力分析 v2"]
    assert copied.args == ["drive"]


def test_manager_select_all_and_batch_delete_visible_configs(qtbot):
    dialog = _dialog(qtbot, [_config("drive", "动力分析", 4), _config("thermal", "温度核查", 2)])

    dialog.search_edit.setText("分析")
    dialog.btn_select_all.click()
    assert dialog.selected_ids() == ("drive",)
    with qtbot.waitSignal(dialog.delete_requested, timeout=200) as deleted:
        dialog.btn_delete.click()

    assert deleted.args == [("drive",)]
