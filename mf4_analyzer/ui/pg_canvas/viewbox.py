"""ViewBox subclass used by the pyqtgraph time-domain canvas."""

from __future__ import annotations

from . import _binding  # noqa: F401

import pyqtgraph as pg
from PyQt5.QtCore import Qt

from .context_menu import _localize_pg_context_menu


class _WheelDeltaGraphicsLayoutWidget(pg.GraphicsLayoutWidget):
    """Preserve raw pixel-wheel direction for scene-level ViewBox events."""

    def __init__(self, *args, owner_canvas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner_canvas = owner_canvas

    def wheelEvent(self, ev):
        owner = self._owner_canvas
        delta = 0.0
        try:
            angle = ev.angleDelta()
            delta = float(angle.y())
            if delta == 0.0:
                pixel = ev.pixelDelta()
                delta = float(pixel.y())
        except Exception:
            pass
        if owner is not None:
            owner._raw_wheel_delta = delta
        try:
            super().wheelEvent(ev)
        finally:
            if owner is not None:
                owner._raw_wheel_delta = None


class _ModifierWheelViewBox(pg.ViewBox):
    """ViewBox that consults Qt keyboard modifiers on wheel events."""

    def __init__(self, *args, owner_canvas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner_canvas = owner_canvas
        _localize_pg_context_menu(getattr(self, "menu", None))

    def raiseContextMenu(self, ev):
        if self._delete_remark_from_context_event(ev):
            return
        menu = self.getMenu(ev)
        if menu is None:
            return
        try:
            self.scene().addParentContextMenus(self, menu, ev)
        except Exception:
            pass
        owner = self._owner_canvas
        if owner is not None and hasattr(owner, "context_menu_requested"):
            owner.context_menu_requested.emit()
        if owner is not None and hasattr(owner, "_redesign_context_menu_for_viewbox"):
            try:
                try:
                    owner._last_rclick_scene_pos = ev.scenePos()
                except Exception:
                    pass
                owner._redesign_context_menu_for_viewbox(self, menu)
            except Exception:
                _localize_pg_context_menu(menu)
        else:
            _localize_pg_context_menu(menu)
        try:
            menu.popup(ev.screenPos().toPoint())
        except Exception:
            pass

    def _delete_remark_from_context_event(self, ev):
        owner = self._owner_canvas
        annotations = getattr(owner, "_annotations", None) if owner is not None else None
        if annotations is None or not getattr(annotations, "enabled", False):
            return False
        try:
            scene_pos = ev.scenePos()
        except Exception:
            scene_pos = None
        owner._last_rclick_scene_pos = scene_pos
        annotations._remove_remark_at(scene_pos)
        return True

    def wheelEvent(self, ev, axis=None):
        owner = self._owner_canvas
        if owner is None:
            super().wheelEvent(ev, axis=axis)
            return
        try:
            delta = float(ev.delta())
            if delta == 0.0:
                delta = float(getattr(owner, "_raw_wheel_delta", 0.0) or 0.0)
            modifiers = ev.modifiers()
            scene_pos = ev.scenePos()
            data_pos = self.mapSceneToView(scene_pos)
            x_pos = float(data_pos.x())
            y_pos = float(data_pos.y())
        except Exception:
            super().wheelEvent(ev, axis=axis)
            return
        consumed = owner._handle_wheel_dispatch(
            delta=delta, modifiers=modifiers, x_pos=x_pos, y_pos=y_pos,
            view_box=self, scene_pos=scene_pos, axis=axis,
        )
        if consumed:
            ev.accept()
        else:
            super().wheelEvent(ev, axis=axis)

    def mouseDragEvent(self, ev, axis=None):
        owner = self._owner_canvas
        try:
            is_left_2d = (
                owner is not None
                and ev.button() == Qt.LeftButton
                and axis is None
            )
            is_rect_left_2d = (
                is_left_2d
                and self.state.get("mouseMode") == pg.ViewBox.RectMode
            )
        except Exception:
            is_left_2d = False
            is_rect_left_2d = False
        if is_left_2d:
            try:
                if ev.isStart():
                    begin = getattr(owner, "_begin_view_interaction", None)
                    if callable(begin):
                        begin()
                    elif is_rect_left_2d:
                        owner.disable_interactive_quality()
            except Exception:
                pass
        super().mouseDragEvent(ev, axis=axis)
        if is_rect_left_2d:
            try:
                is_xmaster = (
                    getattr(owner, "_overlay_mode", False)
                    and getattr(owner, "_x_master_handle", None) is not None
                    and owner._x_master_handle.view_box is self
                )
                if is_xmaster and ev.isFinish():
                    owner._apply_overlay_box_zoom_y()
            except Exception:
                pass
        if is_left_2d:
            try:
                if ev.isFinish():
                    end = getattr(owner, "_end_view_interaction", None)
                    if callable(end):
                        end()
            except Exception:
                pass


__all__ = ["_ModifierWheelViewBox", "_WheelDeltaGraphicsLayoutWidget"]
