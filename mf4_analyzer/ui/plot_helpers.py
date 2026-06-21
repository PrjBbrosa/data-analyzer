"""Pure UI formatting helpers for pyqtgraph canvas label/cursor rendering.

Extracted from ``mf4_analyzer.ui.canvases`` (Phase D, 2026-06-18) so
pyqtgraph sub-modules do not need to import the now-retired canvas layer
to get these pure formatting functions.

``mf4_analyzer.ui.canvases`` re-exports all public symbols defined here
so existing ``from mf4_analyzer.ui.canvases import _format_dual_html``
calls continue to work without change.
"""

import numpy as np


def _split_prefixed_label(text):
    """Return (prefix, rest) for labels shaped like '[filename] channel'.
    Returns (None, text) when the pattern doesn't match."""
    if text.startswith('[') and ']' in text:
        i = text.index(']')
        rest = text[i + 1:].lstrip()
        if rest:
            return text[:i + 1], rest
    return None, text


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


def _format_dual_html(rows):
    """rows: list of (channel_name, mn, mx, avg, delta, unit_suffix, color).
    Channel name is rendered on its own line (file prefix + name split when
    the source matches '[file] channel'); stats follow as a 4-column row.
    Channel name and numeric cells are tinted with the channel's plot color."""
    from html import escape
    parts = ['<table cellspacing="0" cellpadding="0" '
             'style="font-size:11px; color:#111827;">']
    for i, row in enumerate(rows):
        if len(row) >= 7:
            ch, mn, mx, avg, delta, u, color = row[:7]
        else:
            ch, mn, mx, avg, delta, u = row[:6]
            color = '#111827'
        prefix, rest = _split_prefixed_label(ch)
        if prefix is not None:
            name_html = (f'<span style="color:#64748b;">{escape(prefix)}</span>'
                         f'<br/><b style="color:{color};">{escape(rest)}</b>')
        else:
            name_html = f'<b style="color:{color};">{escape(ch)}</b>'
        top_pad = '8px' if i > 0 else '0'
        parts.append(
            f'<tr><td colspan="4" style="padding-top:{top_pad}; padding-bottom:2px;">'
            f'{name_html}</td></tr>'
        )
        cell = (f'padding:1px 8px 1px 0; color:{color}; font-family:'
                '\'SF Mono\',Menlo,Consolas,monospace;')
        lab = 'padding:1px 4px 1px 0; color:#94a3b8;'
        parts.append(
            f'<tr>'
            f'<td style="{lab}">Min</td>'
            f'<td style="{cell}" align="right">{mn:.4g}{escape(u)}</td>'
            f'<td style="{lab}; padding-left:8px;">Max</td>'
            f'<td style="{cell}" align="right">{mx:.4g}{escape(u)}</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="{lab}">Avg</td>'
            f'<td style="{cell}" align="right">{avg:.4g}{escape(u)}</td>'
            f'<td style="{lab}; padding-left:8px;">△</td>'
            f'<td style="{cell}" align="right">{delta:.4g}{escape(u)}</td>'
            f'</tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


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
