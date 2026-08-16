"""UltraView capture pipeline: presentation digest, stable grab, PreviewStore.

UltraView never computes, restores-from-cache, or replots a source View to
fill a preview. This coordinator only reads already-visible source state and
grabs canvases that already satisfy the stability contract.
"""
from __future__ import annotations

import logging
import math
import re
import weakref
from contextlib import contextmanager, nullcontext
from functools import partial
from pathlib import Path
from time import monotonic
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QFileDialog, QWidget

from ...diagnostics import throttled
from ...render_profile import source_revision_for
from ..ultraview_state import (
    COMPARE_FILTER_ALL,
    SECTION_AXIS_KIND,
    SOURCE_SECTIONS,
    PreviewMeta,
    UltraViewBoardState,
    UltraViewWorkspaceState,
    UltraViewRef,
    GridAnchor,
    active_board,
    add_ref,
    apply_board_placement,
    apply_free_grid_preset,
    all_refs,
    best_template_for,
    capture_board_placement,
    create_board,
    delete_board,
    default_board,
    default_workspace,
    duplicate_board,
    derive_preview_status,
    layout_slots,
    LAYOUT_MODE_FREE_GRID,
    MAX_UI_BOARDS,
    mark_workspace_mutated,
    membership_set,
    move_to_unplaced,
    nudge_ratio,
    normalize_workspace_payload,
    parse_ref_payload,
    place_from_unplaced,
    place_free_grid_from_unplaced,
    placed_ref_set,
    placement_for,
    presentation_digest,
    rebind_ref,
    rename_board,
    reorder_board,
    remove_ref,
    replace_free_grid_ref,
    replace_slot,
    set_layout,
    set_active_board,
    set_free_grid_rect,
    set_free_grid_rects,
    set_presentation_flags,
    set_workspace_show_card_actions,
    set_workspace_preview_sidecar,
    swap_slots,
    template_to_free_grid,
    free_grid_default_span,
    free_grid_to_template,
    free_grid_placement_for,
    organize_free_grid,
    BoardPlacementSnapshot,
    GridRect,
    workspace_to_payload,
    DEFAULT_BOARD_NAME,
)
from ..chart_stack.ultraview.preview_store import (
    MAX_PREVIEW_RAW_EDGE,
    PreviewStore,
    ResidencyRequest,
    RESIDENCY_TIER_FOCUS,
    RESIDENCY_TIER_ACTIVE_VISIBLE,
    RESIDENCY_TIER_ACTIVE_PLACED,
    RESIDENCY_TIER_INACTIVE_PLACED,
    RESIDENCY_TIER_TRAY,
)
from ..chart_stack.ultraview.feedback import (
    MEMBERSHIP_CAP,
    PLACED_CAP_STILL_UNPLACED,
    PLACED_CAP_TO_TRAY,
    REMOVED_FROM_BOARD,
    text_for_key,
)
from ..chart_stack.ultraview.free_grid import (
    LAYOUT_RESIZE,
    fit_rect_for_aspect,
    plan_layout,
    screen_grid_metrics,
)
from ..chart_stack.ultraview.viewport import (
    SMOOTH_DELAY_MS,
    focus_grab_scale,
    needs_focus_recapture,
)
from ..chart_stack.ultraview.preview_sidecar import (
    SidecarImagePayload,
    open_preview_sidecar,
    publish_sidecar_image,
    save_preview_sidecar,
)
from ..chart_stack.ultraview.widgets import LibraryRow
from ..chart_stack.ultraview.compositor import (
    ComposeError,
    compose_board,
    save_composed_png,
)
from ..image_utils import pixmap_as_device_pixel_image
from .ultraview_runtime import PresentationRuntimeFacts, PresentationRuntimeLedger

logger = logging.getLogger(__name__)

_MIN_CAPTURE_EDGE = 8
_IDLE_CAPTURE_MS = 120
_SIDECAR_LOAD_BATCH = 2
_DIGEST_RETRY_LIMIT = 3
_HEATMAP_SECTIONS = frozenset({"fft_time", "order"})
_PIXEL_AFFECTING_SIGNALS = frozenset(
    {
        "visible_range_changed",
        "markup_revision_changed",
        "dual_cursor_info",
        "manual_zoom_changed",
    }
)
_HTML_TAG = re.compile(r"<[^>]+>")
_HOVER_CURSOR_LISTS = ("_cursor_line_items", "_cursor_lines")
# Skip details that describe an expected state rather than a fault. A View the
# user simply has not computed is not a defect, and the card already shows it
# via ``_push_preview(usable=False)`` — the log does not need to shout too.
# Every other detail (digest-unavailable, grab-invalid, …) stays a warning.
_CAPTURE_SKIP_LEVELS = {"no-result": logging.DEBUG}
_SECTION_X_UNIT = {
    "time": "s",
    "fft": "Hz",
    "fft_time": "s",
    "frf": "Hz",
    "order": "s",
}


_PLACEMENT_HISTORY_CAP = 100


@dataclass(frozen=True)
class _GridHistoryEntry:
    before: BoardPlacementSnapshot
    after: BoardPlacementSnapshot


@dataclass
class _GridHistory:
    undo: list[_GridHistoryEntry]
    redo: list[_GridHistoryEntry]


@dataclass(frozen=True)
class _PendingAutoAspect:
    board_id: str
    ref: UltraViewRef
    inserted_rect: GridRect
    layout_revision: int
    merge_add: bool = True


def notify_ultraview_plot(window, section: str, reason: str = "plot") -> None:
    """Queue a visible-section capture after an actual plot/set_result."""
    coordinator = getattr(window, "_ultraview", None)
    if coordinator is None or coordinator.is_shutdown:
        return
    coordinator.request_visible_section_capture(section, reason)


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except (RuntimeError, TypeError):
        return True


def _iter_overlay_hosts(widget):
    pane_count = getattr(widget, "pane_count", None)
    pane_canvas = getattr(widget, "pane_canvas", None)
    if callable(pane_count) and callable(pane_canvas):
        for index in range(int(pane_count())):
            canvas = pane_canvas(index)
            if canvas is not None:
                yield canvas
        return
    yield widget


_PLOT_ATTR_NAMES = (
    "_plot",
    "_plot_amp",
    "_plot_time",
    "_plot_magnitude",
    "_plot_phase",
    "_plot_coherence",
)


def _iter_viewboxes(widget):
    axes = getattr(widget, "axes_list", None) or ()
    for handle in axes:
        vb = getattr(handle, "view_box", None)
        if vb is not None:
            yield vb
    for name in _PLOT_ATTR_NAMES:
        plot = getattr(widget, name, None)
        vb = getattr(plot, "vb", None) if plot is not None else None
        if vb is not None:
            yield vb
    plots = getattr(widget, "plots", None) or ()
    for plot in plots:
        vb = getattr(plot, "vb", None)
        if vb is not None:
            yield vb


def _host_expects_viewbox(host) -> bool:
    """True when the host looks like a plot surface that should have a ViewBox.

    An empty View (no axes, no ``_plot*`` attrs) is a legal capture target and
    must not warn. A renamed fake such as ``_plotx`` still counts as a plot
    surface, so a missing ViewBox stays a warning.
    """
    if getattr(host, "axes_list", None):
        return True
    if getattr(host, "plots", None):
        return True
    return any(
        name.startswith("_plot") and getattr(host, name, None) is not None
        for name in dir(host)
    )


def _host_is_dual_cursor(host) -> bool:
    cursor = getattr(host, "_cursor", None)
    if cursor is not None:
        return bool(getattr(cursor, "dual", False))
    getter = getattr(host, "cursor_mode", None)
    if not callable(getter):
        return False
    try:
        return getter() == "dual"
    except (TypeError, RuntimeError):
        return False


def _iter_hover_cursor_items(owner):
    if owner is None:
        return
    for name in _HOVER_CURSOR_LISTS:
        items = getattr(owner, name, None)
        if items:
            yield from items


def _iter_transient_overlay_items(widget, *, section: str = "unknown"):
    seen = set()
    for host in _iter_overlay_hosts(widget):
        # Hover follow lines are always transient. Single mode has no armed
        # cursor (the solid line is mouse-follow); dual mode's dotted hover
        # is the same list. Armed dual A/B lines live on _cursor_a_items /
        # _cursor_b_items and are not in _HOVER_CURSOR_LISTS.
        for owner in (host, getattr(host, "_cursor", None)):
            for item in _iter_hover_cursor_items(owner):
                ident = id(item)
                if ident in seen:
                    continue
                seen.add(ident)
                yield item
        viewboxes = tuple(_iter_viewboxes(host))
        if not viewboxes and _host_expects_viewbox(host):
            host_type = type(host).__name__
            throttled(
                logger,
                f"ultraview:no-viewbox:{section}:{host_type}",
                logging.WARNING,
                "ultraview: no viewbox found on %s (%s)",
                section,
                host_type,
            )
        for vb in viewboxes:
            box = getattr(vb, "rbScaleBox", None)
            if box is not None and id(box) not in seen:
                seen.add(id(box))
                yield box


def _finite_or_none(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _cursor_geometry_from_host(host):
    """Armed dual geometry only. Single-mode has no armed cursor."""
    cursor = getattr(host, "_cursor", None)
    if cursor is not None:
        if bool(getattr(cursor, "dual", False)):
            ax = _finite_or_none(getattr(cursor, "ax", None))
            bx = _finite_or_none(getattr(cursor, "bx", None))
            if ax is None and bx is None:
                return None
            return ["dual", ax, bx]
        return None
    getter = getattr(host, "cursor_mode", None)
    if not callable(getter):
        return None
    try:
        mode = getter()
    except (TypeError, RuntimeError):
        return None
    if mode == "dual":
        ax = _finite_or_none(getattr(host, "_cursor_a_frequency", None))
        bx = _finite_or_none(getattr(host, "_cursor_b_frequency", None))
        if ax is None and bx is None:
            return None
        return ["dual", ax, bx]
    return None


def _plain_text(value) -> str:
    if not value:
        return ""
    return _HTML_TAG.sub("", str(value)).strip()


@contextmanager
def hide_transient_overlays(widget, *, section: str = "unknown"):
    """Hide hover/rubber-band items; restore in ``finally``.

    Hover follow lines (single and dual) are transient. Dual armed A/B
    lines and extreme markers stay visible so the snapshot matches
    copy-as-image. Persistent remarks are not in the transient set.
    """
    hidden = []
    try:
        for item in _iter_transient_overlay_items(widget, section=section):
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


def read_markup_revision(widget) -> int:
    if widget is None:
        return 0
    annotations = getattr(widget, "_annotations", None)
    if annotations is not None and hasattr(annotations, "markup_revision"):
        return int(annotations.markup_revision or 0)
    pane_count = getattr(widget, "pane_count", None)
    pane_canvas = getattr(widget, "pane_canvas", None)
    if callable(pane_count) and callable(pane_canvas):
        revisions = []
        for index in range(int(pane_count())):
            revisions.append(read_markup_revision(pane_canvas(index)))
        return tuple(revisions) if revisions else 0
    return int(getattr(widget, "markup_revision", 0) or 0)


def _channel_pair(key):
    if key is None:
        return None
    try:
        fid, channel = key
    except (TypeError, ValueError):
        return None
    return [str(fid), str(channel)]


class _ResultIdentityRef:
    """Callable identity token for result-generation (UVL-A12).

    Weakref when the result supports it, so a GC'd object cannot recycle
    ``id()`` into a false "unchanged" match. Analysis-cache payloads are
    often tuples/ndarrays, and tests use ``object()`` — none of those can
    be weakly referenced. Those keep a strong token so same-object
    re-notify does not bump; replacement still compares with ``is``.
    """

    __slots__ = ("_ref", "_obj")

    def __init__(self, result) -> None:
        try:
            self._ref = weakref.ref(result)
            self._obj = None
        except TypeError:
            self._ref = None
            self._obj = result

    def __call__(self):
        if self._ref is not None:
            return self._ref()
        return self._obj


def _stable_source_revision(revision):
    """Content fingerprint for UltraView digest; drop ndarray ``id()``.

    ``source_revision_for`` includes object ids so in-place mutation of a
    held array is visible. ``Series.to_numpy()`` / ``np.asarray`` often
    return a new wrapper each call, so those ids churn while the samples
    do not. A presentation digest that includes them never matches the
    queued capture, and the Board stays missing.
    """
    if revision is None:
        return None
    try:
        kind = revision[0]
        items = list(revision)
    except (TypeError, IndexError):
        return None
    if kind == "explicit":
        return items
    if kind == "probed" and len(items) >= 9:
        return [kind, *items[3:]]
    return items


def _array_from_column(column):
    if column is None:
        return None
    to_numpy = getattr(column, "to_numpy", None)
    if callable(to_numpy):
        return to_numpy(copy=False)
    values = getattr(column, "values", None)
    if values is not None:
        return values
    return column


class UltraViewCoordinator(QObject):
    """Owns PreviewStore, canvas→ref bindings, capture queue, and digest."""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent if parent is not None else window)
        self._window_ref = weakref.ref(window)
        self._store = PreviewStore(parent=self)
        self._store.images_dropped.connect(self._on_store_images_dropped)
        self._shutdown = False
        self._bindings: dict[int, tuple[UltraViewRef, Any]] = {}
        self._queued: dict[tuple, QTimer] = {}
        self._unstable: dict[int, tuple] = {}
        self._hooks: list[tuple[Any, Any, Any]] = []
        self._hooked_ids: set[int] = set()
        self._destroy_watched: set[int] = set()
        self._idle_pending: dict[UltraViewRef, tuple[Any, float]] = {}
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(_IDLE_CAPTURE_MS)
        self._idle_timer.timeout.connect(self._on_idle_capture_timeout)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.setInterval(SMOOTH_DELAY_MS)
        self._focus_timer.timeout.connect(self._on_focus_residency_timeout)
        self._sidecar_generation = 0
        self._sidecar_pending: list[SidecarImagePayload] = []
        self._sidecar_timer = QTimer(self)
        self._sidecar_timer.setSingleShot(True)
        self._sidecar_timer.setInterval(0)
        self._sidecar_timer.timeout.connect(self._on_sidecar_load_timeout)
        self._digest_retries: dict[UltraViewRef, int] = {}
        self._result_refs: dict[tuple, _ResultIdentityRef] = {}
        self._result_generation: dict[tuple, int] = {}
        self._runtime = PresentationRuntimeLedger()
        self._presentation_revision: dict[UltraViewRef, int] = {}
        self.last_source_mode = "time"
        self._workspace = default_workspace()
        self._grid_histories: dict[str, _GridHistory] = {}
        self._pending_auto_aspect: dict[tuple[str, UltraViewRef], _PendingAutoAspect] = {}
        self._layout_revision: dict[str, int] = {}
        self._page_hooks: list[tuple[Any, Any, Any]] = []
        self._stack_hooks: list[tuple[Any, Any, Any]] = []
        self._manager_hooks: list[tuple[Any, Any, Any]] = []
        self._sync_work_queue: list[UltraViewRef] = []
        self._sync_current_ref: UltraViewRef | None = None
        self._sync_nav_busy = False
        self._sync_nav_needs_raise = False
        self.attach()

    @property
    def is_shutdown(self) -> bool:
        return bool(self._shutdown)

    def _inactive(self) -> bool:
        return self._shutdown or not _alive(self)

    @property
    def store(self) -> PreviewStore:
        return self._store

    @property
    def _window(self):
        return self._window_ref()

    def note_source_mode(self, mode: str) -> None:
        if mode in SOURCE_SECTIONS:
            self.last_source_mode = mode

    def bind_canvas(self, canvas, ref: UltraViewRef | None) -> None:
        if self._inactive():
            return
        if canvas is None or not _alive(canvas):
            return
        ident = id(canvas)
        if ref is None:
            self._bindings.pop(ident, None)
            self._unstable.pop(ident, None)
            return
        self._bindings[ident] = (ref, weakref.ref(canvas))
        self._ensure_stability_hooks(canvas)
        self._watch_canvas_destroyed(canvas)

    def bound_ref_for(self, canvas) -> UltraViewRef | None:
        if canvas is None:
            return None
        item = self._bindings.get(id(canvas))
        return None if item is None else item[0]

    def offer_capture_bound_canvas(
        self, canvas, incoming_ref: UltraViewRef | None = None
    ) -> None:
        """Grab the currently bound ref before the canvas scene is overwritten.

        Must run synchronously: a queued grab would see the new binding and
        drop the old frame (UV-A18). Same-view replot does not capture the
        outgoing frame.         Hidden secondary widgets are skipped.
        """
        if self._inactive():
            return
        if canvas is None or not _alive(canvas):
            return
        try:
            if not canvas.isVisible():
                return
        except RuntimeError:
            return
        ref = self.bound_ref_for(canvas)
        if ref is None:
            return
        if incoming_ref is not None and ref == incoming_ref:
            return
        self._try_publish_now(ref, canvas, "leaving-bound-canvas")

    def request_capture(self, ref, widget, reason: str) -> None:
        if self._inactive():
            return
        if ref is None or widget is None or not _alive(widget):
            return
        try:
            if not widget.isVisible():
                return
        except RuntimeError:
            return
        if not self._widget_has_any_real_result(widget):
            self._warn_capture(ref, widget, reason, "no-result")
            self._push_preview(ref, usable=False)
            return
        digest = self.current_digest_for(ref)
        if digest is None:
            self._warn_capture(ref, widget, reason, "digest-unavailable")
            return
        if self._has_current_preview(ref, digest) and not self._needs_focus_recapture(
            ref
        ):
            return
        key = (ref, digest)
        self._drop_queued_for_ref(ref, keep=key)
        if key in self._queued:
            return
        self._ensure_stability_hooks(widget)
        if not self._is_stable(widget, ref.section):
            self._unstable[id(widget)] = (ref, digest, reason, weakref.ref(widget))
            return
        self._unstable.pop(id(widget), None)
        if ref.section in _HEATMAP_SECTIONS or self._hosts_heatmap(widget):
            self._queue_heatmap_grab(key, ref, widget, digest, reason)
            return
        self._queue_grab(key, ref, widget, digest, reason)

    def request_visible_section_capture(self, section: str, reason: str = "plot") -> None:
        if self._inactive():
            return
        window = self._window
        if window is None:
            return
        ref = self._active_ref(section)
        if ref is None:
            return
        widget = self._visible_widget_for(section)
        if widget is None:
            return
        self.bind_canvas(widget, ref)
        self.request_capture(ref, widget, reason)

    def notify_result_stored(self, section, view_id, pane_idx, key, result) -> None:
        """Bump generation when the stored result object is new, replaced, or gone.

        Same-object repeat notify is a real path and must not bump. Identity
        is a weakref when possible so a GC'd object cannot recycle its
        ``id()`` into a false "unchanged" comparison (UVL-A12). Objects that
        cannot be weakly referenced keep a strong token and still compare
        with ``is`` — unconditional TypeError bump would jitter digest on
        cache-hit re-notify of tuples/ndarrays.
        """
        if self._inactive():
            return
        slot = self._generation_slot(section, view_id, pane_idx, key)
        previous = self._result_refs.get(slot)
        if previous is not None and previous() is result:
            return
        self._result_generation[slot] = int(self._result_generation.get(slot, 0)) + 1
        self._result_refs[slot] = _ResultIdentityRef(result)

    def result_generation_for(self, section, view_id, pane_idx, key) -> int:
        slot = self._generation_slot(section, view_id, pane_idx, key)
        return int(self._result_generation.get(slot, 0))

    def presentation_payload_for(self, ref: UltraViewRef) -> dict | None:
        window = self._window
        if window is None or ref is None:
            return None
        if ref.section == "time":
            return self._time_payload(window, ref)
        if ref.section in SOURCE_SECTIONS:
            return self._analysis_payload(window, ref)
        return None

    def current_digest_for(self, ref: UltraViewRef) -> str | None:
        payload = self.presentation_payload_for(ref)
        if payload is None:
            return None
        try:
            return presentation_digest(payload)
        except (TypeError, ValueError) as exc:
            # The exception names the offending leaf; a bare "digest failed"
            # does not, and that is the whole diagnosis when a section stops
            # producing previews.
            self._warn_digest(ref, exc)
            return None

    def set_pinned_from_board(self, board) -> None:
        """Compatibility name for P0 callers; residency is Workspace-wide."""
        active = active_board(self._workspace)
        sizes = self._card_display_sizes()
        requests = []
        for candidate in self._workspace.boards:
            if candidate.board_id == active.board_id:
                placed = placed_ref_set(candidate)
                for ref in placed:
                    target = _display_target_size(sizes.get(ref))
                    preview = self._preview_pixel_size(ref)
                    if target is not None and needs_focus_recapture(target, preview):
                        requests.append(
                            ResidencyRequest(
                                ref, tier=RESIDENCY_TIER_FOCUS, target_size=target
                            )
                        )
                    else:
                        tier = (
                            RESIDENCY_TIER_ACTIVE_VISIBLE
                            if self._active_card_visible(ref)
                            else RESIDENCY_TIER_ACTIVE_PLACED
                        )
                        requests.append(
                            ResidencyRequest(ref, tier=tier, target_size=target)
                        )
                requests.extend(
                    ResidencyRequest(ref, tier=RESIDENCY_TIER_TRAY)
                    for ref in candidate.unplaced
                )
            else:
                requests.extend(
                    ResidencyRequest(ref, tier=RESIDENCY_TIER_INACTIVE_PLACED)
                    for ref in placed_ref_set(candidate)
                )
                requests.extend(
                    ResidencyRequest(ref, tier=RESIDENCY_TIER_TRAY)
                    for ref in candidate.unplaced
                )
        self._store.set_residency_requests(requests)

    def _active_card_visible(self, ref: UltraViewRef) -> bool:
        page = self.page()
        if page is None:
            return False
        card = page.card_widget(ref.section, ref.view_id)
        scroll = getattr(page, "board_scroll_area", lambda: None)()
        if card is None or scroll is None:
            return False
        try:
            rect = card.rect()
            center = card.mapTo(scroll.viewport(), rect.center())
            return scroll.viewport().rect().contains(center)
        except RuntimeError:
            return False

    def _card_display_sizes(self) -> dict:
        page = self.page()
        getter = getattr(page, "card_display_sizes", None) if page is not None else None
        if not callable(getter):
            return {}
        try:
            return dict(getter())
        except RuntimeError:
            return {}

    def _preview_pixel_size(self, ref: UltraViewRef) -> tuple[int, int]:
        record = self._store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if image is None or not PreviewStore.image_valid(image):
            return (0, 0)
        return (int(image.width()), int(image.height()))

    def _needs_focus_recapture(self, ref: UltraViewRef) -> bool:
        request = self._store.residency_request(ref)
        if request is None or request.tier != RESIDENCY_TIER_FOCUS:
            return False
        record = self._store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if image is None or not PreviewStore.image_valid(image):
            return True
        if max(image.width(), image.height()) >= MAX_PREVIEW_RAW_EDGE:
            return False
        target = request.target_size
        if target is None:
            return False
        preview = (image.width(), image.height())
        if not needs_focus_recapture(target, preview):
            return False
        widget = self._widget_for_ref(ref)
        if widget is None:
            return True
        try:
            native_w = max(1.0, float(widget.width()) * float(widget.devicePixelRatioF()))
            native_h = max(1.0, float(widget.height()) * float(widget.devicePixelRatioF()))
        except RuntimeError:
            return True
        scale = self._grab_scale(widget, ref)
        next_w = native_w * scale
        next_h = native_h * scale
        return image.width() + 1 < next_w or image.height() + 1 < next_h

    def _on_camera_settled(self) -> None:
        if self._inactive():
            return
        self._focus_timer.start()

    def _on_focus_residency_timeout(self) -> None:
        if self._inactive():
            return
        self.set_pinned_from_board(active_board(self._workspace))
        self._recapture_focus_refs()

    def _recapture_focus_refs(self) -> None:
        for board in self._workspace.boards:
            for ref in placed_ref_set(board):
                if not self._needs_focus_recapture(ref):
                    continue
                widget = self._widget_for_ref(ref)
                if widget is None:
                    candidate = self._visible_widget_for(ref.section)
                    if candidate is not None and self._active_ref(ref.section) == ref:
                        widget = candidate
                if widget is None:
                    continue
                self.bind_canvas(widget, ref)
                self.request_capture(ref, widget, "focus")

    def project_source_mode(self) -> str:
        if self.last_source_mode in SOURCE_SECTIONS:
            return self.last_source_mode
        return "time"

    def to_project_payload(self) -> dict:
        return workspace_to_payload(self._workspace)

    def restore_project_state(self, payload, *, project_path=None) -> list[str]:
        """Replace Board from a persisted payload. Store stays empty."""
        if self._shutdown:
            return []
        self._reset_page_runtime()
        self._drop_all_timers()
        self._disconnect_hooks()
        if _alive(self._store):
            self._store.clear()
        self._bindings.clear()
        self._unstable.clear()
        # Live source canvases persist across project reload. Clearing this
        # set would make `_watch_canvas_destroyed` reconnect `destroyed` on
        # the same QObject every open (receivers grow with N).
        self._result_refs.clear()
        self._result_generation.clear()
        self._digest_retries.clear()
        self._runtime.clear()
        self._presentation_revision.clear()
        workspace, warnings = normalize_workspace_payload(payload)
        self._workspace = workspace
        self._clear_placement_runtime()
        if project_path is not None and workspace.preview_sidecar is not None:
            opened = open_preview_sidecar(
                project_path,
                workspace_to_payload(workspace),
                workspace.preview_sidecar,
            )
            warnings.extend(
                f"{item.code}: {item.detail}" if item.detail else item.code
                for item in opened.warnings
            )
            if opened.ok and opened.images:
                self._queue_sidecar_images(opened.images)
        self.refresh_page()
        for item in warnings:
            logger.warning("UltraView project restore: %s", item)
        return list(warnings)

    def _queue_sidecar_images(self, images: tuple[SidecarImagePayload, ...]) -> None:
        self._sidecar_pending = list(images)
        self._prioritize_sidecar_queue()
        if self._sidecar_pending and not self._shutdown:
            self._sidecar_timer.start()

    def _prioritize_sidecar_queue(self) -> None:
        if not self._sidecar_pending:
            return
        active = set(all_refs(active_board(self._workspace)))
        self._sidecar_pending.sort(key=lambda item: 0 if item.ref in active else 1)

    def _on_sidecar_load_timeout(self) -> None:
        generation = self._sidecar_generation
        if self._shutdown or generation != self._sidecar_generation:
            self._sidecar_pending.clear()
            return
        batch = self._sidecar_pending[:_SIDECAR_LOAD_BATCH]
        self._sidecar_pending = self._sidecar_pending[_SIDECAR_LOAD_BATCH:]
        members = {
            ref for board in self._workspace.boards for ref in all_refs(board)
        }
        for payload in batch:
            if self._shutdown or generation != self._sidecar_generation:
                self._sidecar_pending.clear()
                return
            if payload.ref not in members:
                continue
            try:
                publish_sidecar_image(self._store, payload)
            except (OSError, RuntimeError, ValueError):
                continue
            self._push_preview(payload.ref)
        if (
            self._sidecar_pending
            and not self._shutdown
            and generation == self._sidecar_generation
        ):
            self._sidecar_timer.start()

    @property
    def board(self) -> UltraViewBoardState:
        return active_board(self._workspace)

    @property
    def workspace(self) -> UltraViewWorkspaceState:
        return self._workspace

    def save_preview_sidecar(self, project_path) -> list[str]:
        """Publish optional shared preview pixels before the project JSON commit."""
        if self._inactive():
            return []
        saved = save_preview_sidecar(
            project_path, workspace_to_payload(self._workspace), self._store
        )
        if saved.ok:
            set_workspace_preview_sidecar(self._workspace, saved.descriptor)
            return []
        # A new Save As must never retain a relative descriptor that points to
        # the original project's sibling sidecar directory.  Same-path saves
        # can keep their last known-good descriptor when the optional refresh
        # fails, preserving an already valid acceleration layer.
        existing = self._workspace.preview_sidecar
        if existing is None and isinstance(self._workspace.opaque_payload, dict):
            existing = self._workspace.opaque_payload.get("preview_sidecar")
        descriptor_path = existing.get("path") if isinstance(existing, dict) else None
        expected_prefix = f"{Path(project_path).name}.ultraview/"
        if not isinstance(descriptor_path, str) or not descriptor_path.startswith(expected_prefix):
            set_workspace_preview_sidecar(self._workspace, None)
        return [
            f"{item.code}: {item.detail}" if item.detail else item.code
            for item in saved.warnings
        ]

    def page(self):
        window = self._window
        if window is None:
            return None
        stack = getattr(window, "chart_stack", None)
        return getattr(stack, "page_ultraview", None)

    def attach(self) -> None:
        if self._inactive():
            return
        window = self._window
        if window is None:
            return
        # Page and stack hooks are independent: a late page() must still
        # connect even if the stack add-to-ultraview hook is already live.
        if not self._page_hooks:
            page = self.page()
            if page is not None:
                page.set_workspace(self._workspace)
                self._connect_page(page)
        if not self._stack_hooks:
            stack = getattr(window, "chart_stack", None)
            if stack is not None:
                signal = getattr(stack, "add_to_ultraview_requested", None)
                if signal is not None:
                    signal.connect(self.add_from_source_tab)
                    self._stack_hooks.append(
                        (stack, signal, self.add_from_source_tab)
                    )
        if not self._manager_hooks:
            self._connect_managers()
        self.refresh_page()

    def _connect_page(self, page) -> None:
        pairs = (
            (page.add_ref_requested, self._on_add_ref),
            (page.replace_slot_requested, self._on_replace_slot),
            (page.rebind_ref_requested, self._on_rebind_ref),
            (page.swap_slots_requested, self._on_swap_slots),
            (page.place_from_unplaced_requested, self._on_place_from_unplaced),
            (page.place_free_grid_from_unplaced_requested, self._on_place_free_grid_from_unplaced),
            (page.free_grid_insert_requested, self._on_free_grid_insert),
            (page.free_grid_replace_requested, self._on_free_grid_replace),
            (page.move_to_unplaced_requested, self._on_move_to_unplaced),
            (page.remove_ref_requested, self._on_remove_ref),
            (page.open_source_requested, self.open_source),
            (page.sync_requested, self.sync_preview),
            (page.focus_requested, self._on_focus),
            (page.layout_changed, self._on_layout),
            (page.ratio_nudge_requested, self._on_ratio_nudge),
            (page.presentation_toggled, self._on_presentation),
            (page.compare_filter_changed, self._on_compare_filter),
            (page.copy_board_requested, self.copy_board_to_clipboard),
            (page.copy_card_image_requested, self._on_copy_card),
            (page.export_png_requested, self.choose_and_export_png),
            (page.board_name_changed, self._on_board_name),
            (page.create_board_requested, self._on_create_board),
            (page.duplicate_board_requested, self._on_duplicate_board),
            (page.rename_board_requested, self._on_rename_board),
            (page.delete_board_requested, self._on_delete_board),
            (page.reorder_board_requested, self._on_reorder_board),
            (page.select_board_requested, self._on_select_board),
            (page.free_grid_toggled, self._on_free_grid_toggled),
            (page.free_grid_geometry_requested, self._on_free_grid_geometry),
            (page.free_grid_group_geometry_requested, self._on_free_grid_group_geometry),
            (page.free_grid_preset_requested, self._on_free_grid_preset),
            (page.free_grid_autofit_requested, self._on_free_grid_autofit),
            (page.organize_free_grid_requested, self._on_organize_free_grid),
            (page.free_grid_undo_requested, self._on_free_grid_undo),
            (page.free_grid_redo_requested, self._on_free_grid_redo),
            (page.show_titles_toggled, self._on_show_titles),
            (page.show_sources_toggled, self._on_show_sources),
            (page.show_card_actions_toggled, self._on_show_card_actions),
            (page.feedback_requested, self._on_page_feedback),
            (page.camera_settled, self._on_camera_settled),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._page_hooks.append((page, signal, slot))
        page.resolve_insert_span = self._insert_span_for_drag

    def _connect_managers(self) -> None:
        if self._manager_hooks:
            return
        for _section, manager in self._iter_managers():
            signal = getattr(manager, "views_changed", None)
            if signal is None:
                continue
            signal.connect(self._on_manager_views_changed)
            self._manager_hooks.append(
                (manager, signal, self._on_manager_views_changed)
            )

    def _on_manager_views_changed(self, *_args) -> None:
        if self._inactive():
            return
        self.refresh_page(            )

    def capture_leaving_source(self, section: str) -> None:
        window = self._window
        if window is None or section not in SOURCE_SECTIONS:
            return
        if section == "time":
            self._capture_visible_time_refs("leaving-source-for-ultraview")
            return
        self.request_visible_section_capture(section, "leaving-source-for-ultraview")

    def _capture_visible_time_refs(self, reason: str) -> None:
        window = self._window
        stack = getattr(window, "chart_stack", None)
        manager = getattr(window, "view_manager", None)
        if stack is None or manager is None or not manager.views:
            return
        active = manager.get(manager.active)
        refs = [UltraViewRef("time", active.view_id)]
        if callable(getattr(stack, "split_active", None)) and stack.split_active():
            partner_idx = manager.partner_for(manager.active)
            if partner_idx is not None:
                partner = manager.get(partner_idx)
                refs.append(UltraViewRef("time", partner.view_id))
        for ref in refs:
            widget = self._time_canvas_for_ref(ref)
            if widget is None:
                continue
            self.bind_canvas(widget, ref)
            self.request_capture(ref, widget, reason)

    def add_from_source_tab(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        window = self._window
        stack = getattr(window, "chart_stack", None) if window is not None else None
        current_mode = getattr(stack, "current_mode", lambda: "")()
        if current_mode == section:
            if section == "time":
                widget = self._time_canvas_for_ref(ref)
                if widget is not None:
                    reason = (
                        "add-from-tab-split"
                        if widget is not getattr(stack, "canvas_time", None)
                        else "add-from-tab"
                    )
                    self.bind_canvas(widget, ref)
                    self.request_capture(ref, widget, reason)
            else:
                current = self._active_ref(section)
                if current == ref:
                    widget = self._visible_widget_for(section)
                    if widget is not None:
                        self.bind_canvas(widget, ref)
                        self.request_capture(ref, widget, "add-from-tab")
        page = self.page()
        anchor = (
            page.current_free_grid_insert_anchor() if page is not None else None
        )
        self._apply_add_ref(ref, preferred_anchor=anchor)

    def _time_canvas_for_ref(self, ref: UltraViewRef):
        """Resolve time-domain canvas by pane ownership, not click-focus.

        Active View ↔ primary ``canvas_time``; split partner ↔ secondary.
        Focused pane is ignored so "加入总览" cannot publish the wrong View.
        """
        if ref is None or ref.section != "time":
            return None
        window = self._window
        stack = getattr(window, "chart_stack", None) if window is not None else None
        manager = getattr(window, "view_manager", None) if window is not None else None
        if stack is None or manager is None or not manager.views:
            return None
        active = manager.get(manager.active)
        if str(getattr(active, "view_id", "")) == ref.view_id:
            return getattr(stack, "canvas_time", None)
        if not callable(getattr(stack, "split_active", None)) or not stack.split_active():
            return None
        partner_idx = manager.partner_for(manager.active)
        if partner_idx is None:
            return None
        partner = manager.get(partner_idx)
        if str(getattr(partner, "view_id", "")) != ref.view_id:
            return None
        secondary = getattr(stack, "secondary_canvas", None)
        return secondary() if callable(secondary) else None

    def _navigate_to_view(
        self, section: str, view_id: str, *, raise_window: bool = True
    ) -> bool:
        """Call ``MainWindow.navigate_to_view``; tolerate 2-arg test fakes."""
        window = self._window
        navigate = getattr(window, "navigate_to_view", None) if window is not None else None
        if not callable(navigate):
            return False
        try:
            return bool(navigate(section, view_id, raise_window=raise_window))
        except TypeError:
            return bool(navigate(section, view_id))

    def open_source(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        if self._navigate_to_view(section, view_id, raise_window=True):
            return
        page = self.page()
        if page is not None:
            page.arm_replacement(section, view_id)

    def sync_preview(self, section: str, view_id: str) -> None:
        """Recapture one Board card from the live source View. Never recomputes.

        Hidden sources navigate then grab. Multiple syncs in one turn are
        serialized so the last ``navigate_to_view`` cannot steal an earlier
        canvas before its grab runs. Sync navigation does not raise the
        Analyzer; the Board stays in front and is raised only after the
        queue drains.
        """
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref == self._sync_current_ref or ref in self._sync_work_queue:
            return
        self._sync_work_queue.append(ref)
        self._pump_sync_work()

    def _pump_sync_work(self) -> None:
        if self._inactive() or self._sync_nav_busy:
            return
        if not self._sync_work_queue:
            if self._sync_nav_needs_raise:
                self._sync_nav_needs_raise = False
                self._raise_ultraview_sheet()
            return
        ref = self._sync_work_queue.pop(0)
        self._sync_nav_busy = True
        self._sync_current_ref = ref
        widget = self._sync_capture_widget(ref)
        if widget is not None:
            self._request_user_sync(ref, widget)
            self._finish_sync_item(ref)
            return
        if not self._ref_exists(ref):
            self._toast("找不到原 View，无法同步", "warning")
            self._finish_sync_item(ref, wait_capture=False)
            return
        if self._navigate_to_view(ref.section, ref.view_id, raise_window=False):
            self._sync_nav_needs_raise = True
            QTimer.singleShot(0, partial(self._sync_preview_after_navigate, ref))
            return
        self._toast("请先打开原 View 再同步", "warning")
        self._finish_sync_item(ref, wait_capture=False)

    def _sync_preview_after_navigate(self, ref) -> None:
        try:
            if self._inactive() or ref is None:
                return
            widget = self._sync_capture_widget(ref)
            if widget is None:
                widget = self._visible_widget_for(ref.section)
                if widget is not None and self._active_ref(ref.section) == ref:
                    self.bind_canvas(widget, ref)
                else:
                    widget = None
            if widget is None:
                self._toast("请先打开原 View 再同步", "warning")
                return
            self._request_user_sync(ref, widget)
        finally:
            self._finish_sync_item(ref)

    def _finish_sync_item(self, ref, *, wait_capture: bool = True) -> None:
        coord_ref = weakref.ref(self)

        def _advance():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            if wait_capture and any(key[0] == ref for key in coord._queued):
                QTimer.singleShot(0, _advance)
                return
            if coord._sync_current_ref == ref:
                coord._sync_current_ref = None
            coord._sync_nav_busy = False
            coord._pump_sync_work()

        QTimer.singleShot(0, _advance)

    def _clear_sync_work(self) -> None:
        self._sync_work_queue.clear()
        self._sync_current_ref = None
        self._sync_nav_busy = False
        self._sync_nav_needs_raise = False

    def _sync_capture_widget(self, ref):
        candidates = []
        bound = self._bound_widget_for(ref)
        if bound is not None:
            candidates.append(bound)
        if self._active_ref(ref.section) == ref:
            visible = self._visible_widget_for(ref.section)
            if visible is not None and visible not in candidates:
                candidates.append(visible)
        for widget in candidates:
            if widget is None or not _alive(widget):
                continue
            try:
                if widget.isVisible():
                    return widget
            except RuntimeError:
                continue
        return None

    def _request_user_sync(self, ref, widget) -> None:
        if widget is None or not _alive(widget):
            self._toast("找不到原 View，无法同步", "warning")
            return
        try:
            if not widget.isVisible():
                self._toast("请先打开原 View 再同步", "warning")
                return
        except RuntimeError:
            self._toast("找不到原 View，无法同步", "warning")
            return
        if not self._widget_has_any_real_result(widget):
            self._toast("原 View 尚无可用结果", "warning")
            return
        digest = self.current_digest_for(ref)
        if digest is None:
            self._toast("无法读取当前图面，稍后再试", "warning")
            return
        self.bind_canvas(widget, ref)
        if self._has_current_preview(ref, digest) and not self._needs_focus_recapture(ref):
            self._push_preview(ref)
            return
        self.request_capture(ref, widget, "user-sync")

    def _raise_ultraview_sheet(self) -> None:
        window = self._window
        sheet = getattr(window, "_ultraview_sheet", None) if window is not None else None
        if sheet is None or not _alive(sheet):
            return
        try:
            sheet.raise_()
            sheet.activateWindow()
        except RuntimeError:
            return

    def refresh_page(self) -> None:
        if self._inactive():
            return
        self._sync_entry_content_marker()
        page = self.page()
        if page is None:
            return
        board = active_board(self._workspace)
        batch = getattr(page, "projection_batch", None)
        with batch() if callable(batch) else nullcontext():
            # Library chrome (name/color) must be current before set_board
            # projects cards. Preview-record no-op must not freeze tab color.
            self._refresh_library(page)
            page.set_workspace(self._workspace)
            self.set_pinned_from_board(board)
            for ref in membership_set(board):
                self._push_preview(ref)

    def _sync_entry_content_marker(self) -> None:
        """Keep each source-rail entry honest about configured Board cards."""
        window = self._window
        chart_stack = getattr(window, "chart_stack", None) if window is not None else None
        sync = getattr(chart_stack, "set_ultraview_has_content", None)
        if callable(sync):
            sync(any(all_refs(board) for board in self._workspace.boards))

    def _refresh_library(self, page) -> None:
        rows = []
        for section, manager in self._iter_managers():
            for state in list(manager.views):
                ref = UltraViewRef(section, str(state.view_id))
                record = self._store.get(ref)
                exists = True
                digest = self.current_digest_for(ref)
                image_valid = record is not None and PreviewStore.image_valid(
                    getattr(record, "image", None)
                )
                captured = getattr(record, "captured_digest", None) if record else None
                rows.append(LibraryRow(
                    section=section,
                    view_id=str(state.view_id),
                    name=str(getattr(state, "name", "") or ""),
                    tab_color=str(getattr(state, "tab_color", "") or ""),
                    source_summary=self._checked_summary(state),
                    on_board=any(ref in membership_set(board) for board in self._workspace.boards),
                    status=derive_preview_status(
                        exists, image_valid, captured, digest
                    ),
                ))
        page.set_library_rows(rows)

    def _iter_managers(self):
        window = self._window
        if window is None:
            return
        time_manager = getattr(window, "view_manager", None)
        if time_manager is not None:
            yield "time", time_manager
        managers = getattr(window, "analysis_managers", None) or {}
        for section in SOURCE_SECTIONS:
            if section == "time":
                continue
            manager = managers.get(section)
            if manager is not None:
                yield section, manager

    def _checked_summary(self, state) -> str:
        checked = list(getattr(state, "checked", None) or [])
        names = []
        for item in checked[:3]:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                names.append(str(item[1]))
            else:
                names.append(str(item))
        extra = len(checked) - 3
        text = ", ".join(names)
        if extra > 0:
            text = f"{text} +{extra}"
        return text

    def _ref_exists(self, ref: UltraViewRef) -> bool:
        if ref.section == "time":
            return self._time_state(self._window, ref.view_id) is not None
        resolved = self._analysis_state(self._window, ref.section, ref.view_id)
        return resolved is not None

    def _push_preview(self, ref: UltraViewRef, *, usable: bool = True) -> None:
        page = self.page()
        if page is None:
            return
        record = self._store.get(ref)
        exists = self._ref_exists(ref)
        digest = (
            self.current_digest_for(ref) if exists and usable else None
        )
        image_valid = record is not None and PreviewStore.image_valid(
            getattr(record, "image", None)
        )
        captured = getattr(record, "captured_digest", None) if record else None
        status = derive_preview_status(exists, image_valid, captured, digest)
        apply = getattr(page, "apply_preview_and_status", None)
        if callable(apply):
            apply(ref, record, status, exists)
        else:
            if record is not None:
                page.set_preview(ref, record)
            page.set_ref_status(ref, status, exists)
        if image_valid and any(ref in placed_ref_set(board) for board in self._workspace.boards):
            self._store.touch(ref)
        self._refresh_open_focus(ref)
        if image_valid and usable:
            self._maybe_apply_pending_auto_aspect(ref)

    def _refresh_open_focus(self, ref: UltraViewRef) -> None:
        page = self.page()
        if page is None:
            return
        layer = page.focus_layer()
        if not layer.isVisible():
            return
        current = layer.current_ref()
        if current != (ref.section, ref.view_id):
            return
        page.show_focus(ref.section, ref.view_id)
        digest = self.current_digest_for(ref)
        page.set_focus_syncing(
            digest is None or not self._has_current_preview(ref, digest)
        )

    def presentation_revision_for(self, ref: UltraViewRef) -> int:
        return int(self._presentation_revision.get(ref, 0) or 0)

    def bump_presentation_revision(self, ref: UltraViewRef) -> int:
        """Session-only counter for digest-external pixel-affecting source state.

        Not persisted, not added to presentation_digest.  Temporary inspect
        freshness is digest + this revision.
        """
        next_value = int(self._presentation_revision.get(ref, 0) or 0) + 1
        self._presentation_revision[ref] = next_value
        return next_value

    def _on_store_images_dropped(self, refs) -> None:
        if self._inactive():
            return
        for ref in refs or ():
            if isinstance(ref, UltraViewRef):
                self._push_preview(ref)

    def _after_board_mutation(self) -> None:
        if self._inactive():
            return
        mark_workspace_mutated(self._workspace)
        self.refresh_page()

    def _apply_add_ref(
        self, ref: UltraViewRef, *, preferred_anchor: GridAnchor | None = None
    ) -> None:
        if self._inactive():
            return
        page = self.page()
        board = active_board(self._workspace)
        if ref in membership_set(board):
            if page is not None:
                page.select_ref(ref)
            return
        image_size = self._preview_image_size(ref)
        span = None
        if board.layout_mode == LAYOUT_MODE_FREE_GRID:
            span = self._insert_span_for_ref(board, ref)
        before = self._placement_snapshot(board)
        warnings = add_ref(
            board, ref, preferred_anchor=preferred_anchor, span=span
        )
        if warnings and warnings[0] == "membership_limit":
            self._toast(text_for_key(MEMBERSHIP_CAP), "warning")
            return
        placed_in_tray = (
            board.layout_mode == LAYOUT_MODE_FREE_GRID and ref in board.unplaced
        )
        if placed_in_tray:
            self._toast(text_for_key(PLACED_CAP_TO_TRAY), "info")
        self._commit_grid_change(board, before, [])
        if (
            board.layout_mode == LAYOUT_MODE_FREE_GRID
            and image_size is None
        ):
            item = free_grid_placement_for(board, ref)
            if item is not None:
                self._register_pending_auto_aspect(board, ref, item.rect)

    def _on_add_ref(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            page = self.page()
            anchor = (
                page.current_free_grid_insert_anchor() if page is not None else None
            )
            self._apply_add_ref(ref, preferred_anchor=anchor)

    def _on_replace_slot(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        replace_slot(board, slot_id, ref)
        self._commit_grid_change(board, before, [])

    def _on_rebind_ref(
        self,
        old_section: str,
        old_view_id: str,
        new_section: str,
        new_view_id: str,
    ) -> None:
        old_ref = parse_ref_payload({"section": old_section, "view_id": old_view_id})
        new_ref = parse_ref_payload({"section": new_section, "view_id": new_view_id})
        if old_ref is None or new_ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        rebind_ref(board, old_ref, new_ref)
        self._cancel_pending_for_ref(board.board_id, old_ref)
        self._commit_grid_change(board, before, [])

    def _on_swap_slots(self, slot_a: str, slot_b: str) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        swap_slots(board, slot_a, slot_b)
        self._commit_grid_change(board, before, [])

    def _on_place_from_unplaced(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        place_from_unplaced(board, slot_id, ref)
        self._commit_grid_change(board, before, [])

    def _on_place_free_grid_from_unplaced(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        page = self.page()
        anchor = (
            page.current_free_grid_insert_anchor() if page is not None else None
        )
        board = active_board(self._workspace)
        self._place_unplaced_on_free_grid(
            board, ref, preferred_anchor=anchor
        )

    def _on_free_grid_insert(
        self, section: str, view_id: str, anchor: GridAnchor
    ) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        page = self.page()
        if ref in membership_set(board):
            if page is not None:
                page.select_ref(ref)
            return
        if ref in board.unplaced:
            self._place_unplaced_on_free_grid(
                board, ref, preferred_anchor=anchor
            )
            return
        self._apply_add_ref(ref, preferred_anchor=anchor)

    def _on_free_grid_replace(
        self,
        target_section: str,
        target_view_id: str,
        source_section: str,
        source_view_id: str,
    ) -> None:
        target = parse_ref_payload({"section": target_section, "view_id": target_view_id})
        new_ref = parse_ref_payload({"section": source_section, "view_id": source_view_id})
        if target is None or new_ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        warnings = replace_free_grid_ref(board, target, new_ref)
        if not warnings:
            self._cancel_pending_for_ref(board.board_id, target)
        self._commit_grid_change(board, before, warnings)

    def _on_move_to_unplaced(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        move_to_unplaced(board, ref)
        self._commit_grid_change(board, before, [])

    def _on_remove_ref(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        if ref not in membership_set(board):
            return
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        warnings = remove_ref(board, ref)
        self._commit_grid_change(board, before, warnings)
        if not warnings:
            self._toast(text_for_key(REMOVED_FROM_BOARD), "info")

    def _on_layout(self, layout_id: str) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        warnings = set_layout(board, str(layout_id))
        self._cancel_pending_for_board(board.board_id)
        self._bump_layout_revision(board.board_id)
        self._toast_layout_warnings(warnings)
        if not self._record_grid_transition(board, before):
            self._after_board_mutation()

    def _on_ratio_nudge(self, steps: int) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        nudge_ratio(board, int(steps))
        self._commit_grid_change(board, before, [])

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if enabled and board.layout_mode != LAYOUT_MODE_FREE_GRID:
            template_to_free_grid(board)
        elif not enabled and board.layout_mode == LAYOUT_MODE_FREE_GRID:
            free_grid_to_template(board, best_template_for(len(board.free_grid)))
        else:
            return
        self._cancel_pending_for_board(board.board_id)
        self._bump_layout_revision(board.board_id)
        if not self._record_grid_transition(board, before):
            self._after_board_mutation()

    def _on_free_grid_geometry(
        self,
        section: str,
        view_id: str,
        column: int,
        row: int,
        column_span: int,
        row_span: int,
        _reason: str,
    ) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        wanted = GridRect(int(column), int(row), int(column_span), int(row_span))
        current = free_grid_placement_for(board, ref)
        if current is None:
            return
        span_changed = (
            current.rect.column_span != wanted.column_span
            or current.rect.row_span != wanted.row_span
        )
        warnings = set_free_grid_rect(board, ref, wanted)
        if not warnings and span_changed:
            self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_group_geometry(self, updates) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        parsed: list[tuple[UltraViewRef, GridRect]] = []
        for item in tuple(updates or ()):
            if not isinstance(item, (tuple, list)) or len(item) != 6:
                return
            section, view_id, column, row, column_span, row_span = item
            ref = parse_ref_payload({"section": section, "view_id": view_id})
            if ref is None:
                return
            parsed.append(
                (
                    ref,
                    GridRect(int(column), int(row), int(column_span), int(row_span)),
                )
            )
        if not parsed:
            return
        current = {item.ref: item.rect for item in board.free_grid}
        span_changed = [
            ref
            for ref, wanted in parsed
            if current.get(ref) is not None
            and (
                current[ref].column_span != wanted.column_span
                or current[ref].row_span != wanted.row_span
            )
        ]
        warnings = set_free_grid_rects(board, parsed)
        if not warnings:
            for ref in span_changed:
                self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_preset(self, section: str, view_id: str, preset: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if not any(item_ref == ref for item_ref, _rect in before.free_grid):
            return
        warnings = apply_free_grid_preset(board, ref, preset)
        if not warnings:
            self._cancel_pending_for_ref(board.board_id, ref)
        self._commit_grid_change(board, before, warnings)

    def _on_free_grid_autofit(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        if board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return
        item = free_grid_placement_for(board, ref)
        if item is None:
            return
        record = self._store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if not PreviewStore.image_valid(image):
            self._toast("没有可用预览，无法按原图比例调整", "warning")
            return
        before = self._placement_snapshot(board)
        self._cancel_pending_for_ref(board.board_id, ref)
        metrics = screen_grid_metrics(board.free_grid)
        wanted = fit_rect_for_aspect(
            item.rect, (int(image.width()), int(image.height())), metrics
        )
        if wanted == item.rect:
            return
        plan = plan_layout(
            board.free_grid,
            ref,
            wanted,
            LAYOUT_RESIZE,
        )
        if not plan.accepted:
            self._toast("目标位置与其他卡片重叠", "warning")
            return
        updates = plan.committed_updates()
        if not updates:
            return
        warnings = set_free_grid_rects(board, updates)
        self._commit_grid_change(board, before, warnings)

    def _on_organize_free_grid(self) -> None:
        board = active_board(self._workspace)
        before = self._placement_snapshot(board)
        if not organize_free_grid(board):
            self._record_grid_transition(board, before)

    def _grid_history(self, board: UltraViewBoardState) -> _GridHistory:
        return self._grid_histories.setdefault(board.board_id, _GridHistory([], []))

    @staticmethod
    def _placement_snapshot(board: UltraViewBoardState) -> BoardPlacementSnapshot:
        return capture_board_placement(board)

    def _record_grid_transition(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
    ) -> bool:
        after = self._placement_snapshot(board)
        if after == before:
            return False
        history = self._grid_history(board)
        history.undo.append(_GridHistoryEntry(before, after))
        overflow = len(history.undo) - _PLACEMENT_HISTORY_CAP
        if overflow > 0:
            del history.undo[:overflow]
        history.redo.clear()
        self._clear_pending_merge_flags()
        self._after_board_mutation()
        return True

    def _commit_grid_change(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
        warnings: list[str],
    ) -> None:
        if warnings:
            self._toast_grid_warnings(warnings)
            return
        self._record_grid_transition(board, before)

    def _toast_grid_warnings(self, warnings: list[str]) -> None:
        codes = {item.split(":", 1)[0] for item in warnings}
        if "grid_collision" in codes:
            self._toast("目标位置与其他卡片重叠", "warning")
            return
        if "grid_full" in codes:
            self._toast(text_for_key(PLACED_CAP_STILL_UNPLACED), "info")
            return
        if "membership_limit" in codes:
            self._toast(text_for_key(MEMBERSHIP_CAP), "warning")
            return
        if warnings:
            self._toast(str(warnings[0]), "warning")

    def _toast_layout_warnings(self, warnings: list[str]) -> None:
        for item in warnings:
            code, _, detail = item.partition(": ")
            if code == "tray_refilled":
                self._toast(f"已从托盘补位 {detail} 张", "info")
            elif code == "layout_overflow":
                self._toast(f"{detail} 张已移入未放置", "info")

    def _discard_stale_grid_history(self, history: _GridHistory) -> None:
        history.undo.clear()
        history.redo.clear()

    @staticmethod
    def _apply_grid_snapshot(
        board: UltraViewBoardState,
        snapshot: BoardPlacementSnapshot,
    ) -> bool:
        return apply_board_placement(board, snapshot)

    def _on_free_grid_undo(self) -> None:
        board = active_board(self._workspace)
        history = self._grid_histories.get(board.board_id)
        if history is None or not history.undo:
            return
        entry = history.undo.pop()
        if not self._apply_grid_snapshot(board, entry.before):
            history.undo.append(entry)
            return
        self._cancel_pending_for_board(board.board_id)
        history.redo.append(entry)
        self._after_board_mutation()

    def _on_free_grid_redo(self) -> None:
        board = active_board(self._workspace)
        history = self._grid_histories.get(board.board_id)
        if history is None or not history.redo:
            return
        entry = history.redo.pop()
        if not self._apply_grid_snapshot(board, entry.after):
            history.redo.append(entry)
            return
        self._cancel_pending_for_board(board.board_id)
        history.undo.append(entry)
        self._after_board_mutation()

    def _preview_image_size(self, ref: UltraViewRef) -> tuple[int, int] | None:
        record = self._store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if not PreviewStore.image_valid(image):
            return None
        return (int(image.width()), int(image.height()))

    def _insert_span_for_ref(
        self, board: UltraViewBoardState, ref: UltraViewRef
    ) -> tuple[int, int] | None:
        image_size = self._preview_image_size(ref)
        if image_size is None:
            return None
        return self._fitted_insert_span(board, image_size)

    def _insert_span_for_drag(
        self, section: str, view_id: str
    ) -> tuple[int, int] | None:
        if self._inactive():
            return None
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return None
        return self._insert_span_for_ref(active_board(self._workspace), ref)

    def _place_unplaced_on_free_grid(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        *,
        preferred_anchor: GridAnchor | None,
    ) -> None:
        span = self._insert_span_for_ref(board, ref)
        before = self._placement_snapshot(board)
        warnings = place_free_grid_from_unplaced(
            board, ref, preferred_anchor=preferred_anchor, span=span
        )
        self._commit_grid_change(board, before, warnings)
        if warnings:
            return
        if span is None:
            item = free_grid_placement_for(board, ref)
            if item is not None:
                self._register_pending_auto_aspect(board, ref, item.rect)

    def _fitted_insert_span(
        self, board: UltraViewBoardState, image_size: tuple[int, int]
    ) -> tuple[int, int]:
        column_span, row_span = free_grid_default_span(board)
        max_rect = GridRect(0, 0, column_span, row_span)
        fitted = fit_rect_for_aspect(
            max_rect, image_size, screen_grid_metrics(board.free_grid)
        )
        return (fitted.column_span, fitted.row_span)

    def _current_layout_revision(self, board_id: str) -> int:
        return int(self._layout_revision.get(str(board_id), 0))

    def _bump_layout_revision(self, board_id: str) -> None:
        key = str(board_id)
        self._layout_revision[key] = self._current_layout_revision(key) + 1

    def _register_pending_auto_aspect(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        inserted_rect: GridRect,
    ) -> None:
        self._pending_auto_aspect[(board.board_id, ref)] = _PendingAutoAspect(
            board_id=board.board_id,
            ref=ref,
            inserted_rect=inserted_rect,
            layout_revision=self._current_layout_revision(board.board_id),
            merge_add=True,
        )

    def _cancel_pending_for_ref(self, board_id: str, ref: UltraViewRef) -> None:
        self._pending_auto_aspect.pop((str(board_id), ref), None)

    def _cancel_pending_for_board(self, board_id: str) -> None:
        key = str(board_id)
        self._pending_auto_aspect = {
            token_key: token
            for token_key, token in self._pending_auto_aspect.items()
            if token.board_id != key
        }

    def _clear_pending_merge_flags(self) -> None:
        self._pending_auto_aspect = {
            token_key: replace(token, merge_add=False) if token.merge_add else token
            for token_key, token in self._pending_auto_aspect.items()
        }

    def _clear_placement_runtime(self) -> None:
        self._grid_histories.clear()
        self._pending_auto_aspect.clear()
        self._layout_revision.clear()

    def _drop_board_placement_runtime(self, board_id: str) -> None:
        key = str(board_id)
        self._grid_histories.pop(key, None)
        self._layout_revision.pop(key, None)
        self._cancel_pending_for_board(key)

    def _maybe_apply_pending_auto_aspect(self, ref: UltraViewRef) -> None:
        if self._inactive():
            return
        matching = [
            token
            for token in tuple(self._pending_auto_aspect.values())
            if token.ref == ref
        ]
        for token in matching:
            self._apply_one_pending_auto_aspect(token)

    def _apply_one_pending_auto_aspect(self, token: _PendingAutoAspect) -> None:
        self._pending_auto_aspect.pop((token.board_id, token.ref), None)
        board = next(
            (
                item
                for item in self._workspace.boards
                if item.board_id == token.board_id
            ),
            None,
        )
        if board is None or board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return
        if token.layout_revision != self._current_layout_revision(board.board_id):
            return
        item = free_grid_placement_for(board, token.ref)
        if item is None:
            return
        if (
            item.rect.column_span != token.inserted_rect.column_span
            or item.rect.row_span != token.inserted_rect.row_span
        ):
            return
        image_size = self._preview_image_size(token.ref)
        if image_size is None:
            return
        cap = GridRect(
            item.rect.column,
            item.rect.row,
            token.inserted_rect.column_span,
            token.inserted_rect.row_span,
        )
        wanted = fit_rect_for_aspect(
            cap, image_size, screen_grid_metrics(board.free_grid)
        )
        if wanted == item.rect:
            return
        warnings = set_free_grid_rect(board, token.ref, wanted)
        if warnings:
            return
        after = self._placement_snapshot(board)
        if token.merge_add:
            history = self._grid_histories.get(board.board_id)
            if history is not None and history.undo:
                last = history.undo[-1]
                history.undo[-1] = _GridHistoryEntry(last.before, after)
                history.redo.clear()
        self._after_board_mutation()

    def _on_focus(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        self._store.touch(ref)
        page = self.page()
        digest = self.current_digest_for(ref)
        stale = digest is None or not self._has_current_preview(ref, digest)
        self.set_pinned_from_board(active_board(self._workspace))
        if self._needs_focus_recapture(ref):
            stale = True
        if page is not None:
            page.set_focus_syncing(stale)
        if not stale:
            return
        widget = self._widget_for_ref(ref)
        if widget is None:
            candidate = self._visible_widget_for(ref.section)
            if candidate is not None and self._active_ref(ref.section) == ref:
                widget = candidate
        if widget is None:
            if page is not None:
                page.set_focus_syncing(False)
            return
        self.bind_canvas(widget, ref)
        self.request_capture(ref, widget, "focus-inspect")

    def _on_page_feedback(self, message: str) -> None:
        if self._inactive():
            return
        text = str(message or "").strip()
        if text:
            self._toast(text, "info")

    def _on_copy_card(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self.copy_card_to_clipboard(ref)

    def _on_board_name(self, name: str) -> None:
        if self._inactive():
            return
        cleaned = str(name or "").strip() or DEFAULT_BOARD_NAME
        board = active_board(self._workspace)
        if board.name == cleaned:
            return
        warnings = rename_board(self._workspace, board.board_id, cleaned)
        if warnings:
            for warning in warnings:
                logger.warning("UltraView board rename: %s", warning)
            return
        self._after_board_mutation()

    def _on_create_board(self) -> None:
        if create_board(self._workspace) is None:
            self._toast("最多创建 20 个 Board", "info")
            return
        self._after_board_mutation()

    def _on_duplicate_board(self, board_id: str) -> None:
        if len(self._workspace.boards) >= MAX_UI_BOARDS:
            self._toast("最多创建 20 个 Board", "info")
            return
        if duplicate_board(self._workspace, board_id) is not None:
            self._after_board_mutation()

    def _on_rename_board(self, board_id: str, name: str) -> None:
        if not rename_board(self._workspace, board_id, name):
            self._after_board_mutation()

    def _on_delete_board(self, board_id: str) -> None:
        warnings = delete_board(self._workspace, board_id)
        if warnings and warnings[0] == "last_board_retained":
            self._toast("至少保留一个 Board", "info")
            return
        self._drop_board_placement_runtime(str(board_id))
        self._after_board_mutation()

    def _on_reorder_board(self, board_id: str, index: int) -> None:
        warnings = reorder_board(self._workspace, board_id, index)
        # Success is ``[]``. Do not refresh on success: QTabBar already moved
        # the tab, and rebuilding inside ``tabMoved`` crashes. Failure resyncs
        # from workspace; BoardSwitcher defers that rebuild off the signal.
        if warnings:
            self._after_board_mutation()

    def _on_select_board(self, board_id: str) -> None:
        if not set_active_board(self._workspace, board_id):
            self._prioritize_sidecar_queue()
            self._after_board_mutation()

    def copy_board_to_clipboard(self) -> bool:
        image = self._compose_or_toast(scale=1, action="复制整板图")
        if image is None:
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._export_failed("clipboard_failed", "无法访问剪贴板")
            return False
        clipboard.setImage(image)
        self._toast("已复制整板图", "success")
        return True

    def copy_card_to_clipboard(self, ref: UltraViewRef) -> bool:
        if self._inactive():
            return False
        record = self._store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if not PreviewStore.image_valid(image):
            self._export_failed("missing_preview", "该卡片尚无可用预览")
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._export_failed("clipboard_failed", "无法访问剪贴板")
            return False
        clipboard.setImage(image)
        self._store.touch(ref)
        self._toast("已复制卡片图", "success")
        return True

    def choose_and_export_png(self, scale: int = 1) -> bool:
        if self._inactive():
            return False
        factor = 1 if int(scale) <= 1 else 2
        path, _filter = QFileDialog.getSaveFileName(
            self._feedback_host(),
            f"导出 PNG {factor}×",
            "",
            "PNG (*.png)",
        )
        if not path:
            return False
        if not str(path).lower().endswith(".png"):
            path = str(path) + ".png"
        return self.export_png_to_path(path, scale=factor)

    def export_png_to_path(self, path, *, scale: int = 1) -> bool:
        image = self._compose_or_toast(scale=scale, action="导出 PNG")
        if image is None:
            return False
        try:
            save_composed_png(image, path)
        except ComposeError as exc:
            self._export_failed(exc.code, exc.message)
            return False
        self._toast(f"已导出 PNG {1 if int(scale) <= 1 else 2}×", "success")
        return True

    def compose_board_image(self, scale: int = 1) -> QImage:
        return self._compose_board(scale)

    def _compose_board(self, scale: int) -> QImage:
        records = {}
        statuses = {}
        board = active_board(self._workspace)
        for ref in all_refs(board):
            record = self._store.get(ref)
            records[ref] = record
            if record is not None and PreviewStore.image_valid(getattr(record, "image", None)):
                if ref in placed_ref_set(board):
                    self._store.touch(ref)
            exists = self._ref_exists(ref)
            digest = self.current_digest_for(ref) if exists else None
            image_valid = record is not None and PreviewStore.image_valid(
                getattr(record, "image", None)
            )
            captured = getattr(record, "captured_digest", None) if record else None
            statuses[ref] = derive_preview_status(exists, image_valid, captured, digest)
        return compose_board(board, records, statuses, scale=scale)

    def _compose_or_toast(self, *, scale: int, action: str) -> QImage | None:
        if self._inactive():
            return None
        try:
            return self._compose_board(scale)
        except ComposeError as exc:
            self._export_failed(exc.code, f"{action}失败：{exc.message}")
            return None

    def _export_failed(self, code: str, message: str) -> None:
        logger.warning("UltraView export %s: %s", code, message)
        self._toast(message, "warning")

    def _feedback_host(self):
        """Visible Board window when the page lives there; else Analyzer."""
        page = self.page()
        if page is not None:
            try:
                host = page.window()
            except RuntimeError:
                host = None
            if host is not None and _alive(host):
                try:
                    if host.isVisible() and host is not self._window:
                        return host
                except RuntimeError:
                    pass
        if self._sheet_visible():
            window = self._window
            sheet = getattr(window, "_ultraview_sheet", None) if window is not None else None
            if sheet is not None and _alive(sheet):
                return sheet
        return self._window

    def _toast(self, message: str, level: str) -> None:
        host = self._feedback_host()
        toast = getattr(host, "toast", None) if host is not None else None
        if callable(toast):
            toast(message, level)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        page = self.page()
        if page is not None:
            page.arm_replacement(section, view_id)

    def _on_compare_filter(self, filter_id: str) -> None:
        if self._inactive():
            return
        page = self.page()
        wanted = str(filter_id or COMPARE_FILTER_ALL)
        if page is not None and page.compare_filter() != wanted:
            page.set_compare_filter(wanted)

    def _on_show_titles(self, checked: bool) -> None:
        set_presentation_flags(active_board(self._workspace), show_titles=checked)
        self._after_board_mutation()

    def _on_show_sources(self, checked: bool) -> None:
        set_presentation_flags(active_board(self._workspace), show_sources=checked)
        self._after_board_mutation()

    def _on_show_card_actions(self, checked: bool) -> None:
        set_workspace_show_card_actions(self._workspace, checked)
        # This preference only changes UltraView chrome.  Do not route it
        # through board mutation/capture/viewport paths.
        self.refresh_page()

    def _on_shift_slot(self, section: str, view_id: str, delta: int) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        placement = placement_for(board, ref)
        if placement is None:
            return
        slots = layout_slots(board.layout_id)
        try:
            index = slots.index(placement.slot_id)
        except ValueError:
            return
        target = slots[(index + int(delta)) % len(slots)]
        before = self._placement_snapshot(board)
        swap_slots(board, placement.slot_id, target)
        self._commit_grid_change(board, before, [])

    def _on_set_primary(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        board = active_board(self._workspace)
        placement = placement_for(board, ref)
        if placement is None:
            return
        slots = layout_slots(board.layout_id)
        primary = "primary" if "primary" in slots else slots[0]
        if placement.slot_id == primary:
            return
        before = self._placement_snapshot(board)
        swap_slots(board, placement.slot_id, primary)
        self._commit_grid_change(board, before, [])

    def _on_presentation(self, active: bool) -> None:
        if self._inactive():
            return
        page = self.page()
        if page is not None:
            page.set_presentation_active(bool(active))

    def _index_for_view_id(self, section: str, view_id: str) -> int | None:
        window = self._window
        if window is None:
            return None
        if section == "time":
            manager = getattr(window, "view_manager", None)
        else:
            managers = getattr(window, "analysis_managers", None) or {}
            manager = managers.get(section)
        if manager is None:
            return None
        target = str(view_id)
        for idx, state in enumerate(manager.views):
            if str(getattr(state, "view_id", "")) == target:
                return idx
        return None

    def shutdown(self) -> None:
        """Final MainWindow close path: stop work, drop hooks, then drop pixels.

        Idempotent. Project reset must call ``reset_project_state`` instead.
        Queued callbacks no-op after the flag is set, even if a timer still
        delivers.
        """
        if self._shutdown:
            return
        self._shutdown = True
        self._reset_page_runtime()
        self._clear_sync_work()
        self._drop_all_timers()
        self._disconnect_hooks()
        self._disconnect_page_hooks()
        self._disconnect_stack_hooks()
        self._disconnect_manager_hooks()
        if _alive(self._store):
            self._store.clear()
        self._bindings.clear()
        self._unstable.clear()
        self._destroy_watched.clear()
        self._result_refs.clear()
        self._result_generation.clear()
        self._digest_retries.clear()
        self._runtime.clear()
        self._presentation_revision.clear()
        self._workspace = default_workspace()
        self._clear_placement_runtime()

    def reset_project_state(self) -> None:
        """Clear Board/Store/runtime for a new or replaced project.

        Page and stack hooks stay connected so the same window remains
        interactive. Does not run during shutdown.
        """
        if self._shutdown:
            return
        self._reset_page_runtime()
        self._clear_sync_work()
        self._drop_all_timers()
        self._disconnect_hooks()
        if _alive(self._store):
            self._store.clear()
        self._bindings.clear()
        self._unstable.clear()
        # Live source canvases persist across project reset/open. Clearing this
        # set would make `_watch_canvas_destroyed` reconnect `destroyed` on the
        # same QObject every open (receivers grow with N). Shutdown still clears.
        self._result_refs.clear()
        self._result_generation.clear()
        self._digest_retries.clear()
        self._runtime.clear()
        self._presentation_revision.clear()
        self._workspace = default_workspace()
        self._clear_placement_runtime()
        self.refresh_page()

    def clear(self) -> None:
        """Compatibility shim. Product paths must call reset or shutdown."""
        self.reset_project_state()

    def _reset_page_runtime(self) -> None:
        page = self.page()
        if page is None:
            return
        reset = getattr(page, "reset_sheet_session", None)
        if callable(reset):
            reset()
        clear = getattr(page, "clear_runtime_caches", None)
        if callable(clear):
            clear()

    def _disconnect_page_hooks(self) -> None:
        for obj, signal, slot in self._page_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._page_hooks.clear()

    def _disconnect_stack_hooks(self) -> None:
        for obj, signal, slot in self._stack_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._stack_hooks.clear()

    def _disconnect_manager_hooks(self) -> None:
        for obj, signal, slot in self._manager_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._manager_hooks.clear()

    # -- payload ----------------------------------------------------------

    def _time_payload(self, window, ref: UltraViewRef) -> dict | None:
        state = self._time_state(window, ref.view_id)
        if state is None:
            return None
        facts = self._runtime_facts_for(ref)
        filter_payload = self._filter_payload(window)
        return {
            "attached_file_ids": [str(fid) for fid in (state.attached_file_ids or [])],
            "checked": [
                pair for key in (state.checked or [])
                if (pair := _channel_pair(key)) is not None
            ],
            "hidden_channels": [
                pair for key in (state.hidden_channels or [])
                if (pair := _channel_pair(key)) is not None
            ],
            "colors": [
                [*_channel_pair(key), str(color)]
                for key, color in (state.colors or {}).items()
                if _channel_pair(key) is not None
            ],
            "plot_mode": str(state.plot_mode or ""),
            "xlim": self._pair(state.xlim),
            "ylims": {
                str(name): self._pair(span)
                for name, span in (state.ylims or {}).items()
            },
            "overlay_primary": _channel_pair(state.overlay_primary),
            "axis_opts": dict(state.axis_opts or {}),
            "filter": filter_payload,
            "data_signatures": self._time_data_signatures(window, state),
            "markup_revision": facts.markup_revision,
            **self._cursor_payload(window, ref, state),
        }

    def _analysis_payload(self, window, ref: UltraViewRef) -> dict | None:
        resolved = self._analysis_state(window, ref.section, ref.view_id)
        if resolved is None:
            return None
        _mgr, state = resolved
        facts = self._runtime_facts_for(ref)
        pane_count = len(state.panes)
        if facts.visible_pane_count is not None:
            pane_count = int(facts.visible_pane_count)
        panes = []
        for pane_idx, pane in enumerate(state.panes[:pane_count]):
            keys = self._pane_cache_keys(window, ref.section, ref.view_id, pane_idx)
            panes.append({
                "sources": [_channel_pair(key) for key in (pane.sources or [])],
                "rpm_source": _channel_pair(pane.rpm_source),
                "input_source": _channel_pair(pane.input_source),
                "output_source": _channel_pair(pane.output_source),
                "time_range": self._pair(pane.time_range),
                "effective_time_range": self._pair(pane.effective_time_range),
                "xlim": self._pair(pane.xlim),
                "ylim": self._pair(pane.ylim),
                "ylims": {
                    str(name): self._pair(span)
                    for name, span in (pane.ylims or {}).items()
                },
                "cache_keys": [self._digest_key(key) for key in keys],
                "result_generation": [
                    self.result_generation_for(
                        ref.section, ref.view_id, pane_idx, key
                    )
                    for key in keys
                ],
            })
        return {
            "panes": panes,
            "params": dict(state.params or {}),
            "compare": dict(state.compare or {}),
            "pane_count": pane_count,
            "markup_revision": facts.markup_revision,
            **self._cursor_payload(window, ref, state),
        }

    def _time_data_signatures(self, window, state) -> list:
        files = getattr(window, "files", None) or {}
        signatures = []
        seen = set()
        keys = list(state.checked or [])
        if state.overlay_primary is not None:
            keys.append(state.overlay_primary)
        axis_opts = state.axis_opts or {}
        x_axis = axis_opts.get("x_axis") or {}
        source_fid = x_axis.get("source_fid") or x_axis.get("fid")
        channel = x_axis.get("channel")
        if source_fid and channel:
            keys.append((str(source_fid), str(channel)))
        for key in keys:
            pair = _channel_pair(key)
            if pair is None:
                continue
            token = tuple(pair)
            if token in seen:
                continue
            seen.add(token)
            signatures.append([pair, self._channel_signature(files, pair[0], pair[1])])
        return signatures

    def _channel_signature(self, files, fid, channel):
        fd = files.get(fid) if hasattr(files, "get") else None
        if fd is None:
            return None
        data = getattr(fd, "data", None)
        if data is None:
            return None
        columns = getattr(data, "columns", ())
        if channel not in columns:
            return None
        time_axis = getattr(fd, "time_array", None)
        values = _array_from_column(data[channel])
        try:
            return _stable_source_revision(source_revision_for(time_axis, values))
        except (TypeError, ValueError):
            return None

    def _filter_payload(self, window) -> dict:
        getter = getattr(window, "_project_filter_payload", None)
        if callable(getter):
            payload = getter()
            if isinstance(payload, dict):
                return {
                    "enabled": bool(payload.get("enabled", False)),
                    "spec": dict(payload.get("spec") or {}),
                    "show_original": bool(payload.get("show_original", True)),
                    "show_filtered": bool(payload.get("show_filtered", False)),
                }
        return {
            "enabled": False,
            "spec": {},
            "show_original": True,
            "show_filtered": False,
        }

    def _pane_cache_keys(self, window, section, view_id, pane_idx) -> list:
        """Pinned cache keys for one pane, in a run-to-run stable order.

        ``AnalysisPinBook`` stores each slot as a ``set``, so a multi-source
        pane (an FFT overlay is the common case) hands back a different
        ordering in every process — string hashing is salted per run. The
        digest is persisted alongside the preview and compared after restart,
        so an unordered list would make those cards read STALE forever on a
        View nobody touched. ``repr`` orders tuple and dataclass keys alike;
        the value only has to be deterministic, not meaningful.
        """
        pins = getattr(window, "_analysis_pins", None)
        slot = (section, str(view_id), int(pane_idx))
        if pins is not None and slot in pins:
            return sorted(pins[slot], key=repr)
        return []

    def _cursor_payload(self, window, ref: UltraViewRef, state) -> dict:
        widget = self._bound_widget_for(ref)
        live = (
            widget is not None
            and _alive(widget)
            and bool(widget.isVisible())
        )
        stored = self._runtime.get(ref)
        dual = str(getattr(state, "cursor_mode", None) or "off") == "dual"
        if live:
            geometry = []
            for host in _iter_overlay_hosts(widget):
                geom = _cursor_geometry_from_host(host)
                if geom is not None:
                    geometry.append(geom)
            pill = self._pill_fingerprint(window, widget) if dual else None
        elif stored is not None:
            geometry = [
                list(item) if isinstance(item, tuple) else item
                for item in (stored.cursor_geometry or ())
            ]
            pill = (
                list(stored.pill_fingerprint)
                if stored.pill_fingerprint is not None
                else None
            )
        else:
            geometry = []
            pill = None
        return {
            "cursor_mode": str(getattr(state, "cursor_mode", None) or "off"),
            "cursor_geometry": geometry,
            "pill": pill,
        }

    def _pill_fingerprint(self, window, widget):
        stack = getattr(window, "chart_stack", None) if window is not None else None
        if stack is None:
            return None
        pill = getattr(stack, "_pill", None)
        getter = getattr(stack, "_pill_for_canvas", None)
        if callable(getter) and widget is not None:
            hosts = list(_iter_overlay_hosts(widget))
            canvas = hosts[0] if hosts else widget
            try:
                pill = getter(canvas)
            except (TypeError, RuntimeError):
                pass
        if pill is None:
            return None
        try:
            if not pill.isVisible():
                return None
            primary = ""
            if callable(getattr(pill, "primary_text", None)):
                primary = _plain_text(pill.primary_text())
            detail = ""
            if callable(getattr(pill, "has_detail", None)) and pill.has_detail():
                detail_widget = getattr(pill, "_detail", None)
                if detail_widget is not None:
                    detail = _plain_text(detail_widget.text())
            return [primary, detail]
        except RuntimeError:
            return None

    # -- capture ----------------------------------------------------------

    def _has_current_preview(self, ref, digest: str) -> bool:
        record = self._store.get(ref)
        captured_revision = int(getattr(record, "captured_revision", 0) or 0)
        return (
            record is not None
            and record.captured_digest == digest
            and captured_revision == int(self._presentation_revision.get(ref, 0) or 0)
            and PreviewStore.image_valid(getattr(record, "image", None))
        )

    def _try_publish_now(self, ref, widget, reason: str) -> bool:
        if self._inactive():
            return False
        if not self._widget_has_any_real_result(widget):
            self._warn_capture(ref, widget, reason, "no-result")
            self._push_preview(ref, usable=False)
            return False
        digest = self.current_digest_for(ref)
        if digest is None:
            self._warn_capture(ref, widget, reason, "digest-unavailable")
            return False
        if self._has_current_preview(ref, digest) and not self._needs_focus_recapture(
            ref
        ):
            return True
        if not self._is_stable(widget, ref.section):
            self._warn_capture(ref, widget, reason, "unstable")
            return False
        return self._publish_grab(ref, widget, digest, reason)

    def _queue_grab(self, key, ref, widget, digest, reason) -> None:
        if self._inactive():
            return
        widget_ref = weakref.ref(widget)
        coord_ref = weakref.ref(self)

        def _fire():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            coord._publish_grab(ref, canvas, digest, reason)

        self._start_timer(key, _fire)

    def _queue_heatmap_grab(self, key, ref, widget, digest, reason) -> None:
        if self._inactive():
            return
        widget_ref = weakref.ref(widget)
        coord_ref = weakref.ref(self)

        def _after_layout():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            coord._queue_grab(key, ref, canvas, digest, reason)

        def _after_first_turn():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            coord._start_timer(key, _after_layout)

        self._start_timer(key, _after_first_turn)

    def _publish_grab(self, ref, widget, digest, reason) -> bool:
        if self._inactive():
            return False
        if not _alive(widget):
            return False
        bound = self.bound_ref_for(widget)
        if bound is not None and bound != ref:
            return False
        current = self.current_digest_for(ref)
        if current != digest:
            self._warn_capture(ref, widget, reason, "digest-changed")
            self._requeue_after_digest_change(ref, widget, reason)
            return False
        if not self._widget_visible_and_sized(widget):
            return False
        if not self._is_stable(widget, ref.section):
            self._unstable[id(widget)] = (
                ref, digest, reason, weakref.ref(widget)
            )
            return False
        if not self._widget_has_any_real_result(widget):
            self._warn_capture(ref, widget, reason, "no-result")
            self._push_preview(ref, usable=False)
            return False
        with hide_transient_overlays(widget, section=ref.section):
            image = self._grab_image(widget, ref)
        if image is None:
            self._warn_capture(ref, widget, reason, "grab-invalid")
            return False
        revision = int(self._presentation_revision.get(ref, 0) or 0)
        meta = self._preview_meta(ref, digest)
        published = bool(
            self._store.publish(
                ref, image, digest=digest, meta=meta, revision=revision
            )
        )
        if published:
            self._digest_retries.pop(ref, None)
            self._runtime.commit(ref, self._facts_from_widget(widget))
            self._push_preview(ref)
        return published

    def _grab_scale(self, widget, ref) -> float:
        if ref is None:
            return 1.0
        request = self._store.residency_request(ref)
        if (
            request is None
            or request.tier != RESIDENCY_TIER_FOCUS
            or request.target_size is None
        ):
            return 1.0
        target_w, target_h = request.target_size
        try:
            width = max(1, int(widget.width()))
            height = max(1, int(widget.height()))
            dpr = float(widget.devicePixelRatioF())
        except RuntimeError:
            return 1.0
        native_w = max(1.0, width * dpr)
        native_h = max(1.0, height * dpr)
        return focus_grab_scale(
            (native_w, native_h),
            (target_w, target_h),
            max_edge=MAX_PREVIEW_RAW_EDGE,
        )

    def _grab_image(self, widget, ref=None) -> QImage | None:
        pixmap = None
        window = self._window
        stack = getattr(window, "chart_stack", None) if window is not None else None
        grab_pres = getattr(stack, "grab_presentation_pixmap", None)
        scale = self._grab_scale(widget, ref)
        if callable(grab_pres):
            try:
                pixmap = grab_pres(widget, scale=scale)
            except (TypeError, RuntimeError):
                pixmap = None
            if pixmap is not None and pixmap.isNull():
                pixmap = None
        if pixmap is None:
            grab_combined = getattr(widget, "grab_combined_pixmap", None)
            if callable(grab_combined):
                pixmap = grab_combined(scale=scale)
            elif callable(getattr(widget, "grab_pixmap", None)):
                pixmap = widget.grab_pixmap(scale=scale)
            elif isinstance(widget, QWidget):
                pixmap = widget.grab()
        image = pixmap_as_device_pixel_image(pixmap)
        if image is None:
            return None
        if image.width() < _MIN_CAPTURE_EDGE or image.height() < _MIN_CAPTURE_EDGE:
            return None
        return image

    def _time_host_has_plotted_data(self, host) -> bool:
        """True when a time canvas currently holds plotted channel ink.

        ``quality_status()["curve_count"]`` counts native-AA PlotCurveItems
        only. A ready dense-raster cache covers those items, so the count
        is 0 while the user still sees a full plot. Channel tables are the
        emptiness signal; AA color is not.
        """
        for name in ("_channel_lines", "channel_data"):
            mapping = getattr(host, name, None)
            if not mapping:
                continue
            try:
                if len(mapping) > 0:
                    return True
            except TypeError:
                continue
        return False

    def _quality_says_plotted(self, host) -> bool:
        quality = getattr(host, "quality_status", None)
        if not callable(quality):
            return False
        try:
            status = quality() or {}
        except (TypeError, RuntimeError):
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

    def _host_has_real_result(self, host) -> bool:
        """True when *host* currently shows a computed/plotted result.

        Analysis canvases expose ``has_result()``. Time-domain canvases do
        not; plotted channel tables (or a ready dense-raster path) are the
        emptiness signal. AA color is a render-quality light — dense traces
        often stay red, and raster-backed plots report ``curve_count == 0``.
        """
        has_result = getattr(host, "has_result", None)
        if callable(has_result):
            try:
                return bool(has_result())
            except (TypeError, RuntimeError):
                return False
        if self._time_host_has_plotted_data(host):
            return True
        return self._quality_says_plotted(host)

    def _widget_has_any_real_result(self, widget) -> bool:
        """True if any overlay host (or the widget itself) has a real result.

        All-empty panes must not grab. A split analysis page with one live
        pane is eligible; the composite grab is still one ref.
        """
        hosts = list(_iter_overlay_hosts(widget))
        if not hosts:
            return False
        return any(self._host_has_real_result(host) for host in hosts)

    def _is_stable(self, widget, section: str) -> bool:
        if not self._widget_visible_and_sized(widget):
            return False
        window = self._window
        jobs = getattr(window, "_analysis_jobs", None) if window is not None else None
        if jobs is not None and section in _HEATMAP_SECTIONS | {"frf"}:
            if jobs.is_running(section):
                return False
        for host in _iter_overlay_hosts(widget):
            if not self._host_is_stable(host, section):
                return False
        return True

    def _host_is_stable(self, host, section: str) -> bool:
        if not self._widget_visible_and_sized(host):
            return False
        quality = getattr(host, "quality_status", None)
        if callable(quality):
            status = quality() or {}
            state = status.get("state")
            # Yellow = AA / raster still settling. Red with curves is the
            # native non-AA plot the user already sees — grab that. Empty
            # red is filtered by ``_host_has_real_result``, not here.
            if state == "yellow":
                return False
        dense = getattr(host, "_dense_raster", None)
        if dense is not None and callable(getattr(dense, "quality_status", None)):
            dense_status = dense.quality_status() or {}
            if dense_status.get("has_dense") and dense_status.get("state") == "yellow":
                return False
        if getattr(host, "_interaction_state", "idle") != "idle":
            return False
        if bool(getattr(host, "_refresh_pending", False)):
            return False
        timer = getattr(host, "_aa_idle_timer", None)
        if timer is not None:
            try:
                if timer.isActive():
                    return False
            except RuntimeError:
                return False
        return True

    def _widget_visible_and_sized(self, widget) -> bool:
        if not _alive(widget):
            return False
        try:
            if not widget.isVisible():
                return False
            return widget.width() >= _MIN_CAPTURE_EDGE and widget.height() >= _MIN_CAPTURE_EDGE
        except RuntimeError:
            return False

    def _hosts_heatmap(self, widget) -> bool:
        for host in _iter_overlay_hosts(widget):
            if hasattr(host, "plot_or_update_heatmap"):
                return True
        return False

    def _ensure_stability_hooks(self, widget) -> None:
        for host in _iter_overlay_hosts(widget):
            ident = id(host)
            if ident in self._hooked_ids or not _alive(host):
                continue
            quality = getattr(host, "quality_status_changed", None)
            if quality is not None:
                quality.connect(self._on_quality_status_changed)
                self._hooks.append((host, quality, self._on_quality_status_changed))
            layout = getattr(host, "layout_geometry_changed", None)
            if layout is not None:
                layout.connect(self._on_layout_geometry_changed)
                self._hooks.append((host, layout, self._on_layout_geometry_changed))
            for name in (
                "visible_range_changed",
                "cursor_info",
                "dual_cursor_info",
                "markup_revision_changed",
                "manual_zoom_changed",
            ):
                signal = getattr(host, name, None)
                if signal is None:
                    continue
                slot = (
                    self._on_idle_presentation_signal
                    if name in _PIXEL_AFFECTING_SIGNALS
                    else self._on_idle_source_signal
                )
                signal.connect(slot)
                self._hooks.append((host, signal, slot))
            self._hooked_ids.add(ident)

    def _watch_canvas_destroyed(self, canvas) -> None:
        ident = id(canvas)
        if ident in self._destroy_watched:
            return
        canvas.destroyed.connect(partial(self._on_canvas_destroyed, ident))
        self._destroy_watched.add(ident)

    def _on_canvas_destroyed(self, ident: int, *_args) -> None:
        if not _alive(self):
            return
        self._bindings.pop(ident, None)
        self._unstable.pop(ident, None)
        self._hooked_ids.discard(ident)
        self._destroy_watched.discard(ident)
        kept = []
        for obj, signal, slot in self._hooks:
            if id(obj) == ident or not _alive(obj):
                self._hooked_ids.discard(id(obj))
                continue
            kept.append((obj, signal, slot))
        self._hooks = kept

    def _on_quality_status_changed(self, *_args) -> None:
        if self._inactive():
            return
        self._reconsider_pending(self.sender())

    def _on_layout_geometry_changed(self, *_args) -> None:
        if self._inactive():
            return
        self._reconsider_pending(self.sender())

    def _reconsider_pending(self, sender) -> None:
        if self._inactive() or sender is None:
            return
        for ident, pending in list(self._unstable.items()):
            ref, _digest, reason, widget_ref = pending
            target = widget_ref() if widget_ref is not None else None
            if target is None or not _alive(target):
                self._unstable.pop(ident, None)
                continue
            hosts = [target, *list(_iter_overlay_hosts(target))]
            if sender is target or sender in hosts:
                self.request_capture(ref, target, reason)

    # -- identity / meta --------------------------------------------------

    def _active_ref(self, section: str) -> UltraViewRef | None:
        window = self._window
        if window is None:
            return None
        if section == "time":
            manager = getattr(window, "view_manager", None)
            if manager is None or not manager.views:
                return None
            state = manager.get(manager.active)
            return UltraViewRef("time", state.view_id)
        resolved = self._analysis_state(window, section, None)
        if resolved is None:
            return None
        _mgr, state = resolved
        return UltraViewRef(section, state.view_id)

    def _visible_widget_for(self, section: str):
        window = self._window
        if window is None:
            return None
        if section == "time":
            stack = getattr(window, "chart_stack", None)
            if stack is not None and callable(getattr(stack, "focused_canvas", None)):
                return stack.focused_canvas()
            return getattr(window, "canvas_time", None)
        return self._analysis_page(window, section)

    def _widget_for_ref(self, ref: UltraViewRef):
        return self._bound_widget_for(ref)

    def _bound_widget_for(self, ref: UltraViewRef):
        for _ident, (bound, handle) in list(self._bindings.items()):
            if bound != ref:
                continue
            widget = handle()
            if widget is None or not _alive(widget):
                continue
            if self.bound_ref_for(widget) == ref:
                return widget
        return None

    def _facts_from_widget(self, widget) -> PresentationRuntimeFacts:
        pane_count = getattr(widget, "pane_count", None)
        visible = int(pane_count()) if callable(pane_count) else None
        geometry = []
        dual = False
        for host in _iter_overlay_hosts(widget):
            if _host_is_dual_cursor(host):
                dual = True
            geom = _cursor_geometry_from_host(host)
            if geom is not None:
                geometry.append(tuple(geom))
        pill = self._pill_fingerprint(self._window, widget) if dual else None
        return PresentationRuntimeFacts(
            markup_revision=read_markup_revision(widget),
            visible_pane_count=visible,
            cursor_geometry=tuple(geometry),
            pill_fingerprint=tuple(pill) if pill is not None else None,
        )

    def _runtime_facts_for(self, ref: UltraViewRef) -> PresentationRuntimeFacts:
        widget = self._bound_widget_for(ref)
        live = widget is not None and _alive(widget)
        stored = self._runtime.get(ref)
        if live and bool(widget.isVisible()):
            facts = self._facts_from_widget(widget)
            self._runtime.commit(ref, facts)
            return facts
        if live:
            live_facts = self._facts_from_widget(widget)
            facts = PresentationRuntimeFacts(
                markup_revision=live_facts.markup_revision,
                visible_pane_count=live_facts.visible_pane_count,
                cursor_geometry=stored.cursor_geometry if stored is not None else (),
                pill_fingerprint=(
                    stored.pill_fingerprint if stored is not None else None
                ),
            )
            self._runtime.commit(ref, facts)
            return facts
        if stored is not None:
            return stored
        return PresentationRuntimeFacts()

    def _time_state(self, window, view_id: str):
        manager = getattr(window, "view_manager", None)
        if manager is None:
            return None
        target = str(view_id)
        for state in manager.views:
            if str(getattr(state, "view_id", "")) == target:
                return state
        return None

    def _analysis_state(self, window, section: str, view_id: str | None):
        managers = getattr(window, "analysis_managers", None) or {}
        manager = managers.get(section)
        if manager is None or not manager.views:
            return None
        if view_id is None:
            return manager, manager.get(manager.active)
        target = str(view_id)
        for state in manager.views:
            if str(getattr(state, "view_id", "")) == target:
                return manager, state
        return None

    def _analysis_page(self, window, section: str):
        getter = getattr(window, "_analysis_page", None)
        if callable(getter):
            return getter(section)
        return None

    def _preview_meta(self, ref: UltraViewRef, digest: str) -> PreviewMeta:
        window = self._window
        title = ""
        source_summary = ""
        tab_color = ""
        x_range = None
        if window is not None and ref.section == "time":
            state = self._time_state(window, ref.view_id)
            if state is not None:
                title = str(state.name or "")
                tab_color = str(state.tab_color or "")
                source_summary = self._source_summary(window, state.attached_file_ids)
                x_range = self._pair(state.xlim)
        elif window is not None:
            resolved = self._analysis_state(window, ref.section, ref.view_id)
            if resolved is not None:
                _mgr, state = resolved
                title = str(state.name or "")
                tab_color = str(state.tab_color or "")
                source_summary = self._source_summary(window, state.attached_file_ids)
                if state.panes:
                    x_range = self._pair(state.panes[0].xlim)
        return PreviewMeta(
            ref=ref,
            captured_digest=digest,
            axis_kind=SECTION_AXIS_KIND.get(ref.section),
            x_unit=_SECTION_X_UNIT.get(ref.section, ""),
            x_range=x_range,
            title=title,
            source_summary=source_summary,
            tab_color=tab_color,
        )

    def _source_summary(self, window, fids) -> str:
        files = getattr(window, "files", None) or {}
        names = []
        for fid in fids or ():
            fd = files.get(fid) if hasattr(files, "get") else None
            if fd is None:
                continue
            names.append(
                str(
                    getattr(fd, "short_name", None)
                    or getattr(fd, "filename", None)
                    or fid
                )
            )
        return " · ".join(names)

    @staticmethod
    def _pair(value):
        if value is None:
            return None
        try:
            lo, hi = value
            return (float(lo), float(hi))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _generation_slot(section, view_id, pane_idx, key):
        return (str(section), str(view_id or ""), int(pane_idx or 0), key)

    @staticmethod
    def _digest_key(key):
        if isinstance(key, tuple):
            return [_digest_leaf(item) for item in key]
        return _digest_leaf(key)

    def _warn_capture(self, ref, widget, reason, detail) -> None:
        canvas_type = type(widget).__name__ if widget is not None else "none"
        throttled(
            logger,
            f"ultraview-capture:{ref.section}:{ref.view_id}:{detail}",
            _CAPTURE_SKIP_LEVELS.get(detail, logging.WARNING),
            "UltraView capture skipped (%s/%s) section=%s view_id=%s canvas=%s",
            reason,
            detail,
            ref.section,
            ref.view_id,
            canvas_type,
        )

    def _warn_digest(self, ref, exc) -> None:
        throttled(
            logger,
            f"ultraview-digest:{ref.section}:{ref.view_id}",
            logging.WARNING,
            "UltraView presentation digest failed section=%s view_id=%s: %s",
            ref.section,
            ref.view_id,
            exc,
        )

    def _start_timer(self, key, callback) -> None:
        if self._inactive():
            return
        existing = self._queued.pop(key, None)
        if existing is not None:
            existing.stop()
            existing.deleteLater()
        timer = QTimer(self)
        timer.setSingleShot(True)
        coord_ref = weakref.ref(self)

        def _fire():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            current = coord._queued.get(key)
            if current is timer:
                coord._queued.pop(key, None)
            timer.deleteLater()
            callback()

        timer.timeout.connect(_fire)
        self._queued[key] = timer
        timer.start(0)

    def _drop_queued_for_ref(self, ref, keep=None) -> None:
        for key in [item for item in self._queued if item[0] == ref and item != keep]:
            timer = self._queued.pop(key)
            timer.stop()
            timer.deleteLater()

    def _sheet_visible(self) -> bool:
        window = self._window
        if window is None:
            return False
        sheet = getattr(window, "_ultraview_sheet", None)
        if sheet is None or not _alive(sheet):
            return False
        try:
            return bool(sheet.isVisible())
        except RuntimeError:
            return False

    def _binding_for_idle_sender(self, sender):
        if sender is None:
            return None, None
        ref = self.bound_ref_for(sender)
        if ref is not None:
            return ref, sender
        for _ident, (bound, handle) in list(self._bindings.items()):
            widget = handle()
            if widget is None or not _alive(widget):
                continue
            if sender is widget:
                return bound, widget
            try:
                hosts = list(_iter_overlay_hosts(widget))
            except (TypeError, RuntimeError):
                continue
            if sender in hosts:
                return bound, widget
        return None, None

    def schedule_idle_capture(self, ref, widget=None) -> None:
        if self._inactive() or ref is None:
            return
        if not self._sheet_visible():
            return
        if widget is None:
            widget = self._bound_widget_for(ref)
        self._idle_pending[ref] = (
            weakref.ref(widget) if widget is not None else None,
            monotonic(),
        )
        if not self._idle_timer.isActive():
            self._idle_timer.start()

    def _on_idle_presentation_signal(self, *_args) -> None:
        """Bump the session presentation revision even when the Board is hidden.

        Idle recapture itself stays gated on sheet visibility so a hidden
        UltraView does not grab.  The revision still advances so the next
        temporary-inspect open can see that zoom/cursor/markup changed.
        """
        if self._inactive():
            return
        ref, widget = self._binding_for_idle_sender(self.sender())
        if ref is None:
            return
        self.bump_presentation_revision(ref)
        if not self._sheet_visible():
            return
        self.schedule_idle_capture(ref, widget)

    def _on_idle_source_signal(self, *_args) -> None:
        if self._inactive() or not self._sheet_visible():
            return
        ref, widget = self._binding_for_idle_sender(self.sender())
        if ref is None:
            return
        self.schedule_idle_capture(ref, widget)

    def _on_idle_capture_timeout(self) -> None:
        now = monotonic()
        due: list[tuple[UltraViewRef, Any]] = []
        keep: dict[UltraViewRef, tuple[Any, float]] = {}
        for ref, payload in list(self._idle_pending.items()):
            widget_ref, stamped_at = payload
            elapsed_ms = (now - stamped_at) * 1000.0
            if elapsed_ms + 0.5 >= _IDLE_CAPTURE_MS:
                due.append((ref, widget_ref))
            else:
                keep[ref] = (widget_ref, stamped_at)
        self._idle_pending = keep
        if self._inactive() or not self._sheet_visible():
            return
        for ref, widget_ref in due:
            widget = widget_ref() if widget_ref is not None else None
            if widget is None or not _alive(widget):
                widget = self._bound_widget_for(ref)
            if widget is None:
                continue
            self._push_preview(ref)
            self.request_capture(ref, widget, "idle")
        if self._idle_pending:
            remaining_ms = min(
                _IDLE_CAPTURE_MS - (monotonic() - stamped_at) * 1000.0
                for _ref, (_widget_ref, stamped_at) in self._idle_pending.items()
            )
            self._idle_timer.start(max(1, int(remaining_ms)))

    def _requeue_after_digest_change(self, ref, widget, reason: str) -> None:
        if self._inactive() or ref is None:
            return
        if widget is None or not _alive(widget):
            return
        tries = self._digest_retries.get(ref, 0)
        if tries >= _DIGEST_RETRY_LIMIT:
            self._warn_capture(ref, widget, reason, "digest-retry-exhausted")
            return
        self._digest_retries[ref] = tries + 1
        self.request_capture(ref, widget, reason)

    def _drop_all_timers(self) -> None:
        self._idle_timer.stop()
        self._idle_pending.clear()
        self._digest_retries.clear()
        self._focus_timer.stop()
        self._sidecar_timer.stop()
        self._sidecar_pending.clear()
        self._sidecar_generation += 1
        for timer in list(self._queued.values()):
            timer.stop()
            timer.deleteLater()
        self._queued.clear()
        self._clear_sync_work()

    def _disconnect_hooks(self) -> None:
        for obj, signal, slot in self._hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._hooks.clear()
        self._hooked_ids.clear()


def _display_target_size(display) -> tuple[int, int] | None:
    if display is None:
        return None
    try:
        width, height = int(display[0]), int(display[1])
    except (TypeError, ValueError, IndexError):
        return None
    if width < _MIN_CAPTURE_EDGE or height < _MIN_CAPTURE_EDGE:
        return None
    return (width, height)


def _digest_leaf(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, tuple):
        return [_digest_leaf(item) for item in value]
    if isinstance(value, list):
        return [_digest_leaf(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        # Analysis cache keys are not all tuples: FRF keys are frozen
        # dataclasses (``FrfCacheKey``). Passing one through unchanged used to
        # reach ``presentation_digest`` as an unserializable leaf, so every FRF
        # View holding a pinned result had no digest at all — and a ref with no
        # digest never captures. The class name is part of the encoding so a
        # dataclass can never collide with a plain mapping of the same shape.
        return {
            "__dataclass__": type(value).__name__,
            "fields": {
                field.name: _digest_leaf(getattr(value, field.name))
                for field in fields(value)
            },
        }
    # Anything still unknown falls through to ``_canonical_json_value``, which
    # is the single authority on what is digest-stable. Do not coerce with
    # ``str()`` here: a default ``repr`` carries the object address, which
    # would make the digest differ every run and pin every card to stale.
    return value
