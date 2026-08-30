"""UltraView card widgets: template cards, free-grid cards, and replace hover.

Card copy, status chips, and the action bar live here. The board hosts stay
on the widgets façade until later Wave 1 commits.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import Any

import qtawesome as qta
from PyQt5.QtCore import QEvent, QObject, QPoint, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QContextMenuEvent, QImage, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWIDGETSIZE_MAX,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    SECTION_LABELS_ZH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
)
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.menus import add_rounded_submenu, apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.ultraview_style import titanium_color

from .layouts import (
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    preview_reading_box,
)
from .viewport import (
    LOD_FULL,
    LOD_NO_FOOTER,
    LOD_TITLE_ONLY,
    QUALITY_FAST,
    QUALITY_SMOOTH,
    lod_visibility,
)
from .widgets_common import (
    STATUS_LABELS_ZH,
    _ColorDot,
    _ElideLabel,
    _accept_ultraview_drag,
    _effective_device_pixel_ratio,
    _full_tooltip,
    _repolish,
    _run_ultraview_drag,
    _set_flag,
    extract_ref_strings,
    make_ref_mime,
)

REPLACE_HOVER_MS = 600

_CARD_ICON = titanium_color("muted")
_CARD_DANGER = titanium_color("danger")

class ReplaceHoverController(QObject):
    """Arm a replacement ring after a sustained hover. No lambda slots."""

    armed = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: str | None = None
        self._armed: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def hover(self, key: str | None) -> None:
        if key is None:
            self.clear()
            return
        if key == self._armed:
            return
        if key == self._pending and self._timer.isActive():
            return
        self._armed = None
        self._pending = key
        self.cleared.emit()
        self._timer.start(REPLACE_HOVER_MS)

    def is_armed(self, key: str) -> bool:
        return self._armed == key

    def armed_key(self) -> str | None:
        return self._armed

    def clear(self) -> None:
        self._timer.stop()
        had = self._armed is not None or self._pending is not None
        self._pending = None
        self._armed = None
        if had:
            self.cleared.emit()

    def _on_timeout(self) -> None:
        self._armed = self._pending
        if self._armed is not None:
            self.armed.emit(self._armed)

MISSING_CARD_COPY = "尚无可用结果，UltraView 不会后台计算"
STALE_CARD_COPY = "源已变化"
ORPHANED_CARD_COPY = "源 View 已删除"
DIMMED_OPACITY = 0.28
# Transient dim worn by the cards a drag is currently previewing; the model-level
# ``DIMMED_OPACITY`` above is the persistent one ``restore_dim()`` falls back to.
DRAG_DIM_OPACITY = 0.4

TYPE_CHIP_ICON_ONLY_WIDTH = 168
_SECTION_TYPE_ICONS = {
    "time": Icons.mode_time,
    "fft": Icons.mode_fft,
    "fft_time": Icons.mode_fft_time,
    "frf": Icons.mode_frf,
    "order": Icons.mode_order,
}


@dataclass
class CardViewModel:
    slot_id: str
    section: str
    view_id: str
    title: str = ""
    tab_color: str = ""
    status: str = STATUS_MISSING
    source_summary: str = ""
    axis_kind: str | None = None
    x_unit: str = ""
    x_range: tuple[float, float] | None = None
    image: Any = None
    selected: bool = False
    dimmed: bool = False
    replacement_armed: bool = False
    show_title: bool = True
    show_source: bool = True
    show_card_actions: bool = False

def preview_image(record: Any) -> QImage | None:
    image = getattr(record, "image", None)
    if image is None:
        return None
    is_null = getattr(image, "isNull", None)
    if callable(is_null) and is_null():
        return None
    return image

def _range_text(x_range: tuple[float, float] | None, x_unit: str) -> str:
    if x_range is None or len(x_range) != 2:
        return x_unit
    try:
        lo, hi = float(x_range[0]), float(x_range[1])
    except (TypeError, ValueError):
        return x_unit
    unit = f" {x_unit}" if x_unit else ""
    return f"{lo:g}–{hi:g}{unit}"

class _CardActionBar(QFrame):
    """Header capsule: open, focus, fit, remove, more.

    Height is owned by ``sizeHint`` / ``minimumSizeHint`` only. A separate
    ``setFixedHeight`` used to disagree with the layout hint (24 vs 28),
    which dropped the buttons ~2 px below the header center.
    """

    _FIT_TOOLTIP = "按原图比例：只收紧当前卡，不移动邻卡"
    _FIT_DISABLED_TOOLTIP = "模板布局的尺寸由模板决定，切到自由网格后可用"
    _REMOVE_TOOLTIP = "从当前 Board 移除（不删除源 View）"
    _HEIGHT = 24
    _BUTTON = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCardActionBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setContentsMargins(0, 0, 0, 0)
        # Minimum: never shrink below the visible actions (remove stays).
        # Fixed vertical: height is sizeHint, not a second fixed-height call.
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 0, 3, 0)
        # Adjacent 22 px hit targets share capsule background but never overlap.
        # Zero layout spacing keeps the five-action bar inside a standard card.
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)
        self._buttons: dict[str, QToolButton] = {}
        for action, object_name, icon, tooltip in (
            (
                "open",
                "ultraViewCardOpenButton",
                qta.icon("fa5s.external-link-alt", color=_CARD_ICON),
                "打开原 View",
            ),
            (
                "focus",
                "ultraViewCardFocusButton",
                qta.icon("fa5s.expand", color=_CARD_ICON),
                "临时放大预览",
            ),
            (
                "fit",
                "ultraViewCardFitButton",
                qta.icon("fa5s.vector-square", color=_CARD_ICON),
                self._FIT_TOOLTIP,
            ),
            (
                "remove",
                "ultraViewCardRemoveButton",
                qta.icon("fa5s.trash-alt", color=_CARD_DANGER),
                self._REMOVE_TOOLTIP,
            ),
            (
                "more",
                "ultraViewCardMoreButton",
                qta.icon("fa5s.ellipsis-v", color=_CARD_ICON),
                "更多卡片操作",
            ),
        ):
            button = QToolButton(self)
            button.setObjectName(object_name)
            button.setIcon(icon)
            button.setIconSize(QSize(14, 14))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setAutoRaise(True)
            button.setAutoFillBackground(False)
            button.setAttribute(Qt.WA_StyledBackground, True)
            button.setFixedSize(self._BUTTON, self._BUTTON)
            button.setFocusPolicy(Qt.TabFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setProperty("role", "cardAction")
            button.setProperty("chrome", "ultraview")
            button.setProperty("contextAction", action)
            button.setProperty("danger", "true" if action == "remove" else "false")
            self._buttons[action] = button
            layout.addWidget(button, 0, Qt.AlignVCenter)
        self._sync_action_width()

    def _required_action_width(self) -> int:
        layout = self.layout()
        margins = layout.contentsMargins() if layout is not None else self.contentsMargins()
        spacing = layout.spacing() if layout is not None else 0
        visible = [button for button in self._buttons.values() if not button.isHidden()]
        return (
            margins.left()
            + margins.right()
            + len(visible) * self._BUTTON
            + max(0, len(visible) - 1) * max(0, spacing)
        )

    def _sync_action_width(self) -> None:
        # Qt otherwise compresses this nested layout before fixed child widths,
        # producing overlapping hit targets on compact cards.
        self.setFixedWidth(self._required_action_width())

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(max(hint.width(), self._required_action_width()), self._HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def button(self, action: str) -> QToolButton | None:
        return self._buttons.get(str(action))

    def set_compact(self, compact: bool) -> None:
        """Hide infrequent actions (fit); keep open / focus / remove / more."""
        fit = self._buttons.get("fit")
        if fit is None:
            return
        fit.setVisible(not bool(compact))
        self._sync_action_width()
        self.updateGeometry()

    def set_fit_enabled(self, enabled: bool) -> None:
        button = self._buttons.get("fit")
        if button is None:
            return
        button.setEnabled(bool(enabled))
        tip = self._FIT_TOOLTIP if enabled else self._FIT_DISABLED_TOOLTIP
        button.setToolTip(tip)
        button.setAccessibleName(tip)


class UltraViewCard(QFrame):
    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    autofit_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, model: CardViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_custom_menu)
        self._model = model
        self._press_pos: QPoint | None = None
        self._menu: QMenu | None = None
        self._raw_image: QImage | None = None
        self._source_pixmap: QPixmap | None = None
        self._scale_buffer: QPixmap | None = None
        self._scale_key: tuple | None = None
        self._raw_cache_key: int | None = None
        self._preview_quality = QUALITY_SMOOTH
        self._lod_level = LOD_FULL
        self._lod_show_title = True
        self._lod_show_source = True
        self._lod_presentation = False
        self._show_card_actions = bool(model.show_card_actions)
        self._card_hovered = False
        self._action_focus_revealed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("ultraViewCardHeader")
        self._header.setFixedHeight(CARD_HEADER_HEIGHT)
        header = QHBoxLayout(self._header)
        # Vertical margins stay 0 so AlignVCenter is relative to contentsRect()
        # (the 34 px header), not a second inset that fought the action-bar hint.
        header.setContentsMargins(8, 0, 10, 0)
        header.setSpacing(6)
        self._dot = _ColorDot(self._header)
        header.addWidget(self._dot, 0, Qt.AlignVCenter)
        self._type_chip = QToolButton(self._header)
        self._type_chip.setObjectName("ultraViewCardTypeChip")
        self._type_chip.setAutoRaise(False)
        # Purely informational (icon + section label, no clicked handler): it
        # must not steal the press from the card drag gesture underneath it,
        # so it neither takes tab focus nor accepts mouse hit-testing.
        self._type_chip.setFocusPolicy(Qt.NoFocus)
        self._type_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._type_chip.setCursor(Qt.ArrowCursor)
        self._type_chip.setFixedHeight(22)
        self._type_chip.setIconSize(QSize(12, 12))
        self._type_chip.setProperty("role", "typeChip")
        header.addWidget(self._type_chip, 0, Qt.AlignVCenter)
        self._title = _ElideLabel("", self._header)
        header.addWidget(self._title, 1, Qt.AlignVCenter)
        self._status = QLabel("", self._header)
        self._status.setObjectName("ultraViewCardStatus")
        header.addWidget(self._status, 0, Qt.AlignVCenter)
        self._sync_btn = QToolButton(self._header)
        self._sync_btn.setObjectName("ultraViewCardSyncButton")
        self._sync_btn.setText("同步")
        self._sync_btn.setIcon(Icons.ultraview_sync())
        self._sync_btn.setIconSize(QSize(14, 14))
        self._sync_btn.setToolTip("抓取原 View 当前画面，不重新计算")
        self._sync_btn.setAccessibleName("同步到最新预览")
        self._sync_btn.setCursor(Qt.PointingHandCursor)
        self._sync_btn.setAutoRaise(False)
        self._sync_btn.setFixedHeight(24)
        self._sync_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._sync_btn.clicked.connect(self._emit_sync)
        self._sync_btn.hide()
        header.addWidget(self._sync_btn, 0, Qt.AlignVCenter)
        self._action_bar = _CardActionBar(self._header)
        self._action_bar.button("open").clicked.connect(self._emit_open_source)
        self._action_bar.button("focus").clicked.connect(self._emit_focus)
        self._action_bar.button("fit").clicked.connect(self._emit_autofit)
        self._action_bar.button("remove").clicked.connect(self._emit_remove)
        self._action_bar.button("more").clicked.connect(self._emit_more)
        self._action_buttons = tuple(
            button
            for action in ("open", "focus", "fit", "remove", "more")
            if (button := self._action_bar.button(action)) is not None
        )
        for button in self._action_buttons:
            button.installEventFilter(self)
        header.addWidget(self._action_bar, 0, Qt.AlignVCenter)
        root.addWidget(self._header, 0)

        self._image = QLabel(self)
        self._image.setObjectName("ultraViewCardImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setWordWrap(True)
        self._image.setMinimumHeight(max(8, MIN_CARD_CHROME_HEIGHT // 4))
        self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._image, 1)

        self._orphan_bar = QWidget(self)
        self._orphan_bar.setObjectName("ultraViewCardOrphanBar")
        orphan = QHBoxLayout(self._orphan_bar)
        orphan.setContentsMargins(8, 2, 8, 2)
        orphan.setSpacing(6)
        self._rebind_btn = QPushButton("重新绑定", self._orphan_bar)
        self._rebind_btn.setObjectName("ultraViewCardRebindButton")
        self._rebind_btn.clicked.connect(self._emit_rebind)
        self._remove_btn = QPushButton("从总览移除", self._orphan_bar)
        self._remove_btn.setObjectName("ultraViewCardOrphanRemoveButton")
        self._remove_btn.clicked.connect(self._emit_remove)
        orphan.addWidget(self._rebind_btn)
        orphan.addWidget(self._remove_btn)
        orphan.addStretch(1)
        root.addWidget(self._orphan_bar, 0)

        self._footer = QWidget(self)
        self._footer.setObjectName("ultraViewCardFooter")
        self._footer.setFixedHeight(CARD_FOOTER_HEIGHT)
        footer = QHBoxLayout(self._footer)
        footer.setContentsMargins(8, 2, 8, 4)
        footer.setSpacing(6)
        self._foot_left = _ElideLabel("", self._footer)
        self._foot_source = _ElideLabel("", self._footer)
        self._foot_source.setObjectName("ultraViewCardSource")
        footer.addWidget(self._foot_left, 1)
        footer.addWidget(self._foot_source, 0)
        root.addWidget(self._footer, 0)

        self.apply_model(model)

    def model(self) -> CardViewModel:
        return self._model

    def slot_id(self) -> str:
        return self._model.slot_id

    def action_bar(self) -> QFrame:
        return self._action_bar

    def action_button(self, action: str) -> QToolButton | None:
        return self._action_bar.button(action)

    def _fit_is_enabled(self) -> bool:
        return False

    def _header_is_narrow(self) -> bool:
        width = self._header.width()
        return width > 0 and width < TYPE_CHIP_ICON_ONLY_WIDTH

    def _sync_action_bar(self) -> None:
        # Header actions are not lod_visibility.body_actions (that flag is
        # for orphan/body chrome). TITLE_ONLY still shows open / focus / remove.
        show = not self._lod_presentation and (
            self._show_card_actions
            or self._card_hovered
            or self.hasFocus()
            or self._action_focus_revealed
        )
        if not show and not self._action_focus_revealed:
            focused = QApplication.focusWidget()
            if focused in self._action_buttons:
                # Qt otherwise promotes a hidden action button's startup focus
                # to the card, immediately re-opening a hover-only action bar.
                focused.clearFocus()
        self._action_bar.setVisible(show)
        if not show:
            return
        compact = self._lod_level == LOD_TITLE_ONLY or self._header_is_narrow()
        self._action_bar.set_compact(compact)
        self._action_bar.set_fit_enabled(self._fit_is_enabled())

    def _squeeze_header_for_actions(self) -> None:
        """Omit title/status before the action bar would have to hide remove."""
        if self._lod_presentation or not self._action_bar.isVisible():
            return
        header = self._header
        layout = header.layout()
        if layout is None or header.width() <= 0:
            return
        margins = layout.contentsMargins()
        spacing = layout.spacing()
        extras = [
            widget
            for widget in (self._dot, self._type_chip, self._sync_btn)
            if widget.isVisible()
        ]
        reserved = margins.left() + margins.right()
        reserved += self._action_bar.sizeHint().width()
        reserved += sum(
            max(widget.width(), widget.sizeHint().width()) for widget in extras
        )
        reserved += spacing * (len(extras) + 1)
        leftover = header.width() - reserved
        if leftover < 36:
            self._status.setVisible(False)
        if leftover < 24:
            self._title.setVisible(False)

    def _emit_autofit(self, _checked: bool = False) -> None:
        if not self._fit_is_enabled():
            return
        self.autofit_requested.emit(self._model.section, self._model.view_id)

    def _emit_more(self, _checked: bool = False) -> None:
        menu = self.make_context_menu()
        button = self._action_bar.button("more")
        if button is None:
            menu.popup(self.mapToGlobal(QPoint(self.width(), 0)))
            return
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))

    def header_height(self) -> int:
        return self._header.height()

    def footer_height(self) -> int:
        return self._footer.height()

    def preview_display_size(self) -> tuple[int, int]:
        size = self._preview_fit_size()
        dpr = _effective_device_pixel_ratio(self)
        return (
            max(1, int(round(max(1, size.width()) * dpr))),
            max(1, int(round(max(1, size.height()) * dpr))),
        )

    def chrome_height(self) -> int:
        extra = self._orphan_bar.height() if self._orphan_bar.isVisible() else 0
        return self._header.height() + self._footer.height() + extra

    def apply_model(self, model: CardViewModel) -> None:
        self._model = model
        self._lod_show_title = bool(model.show_title)
        self._lod_show_source = bool(model.show_source)
        previous_show_actions = self._show_card_actions
        self._show_card_actions = bool(model.show_card_actions)
        if previous_show_actions and not self._show_card_actions:
            # A newly hidden bar can retain startup focus on an offscreen Qt
            # platform. Only an explicit later keyboard transfer reveals it.
            self._action_focus_revealed = False
        title = model.title or model.view_id
        self._dot.set_color(model.tab_color)
        self._title.set_full_text(title)
        if model.status == STATUS_MISSING:
            self._status.setText(STATUS_LABELS_ZH[STATUS_MISSING])
        elif model.status == STATUS_STALE:
            self._status.setText(STALE_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._status.setText(ORPHANED_CARD_COPY)
        else:
            self._status.setText("")
        self._status.setProperty("status", model.status)
        section_label = SECTION_LABELS_ZH.get(model.section, model.section)
        self._foot_left.set_full_text(
            f"{section_label} · {_range_text(model.x_range, model.x_unit)}"
        )
        self._foot_source.set_full_text(model.source_summary if model.show_source else "")
        self._sync_type_chip(section_label)
        self._set_image(model)
        _set_flag(self, "selected", model.selected)
        _set_flag(self, "dimmed", model.dimmed)
        _set_flag(self, "orphaned", model.status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", model.replacement_armed)
        self.setProperty("status", model.status)
        self._apply_dim(model.dimmed)
        self._apply_lod_visibility()
        _repolish(self)
        _repolish(self._status)
        parts = [
            section_label,
            title,
            STATUS_LABELS_ZH.get(model.status, model.status),
        ]
        if model.selected:
            parts.append("已选中")
        if model.dimmed:
            parts.append("已弱化")
        if model.replacement_armed:
            parts.append("等待替换")
        if model.status == STATUS_ORPHANED:
            parts.append("源已删除")
        if model.status == STATUS_STALE:
            parts.append("可同步")
        self.setAccessibleName(" ".join(part for part in parts if part))
        self.setToolTip(_full_tooltip(title, model.section, model.source_summary, model.status))

    def set_selected(self, on: bool) -> None:
        wanted = bool(on)
        if bool(self._model.selected) == wanted:
            return
        self.apply_model(replace(self._model, selected=wanted))

    def make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("ultraViewCardMenu")
        apply_rounded_menu_chrome(menu)
        if self._model.status == STATUS_STALE:
            sync_act = menu.addAction("同步到最新")
            sync_act.triggered.connect(self._emit_sync)
        replace_act = menu.addAction("替换为…")
        unplaced_act = menu.addAction("移到未放置")
        copy_act = menu.addAction("复制本卡图像")
        replace_act.triggered.connect(self._emit_rebind)
        unplaced_act.triggered.connect(self._emit_unplaced)
        copy_act.triggered.connect(self._emit_copy)
        self._menu = menu
        return menu

    def apply_lod(
        self,
        level: str,
        *,
        show_title: bool,
        show_source: bool,
        show_card_actions: bool | None = None,
        presentation: bool = False,
    ) -> None:
        self._lod_level = level if level in {LOD_FULL, LOD_NO_FOOTER, LOD_TITLE_ONLY} else LOD_FULL
        self._lod_show_title = bool(show_title)
        self._lod_show_source = bool(show_source)
        if show_card_actions is not None:
            self._show_card_actions = bool(show_card_actions)
        self._lod_presentation = bool(presentation)
        self._apply_lod_visibility()

    def _apply_lod_visibility(self) -> None:
        vis = lod_visibility(self._lod_level)
        self.setProperty("lod", self._lod_level)
        title_text = self._model.title or self._model.view_id
        self._title.setVisible(bool(vis.title and self._lod_show_title and title_text))
        self._sync_type_chip(SECTION_LABELS_ZH.get(self._model.section, self._model.section))
        self._type_chip.setVisible(bool(vis.type_chip))
        has_status = bool(self._status.text())
        self._status.setVisible(bool(vis.trust and has_status))
        self._sync_btn.setVisible(bool(vis.trust and self._model.status == STATUS_STALE))
        self._sync_action_bar()
        self._squeeze_header_for_actions()
        footer = bool(vis.footer and self._lod_show_source)
        self._footer.setVisible(footer)
        self._footer.setFixedHeight(CARD_FOOTER_HEIGHT if footer else 0)
        orphaned = self._model is not None and self._model.status == STATUS_ORPHANED
        self._orphan_bar.setVisible(bool(vis.body_actions and orphaned and not self._lod_presentation))
        self._set_preview_visible(bool(vis.preview))
        _repolish(self)

    def _set_preview_visible(self, visible: bool) -> None:
        if visible:
            self._image.setMinimumHeight(max(8, MIN_CARD_CHROME_HEIGHT // 4))
            self._image.setMaximumHeight(QWIDGETSIZE_MAX)
            self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._image.setVisible(True)
            # A raw image can have arrived while the preview was hidden at a
            # lower LOD tier (``_set_image`` skips scaling in that case); fit
            # it now so growing back to a preview-showing tier is never
            # missing its pixmap.
            self._fit_card_image()
            return
        self._image.setVisible(False)
        self._image.setMinimumHeight(0)
        self._image.setMaximumHeight(0)

    def _sync_type_chip(self, section_label: str) -> None:
        label = str(section_label or self._model.section)
        icon_factory = _SECTION_TYPE_ICONS.get(self._model.section)
        if icon_factory is not None:
            self._type_chip.setIcon(icon_factory())
        else:
            self._type_chip.setIcon(Icons.mode_ultraview())
        self._type_chip.setToolTip(label)
        self._type_chip.setAccessibleName(label)
        icon_only = self._header.width() > 0 and self._header.width() < TYPE_CHIP_ICON_ONLY_WIDTH
        if icon_only:
            self._type_chip.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self._type_chip.setText("")
            self._type_chip.setFixedWidth(22)
        else:
            self._type_chip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._type_chip.setText(label)
            self._type_chip.setMinimumWidth(0)
            self._type_chip.setMaximumWidth(QWIDGETSIZE_MAX)
            hint = self._type_chip.sizeHint()
            self._type_chip.setFixedWidth(max(22, hint.width() + 8))

    def set_preview_quality(self, quality: str) -> None:
        wanted = QUALITY_FAST if quality == QUALITY_FAST else QUALITY_SMOOTH
        if wanted == self._preview_quality:
            return
        self._preview_quality = wanted
        self._fit_card_image()

    def scale_buffer(self) -> QPixmap | None:
        return self._scale_buffer

    def _set_image(self, model: CardViewModel) -> None:
        image = model.image
        if image is not None and not (callable(getattr(image, "isNull", None)) and image.isNull()):
            raw = image if isinstance(image, QImage) else None
            cache_key = int(raw.cacheKey()) if raw is not None else None
            if (
                raw is not None
                and self._raw_image is not None
                and self._raw_cache_key is not None
                and cache_key == self._raw_cache_key
            ):
                return
            self._raw_image = raw
            self._raw_cache_key = cache_key
            self._source_pixmap = None
            self._scale_buffer = None
            self._scale_key = None
            self._image.setText("")
            # TITLE_ONLY hides the preview label entirely; scaling a pixmap
            # nobody can see is pure waste on the LOD tier that carries the
            # most cards.  ``_set_preview_visible(True)`` re-fits on the way
            # back up so the buffer is never stale, just deferred.
            if lod_visibility(self._lod_level).preview:
                self._fit_card_image()
            return
        self._raw_image = None
        self._raw_cache_key = None
        self._source_pixmap = None
        self._scale_buffer = None
        self._scale_key = None
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setPixmap(QPixmap())
        if model.status == STATUS_MISSING:
            self._image.setText(MISSING_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._image.setText(ORPHANED_CARD_COPY)
        elif model.status == STATUS_STALE:
            self._image.setText(STALE_CARD_COPY)
        else:
            self._image.setText("")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_type_chip(SECTION_LABELS_ZH.get(self._model.section, self._model.section))
        self._sync_action_bar()
        self._squeeze_header_for_actions()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._card_hovered = True
        super().enterEvent(event)
        self._apply_lod_visibility()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._card_hovered = False
        super().leaveEvent(event)
        self._apply_lod_visibility()

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._apply_lod_visibility()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._apply_lod_visibility)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched in self._action_buttons:
            if event.type() == QEvent.FocusIn:
                self._action_focus_revealed = True
                self._apply_lod_visibility()
            elif event.type() == QEvent.FocusOut:
                QTimer.singleShot(0, self._sync_action_focus_after_qt)
        return super().eventFilter(watched, event)

    def _sync_action_focus_after_qt(self) -> None:
        self._action_focus_revealed = any(
            button.hasFocus() for button in self._action_buttons
        )
        self._apply_lod_visibility()
        if lod_visibility(self._lod_level).preview:
            self._fit_card_image()

    def _preview_fit_size(self) -> QSize:
        """Inner label box after QSS padding, not the outer ``size()``."""
        avail = self._image.contentsRect().size()
        if avail.width() < 2 or avail.height() < 2:
            return self._image.size()
        return avail

    def _fit_card_image(self) -> None:
        if self._raw_image is None:
            return
        raw_w = self._raw_image.width()
        raw_h = self._raw_image.height()
        avail = self._preview_fit_size()
        if avail.width() < 2 or avail.height() < 2:
            return
        box_w, box_h = preview_reading_box(
            avail.width(), avail.height(), (raw_w, raw_h)
        )
        dpr = _effective_device_pixel_ratio(self)
        cap_w = max(1, min(int(round(box_w * dpr)), raw_w))
        cap_h = max(1, min(int(round(box_h * dpr)), raw_h))
        key = (
            cap_w,
            cap_h,
            dpr,
            self._preview_quality,
            int(self._raw_image.cacheKey()),
        )
        if self._scale_buffer is not None and self._scale_key == key:
            self._image.setAlignment(Qt.AlignCenter)
            self._image.setPixmap(self._scale_buffer)
            return
        if self._source_pixmap is None:
            self._source_pixmap = QPixmap.fromImage(self._raw_image)
        transform = (
            Qt.FastTransformation
            if self._preview_quality == QUALITY_FAST
            else Qt.SmoothTransformation
        )
        scaled = self._source_pixmap.scaled(
            cap_w, cap_h, Qt.KeepAspectRatio, transform
        )
        scaled.setDevicePixelRatio(dpr)
        self._scale_buffer = scaled
        self._scale_key = key
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setPixmap(scaled)

    def restore_dim(self) -> None:
        self._apply_dim(bool(self._model.dimmed))

    def _apply_dim(self, dimmed: bool) -> None:
        if dimmed:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(DIMMED_OPACITY)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def _emit_open_source(self, _checked: bool = False) -> None:
        if self._model.status == STATUS_ORPHANED:
            self.rebind_arm_requested.emit(self._model.section, self._model.view_id)
            return
        self.open_source_requested.emit(self._model.section, self._model.view_id)

    def _emit_sync(self, _checked: bool = False) -> None:
        if self._model.status != STATUS_STALE:
            return
        self.sync_requested.emit(self._model.section, self._model.view_id)

    def _emit_focus(self, _checked: bool = False) -> None:
        self.focus_requested.emit(self._model.section, self._model.view_id)

    def _emit_rebind(self, _checked: bool = False) -> None:
        self.rebind_arm_requested.emit(self._model.section, self._model.view_id)

    def _emit_unplaced(self, _checked: bool = False) -> None:
        self.move_to_unplaced_requested.emit(self._model.section, self._model.view_id)

    def _emit_remove(self, _checked: bool = False) -> None:
        self.remove_ref_requested.emit(self._model.section, self._model.view_id)

    def _emit_copy(self, _checked: bool = False) -> None:
        self.copy_card_image_requested.emit(self._model.section, self._model.view_id)

    def _on_custom_menu(self, pos: QPoint) -> None:
        menu = self.make_context_menu()
        menu.popup(self.mapToGlobal(pos))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            router = getattr(self.parentWidget(), "route_card_press", None)
            if callable(router) and router(self, event):
                event.accept()
                return
            self._press_pos = QPoint(event.pos())
            self.selected.emit(self._model.section, self._model.view_id)
            handler = getattr(self.parentWidget(), "handle_card_mouse_press", None)
            if callable(handler):
                handler(self, event)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        handler = getattr(parent, "handle_card_double_click", None)
        if callable(handler):
            handler(self._model.section, self._model.view_id)
            event.accept()
            return
        self.focus_requested.emit(self._model.section, self._model.view_id)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        handler = getattr(parent, "handle_card_mouse_move", None)
        armed = getattr(parent, "is_slot_drag_armed", None)
        if callable(handler) and (
            event.buttons() & Qt.LeftButton or (callable(armed) and armed())
        ):
            handler(self, event)
            return
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._model.section, self._model.view_id)
        self.drag_started.emit("card")
        _run_ultraview_drag(
            self, mime, Qt.MoveAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
            self._press_pos = None
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._emit_focus()
            event.accept()
            return
        if key == Qt.Key_Delete:
            self._emit_remove()
            event.accept()
            return
        if key == Qt.Key_Backspace:
            self._emit_unplaced()
            event.accept()
            return
        if key == Qt.Key_O:
            self._emit_open_source()
            event.accept()
            return
        if key == Qt.Key_R:
            self._emit_rebind()
            event.accept()
            return
        if key == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self._emit_copy()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(self._model.slot_id)
            return
        _set_flag(self, "dropActive", False)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(self._model.slot_id)
            return
        _set_flag(self, "dropActive", False)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        note = getattr(self.parentWidget(), "note_replace_hover", None)
        if callable(note):
            note(None)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        parent = self.parentWidget()
        armed = getattr(parent, "is_replace_armed", None)
        clear = getattr(parent, "clear_replace_hover", None)
        slot_id = self._model.slot_id
        replace_ok = callable(armed) and armed(slot_id)
        if callable(clear):
            clear()
        if extracted is None:
            return
        if not replace_ok:
            return
        section, view_id = extracted
        self.ref_dropped.emit(slot_id, section, view_id)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = self.make_context_menu()
        menu.popup(event.globalPos())
        event.accept()

class FreeGridCard(UltraViewCard):
    """A static preview card. Layout moves use the board gesture, not QDrag."""

    layout_key_requested = pyqtSignal(str, str, int, int, bool)
    preset_requested = pyqtSignal(str, str, str)

    def __init__(self, model: CardViewModel, parent: QWidget | None = None) -> None:
        self._drag_shell_only = False
        super().__init__(model, parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)

    def set_drag_placeholder(self, on: bool) -> None:
        """Hide preview pixels while keeping the card shell during a live drag."""
        wanted = bool(on)
        if self._drag_shell_only == wanted:
            return
        self._drag_shell_only = wanted
        if wanted:
            self._image.clear()
            return
        if self._raw_image is not None:
            self._fit_card_image()
            return
        self._set_image(self._model)

    def _fit_card_image(self) -> None:
        if getattr(self, "_drag_shell_only", False):
            return
        super()._fit_card_image()

    def _fit_is_enabled(self) -> bool:
        return True

    def make_context_menu(self) -> QMenu:
        menu = super().make_context_menu()
        size_menu = add_rounded_submenu(menu, "自由网格尺寸")
        for preset, label in (
            ("small", "小 3 × 2"),
            ("standard", "标准 4 × 3"),
            ("wide", "宽 6 × 3"),
            ("tall", "高 4 × 5"),
            ("large", "大 6 × 6"),
            ("banner", "横幅 12 × 4"),
        ):
            action = size_menu.addAction(label)
            action.triggered.connect(partial(self._emit_preset, preset))
        return menu

    def _emit_preset(self, preset: str, _checked: bool = False) -> None:
        self.preset_requested.emit(self._model.section, self._model.view_id, preset)

    def _emit_autofit(self, _checked: bool = False) -> None:
        self.autofit_requested.emit(self._model.section, self._model.view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            parent = self.parentWidget()
            already_selected = bool(self._model.selected)
            shift = bool(event.modifiers() & Qt.ShiftModifier)
            if not shift and not already_selected:
                self.selected.emit(self._model.section, self._model.view_id)
            handler = getattr(parent, "handle_card_mouse_press", None)
            if callable(handler):
                handler(self, event, already_selected)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        handler = getattr(parent, "handle_card_mouse_move", None)
        gesture = getattr(parent, "gesture", None)
        armed = callable(gesture) and gesture().is_armed()
        if callable(handler) and (event.buttons() & Qt.LeftButton or armed):
            handler(self, event)
            return
        hover = getattr(parent, "handle_card_mouse_hover", None)
        if callable(hover):
            hover(self, event)
        QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
        self._press_pos = None
        QWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.AltModifier:
            delta = {
                Qt.Key_Left: (-1, 0),
                Qt.Key_Right: (1, 0),
                Qt.Key_Up: (0, -1),
                Qt.Key_Down: (0, 1),
            }.get(event.key())
            if delta is not None:
                self.layout_key_requested.emit(
                    self._model.section,
                    self._model.view_id,
                    delta[0],
                    delta[1],
                    bool(event.modifiers() & Qt.ShiftModifier),
                )
                event.accept()
                return
        handler = getattr(self.parentWidget(), "handle_selection_key", None)
        if callable(handler) and handler(event):
            event.accept()
            return
        super().keyPressEvent(event)
