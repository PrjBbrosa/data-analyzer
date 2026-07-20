from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
from mf4_analyzer.ui.widgets.channel_config_bar import ChannelConfigBar


def fake_config(config_id, name, channels):
    return ChannelSelectionConfig.create(
        config_id,
        name,
        [f"Channel_{idx}" for idx in range(channels)],
        now="2026-07-20T10:00:00+00:00",
    )


def test_config_bar_has_save_combo_apply_order(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)

    assert [bar.layout().itemAt(i).widget().objectName() for i in range(3)] == [
        "channelConfigSave",
        "channelConfigCombo",
        "channelConfigApply",
    ]


def test_selecting_config_does_not_emit_apply(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 4)])

    with qtbot.assertNotEmitted(bar.apply_requested):
        bar.select_config("a")

    assert bar.selected_config_id() == "a"


def test_apply_emits_only_selected_config_id(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 4)], selected_id="a")
    bar.set_context(has_checked=True, has_attached=True)

    with qtbot.waitSignal(bar.apply_requested, timeout=200) as emitted:
        bar.btn_apply.click()

    assert emitted.args == ["a"]


def test_context_controls_save_and_apply_independently(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 1)], selected_id="a")

    bar.set_context(has_checked=False, has_attached=True)
    assert not bar.btn_save.isEnabled()
    assert bar.btn_apply.isEnabled()

    bar.set_context(has_checked=True, has_attached=False)
    assert bar.btn_save.isEnabled()
    assert not bar.btn_apply.isEnabled()


def test_manage_sentinel_emits_and_restores_previous_selection(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 1)], selected_id="a")

    manage_index = bar.combo.findData(bar.MANAGE_SENTINEL)
    with qtbot.waitSignal(bar.manage_requested, timeout=200) as emitted:
        bar.combo.setCurrentIndex(manage_index)

    assert emitted.args == ["a"]
    assert bar.selected_config_id() == "a"


def test_combo_is_editable_for_name_search(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)

    assert bar.combo.isEditable()
    assert not bar.combo.insertPolicy()


def test_typed_nonexistent_name_cannot_apply_stale_selection(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 4)], selected_id="a")
    bar.set_context(has_checked=True, has_attached=True)

    bar.combo.setEditText("不存在的配置")

    assert bar.selected_config_id() is None
    assert not bar.btn_apply.isEnabled()
    with qtbot.assertNotEmitted(bar.apply_requested):
        bar.btn_apply.click()
