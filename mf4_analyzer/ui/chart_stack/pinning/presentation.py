"""Pinned pill/label projection. Does not sample or write the collection.

Overlay graphics stay on the canvas ``PinnedCursorOverlay``. This projector
owns widget maps, local Enter/Leave/Focus filters, anchors, overlay DTOs,
offscreen flags, and highlight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PyQt5.QtWidgets import QApplication, QWidget

from ...pg_canvas.pinned_cursor_overlay import (
    PINNED_OFFSCREEN_TEXT,
    PinnedAxisLabel,
    PinnedOverlayEndpoint,
    PinnedPanelTether,
    PinnedOverlayRecord,
    PinnedTetherPort,
    tether_candidate_ports,
)
from ...pinned_cursor_facts import (
    UNAVAILABLE_TEXT,
    _finite,
    _hidden_keys_from_sample,
    _identity_key,
    _sample_has_unchecked,
)
from ...pinned_cursor_state import DEFAULT_ANCHOR, PinnedCursorAnchor
from ..cursor_display import (
    build_cursor_presentation,
    build_fft_cursor_presentation,
    build_frf_cursor_presentation,
    pin_primary_html,
    pin_status_primary_html,
)
from ..cursor_pill import CursorPill
from .sampling import (
    PIN_STATUS_INCOMPATIBLE_AXIS,
    PIN_STATUS_PENDING,
    PIN_STATUS_READY,
    PIN_STATUS_UNAVAILABLE,
)


PENDING_TEXT = "更新中"
INCOMPATIBLE_AXIS_TEXT = "X 轴已更改"

_NUDGE_STEP = 28
_NUDGE_LIMIT = 72
_PILL_HOVER_EVENTS = frozenset({
    QEvent.Enter,
    QEvent.Leave,
    QEvent.FocusIn,
    QEvent.FocusOut,
})
_PILL_CAPTURE_EVENTS = frozenset({
    QEvent.MouseButtonPress,
    QEvent.MouseButtonRelease,
})
_PILL_GEOMETRY_EVENTS = frozenset({
    QEvent.Move,
    QEvent.Resize,
    QEvent.Show,
    QEvent.Hide,
})


def _widget_alive(widget):
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except RuntimeError:
        return False


def _target_includes(target, record_id) -> bool:
    if target in (None, "", (), []):
        return False
    wanted = str(record_id)
    if isinstance(target, (tuple, list, set, frozenset)):
        return wanted in {str(item) for item in target}
    return str(target) == wanted


def _pointer_over_widget(widget) -> bool:
    if not _widget_alive(widget):
        return False
    try:
        if widget.underMouse():
            return True
        for child in widget.findChildren(QWidget):
            if _widget_alive(child) and child.underMouse():
                return True
    except RuntimeError:
        return False
    return False


def _widget_or_descendant_has_focus(widget) -> bool:
    if not _widget_alive(widget):
        return False
    focus = QApplication.focusWidget()
    current = focus
    while current is not None:
        if current is widget:
            return True
        try:
            current = current.parentWidget()
        except RuntimeError:
            break
    return False


def _widget_holds_interaction(widget) -> bool:
    return _pointer_over_widget(widget) or _widget_or_descendant_has_focus(widget)


@dataclass
class _PresentationState:
    canvas: object = None
    pills: dict = field(default_factory=dict)
    axis_labels: dict = field(default_factory=dict)
    auto_panel_rects: dict = field(default_factory=dict)
    auto_panel_safe_rect: QRect | None = None
    layout_token: int = 0
    applied_token: int = 0
    pending: bool = False
    pending_token: int = 0
    request_serial: int = 0
    layout_fingerprints: dict = field(default_factory=dict)
    content_revisions: dict = field(default_factory=dict)
    panel_endpoints: dict = field(default_factory=dict)
    hover_target: object = None
    capture_target: object = None


class PinPanelProjector(QObject):
    """Per-canvas pinned widgets and layout. Collection writes stay on the façade."""

    def __init__(self, parent, ports):
        super().__init__(parent)
        self._ports = ports
        self._states: dict[int, _PresentationState] = {}
        self._pending_owners = []
        self._in_layout = False
        self._repeat_requested = False
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(0)
        self._layout_timer.timeout.connect(self._on_layout_timer)

    def invalidate_tokens(self) -> None:
        self._cancel_layout_timer()
        self._pending_owners = []
        self._repeat_requested = False
        for state in self._states.values():
            state.layout_token += 1
            state.pending = False
            state.pending_token = state.layout_token
            state.hover_target = None
            state.capture_target = None

    def invalidate_key(self, key) -> None:
        state = self._states.get(key)
        if state is None:
            return
        state.layout_token += 1
        state.pending = False
        state.pending_token = state.layout_token
        state.hover_target = None
        state.capture_target = None
        self._pending_owners = [
            item for item in self._pending_owners if item[0] != key
        ]
        for pill in list(state.pills.values()):
            self._cancel_pill_timers(pill)
        if not self._has_pending():
            self._cancel_layout_timer()
            self._repeat_requested = False

    def bind_canvas(self, key, canvas) -> None:
        state = self._states.setdefault(key, _PresentationState())
        state.canvas = canvas
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        if overlay is not None:
            overlay.set_layout_callback(partial(self._on_overlay_layout, key, canvas))

    def unbind_canvas(self, key, canvas, *, destroy_widgets) -> None:
        self.invalidate_key(key)
        overlay = None
        if _widget_alive(canvas):
            try:
                overlay = getattr(canvas, "_pinned_overlay", None)
            except RuntimeError:
                overlay = None
        if overlay is not None:
            try:
                overlay.set_layout_callback(None)
                if destroy_widgets:
                    overlay.clear()
            except RuntimeError:
                pass
        if destroy_widgets:
            self.clear_widgets(key)
        self._states.pop(key, None)

    def state_for(self, key) -> _PresentationState:
        state = self._states.get(key)
        if state is None:
            state = _PresentationState()
            self._states[key] = state
        return state

    def pills_for(self, key) -> tuple[CursorPill, ...]:
        state = self._states.get(key)
        if state is None:
            return ()
        return tuple(pill for pill in state.pills.values() if _widget_alive(pill))

    def axis_labels_for(self, key) -> tuple[PinnedAxisLabel, ...]:
        state = self._states.get(key)
        if state is None:
            return ()
        return tuple(
            label for label in state.axis_labels.values() if _widget_alive(label)
        )

    def pill_for(self, key, record_id):
        state = self._states.get(key)
        if state is None:
            return None
        pill = state.pills.get(str(record_id))
        return pill if _widget_alive(pill) else None

    def any_dragging(self, key) -> bool:
        state = self._states.get(key)
        if state is None:
            return False
        for pill in state.pills.values():
            if _widget_alive(pill) and pill.is_dragging():
                return True
        return False

    def record_id_for_pill(self, pill):
        for state in self._states.values():
            for record_id, item in state.pills.items():
                if item is pill:
                    return record_id
        return None

    def canvas_and_record_for_pill(self, pill):
        for key, state in self._states.items():
            for record_id, item in state.pills.items():
                if item is pill:
                    return key, record_id
        return None, None

    def clear_widgets(self, key) -> None:
        state = self._states.get(key)
        if state is None:
            return
        for pill in list(state.pills.values()):
            self.destroy_pill(pill)
        state.pills.clear()
        for label in list(state.axis_labels.values()):
            self.destroy_axis_label(label)
        state.axis_labels.clear()
        state.auto_panel_rects.clear()
        state.auto_panel_safe_rect = None
        state.layout_fingerprints.clear()
        state.content_revisions.clear()
        state.panel_endpoints.clear()
        state.hover_target = None
        state.capture_target = None
        state.pending = False

    def destroy_record(self, key, record_id) -> None:
        state = self._states.get(key)
        if state is None:
            return
        pill = state.pills.pop(record_id, None)
        self.destroy_pill(pill)
        state.auto_panel_rects.pop(record_id, None)
        state.layout_fingerprints.pop(record_id, None)
        state.content_revisions.pop(record_id, None)
        state.panel_endpoints.pop(record_id, None)
        if _target_includes(state.capture_target, record_id):
            state.capture_target = None
        if _target_includes(state.hover_target, record_id):
            state.hover_target = None

    @staticmethod
    def destroy_pill(pill) -> None:
        if not _widget_alive(pill):
            return
        pill.hide()
        dismiss = getattr(pill, "dismiss_title_menu", None)
        if callable(dismiss):
            dismiss()
        pill.setParent(None)
        pill.deleteLater()

    @staticmethod
    def destroy_axis_label(label) -> None:
        if not _widget_alive(label):
            return
        label.hide()
        label.setParent(None)
        label.deleteLater()

    @staticmethod
    def snapshot_pill(pill) -> tuple[dict, tuple]:
        if not _widget_alive(pill):
            return {}, (0, 0)
        return pill.snapshot(), (pill.x(), pill.y())

    def eventFilter(self, watched, event):  # noqa: N802
        if not isinstance(watched, CursorPill):
            return False
        etype = event.type()
        if etype in _PILL_HOVER_EVENTS or etype in _PILL_CAPTURE_EVENTS:
            self._on_pinned_pill_event(watched, event)
            return False
        if etype in _PILL_GEOMETRY_EVENTS:
            self._on_pinned_pill_geometry(watched, event)
            return False
        return False

    def request_reflow(self, owners) -> None:
        """Schedule a coalesced geometry apply. Does not sample."""
        self._store_pending_owners(owners)
        self._clamp_overflow_now(owners)
        self._schedule_layout()

    def flush_layout(self, owners=None) -> None:
        """Apply pending final geometry now. Does not sample or mark intent."""
        if owners:
            self._store_pending_owners(owners)
        self._cancel_layout_timer()
        self._apply_pending_layout()

    def reflow_now(self, owners) -> None:
        ports = self._ports
        secondary = ports.secondary_card()
        for key, canvas, collection in owners:
            if not _widget_alive(canvas):
                continue
            on_screen = bool(ports.source_on_screen(canvas))
            card = ports.card_for_canvas(canvas)
            if card is secondary and not ports.split_active():
                on_screen = False
            state = self.state_for(key)
            for record_id, pill in list(state.pills.items()):
                if not _widget_alive(pill):
                    continue
                intent = _intent_in(collection, record_id)
                if not on_screen:
                    pill.setVisible(False)
                    continue
                if intent is None or intent.panel_expanded is not True:
                    # Never rewrite a user-collapsed panel as "not enough space".
                    pill.setVisible(False)
                    continue
                safe_changed = bool(ports.sync_pill_safe_rect(pill, card))
                if getattr(pill, "_host_pending", False):
                    if getattr(pill, "_visibility_requested", False):
                        pill._set_space_hidden(True)
                    continue
                if pill.is_dragging():
                    continue
                self._apply_pill_geometry(
                    state, pill, intent, collection, record_id,
                    safe_changed=safe_changed,
                )
                pill.setVisible(True)
                pill.raise_()
            if on_screen:
                self.arrange_pinned_panels(key, canvas, collection)
            if on_screen:
                self.nudge_live_from_pins(key, canvas)
            overlay = getattr(canvas, "_pinned_overlay", None)
            if overlay is not None:
                overlay.reproject()
            self.sync_tethers(key, canvas)

    def project_record(
        self,
        key,
        canvas,
        intent,
        sample,
        *,
        inherit_live=None,
        availability=None,
        collection=None,
    ) -> None:
        ports = self._ports
        host = ports.host_widget()
        stack = ports.stack_widget()
        status = availability or PIN_STATUS_READY
        expanded = intent.panel_expanded is True
        state = self.state_for(key)
        pill = state.pills.get(intent.record_id)
        if not _widget_alive(pill):
            pill = CursorPill(stack)
            pill.set_pin_role("pinned")
            pill.setFocusPolicy(Qt.TabFocus)
            pill.installEventFilter(self)
            pill.unpin_requested.connect(
                partial(ports.on_unpin, canvas, intent.record_id)
            )
            pill.close_requested.connect(
                partial(ports.on_close, canvas, intent.record_id)
            )
            pill.collapse_requested.connect(
                partial(ports.on_collapse_panel, canvas, intent.record_id)
            )
            pill.title_menu_active_changed.connect(
                partial(self._on_title_menu_active, canvas, intent.record_id)
            )
            pill.moved.connect(
                partial(self._on_pinned_moved, key, canvas, intent.record_id)
            )
            pill.display_mode_changed.connect(
                partial(ports.on_display_mode, canvas, intent.record_id)
            )
            pill._highlight_timer.timeout.connect(
                partial(self._publish_highlight, canvas)
            )
            state.pills[intent.record_id] = pill
        pill.set_ordinal(intent.ordinal)
        pill.set_pin_role("pinned")
        pill.set_live_hint("")
        if status != PIN_STATUS_READY:
            dismiss = getattr(pill, "dismiss_title_menu", None)
            if callable(dismiss):
                dismiss()
        card = ports.card_for_canvas(canvas)
        ports.sync_pill_safe_rect(pill, card)
        primary, projection = self.pill_content(intent, sample, status)
        pill.mark_user_placed(intent.anchor != DEFAULT_ANCHOR)
        self._bump_content_revision(state, intent.record_id)

        def update():
            if projection is not None:
                self._set_primary_original(pill, primary)
                pill.set_display_projection(projection)
            else:
                pill.set_display_projection(None)
                pill.set_primary(primary)
            pill.setVisible(expanded)

        ports.update_pill_content(pill, card, update)
        self._remember_typeset(state, pill, intent)
        if expanded:
            if pill.is_user_placed() and not pill.is_dragging():
                self.apply_anchor(
                    pill, collection, pill_record_id=intent.record_id,
                )
            pill.raise_()
            self.nudge_live_from_pins(key, canvas)

    def pill_content(self, intent, sample, status):
        if status == PIN_STATUS_PENDING:
            return pin_status_primary_html(intent, PENDING_TEXT), None
        if status == PIN_STATUS_INCOMPATIBLE_AXIS:
            return pin_status_primary_html(intent, INCOMPATIBLE_AXIS_TEXT), None
        if status == PIN_STATUS_UNAVAILABLE:
            if _sample_has_unchecked(sample):
                return pin_primary_html(intent), self.presentation_for(intent, sample)
            diagnostic = str(getattr(sample, "diagnostic", "") or "").strip()
            text = diagnostic or UNAVAILABLE_TEXT
            return pin_status_primary_html(intent, text), None
        return pin_primary_html(intent), self.presentation_for(intent, sample)

    def presentation_for(self, intent, sample):
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
        options = self._ports.cursor_display_options()
        return build_cursor_presentation(
            channels, options, cursor_mode=intent.mode, x_mode=x_mode, mini=mini,
        )

    def update_display_projection(
        self, key, canvas, intent, sample, status, collection,
    ) -> None:
        pill = self.pill_for(key, intent.record_id)
        if not _widget_alive(pill):
            return
        if status != PIN_STATUS_READY:
            self.project_record(
                key, canvas, intent, sample,
                availability=status, collection=collection,
            )
            return
        projection = self.presentation_for(intent, sample)
        self._set_primary_original(pill, pin_primary_html(intent))
        state = self.state_for(key)
        self._bump_content_revision(state, intent.record_id)
        if projection is not None:
            pill.set_display_projection(projection)
        self._remember_typeset(state, pill, intent)
        self.arrange_pinned_panels(key, canvas, collection)

    def raise_record(self, key, canvas, record_id) -> None:
        pill = self.pill_for(key, record_id)
        if _widget_alive(pill):
            pill.raise_()
            pill.flash_highlight()
        self._publish_highlight(canvas)

    def set_panel_endpoint(self, key, record_id, endpoint) -> None:
        """Remember only the current visual target of an expanded panel."""
        state = self.state_for(key)
        if endpoint in {"x", "a", "b"}:
            state.panel_endpoints[str(record_id)] = str(endpoint)
        else:
            state.panel_endpoints.pop(str(record_id), None)

    def sync_tethers(self, key, canvas) -> None:
        """Project visible pinned cards as transient canvas-local tether DTOs."""
        state = self._states.get(key)
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        stack = self._ports.stack_widget()
        if state is None or overlay is None or not _widget_alive(stack):
            if overlay is not None:
                overlay.set_tethers(())
            return
        host = overlay.host_rect()
        tethers = []
        mapped_panels = []
        for record in overlay.records():
            pill = state.pills.get(str(record.record_id))
            if not _widget_alive(pill) or not pill.isVisible():
                continue
            mapped = self._map_stack_rect_to_canvas(canvas, stack, pill.geometry())
            if mapped is None:
                continue
            mapped_panels.append((str(record.record_id), pill, mapped, record))
        obstacles_by_id = {
            record_id: (
                float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height()),
            )
            for record_id, _pill, rect, _record in mapped_panels
        }
        shared_obstacles = self._tether_cover_obstacles(canvas, stack)
        for record_id, pill, mapped, record in mapped_panels:
            endpoints = tuple(str(endpoint.key) for endpoint in record.endpoints)
            active = state.panel_endpoints.get(str(record.record_id))
            selected = (active,) if active in endpoints else endpoints
            if not selected:
                continue
            ports = tether_candidate_ports(mapped)
            if not ports:
                continue
            obstacles = tuple(
                rect for other_id, rect in obstacles_by_id.items()
                if other_id != record_id
            ) + shared_obstacles
            tethers.append(PinnedPanelTether(
                record_id=str(record.record_id),
                endpoints=selected,
                panel_rect=(
                    float(mapped.x()), float(mapped.y()),
                    float(mapped.width()), float(mapped.height()),
                ),
                ports=ports,
                obstacles=obstacles,
                panel_port=ports[0].point,
                host_rect=(
                    None if host is None else (
                        float(host.x()), float(host.y()),
                        float(host.width()), float(host.height()),
                    )
                ),
            ))
        overlay.set_tethers(tuple(tethers))

    def _tether_cover_obstacles(self, canvas, stack) -> tuple:
        """Canvas-space rects of sibling QWidgets that can hide a tether.

        Live Cursor panels and the already-exposed display popover are mapped
        the same way as Pin cards.  The DTO stores numbers only — never the
        QWidget pointer.  Legend/UltraView connectors are not host-owned here.
        """
        obstacles = []
        live = self._ports.live_pill(canvas)
        mapped_live = self._mapped_widget_obstacle(canvas, stack, live)
        if mapped_live is not None:
            obstacles.append(mapped_live)
        card = self._ports.card_for_canvas(canvas)
        popover = getattr(card, "cursor_display_popover", lambda: None)()
        if _widget_alive(popover) and popover.isVisible():
            try:
                frame = popover.frameGeometry()
                top_left = stack.mapFromGlobal(frame.topLeft())
                bottom_right = stack.mapFromGlobal(frame.bottomRight())
            except RuntimeError:
                pass
            else:
                mapped = self._map_stack_rect_to_canvas(
                    canvas, stack, QRect(top_left, bottom_right).normalized(),
                )
                if mapped is not None and mapped.isValid():
                    obstacles.append((
                        float(mapped.x()), float(mapped.y()),
                        float(mapped.width()), float(mapped.height()),
                    ))
        return tuple(obstacles)

    def _mapped_widget_obstacle(self, canvas, stack, widget):
        if not _widget_alive(widget) or not widget.isVisible():
            return None
        geo = widget.geometry()
        if not geo.isValid() or geo.width() < 2 or geo.height() < 2:
            return None
        mapped = self._map_stack_rect_to_canvas(canvas, stack, geo)
        if mapped is None or not mapped.isValid():
            return None
        return (
            float(mapped.x()), float(mapped.y()),
            float(mapped.width()), float(mapped.height()),
        )

    def flash_duplicate(self, key, canvas, record_id) -> None:
        if not record_id:
            return
        pill = self.pill_for(key, record_id)
        if _widget_alive(pill):
            pill.flash_highlight()
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        if overlay is not None:
            overlay.set_highlight(record_id)

    def _on_pinned_moved(self, key, canvas, record_id) -> None:
        state = self._states.get(key)
        if state is not None:
            state.auto_panel_rects.pop(record_id, None)
        on_moved = getattr(self._ports, "on_user_moved", None)
        if callable(on_moved):
            on_moved(canvas, record_id)
        self.sync_tethers(key, canvas)

    def anchor_from_pill(self, pill) -> PinnedCursorAnchor:
        return self._anchor_from_pill(pill)

    @staticmethod
    def _rect_within(rect, safe) -> bool:
        return bool(
            isinstance(rect, QRect)
            and rect.isValid()
            and isinstance(safe, QRect)
            and safe.isValid()
            and safe.contains(rect)
        )

    @staticmethod
    def _padded_rect(rect, gap=6) -> QRect:
        return QRect(rect).adjusted(-gap, -gap, gap, gap)

    def _panel_preferred_x(self, key, canvas, record_id, pill, safe) -> int:
        mapper = self._ports.map_canvas_rect_to_stack
        state = self._states.get(key)
        labels = state.axis_labels.values() if state is not None else ()
        for label in labels:
            if not _widget_alive(label):
                continue
            geom = label.geom()
            if geom is None or record_id not in geom.record_ids:
                continue
            mapped = mapper(canvas, QRect(int(round(geom.true_x)), 0, 1, 1))
            if mapped is not None and mapped.isValid():
                return mapped.center().x()
        return safe.center().x()

    def _panel_obstacles(self, key, canvas, candidates) -> list[QRect]:
        stack = self._ports.stack_widget()
        if not _widget_alive(stack):
            return []
        candidate_ids = {id(pill) for _intent, pill in candidates}
        obstacles = []
        for pill in stack.findChildren(CursorPill):
            if not _widget_alive(pill) or id(pill) in candidate_ids:
                continue
            if pill.isVisible() and pill.geometry().isValid():
                obstacles.append(self._padded_rect(pill.geometry()))
        state = self._states.get(key)
        labels = state.axis_labels.values() if state is not None else ()
        for label in labels:
            if _widget_alive(label) and label.isVisible() and label.geometry().isValid():
                obstacles.append(self._padded_rect(label.geometry(), gap=4))
        card = self._ports.card_for_canvas(canvas)
        popover = getattr(card, "cursor_display_popover", lambda: None)()
        if _widget_alive(popover) and popover.isVisible():
            try:
                top_left = stack.mapFromGlobal(popover.frameGeometry().topLeft())
                bottom_right = stack.mapFromGlobal(popover.frameGeometry().bottomRight())
            except RuntimeError:
                pass
            else:
                obstacles.append(self._padded_rect(QRect(top_left, bottom_right)))
        return obstacles

    def _panel_candidates(self, pill, safe, preferred_x):
        width, height = pill.width(), pill.height()
        if width <= 0 or height <= 0 or width > safe.width() or height > safe.height():
            return ()
        min_x = safe.left()
        max_x = safe.right() - width + 1
        min_y = safe.top()
        max_y = safe.bottom() - height + 1
        wanted_x = max(min_x, min(int(preferred_x - width / 2), max_x))
        x_step = max(24, min(120, max(1, width // 2)))
        y_step = max(18, min(96, max(1, height // 2)))
        xs = {wanted_x, min_x, max_x}
        ys = {min_y, max_y}
        for value in range(min_x, max_x + 1, x_step):
            xs.add(value)
        for value in range(min_y, max_y + 1, y_step):
            ys.add(value)
        ranked = []
        for y in sorted(ys):
            for x in sorted(xs, key=lambda item: (abs(item - wanted_x), item)):
                ranked.append(QRect(x, y, width, height))
        return tuple(ranked)

    def arrange_pinned_panels(self, key, canvas, collection) -> None:
        if collection is None:
            return
        state = self.state_for(key)
        candidates = []
        for intent in collection.records:
            if intent.panel_expanded is not True:
                continue
            pill = state.pills.get(intent.record_id)
            if not _widget_alive(pill):
                continue
            if pill.is_user_placed() or pill.is_dragging():
                continue
            candidates.append((intent, pill))
        if not candidates:
            state.auto_panel_rects.clear()
            state.auto_panel_safe_rect = None
            self.sync_tethers(key, canvas)
            return
        safe = candidates[0][1].safe_rect()
        if not safe.isValid() or safe.width() <= 0 or safe.height() <= 0:
            return
        active_ids = {intent.record_id for intent, _pill in candidates}
        state.auto_panel_rects = {
            record_id: QRect(rect)
            for record_id, rect in state.auto_panel_rects.items()
            if record_id in active_ids
        }
        same_safe = state.auto_panel_safe_rect == safe

        def place(*, preserve):
            occupied = self._panel_obstacles(key, canvas, candidates)
            placed = {}
            missing = []
            for intent, pill in candidates:
                stored = state.auto_panel_rects.get(intent.record_id)
                if (
                    preserve
                    and stored is not None
                    and self._rect_within(stored, safe)
                    and not any(stored.intersects(rect) for rect in occupied)
                ):
                    placed[intent.record_id] = QRect(stored)
                    occupied.append(self._padded_rect(stored))
                    continue
                preferred_x = self._panel_preferred_x(
                    key, canvas, intent.record_id, pill, safe,
                )
                chosen = next(
                    (
                        rect for rect in self._panel_candidates(
                            pill, safe, preferred_x,
                        )
                        if not any(rect.intersects(obstacle) for obstacle in occupied)
                    ),
                    None,
                )
                if chosen is None:
                    missing.append((intent, pill))
                    continue
                placed[intent.record_id] = chosen
                occupied.append(self._padded_rect(chosen))
            return placed, missing

        placed, missing = place(preserve=same_safe)
        if missing and len(candidates) > 1:
            placed, missing = place(preserve=False)
        for intent, pill in candidates:
            rect = placed.get(intent.record_id)
            if rect is None:
                pill._set_space_hidden(True)
                continue
            pill.move(rect.topLeft())
            pill._set_space_hidden(False)
            pill.raise_()
        state.auto_panel_rects = {
            record_id: QRect(rect) for record_id, rect in placed.items()
        }
        state.auto_panel_safe_rect = QRect(safe)
        self.sync_tethers(key, canvas)

    def apply_anchor(self, pill, collection, *, pill_record_id) -> None:
        if collection is None:
            return
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
    def _map_stack_rect_to_canvas(canvas, stack, rect):
        if not isinstance(rect, QRect) or not rect.isValid():
            return None
        try:
            top_left = canvas.mapFromGlobal(stack.mapToGlobal(rect.topLeft()))
            bottom_right = canvas.mapFromGlobal(stack.mapToGlobal(rect.bottomRight()))
        except RuntimeError:
            return None
        mapped = QRect(top_left, bottom_right).normalized()
        if not mapped.isValid():
            return None
        return mapped

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

    def nudge_live_from_pins(self, key, canvas) -> None:
        live = self._ports.live_pill(canvas)
        if live is None or not live.isVisible() or live.is_user_placed():
            return
        safe = live.safe_rect()
        if not safe.isValid():
            return
        geo = live.geometry()
        shifted = 0
        state = self._states.get(key)
        pills = state.pills.values() if state is not None else ()
        for pill in pills:
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

    def sync_overlay(
        self,
        key,
        canvas,
        *,
        collection,
        samples,
        availability,
        axis_edit,
    ) -> None:
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        if overlay is None:
            return
        overlay.set_records(self.overlay_records(
            canvas,
            collection=collection,
            samples=samples,
            availability=availability,
            axis_edit=axis_edit,
        ))
        self.sync_tethers(key, canvas)

    def overlay_records(
        self,
        canvas,
        *,
        collection,
        samples,
        availability,
        axis_edit,
    ):
        if collection is None:
            return ()
        records = []
        log_unavailable = getattr(self._ports, "log_unavailable", None)
        for intent in collection.records:
            status = availability.get(intent.record_id, PIN_STATUS_READY)
            if status == PIN_STATUS_INCOMPATIBLE_AXIS:
                continue
            previewing = axis_edit is not None and axis_edit.record_id == intent.record_id
            projected_intent = (
                axis_edit.candidate_intent
                if previewing and axis_edit.candidate_intent is not None
                else intent
            )
            sample = (
                axis_edit.candidate_sample
                if previewing and axis_edit.candidate_sample is not None
                else samples.get(intent.record_id)
            )
            extrema = tuple(getattr(sample, "extrema", ()) or ()) if sample is not None else ()
            hidden = _hidden_keys_from_sample(sample)
            if hidden:
                extrema = tuple(
                    item for item in extrema
                    if _identity_key(getattr(item, "identity", None)) not in hidden
                )
            if status == PIN_STATUS_UNAVAILABLE and callable(log_unavailable) and log_unavailable(
                canvas, intent,
            ):
                continue
            if projected_intent.mode == "dual":
                endpoints = (
                    PinnedOverlayEndpoint(
                        "a", float(projected_intent.ax),
                        f"P{projected_intent.ordinal}·A",
                    ),
                    PinnedOverlayEndpoint(
                        "b", float(projected_intent.bx),
                        f"P{projected_intent.ordinal}·B",
                    ),
                )
            else:
                x_value = _finite(projected_intent.x)
                if x_value is None:
                    continue
                endpoints = (
                    PinnedOverlayEndpoint(
                        "x", x_value, f"P{projected_intent.ordinal}",
                    ),
                )
            records.append(PinnedOverlayRecord(
                record_id=projected_intent.record_id,
                ordinal=int(projected_intent.ordinal),
                mode=projected_intent.mode,
                domain=projected_intent.domain,
                endpoints=endpoints,
                extrema=extrema,
            ))
        return tuple(records)

    def _on_overlay_layout(self, key, canvas, layout) -> None:
        prepare = getattr(self._ports, "prepare_overlay_layout", None)
        if callable(prepare) and not prepare(canvas):
            return
        self.project_axis_labels(key, canvas, layout)
        self.apply_offscreen(key, layout)

    def project_axis_labels(self, key, canvas, layout) -> None:
        ports = self._ports
        stack = ports.stack_widget()
        mapper = ports.map_canvas_rect_to_stack
        on_screen = bool(ports.source_on_screen(canvas))
        collection = ports.collection_for(canvas)
        current_ids = _collection_record_ids(collection)
        expanded_ids = frozenset(
            item.record_id
            for item in getattr(collection, "records", ()) or ()
            if getattr(item, "panel_expanded", False) is True
        )
        state = self.state_for(key)
        wanted = {}
        if (
            layout is not None
            and not layout.pending
            and on_screen
            and callable(mapper)
        ):
            for geom in layout.items:
                if not _layout_item_in_collection(geom, current_ids):
                    continue
                mapped = mapper(canvas, QRect(*geom.canvas_rect))
                if mapped is None or not mapped.isValid():
                    continue
                wanted[geom.key] = (geom, mapped)
        for label_key in list(state.axis_labels):
            if label_key not in wanted:
                label = state.axis_labels[label_key]
                if _widget_alive(label) and label.pointer_captured():
                    continue
                self.destroy_axis_label(state.axis_labels.pop(label_key))
        for label_key, (geom, mapped) in wanted.items():
            label = state.axis_labels.get(label_key)
            if not _widget_alive(label):
                label = PinnedAxisLabel(stack)
                label.panel_requested.connect(
                    partial(ports.on_toggle_panel, canvas)
                )
                label.edit_started.connect(partial(ports.on_edit_started, canvas))
                label.edit_preview.connect(partial(ports.on_edit_preview, canvas))
                label.edit_committed.connect(partial(ports.on_edit_committed, canvas))
                label.edit_cancelled.connect(partial(ports.on_edit_cancelled, canvas))
                label.nudge_requested.connect(partial(ports.on_nudge, canvas))
                label.hover_changed.connect(partial(self.set_hover, canvas))
                label.edit_started.connect(
                    partial(self._on_label_capture_started, canvas)
                )
                label.edit_committed.connect(
                    partial(self._on_label_capture_finished, canvas)
                )
                label.edit_cancelled.connect(
                    partial(self._on_label_capture_finished, canvas)
                )
                state.axis_labels[label_key] = label
            if not label.pointer_captured():
                label.apply_geom(geom)
                label.move(mapped.x(), mapped.y())
            label.set_panel_open(
                bool(expanded_ids.intersection(
                    str(item) for item in geom.record_ids
                )),
                expanded_ids.intersection(str(item) for item in geom.record_ids),
            )
            label.setVisible(True)
            highlight = self._hover_matches(canvas, geom.record_ids)
            label.set_highlighted(highlight)
            label.raise_()

    def apply_offscreen(self, key, layout) -> None:
        offscreen = layout.offscreen_ids if layout is not None else frozenset()
        state = self._states.get(key)
        if state is None:
            return
        for record_id, pill in state.pills.items():
            if not _widget_alive(pill):
                continue
            away = record_id in offscreen
            pill.setProperty("pinnedOffscreen", away)
            pill.setToolTip(PINNED_OFFSCREEN_TEXT if away else "")

    def set_hover(self, canvas, target) -> None:
        state = self._states.get(id(canvas))
        if state is not None:
            state.hover_target = None if target in (None, "", (), []) else target
        self._publish_highlight(canvas)

    def _on_title_menu_active(self, canvas, record_id, active=False) -> None:
        if not _widget_alive(canvas):
            return
        if active:
            self._begin_capture(canvas, record_id)
            return
        pill = self.pill_for(id(canvas), record_id)
        self._end_capture(canvas, pill, record_id)

    def _begin_capture(self, canvas, record_id) -> None:
        state = self._states.get(id(canvas))
        if state is None or not record_id:
            return
        if state.capture_target == record_id:
            return
        state.capture_target = record_id
        if state.hover_target in (None, "", (), []):
            state.hover_target = record_id
        self._publish_highlight(canvas)

    def _end_capture(self, canvas, pill, record_id) -> None:
        state = self._states.get(id(canvas))
        if state is None:
            return
        if not _target_includes(state.capture_target, record_id):
            return
        state.capture_target = None
        state.hover_target = self._resynthesize_hover(canvas, pill, record_id)
        self._publish_highlight(canvas)

    def _resynthesize_hover(self, canvas, widget, record_id):
        if _widget_holds_interaction(widget):
            return record_id
        state = self._states.get(id(canvas))
        if state is None:
            return None
        for label in state.axis_labels.values():
            if not _widget_holds_interaction(label):
                continue
            ids = label.record_ids()
            if not ids:
                continue
            return ids[0] if len(ids) == 1 else ids
        for other_id, other in state.pills.items():
            if _widget_holds_interaction(other):
                return other_id
        return None

    def _locate_target(self, state):
        for record_id, pill in state.pills.items():
            if not _widget_alive(pill):
                continue
            timer = getattr(pill, "_highlight_timer", None)
            if timer is not None and timer.isActive():
                return record_id
        return None

    def _publish_highlight(self, canvas) -> None:
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
        state = self._states.get(id(canvas))
        capture = None if state is None else state.capture_target
        hover = None if state is None else state.hover_target
        locate = None if state is None else self._locate_target(state)
        if capture not in (None, "", (), []):
            target = capture
            stop_locate = True
        elif hover not in (None, "", (), []):
            target = hover
            stop_locate = True
        else:
            target = locate
            stop_locate = False
        if overlay is not None:
            overlay.set_highlight(target)
        ids = set()
        if isinstance(target, (tuple, list, set, frozenset)):
            ids.update(str(item) for item in target)
        elif target:
            ids.add(str(target))
        if state is None:
            return
        for record_id, pill in state.pills.items():
            if not _widget_alive(pill):
                continue
            timer = getattr(pill, "_highlight_timer", None)
            interactive = record_id in ids
            if stop_locate and interactive and timer is not None:
                timer.stop()
            locate_on = timer is not None and timer.isActive()
            highlighted = interactive or locate_on
            pill._highlighted = highlighted
            if highlighted:
                pill.raise_()
            pill.update()
        for label in state.axis_labels.values():
            if not _widget_alive(label):
                continue
            label.set_highlighted(bool(ids.intersection(label.record_ids())))

    def _hover_matches(self, canvas, record_ids) -> bool:
        overlay = getattr(canvas, "_pinned_overlay", None) if _widget_alive(canvas) else None
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
        key, record_id = self.canvas_and_record_for_pill(pill)
        if key is None:
            return
        state = self._states.get(key)
        canvas = state.canvas if state is not None else None
        if not _widget_alive(canvas):
            return
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.set_hover(canvas, record_id)
            self._begin_capture(canvas, record_id)
            return
        if etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._end_capture(canvas, pill, record_id)
            return
        if etype in (QEvent.Enter, QEvent.FocusIn):
            self.set_hover(canvas, record_id)
            return
        if state is not None and _target_includes(state.capture_target, record_id):
            return
        if etype in (QEvent.Leave, QEvent.FocusOut):
            QTimer.singleShot(
                0, partial(self._resynthesize_pill_hover, canvas, pill, record_id)
            )
            return
        self.set_hover(canvas, None)

    def _resynthesize_pill_hover(self, canvas, pill, record_id) -> None:
        state = self._states.get(id(canvas))
        if state is None:
            return
        if _target_includes(state.capture_target, record_id):
            return
        if _widget_holds_interaction(pill):
            self.set_hover(canvas, record_id)
            return
        if not _target_includes(state.hover_target, record_id):
            return
        state.hover_target = self._resynthesize_hover(canvas, None, None)
        self._publish_highlight(canvas)

    def _on_pinned_pill_geometry(self, pill, event=None) -> None:
        """Follow a live panel without sampling or writing the collection."""
        if self._in_layout or pill.pin_role() != "pinned":
            return
        key, record_id = self.canvas_and_record_for_pill(pill)
        if key is None:
            return
        state = self._states.get(key)
        canvas = state.canvas if state is not None else None
        if not _widget_alive(canvas):
            return
        if pill.is_dragging():
            self._begin_capture(canvas, record_id)
        elif event is not None and event.type() == QEvent.Hide:
            self._end_capture(canvas, pill, record_id)
        try:
            self.sync_tethers(key, canvas)
        except RuntimeError:
            return

    def _on_label_capture_started(self, canvas, record_id, *rest) -> None:
        self._begin_capture(canvas, record_id)

    def _on_label_capture_finished(self, canvas, record_id, *rest) -> None:
        state = self._states.get(id(canvas))
        widget = None
        if state is not None:
            wanted = str(record_id)
            for label in state.axis_labels.values():
                if _widget_alive(label) and wanted in label.record_ids():
                    widget = label
                    break
        self._end_capture(canvas, widget, record_id)

    def _store_pending_owners(self, owners) -> None:
        self._merge_owner_keys(owners)
        for key, _canvas, *_rest in owners:
            state = self.state_for(key)
            state.pending = True
            state.pending_token = state.layout_token
            state.request_serial += 1

    def _merge_owner_keys(self, owners) -> None:
        by_key = {item[0]: item[:2] for item in self._pending_owners}
        for item in owners:
            if not item:
                continue
            by_key[item[0]] = (item[0], item[1])
        self._pending_owners = list(by_key.values())

    def _resolve_owner_collection(self, key, canvas):
        getter = getattr(self._ports, "collection_for", None)
        if callable(getter):
            return getter(canvas)
        return None

    def _has_pending(self) -> bool:
        return any(state.pending for state in self._states.values())

    def _cancel_layout_timer(self) -> None:
        timer = self._layout_timer
        if timer is None:
            return
        try:
            timer.stop()
        except RuntimeError:
            pass

    def _schedule_layout(self) -> None:
        if self._in_layout:
            self._repeat_requested = True
            return
        if not self._has_pending():
            return
        timer = self._layout_timer
        if timer is None:
            self._apply_pending_layout()
            return
        try:
            if not timer.isActive():
                timer.start(0)
        except RuntimeError:
            self._apply_pending_layout()

    def _on_layout_timer(self) -> None:
        self._apply_pending_layout()

    def _apply_pending_layout(self) -> None:
        if self._in_layout:
            self._repeat_requested = True
            return
        owners = []
        started = {}
        for key, canvas, *_rest in list(self._pending_owners):
            state = self._states.get(key)
            if state is None or not state.pending:
                continue
            if state.pending_token != state.layout_token:
                state.pending = False
                continue
            collection = self._resolve_owner_collection(key, canvas)
            owners.append((key, canvas, collection))
            started[key] = state.request_serial
        self._in_layout = True
        try:
            if owners:
                self.reflow_now(owners)
            for key, _canvas, _collection in owners:
                state = self._states.get(key)
                if state is None:
                    continue
                if (
                    state.pending_token == state.layout_token
                    and state.request_serial == started.get(key)
                ):
                    state.pending = False
                    state.applied_token = state.layout_token
            self._pending_owners = [
                item[:2] for item in self._pending_owners
                if self._states.get(item[0]) is not None
                and self._states[item[0]].pending
            ]
        finally:
            self._in_layout = False
        if self._repeat_requested:
            self._repeat_requested = False
            if self._has_pending():
                self._schedule_layout()

    def _clamp_overflow_now(self, owners) -> None:
        """Hide or clamp overflowing expanded cards without typesetting."""
        ports = self._ports
        secondary = ports.secondary_card()
        for key, canvas, collection in owners:
            if not _widget_alive(canvas):
                continue
            on_screen = bool(ports.source_on_screen(canvas))
            card = ports.card_for_canvas(canvas)
            if card is secondary and not ports.split_active():
                on_screen = False
            state = self._states.get(key)
            if state is None:
                continue
            for record_id, pill in list(state.pills.items()):
                if not _widget_alive(pill):
                    continue
                intent = _intent_in(collection, record_id)
                if not on_screen or intent is None or intent.panel_expanded is not True:
                    continue
                ports.sync_pill_safe_rect(pill, card)
                if getattr(pill, "_host_pending", False):
                    if getattr(pill, "_visibility_requested", False):
                        pill._set_space_hidden(True)
                    continue
                if pill.is_dragging():
                    continue
                safe = pill.safe_rect()
                if not safe.isValid() or safe.width() <= 0 or safe.height() <= 0:
                    continue
                if pill.width() > safe.width() or pill.height() > safe.height():
                    pill._set_space_hidden(True)
                    continue
                clamp = getattr(pill, "_clamp_to_safe_rect", None)
                if callable(clamp):
                    clamp()

    def _apply_pill_geometry(
        self, state, pill, intent, collection, record_id, *, safe_changed,
    ) -> None:
        if pill.is_dragging():
            if safe_changed:
                clamp = getattr(pill, "_clamp_to_safe_rect", None)
                if callable(clamp):
                    clamp()
            return
        projection = getattr(pill, "_display_projection", None)
        awaiting = bool(pill.awaiting_space())
        content_rev = state.content_revisions.get(record_id, 0)
        fingerprint = self._typeset_key(pill, intent, content_rev)
        last = state.layout_fingerprints.get(record_id)
        size_changed = last is None or last[:2] != fingerprint[:2]
        should_typeset = projection is not None and (
            last != fingerprint or (awaiting and size_changed)
        )
        if should_typeset:
            pill.reflow_to_parent()
            self._remember_typeset(state, pill, intent)
        elif safe_changed:
            clamp = getattr(pill, "_clamp_to_safe_rect", None)
            if callable(clamp):
                clamp()
        if pill.is_user_placed():
            self.apply_anchor(pill, collection, pill_record_id=record_id)

    @staticmethod
    def _style_revision(pill) -> tuple:
        try:
            font_key = pill.font().key() if pill.font() is not None else ""
        except RuntimeError:
            font_key = ""
        try:
            dpi = (int(pill.logicalDpiX()), int(pill.logicalDpiY()))
        except (RuntimeError, TypeError):
            dpi = (0, 0)
        try:
            dpr = round(float(pill.devicePixelRatioF()), 4)
        except (RuntimeError, TypeError, AttributeError):
            dpr = 1.0
        return (font_key, dpi, dpr)

    def _typeset_key(self, pill, intent, content_rev) -> tuple:
        safe = pill.safe_rect()
        projection = getattr(pill, "_display_projection", None)
        presentation = getattr(intent, "presentation", None)
        mini = presentation == "mini" if presentation is not None else bool(
            getattr(projection, "mini", False)
        )
        return (
            int(safe.width()) if safe.isValid() else 0,
            int(safe.height()) if safe.isValid() else 0,
            mini,
            content_rev,
            self._style_revision(pill),
            id(projection) if projection is not None else None,
            getattr(pill, "_primary_original", None),
        )

    @staticmethod
    def _bump_content_revision(state, record_id) -> None:
        state.content_revisions[record_id] = state.content_revisions.get(record_id, 0) + 1

    def _remember_typeset(self, state, pill, intent) -> None:
        if not _widget_alive(pill) or intent is None:
            return
        record_id = intent.record_id
        state.layout_fingerprints[record_id] = self._typeset_key(
            pill, intent, state.content_revisions.get(record_id, 0),
        )

    @staticmethod
    def _set_primary_original(pill, primary) -> None:
        # Projector-owned pill: keep original HTML for later reflow.
        pill._primary_original = primary

    @staticmethod
    def _cancel_pill_timers(pill) -> None:
        if not _widget_alive(pill):
            return
        timer = getattr(pill, "_highlight_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
        except RuntimeError:
            pass


def _collection_record_ids(collection) -> frozenset[str]:
    records = getattr(collection, "records", ()) or ()
    return frozenset(str(item.record_id) for item in records)


def _layout_item_in_collection(geom, current_ids) -> bool:
    """Reject overlay chips whose members are not in the live collection."""
    if not current_ids:
        return False
    geom_ids = tuple(str(item) for item in getattr(geom, "record_ids", ()) or ())
    if not geom_ids:
        return False
    return all(record_id in current_ids for record_id in geom_ids)


def _intent_in(collection, record_id):
    if collection is None:
        return None
    for item in collection.records:
        if item.record_id == record_id:
            return item
    return None
