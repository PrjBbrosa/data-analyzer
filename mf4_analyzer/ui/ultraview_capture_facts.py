"""Transient UltraView presentation-capture facts.

Chart hosts report a frozen snapshot through public methods. The collector
asks those methods; it does not probe canvas private fields. Facts must not
enter project / preset / Board state / sidecar schema.
"""
from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from PyQt5 import sip

from ..diagnostics import throttled

logger = logging.getLogger(__name__)

MIN_CAPTURE_EDGE = 8
CAPABILITY_OK = "ok"
CAPABILITY_UNSUPPORTED = "unsupported"
CAPABILITY_DEGRADED = "degraded"


@dataclass(frozen=True)
class CursorCompositionFacts:
    """Armed dual-cursor composition. Hover x is never included."""

    dual: bool = False
    geometry: tuple | None = None


@dataclass(frozen=True)
class PresentationCaptureFacts:
    """Immutable capture-eligibility snapshot for one host or widget.

    Transient only. Do not persist onto Board / workspace / sidecar.
    """

    host_kind: str
    capability: str = CAPABILITY_OK
    degrade_reason: str | None = None
    visible_and_sized: bool = False
    has_real_result: bool = False
    quality_settled: bool = False
    interaction_idle: bool = False
    cursor_dual: bool = False
    cursor_geometry: tuple | None = None
    cursor_geometries: tuple = ()
    source_revision: Any = None
    digest_leaves: tuple = ()

    @property
    def is_stable(self) -> bool:
        return (
            self.capability == CAPABILITY_OK
            and self.visible_and_sized
            and self.quality_settled
            and self.interaction_idle
        )


def finite_or_none(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def dual_cursor_geometry(*, dual: bool, ax, bx) -> tuple | None:
    """Armed dual geometry only. Single-mode hover x must not enter."""
    if not dual:
        return None
    ax_n = finite_or_none(ax)
    bx_n = finite_or_none(bx)
    if ax_n is None and bx_n is None:
        return None
    return ("dual", ax_n, bx_n)


def mapping_has_items(mapping) -> bool:
    if not mapping:
        return False
    try:
        return len(mapping) > 0
    except TypeError:
        return False


def quality_settled_from_status(status) -> bool:
    """Yellow = AA / raster still settling. Missing status is settled."""
    if not status:
        return True
    return status.get("state") != "yellow"


def quality_plotted_from_status(status) -> bool:
    """Ink presence from a public quality_status dict.

    ``curve_count`` is not the time emptiness gate. It is only a positive
    native-plot signal used by test doubles; production time canvases use
    plotted channel tables or ``render_path == "dense-raster"``.
    """
    if not status:
        return False
    if status.get("render_path") == "dense-raster":
        return True
    count = status.get("curve_count")
    if count is not None:
        try:
            if int(count) > 0:
                return True
        except (TypeError, ValueError):
            return False
        try:
            return int(status.get("high_raster_curve_count") or 0) > 0
        except (TypeError, ValueError):
            return False
    return status.get("state") == "green"


def build_capture_facts(
    *,
    host_kind: str,
    visible_and_sized: bool,
    has_real_result: bool,
    quality_settled: bool,
    interaction_idle: bool,
    cursor_dual: bool = False,
    cursor_geometry: tuple | None = None,
    source_revision: Any = None,
    digest_leaves: tuple | Iterable = (),
    capability: str = CAPABILITY_OK,
    degrade_reason: str | None = None,
) -> PresentationCaptureFacts:
    geometries = (cursor_geometry,) if cursor_geometry is not None else ()
    return PresentationCaptureFacts(
        host_kind=host_kind,
        capability=capability,
        degrade_reason=degrade_reason,
        visible_and_sized=visible_and_sized,
        has_real_result=has_real_result,
        quality_settled=quality_settled,
        interaction_idle=interaction_idle,
        cursor_dual=cursor_dual,
        cursor_geometry=cursor_geometry,
        cursor_geometries=geometries,
        source_revision=source_revision,
        digest_leaves=tuple(digest_leaves),
    )


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except (RuntimeError, TypeError):
        return True


def widget_visible_and_sized(widget, *, min_edge: int = MIN_CAPTURE_EDGE) -> bool:
    if not _alive(widget):
        return False
    try:
        if not widget.isVisible():
            return False
        return widget.width() >= min_edge and widget.height() >= min_edge
    except RuntimeError:
        return False


def iter_overlay_hosts(widget):
    """Yield pane canvases when the widget is a split analysis page."""
    pane_count = getattr(widget, "pane_count", None)
    pane_canvas = getattr(widget, "pane_canvas", None)
    if callable(pane_count) and callable(pane_canvas):
        for index in range(int(pane_count())):
            canvas = pane_canvas(index)
            if canvas is not None:
                yield canvas
        return
    yield widget


def iter_axes_rubberband_items(host) -> Iterator:
    """Rubber-band boxes from public ``axes_list`` / ``plots`` handles."""
    seen: set[int] = set()
    viewboxes = []
    for handle in getattr(host, "axes_list", None) or ():
        vb = getattr(handle, "view_box", None)
        if vb is not None:
            viewboxes.append(vb)
    for plot in getattr(host, "plots", None) or ():
        vb = getattr(plot, "vb", None)
        if vb is not None:
            viewboxes.append(vb)
    for vb in viewboxes:
        box = getattr(vb, "rbScaleBox", None)
        if box is None:
            continue
        ident = id(box)
        if ident in seen:
            continue
        seen.add(ident)
        yield box


def warn_missing_viewbox(host, section: str) -> None:
    host_type = type(host).__name__
    throttled(
        logger,
        f"ultraview:no-viewbox:{section}:{host_type}",
        logging.WARNING,
        "ultraview: no viewbox found on %s (%s)",
        section,
        host_type,
    )


def _unsupported_host_facts(host, *, reason: str) -> PresentationCaptureFacts:
    host_type = type(host).__name__ if host is not None else "none"
    throttled(
        logger,
        f"ultraview:unsupported-host:{host_type}:{reason}",
        logging.WARNING,
        "UltraView capture facts unsupported on %s (%s)",
        host_type,
        reason,
    )
    return PresentationCaptureFacts(
        host_kind="unsupported",
        capability=CAPABILITY_UNSUPPORTED,
        degrade_reason=reason,
        visible_and_sized=widget_visible_and_sized(host),
        has_real_result=False,
        quality_settled=False,
        interaction_idle=False,
    )


def collect_host_capture_facts(host) -> PresentationCaptureFacts:
    """Ask one overlay host for its public capture snapshot."""
    reporter = getattr(host, "presentation_capture_facts", None)
    if not callable(reporter):
        return _unsupported_host_facts(
            host, reason="missing-presentation-capture-facts"
        )
    if not _alive(host):
        return PresentationCaptureFacts(
            host_kind="unsupported",
            capability=CAPABILITY_DEGRADED,
            degrade_reason="host-deleted",
            visible_and_sized=False,
            has_real_result=False,
            quality_settled=False,
            interaction_idle=False,
        )
    facts = reporter()
    if not isinstance(facts, PresentationCaptureFacts):
        throttled(
            logger,
            f"ultraview:invalid-facts:{type(host).__name__}",
            logging.WARNING,
            "UltraView capture facts from %s were not PresentationCaptureFacts",
            type(host).__name__,
        )
        return PresentationCaptureFacts(
            host_kind="unsupported",
            capability=CAPABILITY_DEGRADED,
            degrade_reason="invalid-presentation-capture-facts",
            visible_and_sized=widget_visible_and_sized(host),
            has_real_result=False,
            quality_settled=False,
            interaction_idle=False,
        )
    return facts


def collect_widget_capture_facts(widget) -> PresentationCaptureFacts:
    """Aggregate pane/host facts for one capture target widget."""
    hosts = list(iter_overlay_hosts(widget))
    if not hosts:
        return _unsupported_host_facts(widget, reason="no-overlay-hosts")
    collected = [collect_host_capture_facts(host) for host in hosts]
    ok = [item for item in collected if item.capability == CAPABILITY_OK]
    if not ok:
        return collected[0]
    geometries = tuple(
        geom for item in ok for geom in item.cursor_geometries
    )
    leaves = tuple(leaf for item in ok for leaf in item.digest_leaves)
    kind = ok[0].host_kind if len(ok) == 1 else "composite"
    revision = ok[0].source_revision if len(ok) == 1 else None
    return PresentationCaptureFacts(
        host_kind=kind,
        capability=CAPABILITY_OK,
        visible_and_sized=(
            widget_visible_and_sized(widget)
            and all(item.visible_and_sized for item in ok)
        ),
        has_real_result=any(item.has_real_result for item in ok),
        quality_settled=all(item.quality_settled for item in ok),
        interaction_idle=all(item.interaction_idle for item in ok),
        cursor_dual=any(item.cursor_dual for item in ok),
        cursor_geometry=geometries[0] if geometries else None,
        cursor_geometries=geometries,
        source_revision=revision,
        digest_leaves=leaves,
    )


@contextmanager
def hide_transient_overlays(widget, *, section: str = "unknown"):
    """Hide hover/rubber-band items via each host's public overlay API.

    Hover follow lines (single and dual) are transient. Dual armed A/B
    lines and extreme markers stay visible so the snapshot matches
    copy-as-image. Persistent remarks are not in the transient set.
    """
    hidden = []
    try:
        for host in iter_overlay_hosts(widget):
            getter = getattr(host, "iter_transient_overlay_items", None)
            if not callable(getter):
                if callable(getattr(host, "presentation_capture_facts", None)):
                    throttled(
                        logger,
                        f"ultraview:missing-transient:{section}:{type(host).__name__}",
                        logging.WARNING,
                        "UltraView host %s (%s) lacks iter_transient_overlay_items",
                        section,
                        type(host).__name__,
                    )
                continue
            for item in getter(section=section) or ():
                if not _alive(item):
                    continue
                try:
                    visible = bool(item.isVisible())
                except (RuntimeError, TypeError):
                    continue
                if not visible:
                    continue
                try:
                    item.hide()
                except (RuntimeError, TypeError):
                    continue
                hidden.append(item)
        yield
    finally:
        for item in hidden:
            if not _alive(item):
                continue
            try:
                item.show()
            except (RuntimeError, TypeError):
                continue


def analysis_idle_timer_is_busy(timer) -> bool:
    """True when a host-owned AA idle timer is still armed."""
    if timer is None:
        return False
    try:
        return bool(timer.isActive())
    except RuntimeError:
        return False


__all__ = [
    "CAPABILITY_DEGRADED",
    "CAPABILITY_OK",
    "CAPABILITY_UNSUPPORTED",
    "CursorCompositionFacts",
    "MIN_CAPTURE_EDGE",
    "PresentationCaptureFacts",
    "analysis_idle_timer_is_busy",
    "build_capture_facts",
    "collect_host_capture_facts",
    "collect_widget_capture_facts",
    "dual_cursor_geometry",
    "finite_or_none",
    "hide_transient_overlays",
    "iter_axes_rubberband_items",
    "iter_overlay_hosts",
    "mapping_has_items",
    "quality_plotted_from_status",
    "quality_settled_from_status",
    "warn_missing_viewbox",
    "widget_visible_and_sized",
]
