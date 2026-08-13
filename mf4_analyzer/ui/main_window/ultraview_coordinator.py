"""UltraView capture pipeline: presentation digest, stable grab, PreviewStore.

UltraView never computes, restores-from-cache, or replots a source View to
fill a preview. This coordinator only reads already-visible source state and
grabs canvases that already satisfy the stability contract.
"""
from __future__ import annotations

import logging
import weakref
from contextlib import contextmanager
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QWidget

from ...diagnostics import throttled
from ...render_profile import source_revision_for
from ..ultraview_state import (
    COMPARE_FILTER_ALL,
    SECTION_AXIS_KIND,
    SOURCE_SECTIONS,
    PreviewMeta,
    UltraViewBoardState,
    UltraViewRef,
    add_ref,
    all_refs,
    default_board,
    derive_preview_status,
    layout_slots,
    membership_set,
    move_to_unplaced,
    nudge_ratio,
    parse_ref_payload,
    place_from_unplaced,
    placed_ref_set,
    placement_for,
    presentation_digest,
    remove_ref,
    replace_slot,
    set_layout,
    swap_slots,
)
from ..chart_stack.ultraview.preview_store import PreviewStore
from ..chart_stack.ultraview.widgets import LibraryRow
from ..image_utils import pixmap_as_device_pixel_image

logger = logging.getLogger(__name__)

_MIN_CAPTURE_EDGE = 8
_HEATMAP_SECTIONS = frozenset({"fft_time", "order"})
_SECTION_X_UNIT = {
    "time": "s",
    "fft": "Hz",
    "fft_time": "s",
    "frf": "Hz",
    "order": "s",
}


def notify_ultraview_plot(window, section: str, reason: str = "plot") -> None:
    """Queue a visible-section capture after an actual plot/set_result."""
    coordinator = getattr(window, "_ultraview", None)
    if coordinator is None:
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


def _iter_viewboxes(widget):
    axes = getattr(widget, "axes_list", None) or ()
    for handle in axes:
        vb = getattr(handle, "view_box", None)
        if vb is not None:
            yield vb
    for name in ("_plot", "_plot_amp", "_plot_time", "_plot_magnitude",
                 "_plot_phase", "_plot_coherence"):
        plot = getattr(widget, name, None)
        vb = getattr(plot, "vb", None) if plot is not None else None
        if vb is not None:
            yield vb
    plots = getattr(widget, "plots", None) or ()
    for plot in plots:
        vb = getattr(plot, "vb", None)
        if vb is not None:
            yield vb


def _iter_item_lists(owner):
    if owner is None:
        return
    for name in (
        "_cursor_line_items",
        "_cursor_a_items",
        "_cursor_b_items",
        "_cursor_lines",
        "_cursor_a_lines",
        "_cursor_b_lines",
        "_dual_cursor_extreme_markers",
    ):
        items = getattr(owner, name, None)
        if items:
            yield from items


def _iter_transient_overlay_items(widget):
    seen = set()
    for host in _iter_overlay_hosts(widget):
        for owner in (host, getattr(host, "_cursor", None)):
            for item in _iter_item_lists(owner):
                ident = id(item)
                if ident in seen:
                    continue
                seen.add(ident)
                yield item
        for vb in _iter_viewboxes(host):
            box = getattr(vb, "rbScaleBox", None)
            if box is not None and id(box) not in seen:
                seen.add(id(box))
                yield box


@contextmanager
def hide_transient_overlays(widget):
    """Hide hover/crosshair/cursor/selection items; restore in ``finally``.

    Persistent remarks are not in the transient set and stay visible.
    """
    hidden = []
    try:
        for item in _iter_transient_overlay_items(widget):
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
        self._bindings: dict[int, tuple[UltraViewRef, Any]] = {}
        self._queued: dict[tuple, QTimer] = {}
        self._unstable: dict[int, tuple] = {}
        self._hooks: list[tuple[Any, Any, Any]] = []
        self._hooked_ids: set[int] = set()
        self._result_identity: dict[tuple, int] = {}
        self._result_generation: dict[tuple, int] = {}
        self.last_source_mode = "time"
        self._board = default_board()
        self._left_snapshot = None
        self._inspector_snapshot = None
        self._page_hooks: list[tuple[Any, Any, Any]] = []
        self.attach()

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
        if canvas is None or not _alive(canvas):
            return
        ident = id(canvas)
        if ref is None:
            self._bindings.pop(ident, None)
            self._unstable.pop(ident, None)
            return
        self._bindings[ident] = (ref, weakref.ref(canvas))

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
        outgoing frame. Hidden secondary widgets are skipped.
        """
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
        if ref is None or widget is None or not _alive(widget):
            return
        try:
            if not widget.isVisible():
                return
        except RuntimeError:
            return
        digest = self.current_digest_for(ref)
        if digest is None:
            self._warn_capture(ref, widget, reason, "digest-unavailable")
            return
        record = self._store.get(ref)
        if record is not None and record.captured_digest == digest:
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
        """Bump generation only when the key is new or the object identity changed."""
        slot = self._generation_slot(section, view_id, pane_idx, key)
        identity = id(result)
        previous = self._result_identity.get(slot)
        if previous is None or previous != identity:
            self._result_generation[slot] = int(self._result_generation.get(slot, 0)) + 1
            self._result_identity[slot] = identity

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
        except (TypeError, ValueError):
            self._warn_digest(ref)
            return None

    def set_pinned_from_board(self, board) -> None:
        if board is None:
            self._store.set_pinned_refs(())
            return
        self._store.set_pinned_refs(placed_ref_set(board))

    @property
    def board(self) -> UltraViewBoardState:
        return self._board

    def page(self):
        window = self._window
        if window is None:
            return None
        stack = getattr(window, "chart_stack", None)
        return getattr(stack, "page_ultraview", None)

    def attach(self) -> None:
        window = self._window
        if window is None:
            return
        page = self.page()
        if page is not None:
            page.set_board(self._board)
            self._connect_page(page)
        inspector = getattr(window, "inspector", None)
        ctx = getattr(inspector, "ultraview_ctx", None)
        if ctx is not None:
            self._connect_inspector(ctx)
        stack = getattr(window, "chart_stack", None)
        if stack is not None:
            signal = getattr(stack, "add_to_ultraview_requested", None)
            if signal is not None:
                signal.connect(self.add_from_source_tab)
                self._page_hooks.append((stack, signal, self.add_from_source_tab))
        self.refresh_page()

    def _connect_page(self, page) -> None:
        pairs = (
            (page.add_ref_requested, self._on_add_ref),
            (page.replace_slot_requested, self._on_replace_slot),
            (page.swap_slots_requested, self._on_swap_slots),
            (page.place_from_unplaced_requested, self._on_place_from_unplaced),
            (page.move_to_unplaced_requested, self._on_move_to_unplaced),
            (page.remove_ref_requested, self._on_remove_ref),
            (page.open_source_requested, self.open_source),
            (page.focus_requested, self._on_focus),
            (page.layout_changed, self._on_layout),
            (page.ratio_nudge_requested, self._on_ratio_nudge),
            (page.presentation_toggled, self._on_presentation),
            (page.compare_filter_changed, self._on_compare_filter),
            (page.selection_changed, self._on_selection),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._page_hooks.append((page, signal, slot))

    def _connect_inspector(self, ctx) -> None:
        pairs = (
            (ctx.layout_changed, self._on_layout),
            (ctx.ratio_nudge_requested, self._on_ratio_nudge),
            (ctx.open_source_requested, self.open_source),
            (ctx.focus_requested, self._on_focus),
            (ctx.shift_slot_requested, self._on_shift_slot),
            (ctx.set_primary_requested, self._on_set_primary),
            (ctx.replace_arm_requested, self._on_rebind_arm),
            (ctx.move_to_unplaced_requested, self._on_move_to_unplaced),
            (ctx.remove_ref_requested, self._on_remove_ref),
            (ctx.compare_filter_changed, self._on_compare_filter),
            (ctx.show_titles_toggled, self._on_show_titles),
            (ctx.show_sources_toggled, self._on_show_sources),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._page_hooks.append((ctx, signal, slot))

    def enter_ultraview(self) -> None:
        window = self._window
        if window is None:
            return
        left = getattr(window, "_panel_ctrl_left", None)
        if left is not None and self._left_snapshot is None:
            self._left_snapshot = left.snapshot_persistent_state()
            left.restore_persistent_state({
                "state": "HIDDEN",
                "width": self._left_snapshot.get("width"),
            })
        page = self.page()
        if page is not None:
            toolbar = getattr(window, "toolbar", None)
            if toolbar is not None:
                toolbar.set_nav_open(page.is_library_visible())
        self.refresh_page()

    def leave_ultraview(self) -> None:
        window = self._window
        if window is None:
            return
        page = self.page()
        if page is not None and page.is_presentation_active():
            self._on_presentation(False)
        left = getattr(window, "_panel_ctrl_left", None)
        if left is not None and self._left_snapshot is not None:
            left.restore_persistent_state(self._left_snapshot)
            self._left_snapshot = None

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
        primary = getattr(stack, "canvas_time", None)
        if primary is not None:
            ref = UltraViewRef("time", active.view_id)
            self.bind_canvas(primary, ref)
            self.request_capture(ref, primary, reason)
        if not callable(getattr(stack, "split_active", None)) or not stack.split_active():
            return
        partner_idx = manager.partner_for(manager.active)
        secondary = stack.secondary_canvas()
        if partner_idx is None or secondary is None:
            return
        partner = manager.get(partner_idx)
        ref = UltraViewRef("time", partner.view_id)
        self.bind_canvas(secondary, ref)
        self.request_capture(ref, secondary, reason)

    def add_from_source_tab(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        window = self._window
        if window is not None and getattr(window.chart_stack, "current_mode", lambda: "")() == section:
            current = self._active_ref(section)
            if current == ref:
                widget = self._visible_widget_for(section)
                if widget is not None:
                    self.bind_canvas(widget, ref)
                    self.request_capture(ref, widget, "add-from-tab")
            elif section == "time":
                self._maybe_capture_time_partner(ref)
        self._apply_add_ref(ref)

    def _maybe_capture_time_partner(self, ref: UltraViewRef) -> None:
        window = self._window
        stack = getattr(window, "chart_stack", None)
        manager = getattr(window, "view_manager", None)
        if stack is None or manager is None or not stack.split_active():
            return
        partner_idx = manager.partner_for(manager.active)
        if partner_idx is None:
            return
        partner = manager.get(partner_idx)
        if str(partner.view_id) != ref.view_id:
            return
        secondary = stack.secondary_canvas()
        if secondary is None:
            return
        self.bind_canvas(secondary, ref)
        self.request_capture(ref, secondary, "add-from-tab-split")

    def open_source(self, section: str, view_id: str) -> None:
        window = self._window
        if window is None:
            return
        idx = self._index_for_view_id(section, view_id)
        if idx is None:
            page = self.page()
            if page is not None:
                page.arm_replacement(section, view_id)
            return
        toolbar = getattr(window, "toolbar", None)
        if toolbar is not None:
            toolbar._set_mode(section)

        def _switch():
            host = self._window
            if host is None:
                return
            if section == "time":
                host._switch_view(idx)
            else:
                host._on_analysis_switch(section, idx)

        QTimer.singleShot(0, _switch)

    def refresh_page(self) -> None:
        page = self.page()
        if page is None:
            return
        page.set_board(self._board)
        self.set_pinned_from_board(self._board)
        self._refresh_library(page)
        for ref in all_refs(self._board):
            self._push_preview(ref)
        self._sync_inspector()

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
                    on_board=ref in membership_set(self._board),
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

    def _push_preview(self, ref: UltraViewRef) -> None:
        page = self.page()
        if page is None:
            return
        record = self._store.get(ref)
        if record is not None:
            page.set_preview(ref, record)
        exists = self._ref_exists(ref)
        digest = self.current_digest_for(ref) if exists else None
        image_valid = record is not None and PreviewStore.image_valid(
            getattr(record, "image", None)
        )
        captured = getattr(record, "captured_digest", None) if record else None
        page.set_ref_status(
            ref,
            derive_preview_status(exists, image_valid, captured, digest),
            exists,
        )

    def _sync_inspector(self) -> None:
        window = self._window
        inspector = getattr(window, "inspector", None) if window is not None else None
        ctx = getattr(inspector, "ultraview_ctx", None)
        if ctx is None:
            return
        page = self.page()
        selected = None
        if page is not None:
            pair = page.selected_ref()
            if pair is not None:
                selected = parse_ref_payload(
                    {"section": pair[0], "view_id": pair[1]}
                )
        compare = COMPARE_FILTER_ALL if page is None else page.compare_filter()
        ctx.set_board(self._board, selected=selected, compare_filter=compare)

    def _after_board_mutation(self) -> None:
        self.refresh_page()

    def _apply_add_ref(self, ref: UltraViewRef) -> None:
        page = self.page()
        if ref in membership_set(self._board):
            if page is not None:
                page._select_ref(ref)
            return
        add_ref(self._board, ref)
        self._after_board_mutation()

    def _on_add_ref(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self._apply_add_ref(ref)

    def _on_replace_slot(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        replace_slot(self._board, slot_id, ref)
        self._after_board_mutation()

    def _on_swap_slots(self, slot_a: str, slot_b: str) -> None:
        swap_slots(self._board, slot_a, slot_b)
        self._after_board_mutation()

    def _on_place_from_unplaced(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        place_from_unplaced(self._board, slot_id, ref)
        self._after_board_mutation()

    def _on_move_to_unplaced(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        move_to_unplaced(self._board, ref)
        self._after_board_mutation()

    def _on_remove_ref(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        remove_ref(self._board, ref)
        self._after_board_mutation()

    def _on_layout(self, layout_id: str) -> None:
        set_layout(self._board, str(layout_id))
        self._after_board_mutation()

    def _on_ratio_nudge(self, steps: int) -> None:
        nudge_ratio(self._board, int(steps))
        self._after_board_mutation()

    def _on_focus(self, section: str, view_id: str) -> None:
        page = self.page()
        if page is not None:
            page.show_focus(section, view_id)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        page = self.page()
        if page is not None:
            page.arm_replacement(section, view_id)

    def _on_compare_filter(self, filter_id: str) -> None:
        page = self.page()
        wanted = str(filter_id or COMPARE_FILTER_ALL)
        if page is not None and page.compare_filter() != wanted:
            page.set_compare_filter(wanted)
        self._sync_inspector()

    def _on_selection(self, _section: str, _view_id: str) -> None:
        self._sync_inspector()

    def _on_show_titles(self, checked: bool) -> None:
        self._board.show_titles = bool(checked)
        self._after_board_mutation()

    def _on_show_sources(self, checked: bool) -> None:
        self._board.show_sources = bool(checked)
        self._after_board_mutation()

    def _on_shift_slot(self, section: str, view_id: str, delta: int) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        placement = placement_for(self._board, ref)
        if placement is None:
            return
        slots = layout_slots(self._board.layout_id)
        try:
            index = slots.index(placement.slot_id)
        except ValueError:
            return
        target = slots[(index + int(delta)) % len(slots)]
        swap_slots(self._board, placement.slot_id, target)
        self._after_board_mutation()

    def _on_set_primary(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        placement = placement_for(self._board, ref)
        if placement is None:
            return
        slots = layout_slots(self._board.layout_id)
        primary = "primary" if "primary" in slots else slots[0]
        if placement.slot_id == primary:
            return
        swap_slots(self._board, placement.slot_id, primary)
        self._after_board_mutation()

    def _on_presentation(self, active: bool) -> None:
        window = self._window
        page = self.page()
        if page is not None:
            page.set_presentation_active(bool(active))
        if window is None:
            return
        right = getattr(window, "_panel_ctrl_right", None)
        if right is None:
            return
        if active:
            if self._inspector_snapshot is None:
                self._inspector_snapshot = right.snapshot_persistent_state()
            right.restore_persistent_state({
                "state": "HIDDEN",
                "width": self._inspector_snapshot.get("width"),
            })
            return
        if self._inspector_snapshot is not None:
            right.restore_persistent_state(self._inspector_snapshot)
            self._inspector_snapshot = None

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

    def clear(self) -> None:
        self._drop_all_timers()
        self._disconnect_hooks()
        self._disconnect_page_hooks()
        self._store.clear()
        self._bindings.clear()
        self._unstable.clear()
        self._result_identity.clear()
        self._result_generation.clear()

    def _disconnect_page_hooks(self) -> None:
        for obj, signal, slot in self._page_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._page_hooks.clear()

    # -- payload ----------------------------------------------------------

    def _time_payload(self, window, ref: UltraViewRef) -> dict | None:
        state = self._time_state(window, ref.view_id)
        if state is None:
            return None
        widget = self._widget_for_ref(ref)
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
            "markup_revision": read_markup_revision(widget) if widget is not None
            else read_markup_revision(getattr(window, "canvas_time", None)),
        }

    def _analysis_payload(self, window, ref: UltraViewRef) -> dict | None:
        resolved = self._analysis_state(window, ref.section, ref.view_id)
        if resolved is None:
            return None
        _mgr, state = resolved
        page = self._analysis_page(window, ref.section)
        pane_count = int(page.pane_count()) if page is not None else len(state.panes)
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
        widget = page if page is not None else self._widget_for_ref(ref)
        return {
            "panes": panes,
            "params": dict(state.params or {}),
            "compare": dict(state.compare or {}),
            "pane_count": pane_count,
            "markup_revision": read_markup_revision(widget),
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
            return list(source_revision_for(time_axis, values))
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
        pins = getattr(window, "_analysis_pins", None)
        slot = (section, str(view_id), int(pane_idx))
        if pins is not None and slot in pins:
            return list(pins[slot])
        return []

    # -- capture ----------------------------------------------------------

    def _try_publish_now(self, ref, widget, reason: str) -> bool:
        digest = self.current_digest_for(ref)
        if digest is None:
            self._warn_capture(ref, widget, reason, "digest-unavailable")
            return False
        record = self._store.get(ref)
        if record is not None and record.captured_digest == digest:
            return True
        if not self._is_stable(widget, ref.section):
            self._warn_capture(ref, widget, reason, "unstable")
            return False
        return self._publish_grab(ref, widget, digest, reason)

    def _queue_grab(self, key, ref, widget, digest, reason) -> None:
        widget_ref = weakref.ref(widget)

        def _fire():
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            self._publish_grab(ref, canvas, digest, reason)

        self._start_timer(key, _fire)

    def _queue_heatmap_grab(self, key, ref, widget, digest, reason) -> None:
        widget_ref = weakref.ref(widget)

        def _after_layout():
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            self._queue_grab(key, ref, canvas, digest, reason)

        def _after_first_turn():
            canvas = widget_ref()
            if canvas is None or not _alive(canvas):
                return
            self._start_timer(key, _after_layout)

        self._start_timer(key, _after_first_turn)

    def _publish_grab(self, ref, widget, digest, reason) -> bool:
        if not _alive(widget):
            return False
        bound = self.bound_ref_for(widget)
        if bound is not None and bound != ref:
            return False
        current = self.current_digest_for(ref)
        if current != digest:
            return False
        if not self._widget_visible_and_sized(widget):
            return False
        if not self._is_stable(widget, ref.section):
            self._unstable[id(widget)] = (
                ref, digest, reason, weakref.ref(widget)
            )
            return False
        with hide_transient_overlays(widget):
            image = self._grab_image(widget)
        if image is None:
            self._warn_capture(ref, widget, reason, "grab-invalid")
            return False
        meta = self._preview_meta(ref, digest)
        published = bool(self._store.publish(ref, image, digest=digest, meta=meta))
        if published:
            self._push_preview(ref)
        return published

    def _grab_image(self, widget) -> QImage | None:
        pixmap = None
        grab_combined = getattr(widget, "grab_combined_pixmap", None)
        if callable(grab_combined):
            pixmap = grab_combined(scale=1.0)
        elif callable(getattr(widget, "grab_pixmap", None)):
            pixmap = widget.grab_pixmap(scale=1.0)
        elif isinstance(widget, QWidget):
            pixmap = widget.grab()
        image = pixmap_as_device_pixel_image(pixmap)
        if image is None:
            return None
        if image.width() < _MIN_CAPTURE_EDGE or image.height() < _MIN_CAPTURE_EDGE:
            return None
        return image

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
            if status.get("state") != "green":
                return False
        dense = getattr(host, "_dense_raster", None)
        if dense is not None and callable(getattr(dense, "quality_status", None)):
            dense_status = dense.quality_status() or {}
            if dense_status.get("has_dense") and dense_status.get("state") not in (
                None,
                "green",
            ):
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
            self._hooked_ids.add(ident)

    def _on_quality_status_changed(self, *_args) -> None:
        self._reconsider_pending(self.sender())

    def _on_layout_geometry_changed(self, *_args) -> None:
        self._reconsider_pending(self.sender())

    def _reconsider_pending(self, sender) -> None:
        if sender is None:
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
        for _ident, (bound, handle) in self._bindings.items():
            if bound != ref:
                continue
            widget = handle()
            if widget is not None and _alive(widget):
                return widget
        window = self._window
        if window is None:
            return None
        if ref.section == "time":
            return getattr(window, "canvas_time", None)
        return self._analysis_page(window, ref.section)

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
            logging.WARNING,
            "UltraView capture skipped (%s/%s) section=%s view_id=%s canvas=%s",
            reason,
            detail,
            ref.section,
            ref.view_id,
            canvas_type,
        )

    def _warn_digest(self, ref) -> None:
        throttled(
            logger,
            f"ultraview-digest:{ref.section}:{ref.view_id}",
            logging.WARNING,
            "UltraView presentation digest failed section=%s view_id=%s",
            ref.section,
            ref.view_id,
        )

    def _start_timer(self, key, callback) -> None:
        existing = self._queued.pop(key, None)
        if existing is not None:
            existing.stop()
            existing.deleteLater()
        timer = QTimer(self)
        timer.setSingleShot(True)

        def _fire():
            current = self._queued.get(key)
            if current is timer:
                self._queued.pop(key, None)
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

    def _drop_all_timers(self) -> None:
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


def _digest_leaf(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, tuple):
        return [_digest_leaf(item) for item in value]
    if isinstance(value, list):
        return [_digest_leaf(item) for item in value]
    return value
