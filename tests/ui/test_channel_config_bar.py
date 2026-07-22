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
    assert bar.combo.maxVisibleItems() == 8
    assert bar.combo.property("popupStyle") == "channel-config"
    assert bar.combo.property("popupMinWidth") == 320


def test_config_popup_items_keep_names_and_counts_in_separate_roles(qtbot):
    from mf4_analyzer.ui.widgets.channel_config_bar import (
        CHANNEL_COUNT_ROLE,
        CONFIG_NAME_ROLE,
        ITEM_KIND_ROLE,
    )

    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([fake_config("a", "动力分析", 4)])

    assert bar.combo.itemText(1) == "动力分析"
    assert bar.combo.itemData(1, CONFIG_NAME_ROLE) == "动力分析"
    assert bar.combo.itemData(1, CHANNEL_COUNT_ROLE) == 4
    assert bar.combo.itemData(1, ITEM_KIND_ROLE) == "config"
    assert bar.combo.itemText(bar.combo.count() - 1) == "管理通道配置…"


def test_config_combo_opens_above_its_bottom_bar_anchor(qtbot):
    from PyQt5.QtCore import QCoreApplication

    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.set_configs([
        fake_config("a", "动力分析", 4),
        fake_config("b", "转向回正", 3),
        fake_config("c", "温度核查", 5),
    ])
    bar.resize(280, 38)
    bar.show()
    QCoreApplication.processEvents()

    bar.combo.showPopup()
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()

    popup = bar.combo.view().window()
    anchor_y = bar.combo.mapToGlobal(bar.combo.rect().topLeft()).y()
    # Native popup borders may occupy the final 1–2 logical pixels.
    assert popup.y() + popup.height() <= anchor_y + 3
    assert popup.width() >= 320
    bar.combo.hidePopup()


def test_config_actions_match_the_selector_geometry(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.resize(360, 46)
    bar.show()

    assert bar.btn_save.minimumWidth() == bar.btn_apply.minimumWidth() == 64
    assert bar.btn_save.maximumWidth() == bar.btn_apply.maximumWidth() == 64
    assert bar.combo.minimumWidth() == 132
    assert bar.btn_save.width() == 64
    assert bar.btn_apply.width() == 64
    assert bar.combo.width() == 220
    assert bar.btn_save.height() == bar.combo.height() == bar.btn_apply.height() == 32
    assert bar.btn_save.y() == bar.combo.y() == bar.btn_apply.y()


def test_popup_shows_all_four_configs_without_a_scrollbar(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    bar.resize(640, 46)
    bar.set_configs([
        fake_config("a", "1", 3),
        fake_config("b", "test", 2),
        fake_config("c", "2", 4),
        fake_config("d", "33", 3),
    ])
    bar.show()

    bar.combo.showPopup()
    qtbot.wait(10)

    view = bar.combo.view()
    assert not view.verticalScrollBar().isVisible()
    assert view.height() >= sum(view.sizeHintForRow(i) for i in range(7))
    bar.combo.hidePopup()


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
