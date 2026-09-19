"""P-key pin routing, capture transaction, and pinned CursorPill projection.

ChartStack holds one controller. Live readout still uses the existing
per-canvas pill; pinned records never share ``_cursor_rows_by_canvas``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import partial
from uuid import uuid4

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

from ..pg_canvas.frf_canvas import PgFrfCanvas
from ..pg_canvas.heatmap_canvas import PgHeatmapCanvas
from ..pg_canvas.line_canvas import PgLineCanvas
from ..pg_canvas.pinned_cursor_overlay import (
    PINNED_OFFSCREEN_TEXT,
    PinnedAxisLabel,
    PinnedOverlayEndpoint,
    PinnedOverlayRecord,
)
from ..cursor_display_model import CursorDisplayChannel, PinnedCursorSample
from ..pg_canvases import TimeDomainCanvasPG
from ..pinned_cursor_state import (
    DEFAULT_ANCHOR,
    PinnedCursorAnchor,
    PinnedCursorBinding,
    PinnedCursorCollection,
    PinnedCursorIntent,
    captures_equal,
    coords_equal,
    empty_collection,
    next_record,
    remove_record,
)
from ..plot_helpers import _cursor_identity_parts
from .cursor_display import (
    build_cursor_presentation,
    build_fft_cursor_presentation,
    build_frf_cursor_presentation,
    live_pin_hint_text,
)
from .cursor_pill import CursorPill
from .ultraview.author_widgets import is_text_input_widget

_PLACE_B_MESSAGE = "先放置 B，再按 P 固定"
_PLACE_AB_MESSAGE = "先放置 A、B，再按 P 固定"
_NUDGE_STEP = 28
_NUDGE_LIMIT = 72
_DUMMY_RECORD_ID = "00000000-0000-0000-0000-000000000001"

PIN_STATUS_READY = "ready"
PIN_STATUS_PENDING = "pending"
PIN_STATUS_UNAVAILABLE = "unavailable"
PIN_STATUS_INCOMPATIBLE_AXIS = "incompatible_axis"

HIDDEN_CHANNEL_TEXT = "已隐藏"
PENDING_TEXT = "更新中"
INCOMPATIBLE_AXIS_TEXT = "X 轴已更改"
UNAVAILABLE_TEXT = "无数据"


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


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
class _ClosedPin:
    intent: PinnedCursorIntent
    sample: object
    snapshot: dict
    pos: tuple[int, int]
    data_revision: int | None


@dataclass
class _OwnerState:
    canvas: object
    collection: PinnedCursorCollection
    pills: dict = field(default_factory=dict)
    samples: dict = field(default_factory=dict)
    axis_labels: dict = field(default_factory=dict)
    reserved_ordinal: int | None = None
    reserved_intent: PinnedCursorIntent | None = None
    undo: _ClosedPin | None = None
    live_suppressed: bool = False
    dual_hidden_placement: object = None
    availability: dict = field(default_factory=dict)
    pending_epoch: int = 0
    reproject_timer: object = None
    signal_conns: list = field(default_factory=list)


class PinnedCursorController(QObject):
    """Application-filter P routing and per-canvas pinned-pill projection."""

    pin_feedback = pyqtSignal(str)
    intent_changed = pyqtSignal()

    def __init__(self, host):
        super().__init__(host)
        self._host = host
        self._owners: dict[int, _OwnerState] = {}
        self._application_filter_installed = False
        self._last_mouse_global = QPoint()
        self._pin_key_armed = False
        self.user_intent_revision = 0
        self._install_application_filter()
        host.destroyed.connect(self._remove_application_filter)

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
        owner = _OwnerState(
            canvas=canvas,
            collection=empty_collection(),
            reproject_timer=timer,
        )
        self._owners[key] = owner
        overlay = getattr(canvas, "_pinned_overlay", None)
        if overlay is not None:
            overlay.set_layout_callback(partial(self._on_overlay_layout, canvas))
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

    def collection_for(self, canvas) -> PinnedCursorCollection:
        owner = self._owner(canvas, create=True)
        if owner is None:
            return empty_collection()
        return owner.collection

    def set_collection(self, canvas, collection) -> None:
        owner = self._owner(canvas, create=True)
        if owner is None:
            return
        if not isinstance(collection, PinnedCursorCollection):
            collection = empty_collection()
        self._cancel_reproject(owner)
        self._clear_pills(owner)
        owner.collection = collection
        owner.undo = None
        owner.reserved_ordinal = None
        owner.reserved_intent = None
        owner.availability.clear()
        self._reproject_now(owner, drop_unbound=False)

    def availability_for(self, canvas, record_id: str) -> str:
        owner = self._owner(canvas)
        if owner is None:
            return PIN_STATUS_READY
        return str(owner.availability.get(str(record_id), PIN_STATUS_READY))

    def clear_all(self) -> None:
        """Drop GUI, caches, undo, and records on every bound canvas.

        Used when the last source closes / the session is replaced. Does not
        emit ``intent_changed``; those paths already mark project dirty.
        """
        for owner in list(self._owners.values()):
            self._cancel_reproject(owner)
            overlay = getattr(owner.canvas, "_pinned_overlay", None)
            if overlay is not None:
                overlay.clear()
            self._clear_pills(owner)
            owner.collection = empty_collection()
            owner.undo = None
            owner.reserved_ordinal = None
            owner.reserved_intent = None
            owner.live_suppressed = False
            owner.dual_hidden_placement = None
            owner.availability.clear()

    @staticmethod
    def filter_collection_identities(
        collection,
        *,
        fids=(),
        channels=(),
    ) -> PinnedCursorCollection:
        """Drop closed identities from records. Empty binding set → drop record."""
        if collection is None or not isinstance(collection, PinnedCursorCollection):
            return empty_collection()
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
            filtered = self.filter_collection_identities(
                owner.collection, fids=fids, channels=channels,
            )
            if filtered is owner.collection:
                continue
            removed = {
                item.record_id for item in owner.collection.records
            } - {item.record_id for item in filtered.records}
            for record_id in removed:
                pill = owner.pills.pop(record_id, None)
                owner.samples.pop(record_id, None)
                owner.availability.pop(record_id, None)
                self._destroy_pill(pill)
            owner.collection = filtered
            if owner.undo is not None and owner.undo.intent.record_id in removed:
                owner.undo = None
            self._reproject_now(owner)

    def pills_for(self, canvas) -> tuple[CursorPill, ...]:
        owner = self._owner(canvas)
        if owner is None:
            return ()
        return tuple(
            pill for pill in owner.pills.values() if _widget_alive(pill)
        )

    def axis_labels_for(self, canvas) -> tuple[PinnedAxisLabel, ...]:
        owner = self._owner(canvas)
        if owner is None:
            return ()
        return tuple(
            label for label in owner.axis_labels.values() if _widget_alive(label)
        )

    def capture_fingerprint_for(self, canvas) -> tuple:
        """Stable pin presentation digest. Hover highlight is omitted."""
        owner = self._owner(canvas)
        if owner is None:
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
        owner = self._owner(canvas)
        if owner is None:
            return
        pill = owner.pills.get(str(record_id))
        if _widget_alive(pill):
            pill.raise_()
            pill.flash_highlight()
        overlay = getattr(canvas, "_pinned_overlay", None)
        if overlay is not None:
            overlay.set_highlight(str(record_id))
        for label in owner.axis_labels.values():
            if not _widget_alive(label):
                continue
            label.set_highlighted(str(record_id) in label.record_ids())

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
        host = self._host
        for owner in list(self._owners.values()):
            canvas = owner.canvas
            if not _widget_alive(canvas):
                continue
            on_screen = bool(host._cursor_source_on_screen(canvas))
            card = host._card_for_canvas(canvas)
            if (
                card is getattr(host, "_secondary_card", None)
                and not host.split_active()
            ):
                on_screen = False
            for pill in list(owner.pills.values()):
                if not _widget_alive(pill):
                    continue
                if not on_screen:
                    pill.setVisible(False)
                    continue
                host._sync_pill_safe_rect(pill, card)
                if pill._display_projection is not None:
                    pill.reflow_to_parent()
                self._apply_anchor(pill, owner.collection, pill_record_id=self._record_id_for(owner, pill))
                pill.setVisible(True)
                pill.raise_()
            if on_screen:
                self._nudge_live_from_pins(owner)
            overlay = getattr(canvas, "_pinned_overlay", None)
            if overlay is not None:
                overlay.reproject()

    # ---- P routing ----------------------------------------------------------

    def eventFilter(self, watched, event):  # noqa: N802
        if isinstance(watched, CursorPill):
            self._on_pinned_pill_event(watched, event)
        etype = event.type()
        if etype in (QEvent.MouseMove, QEvent.HoverMove):
            global_pos = self._event_global_pos(event)
            if global_pos is not None:
                self._last_mouse_global = QPoint(global_pos)
            return super().eventFilter(watched, event)
        if etype not in (QEvent.ShortcutOverride, QEvent.KeyPress):
            return super().eventFilter(watched, event)
        if not self._is_unmodified_p(event):
            return super().eventFilter(watched, event)
        if event.isAutoRepeat():
            return super().eventFilter(watched, event)
        eligible = self._pin_eligible()
        if etype == QEvent.ShortcutOverride:
            if eligible:
                event.accept()
                self._pin_key_armed = True
                return True
            self._pin_key_armed = False
            return super().eventFilter(watched, event)
        if not eligible:
            self._pin_key_armed = False
            return super().eventFilter(watched, event)
        self._pin_key_armed = False
        self._pin_at_mouse()
        event.accept()
        return True

    def _install_application_filter(self) -> None:
        if self._application_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._application_filter_installed = True

    def _remove_application_filter(self) -> None:
        if not self._application_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass
        self._application_filter_installed = False

    def close(self) -> None:
        self._remove_application_filter()
        for key in list(self._owners):
            self._drop_owner(key, destroy_pills=True)

    # ---- transaction --------------------------------------------------------

    def _pin_at_mouse(self) -> None:
        hit = self._hit_owner()
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

    def _pin_single(self, owner, canvas, domain, viewport_pos) -> None:
        x = self._physical_x(canvas, domain, viewport_pos)
        if x is None:
            return
        sample = self._evaluate(canvas, domain, mode="single", x=x)
        if not self._sample_has_result(sample):
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
        if self._highlight_duplicate(owner, intent):
            self._consume_live(owner, canvas, dual=False)
            return
        collection, record = self._commit_record(owner, intent)
        owner.collection = collection
        owner.samples[record.record_id] = sample
        owner.availability[record.record_id] = PIN_STATUS_READY
        self._project_record(owner, record, sample, inherit_live=live)
        self._sync_overlay(owner)
        self._consume_live(owner, canvas, dual=False)
        self._mark_user_intent()
        self.pin_feedback.emit(self._success_text(record))

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
        if self._highlight_duplicate(owner, intent):
            self._consume_live(owner, canvas, dual=True, placement=placement)
            return
        collection, record = self._commit_record(owner, intent)
        owner.collection = collection
        owner.samples[record.record_id] = sample
        owner.availability[record.record_id] = PIN_STATUS_READY
        self._project_record(owner, record, sample, inherit_live=live)
        self._sync_overlay(owner)
        self._consume_live(owner, canvas, dual=True, placement=placement)
        self._mark_user_intent()
        self.pin_feedback.emit(self._success_text(record))

    def _commit_record(self, owner, intent):
        reserved = owner.reserved_ordinal
        reserved_intent = owner.reserved_intent
        owner.reserved_ordinal = None
        owner.reserved_intent = None
        if (
            reserved is not None
            and reserved_intent is not None
            and captures_equal(reserved_intent, intent)
            and all(item.ordinal != reserved for item in owner.collection.records)
        ):
            record = replace(
                intent,
                record_id=str(uuid4()),
                ordinal=int(reserved),
            )
            collection = replace(
                owner.collection,
                records=owner.collection.records + (record,),
            )
            return collection, record
        return next_record(owner.collection, intent)

    def _highlight_duplicate(self, owner, intent) -> bool:
        for existing in owner.collection.records:
            if not captures_equal(existing, intent):
                continue
            pill = owner.pills.get(existing.record_id)
            if _widget_alive(pill):
                pill.flash_highlight()
            overlay = getattr(owner.canvas, "_pinned_overlay", None)
            if overlay is not None:
                overlay.set_highlight(existing.record_id)
            self.pin_feedback.emit(f"P{existing.ordinal} 已在此位置")
            return True
        return False

    def _consume_live(self, owner, canvas, *, dual, placement=None) -> None:
        owner.live_suppressed = True
        owner.dual_hidden_placement = placement if dual else None
        consume = getattr(self._host, "consume_live_cursor_pill", None)
        if callable(consume):
            consume(canvas)
        self._nudge_live_from_pins(owner)

    # ---- unpin / close / undo ----------------------------------------------

    def unpin_record(self, canvas, record_id: str) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        pill = owner.pills.pop(record_id, None)
        snapshot = pill.snapshot() if _widget_alive(pill) else {}
        pos = (pill.x(), pill.y()) if _widget_alive(pill) else (0, 0)
        owner.collection = remove_record(owner.collection, record_id)
        owner.samples.pop(record_id, None)
        owner.availability.pop(record_id, None)
        owner.reserved_ordinal = intent.ordinal
        owner.reserved_intent = intent
        owner.undo = None
        owner.live_suppressed = False
        self._destroy_pill(pill)
        self._sync_overlay(owner)
        self._mark_user_intent()
        if intent.mode == "dual":
            restore = getattr(canvas, "restore_cursor_placement", None)
            if callable(restore):
                restore({"ax": intent.ax, "bx": intent.bx})
        restore_live = getattr(self._host, "restore_live_from_pin", None)
        if callable(restore_live):
            restore_live(canvas, snapshot, pos, intent.mode)
        else:
            self._host.set_cursor_mode_for_canvas(canvas, intent.mode)
        self.pin_feedback.emit(f"P{intent.ordinal} 已取消固定")

    def close_record(self, canvas, record_id: str) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        pill = owner.pills.pop(record_id, None)
        snapshot = pill.snapshot() if _widget_alive(pill) else {}
        pos = (pill.x(), pill.y()) if _widget_alive(pill) else (0, 0)
        sample = owner.samples.pop(record_id, None)
        owner.availability.pop(record_id, None)
        owner.collection = remove_record(owner.collection, record_id)
        owner.undo = _ClosedPin(
            intent=intent,
            sample=sample,
            snapshot=snapshot,
            pos=pos,
            data_revision=getattr(sample, "data_revision", None),
        )
        self._destroy_pill(pill)
        self._sync_overlay(owner)
        self._mark_user_intent()
        self.pin_feedback.emit(f"已关闭 P{intent.ordinal}")

    def undo_close(self, canvas=None) -> None:
        owner = self._owner(canvas) if canvas is not None else None
        if owner is None:
            for item in self._owners.values():
                if item.undo is not None:
                    owner = item
                    canvas = item.canvas
                    break
        if owner is None or owner.undo is None or not _widget_alive(canvas):
            return
        closed = owner.undo
        current = self._evaluate_intent(canvas, closed.intent)
        current_rev = getattr(current, "data_revision", None)
        if (
            closed.data_revision is not None
            and current_rev is not None
            and current_rev != closed.data_revision
        ):
            owner.undo = None
            self.pin_feedback.emit("无法撤销：数据已更新")
            return
        owner.undo = None
        intent = closed.intent
        if any(item.record_id == intent.record_id for item in owner.collection.records):
            return
        owner.collection = replace(
            owner.collection,
            records=owner.collection.records + (intent,),
        )
        sample = current if self._sample_has_result(current) else closed.sample
        owner.samples[intent.record_id] = sample
        status = self._status_for_sample(owner.canvas, intent, sample)
        owner.availability[intent.record_id] = status
        self._project_record(owner, intent, sample, availability=status)
        self._sync_overlay(owner)
        self._mark_user_intent()
        pill = owner.pills.get(intent.record_id)
        if _widget_alive(pill) and closed.snapshot:
            pill.restore_snapshot(closed.snapshot)
            pill.set_pin_role("pinned")
            pill.move(*closed.pos)
            pill.mark_user_placed(True)
            pill.setVisible(True)
        self.pin_feedback.emit(f"已恢复 P{intent.ordinal}")

    # ---- eligibility / hit test --------------------------------------------

    def _pin_eligible(self) -> bool:
        return self._hit_owner() is not None

    def _hit_owner(self):
        app = QApplication.instance()
        if app is None:
            return None
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return None
        if is_text_input_widget(app.focusWidget()):
            return None
        host = self._host
        ultraview = getattr(host, "page_ultraview", None)
        widget = self._widget_under_mouse()
        if widget is None:
            return None
        if ultraview is not None and self._is_under(widget, ultraview):
            return None
        if self._is_under_type(widget, CursorPill):
            return None
        canvas = self._canvas_from_widget(widget)
        if canvas is None or isinstance(canvas, PgHeatmapCanvas):
            return None
        if not _widget_alive(canvas) or not canvas.isVisible() or not canvas.isVisibleTo(host):
            return None
        if id(canvas) not in self._owners:
            if not self._canvas_belongs_to_host(canvas):
                return None
            self.bind_canvas(canvas)
        if not host._cursor_source_on_screen(canvas):
            return None
        mode = host._cursor_mode_for_canvas(canvas)
        if mode not in {"single", "dual"}:
            return None
        if self._gesture_in_progress(canvas):
            return None
        domain = self._domain_for(canvas)
        if domain is None:
            return None
        viewport = _canvas_viewport(canvas)
        if viewport is None or not viewport.isVisible():
            return None
        global_pos = self._mouse_global()
        local = viewport.mapFromGlobal(global_pos)
        if not viewport.rect().contains(local):
            return None
        if not self._in_data_viewport(canvas, domain, local):
            return None
        return canvas, domain, local

    def _gesture_in_progress(self, canvas) -> bool:
        app = QApplication.instance()
        if app is not None and app.mouseButtons() != Qt.NoButton:
            return True
        live = self._live_pill(canvas)
        if live is not None and live.is_dragging():
            return True
        owner = self._owner(canvas)
        if owner is not None:
            for pill in owner.pills.values():
                if _widget_alive(pill) and pill.is_dragging():
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
        if domain in {"time", "channel"}:
            return _finite(self._physical_x(canvas, domain, viewport_pos)) is not None
        if domain == "frequency":
            host_rect = getattr(canvas, "frequency_cursor_host_rect", None)
            rect = host_rect() if callable(host_rect) else None
            if rect is None or not QRect(rect).isValid():
                return False
            try:
                mapped = canvas.mapTo(canvas._glw.viewport(), rect.center())
            except (RuntimeError, TypeError, AttributeError):
                mapped = viewport_pos
            if isinstance(rect, QRect):
                top_left = canvas.mapTo(canvas._glw.viewport(), rect.topLeft())
                bottom_right = canvas.mapTo(canvas._glw.viewport(), rect.bottomRight())
                local_rect = QRect(top_left, bottom_right)
                if not local_rect.contains(viewport_pos):
                    return False
            return _finite(self._physical_x(canvas, domain, viewport_pos)) is not None
        if domain == "frf":
            return _finite(self._physical_x(canvas, domain, viewport_pos)) is not None
        return False

    def _physical_x(self, canvas, domain, viewport_pos):
        if domain in {"time", "channel"}:
            fn = getattr(canvas, "data_x_from_viewport_pos", None)
            return _finite(fn(viewport_pos) if callable(fn) else None)
        glw = getattr(canvas, "_glw", None)
        if glw is None:
            return None
        try:
            scene_pos = glw.mapToScene(viewport_pos)
        except (RuntimeError, TypeError):
            return None
        if domain == "frequency":
            plot = getattr(canvas, "_plot_amp", None)
            vb = getattr(plot, "vb", None)
            if vb is None:
                return None
            try:
                if not vb.sceneBoundingRect().contains(scene_pos):
                    return None
                return _finite(vb.mapSceneToView(scene_pos).x())
            except (RuntimeError, TypeError, ValueError):
                return None
        plots = getattr(canvas, "plots", None) or ()
        for plot in plots:
            vb = getattr(plot, "vb", None)
            if vb is None:
                continue
            try:
                if not vb.sceneBoundingRect().contains(scene_pos):
                    continue
                view_x = float(vb.mapSceneToView(scene_pos).x())
            except (RuntimeError, TypeError, ValueError):
                continue
            converter = getattr(canvas, "_view_x_to_hz", None)
            if callable(converter):
                return _finite(converter(view_x))
            return _finite(view_x)
        return None

    def _domain_for(self, canvas) -> str | None:
        if isinstance(canvas, PgFrfCanvas):
            return "frf"
        if isinstance(canvas, PgLineCanvas):
            return "frequency"
        if isinstance(canvas, TimeDomainCanvasPG):
            checker = getattr(canvas, "cursor_x_mode", None)
            if callable(checker) and checker():
                return "channel"
            return "time"
        return None

    # ---- evaluate / project -------------------------------------------------

    def _evaluate(self, canvas, domain, *, mode, x=None, ax=None, bx=None):
        if mode == "single":
            if domain in {"time", "channel"}:
                fn = self._sample_fn(canvas, "evaluate_single_cursor_sample")
                if callable(fn):
                    return fn(x)
                rows = canvas.evaluate_single_cursor(x)
                return self._wrap_channels(domain, "single", x=x, channels=rows)
            fn = getattr(canvas, "evaluate_frequency_cursor_sample", None)
            if callable(fn):
                return fn(x)
            result = canvas.evaluate_frequency_cursor(x)
            if result is None:
                return None
            if domain == "frf":
                return self._wrap_frf("single", result)
            snapped, channels = result
            return self._wrap_channels(
                "frequency", "single", x=snapped, channels=channels,
            )
        if domain in {"time", "channel"}:
            fn = self._sample_fn(canvas, "evaluate_dual_cursor_sample")
            if callable(fn):
                return fn(ax, bx)
            rows = canvas.evaluate_dual_cursor(ax, bx)
            return self._wrap_channels(domain, "dual", ax=ax, bx=bx, channels=rows)
        fn = getattr(canvas, "evaluate_dual_frequency_cursor_sample", None)
        if callable(fn):
            return fn(ax, bx)
        result = canvas.evaluate_dual_frequency_cursor(ax, bx)
        if result is None:
            return None
        if domain == "frf":
            return self._wrap_frf("dual", result)
        a_value, b_value, channels = result
        return self._wrap_channels(
            "frequency", "dual", ax=a_value, bx=b_value, channels=channels,
        )

    def _evaluate_intent(self, canvas, intent):
        if not self._axis_compatible(canvas, intent):
            return None
        domain = intent.domain
        if intent.mode == "single":
            sample = self._evaluate(canvas, domain, mode="single", x=intent.x)
        else:
            sample = self._evaluate(
                canvas, domain, mode="dual", ax=intent.ax, bx=intent.bx,
            )
        return self._stamp_sample(canvas, sample)

    @staticmethod
    def _sample_fn(canvas, name):
        fn = getattr(canvas, name, None)
        if callable(fn):
            return fn
        cursor = getattr(canvas, "_cursor", None)
        fn = getattr(cursor, name, None)
        return fn if callable(fn) else None

    @staticmethod
    def _wrap_channels(domain, mode, *, x=None, ax=None, bx=None, channels=()):
        return PinnedCursorSample(
            domain=domain,
            mode=mode,
            x=_finite(x),
            ax=_finite(ax),
            bx=_finite(bx),
            channels=tuple(channels or ()),
        )

    @staticmethod
    def _wrap_frf(mode, sample):
        if sample is None:
            return None
        if mode == "single":
            return PinnedCursorSample(
                domain="frf",
                mode="single",
                x=_finite(getattr(sample, "frequency_hz", None)),
                frf_sample=sample,
            )
        return PinnedCursorSample(
            domain="frf",
            mode="dual",
            ax=None if sample.a is None else _finite(sample.a.frequency_hz),
            bx=None if sample.b is None else _finite(sample.b.frequency_hz),
            frf_sample=sample,
        )

    @staticmethod
    def _sample_has_result(sample) -> bool:
        if sample is None:
            return False
        if getattr(sample, "frf_sample", None) is not None:
            return True
        if tuple(getattr(sample, "channels", ()) or ()):
            return True
        return bool(str(getattr(sample, "diagnostic", "") or "").strip())

    def _draft_intent(
        self, canvas, domain, mode, live, *, x=None, ax=None, bx=None, sample=None,
    ):
        unit = self._x_unit(canvas, domain)
        presentation = "full"
        if live is not None and live.display_mode() in {"full", "mini"}:
            presentation = live.display_mode()
        anchor = DEFAULT_ANCHOR
        if live is not None and live.isVisible():
            anchor = self._anchor_from_pill(live)
        payload = {
            "mode": mode,
            "domain": domain,
            "x_unit": unit,
            "bindings": self._bindings_from_sample(sample),
            "presentation": presentation,
            "anchor": anchor,
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
        canvas = owner.canvas
        host = self._host
        stack = host.stack
        status = availability or owner.availability.get(
            intent.record_id, PIN_STATUS_READY,
        )
        pill = owner.pills.get(intent.record_id)
        if not _widget_alive(pill):
            pill = CursorPill(stack)
            pill.set_pin_role("pinned")
            pill.setFocusPolicy(Qt.TabFocus)
            pill.installEventFilter(self)
            pill.unpin_requested.connect(
                partial(self.unpin_record, canvas, intent.record_id)
            )
            pill.close_requested.connect(
                partial(self.close_record, canvas, intent.record_id)
            )
            pill.moved.connect(
                partial(self._on_pinned_moved, canvas, intent.record_id)
            )
            pill.display_mode_changed.connect(
                partial(self._on_pinned_display_mode, canvas, intent.record_id)
            )
            owner.pills[intent.record_id] = pill
        pill.set_ordinal(intent.ordinal)
        pill.set_pin_role("pinned")
        pill.set_live_hint("")
        card = host._card_for_canvas(canvas)
        host._sync_pill_safe_rect(pill, card)
        primary, projection = self._pill_content(intent, sample, host, status)
        if inherit_live is not None and _widget_alive(inherit_live):
            pill.mark_user_placed(True)
            pill.move(inherit_live.x(), inherit_live.y())
        else:
            pill.mark_user_placed(intent.anchor != DEFAULT_ANCHOR)

        def update():
            pill._primary_original = primary
            if projection is not None:
                pill.set_display_projection(projection)
            else:
                pill.set_display_projection(None)
                pill.set_primary(primary)
            pill.setVisible(True)

        host._update_pill_content(pill, card, update)
        if inherit_live is None or not _widget_alive(inherit_live):
            self._apply_anchor(pill, owner.collection, pill_record_id=intent.record_id)
        else:
            self._store_anchor_from_pill(owner, intent.record_id, pill)
        pill.raise_()
        self._nudge_live_from_pins(owner)

    def _pill_content(self, intent, sample, host, status):
        if status == PIN_STATUS_PENDING:
            return self._status_primary_html(intent, PENDING_TEXT), None
        if status == PIN_STATUS_INCOMPATIBLE_AXIS:
            return self._status_primary_html(intent, INCOMPATIBLE_AXIS_TEXT), None
        if status == PIN_STATUS_UNAVAILABLE:
            diagnostic = str(getattr(sample, "diagnostic", "") or "").strip()
            text = diagnostic or UNAVAILABLE_TEXT
            return self._status_primary_html(intent, text), None
        return self._primary_html(intent), self._presentation_for(intent, sample, host)

    def _status_primary_html(self, intent, status_text) -> str:
        from html import escape

        tag = (
            f'<span style="color:#416faa;">P{intent.ordinal}</span>'
            '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
        )
        return (
            tag
            + f'<span style="color:#64748b;">{escape(str(status_text))}</span>'
        )

    def _presentation_for(self, intent, sample, host):
        mini = intent.presentation == "mini"
        if intent.domain == "frf":
            frf = getattr(sample, "frf_sample", None) if sample is not None else None
            return build_frf_cursor_presentation(frf, mini=mini)
        channels = tuple(getattr(sample, "channels", ()) or ()) if sample is not None else ()
        if intent.domain == "frequency":
            return build_fft_cursor_presentation(
                channels, cursor_mode=intent.mode, mini=mini,
            )
        x_mode = "custom" if intent.domain == "channel" else "time"
        options = host._cursor_display_options
        return build_cursor_presentation(
            channels, options, cursor_mode=intent.mode, x_mode=x_mode, mini=mini,
        )

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

    # ---- geometry -----------------------------------------------------------

    def _on_pinned_moved(self, canvas, record_id) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        pill = owner.pills.get(record_id)
        if not _widget_alive(pill):
            return
        self._store_anchor_from_pill(owner, record_id, pill)

    def _on_pinned_display_mode(self, canvas, record_id, mode) -> None:
        owner = self._owner(canvas)
        if owner is None:
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
        pill = owner.pills.get(record_id)
        if not _widget_alive(pill):
            return
        status = owner.availability.get(record_id, PIN_STATUS_READY)
        if status != PIN_STATUS_READY:
            self._project_record(owner, updated, sample, availability=status)
            return
        projection = self._presentation_for(updated, sample, self._host)
        pill._primary_original = self._primary_html(updated)
        if projection is not None:
            pill.set_display_projection(projection)

    def _store_anchor_from_pill(self, owner, record_id, pill) -> None:
        intent = self._intent(owner, record_id)
        if intent is None:
            return
        anchor = self._anchor_from_pill(pill)
        if anchor == intent.anchor:
            return
        updated = replace(intent, anchor=anchor)
        records = tuple(
            updated if item.record_id == record_id else item
            for item in owner.collection.records
        )
        owner.collection = replace(owner.collection, records=records)
        self._mark_user_intent()

    def _apply_anchor(self, pill, collection, *, pill_record_id) -> None:
        intent = next(
            (item for item in collection.records if item.record_id == pill_record_id),
            None,
        )
        if intent is None:
            return
        safe = pill.safe_rect()
        if not safe.isValid() or safe.width() <= 0 or safe.height() <= 0:
            return
        x, y = self._pos_from_anchor(intent.anchor, pill, safe)
        pill.move(x, y)

    @staticmethod
    def _pos_from_anchor(anchor, pill, safe):
        width = max(1, safe.width() - 1)
        height = max(1, safe.height() - 1)
        nx = _finite(anchor.nx)
        ny = _finite(anchor.ny)
        if nx is None:
            nx = 1.0
        if ny is None:
            ny = 0.0
        if anchor.h_edge == "right":
            x = int(round(safe.left() + nx * width)) - pill.width() + 1
        else:
            x = int(round(safe.left() + nx * width))
        if anchor.v_edge == "bottom":
            y = int(round(safe.top() + ny * height)) - pill.height() + 1
        else:
            y = int(round(safe.top() + ny * height))
        x = max(safe.left(), min(x, safe.right() - pill.width() + 1))
        y = max(safe.top(), min(y, safe.bottom() - pill.height() + 1))
        return x, y

    @staticmethod
    def _anchor_from_pill(pill) -> PinnedCursorAnchor:
        safe = pill.safe_rect()
        if not safe.isValid() or safe.width() <= 1 or safe.height() <= 1:
            return DEFAULT_ANCHOR
        nx = (pill.geometry().right() - safe.left()) / float(safe.width() - 1)
        ny = (pill.y() - safe.top()) / float(safe.height() - 1)
        return PinnedCursorAnchor(
            h_edge="right",
            v_edge="top",
            nx=float(nx),
            ny=float(ny),
        )

    def _nudge_live_from_pins(self, owner) -> None:
        live = self._live_pill(owner.canvas)
        if live is None or not live.isVisible() or live.is_user_placed():
            return
        safe = live.safe_rect()
        if not safe.isValid():
            return
        geo = live.geometry()
        shifted = 0
        for pill in owner.pills.values():
            if not _widget_alive(pill) or not pill.isVisible():
                continue
            title = QRect(pill.x(), pill.y(), pill.width(), min(26, pill.height()))
            if not geo.intersects(title.adjusted(-6, -6, 6, 6)):
                continue
            new_y = min(title.bottom() + 8, safe.bottom() - live.height() + 1)
            new_x = geo.x()
            if new_y <= geo.y() or shifted >= _NUDGE_LIMIT:
                new_x = max(safe.left(), geo.x() - _NUDGE_STEP)
                new_y = geo.y()
            live.move(new_x, new_y)
            geo = live.geometry()
            shifted += _NUDGE_STEP

    # ---- host / widget helpers ---------------------------------------------

    def _owner(self, canvas, *, create=False):
        if canvas is None:
            return None
        owner = self._owners.get(id(canvas))
        if owner is None and create:
            self.bind_canvas(canvas)
            owner = self._owners.get(id(canvas))
        return owner

    def _intent(self, owner, record_id):
        for item in owner.collection.records:
            if item.record_id == record_id:
                return item
        return None

    @staticmethod
    def _record_id_for(owner, pill):
        for record_id, item in owner.pills.items():
            if item is pill:
                return record_id
        return None

    def _live_pill(self, canvas):
        fn = getattr(self._host, "_pill_for_canvas", None)
        if not callable(fn):
            return None
        pill = fn(canvas)
        return pill if _widget_alive(pill) else None

    def _canvas_belongs_to_host(self, canvas) -> bool:
        card = self._host._card_for_canvas(canvas)
        return getattr(card, "canvas", None) is canvas

    def _drop_owner(self, key, *, destroy_pills) -> None:
        owner = self._owners.pop(key, None)
        if owner is None:
            return
        self._cancel_reproject(owner)
        self._disconnect_owner_signals(owner)
        overlay = None
        canvas = owner.canvas
        if _widget_alive(canvas):
            try:
                overlay = getattr(canvas, "_pinned_overlay", None)
            except RuntimeError:
                overlay = None
        if overlay is not None:
            try:
                overlay.set_layout_callback(None)
                if destroy_pills:
                    overlay.clear()
            except RuntimeError:
                pass
        if destroy_pills:
            self._clear_pills(owner)
        timer = owner.reproject_timer
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
            owner.reproject_timer = None

    def _on_canvas_destroyed(self, key, *_args) -> None:
        self._drop_owner(key, destroy_pills=True)

    def _clear_pills(self, owner) -> None:
        for pill in list(owner.pills.values()):
            self._destroy_pill(pill)
        owner.pills.clear()
        owner.samples.clear()
        owner.availability.clear()
        for label in list(owner.axis_labels.values()):
            self._destroy_axis_label(label)
        owner.axis_labels.clear()

    @staticmethod
    def _destroy_pill(pill) -> None:
        if not _widget_alive(pill):
            return
        pill.hide()
        pill.setParent(None)
        pill.deleteLater()

    @staticmethod
    def _destroy_axis_label(label) -> None:
        if not _widget_alive(label):
            return
        label.hide()
        label.setParent(None)
        label.deleteLater()

    def _mark_user_intent(self) -> None:
        self.user_intent_revision += 1
        self.intent_changed.emit()

    @staticmethod
    def _disconnect_owner_signals(owner) -> None:
        for signal, slot in list(owner.signal_conns):
            try:
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
        if owner is None or not owner.collection.records:
            return
        if not _widget_alive(owner.canvas):
            return
        self._mark_records_pending(owner)
        if self._bound_identity_keys(owner.canvas) or getattr(
            owner.canvas, "chart_rebuilt", None,
        ) is None:
            self._schedule_reproject(owner)

    def _on_chart_rebuilt(self, key, *_args) -> None:
        owner = self._owners.get(key)
        if owner is None or not owner.collection.records:
            return
        if not _widget_alive(owner.canvas):
            return
        self._cancel_reproject(owner)
        self._reproject_now(owner, drop_unbound=True)

    def _reproject_owner(self, key) -> None:
        owner = self._owners.get(key)
        if owner is None:
            return
        self._reproject_now(owner)

    def _mark_records_pending(self, owner) -> None:
        for intent in owner.collection.records:
            owner.availability[intent.record_id] = PIN_STATUS_PENDING
            self._project_record(
                owner, intent, owner.samples.get(intent.record_id),
                availability=PIN_STATUS_PENDING,
            )
        self._sync_overlay(owner)

    def _reproject_now(self, owner, *, drop_unbound=None) -> None:
        canvas = owner.canvas
        if not _widget_alive(canvas):
            return
        if self._canvas_compute_pending(canvas):
            self._mark_records_pending(owner)
            return
        kept = []
        dropped = []
        generation, revision = self._canvas_generations(canvas)
        bound = self._bound_identity_keys(canvas)
        hidden = self._hidden_identity_keys(canvas)
        if drop_unbound is None:
            drop_unbound = bool(bound)
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
                sample, next_intent, dropped_record = self._reconcile_sample(
                    intent, sample, bound=bound, hidden=hidden,
                    drop_unbound=drop_unbound,
                )
                if dropped_record:
                    dropped.append(intent.record_id)
                    continue
                if sample is None or (
                    not self._sample_has_numeric(sample)
                    and not self._sample_has_hidden(sample)
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
                else:
                    status = PIN_STATUS_READY
                owner.samples[intent.record_id] = sample
            owner.availability[intent.record_id] = status
            kept.append(next_intent)
            self._project_record(
                owner, next_intent, owner.samples.get(next_intent.record_id),
                availability=status,
            )
        if dropped:
            for record_id in dropped:
                pill = owner.pills.pop(record_id, None)
                owner.samples.pop(record_id, None)
                owner.availability.pop(record_id, None)
                self._destroy_pill(pill)
            if owner.undo is not None and owner.undo.intent.record_id in dropped:
                owner.undo = None
        if tuple(kept) != owner.collection.records:
            owner.collection = replace(owner.collection, records=tuple(kept))
        self._sync_overlay(owner)

    def _axis_status(self, canvas, intent) -> str:
        if not self._axis_compatible(canvas, intent):
            return PIN_STATUS_INCOMPATIBLE_AXIS
        if self._log_unavailable(canvas, intent):
            return PIN_STATUS_UNAVAILABLE
        return PIN_STATUS_READY

    def _status_for_sample(self, canvas, intent, sample) -> str:
        status = self._axis_status(canvas, intent)
        if status != PIN_STATUS_READY:
            return status
        if sample is None or (
            not self._sample_has_numeric(sample)
            and not self._sample_has_hidden(sample)
        ):
            return PIN_STATUS_UNAVAILABLE
        return PIN_STATUS_READY

    def _axis_compatible(self, canvas, intent) -> bool:
        current = self._domain_for(canvas)
        if intent.domain in {"frequency", "frf"}:
            return current == intent.domain
        if intent.domain == "time":
            return current == "time"
        if intent.domain == "channel":
            if current != "channel":
                return False
            wanted = intent.axis_identity
            if wanted is None:
                return True
            return self._axis_identity(canvas, "channel") == wanted
        return current == intent.domain

    def _log_unavailable(self, canvas, intent) -> bool:
        checker = getattr(canvas, "_is_log_frequency", None)
        if not callable(checker) or not checker():
            return False
        if intent.domain not in {"frequency", "frf"}:
            return False
        values = (intent.x,) if intent.mode == "single" else (intent.ax, intent.bx)
        return any(value is not None and _finite(value) is not None and value <= 0 for value in values)

    def _canvas_compute_pending(self, canvas) -> bool:
        state = getattr(canvas, "state", None)
        token = state() if callable(state) else None
        return token in {"progress", "stale"}

    def _canvas_generations(self, canvas):
        binding = getattr(canvas, "_spectrum_display_generation", None)
        if binding is None:
            binding = getattr(canvas, "_interaction_generation", None)
        revision = getattr(canvas, "_spectrum_display_revision", None)
        if revision is None:
            revision = getattr(canvas, "_cursor_data_revision", None)
        if revision is None:
            cursor = getattr(canvas, "_cursor", None)
            revision = getattr(cursor, "_cursor_data_revision", None)
        try:
            binding = int(binding) if binding is not None else None
        except (TypeError, ValueError):
            binding = None
        try:
            revision = int(revision) if revision is not None else None
        except (TypeError, ValueError):
            revision = None
        return binding, revision

    def _stamp_sample(self, canvas, sample):
        if sample is None or not isinstance(sample, PinnedCursorSample):
            return sample
        generation, revision = self._canvas_generations(canvas)
        updates = {}
        if sample.binding_generation is None and generation is not None:
            updates["binding_generation"] = generation
        if sample.data_revision is None and revision is not None:
            updates["data_revision"] = revision
        return replace(sample, **updates) if updates else sample

    @staticmethod
    def _sample_matches_generation(sample, generation, revision) -> bool:
        if sample is None:
            return False
        sample_gen = getattr(sample, "binding_generation", None)
        sample_rev = getattr(sample, "data_revision", None)
        if sample_gen is not None and generation is not None and sample_gen != generation:
            return False
        if sample_rev is not None and revision is not None and sample_rev != revision:
            return False
        return True

    def _reconcile_sample(self, intent, sample, *, bound, hidden, drop_unbound):
        if not intent.bindings:
            return sample, intent, False
        evaluated = {}
        for channel in tuple(getattr(sample, "channels", ()) or ()) if sample is not None else ():
            key = self._identity_key(getattr(channel, "identity", None))
            if key is not None:
                evaluated[key] = channel
        kept_bindings = []
        channels = []
        for binding in intent.bindings:
            key = (str(binding.fid), str(binding.channel))
            is_bound = key in bound or self._key_in(key, bound)
            is_hidden = key in hidden or self._key_in(key, hidden)
            if not is_bound and not is_hidden:
                if drop_unbound:
                    continue
                kept_bindings.append(binding)
                continue
            kept_bindings.append(binding)
            match = evaluated.get(key)
            if match is None:
                for ekey, channel in evaluated.items():
                    if self._key_in(key, {ekey}):
                        match = channel
                        break
            if is_hidden:
                channels.append(self._hidden_channel_row(binding, match))
                continue
            if match is not None:
                channels.append(match)
                continue
            channels.append(self._hidden_channel_row(binding, None, diagnostic=UNAVAILABLE_TEXT))
        if not kept_bindings:
            return None, intent, True
        next_intent = intent
        if tuple(kept_bindings) != intent.bindings:
            next_intent = replace(intent, bindings=tuple(kept_bindings))
        if sample is None:
            sample = PinnedCursorSample(
                domain=intent.domain,
                mode=intent.mode,
                x=intent.x,
                ax=intent.ax,
                bx=intent.bx,
                channels=tuple(channels),
            )
        else:
            extrema = tuple(
                item for item in (getattr(sample, "extrema", ()) or ())
                if self._identity_key(getattr(item, "identity", None)) not in hidden
            )
            sample = replace(sample, channels=tuple(channels), extrema=extrema)
        return sample, next_intent, False

    @staticmethod
    def _key_in(key, pool) -> bool:
        if key in pool:
            return True
        fid, channel = key
        return any(item[1] == channel and (not item[0] or not fid or item[0] == fid) for item in pool)

    @staticmethod
    def _hidden_channel_row(binding, existing, diagnostic=HIDDEN_CHANNEL_TEXT):
        if existing is not None and isinstance(existing, CursorDisplayChannel):
            return replace(
                existing,
                current_value=None,
                delta=None,
                min_value=None,
                max_value=None,
                avg_value=None,
                branches=(),
                diagnostic=diagnostic,
            )
        return CursorDisplayChannel(
            identity=(binding.fid, binding.channel),
            source_label="",
            channel_label=binding.channel,
            diagnostic=diagnostic,
        )

    @staticmethod
    def _sample_has_numeric(sample) -> bool:
        if sample is None:
            return False
        if getattr(sample, "frf_sample", None) is not None:
            return True
        skip = {HIDDEN_CHANNEL_TEXT, UNAVAILABLE_TEXT}
        for channel in tuple(getattr(sample, "channels", ()) or ()):
            if str(getattr(channel, "diagnostic", "") or "") in skip:
                continue
            if getattr(channel, "current_value", None) is not None:
                return True
            if getattr(channel, "value", None) is not None:
                return True
            if getattr(channel, "a_value", None) is not None:
                return True
            if getattr(channel, "min_value", None) is not None:
                return True
            if tuple(getattr(channel, "branches", ()) or ()):
                return True
            if str(getattr(channel, "diagnostic", "") or ""):
                return True
        return False

    @staticmethod
    def _sample_has_hidden(sample) -> bool:
        for channel in tuple(getattr(sample, "channels", ()) or ()):
            if str(getattr(channel, "diagnostic", "") or "") == HIDDEN_CHANNEL_TEXT:
                return True
        return False

    @staticmethod
    def _hidden_keys_from_sample(sample):
        keys = set()
        for channel in tuple(getattr(sample, "channels", ()) or ()) if sample is not None else ():
            if str(getattr(channel, "diagnostic", "") or "") != HIDDEN_CHANNEL_TEXT:
                continue
            key = PinnedCursorController._identity_key(getattr(channel, "identity", None))
            if key is not None:
                keys.add(key)
        return keys

    def _bound_identity_keys(self, canvas):
        keys = set()
        lines = getattr(canvas, "_channel_lines", None)
        items = getattr(lines, "composite_items", None)
        if callable(items):
            for channel_key, name, _values in items():
                key = self._identity_key(channel_key) or self._identity_key(name)
                if key is not None:
                    keys.add(key)
            return keys
        data = getattr(canvas, "channel_data", None)
        if data is not None and hasattr(data, "items"):
            for name in data:
                key = self._identity_key(name)
                if key is not None:
                    keys.add(key)
        entries = getattr(canvas, "_entries", None) or ()
        for entry in entries:
            identity = entry.get("identity") if isinstance(entry, dict) else None
            key = self._identity_key(identity) or self._identity_key(
                entry.get("label") if isinstance(entry, dict) else None
            )
            if key is not None:
                keys.add(key)
        return keys

    def _hidden_identity_keys(self, canvas):
        keys = set()
        cursor = getattr(canvas, "_cursor", None)
        hidden = getattr(cursor, "_hidden_channel_names", None)
        names = hidden() if callable(hidden) else ()
        for item in names or ():
            key = self._identity_key(item)
            if key is not None:
                keys.add(key)
        return keys

    @staticmethod
    def _identity_key(identity):
        fid, channel = _cursor_identity_parts(identity)
        if fid and channel:
            return (str(fid), str(channel))
        if isinstance(identity, str) and identity:
            return ("", identity)
        return None

    def _widget_under_mouse(self):
        app = QApplication.instance()
        pos = self._mouse_global()
        widget = app.widgetAt(pos) if app is not None else None
        if _widget_alive(widget):
            return widget
        stack = getattr(self._host, "stack", None)
        if isinstance(stack, QWidget) and _widget_alive(stack):
            local = stack.mapFromGlobal(pos)
            child = stack.childAt(local)
            if _widget_alive(child):
                return child
        return None

    def _mouse_global(self) -> QPoint:
        pos = QCursor.pos()
        app = QApplication.instance()
        if app is not None and app.widgetAt(pos) is not None:
            return pos
        if not self._last_mouse_global.isNull():
            return QPoint(self._last_mouse_global)
        return pos

    @staticmethod
    def _event_global_pos(event):
        for name in ("globalPos", "globalPosition"):
            getter = getattr(event, name, None)
            if not callable(getter):
                continue
            try:
                value = getter()
            except TypeError:
                continue
            if hasattr(value, "toPoint"):
                value = value.toPoint()
            if isinstance(value, QPoint):
                return value
        return None

    @staticmethod
    def _is_unmodified_p(event: QKeyEvent) -> bool:
        if event.key() != Qt.Key_P:
            return False
        mods = event.modifiers()
        blocked = Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier | Qt.ShiftModifier
        return not bool(mods & blocked)

    @staticmethod
    def _is_under(widget, ancestor) -> bool:
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _is_under_type(widget, cls) -> bool:
        current = widget
        while current is not None:
            if isinstance(current, cls):
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _canvas_from_widget(widget):
        current = widget
        while current is not None:
            if isinstance(current, PgHeatmapCanvas):
                return None
            if isinstance(current, (TimeDomainCanvasPG, PgLineCanvas, PgFrfCanvas)):
                return current
            current = current.parentWidget()
        return None

    def _snapshot_placement(self, canvas):
        fn = getattr(canvas, "snapshot_cursor_placement", None)
        return fn() if callable(fn) else None

    @staticmethod
    def _bindings_from_sample(sample) -> tuple[PinnedCursorBinding, ...]:
        if sample is None:
            return ()
        out = []
        for channel in getattr(sample, "channels", ()) or ():
            identity = getattr(channel, "identity", None)
            fid = channel_name = ""
            if isinstance(identity, tuple) and len(identity) == 2:
                fid, channel_name = str(identity[0]), str(identity[1])
            elif getattr(channel, "channel_label", None) and getattr(channel, "source_label", None):
                fid = str(channel.source_label)
                channel_name = str(channel.channel_label)
            if fid and channel_name:
                out.append(PinnedCursorBinding(fid=fid, channel=channel_name))
        return tuple(out)

    @staticmethod
    def _axis_identity(canvas, domain):
        if domain != "channel":
            return None
        ctx = getattr(getattr(canvas, "_cursor", None), "x_axis_context", None)
        identity = getattr(ctx, "identity", None)
        if isinstance(identity, tuple) and len(identity) == 2:
            fid, channel = identity
            if fid and channel:
                return (str(fid), str(channel))
        return None

    @staticmethod
    def _x_unit(canvas, domain) -> str:
        if domain == "time":
            return "s"
        if domain in {"frequency", "frf"}:
            return "Hz"
        ctx = getattr(getattr(canvas, "_cursor", None), "x_axis_context", None)
        unit = str(getattr(ctx, "unit", "") or "").strip()
        return unit

    def _primary_html(self, intent) -> str:
        tag = (
            f'<span style="color:#416faa;">P{intent.ordinal}</span>'
            '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
        )
        return tag + self._coord_html(intent)

    def _live_primary_html(self, domain, mode, sample) -> str:
        unit = "s" if domain == "time" else ("Hz" if domain in {"frequency", "frf"} else "")
        if mode == "single":
            return self._format_coord_html(domain, getattr(sample, "x", None), unit)
        return self._format_dual_html(
            domain, getattr(sample, "ax", None), getattr(sample, "bx", None), unit,
        )

    def _coord_html(self, intent) -> str:
        unit = intent.x_unit
        if intent.mode == "single":
            return self._format_coord_html(intent.domain, intent.x, unit)
        return self._format_dual_html(intent.domain, intent.ax, intent.bx, unit)

    @staticmethod
    def _format_coord_html(domain, x, unit) -> str:
        value = _finite(x)
        text = "—" if value is None else PinnedCursorController._format_value(domain, value, unit)
        return f'<span style="color:#111827;">{text}</span>'

    @staticmethod
    def _format_dual_html(domain, ax, bx, unit) -> str:
        a = _finite(ax)
        b = _finite(bx)
        a_text = "—" if a is None else PinnedCursorController._format_number(domain, a, unit)
        b_text = "—" if b is None else PinnedCursorController._format_number(domain, b, unit)
        return (
            f'<span style="color:#111827;">A={a_text}</span>'
            '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
            f'<span style="color:#111827;">B={b_text}</span>'
        )

    @staticmethod
    def _format_value(domain, value, unit) -> str:
        if domain == "time":
            return f"t={value:.4f}{unit or 's'}"
        if domain == "channel":
            suffix = f" {unit}" if unit else ""
            return f"X={value:.4g}{suffix}"
        suffix = f" {unit}" if unit else " Hz"
        return f"f={value:g}{suffix}"

    @staticmethod
    def _format_number(domain, value, unit) -> str:
        if domain == "time":
            return f"{value:.4f}{unit or 's'}"
        suffix = f" {unit}" if unit else ""
        if domain in {"frequency", "frf"} and not suffix:
            suffix = " Hz"
        return f"{value:g}{suffix}"

    def _sync_overlay(self, owner) -> None:
        canvas = owner.canvas
        overlay = getattr(canvas, "_pinned_overlay", None)
        if overlay is None:
            return
        overlay.set_records(self._overlay_records(owner))

    def _overlay_records(self, owner):
        records = []
        for intent in owner.collection.records:
            status = owner.availability.get(intent.record_id, PIN_STATUS_READY)
            if status == PIN_STATUS_INCOMPATIBLE_AXIS:
                continue
            sample = owner.samples.get(intent.record_id)
            extrema = tuple(getattr(sample, "extrema", ()) or ()) if sample is not None else ()
            hidden = self._hidden_keys_from_sample(sample)
            if hidden:
                extrema = tuple(
                    item for item in extrema
                    if self._identity_key(getattr(item, "identity", None)) not in hidden
                )
            if status == PIN_STATUS_UNAVAILABLE and self._log_unavailable(
                owner.canvas, intent,
            ):
                continue
            if intent.mode == "dual":
                if coords_equal(intent.ax, intent.bx):
                    endpoints = (
                        PinnedOverlayEndpoint(
                            "ab", float(intent.ax), f"P{intent.ordinal}·A/B",
                        ),
                    )
                else:
                    endpoints = (
                        PinnedOverlayEndpoint(
                            "a", float(intent.ax), f"P{intent.ordinal}·A",
                        ),
                        PinnedOverlayEndpoint(
                            "b", float(intent.bx), f"P{intent.ordinal}·B",
                        ),
                    )
            else:
                x_value = _finite(intent.x)
                if x_value is None:
                    continue
                endpoints = (
                    PinnedOverlayEndpoint("x", x_value, f"P{intent.ordinal}"),
                )
            records.append(PinnedOverlayRecord(
                record_id=intent.record_id,
                ordinal=int(intent.ordinal),
                mode=intent.mode,
                domain=intent.domain,
                endpoints=endpoints,
                extrema=extrema,
            ))
        return tuple(records)

    def _on_overlay_layout(self, canvas, layout) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        self._project_axis_labels(owner, layout)
        self._apply_offscreen(owner, layout)

    def _project_axis_labels(self, owner, layout) -> None:
        host = self._host
        stack = getattr(host, "stack", None)
        canvas = owner.canvas
        mapper = getattr(host, "map_canvas_rect_to_stack", None)
        on_screen = bool(host._cursor_source_on_screen(canvas))
        wanted = {}
        if (
            layout is not None
            and not layout.pending
            and on_screen
            and callable(mapper)
        ):
            for geom in layout.items:
                mapped = mapper(canvas, QRect(*geom.canvas_rect))
                if mapped is None or not mapped.isValid():
                    continue
                wanted[geom.key] = (geom, mapped)
        for key in list(owner.axis_labels):
            if key not in wanted:
                self._destroy_axis_label(owner.axis_labels.pop(key))
        for key, (geom, mapped) in wanted.items():
            label = owner.axis_labels.get(key)
            if not _widget_alive(label):
                label = PinnedAxisLabel(stack)
                label.clicked.connect(partial(self.raise_record, canvas))
                label.hover_changed.connect(partial(self._set_hover, canvas))
                owner.axis_labels[key] = label
            label.apply_geom(geom)
            label.move(mapped.x(), mapped.y())
            label.setVisible(True)
            highlight = self._hover_matches(owner, geom.record_ids)
            label.set_highlighted(highlight)
            label.raise_()

    def _apply_offscreen(self, owner, layout) -> None:
        offscreen = layout.offscreen_ids if layout is not None else frozenset()
        for record_id, pill in owner.pills.items():
            if not _widget_alive(pill):
                continue
            away = record_id in offscreen
            pill.setProperty("pinnedOffscreen", away)
            pill.setToolTip(PINNED_OFFSCREEN_TEXT if away else "")

    def _set_hover(self, canvas, target) -> None:
        owner = self._owner(canvas)
        if owner is None:
            return
        overlay = getattr(canvas, "_pinned_overlay", None)
        if overlay is not None:
            overlay.set_highlight(target)
        ids = set()
        if isinstance(target, (tuple, list, set, frozenset)):
            ids.update(str(item) for item in target)
        elif target:
            ids.add(str(target))
        for record_id, pill in owner.pills.items():
            if not _widget_alive(pill):
                continue
            highlighted = record_id in ids
            pill._highlighted = highlighted
            if highlighted:
                pill.raise_()
                timer = getattr(pill, "_highlight_timer", None)
                if timer is not None:
                    timer.stop()
            pill.update()
        for label in owner.axis_labels.values():
            if not _widget_alive(label):
                continue
            label.set_highlighted(bool(ids.intersection(label.record_ids())))

    def _hover_matches(self, owner, record_ids) -> bool:
        overlay = getattr(owner.canvas, "_pinned_overlay", None)
        target = overlay.highlight_id() if overlay is not None else None
        if target is None:
            return False
        ids = set(record_ids)
        if isinstance(target, (tuple, list, set, frozenset)):
            return bool(ids.intersection(str(item) for item in target))
        return str(target) in ids

    def _on_pinned_pill_event(self, pill, event) -> None:
        if pill.pin_role() != "pinned":
            return
        etype = event.type()
        if etype not in (QEvent.Enter, QEvent.Leave, QEvent.FocusIn, QEvent.FocusOut):
            return
        owner, record_id = self._owner_and_record_for_pill(pill)
        if owner is None:
            return
        if etype in (QEvent.Enter, QEvent.FocusIn):
            self._set_hover(owner.canvas, record_id)
        else:
            self._set_hover(owner.canvas, None)

    def _owner_and_record_for_pill(self, pill):
        for owner in self._owners.values():
            for record_id, item in owner.pills.items():
                if item is pill:
                    return owner, record_id
        return None, None

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
