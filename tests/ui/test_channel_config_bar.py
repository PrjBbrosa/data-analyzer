from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
from mf4_analyzer.ui.widgets.channel_config_bar import ChannelConfigBar
import pytest
from PyQt5.QtCore import Qt


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
    assert bar.combo.minimumWidth() == ChannelConfigBar.COMBO_MIN_WIDTH == 100
    assert bar.btn_save.width() == 64
    assert bar.btn_apply.width() == 64
    assert bar.combo.width() == 220
    assert bar.height() == ChannelConfigBar.CONTROL_HEIGHT == 28
    assert bar.btn_save.height() == bar.combo.height() == bar.btn_apply.height() == 28
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


def test_config_bar_shares_the_time_domain_view_rail_height(qtbot):
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.file_navigator import FileNavigator
    from mf4_analyzer.ui.view_state import ViewManager
    from mf4_analyzer.ui.view_tabbar import RAIL_HEIGHT, ViewTabBar
    from mf4_analyzer.ui.widgets.ultraview_entry import ENTRY_HEIGHT
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(QApplication.instance())

    nav = FileNavigator()
    qtbot.addWidget(nav)
    bar = nav.channel_list.config_bar
    tabbar = ViewTabBar(ViewManager(), section="time")
    qtbot.addWidget(tabbar)
    nav.show()
    tabbar.show()
    QApplication.processEvents()

    assert ChannelConfigBar.CONTROL_HEIGHT == 28
    assert ENTRY_HEIGHT == RAIL_HEIGHT == 30
    assert tabbar.height() == ENTRY_HEIGHT
    assert bar.height() == bar.btn_save.height() == bar.combo.height() == 28
    assert nav.layout().contentsMargins().bottom() == 3
    assert nav.channel_list.layout().contentsMargins().bottom() == 2
    assert nav.channel_list.layout().contentsMargins().top() == 8
    assert bar.height() + nav.channel_list.layout().contentsMargins().bottom() == ENTRY_HEIGHT


def test_config_bar_top_aligns_with_view_rail_in_navigator_width_host(qtbot):
    from PyQt5.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

    from mf4_analyzer.ui.file_navigator import FileNavigator
    from mf4_analyzer.ui.view_state import ViewManager
    from mf4_analyzer.ui.view_tabbar import RAIL_HEIGHT, ViewTabBar
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(QApplication.instance())

    host = QWidget()
    host.setFixedSize(850, 520)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    nav = FileNavigator(host)
    nav.setFixedWidth(288)
    right = QWidget(host)
    right_lay = QVBoxLayout(right)
    right_lay.setContentsMargins(0, 0, 0, 0)
    right_lay.setSpacing(0)
    filler = QWidget(right)
    filler.setStyleSheet("background: #ffffff;")
    tabbar = ViewTabBar(ViewManager(), right, section="time")
    right_lay.addWidget(filler, 1)
    right_lay.addWidget(tabbar, 0)
    row.addWidget(nav, 0)
    row.addWidget(right, 1)

    qtbot.addWidget(host)
    host.show()
    QApplication.processEvents()
    QApplication.processEvents()

    bar = nav.channel_list.config_bar
    bar.set_configs([fake_config("a", "转向基础信号", 3)], selected_id="a")
    bar.set_context(has_checked=True, has_attached=True)
    QApplication.processEvents()

    btn_top = bar.btn_save.mapTo(host, bar.btn_save.rect().topLeft()).y()
    rail_top = tabbar.mapTo(host, tabbar.rect().topLeft()).y()
    btn_mid = bar.btn_save.mapTo(host, bar.btn_save.rect().center()).y()
    rail_mid = tabbar.mapTo(host, tabbar.rect().center()).y()
    # FileNavigator keeps a 3px shell inset so the outer rounded corner
    # stays visible (test_surface_panel_children_leave_outer_shell_visible).
    # The 28px controls + 2px host inset share the 30px rail; leftover is
    # that shell, not a second misaligned band.
    leftover = rail_top - btn_top
    assert bar.btn_save.height() == 28
    assert tabbar.height() == RAIL_HEIGHT
    assert 2 <= leftover <= 5
    assert abs(btn_mid - rail_mid) <= 4


def test_unselected_config_shows_search_placeholder_from_start(qtbot):
    bar = ChannelConfigBar()
    qtbot.addWidget(bar)
    assert bar.combo.currentText() == ""
    assert bar.combo.lineEdit().placeholderText() == "输入关键词搜索配置"
    bar.set_configs([fake_config("a", "动力分析", 4)])
    assert bar.combo.currentText() == ""
    bar.select_config("a")
    assert bar.combo.currentText() == "动力分析"
    bar.select_config(None)
    assert bar.combo.currentText() == ""
    bar.combo.setEditText("动力")
    assert bar.combo.currentText() == "动力"
    assert bar.selected_config_id() is None


def _widget_rect_in(host, widget):
    from PyQt5.QtCore import QPoint, QRect

    return QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())


def _combo_arrow_rect_in(host, combo):
    from PyQt5.QtCore import QPoint, QRect
    from PyQt5.QtWidgets import QStyle, QStyleOptionComboBox

    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    arrow = combo.style().subControlRect(
        QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, combo,
    )
    return QRect(combo.mapTo(host, arrow.topLeft()), arrow.size())


def _assert_navigator_rows_unclipped(nav):
    from PyQt5.QtWidgets import QApplication

    bar = nav.channel_list.config_bar
    edit = nav.channel_list.btn_edit
    save = _widget_rect_in(nav, bar.btn_save)
    combo = _widget_rect_in(nav, bar.combo)
    apply = _widget_rect_in(nav, bar.btn_apply)
    arrow = _combo_arrow_rect_in(nav, bar.combo)
    edit_rect = _widget_rect_in(nav, edit)

    assert not save.intersects(combo)
    assert not combo.intersects(apply)
    assert not save.intersects(apply)
    assert not arrow.isEmpty()
    assert combo.contains(arrow.center())
    assert not apply.intersects(arrow)
    local_arrow = bar.combo.mapFrom(nav, arrow.center())
    assert bar.combo.rect().contains(local_arrow)
    assert not apply.contains(arrow.center())

    hint = edit.minimumSizeHint()
    assert edit.width() >= hint.width()
    assert edit.height() >= hint.height()
    fm = edit.fontMetrics()
    text_w = fm.horizontalAdvance(edit.text())
    icon_w = edit.iconSize().width() if not edit.icon().isNull() else 0
    assert edit.contentsRect().width() >= text_w
    assert edit.contentsRect().width() >= icon_w
    assert edit_rect.right() <= nav.rect().right()
    QApplication.processEvents()


def _show_navigator_splitter(qtbot, qapp, requested_width, host_width=980):
    from PyQt5.QtWidgets import QApplication, QSplitter, QWidget

    from mf4_analyzer.ui.file_navigator import FileNavigator
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(qapp)
    host = QWidget()
    host.resize(host_width, 640)
    splitter = QSplitter(Qt.Horizontal, host)
    nav = FileNavigator(splitter)
    rest = QWidget(splitter)
    rest.setMinimumWidth(400)
    splitter.addWidget(nav)
    splitter.addWidget(rest)
    splitter.setCollapsible(0, True)
    splitter.setSizes([requested_width, max(400, host_width - requested_width)])
    layout_host = host
    from PyQt5.QtWidgets import QHBoxLayout
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(splitter)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    QApplication.processEvents()
    QApplication.processEvents()
    return layout_host, splitter, nav


@pytest.mark.parametrize("requested, expected_min", [(220, 288), (250, 288), (288, 288)])
def test_navigator_splitter_widths_keep_config_and_edit_unclipped(
    qapp, qtbot, requested, expected_min,
):
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.file_navigator import (
        NAVIGATOR_DEFAULT_EXPANDED_WIDTH,
        NAVIGATOR_MIN_EXPANDED_WIDTH,
    )

    qapp.setStyle("Fusion")
    host, splitter, nav = _show_navigator_splitter(qtbot, qapp, requested)
    nav_min = nav.expanded_minimum_width()
    assert nav_min >= NAVIGATOR_MIN_EXPANDED_WIDTH
    assert nav.default_expanded_width() == NAVIGATOR_DEFAULT_EXPANDED_WIDTH == 288
    QApplication.processEvents()
    actual = splitter.sizes()[0]
    assert actual >= nav_min
    if requested >= NAVIGATOR_DEFAULT_EXPANDED_WIDTH:
        assert actual >= NAVIGATOR_DEFAULT_EXPANDED_WIDTH - 2
    else:
        assert actual >= expected_min
    assert nav.width() >= nav_min
    _assert_navigator_rows_unclipped(nav)
    edit = nav.channel_list.btn_edit
    dpr = float(nav.devicePixelRatioF() or 1.0)
    grab = edit.grab()
    assert grab.width() in {
        edit.width(),
        int(round(edit.width() * dpr)),
        int(edit.width() * dpr),
    }


def test_navigator_wide_narrow_restore_keeps_controls_unclipped(qapp, qtbot):
    from PyQt5.QtWidgets import QApplication

    qapp.setStyle("Fusion")
    host, splitter, nav = _show_navigator_splitter(qtbot, qapp, 420)
    _assert_navigator_rows_unclipped(nav)
    splitter.setSizes([288, 692])
    QApplication.processEvents()
    QApplication.processEvents()
    assert splitter.sizes()[0] >= nav.expanded_minimum_width()
    _assert_navigator_rows_unclipped(nav)
    splitter.setSizes([420, 560])
    QApplication.processEvents()
    QApplication.processEvents()
    _assert_navigator_rows_unclipped(nav)


@pytest.mark.parametrize("assumed_dpr", [1.0, 1.5, 2.0])
def test_navigator_content_budget_is_logical_pixels(qapp, qtbot, assumed_dpr):
    qapp.setStyle("Fusion")
    host, splitter, nav = _show_navigator_splitter(qtbot, qapp, 288)
    edit = nav.channel_list.btn_edit
    logical = edit.width()
    device_budget = int(round(logical * assumed_dpr))
    assert device_budget >= int(round(edit.minimumSizeHint().width() * assumed_dpr))
    assert nav.width() == pytest.approx(splitter.sizes()[0], abs=1)
