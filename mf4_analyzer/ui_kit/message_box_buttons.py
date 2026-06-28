"""Semantic QMessageBox button roles for shared QSS styling.

Static ``QMessageBox.question(...)`` call sites do not expose the transient
box instance for per-call styling. This app-level filter tags buttons by their
standard QMessageBox role so ``style.qss`` can give confirmations a semantic
accent while keeping cancel/no buttons neutral.
"""
from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QMessageBox, QPushButton


_DANGER_WORDS = (
    "删除",
    "移除",
    "清空",
    "覆盖",
    "丢弃",
    "不可恢复",
    "停止并",
)
_WARNING_WORDS = (
    "可能",
    "卡顿",
    "风险",
    "数据量较大",
    "继续",
    "额外增加",
)
_NEUTRAL_ROLES = {
    QMessageBox.NoRole,
    QMessageBox.RejectRole,
}
_CONFIRM_ROLES = {
    QMessageBox.AcceptRole,
    QMessageBox.ApplyRole,
    QMessageBox.YesRole,
}
_ALLOWED_CONFIRM_STYLES = {"primary", "warning", "danger"}


def _dialog_text(box: QMessageBox) -> str:
    return "\n".join(
        part
        for part in (
            box.windowTitle(),
            box.text(),
            box.informativeText(),
            box.detailedText(),
        )
        if part
    )


def _confirm_style(box: QMessageBox) -> str:
    explicit = box.property("messageBoxConfirmRole")
    if explicit in _ALLOWED_CONFIRM_STYLES:
        return explicit

    text = _dialog_text(box)
    if any(word in text for word in _DANGER_WORDS):
        return "danger"
    if box.icon() == QMessageBox.Critical:
        return "danger"
    if any(word in text for word in _WARNING_WORDS):
        return "warning"
    if box.icon() == QMessageBox.Warning:
        return "warning"
    return "primary"


def _set_button_role(button: QPushButton, role: str) -> None:
    if button.property("messageBoxRole") == role:
        return
    button.setProperty("messageBoxRole", role)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()


def _role_for_button(box: QMessageBox, button: QPushButton) -> str:
    role = box.buttonRole(button)
    if role == QMessageBox.DestructiveRole:
        return "danger"
    if role in _NEUTRAL_ROLES:
        return "neutral"
    if role in _CONFIRM_ROLES:
        return _confirm_style(box)
    return "neutral"


def prepare_message_box_buttons(box):
    if not isinstance(box, QMessageBox):
        return box
    for button in box.findChildren(QPushButton):
        _set_button_role(button, _role_for_button(box, button))
    return box


class _MessageBoxButtonRoleFilter(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Polish, QEvent.Show, QEvent.ChildAdded):
            if isinstance(obj, QMessageBox):
                prepare_message_box_buttons(obj)
        return False


_filter_ref = []


def install_message_box_button_roles(app):
    """Install the message-box button role filter on ``app`` idempotently."""
    if _filter_ref:
        return _filter_ref[0]
    filt = _MessageBoxButtonRoleFilter(app)
    app.installEventFilter(filt)
    _filter_ref.append(filt)
    return filt
