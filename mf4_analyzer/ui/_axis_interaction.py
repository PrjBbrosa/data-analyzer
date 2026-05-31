"""Pure axis-hit detection + side-effecting axis-edit helper.

Extracted so all 4 canvases (TimeDomain, Plot, Spectrogram, Order) share
the same hover/dblclick affordance without duplicating PlotCanvas-specific
state references.

The hit-test helper is intentionally stateless: it depends only on its
arguments and the live Figure layout. Callers may rebuild figures freely
(e.g. ``fig.clear()`` followed by ``add_subplot``) without invalidating
this helper -- there is nothing to disconnect or re-wire here. See
``docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md``
for the matching guidance on Axes.callbacks (which IS stateful and must
be managed at the canvas level).

After Task 3 of the pyqtgraph TimeDomain migration, the construction
site for ``AxisHandle`` lives in ``_make_handle`` below. Today it is a
thin wrapper around :func:`mf4_analyzer.ui._axis_handle.make_handle`;
when Task 5 lands ``TimeDomainCanvasPG``, this is the single seam that
picks ``PgAxisHandle`` for a pyqtgraph ``ViewBox`` and ``MplAxisHandle``
for a matplotlib ``Axes``. No call-site outside this module needs to
care which path runs.
"""
from PyQt5.QtWidgets import QDialog

from ._axis_handle import make_handle as _mpl_make_handle


def find_axis_for_dblclick(fig, x_px, y_px, margin):
    """Return ``(Axes, 'x' | 'y')`` or ``(None, None)``.

    Pixel-based hit test that includes the tick-label gutter region
    (``margin`` px outside the axes bbox) so clicking on tick numbers also
    targets the axis. Pure: depends only on inputs.

    Parameters
    ----------
    fig
        A matplotlib ``Figure`` whose ``axes`` are scanned.
    x_px, y_px
        Click coordinates in display (pixel) space.
    margin
        Gutter size in pixels outside each axes bbox that still counts as
        a hit on that side.
    """
    best = (None, None)
    best_dist = float('inf')
    for ax in fig.axes:
        bbox = ax.get_window_extent()
        # X axis: below bottom within `margin` px, x within bounds
        if bbox.x0 - 10 <= x_px <= bbox.x1 + 10:
            if bbox.y0 - margin <= y_px <= bbox.y0 + 20:
                dist = abs(y_px - bbox.y0)
                if dist < best_dist:
                    best = (ax, 'x')
                    best_dist = dist
        # Y axis: left side within `margin` px, y within bounds
        if bbox.y0 - 10 <= y_px <= bbox.y1 + 10:
            if bbox.x0 - margin <= x_px <= bbox.x0 + 20:
                dist = abs(x_px - bbox.x0)
                if dist < best_dist:
                    best = (ax, 'y')
                    best_dist = dist
            # Right Y axis (e.g. colorbar)
            if bbox.x1 - 20 <= x_px <= bbox.x1 + margin:
                dist = abs(x_px - bbox.x1)
                if dist < best_dist:
                    best = (ax, 'y')
                    best_dist = dist
    return best


def target_axes_for_event(fig, event, margin):
    """Return the axes targeted by a chart-options double-click event."""
    event_ax = getattr(event, 'inaxes', None)
    if event_ax is not None and event_ax in fig.axes:
        return event_ax
    ax, _axis = find_axis_for_dblclick(fig, event.x, event.y, margin)
    return ax


def edit_axis_dialog(parent_widget, ax, axis):
    """Side-effecting: open ``AxisEditDialog`` modal, apply user's choice
    to ``ax``, return ``True`` iff the dialog was accepted.

    Caller is responsible for calling ``canvas.draw_idle()`` when this
    returns ``True``.
    """
    from .dialogs import AxisEditDialog

    dlg = AxisEditDialog(parent_widget, ax, axis)
    if dlg.exec_() != QDialog.Accepted:
        return False
    vmin, vmax, label, auto = dlg.get_values()
    if axis == 'x':
        if auto:
            ax.autoscale(axis='x')
        else:
            ax.set_xlim(vmin, vmax)
        if label:
            ax.set_xlabel(label)
    else:
        if auto:
            ax.autoscale(axis='y')
        else:
            ax.set_ylim(vmin, vmax)
        if label:
            ax.set_ylabel(label)
    return True


def _make_handle(ax_or_view):
    """Single dispatch point that lifts a raw axis/view into an
    ``AxisHandle`` (design §5.3).

    Today only the matplotlib branch is live: ``make_handle`` from
    ``_axis_handle`` either returns the input unchanged (already a
    handle) or wraps a matplotlib ``Axes`` with ``MplAxisHandle``. T5
    will extend this to recognize a pyqtgraph ``ViewBox`` / ``PlotItem``
    pair and produce a ``PgAxisHandle``. Keeping the dispatch in ONE
    function lets the rest of ``_axis_interaction`` stay branch-free
    when pyqtgraph lands.
    """
    # ``PgAxisHandle`` will be added here when Task 5 lands. Until then
    # the matplotlib path is the only live branch; the discrimination
    # rule (handle vs. raw Axes) lives inside ``make_handle``.
    return _mpl_make_handle(ax_or_view)


def edit_chart_options_dialog(parent_widget, ax):
    """Open the lightweight chart options dialog for ``ax``.

    Returns True when the dialog accepted or when the user clicked Apply before
    closing it, so callers can redraw for both paths.

    The axis can be either a raw matplotlib ``Axes`` (current
    behaviour) or an already-wrapped ``AxisHandle`` (forward path).
    ``_make_handle`` normalises both and ``ChartOptionsDialog`` accepts
    either form transparently — no caller change required.
    """
    from .dialogs import ChartOptionsDialog

    handle = _make_handle(ax)
    dlg = ChartOptionsDialog(parent_widget, handle)
    accepted = dlg.exec_() == QDialog.Accepted
    return accepted or dlg.was_applied()
