"""Cursor-result display preferences, pure projection, and settings popover."""

from __future__ import annotations

from html import escape
import json
from typing import Iterable

from PyQt5.QtCore import QRectF, QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QVBoxLayout,
)

from ..cursor_display_model import (
    CursorDisplayBlock,
    CursorDisplayBranch,
    CursorDisplayChannel,
    CursorDisplayOptions,
    CursorDisplayRow,
    CursorPresentation,
    _OPTION_NAMES,
    enabled_value_fields,
)
from ..plot_helpers import cursor_result_source_count

_POPOVER_BG = QColor(255, 255, 255, 248)
_POPOVER_BORDER = QColor("#d8e0eb")
_POPOVER_RADIUS = 10.0
_DOT_MARKER = "●"


CURSOR_DISPLAY_SETTINGS_KEY = "charts/time_cursor/display_options_v1"


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


def _formatted(value, unit="") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.4g}{unit}"
    except (TypeError, ValueError):
        return f"{value}{unit}"


def _face_name(channel) -> str:
    return str(channel.channel_label or channel.qualified_label or "").strip()


_MINI_PRIORITY = ("Δ", "Avg", "Max", "Min")
_BRANCH_ATTR = {
    "min_value": "min_value",
    "max_value": "max_value",
    "avg_value": "avg_value",
    "delta": "delta_value",
}


def _identity_row(name):
    return CursorDisplayRow(name, "")


def _priority_stat(stats):
    return next(
        (row for wanted in _MINI_PRIORITY for row in stats if row.label == wanted),
        None,
    )


def _time_rows(channel, options, cursor_mode, mini):
    name = _face_name(channel)
    if cursor_mode == "single":
        value = _formatted(channel.current_value, channel.unit_suffix)
        tooltip = (CursorDisplayRow(name, value),)
        if mini:
            return (CursorDisplayRow(_DOT_MARKER, value),), tooltip
        return (CursorDisplayRow(name, value),), tooltip
    stats = []
    for label, attr in enabled_value_fields(options):
        row = CursorDisplayRow(label, _formatted(getattr(channel, attr), channel.unit_suffix))
        stats.append(row)
    tooltip = tuple(stats) if stats else (_identity_row(name),)
    if mini:
        priority = _priority_stat(stats)
        if priority is None:
            return (_identity_row(name),), tooltip
        return (CursorDisplayRow(name, priority.value, role=priority.label),), tooltip
    return tuple(stats) if stats else (_identity_row(name),), tooltip


def _custom_rows(channel, options, cursor_mode, mini):
    visible = []
    tooltip = []
    enabled = enabled_value_fields(options)
    priority = next(
        (item for wanted in _MINI_PRIORITY for item in enabled if item[0] == wanted),
        None,
    )
    if cursor_mode == "single":
        for branch in channel.branches:
            row = CursorDisplayRow(
                branch.label, _formatted(branch.current_value, channel.unit_suffix)
            )
            visible.append(row)
            tooltip.append(row)
        if visible:
            face = _DOT_MARKER if mini else _face_name(channel)
            visible.insert(0, CursorDisplayRow(face, ""))
        elif channel.diagnostic:
            row = CursorDisplayRow("状态", str(channel.diagnostic))
            visible.append(row)
            tooltip.append(row)
        return tuple(visible), tuple(tooltip)
    for branch in channel.branches:
        visible.append(CursorDisplayRow(branch.label, "", role="branch"))
        tooltip.append(CursorDisplayRow(branch.label, "", role="branch"))
        for label, attr in enabled:
            branch_attr = _BRANCH_ATTR.get(attr, attr)
            row = CursorDisplayRow(
                label, _formatted(getattr(branch, branch_attr), channel.unit_suffix)
            )
            tooltip.append(row)
            if not mini:
                visible.append(row)
        if mini and priority is not None:
            label, attr = priority
            branch_attr = _BRANCH_ATTR.get(attr, attr)
            visible.append(CursorDisplayRow(
                label, _formatted(getattr(branch, branch_attr), channel.unit_suffix)
            ))
    if not visible and channel.diagnostic:
        row = CursorDisplayRow("状态", str(channel.diagnostic))
        visible.append(row)
        tooltip.append(row)
    return tuple(visible), tuple(tooltip)


def _channel_face_name(block: CursorDisplayBlock) -> str:
    return str(block.channel_label or block.qualified_label or "").strip()


def visible_block_label(block: CursorDisplayBlock, omit_source_prefix: bool) -> str:
    """Visible identity: channel-only when D1 omits the source prefix."""
    if omit_source_prefix:
        return _channel_face_name(block)
    return str(block.qualified_label or "").strip()


def _metric_cells(rows, color: str) -> str:
    parts = []
    for row in rows:
        if not row.value:
            parts.append(
                f'<td style="color:#94a3b8;padding-right:10px;">{escape(row.label)}</td>'
            )
            continue
        parts.append(
            f'<td style="color:#94a3b8;padding-right:4px;">{escape(row.label)}</td>'
            f'<td style="color:{color};font-family:Consolas,monospace;padding-right:10px;">'
            f'{escape(row.value)}</td>'
        )
    return "".join(parts)


def _branch_groups(rows):
    groups = []
    label = None
    metrics = []
    pending = False
    for row in rows:
        if not row.value:
            if pending:
                groups.append((label, tuple(metrics)))
            label = row.label
            metrics = []
            pending = True
            continue
        metrics.append(row)
        pending = True
    if pending:
        groups.append((label, tuple(metrics)))
    return groups


def _dot_html(color: str) -> str:
    return f'<span style="color:{color};">{_DOT_MARKER}</span>'


def _compact_block_html(
    block: CursorDisplayBlock,
    *,
    color: str,
    constrained: bool,
    header_override: str | None,
    mini: bool,
    cursor_mode: str,
    x_mode: str,
) -> str:
    out = ['<table cellspacing="0" cellpadding="0" style="font-size:11px;">']
    face_name = header_override or _channel_face_name(block)
    rows = block.visible_rows
    if cursor_mode == "single" and x_mode == "time":
        row = rows[0] if rows else CursorDisplayRow(
            _DOT_MARKER if mini else face_name, "—"
        )
        if mini:
            out.append(
                '<tr>'
                f'<td style="padding-right:5px;line-height:1.15;">{_dot_html(color)}</td>'
                f'<td style="color:{color};line-height:1.15;'
                'font-family:Consolas,monospace;font-weight:650;">'
                f'{escape(row.value)}</td>'
                '</tr>'
            )
        else:
            out.append(
                '<tr>'
                f'<td style="color:{color};font-weight:600;padding-right:8px;">'
                f'{escape(row.label)}</td>'
                f'<td style="color:{color};font-family:Consolas,monospace;">'
                f'{escape(row.value)}</td>'
                '</tr>'
            )
        out.append('</table>')
        return "".join(out)
    if cursor_mode == "dual" and x_mode == "time" and mini:
        row = rows[0] if rows else CursorDisplayRow(face_name, "—")
        name = header_override or row.label
        metric_cell = ""
        if row.value:
            if row.role == "Δ":
                prefix = "△"
            elif row.role in {"Min", "Max", "Avg"}:
                prefix = escape(row.role)
            else:
                prefix = "△"
            metric_cell = (
                f'<td style="color:{color};font-family:Consolas,monospace;">'
                f'{prefix}&nbsp;{escape(row.value)}</td>'
            )
        out.append(
            '<tr>'
            f'<td style="padding-right:4px;">{_dot_html(color)}</td>'
            f'<td style="color:{color};font-weight:600;padding-right:8px;">'
            f'{escape(name)}</td>'
            f'{metric_cell}'
            '</tr>'
        )
        out.append('</table>')
        return "".join(out)
    metrics = list(rows)
    identity_label = None
    if (
        cursor_mode == "single"
        and x_mode == "custom"
        and metrics
        and not metrics[0].value
        and metrics[0].label
    ):
        identity_label = metrics[0].label
        metrics = metrics[1:]
    if mini and cursor_mode == "dual":
        face = (
            f'<td style="color:{color};font-weight:600;padding-right:8px;">'
            f'{_dot_html(color)} {escape(face_name)}</td>'
        )
    elif mini:
        face = f'<td style="padding-right:5px;">{_dot_html(color)}</td>'
    else:
        name = header_override or identity_label or face_name
        face = (
            f'<td style="color:{color};font-weight:600;padding-right:8px;">'
            f'{escape(name)}</td>'
        )
    wrap_branches = (
        constrained and mini and cursor_mode == "dual" and x_mode == "custom"
    )
    groups = _branch_groups(metrics)
    if wrap_branches:
        out.append(f'<tr>{face}</tr>')
        for label, group_rows in groups:
            cells = ""
            if label:
                cells += (
                    f'<td style="color:#94a3b8;padding-right:4px;">'
                    f'{escape(label)}</td>'
                )
            cells += _metric_cells(group_rows, color)
            out.append(f'<tr>{cells}</tr>')
    else:
        cells = face
        for label, group_rows in groups:
            if label:
                cells += (
                    f'<td style="color:#94a3b8;padding-right:4px;">'
                    f'{escape(label)}</td>'
                )
            cells += _metric_cells(group_rows, color)
        out.append(f'<tr>{cells}</tr>')
    out.append('</table>')
    return "".join(out)


def _block_html(
    block: CursorDisplayBlock,
    *,
    constrained: bool,
    header_override: str | None = None,
    mini: bool = False,
    cursor_mode: str = "dual",
    x_mode: str = "time",
    omit_visible_source_prefix: bool = False,
) -> str:
    color = escape(block.color or "#111827", quote=True)
    compact = bool(mini) or cursor_mode == "single"
    if compact:
        return _compact_block_html(
            block,
            color=color,
            constrained=constrained,
            header_override=header_override,
            mini=bool(mini),
            cursor_mode=cursor_mode,
            x_mode=x_mode,
        )
    default_header = visible_block_label(block, omit_visible_source_prefix)
    header = escape(header_override or default_header)
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
        first_cell = True
        for row in block.visible_rows:
            if row.role == "branch":
                if not first_cell:
                    out.append('</tr><tr>')
                first_cell = False
                out.append(
                    f'<td colspan="2" style="color:#94a3b8;padding-right:10px;">'
                    f'{escape(row.label)}</td>'
                )
                continue
            first_cell = False
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
            block,
            constrained=constrained,
            header_override=header,
            mini=projection.mini,
            cursor_mode=projection.cursor_mode,
            x_mode=projection.x_mode,
            omit_visible_source_prefix=projection.omit_visible_source_prefix,
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
            if row.role == "branch" or (not row.value and row.label not in {_DOT_MARKER}):
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
    channel_list = tuple(channels)
    omit_prefix = cursor_result_source_count(channel_list) <= 1
    blocks = []
    for channel in channel_list:
        if x_mode == "custom":
            visible, tooltip = _custom_rows(channel, options, cursor_mode, mini)
        else:
            visible, tooltip = _time_rows(channel, options, cursor_mode, mini)
        if not visible:
            continue
        blocks.append(CursorDisplayBlock(
            identity=channel.identity,
            qualified_label=channel.qualified_label,
            channel_label=channel.channel_label,
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
        omit_visible_source_prefix=omit_prefix,
    )
    return CursorPresentation(
        blocks=projection.blocks,
        html=render_cursor_presentation(projection),
        tooltip=_tooltip(projection.blocks),
        layout_category=projection.layout_category,
        cursor_mode=projection.cursor_mode,
        x_mode=projection.x_mode,
        mini=projection.mini,
        omit_visible_source_prefix=omit_prefix,
    )


class CursorDisplayPopover(QFrame):
    """Six-option floating control anchored by :class:`TimeChartCard`."""

    options_changed = pyqtSignal(object)
    visibility_changed = pyqtSignal(object)

    _LABELS = (
        ("show_max_point", "显示最大值点"),
        ("show_min_point", "显示最小值点"),
        ("show_max_value", "显示最大值"),
        ("show_min_value", "显示最小值"),
        ("show_avg_value", "显示平均值"),
        ("show_delta_value", "显示差值"),
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

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(_POPOVER_BG)
            painter.setPen(QPen(_POPOVER_BORDER, 1.0))
            painter.drawRoundedRect(rect, _POPOVER_RADIUS, _POPOVER_RADIUS)
        finally:
            painter.end()

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
        self.resize(max(hint.width(), 252), hint.height())
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
    "visible_block_label",
]
