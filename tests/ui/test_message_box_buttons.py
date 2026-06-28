from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui_kit.message_box_buttons import (
    install_message_box_button_roles,
    prepare_message_box_buttons,
)


def _question_box(text: str) -> QMessageBox:
    box = QMessageBox()
    box.setWindowTitle("确认")
    box.setText(text)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    return box


def test_warning_question_colors_yes_and_keeps_no_neutral(qapp):
    box = _question_box("共有 24 个通道，全部勾选可能导致卡顿。\n确定要全选吗？")

    prepare_message_box_buttons(box)

    assert box.button(QMessageBox.Yes).property("messageBoxRole") == "warning"
    assert box.button(QMessageBox.No).property("messageBoxRole") == "neutral"
    box.deleteLater()


def test_danger_question_colors_destructive_yes(qapp):
    box = _question_box("删除 3 个通道？")

    prepare_message_box_buttons(box)

    assert box.button(QMessageBox.Yes).property("messageBoxRole") == "danger"
    assert box.button(QMessageBox.No).property("messageBoxRole") == "neutral"
    box.deleteLater()


def test_plain_question_uses_primary_yes(qapp):
    box = _question_box("是否保存当前项目？")

    prepare_message_box_buttons(box)

    assert box.button(QMessageBox.Yes).property("messageBoxRole") == "primary"
    assert box.button(QMessageBox.No).property("messageBoxRole") == "neutral"
    box.deleteLater()


def test_install_message_box_button_roles_is_idempotent(qapp):
    first = install_message_box_button_roles(qapp)
    second = install_message_box_button_roles(qapp)

    assert first is second


def test_installed_filter_tags_message_box_buttons_on_show(qapp):
    install_message_box_button_roles(qapp)
    box = _question_box("叠加模式数据量较大。\n这可能导致明显卡顿。是否继续？")

    box.show()
    qapp.processEvents()

    assert box.button(QMessageBox.Yes).property("messageBoxRole") == "warning"
    assert box.button(QMessageBox.No).property("messageBoxRole") == "neutral"
    box.close()
    box.deleteLater()


def test_message_box_button_qss_contract_is_present():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    assert 'QMessageBox QPushButton[messageBoxRole="primary"]' in qss
    assert 'QMessageBox QPushButton[messageBoxRole="warning"]' in qss
    assert 'QMessageBox QPushButton[messageBoxRole="danger"]' in qss
