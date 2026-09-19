"""P-key pin routing, capture transaction, and pinned CursorPill projection.

ChartStack holds one controller. Live readout still uses the existing
per-canvas pill; pinned records never share ``_cursor_rows_by_canvas``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import partial

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

from ..cursor_display_model import PinnedCursorSample
from ..pinned_cursor_facts import (
    HIDDEN_CHANNEL_TEXT,
    UNCHECKED_TEXT,
    UNAVAILABLE_TEXT,
    _binding_key as _facts_binding_key,
    _finite,
    _hidden_channel_row as _facts_hidden_channel_row,
    _hidden_keys_from_sample as _facts_hidden_keys_from_sample,
    _identity_key as _facts_identity_key,
    _key_in as _facts_key_in,
    _reconcile_sample as _facts_reconcile_sample,
    _sample_has_hidden as _facts_sample_has_hidden,
    _sample_has_numeric as _facts_sample_has_numeric,
    _sample_has_unchecked as _facts_sample_has_unchecked,
)
from ..pinned_cursor_state import (
    DEFAULT_ANCHOR,
    PinnedCursorCollection,
    PinnedCursorIntent,
    clear_collection,
    coords_equal,
    empty_collection,
    next_record,
)
from .pinning.commands import PinCommands, PinnedAxisEdit
from .pinning.key_router import PinKeyRouter
from .pinning.presentation import (
    INCOMPATIBLE_AXIS_TEXT,
    PENDING_TEXT,
    PinPanelProjector,
)
from .pinning.sampling import (
    PIN_STATUS_INCOMPATIBLE_AXIS,
    PIN_STATUS_PENDING,
    PIN_STATUS_READY,
    PIN_STATUS_UNAVAILABLE,
    PinSampleEvaluator,
)
from .cursor_display import (
    live_pin_hint_text,
    pin_coord_html,
    pin_format_coord_html,
    pin_format_dual_html,
    pin_format_number,
    pin_format_value,
    pin_live_primary_html,
    pin_primary_html,
    pin_status_primary_html,
)
from .cursor_pill import CursorPill

_PLACE_B_MESSAGE = "先放置 B，再按 P 固定"
_PLACE_AB_MESSAGE = "先放置 A、B，再按 P 固定"
_PIN_WARNING_MESSAGES = frozenset({
    _PLACE_B_MESSAGE, _PLACE_AB_MESSAGE, "无数据",
})
_DUMMY_RECORD_ID = "00000000-0000-0000-0000-000000000001"
_HOST_FILTER_EVENTS = frozenset({QEvent.Show, QEvent.Hide})


def pin_feedback_level(message: str) -> str:
    text = str(message or "")
    if text in _PIN_WARNING_MESSAGES or text.startswith("先放置"):
        return "warning"
    return "info"


def _canvas_viewport(canvas):
    glw = getattr(canvas, "_glw", None)
    if glw is None:
        return None
    try:
        viewport = glw.viewport()
    except RuntimeError:
        return None
    return viewport if isinstance(viewport, QWidget) else None


def _widget_alive(widget):
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except RuntimeError:
        return False


@dataclass
class _OwnerState:
    """Committed pin logic. Pill/label maps live on ``PinPanelProjector``."""

    canvas: object
    collection: PinnedCursorCollection | None = None
    samples: dict = field(default_factory=dict)
    reserved_ordinal: int | None = None
    reserved_intent: PinnedCursorIntent | None = None
    live_suppressed: bool = False
    dual_hidden_placement: object = None
    availability: dict = field(default_factory=dict)
    pending_epoch: int = 0
    reproject_timer: object = None
    axis_edit_timer: object = None
    axis_edit: object = None
    signal_conns: list = field(default_factory=list)
    projected_generation: tuple | None = None
    skip_stale_invalidation: bool = False


class _PinHostPorts:
    """Narrow callbacks for Router/Projector. Not a service container."""

    def __init__(self, controller):
        self._c = controller

    def host_widget(self):
        return self._c._host

    def source_on_screen(self, canvas):
        host = self._c._host
        return bool(_widget_alive(host) and host._cursor_source_on_screen(canvas))

    def cursor_mode(self, canvas):
        host = self._c._host
        if not _widget_alive(host):
            return None
        return host._cursor_mode_for_canvas(canvas)

    def canvas_belongs(self, canvas):
        return self._c._canvas_belongs_to_host(canvas)

    def ultraview_widget(self):
        host = self._c._host
        return getattr(host, "page_ultraview", None) if _widget_alive(host) else None

    def fallback_widget_at(self, pos):
        host = self._c._host
        stack = getattr(host, "stack", None) if _widget_alive(host) else None
        if not isinstance(stack, QWidget) or not _widget_alive(stack):
            return None
        local = stack.mapFromGlobal(pos)
        child = stack.childAt(local)
        return child if _widget_alive(child) else None

    def gesture_busy(self, canvas):
        return self._c._gesture_in_progress(canvas)

    def domain_for(self, canvas):
        return self._c._domain_for(canvas)

    def on_confirmed_hit(self, hit):
        self._c._pin_at_mouse(hit)

    def collection_for(self, canvas):
        return self._c.collection_for(canvas)

    def stack_widget(self):
        host = self._c._host
        return getattr(host, "stack", None) if _widget_alive(host) else None

    def card_for_canvas(self, canvas):
        host = self._c._host
        fn = getattr(host, "_card_for_canvas", None)
        return fn(canvas) if callable(fn) else None

    def sync_pill_safe_rect(self, pill, card):
        host = self._c._host
        fn = getattr(host, "_sync_pill_safe_rect", None)
        if callable(fn):
            return fn(pill, card)
        return False

    def update_pill_content(self, pill, card, update):
        host = self._c._host
        fn = getattr(host, "_update_pill_content", None)
        if callable(fn):
            fn(pill, card, update)
            return
        update()

    def split_active(self):
        host = self._c._host
        fn = getattr(host, "split_active", None)
        return bool(callable(fn) and fn())

    def secondary_card(self):
        host = self._c._host
        return getattr(host, "_secondary_card", None) if _widget_alive(host) else None

    def map_canvas_rect_to_stack(self, canvas, rect):
        host = self._c._host
        fn = getattr(host, "map_canvas_rect_to_stack", None)
        return fn(canvas, rect) if callable(fn) else None

    def cursor_display_options(self):
        host = self._c._host
        return getattr(host, "_cursor_display_options", None)

    def live_pill(self, canvas):
        return self._c._live_pill(canvas)

    def prepare_overlay_layout(self, canvas):
        return self._c._prepare_overlay_layout(canvas)

    def on_unpin(self, canvas, record_id):
        self._c.unpin_record(canvas, record_id)

    def on_close(self, canvas, record_id):
        self._c.close_record(canvas, record_id)

    def on_user_moved(self, canvas, record_id):
        self._c._commit_user_anchor(canvas, record_id)

    def on_display_mode(self, canvas, record_id, mode):
        self._c._commit_display_mode(canvas, record_id, mode)

    def on_toggle_panel(self, canvas, record_id, endpoint=None):
        self._c.toggle_record_panel(canvas, record_id, endpoint=endpoint)

    def on_edit_started(self, canvas, record_id, endpoint, global_pos):
        self._c.begin_axis_edit(canvas, record_id, endpoint, global_pos)

    def on_edit_preview(self, canvas, record_id, endpoint, global_pos, modifiers):
        self._c.preview_axis_edit(canvas, record_id, endpoint, global_pos, modifiers)

    def on_edit_committed(self, canvas, record_id, endpoint, global_pos, modifiers):
        self._c.commit_axis_edit(canvas, record_id, endpoint, global_pos, modifiers)

    def on_edit_cancelled(self, canvas, record_id=None, endpoint=None):
        self._c.cancel_axis_edit(canvas, record_id, endpoint)

    def on_nudge(self, canvas, record_id, endpoint, direction, global_pos):
        self._c.nudge_axis_edit(canvas, record_id, endpoint, direction, global_pos)

    def log_unavailable(self, canvas, intent):
        return self._c._log_unavailable(canvas, intent)


_PinnedAxisEdit = PinnedAxisEdit


class PinnedCursorController(QObject):
    """Application-filter P routing and per-canvas pinned-pill projection."""

    pin_feedback = pyqtSignal(str)
    intent_changed = pyqtSignal()
    # ``False`` is emitted only after the committed or restored projection is
    # in place.  Capture owners use this to defer their own idle work while a
    # preview can differ from the serializable collection.
    axis_edit_state_changed = pyqtSignal(object, bool)

    def __init__(self, host):
        super().__init__(host)
        self._host = host
        self._owners: dict[int, _OwnerState] = {}
        self._sampling = PinSampleEvaluator()
        self._commands = PinCommands()
        ports = _PinHostPorts(self)
        self._router = PinKeyRouter(self, ports)
        self._projector = PinPanelProjector(self, ports)
        self.user_intent_revision = 0
        if host is not None:
            host.installEventFilter(self)
            host.destroyed.connect(self._remove_application_filter)
            mode_changed = getattr(host, "mode_changed", None)
            if mode_changed is not None:
                mode_changed.connect(self._cancel_axis_edits_for_mode_change)
            if host.isVisible():
                self._install_application_filter()

    @property
    def _application_filter_installed(self) -> bool:
        """True only while the Router's application filter is actually installed."""
        router = getattr(self, "_router", None)
        return bool(router is not None and router.application_filter_installed)

    @property
    def _last_mouse_global(self):
        return self._router.last_mouse_global

    @_last_mouse_global.setter
    def _last_mouse_global(self, value):
        self._router.last_mouse_global = QPoint() if value is None else QPoint(value)

    # ---- bind / collections -------------------------------------------------

    def bind_canvas(self, canvas) -> None:
        if canvas is None or not _widget_alive(canvas):
            return
        key = id(canvas)
        if key in self._owners:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(0)
        timer.timeout.connect(partial(self._reproject_owner, key))
        axis_edit_timer = QTimer(self)
        axis_edit_timer.setSingleShot(True)
        axis_edit_timer.setInterval(0)
        axis_edit_timer.timeout.connect(partial(self._flush_axis_edit_preview, key))
        owner = _OwnerState(
            canvas=canvas,
            collection=None,
            reproject_timer=timer,
            axis_edit_timer=axis_edit_timer,
        )
        self._owners[key] = owner
        self._projector.bind_canvas(key, canvas)
        destroyed = getattr(canvas, "destroyed", None)
        if destroyed is not None:
            slot = partial(self._on_canvas_destroyed, key)
            destroyed.connect(slot)
            owner.signal_conns.append((destroyed, slot))
        invalidated = getattr(canvas, "presentation_content_invalidated", None)
        if invalidated is not None:
            slot = partial(self._on_content_invalidated, key)
            invalidated.connect(slot)
            owner.signal_conns.append((invalidated, slot))
        rebuilt = getattr(canvas, "chart_rebuilt", None)
        if rebuilt is not None:
            slot = partial(self._on_chart_rebuilt, key)
            rebuilt.connect(slot)
            owner.signal_conns.append((rebuilt, slot))

    def unbind_canvas(self, canvas) -> None:
        if canvas is None:
            return
        self._drop_owner(id(canvas), destroy_pills=True)

    def collection_for(self, canvas) -> PinnedCursorCollection | None:
        owner = self._owner(canvas)
        if owner is None:
            return None
        return owner.collection

    def is_axis_edit_active(self, canvas) -> bool:
        """Whether ``canvas`` has an uncommitted bottom-handle transaction."""
        owner = self._owner(canvas)
        return owner is not None and owner.axis_edit is not None

    def axis_edit_is_settled(self, canvas) -> bool:
        """Whether capture may safely read the committed owner collection."""
        return not self.is_axis_edit_active(canvas)

    def set_collection(self, canvas, collection) -> None:
        owner = self._owner(canvas, create=True)
        if owner is None:
            return
        if not isinstance(collection, PinnedCursorCollection):
            return
        self.cancel_axis_edit(canvas, render=False)
        self._cancel_reproject(owner)
        self._clear_pills(owner)
        owner.collection = collection
        owner.reserved_ordinal = None
        owner.reserved_intent = None
        owner.dual_hidden_placement = None
        owner.availability.clear()
        owner.projected_generation = None
        owner.skip_stale_invalidation = False
        if collection.records:
            self._mark_records_pending(owner)
            self._schedule_reproject(owner)

    def availability_for(self, canvas, record_id: str) -> str:
        owner = self._owner(canvas)
        if owner is None:
            return PIN_STATUS_READY
        return str(owner.availability.get(str(record_id), PIN_STATUS_READY))

    def clear_all(self) -> None:
        """Drop GUI, caches, and records on every bound canvas.

        Used when the last source closes / the session is replaced. Does not
        emit ``intent_changed``; those paths already mark project dirty.
        Does not mint a new ``scope_id``.
        """
        self._projector.invalidate_tokens()
        for owner in list(self._owners.values()):
            self._cancel_axis_edit(owner, render=False)
            self._cancel_reproject(owner)
            overlay = getattr(owner.canvas, "_pinned_overlay", None)
            if overlay is not None:
                overlay.clear()
            self._clear_pills(owner)
            if owner.collection is not None:
                owner.collection = clear_collection(owner.collection)
            owner.reserved_ordinal = None
            owner.reserved_intent = None
            owner.live_suppressed = False
            owner.dual_hidden_placement = None
            owner.projected_generation = None

    @staticmethod
    def filter_collection_identities(
        collection,
        *,
        fids=(),
        channels=(),
    ) -> PinnedCursorCollection:
        """Drop closed identities from records. Empty binding set → drop record."""
        if collection is None or not isinstance(collection, PinnedCursorCollection):
            return collection
        drop_fids = {str(item) for item in (fids or ()) if str(item)}
        drop_channels = {
            (str(fid), str(channel))
            for fid, channel in (channels or ())
            if str(fid) and str(channel)
        }
        if not drop_fids and not drop_channels:
            return collection
        kept = []
        for intent in collection.records:
            if not intent.bindings:
                kept.append(intent)
                continue
            bindings = tuple(
                item for item in intent.bindings
                if str(item.fid) not in drop_fids
                and (str(item.fid), str(item.channel)) not in drop_channels
            )
            if not bindings:
                continue
            if bindings != intent.bindings:
                intent = replace(intent, bindings=bindings)
            kept.append(intent)
        if tuple(kept) == collection.records:
            return collection
        return replace(collection, records=tuple(kept))

    def drop_closed_identities(self, *, fids=(), channels=()) -> None:
        """Remove closed source/channel identities from live collections."""
        for owner in list(self._owners.values()):
            if owner.collection is None:
                continue
            filtered = self.filter_collection_identities(
                owner.collection, fids=fids, channels=channels,
            )
            if filtered is owner.collection:
                continue
            self._cancel_axis_edit(owner, render=False)
            removed = {
                item.record_id for item in owner.collection.records
            } - {item.record_id for item in filtered.records}
            for record_id in removed:
                owner.samples.pop(record_id, None)
                owner.availability.pop(record_id, None)
                self._projector.destroy_record(id(owner.canvas), record_id)
            owner.collection = filtered
            self._reproject_now(owner)

    def pills_for(self, canvas) -> tuple[CursorPill, ...]:
        if canvas is None:
            return ()
        return self._projector.pills_for(id(canvas))

    def axis_labels_for(self, canvas):
        if canvas is None:
            return ()
        return self._projector.axis_labels_for(id(canvas))

    def capture_fingerprint_for(self, canvas) -> tuple:
        """Stable pin presentation digest. Hover highlight is omitted."""
        owner = self._owner(canvas)
        if owner is None or owner.collection is None:
            return ()
        rows = []
        for intent in owner.collection.records:
            sample = owner.samples.get(intent.record_id)
            revision = (
                getattr(sample, "data_revision", None)
                if sample is not None else None
            )
            if revision is not None:
                try:
                    revision = int(revision)
                except (TypeError, ValueError):
                    revision = None
            anchor = intent.anchor
            rows.append((
                str(intent.record_id),
                int(intent.ordinal),
                str(intent.mode),
                str(intent.domain),
                _finite(intent.x),
                _finite(intent.ax),
                _finite(intent.bx),
                str(intent.presentation or "full"),
                intent.panel_expanded is True,
                str(anchor.h_edge),
                str(anchor.v_edge),
                _finite(anchor.nx),
                _finite(anchor.ny),
                revision,
            ))
        return tuple(rows)

    def overlay_for(self, canvas):
        return getattr(canvas, "_pinned_overlay", None)

    def raise_record(self, canvas, record_id: str) -> None:
        """Raise/locate the pill. Does not change X, zoom, or placement."""
        if canvas is None:
            return
        self._projector.raise_record(id(canvas), canvas, str(record_id))

    def toggle_record_panel(self, canvas, record_id: str, *, endpoint=None) -> None:
        """Commit one record's independent bottom-Pn expand/collapse intent."""
        owner = self._owner(canvas)
        if owner is None or owner.collection is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        result = self._commands.toggle_panel(owner.collection, intent)
        if result.collection is None or result.record is None:
            return
        owner.collection = result.collection
        self._projector.set_panel_endpoint(
            id(canvas),
            record_id,
            endpoint if result.record.panel_expanded is True else None,
        )
        self._project_record(
            owner,
            result.record,
            owner.samples.get(record_id),
            availability=owner.availability.get(record_id, PIN_STATUS_READY),
        )
        self._sync_overlay(owner)
        self._arrange_pinned_panels(owner)
        if result.mark_intent:
            self._mark_user_intent()

    # ---- bottom-axis edit transaction -------------------------------------

    @staticmethod
    def _endpoint_value(intent, endpoint):
        return PinCommands.endpoint_value(intent, endpoint)

    @staticmethod
    def _with_endpoint_value(intent, endpoint, value):
        return PinCommands.with_endpoint_value(intent, endpoint, value)

    def _sample_endpoint_value(self, sample, endpoint):
        return self._commands.sample_endpoint_value(sample, endpoint)

    def _axis_edit_overlay(self, owner):
        canvas = owner.canvas if owner is not None else None
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        return overlay if overlay is not None else None

    def _axis_edit_bounds(self, owner):
        overlay = self._axis_edit_overlay(owner)
        getter = getattr(overlay, "bottom_axis_physical_bounds", None)
        bounds = getter() if callable(getter) else None
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            return None
        lo, hi = _finite(bounds[0]), _finite(bounds[1])
        if lo is None or hi is None or hi <= lo:
            return None
        return lo, hi

    @staticmethod
    def _axis_bounds_equal(left, right):
        return PinCommands.axis_bounds_equal(left, right)

    def _axis_edit_is_valid(self, owner, edit):
        if owner is None or edit is None or owner.collection is None:
            return False
        return self._commands.axis_edit_is_valid(
            edit,
            scope_id=str(owner.collection.scope_id),
            current_intent=self._intent(owner, edit.record_id),
            generation=self._canvas_generations(owner.canvas),
            visible_bounds=self._axis_edit_bounds(owner),
        )

    def begin_axis_edit(self, canvas, record_id, endpoint, global_pos) -> bool:
        """Start a side-effect-free edit for one stable record endpoint."""
        owner = self._owner(canvas)
        if owner is None or owner.collection is None:
            return False
        record_id, endpoint = str(record_id), str(endpoint)
        intent = self._intent(owner, record_id)
        value = self._endpoint_value(intent, endpoint)
        if value is None:
            return False
        status = owner.availability.get(record_id, PIN_STATUS_READY)
        if status not in {PIN_STATUS_READY, PIN_STATUS_UNAVAILABLE}:
            return False
        overlay = self._axis_edit_overlay(owner)
        position_for = getattr(overlay, "bottom_axis_viewport_pos_for_physical", None)
        if not callable(position_for):
            return False
        viewport_pos = position_for(value)
        viewport = _canvas_viewport(canvas)
        bounds = self._axis_edit_bounds(owner)
        if viewport_pos is None or viewport is None or bounds is None:
            return False
        try:
            endpoint_global = viewport.mapToGlobal(viewport_pos)
        except RuntimeError:
            return False
        if owner.axis_edit is not None:
            self._cancel_axis_edit(owner, render=True)
        result = self._commands.begin_axis_edit(
            scope_id=str(owner.collection.scope_id),
            record_id=record_id,
            endpoint=endpoint,
            original=intent,
            generation=self._canvas_generations(canvas),
            visible_bounds=bounds,
            endpoint_global=endpoint_global,
            pointer_global=global_pos,
        )
        owner.axis_edit = result.axis_edit
        self.axis_edit_state_changed.emit(canvas, True)
        return True

    def preview_axis_edit(self, canvas, record_id, endpoint, global_pos, modifiers) -> None:
        owner = self._owner(canvas)
        edit = owner.axis_edit if owner is not None else None
        if (
            edit is None or edit.record_id != str(record_id)
            or edit.endpoint != str(endpoint)
        ):
            return
        if not self._axis_edit_is_valid(owner, edit):
            self._cancel_axis_edit(owner, render=True)
            return
        self._commands.accumulate_preview_pointer(edit, global_pos, modifiers)
        timer = owner.axis_edit_timer
        if timer is None:
            self._flush_axis_edit_preview(id(owner.canvas))
            return
        try:
            if not timer.isActive():
                timer.start()
        except RuntimeError:
            self._flush_axis_edit_preview(id(owner.canvas))

    def _candidate_for_axis_endpoint(self, owner, intent, endpoint, raw_value):
        bounds = self._axis_edit_bounds(owner)
        requested = self._commands.requested_endpoint(
            intent, endpoint, raw_value, bounds,
        )
        if requested is None:
            return None, None
        sample = self._evaluate_intent(owner.canvas, requested)
        if not self._sample_has_result(sample):
            return None, None
        return self._commands.accept_endpoint_sample(requested, endpoint, sample)

    def _flush_axis_edit_preview(self, key) -> None:
        owner = self._owners.get(key)
        edit = owner.axis_edit if owner is not None else None
        if edit is None or edit.pending_global is None:
            return
        if not self._axis_edit_is_valid(owner, edit):
            self._cancel_axis_edit(owner, render=True)
            return
        overlay = self._axis_edit_overlay(owner)
        mapper = getattr(overlay, "bottom_axis_global_to_viewport", None)
        viewport_pos = mapper(edit.pending_global) if callable(mapper) else None
        edit.pending_global = None
        if viewport_pos is None:
            return
        value = self._physical_x(owner.canvas, edit.original.domain, viewport_pos)
        candidate, sample = self._candidate_for_axis_endpoint(
            owner, edit.original, edit.endpoint, value,
        )
        result = self._commands.accept_preview_candidate(edit, candidate, sample)
        if result.preview_intent is None:
            return
        self._project_record(
            owner, result.preview_intent, result.preview_sample,
            availability=owner.availability.get(edit.record_id, PIN_STATUS_READY),
        )
        self._sync_overlay(owner)

    def commit_axis_edit(self, canvas, record_id, endpoint, global_pos, modifiers) -> None:
        owner = self._owner(canvas)
        edit = owner.axis_edit if owner is not None else None
        if (
            edit is None or edit.record_id != str(record_id)
            or edit.endpoint != str(endpoint)
        ):
            return
        if QPoint(global_pos) != edit.last_pointer_global:
            self.preview_axis_edit(canvas, record_id, endpoint, global_pos, modifiers)
        self._flush_axis_edit_preview(id(canvas))
        edit = owner.axis_edit
        result = self._commands.decide_axis_commit(
            edit,
            collection=owner.collection if owner is not None else None,
            current_intent=(
                self._intent(owner, edit.record_id)
                if owner is not None and edit is not None else None
            ),
            generation=(
                self._canvas_generations(canvas)
                if owner is not None else None
            ),
            visible_bounds=(
                self._axis_edit_bounds(owner) if owner is not None else None
            ),
        )
        if result.action == "edit_stale" or edit is None:
            self._cancel_axis_edit(owner, render=True)
            return
        original = edit.original
        record_id = edit.record_id
        self._clear_axis_edit(owner)
        if result.action != "edit_commit":
            self._restore_axis_edit_projection(owner, original)
            self._emit_axis_edit_settled(owner)
            return
        owner.collection = result.collection
        owner.samples[record_id] = result.sample
        owner.availability[record_id] = PIN_STATUS_READY
        self._project_record(
            owner, result.record, result.sample, availability=PIN_STATUS_READY,
        )
        self._sync_overlay(owner)
        if result.mark_intent:
            self._mark_user_intent()
        self._emit_axis_edit_settled(owner)

    def cancel_axis_edit(self, canvas, record_id=None, endpoint=None, *, render=True) -> None:
        owner = self._owner(canvas)
        edit = owner.axis_edit if owner is not None else None
        if edit is None:
            return
        if record_id is not None and edit.record_id != str(record_id):
            return
        if endpoint is not None and edit.endpoint != str(endpoint):
            return
        self._cancel_axis_edit(owner, render=render)

    def _cancel_axis_edit(self, owner, *, render, notify=None):
        edit = owner.axis_edit if owner is not None else None
        if edit is None:
            return
        self._clear_axis_edit(owner)
        if render and _widget_alive(owner.canvas):
            self._restore_axis_edit_projection(owner, edit.original)
        # Destructive callers clear or replace the owner projection in the
        # same stack frame.  They leave notification to their own settled
        # generation rather than falsely advertising a still-visible preview.
        if notify is None:
            notify = render
        if notify:
            self._emit_axis_edit_settled(owner)

    @staticmethod
    def _clear_axis_edit(owner):
        owner.axis_edit = None
        timer = owner.axis_edit_timer
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass

    def _emit_axis_edit_settled(self, owner) -> None:
        canvas = owner.canvas if owner is not None else None
        if _widget_alive(canvas):
            self.axis_edit_state_changed.emit(canvas, False)

    def _restore_axis_edit_projection(self, owner, intent):
        self._project_record(
            owner, intent, owner.samples.get(intent.record_id),
            availability=owner.availability.get(intent.record_id, PIN_STATUS_READY),
        )
        self._sync_overlay(owner)

    def _cancel_axis_edits_for_mode_change(self, *_args):
        for owner in list(self._owners.values()):
            self._cancel_axis_edit(owner, render=True)

    def nudge_axis_edit(self, canvas, record_id, endpoint, direction, global_pos) -> None:
        """Commit one keyboard step through the existing coordinate/fact path."""
        owner = self._owner(canvas)
        if owner is None or owner.collection is None or direction not in {-1, 1}:
            return
        if owner.axis_edit is not None:
            return
        intent = self._intent(owner, str(record_id))
        value = self._endpoint_value(intent, str(endpoint))
        if value is None or owner.availability.get(str(record_id), PIN_STATUS_READY) != PIN_STATUS_READY:
            return
        if intent.domain == "time":
            raw_value = value + (0.001 * direction)
            candidate, sample = self._candidate_for_axis_endpoint(
                owner, intent, str(endpoint), raw_value,
            )
        elif intent.domain == "channel":
            candidate, sample = self._pixel_axis_candidate(
                owner, intent, str(endpoint), direction,
            )
        elif intent.domain in {"frequency", "frf"}:
            candidate, sample = self._adjacent_frequency_candidate(
                owner, intent, str(endpoint), direction,
            )
        else:
            return
        if candidate is None or sample is None:
            if intent.domain in {"frequency", "frf"}:
                self.pin_feedback.emit("无相邻有效频点")
            return
        result = self._commands.decide_nudge_commit(
            collection=owner.collection,
            original=intent,
            endpoint=str(endpoint),
            candidate=candidate,
            sample=sample,
        )
        if result.action != "edit_commit":
            if intent.domain in {"frequency", "frf"}:
                self.pin_feedback.emit("无相邻有效频点")
            return
        owner.collection = result.collection
        owner.samples[str(record_id)] = result.sample
        owner.availability[str(record_id)] = PIN_STATUS_READY
        self._project_record(
            owner, result.record, result.sample, availability=PIN_STATUS_READY,
        )
        self._sync_overlay(owner)
        if result.mark_intent:
            self._mark_user_intent()

    def _pixel_axis_candidate(self, owner, intent, endpoint, direction):
        overlay = self._axis_edit_overlay(owner)
        position_for = getattr(overlay, "bottom_axis_viewport_pos_for_physical", None)
        pos = position_for(self._endpoint_value(intent, endpoint)) if callable(position_for) else None
        if pos is None:
            return None, None
        shifted = QPoint(pos.x() + int(direction), pos.y())
        raw_value = self._physical_x(owner.canvas, intent.domain, shifted)
        return self._candidate_for_axis_endpoint(owner, intent, endpoint, raw_value)

    def _adjacent_frequency_candidate(self, owner, intent, endpoint, direction):
        """Find the neighbouring effective grid point without reading arrays.

        Frequency canvases already expose a side-effect-free evaluator which
        snaps a query to their active reference grid.  Probe that public fact
        interface across the current viewport; no DSP or private curve array is
        duplicated here.
        """
        overlay = self._axis_edit_overlay(owner)
        position_for = getattr(overlay, "bottom_axis_viewport_pos_for_physical", None)
        origin = position_for(self._endpoint_value(intent, endpoint)) if callable(position_for) else None
        viewport = _canvas_viewport(owner.canvas)
        if origin is None or viewport is None or not viewport.rect().contains(origin):
            return None, None
        original = self._endpoint_value(intent, endpoint)
        low = 0
        high = 1
        found = None
        limit = (
            viewport.width() - origin.x() - 1
            if direction > 0 else origin.x()
        )
        while high <= max(0, int(limit)):
            probe = QPoint(origin.x() + direction * high, origin.y())
            candidate, sample = self._candidate_for_axis_endpoint(
                owner, intent, endpoint,
                self._physical_x(owner.canvas, intent.domain, probe),
            )
            value = self._endpoint_value(candidate, endpoint)
            if candidate is not None and value is not None and (
                (direction > 0 and value > original and not coords_equal(value, original))
                or (direction < 0 and value < original and not coords_equal(value, original))
            ):
                found = (high, candidate, sample)
                break
            low, high = high, high * 2
        if found is None:
            return None, None
        hi, candidate, sample = found
        while hi - low > 1:
            middle = (low + hi) // 2
            probe = QPoint(origin.x() + direction * middle, origin.y())
            trial, trial_sample = self._candidate_for_axis_endpoint(
                owner, intent, endpoint,
                self._physical_x(owner.canvas, intent.domain, probe),
            )
            value = self._endpoint_value(trial, endpoint)
            changed = trial is not None and value is not None and (
                (direction > 0 and value > original and not coords_equal(value, original))
                or (direction < 0 and value < original and not coords_equal(value, original))
            )
            if changed:
                hi, candidate, sample = middle, trial, trial_sample
            else:
                low = middle
        return candidate, sample

    def is_live_suppressed(self, canvas) -> bool:
        owner = self._owner(canvas)
        return bool(owner is not None and owner.live_suppressed)

    def clear_live_suppressed(self, canvas) -> None:
        owner = self._owner(canvas)
        if owner is not None:
            owner.live_suppressed = False
            owner.dual_hidden_placement = None

    def nudge_live(self, canvas) -> None:
        owner = self._owner(canvas)
        if owner is not None:
            self._nudge_live_from_pins(owner)

    def reflow_visible(self) -> None:
        owners = [
            (id(owner.canvas), owner.canvas, owner.collection)
            for owner in list(self._owners.values())
        ]
        self._projector.request_reflow(owners)

    def flush_layout(self, canvas=None) -> None:
        """Consume pending Pin geometry. Does not sample or mark intent."""
        if canvas is None:
            owners = [
                (id(owner.canvas), owner.canvas, owner.collection)
                for owner in list(self._owners.values())
            ]
            self._projector.flush_layout(owners)
            return
        owner = self._owner(canvas)
        if owner is None:
            self._projector.flush_layout()
            return
        self._projector.flush_layout(
            [(id(owner.canvas), owner.canvas, owner.collection)]
        )

    # ---- P routing ----------------------------------------------------------

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self._host and event.type() in _HOST_FILTER_EVENTS:
            self._sync_application_filter()
        return False

    def _sync_application_filter(self) -> None:
        self._router.sync_application_filter()

    def _install_application_filter(self) -> None:
        self._router.install_application_filter()

    def _remove_application_filter(self) -> None:
        self._router.remove_application_filter()

    def close(self) -> None:
        self._router.invalidate_tokens()
        self._projector.invalidate_tokens()
        host = self._host
        if _widget_alive(host):
            try:
                host.removeEventFilter(self)
            except RuntimeError:
                pass
        self._remove_application_filter()
        for key in list(self._owners):
            self._drop_owner(key, destroy_pills=True)

    # ---- transaction --------------------------------------------------------

    def pin_live_readout(self, canvas) -> None:
        """Pin the value already shown on the live pill, not the P-button click."""
        if canvas is None or not _widget_alive(canvas):
            return
        owner = self._owner(canvas, create=True)
        if owner is None:
            return
        mode = self._host._cursor_mode_for_canvas(canvas)
        if mode not in {"single", "dual"}:
            return
        if self._gesture_in_progress(canvas):
            return
        domain = self._domain_for(canvas)
        if domain is None:
            return
        if mode == "dual":
            self._pin_dual(owner, canvas, domain)
            return
        x = self._current_live_x(canvas)
        if x is None:
            return
        self._pin_single(owner, canvas, domain, viewport_pos=None, x=x)

    def _pin_at_mouse(self, hit=None) -> None:
        if hit is None:
            hit = self._router.hit_owner()
        if hit is None:
            return
        canvas, domain, viewport_pos = hit
        owner = self._owner(canvas, create=True)
        if owner is None:
            return
        mode = self._host._cursor_mode_for_canvas(canvas)
        if mode not in {"single", "dual"}:
            return
        if self._gesture_in_progress(canvas):
            return
        if mode == "single":
            self._pin_single(owner, canvas, domain, viewport_pos)
        else:
            self._pin_dual(owner, canvas, domain)

    def _pin_single(self, owner, canvas, domain, viewport_pos, *, x=None) -> None:
        use_reserved = (
            x is None
            and owner.dual_hidden_placement is not None
            and owner.reserved_intent is not None
            and owner.reserved_intent.mode == "single"
        )
        if x is None:
            if use_reserved:
                x = _finite(owner.reserved_intent.x)
            else:
                x = self._physical_x(canvas, domain, viewport_pos)
        if x is None:
            return
        sample = self._evaluate(canvas, domain, mode="single", x=x)
        if not self._sample_has_result(sample):
            self.pin_feedback.emit(UNAVAILABLE_TEXT)
            return
        x_value = _finite(getattr(sample, "x", None))
        if x_value is None:
            x_value = x
        live = self._live_pill(canvas)
        self._refresh_live_from_sample(canvas, sample, domain, "single")
        intent = self._draft_intent(
            canvas, domain, "single", live,
            x=x_value, sample=sample,
        )
        if intent is None:
            return
        result = self._commands.create_pin(
            collection=owner.collection,
            intent=intent,
            sample=sample,
            reserved_ordinal=owner.reserved_ordinal,
            reserved_intent=owner.reserved_intent,
        )
        if result.action == "duplicate":
            self._flash_duplicate(owner, result.duplicate_record_id)
            self._consume_live(owner, canvas, dual=False)
            if result.feedback:
                self.pin_feedback.emit(result.feedback)
            return
        if result.clear_reserved:
            owner.reserved_ordinal = None
            owner.reserved_intent = None
        owner.collection = result.collection
        owner.samples[result.record.record_id] = sample
        owner.availability[result.record.record_id] = PIN_STATUS_READY
        self._project_record(owner, result.record, sample, inherit_live=live)
        self._sync_overlay(owner)
        self._consume_live(owner, canvas, dual=False)
        if result.mark_intent:
            self._mark_user_intent()
        self.pin_feedback.emit(self._success_text(result.record))

    def _pin_dual(self, owner, canvas, domain) -> None:
        placement = self._snapshot_placement(canvas)
        if not isinstance(placement, dict):
            self.pin_feedback.emit(_PLACE_AB_MESSAGE)
            return
        ax = _finite(placement.get("ax"))
        bx = _finite(placement.get("bx"))
        if ax is None:
            self.pin_feedback.emit(_PLACE_AB_MESSAGE)
            return
        if bx is None:
            self.pin_feedback.emit(_PLACE_B_MESSAGE)
            return
        sample = self._evaluate(canvas, domain, mode="dual", ax=ax, bx=bx)
        if not self._sample_has_result(sample):
            self.pin_feedback.emit(UNAVAILABLE_TEXT)
            return
        ax_value = _finite(getattr(sample, "ax", None))
        bx_value = _finite(getattr(sample, "bx", None))
        if ax_value is None:
            ax_value = ax
        if bx_value is None:
            bx_value = bx
        live = self._live_pill(canvas)
        intent = self._draft_intent(
            canvas, domain, "dual", live,
            ax=ax_value, bx=bx_value, sample=sample,
        )
        if intent is None:
            return
        result = self._commands.create_pin(
            collection=owner.collection,
            intent=intent,
            sample=sample,
            reserved_ordinal=owner.reserved_ordinal,
            reserved_intent=owner.reserved_intent,
        )
        if result.action == "duplicate":
            self._flash_duplicate(owner, result.duplicate_record_id)
            self._consume_live(owner, canvas, dual=True, placement=placement)
            if result.feedback:
                self.pin_feedback.emit(result.feedback)
            return
        if result.clear_reserved:
            owner.reserved_ordinal = None
            owner.reserved_intent = None
        owner.collection = result.collection
        owner.samples[result.record.record_id] = sample
        owner.availability[result.record.record_id] = PIN_STATUS_READY
        self._project_record(owner, result.record, sample, inherit_live=live)
        self._sync_overlay(owner)
        self._consume_live(owner, canvas, dual=True, placement=placement)
        if result.mark_intent:
            self._mark_user_intent()
        self.pin_feedback.emit(self._success_text(result.record))

    def _commit_record(self, owner, intent):
        collection, record = self._commands.commit_record(
            owner.collection, intent,
            reserved_ordinal=owner.reserved_ordinal,
            reserved_intent=owner.reserved_intent,
        )
        owner.reserved_ordinal = None
        owner.reserved_intent = None
        return collection, record

    def _highlight_duplicate(self, owner, intent) -> bool:
        duplicate = self._commands.find_duplicate(owner.collection, intent)
        if duplicate is None:
            return False
        self._flash_duplicate(owner, duplicate.record_id)
        self.pin_feedback.emit(f"P{duplicate.ordinal} 已在此位置")
        return True

    def _flash_duplicate(self, owner, record_id) -> None:
        self._projector.flash_duplicate(id(owner.canvas), owner.canvas, record_id)

    def _consume_live(self, owner, canvas, *, dual, placement=None) -> None:
        owner.live_suppressed = True
        owner.dual_hidden_placement = placement if dual else None
        consume = getattr(self._host, "consume_live_cursor_pill", None)
        if callable(consume):
            consume(canvas)
        self._nudge_live_from_pins(owner)

    # ---- unpin / close ------------------------------------------------------

    def unpin_record(self, canvas, record_id: str) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        result = self._commands.unpin(owner.collection, intent)
        if result.action != "unpin":
            return
        self.cancel_axis_edit(canvas, record_id, render=False)
        snapshot, pos = self._projector.snapshot_pill(
            self._projector.pill_for(id(canvas), record_id)
        )
        self._projector.destroy_record(id(canvas), record_id)
        owner.collection = result.collection
        owner.samples.pop(record_id, None)
        owner.availability.pop(record_id, None)
        if result.set_reserved:
            owner.reserved_ordinal = result.reserved_ordinal
            owner.reserved_intent = result.reserved_intent
        if result.live_suppressed is not None:
            owner.live_suppressed = result.live_suppressed
        if result.set_dual_hidden_placement:
            owner.dual_hidden_placement = result.dual_hidden_placement
        self._sync_overlay(owner)
        if result.mark_intent:
            self._mark_user_intent()
        if result.restore_placement is not None:
            restore = getattr(canvas, "restore_cursor_placement", None)
            if callable(restore):
                restore(result.restore_placement)
        restore_live = getattr(self._host, "restore_live_from_pin", None)
        if callable(restore_live):
            restore_live(canvas, snapshot, pos, intent.mode)
        else:
            self._host.set_cursor_mode_for_canvas(canvas, intent.mode)
        if result.feedback:
            self.pin_feedback.emit(result.feedback)

    def close_record(self, canvas, record_id: str) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        result = self._commands.close(owner.collection, intent)
        if result.action != "close":
            return
        self.cancel_axis_edit(canvas, record_id, render=False)
        self._projector.destroy_record(id(canvas), record_id)
        owner.samples.pop(record_id, None)
        owner.availability.pop(record_id, None)
        owner.collection = result.collection
        self._sync_overlay(owner)
        if result.mark_intent:
            self._mark_user_intent()
        if result.feedback:
            self.pin_feedback.emit(result.feedback)

    # ---- eligibility / hit test --------------------------------------------

    def _pin_eligible(self) -> bool:
        return self._hit_owner() is not None

    def _hit_owner(self):
        return self._router.hit_owner()

    def _gesture_in_progress(self, canvas) -> bool:
        app = QApplication.instance()
        if app is not None and app.mouseButtons() != Qt.NoButton:
            return True
        live = self._live_pill(canvas)
        if live is not None and live.is_dragging():
            return True
        if self._projector.any_dragging(id(canvas)):
            return True
        activity = getattr(canvas, "_idle_activity", None)
        if activity is not None and callable(getattr(activity, "is_busy", None)):
            if activity.is_busy():
                return True
        transition = getattr(self._host, "_page_transition", None)
        if transition is not None and (
            transition.is_active() or transition.is_pending()
        ):
            return True
        return False

    def _in_data_viewport(self, canvas, domain, viewport_pos) -> bool:
        return self._router.in_data_viewport(canvas, domain, viewport_pos)

    def _physical_x(self, canvas, domain, viewport_pos):
        return self._router.physical_x(canvas, domain, viewport_pos)

    def _domain_for(self, canvas) -> str | None:
        return self._sampling.domain_for(canvas)

    # ---- evaluate / project -------------------------------------------------

    def _evaluate(self, canvas, domain, *, mode, x=None, ax=None, bx=None):
        return self._sampling.evaluate(
            canvas, domain, mode=mode, x=x, ax=ax, bx=bx,
        )

    def _evaluate_intent(self, canvas, intent):
        return self._sampling.evaluate_intent(canvas, intent)

    @staticmethod
    def _sample_fn(canvas, name):
        return PinSampleEvaluator.sample_fn(canvas, name)

    @staticmethod
    def _wrap_channels(domain, mode, *, x=None, ax=None, bx=None, channels=()):
        return PinSampleEvaluator.wrap_channels(
            domain, mode, x=x, ax=ax, bx=bx, channels=channels,
        )

    @staticmethod
    def _wrap_frf(mode, sample):
        return PinSampleEvaluator.wrap_frf(mode, sample)

    @staticmethod
    def _sample_has_result(sample) -> bool:
        return PinSampleEvaluator.sample_has_result(sample)

    def _draft_intent(
        self, canvas, domain, mode, live, *, x=None, ax=None, bx=None, sample=None,
    ):
        unit = self._x_unit(canvas, domain)
        # Live +/- is not inherited. New pins always start mini; a later +
        # on that card is stored on the intent and reused on the next expand.
        _ = live
        presentation = "mini"
        payload = {
            "mode": mode,
            "domain": domain,
            "x_unit": unit,
            "bindings": self._bindings_from_sample(sample),
            "presentation": presentation,
            "panel_expanded": False,
            # A new pin always starts with a default (not user-placed)
            # anchor.  Its first expanded geometry comes from the bounded
            # multi-card solver below, never the live pill's location.
            "anchor": DEFAULT_ANCHOR,
            "axis_identity": self._axis_identity(canvas, domain),
        }
        if mode == "single":
            payload["x"] = x
        else:
            payload["ax"] = ax
            payload["bx"] = bx
        try:
            collection, intent = next_record(empty_collection(), payload)
        except ValueError:
            return None
        return replace(intent, record_id=_DUMMY_RECORD_ID, ordinal=1)

    def _project_record(
        self, owner, intent, sample, *, inherit_live=None, availability=None,
    ) -> None:
        status = availability or owner.availability.get(
            intent.record_id, PIN_STATUS_READY,
        )
        self._projector.project_record(
            id(owner.canvas),
            owner.canvas,
            intent,
            sample,
            inherit_live=inherit_live,
            availability=status,
            collection=owner.collection,
        )

    def _pill_content(self, intent, sample, host, status):
        return self._projector.pill_content(intent, sample, status)

    def _presentation_for(self, intent, sample, host):
        return self._projector.presentation_for(intent, sample)

    def _status_primary_html(self, intent, status_text) -> str:
        return pin_status_primary_html(intent, status_text)

    def _refresh_live_from_sample(self, canvas, sample, domain, mode) -> None:
        """Keep header/rows on the same evaluate version as the pin."""
        live = self._live_pill(canvas)
        if live is None or sample is None:
            return
        host = self._host
        source = canvas
        x_mode = "custom" if domain == "channel" else (
            "frequency" if domain in {"frequency", "frf"} else "time"
        )
        channels = tuple(getattr(sample, "channels", ()) or ())
        if domain == "frf":
            return
        host._cursor_rows_by_canvas[source] = (
            mode, x_mode, channels, self._live_primary_html(domain, mode, sample),
        )
        host._refresh_cursor_projection(
            source, primary=self._live_primary_html(domain, mode, sample),
        )
        live.set_pin_role("live")
        live.set_live_hint(live_pin_hint_text(mode, dual_complete=True))
        if mode == "single":
            x_value = _finite(getattr(sample, "x", None))
            if x_value is not None:
                sync = getattr(canvas, "sync_single_cursor_line", None)
                if not callable(sync):
                    cursor = getattr(canvas, "_cursor", None)
                    sync = getattr(cursor, "sync_single_cursor_line", None)
                if callable(sync):
                    sync(x_value)

    # ---- geometry -----------------------------------------------------------


    def _commit_user_anchor(self, canvas, record_id) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        pill = self._projector.pill_for(id(canvas), record_id)
        if not _widget_alive(pill):
            return
        self._store_anchor_from_pill(owner, record_id, pill)

    def _commit_display_mode(self, canvas, record_id, mode) -> None:
        owner = self._owner(canvas)
        if owner is None or owner.collection is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        presentation = "mini" if mode == "mini" else "full"
        if intent.presentation == presentation:
            return
        updated = replace(intent, presentation=presentation)
        records = tuple(
            updated if item.record_id == record_id else item
            for item in owner.collection.records
        )
        owner.collection = replace(owner.collection, records=records)
        self._mark_user_intent()
        sample = owner.samples.get(record_id)
        status = owner.availability.get(record_id, PIN_STATUS_READY)
        self._projector.update_display_projection(
            id(canvas), canvas, updated, sample, status, owner.collection,
        )

    def _store_anchor_from_pill(self, owner, record_id, pill) -> None:
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        anchor = self._projector.anchor_from_pill(pill)
        if anchor == intent.anchor:
            return
        updated = replace(intent, anchor=anchor)
        records = tuple(
            updated if item.record_id == record_id else item
            for item in owner.collection.records
        )
        owner.collection = replace(owner.collection, records=records)
        self._mark_user_intent()

    def _arrange_pinned_panels(self, owner) -> None:
        self._projector.arrange_pinned_panels(
            id(owner.canvas), owner.canvas, owner.collection,
        )

    def _apply_anchor(self, pill, collection, *, pill_record_id) -> None:
        self._projector.apply_anchor(
            pill, collection, pill_record_id=pill_record_id,
        )

    def _nudge_live_from_pins(self, owner) -> None:
        self._projector.nudge_live_from_pins(id(owner.canvas), owner.canvas)

    def _prepare_overlay_layout(self, canvas) -> bool:
        owner = self._owner(canvas)
        if owner is None:
            return False
        if owner.axis_edit is not None and not self._axis_edit_is_valid(
            owner, owner.axis_edit,
        ):
            self._cancel_axis_edit(owner, render=True)
            return False
        return True

    # ---- host / widget helpers ---------------------------------------------

    def _owner(self, canvas, *, create=False):
        if canvas is None:
            return None
        key = id(canvas)
        owner = self._owners.get(key)
        if owner is not None and owner.canvas is not canvas:
            self._drop_owner(key, destroy_pills=True)
            owner = None
            if not create:
                self.bind_canvas(canvas)
                owner = self._owners.get(key)
        if owner is None and create:
            self.bind_canvas(canvas)
            owner = self._owners.get(key)
        return owner

    def _intent(self, owner, record_id):
        if owner is None or owner.collection is None:
            return None
        for item in owner.collection.records:
            if item.record_id == record_id:
                return item
        return None

    def _record_id_for(self, owner, pill):
        return self._projector.record_id_for_pill(pill)

    def _live_pill(self, canvas):
        fn = getattr(self._host, "_pill_for_canvas", None)
        if not callable(fn):
            return None
        pill = fn(canvas)
        return pill if _widget_alive(pill) else None

    def _current_live_x(self, canvas):
        """Data-space X currently drawn on the live single-cursor line."""
        cursor = getattr(canvas, "_cursor", None)
        items = getattr(cursor, "_cursor_line_items", None) if cursor is not None else None
        if items:
            try:
                value = _finite(items[0].value())
                if value is not None:
                    return value
            except (RuntimeError, TypeError, AttributeError, IndexError):
                pass
        snap_fn = getattr(canvas, "snapshot_cursor_placement", None)
        snap = snap_fn() if callable(snap_fn) else None
        if not isinstance(snap, dict):
            return None
        value = _finite(snap.get("x"))
        if value is not None:
            return value
        # FFT/FRF single stores the live frequency as ax; a leftover dual
        # A/B pair must not masquerade as the current single readout.
        if _finite(snap.get("bx")) is not None:
            return None
        return _finite(snap.get("ax"))

    def _canvas_belongs_to_host(self, canvas) -> bool:
        card = self._host._card_for_canvas(canvas)
        return getattr(card, "canvas", None) is canvas

    def _drop_owner(self, key, *, destroy_pills) -> None:
        owner = self._owners.get(key)
        if owner is None:
            return
        self._router.invalidate_tokens()
        self._projector.invalidate_key(key)
        self._cancel_axis_edit(owner, render=False)
        self._owners.pop(key, None)
        self._cancel_reproject(owner)
        self._disconnect_owner_signals(owner)
        canvas = owner.canvas
        self._projector.unbind_canvas(key, canvas, destroy_widgets=destroy_pills)
        if destroy_pills:
            owner.samples.clear()
            owner.availability.clear()
        timer = owner.reproject_timer
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
            owner.reproject_timer = None
        axis_edit_timer = owner.axis_edit_timer
        if axis_edit_timer is not None:
            try:
                axis_edit_timer.stop()
                axis_edit_timer.deleteLater()
            except RuntimeError:
                pass
            owner.axis_edit_timer = None

    def _on_canvas_destroyed(self, key, *_args) -> None:
        self._drop_owner(key, destroy_pills=True)

    def _clear_pills(self, owner) -> None:
        self._projector.clear_widgets(id(owner.canvas))
        owner.samples.clear()
        owner.availability.clear()

    def _mark_user_intent(self) -> None:
        self.user_intent_revision += 1
        self.intent_changed.emit()

    @staticmethod
    def _disconnect_owner_signals(owner) -> None:
        canvas = owner.canvas
        if not _widget_alive(canvas):
            owner.signal_conns.clear()
            return
        for signal, slot in list(owner.signal_conns):
            try:
                if sip.isdeleted(canvas):
                    break
                sig = getattr(signal, "signal", None)
                name = ""
                if isinstance(sig, (bytes, bytearray)):
                    name = sig.decode("ascii", "replace").split("(")[0]
                elif sig:
                    name = str(sig).split("(")[0]
                if name and not hasattr(canvas, name):
                    continue
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        owner.signal_conns.clear()

    def _cancel_reproject(self, owner) -> None:
        owner.pending_epoch += 1
        timer = owner.reproject_timer
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass

    def _schedule_reproject(self, owner) -> None:
        owner.pending_epoch += 1
        timer = owner.reproject_timer
        if timer is None:
            self._reproject_now(owner)
            return
        try:
            timer.start(0)
        except RuntimeError:
            self._reproject_now(owner)

    def _on_content_invalidated(self, key, *_args) -> None:
        owner = self._owners.get(key)
        if owner is None or owner.collection is None or not owner.collection.records:
            return
        self._cancel_axis_edit(owner, render=True)
        if not _widget_alive(owner.canvas):
            return
        if owner.skip_stale_invalidation:
            return
        self._mark_records_pending(owner)
        if self._bound_identity_keys(owner.canvas) or getattr(
            owner.canvas, "chart_rebuilt", None,
        ) is None:
            self._schedule_reproject(owner)

    def _on_chart_rebuilt(self, key, *_args) -> None:
        owner = self._owners.get(key)
        if owner is None or owner.collection is None or not owner.collection.records:
            return
        self._cancel_axis_edit(owner, render=True)
        if not _widget_alive(owner.canvas):
            return
        self._cancel_reproject(owner)
        self._reproject_now(owner)
        owner.skip_stale_invalidation = True
        QTimer.singleShot(0, partial(self._clear_skip_stale, key))

    def _clear_skip_stale(self, key) -> None:
        owner = self._owners.get(key)
        if owner is None:
            return
        owner.skip_stale_invalidation = False

    def _reproject_owner(self, key) -> None:
        owner = self._owners.get(key)
        if owner is None:
            return
        self._reproject_now(owner)

    def _mark_records_pending(self, owner) -> None:
        if owner.collection is None:
            return
        for intent in owner.collection.records:
            owner.availability[intent.record_id] = PIN_STATUS_PENDING
            self._project_record(
                owner, intent, owner.samples.get(intent.record_id),
                availability=PIN_STATUS_PENDING,
            )
        self._sync_overlay(owner)
        self._arrange_pinned_panels(owner)

    def _reproject_now(self, owner) -> None:
        canvas = owner.canvas
        if not _widget_alive(canvas) or owner.collection is None:
            return
        if self._canvas_compute_pending(canvas):
            self._mark_records_pending(owner)
            return
        kept = []
        generation, revision = self._canvas_generations(canvas)
        bound = self._bound_identity_keys(canvas)
        hidden = self._hidden_identity_keys(canvas)
        for intent in owner.collection.records:
            status = self._axis_status(canvas, intent)
            sample = None
            next_intent = intent
            if status == PIN_STATUS_INCOMPATIBLE_AXIS:
                owner.samples[intent.record_id] = None
            elif status == PIN_STATUS_UNAVAILABLE:
                sample = PinnedCursorSample(
                    binding_generation=generation,
                    data_revision=revision,
                    domain=intent.domain,
                    mode=intent.mode,
                    x=intent.x,
                    ax=intent.ax,
                    bx=intent.bx,
                    diagnostic=UNAVAILABLE_TEXT,
                )
                owner.samples[intent.record_id] = sample
            else:
                sample = self._evaluate_intent(canvas, intent)
                if (
                    sample is not None
                    and not self._sample_matches_generation(sample, generation, revision)
                ):
                    kept.append(intent)
                    continue
                sample, next_intent, _dropped_record = self._reconcile_sample(
                    intent, sample, bound=bound, hidden=hidden,
                )
                if sample is None or (
                    not self._sample_has_numeric(sample)
                    and not self._sample_has_hidden(sample)
                    and not self._sample_has_unchecked(sample)
                ):
                    status = PIN_STATUS_UNAVAILABLE
                    sample = sample or PinnedCursorSample(
                        binding_generation=generation,
                        data_revision=revision,
                        domain=intent.domain,
                        mode=intent.mode,
                        x=intent.x,
                        ax=intent.ax,
                        bx=intent.bx,
                        diagnostic=UNAVAILABLE_TEXT,
                    )
                elif self._sample_has_numeric(sample) or self._sample_has_hidden(sample):
                    status = PIN_STATUS_READY
                else:
                    status = PIN_STATUS_UNAVAILABLE
                owner.samples[intent.record_id] = sample
            owner.availability[intent.record_id] = status
            kept.append(next_intent)
            self._project_record(
                owner, next_intent, owner.samples.get(next_intent.record_id),
                availability=status,
            )
        if tuple(kept) != owner.collection.records:
            owner.collection = replace(owner.collection, records=tuple(kept))
        owner.projected_generation = (generation, revision)
        self._sync_overlay(owner)
        self._arrange_pinned_panels(owner)

    def _axis_status(self, canvas, intent) -> str:
        return self._sampling.axis_status(canvas, intent)

    def _status_for_sample(self, canvas, intent, sample) -> str:
        return self._sampling.status_for_sample(canvas, intent, sample)

    def _axis_compatible(self, canvas, intent) -> bool:
        return self._sampling.axis_compatible(canvas, intent)

    def _log_unavailable(self, canvas, intent) -> bool:
        return self._sampling.log_unavailable(canvas, intent)

    def _canvas_compute_pending(self, canvas) -> bool:
        return self._sampling.canvas_compute_pending(canvas)

    def _canvas_generations(self, canvas):
        return self._sampling.canvas_generations(canvas)

    def _stamp_sample(self, canvas, sample):
        return self._sampling.stamp_sample(canvas, sample)

    @staticmethod
    def _sample_matches_generation(sample, generation, revision) -> bool:
        return PinSampleEvaluator.sample_matches_generation(
            sample, generation, revision,
        )

    def _reconcile_sample(self, intent, sample, *, bound, hidden):
        return _facts_reconcile_sample(intent, sample, bound=bound, hidden=hidden)

    @staticmethod
    def _binding_key(binding):
        return _facts_binding_key(binding)

    @staticmethod
    def _key_in(key, pool) -> bool:
        return _facts_key_in(key, pool)

    @staticmethod
    def _hidden_channel_row(binding, existing, diagnostic=HIDDEN_CHANNEL_TEXT):
        return _facts_hidden_channel_row(binding, existing, diagnostic=diagnostic)

    @staticmethod
    def _sample_has_numeric(sample) -> bool:
        return _facts_sample_has_numeric(sample)

    @staticmethod
    def _sample_has_hidden(sample) -> bool:
        return _facts_sample_has_hidden(sample)

    @staticmethod
    def _sample_has_unchecked(sample) -> bool:
        return _facts_sample_has_unchecked(sample)

    @staticmethod
    def _hidden_keys_from_sample(sample):
        return _facts_hidden_keys_from_sample(sample)

    def _bound_identity_keys(self, canvas):
        return self._sampling.bound_identity_keys(canvas)

    def _hidden_identity_keys(self, canvas):
        return self._sampling.hidden_identity_keys(canvas)

    @staticmethod
    def _identity_key(identity):
        return _facts_identity_key(identity)

    def _widget_under_mouse(self):
        return self._router.widget_under_mouse()

    def _mouse_global(self) -> QPoint:
        return self._router.mouse_global()

    @staticmethod
    def _is_unmodified_p(event: QKeyEvent) -> bool:
        return PinKeyRouter._is_unmodified_p(event)

    @staticmethod
    def _is_under(widget, ancestor) -> bool:
        return PinKeyRouter._is_under(widget, ancestor)

    @staticmethod
    def _is_under_type(widget, cls) -> bool:
        return PinKeyRouter._is_under_type(widget, cls)

    @staticmethod
    def _canvas_from_widget(widget):
        return PinKeyRouter.canvas_from_widget(widget)

    def _snapshot_placement(self, canvas):
        fn = getattr(canvas, "snapshot_cursor_placement", None)
        return fn() if callable(fn) else None

    @staticmethod
    def _bindings_from_sample(sample):
        return PinSampleEvaluator.bindings_from_sample(sample)

    @staticmethod
    def _axis_identity(canvas, domain):
        return PinSampleEvaluator.axis_identity(canvas, domain)

    @staticmethod
    def _x_unit(canvas, domain) -> str:
        return PinSampleEvaluator.x_unit(canvas, domain)

    def _primary_html(self, intent) -> str:
        return pin_primary_html(intent)

    def _live_primary_html(self, domain, mode, sample) -> str:
        return pin_live_primary_html(domain, mode, sample)

    def _coord_html(self, intent) -> str:
        return pin_coord_html(intent)

    @staticmethod
    def _format_coord_html(domain, x, unit) -> str:
        return pin_format_coord_html(domain, x, unit)

    @staticmethod
    def _format_dual_html(domain, ax, bx, unit) -> str:
        return pin_format_dual_html(domain, ax, bx, unit)

    @staticmethod
    def _format_value(domain, value, unit) -> str:
        return pin_format_value(domain, value, unit)

    @staticmethod
    def _format_number(domain, value, unit) -> str:
        return pin_format_number(domain, value, unit)

    def _sync_overlay(self, owner) -> None:
        self._projector.sync_overlay(
            id(owner.canvas),
            owner.canvas,
            collection=owner.collection,
            samples=owner.samples,
            availability=owner.availability,
            axis_edit=owner.axis_edit,
        )

    def _overlay_records(self, owner):
        return self._projector.overlay_records(
            owner.canvas,
            collection=owner.collection,
            samples=owner.samples,
            availability=owner.availability,
            axis_edit=owner.axis_edit,
        )

    def _set_hover(self, canvas, target) -> None:
        self._projector.set_hover(canvas, target)

    def _success_text(self, intent) -> str:
        label = f"P{intent.ordinal} 已固定"
        unit = intent.x_unit
        if intent.mode == "single":
            value = _finite(intent.x)
            if value is None:
                return label
            if intent.domain == "time":
                return f"{label} · t={value:.4f}{unit or 's'}"
            if intent.domain == "channel":
                suffix = unit or ""
                return f"{label} · X={value:.4g}{suffix}"
            return f"{label} · f={value:g} {unit or 'Hz'}"
        a = _finite(intent.ax)
        b = _finite(intent.bx)
        if a is None or b is None:
            return label
        if intent.domain == "time":
            return f"{label} · A={a:.4f}s · B={b:.4f}s"
        if intent.domain == "channel":
            suffix = unit or ""
            return f"{label} · A={a:.4g}{suffix} · B={b:.4g}{suffix}"
        return f"{label} · A={a:g} Hz · B={b:g} Hz"
