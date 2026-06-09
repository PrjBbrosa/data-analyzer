"""Shared canvas back-reference for pyqtgraph canvas collaborators."""

from __future__ import annotations


_MISSING = object()


class _CanvasBackref:
    _delegate_names = frozenset()
    _owned_names = frozenset()

    def __init__(self, canvas):
        object.__setattr__(self, "_c", canvas)

    def __getattribute__(self, name):
        if name not in {
            "_c",
            "_delegate_names",
            "_owned_names",
            "__dict__",
            "__class__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
        }:
            delegate_names = object.__getattribute__(self, "_delegate_names")
            if name in delegate_names:
                canvas = object.__getattribute__(self, "_c")
                value = getattr(canvas, "__dict__", {}).get(name, _MISSING)
                if value is not _MISSING:
                    return value
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
            return
        owned_names = object.__getattribute__(self, "_owned_names")
        delegate_names = object.__getattribute__(self, "_delegate_names")
        if name in owned_names or name in delegate_names:
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)
