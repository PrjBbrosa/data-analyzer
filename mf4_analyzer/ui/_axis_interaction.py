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
"""
from PyQt5.QtWidgets import QDialog


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
