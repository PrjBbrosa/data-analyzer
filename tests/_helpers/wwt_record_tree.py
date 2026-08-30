"""Query WinWert record-tree presentation by UserRole, never child index.

Suggested production roles (spec D6 / plan 3.1)::

    ("record_group", view_id, owner_fid)
    ("record_binding", view_id, binding_id, owner_fid, record_index)
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem

RECORD_GROUP = "record_group"
RECORD_BINDING = "record_binding"


def make_record_row(
    *,
    binding_id: str = "bind-1",
    owner_fid: str = "file-a",
    record_index: int = 5,
    name: str = "TolY",
    unit: str = "mm",
    color: str = "#ff0000",
    visible: bool = True,
) -> dict[str, object]:
    return {
        "binding_id": binding_id,
        "owner_fid": owner_fid,
        "record_index": record_index,
        "name": name,
        "unit": unit,
        "color": color,
        "visible": visible,
    }


def tree_of(widget) -> QTreeWidget:
    if isinstance(widget, QTreeWidget):
        return widget
    channel_list = getattr(widget, "channel_list", None)
    if channel_list is not None and hasattr(channel_list, "tree"):
        return channel_list.tree
    tree = getattr(widget, "tree", None)
    if tree is None:
        raise AssertionError("widget has no QTreeWidget to walk")
    return tree


def iter_record_tree_items(widget):
    """Yield ``(item, role_tuple)`` for record_group / record_binding rows."""
    tree = tree_of(widget)
    stack: list[QTreeWidgetItem] = [
        tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
    ]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple) and data and data[0] in (RECORD_GROUP, RECORD_BINDING):
            yield item, data
        for index in range(item.childCount() - 1, -1, -1):
            stack.append(item.child(index))


def record_binding_roles(widget) -> list[tuple]:
    return [data for _item, data in iter_record_tree_items(widget) if data[0] == RECORD_BINDING]


def record_group_roles(widget) -> list[tuple]:
    return [data for _item, data in iter_record_tree_items(widget) if data[0] == RECORD_GROUP]


def record_binding_count(widget) -> int:
    return len(record_binding_roles(widget))


def item_holds_ndarray(item: QTreeWidgetItem) -> bool:
    import numpy as np

    for column in range(item.columnCount()):
        value = item.data(column, Qt.UserRole)
        if isinstance(value, np.ndarray):
            return True
        if isinstance(value, (tuple, list)):
            if any(isinstance(part, np.ndarray) for part in value):
                return True
        if isinstance(value, dict) and any(
            isinstance(part, np.ndarray) for part in value.values()
        ):
            return True
    return False
