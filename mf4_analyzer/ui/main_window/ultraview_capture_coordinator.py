"""UltraView capture owner: PreviewStore, digest, timers, and sidecar.

MainWindow still talks to ``UltraViewCoordinator``. This coordinator is the
single capture/store/timer owner; the façade constructs one instance and keeps
thin delegates. Workspace mutation stays on ``UltraViewWorkspaceController``.
"""
from __future__ import annotations

import logging
import re
import weakref
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QWidget

from ...diagnostics import throttled
from ...render_profile import source_revision_for
from ..ultraview_capture_facts import (
    CAPABILITY_OK,
    MIN_CAPTURE_EDGE as _MIN_CAPTURE_EDGE,
    collect_widget_capture_facts,
    hide_transient_overlays,
    iter_overlay_hosts as _iter_overlay_hosts,
    widget_visible_and_sized,
)
from ..ultraview_state import (
    PreviewMeta,
    SECTION_AXIS_KIND,
    SOURCE_SECTIONS,
    UltraViewRef,
    UltraViewWorkspaceState,
    active_board,
    all_refs,
    placed_ref_set,
    presentation_digest,
    set_workspace_preview_sidecar,
    workspace_to_payload,
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
from ..image_utils import pixmap_as_device_pixel_image
from .ultraview_runtime import PresentationRuntimeFacts, PresentationRuntimeLedger

logger = logging.getLogger(__name__)

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
_CAPTURE_SKIP_LEVELS = {"no-result": logging.DEBUG}
_SECTION_X_UNIT = {
    "time": "s",
    "fft": "Hz",
    "fft_time": "s",
    "frf": "Hz",
    "order": "s",
}
def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except (RuntimeError, TypeError):
        return True
def _plain_text(value) -> str:
    if not value:
        return ""
    return _HTML_TAG.sub("", str(value)).strip()
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


class UltraViewCaptureCoordinator(QObject):
    """Own PreviewStore, canvas bindings, capture queue, digest, and sidecar."""

    def __init__(
        self,
        *,
        window: Callable[[], Any],
        is_inactive: Callable[[], bool],
        page: Callable[[], Any],
        push_preview: Callable[..., None],
        workspace: Callable[[], UltraViewWorkspaceState],
        sheet_visible: Callable[[], bool],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._window_impl = window
        self._is_inactive = is_inactive
        self._page_impl = page
        self._push_preview_impl = push_preview
        self._workspace_impl = workspace
        self._sheet_visible_impl = sheet_visible
        self._store = PreviewStore(parent=self)
        self._store.images_dropped.connect(self._on_store_images_dropped)
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

    @property
    def store(self) -> PreviewStore:
        return self._store

    @property
    def _window(self):
        return self._window_impl()

    @property
    def _workspace(self) -> UltraViewWorkspaceState:
        return self._workspace_impl()

    def _inactive(self) -> bool:
        return bool(self._is_inactive())

    def page(self):
        return self._page_impl()

    def _push_preview(self, ref: UltraViewRef, *, usable: bool = True) -> None:
        return self._push_preview_impl(ref, usable=usable)

    def _sheet_visible(self) -> bool:
        return bool(self._sheet_visible_impl())

    def reset_capture_state(self) -> None:
        """Stop capture work and drop pixels. Does not touch workspace or page."""
        self._drop_all_timers()
        self._disconnect_hooks()
        if _alive(self._store):
            self._store.clear()
        self._bindings.clear()
        self._unstable.clear()
        self._result_refs.clear()
        self._result_generation.clear()
        self._digest_retries.clear()
        self._runtime.clear()
        self._presentation_revision.clear()

    def shutdown_capture(self) -> None:
        """Final close path: reset capture and forget destroy watches."""
        self.reset_capture_state()
        self._destroy_watched.clear()

    def load_preview_sidecar(self, project_path, workspace_payload, descriptor) -> list[str]:
        opened = open_preview_sidecar(project_path, workspace_payload, descriptor)
        warnings = [
            f"{item.code}: {item.detail}" if item.detail else item.code
            for item in opened.warnings
        ]
        if opened.ok and opened.images:
            self._queue_sidecar_images(opened.images)
        return warnings

    def prioritize_sidecar_queue(self) -> None:
        self._prioritize_sidecar_queue()

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
        captured = collect_widget_capture_facts(widget)
        if captured.capability != CAPABILITY_OK:
            self._warn_capture(
                ref, widget, reason, captured.degrade_reason or "unsupported-host"
            )
            self._push_preview(ref, usable=False)
            return
        if not captured.has_real_result:
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
        if not self._is_stable(widget, ref.section, facts=captured):
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

    def _queue_sidecar_images(self, images: tuple[SidecarImagePayload, ...]) -> None:
        self._sidecar_pending = list(images)
        self._prioritize_sidecar_queue()
        if self._sidecar_pending and not self._inactive():
            self._sidecar_timer.start()

    def _prioritize_sidecar_queue(self) -> None:
        if not self._sidecar_pending:
            return
        active = set(all_refs(active_board(self._workspace)))
        self._sidecar_pending.sort(key=lambda item: 0 if item.ref in active else 1)

    def _on_sidecar_load_timeout(self) -> None:
        generation = self._sidecar_generation
        if self._inactive() or generation != self._sidecar_generation:
            self._sidecar_pending.clear()
            return
        batch = self._sidecar_pending[:_SIDECAR_LOAD_BATCH]
        self._sidecar_pending = self._sidecar_pending[_SIDECAR_LOAD_BATCH:]
        members = {
            ref for board in self._workspace.boards for ref in all_refs(board)
        }
        for payload in batch:
            if self._inactive() or generation != self._sidecar_generation:
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
            and not self._inactive()
            and generation == self._sidecar_generation
        ):
            self._sidecar_timer.start()

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

    def _ref_exists(self, ref: UltraViewRef) -> bool:
        if ref.section == "time":
            return self._time_state(self._window, ref.view_id) is not None
        resolved = self._analysis_state(self._window, ref.section, ref.view_id)
        return resolved is not None

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
            captured = collect_widget_capture_facts(widget)
            geometry = [list(item) for item in captured.cursor_geometries]
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
        captured = collect_widget_capture_facts(widget)
        if captured.capability != CAPABILITY_OK:
            self._warn_capture(
                ref, widget, reason, captured.degrade_reason or "unsupported-host"
            )
            self._push_preview(ref, usable=False)
            return False
        if not captured.has_real_result:
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
        if not self._is_stable(widget, ref.section, facts=captured):
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
        captured = collect_widget_capture_facts(widget)
        if not self._is_stable(widget, ref.section, facts=captured):
            self._unstable[id(widget)] = (
                ref, digest, reason, weakref.ref(widget)
            )
            return False
        if captured.capability != CAPABILITY_OK:
            self._warn_capture(
                ref, widget, reason, captured.degrade_reason or "unsupported-host"
            )
            self._push_preview(ref, usable=False)
            return False
        if not captured.has_real_result:
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

    def _widget_has_any_real_result(self, widget) -> bool:
        """True if any overlay host currently shows a computed/plotted result.

        All-empty panes must not grab. A split analysis page with one live
        pane is eligible; the composite grab is still one ref. Unsupported
        hosts are not treated as an empty-but-eligible View.
        """
        captured = collect_widget_capture_facts(widget)
        return captured.capability == CAPABILITY_OK and captured.has_real_result

    def _is_stable(self, widget, section: str, *, facts=None) -> bool:
        captured = facts if facts is not None else collect_widget_capture_facts(widget)
        if captured.capability != CAPABILITY_OK:
            return False
        if not captured.is_stable:
            return False
        window = self._window
        jobs = getattr(window, "_analysis_jobs", None) if window is not None else None
        if jobs is not None and section in _HEATMAP_SECTIONS | {"frf"}:
            if jobs.is_running(section):
                return False
        return True

    def _widget_visible_and_sized(self, widget) -> bool:
        return widget_visible_and_sized(widget)

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
        captured = collect_widget_capture_facts(widget)
        geometry = tuple(captured.cursor_geometries)
        dual = captured.cursor_dual
        pill = self._pill_fingerprint(self._window, widget) if dual else None
        return PresentationRuntimeFacts(
            markup_revision=read_markup_revision(widget),
            visible_pane_count=visible,
            cursor_geometry=geometry,
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

