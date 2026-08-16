"""Shared Qt-free remark-intent store for analysis canvases.

Time-domain annotations live in ``AnnotationManager``. FFT / heatmap / FRF
canvases share this store so a replot can drop Qt items and reproject
without discarding the user's overlay.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from mf4_analyzer.ui.view_overlay_state import (
    normalize_cursor_placement,
    normalize_remark,
    normalize_remarks,
)

from .remarks import remark_label_offset, remark_qt_alive


def _finite_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _source_key(raw):
    if isinstance(raw, Mapping):
        raw = raw.get("source")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        fid, channel = raw[0], raw[1]
        if fid is None or channel is None:
            return None
        return (str(fid), str(channel))
    return None


def _panel_of(raw) -> str:
    if not isinstance(raw, Mapping):
        return ""
    panel = raw.get("panel")
    return str(panel).strip() if panel is not None else ""


class AnalysisRemarkStore:
    """Intent list for one analysis canvas. Qt items are a projection."""

    def __init__(self):
        self.items: list[dict] = []

    def clear(self) -> None:
        self.items = []

    def replace(self, payload) -> None:
        self.items = []
        for raw in payload or []:
            item = self._coerce(raw)
            if item is not None:
                self.items.append(item)

    def record(self, remark, *, panel: str | None = None) -> None:
        item = self._from_live(remark, panel=panel)
        if item is not None:
            self.items.append(item)

    def discard(self, remark) -> None:
        source = _source_key(remark)
        panel = _panel_of(remark)
        rx = self._physical_x(remark)
        best_i, best_d = None, float("inf")
        for i, item in enumerate(self.items):
            if _source_key(item) != source:
                continue
            if _panel_of(item) != panel:
                continue
            ix = _finite_float(item.get("x"))
            if ix is None or rx is None:
                continue
            dist = abs(ix - rx)
            if dist < best_d:
                best_i, best_d = i, dist
        if best_i is not None:
            self.items.pop(best_i)

    def snapshot(self, live_remarks) -> list[dict]:
        used = set()
        payload = []
        for intent in list(self.items):
            item = dict(intent)
            live = self._live_for(item, live_remarks, used)
            if live is not None:
                offset = remark_label_offset(live)
                if offset is not None:
                    item["label_dx"] = float(offset[0])
                    item["label_dy"] = float(offset[1])
                x = self._physical_x(live)
                y = _finite_float(live.get("data_y"))
                if x is not None:
                    item["x"] = x
                if y is not None:
                    item["y"] = y
                panel = _panel_of(live) or _panel_of(item)
                if panel:
                    item["panel"] = panel
            normalized = normalize_remark(item)
            if normalized is not None:
                payload.append(normalized)
        for i, remark in enumerate(live_remarks or []):
            if i in used:
                continue
            extra = self._from_live(remark)
            if extra is None:
                continue
            normalized = normalize_remark(extra)
            if normalized is not None:
                payload.append(normalized)
        return payload

    def _coerce(self, raw):
        normalized = normalize_remark(raw)
        if normalized is not None:
            return normalized
        if not isinstance(raw, Mapping):
            return None
        x = _finite_float(raw.get("x"))
        y = _finite_float(raw.get("y"))
        if x is None or y is None:
            return None
        item = {"x": x, "y": y}
        panel = raw.get("panel")
        if isinstance(panel, str) and panel.strip():
            item["panel"] = panel.strip()
        for key in ("label_dx", "label_dy"):
            value = _finite_float(raw.get(key))
            if value is not None:
                item[key] = value
        return item

    def _from_live(self, remark, *, panel: str | None = None):
        if not isinstance(remark, dict):
            return None
        x = self._physical_x(remark)
        y = _finite_float(remark.get("data_y"))
        if x is None or y is None:
            return None
        item = {"x": x, "y": y}
        source = remark.get("source")
        if source is not None:
            item["source"] = source
        resolved_panel = panel or _panel_of(remark)
        if resolved_panel:
            item["panel"] = resolved_panel
        offset = remark_label_offset(remark)
        if offset is not None:
            item["label_dx"] = float(offset[0])
            item["label_dy"] = float(offset[1])
        return self._coerce(item)

    def _live_for(self, intent, live_remarks, used):
        source = _source_key(intent)
        panel = _panel_of(intent)
        ix = _finite_float(intent.get("x"))
        best_i, best_d = None, float("inf")
        for i, remark in enumerate(live_remarks or []):
            if i in used or not isinstance(remark, dict):
                continue
            if not remark_qt_alive(remark.get("vb")):
                continue
            if not remark_qt_alive(remark.get("text")):
                continue
            if _source_key(remark) != source:
                continue
            if _panel_of(remark) != panel:
                continue
            rx = self._physical_x(remark)
            if rx is None or ix is None:
                continue
            dist = abs(rx - ix)
            if dist < best_d:
                best_i, best_d = i, dist
        if best_i is None:
            return None
        used.add(best_i)
        return live_remarks[best_i]

    @staticmethod
    def _physical_x(remark):
        if not isinstance(remark, dict):
            return None
        physical = _finite_float(remark.get("display_x"))
        if physical is not None:
            return physical
        return _finite_float(remark.get("data_x"))


def snapshot_frequency_cursor(ax, bx, *, cursor_mode: str = "off"):
    payload = {}
    if ax is not None:
        payload["ax"] = ax
    if bx is not None or "ax" in payload:
        payload["bx"] = bx
    return normalize_cursor_placement(payload, cursor_mode=cursor_mode)


__all__ = [
    "AnalysisRemarkStore",
    "normalize_remarks",
    "snapshot_frequency_cursor",
]
