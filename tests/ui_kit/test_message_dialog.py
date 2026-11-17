"""AppMessageDialog: layout, keys, one-shot result, unsaved-project demo."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QDialogButtonBox, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_HEIGHTS
from mf4_analyzer.ui_kit.dialog_geometry import IntRect, SCREEN_MARGIN, as_rect
from mf4_analyzer.ui_kit.message_dialog import (
    BODY_STACK_SPACING,
    CLOSE_REASON_BUTTON,
    CLOSE_REASON_DEFAULT_KEY,
    CLOSE_REASON_ESCAPE,
    CLOSE_REASON_WINDOW_CLOSE,
    GAP_BODY_ACTIONS,
    ICON_LOGICAL_PX,
    MARGIN_BOTTOM,
    MARGIN_TOP,
    PREFERRED_WIDTH,
    AppMessageDialog,
    MessageAction,
    build_unsaved_project_dialog,
    outer_button_width,
    wrap_button_label,
)


_CHINESE_NAME = "方向盘扭矩测量_" + ("很长文件名" * 11)
_LONG_PATH = "C:/data/" + ("unbroken_english_path_segment_" * 4) + "file.mf4"
_LONG_BODY = "x" * 64


def _load_sheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    return previous


def _actions(*pairs):
    mapping = {
        "save": ("保存", QDialogButtonBox.AcceptRole, "warning"),
        "discard": ("不保存", QDialogButtonBox.DestructiveRole, "danger"),
        "cancel": ("取消", QDialogButtonBox.RejectRole, "neutral"),
        "ok": ("确定", QDialogButtonBox.AcceptRole, "primary"),
        "help": ("帮助", QDialogButtonBox.HelpRole, "neutral"),
    }
    out = []
    for action_id in pairs:
        label, role, style = mapping[action_id]
        out.append(
            MessageAction(
                action_id=action_id, label=label, button_role=role, style=style,
            )
        )
    return tuple(out)


def test_outer_button_width_includes_padding_border_and_slack(qapp):
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QLabel

    label = QLabel("统一选择 DBC")
    fm = QFontMetrics(label.font())
    width = outer_button_width(fm, "统一选择 DBC")
    assert width >= fm.horizontalAdvance("统一选择 DBC") + 10 + 10 + 1 + 1 + 8
    assert width >= 74


def test_wrap_button_label_breaks_long_unspaced_text(qapp):
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QLabel

    fm = QFontMetrics(QLabel("x").font())
    wrapped = wrap_button_label("ABCDEFGHIJKLMNOPQRSTUVWXYZ", fm, 12)
    assert "\n" in wrapped
    assert wrapped.replace("\n", "") == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_duplicate_or_unknown_action_ids_are_programming_errors(qapp):
    dup = MessageAction(
        action_id="ok",
        label="A",
        button_role=QDialogButtonBox.AcceptRole,
    )
    with pytest.raises(ValueError, match="duplicate"):
        AppMessageDialog(
            prompt_id="x",
            title="t",
            text="b",
            actions=(dup, dup),
            default_action_id="ok",
            escape_action_id="ok",
        )
    only = MessageAction(
        action_id="ok",
        label="A",
        button_role=QDialogButtonBox.AcceptRole,
    )
    with pytest.raises(ValueError, match="default_action_id"):
        AppMessageDialog(
            prompt_id="x",
            title="t",
            text="b",
            actions=(only,),
            default_action_id="missing",
            escape_action_id="ok",
        )


def test_unsaved_dialog_buttons_match_dirty_guard_contract(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = build_unsaved_project_dialog()
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        qapp.processEvents()
        assert dialog.default_button() is dialog.button("save")
        assert dialog.escape_button() is dialog.button("cancel")
        assert dialog.button("save").text() == "保存"
        assert dialog.button("discard").text() == "不保存"
        assert dialog.button("cancel").text() == "取消"
        heights = {
            dialog.button("save").height(),
            dialog.button("discard").height(),
            dialog.button("cancel").height(),
        }
        assert len(heights) == 1
        assert max(heights) >= CONTROL_HEIGHTS["base"]
    finally:
        qapp.setStyleSheet(previous)


def test_enter_escape_and_title_close_reasons(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = build_unsaved_project_dialog()
        qtbot.addWidget(dialog)
        results = []
        dialog.completed.connect(results.append)
        dialog.show()
        qtbot.waitExposed(dialog)
        QTest.keyClick(dialog, Qt.Key_Return)
        qapp.processEvents()
        assert [item.action_id for item in results] == ["save"]
        assert results[0].close_reason == CLOSE_REASON_DEFAULT_KEY

        dialog = build_unsaved_project_dialog()
        qtbot.addWidget(dialog)
        results.clear()
        dialog.completed.connect(results.append)
        dialog.show()
        qtbot.waitExposed(dialog)
        QTest.keyClick(dialog, Qt.Key_Escape)
        qapp.processEvents()
        assert results[0].action_id == "cancel"
        assert results[0].close_reason == CLOSE_REASON_ESCAPE

        dialog = build_unsaved_project_dialog()
        qtbot.addWidget(dialog)
        results.clear()
        dialog.completed.connect(results.append)
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.close()
        qapp.processEvents()
        assert results[0].action_id == "cancel"
        assert results[0].close_reason == CLOSE_REASON_WINDOW_CLOSE
        dialog.close()
        qapp.processEvents()
        assert len(results) == 1
    finally:
        qapp.setStyleSheet(previous)


def test_each_unsaved_button_submits_once(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        for action_id in ("save", "discard", "cancel"):
            dialog = build_unsaved_project_dialog()
            qtbot.addWidget(dialog)
            results = []
            dialog.completed.connect(results.append)
            dialog.action_triggered.connect(lambda *_args: results.append("triggered"))
            dialog.show()
            qtbot.waitExposed(dialog)
            qtbot.mouseClick(dialog.button(action_id), Qt.LeftButton)
            qapp.processEvents()
            assert [item.action_id for item in results] == [action_id]
            assert results[0].close_reason == CLOSE_REASON_BUTTON
    finally:
        qapp.setStyleSheet(previous)


def test_help_action_does_not_close(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = AppMessageDialog(
            prompt_id="help_probe",
            title="帮助",
            text="说明",
            actions=_actions("ok", "help"),
            default_action_id="ok",
            escape_action_id="ok",
        )
        qtbot.addWidget(dialog)
        triggered = []
        completed = []
        dialog.action_triggered.connect(triggered.append)
        dialog.completed.connect(completed.append)
        dialog.show()
        qtbot.waitExposed(dialog)
        qtbot.mouseClick(dialog.button("help"), Qt.LeftButton)
        qapp.processEvents()
        assert triggered == ["help"]
        assert completed == []
        assert dialog.isVisible()
    finally:
        qapp.setStyleSheet(previous)


def test_disabled_default_does_not_submit_another_action(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = build_unsaved_project_dialog()
        qtbot.addWidget(dialog)
        results = []
        dialog.completed.connect(results.append)
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.button("save").setEnabled(False)
        QTest.keyClick(dialog, Qt.Key_Return)
        qapp.processEvents()
        assert results == []
        assert dialog.isVisible()
        QTest.keyClick(dialog, Qt.Key_Escape)
        qapp.processEvents()
        assert results[0].action_id == "cancel"
    finally:
        qapp.setStyleSheet(previous)


def test_long_plain_text_stays_accessible_and_unparsed(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        htmlish = f"{_LONG_BODY}\n{_LONG_PATH}\n<{_CHINESE_NAME}> & more"
        dialog = AppMessageDialog(
            prompt_id="long_body",
            title="错误",
            text=htmlish,
            detailed_text=_CHINESE_NAME,
            icon=AppMessageDialog.Critical,
            actions=_actions("ok"),
            default_action_id="ok",
            escape_action_id="ok",
            available_rect=IntRect(0, 0, 640, 360),
        )
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        qapp.processEvents()
        assert dialog._text_label.textFormat() == Qt.PlainText
        assert "<" in dialog._text_label.text()
        assert len(_CHINESE_NAME.encode("utf-8")) >= 180
        assert _CHINESE_NAME in dialog._detailed_label.text()
        assert dialog._detailed_label.textInteractionFlags() & Qt.TextSelectableByMouse
        frame = as_rect(dialog.frameGeometry())
        safe = IntRect(0, 0, 640, 360).adjusted(
            SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
        )
        assert safe.contains_rect(frame)
        assert dialog._button_box.isVisible()
        host = dialog.rect()
        assert host.contains(dialog.button("ok").geometry())
    finally:
        qapp.setStyleSheet(previous)


def test_same_row_heights_grow_together_at_24px(qapp, qtbot):
    previous = _load_sheet(qapp)
    try:
        dialog = build_unsaved_project_dialog(available_rect=IntRect(0, 0, 800, 600))
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        font = QFont(dialog.font())
        font.setPixelSize(24)
        dialog.setFont(font)
        for button in dialog._buttons.values():
            button.setFont(font)
        dialog.notify_content_changed()
        qapp.processEvents()
        heights = {button.height() for button in dialog._buttons.values()}
        assert len(heights) == 1
        assert max(heights) >= 24
    finally:
        qapp.setStyleSheet(previous)


def test_mixin_prompt_maps_button_clicks(qapp, qtbot):
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    previous = _load_sheet(qapp)
    try:
        widget = QWidget()
        qtbot.addWidget(widget)
        widget._prompt_unsaved_project = (
            ProjectIOMixin._prompt_unsaved_project.__get__(widget)
        )
        holder = {}

        def _capture(*_args, **_kwargs):
            box, save_btn, discard_btn, cancel_btn = (
                ProjectIOMixin._unsaved_project_prompt_buttons(widget)
            )
            holder["box"] = box
            qtbot.addWidget(box)
            return box, save_btn, discard_btn, cancel_btn

        widget._unsaved_project_prompt_buttons = _capture
        QTimer.singleShot(0, lambda: holder["box"].button("discard").click())
        assert widget._prompt_unsaved_project() == "discard"
        QTimer.singleShot(0, lambda: holder["box"].close())
        assert widget._prompt_unsaved_project() == "cancel"
    finally:
        qapp.setStyleSheet(previous)


def _checkbox_dialog(**kwargs):
    defaults = dict(
        prompt_id="checkbox_probe",
        title="可选",
        text="记住这次选择",
        actions=_actions("ok", "cancel"),
        default_action_id="ok",
        escape_action_id="cancel",
    )
    defaults.update(kwargs)
    return AppMessageDialog(**defaults)


def test_optional_checkbox_stays_visible_after_show(qapp, qtbot):
    dialog = _checkbox_dialog(checkbox_text="不再提示", checkbox_checked=True)
    qtbot.addWidget(dialog)
    assert dialog._checkbox.isHidden() is False
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog._checkbox.isVisible() is True
    assert dialog._checkbox.isChecked() is True
    dialog._checkbox.setChecked(False)
    qtbot.mouseClick(dialog.button("ok"), Qt.LeftButton)
    qapp.processEvents()
    assert dialog.message_result.checkbox_checked is False


def test_optional_checkbox_absent_without_text(qapp, qtbot):
    dialog = _checkbox_dialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog._checkbox.isHidden() is True
    assert dialog._checkbox.isVisible() is False


def test_optional_checkbox_survives_hidden_parent_then_show(qapp, qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = _checkbox_dialog(parent=parent, checkbox_text="不再提示")
    assert parent.isVisible() is False
    assert dialog._checkbox.isHidden() is False
    parent.show()
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog._checkbox.isVisible() is True
    dialog.close()
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog._checkbox.isVisible() is True


_NORMAL_WORK = IntRect(0, 0, 1366, 768)
_SHORT_UNSAVED_TEXT = "项目有未保存的更改。是否保存？"


def _show_production_unsaved(qapp, qtbot, **kwargs):
    previous = _load_sheet(qapp)
    dialog = build_unsaved_project_dialog(
        available_rect=kwargs.pop("available_rect", _NORMAL_WORK),
        **kwargs,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qapp.processEvents()
    return previous, dialog


def _content_formula(dialog) -> tuple[int, int, int]:
    """Spec height from live margins, wrapped text, icon, and the button row.

    Returns ``(formula, text height, body slot)``. The body slot is
    ``max(wrapped text, icon)`` and must not follow ``QScrollArea.sizeHint``.
    """
    margins = dialog._root.contentsMargins()
    top = margins.top()
    bottom = margins.bottom()
    assert top == MARGIN_TOP
    assert bottom == MARGIN_BOTTOM
    icon_h = 0 if dialog._icon_label.isHidden() else max(
        dialog._icon_label.height(), ICON_LOGICAL_PX,
    )
    body_w = dialog._scroll.width()
    if body_w < 40:
        body_w = max(1, PREFERRED_WIDTH - margins.left() - margins.right() - ICON_LOGICAL_PX - 16)
    text_h = 0
    visible = 0
    for label in (dialog._text_label, dialog._informative_label, dialog._detailed_label):
        if label.isHidden() or not label.text():
            continue
        visible += 1
        text_h += max(
            label.heightForWidth(max(1, body_w)),
            label.fontMetrics().height(),
        )
    if visible > 1:
        text_h += BODY_STACK_SPACING * (visible - 1)
    actions_h = dialog._button_box.height()
    if actions_h <= 0:
        actions_h = max(
            CONTROL_HEIGHTS["base"],
            dialog._button_box.sizeHint().height(),
        )
    formula = top + max(text_h, icon_h) + GAP_BODY_ACTIONS + actions_h + bottom
    return formula, text_h, max(text_h, icon_h)


def _assert_content_height(dialog) -> int:
    formula, _text_h, body_slot = _content_formula(dialog)
    surplus = dialog.height() - formula
    assert 0 <= surplus <= 8, (
        f"client {dialog.width()}x{dialog.height()} formula {formula} "
        f"surplus {surplus} scroll {dialog._scroll.width()}x{dialog._scroll.height()}"
    )
    assert dialog.height() < 200
    assert dialog.width() == PREFERRED_WIDTH
    assert dialog._scroll.height() <= body_slot + 8
    assert dialog._scroll.height() < 160
    return formula


def test_production_unsaved_prompt_uses_content_height(qapp, qtbot):
    previous, dialog = _show_production_unsaved(qapp, qtbot)
    try:
        _assert_content_height(dialog)
        assert dialog.windowTitle() == "未保存的项目"
        assert dialog._text_label.text() == _SHORT_UNSAVED_TEXT
        assert dialog.default_button() is dialog.button("save")
        assert dialog.escape_button() is dialog.button("cancel")
        assert dialog.button("save").text() == "保存"
        assert dialog.button("discard").text() == "不保存"
        assert dialog.button("cancel").text() == "取消"
        save_top = dialog.button("save").mapTo(dialog, dialog.button("save").rect().topLeft())
        assert save_top.y() >= dialog._scroll.geometry().bottom()
        assert dialog._scroll.widget() is not None
        assert dialog._scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert int(dialog.windowFlags() & Qt.WindowContextHelpButtonHint) == 0
    finally:
        qapp.setStyleSheet(previous)


def test_unsaved_prompt_returns_to_content_height_after_long_text(qapp, qtbot):
    previous, dialog = _show_production_unsaved(qapp, qtbot)
    try:
        short_height = dialog.height()
        _assert_content_height(dialog)
        dialog._text_label.setText(("方向盘扭矩出现周期性波动，需要继续观察。" * 12))
        dialog.relayout()
        qapp.processEvents()
        assert dialog.height() > short_height
        assert dialog._scroll.verticalScrollBarPolicy() in (
            Qt.ScrollBarAsNeeded,
            Qt.ScrollBarAlwaysOff,
        )
        long_height = dialog.height()
        dialog._text_label.setText(_SHORT_UNSAVED_TEXT)
        dialog.relayout()
        qapp.processEvents()
        _assert_content_height(dialog)
        assert dialog.height() < long_height
        assert dialog.height() <= short_height + 8
        assert dialog.button("save").isVisible()
        assert dialog.button("discard").isVisible()
        assert dialog.button("cancel").isVisible()
        assert dialog.default_button() is dialog.button("save")
        assert dialog.escape_button() is dialog.button("cancel")
        save_top = dialog.button("save").mapTo(dialog, dialog.button("save").rect().topLeft())
        assert save_top.y() >= dialog._scroll.geometry().bottom()
    finally:
        qapp.setStyleSheet(previous)


def test_import_resource_dialog_folds_details_and_copies_exact_bytes(qapp):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui_kit.message_dialog import build_import_resource_dialog

    detail = "估算请求：638,976,000 bytes\n上限：498,988,944 bytes"
    dialog = build_import_resource_dialog(
        None,
        text="本次未导入此文件。预计导入资源需求约609 MiB，当前预算约476 MiB。",
        detail=detail,
        action_ids=("close", "toggle_details", "copy_diagnostics", "recheck_retry"),
    )
    qt_ids = [
        button.property("appMessageActionId") for button in dialog._buttons.values()
    ]
    assert qt_ids == ["close", "toggle_details", "copy_diagnostics", "recheck_retry"]
    assert dialog._text_label.textFormat() == Qt.PlainText
    assert dialog._detailed_label.isHidden()
    assert "638,976,000" not in dialog._text_label.text()
    assert dialog.default_button() is dialog.button("close")
    assert dialog.escape_button() is dialog.button("close")
    dialog.button("copy_diagnostics").click()
    assert QApplication.clipboard().text() == detail
    assert dialog.message_result is None
    toggle = dialog.button("toggle_details")
    toggle.click()
    assert toggle.property("appMessageActionId") == "toggle_details"
    assert not dialog._detailed_label.isHidden()
    assert "638,976,000" in dialog._detailed_label.text()
    assert "498,988,944" in dialog._detailed_label.text()
    dialog.button("recheck_retry").click()
    assert dialog.message_result.action_id == "recheck_retry"


def test_import_resource_dialog_omits_recheck_when_the_action_is_absent(qapp):
    from mf4_analyzer.ui_kit.message_dialog import build_import_resource_dialog

    dialog = build_import_resource_dialog(
        None,
        text="本次未导入此文件。通道数量为 120,000，当前上限为 100,000。",
        detail="估算请求：120,000 count",
        action_ids=("close", "toggle_details", "copy_diagnostics"),
    )
    ids = [button.property("appMessageActionId") for button in dialog._buttons.values()]
    assert "recheck_retry" not in ids
    assert "MiB" not in dialog._text_label.text()
