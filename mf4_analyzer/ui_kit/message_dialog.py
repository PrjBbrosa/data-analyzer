"""Application-owned message dialog (QDialog + QDialogButtonBox).

Layout, keyboard defaults, and the one-shot result belong here. Callers map
``MessageDialogResult.action_id`` onto business actions; this module does not
save, discard, or delete anything. Do not inherit QMessageBox or install a
global key filter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from PyQt5.QtCore import QEvent, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - sip is part of PyQt5
    sip = None

from .control_style import CONTROL_HEIGHTS
from .dialog_button_defaults import set_unique_default_button
from .dialog_geometry import (
    COMPACT_WORK_HEIGHT,
    COMPACT_WORK_WIDTH,
    Size,
    apply_plan,
    as_rect,
    client_budget,
    effective_margin,
    frame_insets_of,
    install_geometry_relayout,
    plan_geometry,
    resolve_available_rect,
)

CLOSE_REASON_BUTTON = "button"
CLOSE_REASON_DEFAULT_KEY = "default_key"
CLOSE_REASON_ESCAPE = "escape"
CLOSE_REASON_WINDOW_CLOSE = "window_close"

MARGIN_LEFT = 24
MARGIN_RIGHT = 24
MARGIN_TOP = 18
MARGIN_BOTTOM = 20
MARGIN_COMPACT = 12
ICON_LOGICAL_PX = 48
GAP_ICON_BODY = 16
GAP_BODY_ACTIONS = 16
PREFERRED_WIDTH = 380
SOFT_WIDTH_MAX = 560
BUTTON_PAD_H = 10
BUTTON_PAD_V = 4
BUTTON_BORDER = 1
BUTTON_TEXT_SLACK = 8
BUTTON_MIN_OUTER = 74
BODY_STACK_SPACING = 8

_ALLOWED_STYLES = frozenset({"primary", "warning", "danger", "neutral"})
_NON_CLOSING_ROLES = frozenset(
    {
        QDialogButtonBox.HelpRole,
        QDialogButtonBox.ApplyRole,
        QDialogButtonBox.ResetRole,
        QDialogButtonBox.ActionRole,
    }
)
_ICON_PIXMAPS = {
    1: QStyle.SP_MessageBoxInformation,
    2: QStyle.SP_MessageBoxWarning,
    3: QStyle.SP_MessageBoxCritical,
    4: QStyle.SP_MessageBoxQuestion,
}


def _alive(obj) -> bool:
    if obj is None:
        return False
    if sip is not None and sip.isdeleted(obj):
        return False
    return True


def _action_closes(action: "MessageAction") -> bool:
    if action.closes is not None:
        return bool(action.closes)
    return action.button_role not in _NON_CLOSING_ROLES


def _text_width(fm: QFontMetrics, text: str) -> int:
    if not text:
        return 0
    return max(
        fm.size(Qt.TextShowMnemonic, line).width()
        for line in text.split("\n")
    )


def outer_button_width(fm: QFontMetrics, text: str) -> int:
    """Outer width: glyph + H padding + border + slack. Not contentsRect."""
    return max(
        BUTTON_MIN_OUTER,
        _text_width(fm, text)
        + 2 * BUTTON_PAD_H
        + 2 * BUTTON_BORDER
        + BUTTON_TEXT_SLACK,
    )


def wrap_button_label(text: str, fm: QFontMetrics, max_inner: int) -> str:
    if max_inner <= 0 or _text_width(fm, text) <= max_inner:
        return text
    parts = text.split(" ")
    if len(parts) > 1:
        lines: list[str] = []
        current = ""
        for part in parts:
            trial = part if not current else f"{current} {part}"
            if current and fm.size(Qt.TextShowMnemonic, trial).width() > max_inner:
                lines.append(current)
                current = part
            else:
                current = trial
        if current:
            lines.append(current)
        return "\n".join(lines) if lines else text
    lines = []
    current = ""
    for char in text:
        trial = current + char
        if current and fm.size(Qt.TextShowMnemonic, trial).width() > max_inner:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return "\n".join(lines) if lines else text


@dataclass(frozen=True)
class MessageAction:
    """One dialog action. ``action_id`` is the identity; never derive it."""

    action_id: str
    label: str
    button_role: QDialogButtonBox.ButtonRole
    style: str = "neutral"
    standard_button: Optional[int] = None
    closes: Optional[bool] = None


@dataclass(frozen=True)
class MessageDialogResult:
    action_id: Optional[str]
    standard_button: Optional[int]
    checkbox_checked: bool
    close_reason: str


class AppMessageDialog(QDialog):
    """Owned message prompt with a scrollable body and a pinned action row."""

    NoIcon = 0
    Information = 1
    Warning = 2
    Critical = 3
    Question = 4

    completed = pyqtSignal(object)
    action_triggered = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        prompt_id: str,
        title: str,
        text: str,
        informative_text: str = "",
        detailed_text: str = "",
        icon: int = NoIcon,
        actions: Sequence[MessageAction],
        default_action_id: str,
        escape_action_id: str,
        modality: Qt.WindowModality = Qt.WindowModal,
        checkbox_text: str | None = None,
        checkbox_checked: bool = False,
        rich_text: bool = False,
        available_rect=None,
    ):
        super().__init__(parent)
        self.setObjectName("appMessageDialog")
        self.prompt_id = str(prompt_id)
        if not self.prompt_id:
            raise ValueError("prompt_id is required")
        self._validate_actions(actions, default_action_id, escape_action_id)

        self._icon_kind = int(icon)
        self._rich_text = bool(rich_text)
        self._modality = modality
        self._default_action_id = default_action_id
        self._escape_action_id = escape_action_id
        self._actions = tuple(actions)
        self._action_by_id = {action.action_id: action for action in self._actions}
        self._available_override = (
            None if available_rect is None else as_rect(available_rect)
        )
        self._submitted = False
        self._result: MessageDialogResult | None = None
        self._pending_reason: str | None = None
        self._applying = False
        self._actions_vertical = False
        self._buttons: dict[str, QPushButton] = {}
        self._action_by_button: dict[QAbstractButton, MessageAction] = {}

        self.setWindowTitle(title)
        self.setWindowModality(modality)
        self.setModal(modality != Qt.NonModal)

        self._root = QGridLayout(self)
        self._root.setContentsMargins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM)
        self._root.setHorizontalSpacing(GAP_ICON_BODY)
        self._root.setVerticalSpacing(GAP_BODY_ACTIONS)
        self._root.setColumnStretch(1, 1)
        self._root.setRowStretch(0, 1)

        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("appMessageIcon")
        self._icon_label.setFixedSize(ICON_LOGICAL_PX, ICON_LOGICAL_PX)
        self._icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("appMessageBody")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scroll.setMinimumHeight(CONTROL_HEIGHTS["base"])

        body = QWidget(self._scroll)
        body.setObjectName("appMessageBodyHost")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(BODY_STACK_SPACING)
        text_format = Qt.RichText if self._rich_text else Qt.PlainText
        selectable = Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        self._text_label = self._make_body_label(
            "appMessageText", text, text_format, selectable, bold=True,
        )
        self._informative_label = self._make_body_label(
            "appMessageInformative", informative_text, text_format, selectable,
        )
        self._detailed_label = self._make_body_label(
            "appMessageDetailed", detailed_text, text_format, selectable,
        )
        self._body_layout.addWidget(self._text_label)
        self._body_layout.addWidget(self._informative_label)
        self._body_layout.addWidget(self._detailed_label)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(body)

        self._checkbox = QCheckBox(checkbox_text or "", self)
        self._checkbox.setObjectName("appMessageCheckbox")
        self._checkbox.setChecked(bool(checkbox_checked))
        self._checkbox.setVisible(bool(checkbox_text))

        self._button_box = QDialogButtonBox(self)
        self._button_box.setObjectName("appMessageActions")
        self._button_box.setOrientation(Qt.Horizontal)
        self._button_box.setCenterButtons(False)
        self._button_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._build_actions()
        self._button_box.clicked.connect(self._on_button_box_clicked)

        self._root.addWidget(self._icon_label, 0, 0, Qt.AlignTop)
        self._root.addWidget(self._scroll, 0, 1)
        self._root.addWidget(self._checkbox, 1, 1)
        self._root.addWidget(self._button_box, 2, 1)
        if not self._checkbox.isVisible():
            self._checkbox.hide()

        self._refresh_icon_pixmap()
        self._install_key_filters()
        set_unique_default_button(self.default_button(), host=self)
        self._geometry = install_geometry_relayout(self, self._apply_geometry)
        self._apply_geometry()

    @staticmethod
    def _validate_actions(
        actions: Sequence[MessageAction],
        default_action_id: str,
        escape_action_id: str,
    ) -> None:
        if not actions:
            raise ValueError("actions must not be empty")
        seen: set[str] = set()
        for action in actions:
            if not action.action_id:
                raise ValueError("action_id is required")
            if action.action_id in seen:
                raise ValueError(f"duplicate action_id {action.action_id!r}")
            seen.add(action.action_id)
            if action.style not in _ALLOWED_STYLES:
                raise ValueError(
                    f"unknown action style {action.style!r}; "
                    f"expected one of {sorted(_ALLOWED_STYLES)}"
                )
        if default_action_id not in seen:
            raise ValueError(
                f"default_action_id {default_action_id!r} is not an action"
            )
        if escape_action_id not in seen:
            raise ValueError(
                f"escape_action_id {escape_action_id!r} is not an action"
            )

    def _make_body_label(
        self,
        object_name: str,
        text: str,
        text_format: Qt.TextFormat,
        interaction,
        *,
        bold: bool = False,
    ) -> QLabel:
        label = QLabel(self)
        label.setObjectName(object_name)
        label.setTextFormat(text_format)
        label.setTextInteractionFlags(interaction)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        if bold:
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        label.setText(text)
        label.setVisible(bool(text))
        return label

    def _build_actions(self) -> None:
        for action in self._actions:
            button = QPushButton(action.label, self)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setProperty("messageBoxRole", action.style)
            button.setProperty("appMessageLabel", action.label)
            button.setProperty("appMessageActionId", action.action_id)
            button.setAccessibleName(action.label)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._button_box.addButton(button, action.button_role)
            self._buttons[action.action_id] = button
            self._action_by_button[button] = action
        self._polish_buttons()

    def _polish_buttons(self) -> None:
        for button in self._buttons.values():
            style = button.style()
            style.unpolish(button)
            style.polish(button)
            button.update()

    def _host_rect(self):
        parent = self.parentWidget()
        if parent is None or not _alive(parent):
            return None
        top = parent.window()
        if top is None or not _alive(top):
            return None
        try:
            return as_rect(top.frameGeometry())
        except RuntimeError:
            return None

    def _install_key_filters(self) -> None:
        self.installEventFilter(self)
        self._button_box.installEventFilter(self)
        self._checkbox.installEventFilter(self)
        for button in self._buttons.values():
            button.installEventFilter(self)

    def button(self, action_id: str) -> QPushButton:
        return self._buttons[action_id]

    def default_button(self) -> QPushButton:
        return self._buttons[self._default_action_id]

    def escape_button(self) -> QPushButton:
        return self._buttons[self._escape_action_id]

    @property
    def message_result(self) -> MessageDialogResult | None:
        return self._result

    def notify_content_changed(self) -> None:
        self._geometry.notify_content_changed()

    def relayout(self) -> None:
        self._apply_geometry()

    def set_available_rect(self, rect) -> None:
        self._available_override = None if rect is None else as_rect(rect)
        self.notify_content_changed()

    def open(self):
        self.setWindowModality(self._modality)
        super().open()

    def exec_(self):
        self.setWindowModality(self._modality)
        return super().exec_()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.KeyPress and _alive(self) and not self._submitted:
            if self._is_editor_key_target(obj):
                return False
            if self._handle_dialog_key(event):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        if self._handle_dialog_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):  # noqa: N802
        if not self._submitted:
            self._commit_result(
                self._action_by_id[self._escape_action_id],
                CLOSE_REASON_WINDOW_CLOSE,
            )
        event.accept()
        super().closeEvent(event)

    def _is_editor_key_target(self, obj) -> bool:
        if obj is self._checkbox:
            return False
        try:
            from PyQt5.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit
        except ImportError:  # pragma: no cover
            return False
        return isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit))

    def _handle_dialog_key(self, event) -> bool:
        if not _alive(self) or self._submitted:
            return False
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            default = self.default_button()
            if not default.isEnabled():
                return True
            self._pending_reason = CLOSE_REASON_DEFAULT_KEY
            default.click()
            return True
        if key == Qt.Key_Escape:
            self._finish(
                self._action_by_id[self._escape_action_id],
                CLOSE_REASON_ESCAPE,
            )
            return True
        return False

    def _on_button_box_clicked(self, button: QAbstractButton) -> None:
        action = self._action_by_button.get(button)
        if action is None:
            return
        if not _action_closes(action):
            self._pending_reason = None
            self.action_triggered.emit(action.action_id)
            return
        reason = self._pending_reason or CLOSE_REASON_BUTTON
        self._pending_reason = None
        self._finish(action, reason)

    def _make_result(self, action: MessageAction, reason: str) -> MessageDialogResult:
        checked = bool(self._checkbox.isChecked()) if _alive(self._checkbox) else False
        return MessageDialogResult(
            action_id=action.action_id,
            standard_button=action.standard_button,
            checkbox_checked=checked,
            close_reason=reason,
        )

    def _commit_result(self, action: MessageAction, reason: str) -> bool:
        if self._submitted or not _alive(self):
            return False
        self._submitted = True
        self._pending_reason = None
        self._result = self._make_result(action, reason)
        self.completed.emit(self._result)
        return _alive(self)

    def _finish(self, action: MessageAction, reason: str) -> None:
        if not self._commit_result(action, reason):
            return
        if _alive(self):
            self.done(QDialog.Accepted)

    def _resolve_available(self):
        if self._available_override is not None:
            return self._available_override
        return resolve_available_rect(widget=self, parent=self.parentWidget())

    def _margins(self, compact: bool) -> tuple[int, int, int]:
        if compact:
            return MARGIN_COMPACT, MARGIN_COMPACT, MARGIN_COMPACT
        return MARGIN_LEFT, MARGIN_TOP, MARGIN_BOTTOM

    def _refresh_icon_pixmap(self) -> None:
        std = _ICON_PIXMAPS.get(self._icon_kind)
        if std is None:
            self._icon_label.hide()
            self._icon_label.setFixedSize(0, 0)
            return
        self._icon_label.show()
        self._icon_label.setFixedSize(ICON_LOGICAL_PX, ICON_LOGICAL_PX)
        icon = self.style().standardIcon(std, None, self)
        handle = self.windowHandle()
        if handle is not None:
            pixmap = icon.pixmap(handle, QSize(ICON_LOGICAL_PX, ICON_LOGICAL_PX))
        else:
            dpr = max(1.0, float(self.devicePixelRatioF()))
            pixmap = icon.pixmap(
                QSize(int(ICON_LOGICAL_PX * dpr), int(ICON_LOGICAL_PX * dpr))
            )
            pixmap.setDevicePixelRatio(dpr)
        self._icon_label.setPixmap(pixmap)

    def _place_action_row(self, vertical: bool) -> None:
        self._button_box.setOrientation(Qt.Vertical if vertical else Qt.Horizontal)
        self._root.removeWidget(self._button_box)
        if vertical:
            self._root.addWidget(self._button_box, 2, 0, 1, 2)
        else:
            self._root.addWidget(self._button_box, 2, 1, 1, 1)
        self._actions_vertical = vertical

    def _apply_button_metrics(self, max_outer: int | None) -> None:
        row_height = CONTROL_HEIGHTS["base"]
        for button in self._buttons.values():
            original = button.property("appMessageLabel") or button.text()
            fm = button.fontMetrics()
            label = original
            if max_outer is not None:
                inner = (
                    max_outer
                    - 2 * BUTTON_PAD_H
                    - 2 * BUTTON_BORDER
                    - BUTTON_TEXT_SLACK
                )
                label = wrap_button_label(original, fm, max(1, inner))
            button.setText(label)
            button.setAccessibleName(original)
            width = outer_button_width(button.fontMetrics(), label)
            if max_outer is not None:
                width = min(width, max(BUTTON_MIN_OUTER, max_outer)) if (
                    "\n" not in label
                ) else min(max(width, BUTTON_MIN_OUTER), max(max_outer, BUTTON_MIN_OUTER))
            button.setMinimumWidth(width)
            lines = label.count("\n") + 1
            needed = max(
                CONTROL_HEIGHTS["base"],
                button.fontMetrics().height() * lines
                + 2 * BUTTON_PAD_V
                + 2 * BUTTON_BORDER,
            )
            row_height = max(row_height, needed)
        for button in self._buttons.values():
            button.setMinimumHeight(row_height)
            button.setMaximumHeight(16777215)

    def _horizontal_actions_width(self) -> int:
        self._button_box.setOrientation(Qt.Horizontal)
        self._button_box.updateGeometry()
        hint = self._button_box.sizeHint().width()
        layout = self._button_box.layout()
        spacing = layout.spacing() if layout is not None else 6
        widths = [button.minimumWidth() for button in self._buttons.values()]
        n = len(widths)
        summed = sum(widths) + max(0, n - 1) * max(0, spacing)
        return max(hint, summed)

    def _body_column_width(self, client_width: int, margin_lr: int, icon_w: int) -> int:
        inner = max(0, client_width - 2 * margin_lr)
        if icon_w:
            return max(0, inner - icon_w - GAP_ICON_BODY)
        return inner

    def _body_height_for_width(self, width: int) -> int:
        height = 0
        visible = 0
        for label in (self._text_label, self._informative_label, self._detailed_label):
            if not label.isVisible() or not label.text():
                continue
            visible += 1
            height += max(label.heightForWidth(max(1, width)), label.fontMetrics().height())
        if visible > 1:
            height += BODY_STACK_SPACING * (visible - 1)
        return max(height, self._text_label.fontMetrics().height())

    def _apply_geometry(self) -> None:
        if self._applying or not _alive(self):
            return
        self._applying = True
        try:
            self._refresh_icon_pixmap()
            available = as_rect(self._resolve_available())
            insets = frame_insets_of(self)
            used = effective_margin(available, insets)
            budget = client_budget(available, insets, used)
            compact = (
                available.width <= COMPACT_WORK_WIDTH
                or available.height <= COMPACT_WORK_HEIGHT
            )
            margin_lr, margin_top, margin_bottom = self._margins(compact)
            self._root.setContentsMargins(
                margin_lr, margin_top, margin_lr, margin_bottom,
            )
            self._root.setHorizontalSpacing(GAP_ICON_BODY if self._icon_label.isVisible() else 0)
            self._root.setVerticalSpacing(GAP_BODY_ACTIONS)

            icon_w = ICON_LOGICAL_PX if self._icon_label.isVisible() else 0
            max_client_w = max(1, budget.width)
            soft_max = min(SOFT_WIDTH_MAX, max_client_w)
            preferred = min(PREFERRED_WIDTH, soft_max)

            self._apply_button_metrics(max_outer=None)
            horizontal_need = self._horizontal_actions_width()
            needed_client = (
                horizontal_need
                + (icon_w + GAP_ICON_BODY if icon_w else 0)
                + 2 * margin_lr
            )
            width = preferred
            if needed_client > width:
                width = min(soft_max, max(width, needed_client))
            body_w = self._body_column_width(width, margin_lr, icon_w)
            vertical = horizontal_need > body_w
            if vertical:
                width = min(soft_max, max(width, preferred))
            width = max(1, min(width, max_client_w))
            self._place_action_row(vertical)
            action_max = (
                max(1, width - 2 * margin_lr)
                if vertical
                else max(1, self._body_column_width(width, margin_lr, icon_w))
            )
            self._apply_button_metrics(max_outer=action_max)
            set_unique_default_button(self.default_button(), host=self)

            body_w = self._body_column_width(width, margin_lr, icon_w)
            body_h = self._body_height_for_width(max(1, body_w))
            icon_h = ICON_LOGICAL_PX if self._icon_label.isVisible() else 0
            checkbox_h = 0
            if self._checkbox.isVisible():
                checkbox_h = self._checkbox.sizeHint().height() + GAP_BODY_ACTIONS
            actions_h = max(
                CONTROL_HEIGHTS["base"],
                self._button_box.sizeHint().height(),
            )
            pref_h = (
                margin_top
                + max(body_h, icon_h)
                + checkbox_h
                + GAP_BODY_ACTIONS
                + actions_h
                + margin_bottom
            )
            one_line = self._text_label.fontMetrics().height()
            content_min = Size(
                min(width, max_client_w),
                margin_top
                + max(icon_h, one_line)
                + checkbox_h
                + GAP_BODY_ACTIONS
                + actions_h
                + margin_bottom,
            )
            plan = plan_geometry(
                available,
                Size(width, pref_h),
                frame=insets,
                content_minimum=content_min,
                host=self._host_rect(),
            )
            apply_plan(self, plan)
            remaining_body = max(
                one_line,
                plan.client.height
                - margin_top
                - margin_bottom
                - checkbox_h
                - GAP_BODY_ACTIONS
                - actions_h,
            )
            if plan.needs_scroll or body_h > remaining_body:
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        finally:
            self._applying = False


def build_unsaved_project_dialog(parent=None, *, available_rect=None) -> AppMessageDialog:
    """Unsaved-project demonstration prompt. Business mapping stays in the mixin."""
    return AppMessageDialog(
        parent,
        prompt_id="unsaved_project",
        title="未保存的项目",
        text="项目有未保存的更改。是否保存？",
        icon=AppMessageDialog.Warning,
        actions=(
            MessageAction(
                action_id="save",
                label="保存",
                button_role=QDialogButtonBox.AcceptRole,
                style="warning",
            ),
            MessageAction(
                action_id="discard",
                label="不保存",
                button_role=QDialogButtonBox.DestructiveRole,
                style="danger",
            ),
            MessageAction(
                action_id="cancel",
                label="取消",
                button_role=QDialogButtonBox.RejectRole,
                style="neutral",
            ),
        ),
        default_action_id="save",
        escape_action_id="cancel",
        available_rect=available_rect,
    )
