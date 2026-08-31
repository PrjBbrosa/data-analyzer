"""Pure UI formatting helpers for pyqtgraph canvas label/cursor rendering.

Extracted from ``mf4_analyzer.ui.canvases`` (Phase D, 2026-06-18) so
pyqtgraph sub-modules do not need to import the now-retired canvas layer
to get these pure formatting functions.

``mf4_analyzer.ui.canvases`` re-exports all public symbols defined here
so existing ``from mf4_analyzer.ui.canvases import _format_dual_html``
calls continue to work without change.
"""

from dataclasses import dataclass, field
import json
import re

import numpy as np

from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE, TIME_MODE

_DUAL_TABLE_OPEN = (
    '<table cellspacing="0" cellpadding="0" '
    'style="font-size:11px; color:#111827;">'
)
_DUAL_MINI_TABLE_OPEN = (
    '<table cellspacing="0" cellpadding="0" style="font-size:11px;">'
)
_MINI_VALUE_FONT = "font-family:'SF Mono',Menlo,Consolas,monospace;"


@dataclass(frozen=True)
class DualCursorBranch:
    """One Custom-X path contribution shown as a compact subrow."""

    direction: int
    min_value: float
    max_value: float
    avg: float
    delta: float | None = None

    @property
    def branch_label(self) -> str:
        if self.direction > 0:
            return "X↑"
        if self.direction < 0:
            return "X↓"
        return "全程"

    @property
    def tooltip_role(self) -> str:
        if self.direction > 0:
            return "升程"
        if self.direction < 0:
            return "回程"
        return ""


@dataclass
class DualCursorRow:
    """Structured dual-cursor row. Time mode keeps the 7-field visual contract.

    Custom-X rows carry ``mode='channel'`` plus optional ``branches`` / ``status``.
    Sequence access ``row[0]..row[6]`` remains the historical 7-tuple so hidden-
    curve and pill tests that index a time row keep working.
    """

    channel_name: str
    min_value: float | None
    max_value: float | None
    avg: float | None
    delta: float | None
    unit_suffix: str
    color: str
    identity: object = None
    label: str = ""
    mode: str = TIME_MODE
    branch: str = ""
    status: str = ""
    x_unit: str = ""
    branches: tuple[DualCursorBranch, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.channel_name

    def __len__(self) -> int:
        return 7

    def __getitem__(self, index):
        seq = (
            self.channel_name,
            _numeric_or_nan(self.min_value),
            _numeric_or_nan(self.max_value),
            _numeric_or_nan(self.avg),
            _numeric_or_nan(self.delta),
            self.unit_suffix,
            self.color,
        )
        return seq[index]


def _numeric_or_nan(value):
    if value is None:
        return float("nan")
    return value


def dual_row_is_custom_x(row) -> bool:
    mode = getattr(row, "mode", None)
    return mode in (CHANNEL_MODE, "channel")


def _split_prefixed_label(text):
    """Return (prefix, rest) for labels shaped like '[filename] channel'.
    Returns (None, text) when the pattern doesn't match."""
    if text.startswith('[') and ']' in text:
        i = text.index(']')
        rest = text[i + 1:].lstrip()
        if rest:
            return text[:i + 1], rest
    return None, text


_FID_LABEL_RE = re.compile(r"^f\d+$")


def _is_internal_fid(text):
    return bool(_FID_LABEL_RE.fullmatch(str(text or "").strip()))


def _cursor_identity_parts(identity):
    """Return ``(source_id, channel)`` from a composite identity, else ``(None, None)``."""
    parsed = identity
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None, None
    if isinstance(parsed, (tuple, list)) and len(parsed) == 2:
        source_id, channel = parsed[0], parsed[1]
        source_s = "" if source_id is None else str(source_id)
        channel_s = "" if channel is None else str(channel)
        return source_s, channel_s
    return None, None


def _reject_fid_label(text):
    value = str(text or "").strip()
    if not value or _is_internal_fid(value):
        return ""
    return value


def resolve_cursor_source_label(display_name, identity, fid_resolver=None):
    """Return ``(source_label, channel_label)``. ``source_label`` is never an internal fid.

    1. If ``display_name`` has a ``[short_name]`` prefix via ``_split_prefixed_label``,
       use that prefix content (unless it is itself an internal fid).
    2. Else if identity is ``(fid, ch)`` or a JSON list of that shape, call
       ``fid_resolver(fid)`` when provided.
    3. Else empty ``source_label``.

    Channel label: prefixed rest, else identity[1], else ``display_name``.
    Strings matching ``^f\\d+$`` are treated as fids, never as display labels.
    """
    display = "" if display_name is None else str(display_name)
    prefix, rest = _split_prefixed_label(display)
    source_label = _reject_fid_label(prefix[1:-1] if prefix else "")
    source_id, ident_channel = _cursor_identity_parts(identity)
    if not source_label and source_id is not None and callable(fid_resolver):
        source_label = _reject_fid_label(fid_resolver(source_id))

    if prefix is not None:
        channel_label = rest
    elif ident_channel:
        channel_label = ident_channel
    else:
        channel_label = display
    channel_label = str(channel_label or "")
    if _is_internal_fid(channel_label):
        if ident_channel and not _is_internal_fid(ident_channel):
            channel_label = ident_channel
        elif rest and not _is_internal_fid(rest) and rest != display:
            channel_label = rest
        elif display and not _is_internal_fid(display):
            channel_label = display
        else:
            channel_label = ""
    return source_label, channel_label


def cursor_result_source_count(channels):
    """Count distinct sources in a cursor-result batch (identity fid, else label)."""
    unique = set()
    for channel in channels:
        source_id, _ = _cursor_identity_parts(getattr(channel, "identity", None))
        source_label = str(getattr(channel, "source_label", "") or "").strip()
        if source_id:
            unique.add(("id", source_id))
        elif source_label:
            unique.add(("label", source_label))
    return len(unique)


def apply_cursor_source_prefix_policy(channels):
    """Identity passthrough: D1 omit is a visible-face decision in presentation.

    ``source_label`` stays resolved (never fid) so tooltips keep the qualified
    name. Visible HTML omits the prefix when :func:`cursor_result_source_count`
    is ≤ 1.
    """
    return list(channels)


def _compact_axis_label(name, unit='', max_chars=22):
    """Channel-name only -- units are now drawn separately above the axis."""
    text = str(name)
    if len(text) <= max_chars:
        return text
    prefix, rest = _split_prefixed_label(text)
    if prefix is not None:
        return f"{prefix}\n{rest}"
    return text[:max_chars - 3] + '...'


def _middle_ellipsis(text, max_chars=56):
    text = str(text)
    if len(text) <= max_chars:
        return text
    if max_chars <= 8:
        return text[:max(1, max_chars - 3)] + '...'
    keep = max_chars - 3
    left = max(1, keep // 2)
    right = max(1, keep - left)
    return f"{text[:left]}...{text[-right:]}"


def _set_series_ylabel(ax, label, color, labelpad=10, unit='', side='left'):
    ax.set_ylabel(label, fontsize=8, color=color, labelpad=labelpad)
    ax.yaxis.label.set_clip_on(False)
    if unit:
        # Horizontal unit chip at the very top of the spine (above tick labels).
        x_anchor = 0.0 if side == 'left' else 1.0
        ha = 'left' if side == 'left' else 'right'
        ax.text(
            x_anchor, 1.012, unit,
            transform=ax.transAxes,
            ha=ha, va='bottom',
            fontsize=8, color=color, fontweight='600',
            clip_on=False,
        )


def _format_single_cursor_channel_html(channel_name, value, unit_suffix, color):
    """Render one single-cursor channel row without truncating the name.

    Mirrors the dual-cursor name treatment: a source prefix such as
    ``[file]`` is shown separately, while the actual signal name keeps the
    channel color and stays complete.
    """
    from html import escape

    prefix, rest = _split_prefixed_label(channel_name)
    if prefix is not None:
        return (
            f'<span style="color:#64748b;">{escape(prefix)}</span> '
            f'<span style="color:{color};">'
            f'{escape(rest)}=<b>{value:.4g}{escape(unit_suffix)}</b>'
            f'</span>'
        )
    return (
        f'<span style="color:{color};">'
        f'{escape(channel_name)}=<b>{value:.4g}{escape(unit_suffix)}</b>'
        f'</span>'
    )


def _channel_name_html(channel_name, color):
    from html import escape

    prefix, rest = _split_prefixed_label(channel_name)
    if prefix is not None:
        return (
            f'<span style="color:#64748b;">{escape(prefix)}</span>'
            f'<br/><b style="color:{color};">{escape(rest)}</b>'
        )
    return f'<b style="color:{color};">{escape(channel_name)}</b>'


def _unpack_time_dual_row(row):
    if len(row) >= 7:
        ch, mn, mx, avg, delta, u, color = row[:7]
    else:
        ch, mn, mx, avg, delta, u = row[:6]
        color = '#111827'
    return ch, mn, mx, avg, delta, u, color


def _enabled_cursor_value_fields(options):
    if options is None:
        return (("Min", "min_value"), ("Max", "max_value"), ("Avg", "avg"))
    return tuple(
        item for item, enabled in (
            (("Min", "min_value"), getattr(options, "show_min_value", True)),
            (("Max", "max_value"), getattr(options, "show_max_value", True)),
            (("Avg", "avg"), getattr(options, "show_avg_value", True)),
            (("Δ", "delta"), getattr(options, "show_delta_value", True)),
        )
        if enabled
    )


def _format_dual_stat_text(value, unit):
    from html import escape

    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(number):
        return "—"
    return f"{number:.4g}{escape(unit)}"


def _format_time_dual_block(
    parts, *, index, channel_name, mn, mx, avg, delta, unit_suffix, color,
    options=None,
):
    from html import escape

    top_pad = '8px' if index > 0 else '0'
    parts.append(
        f'<tr><td colspan="4" style="padding-top:{top_pad}; padding-bottom:2px;">'
        f'{_channel_name_html(channel_name, color)}</td></tr>'
    )
    cell = (f'padding:1px 8px 1px 0; color:{color}; font-family:'
            '\'SF Mono\',Menlo,Consolas,monospace;')
    lab = 'padding:1px 4px 1px 0; color:#94a3b8;'
    if options is None:
        parts.append(
            f'<tr>'
            f'<td style="{lab}">Min</td>'
            f'<td style="{cell}" align="right">{mn:.4g}{escape(unit_suffix)}</td>'
            f'<td style="{lab}; padding-left:8px;">Max</td>'
            f'<td style="{cell}" align="right">{mx:.4g}{escape(unit_suffix)}</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="{lab}">Avg</td>'
            f'<td style="{cell}" align="right">{avg:.4g}{escape(unit_suffix)}</td>'
            f'<td style="{lab}; padding-left:8px;">△</td>'
            f'<td style="{cell}" align="right">{delta:.4g}{escape(unit_suffix)}</td>'
            f'</tr>'
        )
        return
    values = {"min_value": mn, "max_value": mx, "avg": avg, "delta": delta}
    for label, attr in _enabled_cursor_value_fields(options):
        display = "△" if label == "Δ" else label
        parts.append(
            f'<tr><td style="{lab}">{display}</td>'
            f'<td style="{cell}" align="right">'
            f'{_format_dual_stat_text(values[attr], unit_suffix)}</td></tr>'
        )


def _format_custom_x_dual_block(parts, *, index, row, options=None):
    from html import escape

    color = row.color or '#111827'
    unit = row.unit_suffix or ''
    top_pad = '8px' if index > 0 else '0'
    parts.append(
        f'<tr><td colspan="4" style="padding-top:{top_pad}; padding-bottom:2px;">'
        f'{_channel_name_html(row.channel_name, color)}</td></tr>'
    )
    cell = (f'padding:1px 8px 1px 0; color:{color}; font-family:'
            '\'SF Mono\',Menlo,Consolas,monospace;')
    lab = 'padding:1px 4px 1px 0; color:#94a3b8;'
    if row.status and not row.branches:
        parts.append(
            f'<tr><td colspan="4" style="{lab}">{escape(row.status)}</td></tr>'
        )
        return
    enabled = _enabled_cursor_value_fields(options)
    for branch in row.branches:
        label = branch.branch_label
        if options is None:
            parts.append(
                f'<tr>'
                f'<td style="{lab}">{escape(label)}</td>'
                f'<td style="{cell}" align="right">Min {branch.min_value:.4g}{escape(unit)}</td>'
                f'<td style="{lab}; padding-left:8px;">Max</td>'
                f'<td style="{cell}" align="right">{branch.max_value:.4g}{escape(unit)}</td>'
                f'</tr>'
                f'<tr>'
                f'<td style="{lab}"></td>'
                f'<td style="{cell}" align="right">Avg {branch.avg:.4g}{escape(unit)}</td>'
                f'<td colspan="2"></td>'
                f'</tr>'
            )
            continue
        parts.append(
            f'<tr><td colspan="4" style="{lab}">{escape(label)}</td></tr>'
        )
        for value_label, attr in enabled:
            parts.append(
                f'<tr><td style="{lab}">{escape(label)} {escape(value_label)}</td>'
                f'<td style="{cell}" align="right">'
                f'{_format_dual_stat_text(getattr(branch, attr, None), unit)}</td></tr>'
            )
    if row.status and row.branches:
        parts.append(
            f'<tr><td colspan="4" style="{lab}">{escape(row.status)}</td></tr>'
        )


def _format_dual_html(rows, options=None):
    """Format dual-cursor rows.

    Time rows keep the historical 4-cell Min/Max/Avg/△ table. Custom-X rows
    show a channel title plus ``X↑`` / ``X↓`` / ``全程`` subrows and never a
    single-value △ column.
    """
    parts = [_DUAL_TABLE_OPEN]
    for i, row in enumerate(rows):
        if dual_row_is_custom_x(row):
            _format_custom_x_dual_block(parts, index=i, row=row, options=options)
            continue
        ch, mn, mx, avg, delta, u, color = _unpack_time_dual_row(row)
        _format_time_dual_block(
            parts,
            index=i,
            channel_name=ch,
            mn=mn,
            mx=mx,
            avg=avg,
            delta=delta,
            unit_suffix=u,
            color=color,
            options=options,
        )
    parts.append('</table>')
    return ''.join(parts)


def _format_dual_mini_html(rows, options=None):
    """Mini dual-cursor table.

    Time rows keep coloured-dot + name + △. Custom-X rows keep direction + Avg
    so four files × two branches stay readable.
    """
    from html import escape

    if any(dual_row_is_custom_x(row) for row in rows or ()):
        parts = [_DUAL_MINI_TABLE_OPEN]
        for i, row in enumerate(rows):
            color = getattr(row, "color", "#111827") or '#111827'
            top_pad = '5px' if i > 0 else '0'
            name = str(getattr(row, "channel_name", "") or "")
            if ']' in name and name.startswith('['):
                name = name.split(']', 1)[-1].strip()
            if options is None:
                parts.append(
                    f'<tr><td style="padding-top:{top_pad};">'
                    f'<span style="color:{color};">●</span></td>'
                    f'<td style="padding-left:4px; color:{color}; font-weight:600; '
                    f'padding-top:{top_pad};">{escape(name)}</td>'
                    f'<td></td></tr>'
                )
            else:
                parts.append(
                    f'<tr><td colspan="3" style="color:{color}; font-weight:600; '
                    f'padding-top:{top_pad};"><span style="color:{color};">●</span> '
                    f'{escape(name)}</td></tr>'
                )
            if row.status and not getattr(row, "branches", ()):
                if options is None:
                    parts.append(
                        f'<tr><td></td><td colspan="2" style="padding-left:4px; '
                        f'color:#94a3b8;">{escape(row.status)}</td></tr>'
                    )
                else:
                    parts.append(
                        f'<tr><td colspan="3" style="padding-left:4px; '
                        f'color:#94a3b8;">{escape(row.status)}</td></tr>'
                    )
                continue
            unit = getattr(row, "unit_suffix", "") or ""
            enabled = _enabled_cursor_value_fields(options)
            priority = next(
                (item for wanted in ("Δ", "Avg", "Max", "Min")
                 for item in enabled if item[0] == wanted),
                None,
            )
            for branch in getattr(row, "branches", ()) or ():
                value_html = ""
                if priority is not None:
                    value_label, attr = priority
                    value_html = (
                        f'{escape(value_label)}&nbsp;'
                        f'{_format_dual_stat_text(getattr(branch, attr, None), unit)}'
                    )
                if options is None:
                    parts.append(
                        f'<tr><td></td>'
                        f'<td style="padding-left:4px; color:{color};">{escape(branch.branch_label)}</td>'
                        f'<td style="padding-left:8px; color:{color}; {_MINI_VALUE_FONT}">'
                        f'{value_html}</td></tr>'
                    )
                elif value_html:
                    parts.append(
                        f'<tr><td colspan="3" style="padding-left:4px; color:{color}; '
                        f'{_MINI_VALUE_FONT}">{escape(branch.branch_label)} '
                        f'{value_html}</td></tr>'
                    )
                else:
                    parts.append(
                        f'<tr><td colspan="3" style="padding-left:4px; color:{color};">'
                        f'{escape(branch.branch_label)}</td></tr>'
                    )
            if row.status and getattr(row, "branches", ()):
                if options is None:
                    parts.append(
                        f'<tr><td></td><td colspan="2" style="padding-left:4px; '
                        f'color:#94a3b8;">{escape(row.status)}</td></tr>'
                    )
                else:
                    parts.append(
                        f'<tr><td colspan="3" style="padding-left:4px; '
                        f'color:#94a3b8;">{escape(row.status)}</td></tr>'
                    )
        parts.append('</table>')
        return ''.join(parts)

    parts = [_DUAL_MINI_TABLE_OPEN]
    for i, row in enumerate(rows):
        ch, mn, mx, avg, delta, u, color = _unpack_time_dual_row(row)
        if ']' in ch and ch.startswith('['):
            ch = ch.split(']', 1)[-1].strip()
        top_pad = '5px' if i > 0 else '0'
        values = {"min_value": mn, "max_value": mx, "avg": avg, "delta": delta}
        if options is None:
            metric_html = f'△&nbsp;{_format_dual_stat_text(delta, u)}'
        else:
            enabled = _enabled_cursor_value_fields(options)
            priority = next(
                (item for wanted in ("Δ", "Avg", "Max", "Min")
                 for item in enabled if item[0] == wanted),
                None,
            )
            if priority is None:
                metric_html = ""
            else:
                label, attr = priority
                display = "△" if label == "Δ" else label
                metric_html = (
                    f'{display}&nbsp;{_format_dual_stat_text(values[attr], u)}'
                )
        metric_td = ""
        if metric_html:
            metric_td = (
                f'<td style="padding-left:8px; color:{color}; {_MINI_VALUE_FONT} '
                f'padding-top:{top_pad};">{metric_html}</td>'
            )
        parts.append(
            f'<tr><td style="padding-top:{top_pad};">'
            f'<span style="color:{color};">●</span></td>'
            f'<td style="padding-left:4px; color:{color}; font-weight:600; padding-top:{top_pad};">'
            f'{escape(ch)}</td>'
            f'{metric_td}</tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


def format_dual_rows_tooltip(rows, options=None) -> str:
    """Plain-text tooltip for mini Custom-X rows (Min/Max + 升程/回程)."""
    lines = []
    for row in rows or ():
        if not dual_row_is_custom_x(row):
            continue
        name = str(row.channel_name or row.label or "")
        if row.status and not row.branches:
            lines.append(f"{name}: {row.status}" if name else row.status)
            continue
        if name:
            lines.append(name)
        unit = row.unit_suffix or ""
        enabled = _enabled_cursor_value_fields(options)
        for branch in row.branches:
            role = branch.tooltip_role
            role_bit = f" {role}" if role else ""
            values = "  ".join(
                f"{label}={_format_dual_stat_text(getattr(branch, attr, None), unit)}"
                for label, attr in enabled
            )
            lines.append(f"{branch.branch_label}{role_bit}  {values}".rstrip())
        if row.status:
            lines.append(row.status)
    return "\n".join(lines)


def _interp_cursor_value(t, sig, x):
    """Value of ``sig`` at cursor time ``x`` using linear interpolation."""
    t = np.asarray(t, dtype=float)
    sig = np.asarray(sig, dtype=float)
    if t.size == 0 or sig.size == 0:
        return np.nan
    valid = np.isfinite(t) & np.isfinite(sig)
    if not np.any(valid):
        return np.nan
    t = t[valid]
    sig = sig[valid]
    if t.size > 1 and np.any(np.diff(t) < 0):
        order = np.argsort(t)
        t = t[order]
        sig = sig[order]
    return float(np.interp(float(x), t, sig))
