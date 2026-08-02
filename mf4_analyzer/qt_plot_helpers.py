"""Small Qt/pyqtgraph plot helpers with no Analyzer UI dependency."""
from __future__ import annotations


def hide_native_auto_button(plot) -> None:
    """Hide pyqtgraph's built-in lower-left auto-range button."""
    hide = getattr(plot, "hideButtons", None)
    if callable(hide):
        hide()


def show_major_grid_left_bottom_only(plot, *, x=True, y=True, alpha=0.25):
    """Enable major grid on left+bottom and force top/right off."""
    plot.showGrid(x=bool(x), y=bool(y), alpha=alpha)
    for name in ("top", "right"):
        try:
            plot.getAxis(name).setGrid(False)
        except Exception:
            pass


__all__ = ["hide_native_auto_button", "show_major_grid_left_bottom_only"]
