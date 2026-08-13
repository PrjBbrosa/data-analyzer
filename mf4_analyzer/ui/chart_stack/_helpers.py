"""Pixmap/HTML helpers, toolbar-icon helpers, and shared module-level constants."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QKeySequence, QPainter
from PyQt5.QtWidgets import QFrame, QToolButton

import qtawesome as qta

from .. import hints
from ..image_utils import pixmap_as_device_pixels

# ---------------------------------------------------------------------------
# Module-level constants (shared across sub-modules)
# ---------------------------------------------------------------------------

# Hi-DPI copy/save scale (spec §E). The TimeDomainCanvasPG caps the
# effective magnification internally (floor 1×, width ceiling 2560px) so
# both the toolbar 保存图片 and 复制为图片 paths request the same factor and
# export stays fast.
_HIDPI_EXPORT_SCALE = 2.0

# Icon colour tokens (match Precision Light palette)
_ICON_COLOR  = '#374151'
_ICON_ACTIVE = '#2563eb'
_TOOLBAR_COMPACT_WIDTH = 1500
_QT_WIDGETSIZE_MAX = 16777215
_STATS_STRIP_ENABLED = False

# MDI action-key → qtawesome icon name mapping
_MDI_NAV_ICONS = {
    'home':    'mdi.home',
    'back':    'mdi.arrow-left',
    'forward': 'mdi.arrow-right',
    'pan':     'mdi.cursor-move',
    'zoom':    'mdi.magnify-plus-outline',
    'save':    'mdi.content-save-outline',
}

# Chart nav shortcuts use Ctrl.
# The wheel modifiers (Ctrl+wheel / Shift+wheel) intentionally STAY Ctrl/Shift.
_NAV_SHORTCUTS = hints.NAV_SHORTCUTS

# Time-card segmented controls — Ctrl+digit shortcuts (left-hand reachable).
# Keys mirror the attribute names so the install helper can locate the button.
_TIME_CARD_SHORTCUTS = hints.TIME_CARD_SHORTCUTS

_MODE_TO_INDEX = {
    'time': 0,
    'fft': 1,
    'fft_time': 2,
    'frf': 3,
    'order': 4,
    # Index 5 hosts UltraViewPage so UltraViewSheet can return it on close.
    # Not a live workspace mode: ChartStack.set_mode rejects 'ultraview'.
    'ultraview': 5,
}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}

# Legacy module constant. The static "persistent" footer label was RETIRED:
# the base gestures are now the highest-weight anchors of the rotating pool
# (hints.rotation_hints), so the bottom bar no longer renders this string. Kept
# as a registry-derived compatibility value (hints.persistent_hints() still
# returns the two universal wheel strings). Rotating-row copy is selected at
# runtime by hints.rotation_hints(); the right slot by hints.discovery_hint().
_BOTTOM_HINT_PERSISTENT = "    ·    ".join(hints.persistent_hints())


# ---------------------------------------------------------------------------
# Pixmap helpers
# ---------------------------------------------------------------------------

def _pixmap_as_device_pixels(pixmap):
    if pixmap is None or pixmap.isNull():
        return pixmap
    normalized = pixmap_as_device_pixels(pixmap)
    return pixmap if normalized is None else normalized


def _grab_pixmap_hidpi(canvas, requested=_HIDPI_EXPORT_SCALE):
    """Grab a hi-DPI pixmap from ``canvas``.

    Preference order, each step guarded by ``isNull()``:
    1. ``grab_pixmap(scale=requested)`` — the pyqtgraph time canvas's
       capped hi-DPI render.
    2. ``grab_pixmap()`` — a ``grab_pixmap`` without the scale kwarg.
    3. ``canvas.grab()`` — every ``QWidget`` (matplotlib fft/order
       canvases lack ``grab_pixmap`` entirely; this preserves their
       pre-existing 1× copy behavior).
    Returns ``None`` only when no path yields a non-null pixmap.
    """
    grab_px = getattr(canvas, "grab_pixmap", None)
    if grab_px is not None:
        try:
            pix = grab_px(scale=requested)
        except TypeError:
            pix = grab_px()
        except Exception:
            pix = None
        if pix is not None and not pix.isNull():
            return _pixmap_as_device_pixels(pix)
    # Fallback for canvases without grab_pixmap (matplotlib) or a null
    # grab_pixmap result: plain QWidget grab.
    try:
        pix = canvas.grab()
        if pix is not None and not pix.isNull():
            return _pixmap_as_device_pixels(pix)
    except Exception:
        pass
    return None


def _format_mini_html(rows):
    """Mini dual-cursor: one row per channel — colored dot + name + △ only."""
    from html import escape
    parts = ['<table cellspacing="0" cellpadding="0" style="font-size:11px;">']
    for i, row in enumerate(rows):
        if len(row) >= 7:
            ch, _mn, _mx, _avg, delta, u, color = row[:7]
        else:
            ch, _mn, _mx, _avg, delta, u = row[:6]
            color = '#111827'
        if ']' in ch and ch.startswith('['):
            ch = ch.split(']', 1)[-1].strip()
        top_pad = '5px' if i > 0 else '0'
        mono = "font-family:'SF Mono',Menlo,Consolas,monospace;"
        parts.append(
            f'<tr><td style="padding-top:{top_pad};">'
            f'<span style="color:{color};">●</span></td>'
            f'<td style="padding-left:4px; color:{color}; font-weight:600; padding-top:{top_pad};">'
            f'{escape(ch)}</td>'
            f'<td style="padding-left:8px; color:{color}; {mono} padding-top:{top_pad};">'
            f'△&nbsp;{delta:.4g}{escape(u)}</td></tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Toolbar helpers
# ---------------------------------------------------------------------------

def _strip_subplots_action(toolbar):
    """Remove the matplotlib 'Configure subplots' button — tight_layout
    is the default in this app so the dialog is not useful."""
    for act in list(toolbar.actions()):
        name = (act.text() or '').lower()
        if 'subplots' in name or 'configure subplots' in name:
            toolbar.removeAction(act)
            return


def _find_action(toolbar, key_lower):
    """Match by act.data() first (i18n-stable), then by act.text()."""
    for act in toolbar.actions():
        if act.data() == key_lower or (act.text() or '').strip().lower() == key_lower:
            return act
    return None


def _apply_mdi_icons(toolbar, active_key=''):
    """Replace nav icons and flag the active button for QSS highlighting."""
    for act in toolbar.actions():
        key = act.data() if act.data() else (act.text() or '').strip().lower()
        icon_name = _MDI_NAV_ICONS.get(key)
        if icon_name is None:
            continue
        is_active = key == active_key
        color = _ICON_ACTIVE if is_active else _ICON_COLOR
        act.setIcon(qta.icon(icon_name, color=color))
        btn = toolbar.widgetForAction(act)
        if isinstance(btn, QToolButton):
            btn.setProperty("navActive", bool(is_active))
            btn.style().unpolish(btn)
            btn.style().polish(btn)


def _install_nav_shortcuts(card, toolbar):
    for key, shortcut in _NAV_SHORTCUTS.items():
        act = _find_action(toolbar, key)
        if act is None:
            continue
        shortcut = hints.shortcut_tooltip(key) or shortcut
        seq = QKeySequence(shortcut)
        act.setShortcut(seq)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        tip = act.toolTip() or act.text()
        native = seq.toString(QKeySequence.NativeText)
        if native and native not in tip:
            act.setToolTip(f"{tip} ({native})")
        act.triggered.connect(
            lambda _checked=False, c=card: c.mark_discovered("toolbar.shortcuts_exist")
        )
        card.addAction(act)


def _install_button_shortcut(card, button, label, shortcut, action_key=None):
    """Attach a card-wide QShortcut to a QPushButton and annotate its tooltip.

    Buttons created from QPushButton don't have a setShortcutContext like
    QAction; the QShortcut wired here fires when the focus is anywhere
    inside the card subtree (Qt.WidgetWithChildrenShortcut).
    """
    from PyQt5.QtWidgets import QShortcut

    shortcut = hints.shortcut_tooltip(action_key) or shortcut
    seq = QKeySequence(shortcut)
    sc = QShortcut(seq, card)
    sc.setContext(Qt.WidgetWithChildrenShortcut)
    sc.activated.connect(
        lambda c=card: c.mark_discovered("toolbar.shortcuts_exist")
    )
    sc.activated.connect(button.click)
    native = seq.toString(QKeySequence.NativeText)
    button.setToolTip(f"{label} ({native})" if native else label)
    return sc


def _vline():
    f = QFrame()
    f.setObjectName("chartToolbarSep")
    f.setFixedWidth(1)
    f.setFixedHeight(20)
    f.setContentsMargins(0, 0, 0, 0)
    return f
