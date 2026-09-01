"""Neutral axis-group tagging shared by TimeDomain render paths."""
from __future__ import annotations


def tag_axis_group(handle, axis_id) -> None:
    """Stamp a shared-axis identity on a handle and its Y ``AxisItem``."""
    handle.axis_group = axis_id
    getter = getattr(handle, "y_axis_item", None)
    axis = getter() if callable(getter) else None
    if axis is not None:
        axis.axis_group = axis_id
