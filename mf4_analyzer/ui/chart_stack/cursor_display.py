"""Cursor-result display preferences, pure projection, and settings popover."""

from __future__ import annotations

from dataclasses import dataclass, fields
from html import escape
import json
from typing import Iterable

from PyQt5.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QVBoxLayout,
)


CURSOR_DISPLAY_SETTINGS_KEY = "charts/time_cursor/display_options_v1"


@dataclass(frozen=True)
class CursorDisplayOptions:
    show_max_point: bool = True
    show_min_point: bool = True
    show_max_value: bool = True
    show_min_value: bool = True
    show_avg_value: bool = True


_OPTION_NAMES = tuple(item.name for item in fields(CursorDisplayOptions))


class CursorDisplaySettingsStore:
    """Persist one immutable option snapshot under the versioned JSON key."""

    def __init__(self, settings=None):
        self._settings = settings if settings is not None else QSettings()

    def load(self) -> CursorDisplayOptions:
        raw = self._settings.value(CURSOR_DISPLAY_SETTINGS_KEY, None)
        if raw is None:
            return CursorDisplayOptions()
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return CursorDisplayOptions()
        if not isinstance(payload, dict):
            return CursorDisplayOptions()
        return CursorDisplayOptions(**{
            name: payload[name] if type(payload.get(name)) is bool else True
            for name in _OPTION_NAMES
        })

    def save(self, options: CursorDisplayOptions) -> None:
        if not isinstance(options, CursorDisplayOptions):
            raise TypeError("options must be CursorDisplayOptions")
        payload = {name: getattr(options, name) for name in _OPTION_NAMES}
        self._settings.setValue(
            CURSOR_DISPLAY_SETTINGS_KEY,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self._settings.sync()


@dataclass(frozen=True)
class CursorDisplayBranch:
    label: str
    current_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None


@dataclass(frozen=True)
class CursorDisplayChannel:
    identity: object
    source_label: str
    channel_label: str
    color: str = "#111827"
    unit_suffix: str = ""
    current_value: float | None = None
    delta: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    branches: tuple[CursorDisplayBranch, ...] = ()
    diagnostic: str = ""

    @property
    def qualified_label(self) -> str:
        source = str(self.source_label or "").strip()
        channel = str(self.channel_label or "").strip()
        return f"{source} / {channel}" if source else channel


@dataclass(frozen=True)
class CursorDisplayRow:
    label: str
    value: str


@dataclass(frozen=True)
class CursorDisplayBlock:
    identity: object
    qualified_label: str
    color: str
    visible_rows: tuple[CursorDisplayRow, ...]
    tooltip_rows: tuple[CursorDisplayRow, ...]
    diagnostic: str = ""


@dataclass(frozen=True)
class CursorPresentation:
    blocks: tuple[CursorDisplayBlock, ...]
    html: str
    tooltip: str
    layout_category: str
    cursor_mode: str
    x_mode: str
    mini: bool


def enabled_value_fields(options: CursorDisplayOptions):
    """Return enabled value fields in the product order Min, Max, Avg."""
    return tuple(
        item for item, enabled in (
            (("Min", "min_value"), options.show_min_value),
            (("Max", "max_value"), options.show_max_value),
            (("Avg", "avg_value"), options.show_avg_value),
        )
        if enabled
    )


def _formatted(value, unit="") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.4g}{unit}"
    except (TypeError, ValueError):
        return f"{value}{unit}"


def _time_rows(channel, options, cursor_mode, mini):
    if cursor_mode == "single":
        row = CursorDisplayRow(
            "Value", _formatted(channel.current_value, channel.unit_suffix)
        )
        return (row,), (row,)
    visible = [CursorDisplayRow("Δ", _formatted(channel.delta, channel.unit_suffix))]
    tooltip = list(visible)
    for label, attr in enabled_value_fields(options):
        row = CursorDisplayRow(label, _formatted(getattr(channel, attr), channel.unit_suffix))
        tooltip.append(row)
        if not mini:
            visible.append(row)
    return tuple(visible), tuple(tooltip)


def _custom_rows(channel, options, cursor_mode, mini):
    visible = []
    tooltip = []
    enabled = enabled_value_fields(options)
    priority = next(
        (item for wanted in ("Avg", "Max", "Min") for item in enabled if item[0] == wanted),
        None,
    )
    for branch in channel.branches:
        if cursor_mode == "single":
            row = CursorDisplayRow(branch.label, _formatted(branch.current_value, channel.unit_suffix))
            visible.append(row)
            tooltip.append(row)
            continue
        visible.append(CursorDisplayRow(branch.label, ""))
        tooltip.append(CursorDisplayRow(branch.label, ""))
        for label, attr in enabled:
            row = CursorDisplayRow(label, _formatted(getattr(branch, attr), channel.unit_suffix))
            tooltip.append(row)
            if not mini:
                visible.append(row)
        if mini and priority is not None:
            label, attr = priority
            visible.append(CursorDisplayRow(label, _formatted(getattr(branch, attr), channel.unit_suffix)))
    if not visible and channel.diagnostic:
        row = CursorDisplayRow("状态", str(channel.diagnostic))
        visible.append(row)
        tooltip.append(row)
    return tuple(visible), tuple(tooltip)


def _block_html(
    block: CursorDisplayBlock,
    *,
    constrained: bool,
    header_override: str | None = None,
) -> str:
    color = escape(block.color or "#111827", quote=True)
    header = escape(header_override or block.qualified_label)
    out = [
        '<table cellspacing="0" cellpadding="0" style="font-size:11px;">',
        f'<tr><td colspan="8" style="color:{color};font-weight:600;padding:2px 0;">{header}</td></tr>',
    ]
    if constrained:
        pending = []

        def append_metric_pair(rows):
            values = " · ".join(
                f'<span style="color:#94a3b8;">{escape(row.label)}</span> '
                f'<span style="color:{color};font-family:Consolas,monospace;">'
                f'{escape(row.value)}</span>'
                for row in rows
            )
            out.append(
                '<tr><td colspan="4" style="padding-right:4px;">'
                f'{values}</td></tr>'
            )

        for row in block.visible_rows:
            if not row.value:
                if pending:
                    append_metric_pair(pending)
                    pending = []
                out.append(
                    '<tr>'
                    f'<td colspan="4" style="color:#94a3b8;">{escape(row.label)}</td>'
                    '</tr>'
                )
                continue
            pending.append(row)
            if len(pending) == 2:
                append_metric_pair(pending)
                pending = []
        if pending:
            append_metric_pair(pending)
    else:
        out.append('<tr>')
        for row in block.visible_rows:
            if not row.value:
                out.append(
                    f'<td colspan="2" style="color:#94a3b8;padding-right:10px;">'
                    f'{escape(row.label)}</td>'
                )
                continue
            out.append(
                f'<td style="color:#94a3b8;padding-right:4px;">{escape(row.label)}</td>'
                f'<td style="color:{color};font-family:Consolas,monospace;padding-right:10px;">'
                f'{escape(row.value)}</td>'
            )
        out.append('</tr>')
    out.append('</table>')
    return "".join(out)


def render_cursor_presentation(
    projection: CursorPresentation,
    *,
    layout_category: str | None = None,
    visible_count: int | None = None,
    header_overrides: tuple[str, ...] | None = None,
) -> str:
    category = layout_category or projection.layout_category
    constrained = category == "constrained"
    count = len(projection.blocks) if visible_count is None else max(0, visible_count)
    shown = projection.blocks[:count]
    gap = "4px" if constrained else "6px"
    parts = [f'<div style="margin:0;">']
    for index, block in enumerate(shown):
        if index:
            parts.append(f'<div style="height:{gap};"></div>')
        header = (
            header_overrides[index]
            if header_overrides is not None and index < len(header_overrides)
            else None
        )
        parts.append(_block_html(
            block, constrained=constrained, header_override=header
        ))
    omitted = len(projection.blocks) - len(shown)
    if omitted:
        parts.append(
            '<div style="color:#64748b;padding-top:4px;">'
            f'+{omitted} channels</div>'
        )
    parts.append('</div>')
    return "".join(parts)


def _tooltip(blocks: Iterable[CursorDisplayBlock]) -> str:
    lines = []
    for block in blocks:
        lines.append(block.qualified_label)
        branch = ""
        for row in block.tooltip_rows:
            if row.label.startswith("X") and not row.value:
                branch = row.label
                lines.append(branch)
                continue
            prefix = f"{branch} " if branch else ""
            lines.append(f"{prefix}{row.label}={row.value}")
        if block.diagnostic and not any(
            row.value == block.diagnostic for row in block.tooltip_rows
        ):
            lines.append(block.diagnostic)
    return "\n".join(lines)


def build_cursor_presentation(
    channels: Iterable[CursorDisplayChannel],
    options: CursorDisplayOptions,
    *,
    cursor_mode: str,
    x_mode: str,
    mini: bool,
    layout_category: str = "natural",
) -> CursorPresentation:
    """Build a deterministic, calculation-free cursor-result projection."""
    if cursor_mode not in {"single", "dual"}:
        raise ValueError("cursor_mode must be single or dual")
    if x_mode not in {"time", "custom"}:
        raise ValueError("x_mode must be time or custom")
    blocks = []
    for channel in channels:
        if x_mode == "custom":
            visible, tooltip = _custom_rows(channel, options, cursor_mode, mini)
        else:
            visible, tooltip = _time_rows(channel, options, cursor_mode, mini)
        if not visible:
            continue
        blocks.append(CursorDisplayBlock(
            identity=channel.identity,
            qualified_label=channel.qualified_label,
            color=channel.color,
            visible_rows=visible,
            tooltip_rows=tooltip,
            diagnostic=channel.diagnostic,
        ))
    projection = CursorPresentation(
        blocks=tuple(blocks),
        html="",
        tooltip="",
        layout_category=layout_category,
        cursor_mode=cursor_mode,
        x_mode=x_mode,
        mini=bool(mini),
    )
    return CursorPresentation(
        blocks=projection.blocks,
        html=render_cursor_presentation(projection),
        tooltip=_tooltip(projection.blocks),
        layout_category=projection.layout_category,
        cursor_mode=projection.cursor_mode,
        x_mode=projection.x_mode,
        mini=projection.mini,
    )


class CursorDisplayPopover(QFrame):
    """Five-option floating control anchored by :class:`TimeChartCard`."""

    options_changed = pyqtSignal(object)
    visibility_changed = pyqtSignal(object)

    _LABELS = (
        ("show_max_point", "显示最大值点"),
        ("show_min_point", "显示最小值点"),
        ("show_max_value", "显示最大值"),
        ("show_min_value", "显示最小值"),
        ("show_avg_value", "显示平均值"),
    )

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setObjectName("cursorDisplayPopover")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(252)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        title = QLabel("游标显示", self)
        title.setObjectName("cursorDisplayPopoverTitle")
        layout.addWidget(title)
        point_group = QLabel("极值点", self)
        point_group.setObjectName("cursorDisplayPopoverGroup")
        layout.addWidget(point_group)
        self._checks = {}
        for index, (name, label) in enumerate(self._LABELS):
            if index == 2:
                value_group = QLabel("双游标统计", self)
                value_group.setObjectName("cursorDisplayPopoverGroup")
                layout.addWidget(value_group)
            check = QCheckBox(label, self)
            check.setObjectName("cursorDisplayOption")
            check.setProperty("optionName", name)
            check.toggled.connect(self._on_toggle)
            self._checks[name] = check
            layout.addWidget(check)
        self._note = QLabel("", self)
        self._note.setObjectName("cursorDisplayPopoverNote")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        self._options = CursorDisplayOptions()
        self._refit_pending = False
        self.set_options(self._options)

    def options(self) -> CursorDisplayOptions:
        return self._options

    def checkbox(self, name: str) -> QCheckBox:
        return self._checks[name]

    def context_note(self) -> str:
        return self._note.text()

    def set_options(self, options: CursorDisplayOptions) -> None:
        self._options = options
        for name, check in self._checks.items():
            old = check.blockSignals(True)
            check.setChecked(getattr(options, name))
            check.blockSignals(old)

    def set_cursor_mode(self, mode: str) -> None:
        self._note.setText(
            "最大值、最小值与平均值仅用于双游标统计。"
            if mode == "single" else ""
        )
        self._note.setVisible(bool(self._note.text()))
        self._schedule_refit()

    def show_for(self, anchor, cursor_mode: str) -> None:
        self.set_cursor_mode(cursor_mode)
        self.adjustSize()
        anchor_global = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.move(anchor_global.x() - self.width(), anchor_global.y() + 8)
        self.show()
        self.raise_()
        self.visibility_changed.emit(self.frameGeometry())
        self._schedule_refit()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(None)

    def _on_toggle(self, _checked):
        sender = self.sender()
        if sender not in self._checks.values():
            return
        self._options = CursorDisplayOptions(**{
            name: check.isChecked() for name, check in self._checks.items()
        })
        self.options_changed.emit(self._options)

    def _schedule_refit(self):
        if self._refit_pending:
            return
        self._refit_pending = True
        QTimer.singleShot(0, self._deferred_refit)

    def _deferred_refit(self):
        self._refit_pending = False
        if self.layout() is not None:
            self.layout().activate()
        hint = self.sizeHint().expandedTo(self.minimumSizeHint())
        self.resize(max(hint.width(), 252), max(hint.height(), 248))
        if self.isVisible():
            self.visibility_changed.emit(self.frameGeometry())


__all__ = [
    "CURSOR_DISPLAY_SETTINGS_KEY",
    "CursorDisplayBranch",
    "CursorDisplayChannel",
    "CursorDisplayOptions",
    "CursorDisplayPopover",
    "CursorDisplaySettingsStore",
    "CursorDisplayBlock",
    "CursorDisplayRow",
    "CursorPresentation",
    "build_cursor_presentation",
    "enabled_value_fields",
    "render_cursor_presentation",
]
