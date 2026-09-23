"""Small AppKit backdrop adapter for the two Qt panels (Cocoa only).

No PyObjC dependency, desktop capture, private blur API, or background polling.
The effect is a sibling below Qt's content view, so text/input stays with Qt.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import weakref


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Size)]


@lru_cache(maxsize=1)
def _runtime():
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    return objc


@lru_cache(maxsize=32)
def _sender(result_type, argument_types):
    # Separate function pointer per ABI signature; never mutate objc_msgSend's
    # argtypes between calls. These structs keep one class identity on Intel/ARM.
    return ctypes.CFUNCTYPE(
        result_type, ctypes.c_void_p, ctypes.c_void_p, *argument_types
    )(("objc_msgSend", _runtime()))


def _send(receiver, selector, result=ctypes.c_void_p, types=(), values=()):
    return _sender(result, types)(
        receiver, _runtime().sel_registerName(selector.encode("ascii")), *values
    )


class CocoaBackdrop:
    """Own one retained NSVisualEffectView; release on hide or Qt destruction."""

    def __init__(self, widget):
        from PyQt5.QtCore import QThread
        from PyQt5.QtWidgets import QApplication

        if QThread.currentThread() != QApplication.instance().thread():
            raise RuntimeError("Cocoa backdrop must be created on the GUI thread")
        self.applied = False
        self.reason = "native_view_unavailable"
        self._view = None
        self._widget_ref = weakref.ref(widget)
        self._connected = False
        objc = _runtime()
        workspace = _send(objc.objc_getClass(b"NSWorkspace"), "sharedWorkspace")
        if _send(workspace, "accessibilityDisplayShouldReduceTransparency", ctypes.c_bool):
            self.reason = "transparency_disabled"
            return
        qt_view = int(widget.winId())
        parent = _send(qt_view, "superview")
        if not parent:
            return
        view = _send(objc.objc_getClass(b"NSVisualEffectView"), "alloc")
        view = _send(
            view, "initWithFrame:", types=(_Rect,),
            values=(_Rect(_Point(0, 0), _Size(widget.width(), widget.height())),),
        )
        if not view:
            return
        self._view = view
        integer = (ctypes.c_long,)
        _send(view, "setBlendingMode:", None, integer, (0,))  # behindWindow
        _send(view, "setMaterial:", None, integer, (21,))  # underWindowBackground
        _send(view, "setState:", None, integer, (1,))  # active, including no-focus splash
        _send(view, "setAutoresizingMask:", None, (ctypes.c_ulong,), (18,))
        name = _send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:",
                     types=(ctypes.c_char_p,), values=(b"NSAppearanceNameAqua",))
        appearance = _send(objc.objc_getClass(b"NSAppearance"), "appearanceNamed:",
                           types=(ctypes.c_void_p,), values=(name,))
        _send(view, "setAppearance:", None, (ctypes.c_void_p,), (appearance,))
        _send(view, "setWantsLayer:", None, (ctypes.c_bool,), (True,))
        layer = _send(view, "layer")
        radius = float(widget.property("panelCornerRadius") or 14.)
        _send(layer, "setCornerRadius:", None, (ctypes.c_double,), (radius,))
        _send(layer, "setMasksToBounds:", None, (ctypes.c_bool,), (True,))
        _send(parent, "addSubview:positioned:relativeTo:", None,
              (ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p), (view, -1, qt_view))
        # Qt's content view keeps all interaction; the native sibling only paints.
        widget.destroyed.connect(self.release)
        self._connected = True
        self.applied = True
        self.reason = ""

    def release(self, *_args):
        if self._connected:
            self._connected = False
            widget = self._widget_ref()
            if widget is not None:
                try:
                    widget.destroyed.disconnect(self.release)
                except (RuntimeError, TypeError):
                    # The QObject may already be emitting destroyed, or Qt may
                    # have disconnected its signals during native teardown.
                    pass
        view, self._view = self._view, None
        if view:
            _send(view, "removeFromSuperview", None)
            _send(view, "release", None)
        self.applied = False
