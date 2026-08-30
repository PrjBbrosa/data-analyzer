"""ViewMixin: time-domain split-view switch / capture / render pipeline."""

from contextlib import contextmanager
from dataclasses import replace
from functools import partial

from PyQt5 import sip
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QColorDialog, QMessageBox

from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text
from ..time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    CustomXAxisSpec,
    selection_payload,
)
from ..chart_stack.toolbar import DEFAULT_CHART_TICK_DENSITY
from . import view_activation


class ViewMixin:
    """Domain mixin: the time-domain View system (named views + split panes).

    Covers the capture → switch → apply → render pipeline for the time
    section's cross-view pairing, plus the view tab-bar intent handlers
    (new / delete / duplicate / color).  Instance state these methods read
    (``self._primary_view_idx`` / ``_secondary_view_idx`` /
    ``_focused_view_idx`` / ``_applying_view`` / ``_view_bridge`` /
    ``view_manager`` / ``canvas_time`` / ``chart_stack``) is created in
    ``MainWindow.__init__`` / ``_init_ui``.

    Time-domain plotting (``_plot_time_on_canvas``) and the analysis-section
    switch (``_on_analysis_switch``) remain on other classes and resolve
    through the MRO via ``self.``.
    """

    # -- render re-entrancy gate ------------------------------------------
    #
    # A time render is NOT atomic: `_begin_compute_progress` pumps the Qt
    # event loop so the status-bar bar reaches the screen, and any 0 ms timer
    # already posted (UltraView `navigate_to_view`) is delivered inside that
    # pump.  A View switch executing there re-enters this pipeline on the same
    # canvas -- the outer render then finishes on top of the inner one and the
    # tab highlight, the navigator projection and the painted curves describe
    # three different Views.  The gate below turns that into a serial replay.

    def _time_render_gate(self):
        """The window's :class:`TimeRenderGate`, or ``None`` on a bare host.

        Test doubles bind these methods onto plain namespaces that never ran
        ``MainWindow.__init__``; they get the historical unguarded behaviour.
        """
        return getattr(self, "_time_render", None)

    @contextmanager
    def _time_render_scope(self):
        """Mark a render in flight; replay a deferred switch once it unwinds."""
        gate = self._time_render_gate()
        if gate is None:
            yield
            return
        gate.enter()
        try:
            yield
        finally:
            gate.leave()
            if not gate.busy:
                self._schedule_pending_view_switch()

    def _time_render_busy(self) -> bool:
        gate = self._time_render_gate()
        return gate is not None and gate.busy

    def _schedule_pending_view_switch(self) -> None:
        """Replay the parked switch on the next event-loop turn, not inline.

        Inline would land in the middle of whatever called us:
        ``_apply_active_view`` renders two panes back to back, and
        ``plot_time``'s callers keep working on the canvas after it returns.  A
        queued turn is also exactly when the real click would have been handled
        had the pump not been open.
        """
        gate = self._time_render_gate()
        if gate is None or gate.pending_view_id is None or gate.drain_scheduled:
            return
        gate.drain_scheduled = True
        QTimer.singleShot(0, self._drain_pending_view_switch)

    def _drain_pending_view_switch(self) -> None:
        gate = self._time_render_gate()
        if gate is None:
            # No gate => nothing was ever parked (bare test host).  Checked
            # before the sip probe below, which only accepts a real wrapper.
            return
        # Clear the scheduling flag FIRST: every early return below must leave
        # the gate able to schedule again, or a later parked switch would never
        # be replayed.
        gate.drain_scheduled = False
        # A queued drain can outlive the window it belongs to (close during a
        # render). Replaying there drives a full render through a widget tree
        # that is gone -- ``closeEvent`` drops the intent for an orderly close,
        # this covers a window already destroyed when the timer fires.
        if sip.isdeleted(self):
            gate.clear_pending_switch()
            return
        if gate.busy:
            # Another render started meanwhile; its scope exit re-schedules us.
            return
        view_id = gate.take_pending_switch()
        if view_id is None:
            return
        idx = next(
            (
                i
                for i, state in enumerate(self.view_manager.views)
                if str(getattr(state, "view_id", "")) == view_id
            ),
            None,
        )
        if idx is None:
            return
        if idx == self.view_manager.active:
            # Nothing to switch, but the tab bar moved its current index on the
            # click that got deferred; put the highlight back on the View that
            # is actually shown.
            tabbar = getattr(self, "view_tabbar", None)
            refresh = getattr(tabbar, "refresh", None)
            if callable(refresh):
                refresh()
            return
        self._switch_view(idx)

    def _connect_canvas_range_signals(self, canvas):
        visible_range_changed = getattr(canvas, 'visible_range_changed', None)
        if visible_range_changed is not None:
            visible_range_changed.connect(
                lambda c=canvas: self._capture_canvas_ranges_for_bound_view(c)
            )

    def _connect_channel_color_sync(self, canvas):
        """Wire a time canvas's recolor signal back to the navigator so the
        left channel-list swatch (and the color source-of-truth used by time
        replot + FFT/order analysis) follows a 图表选项 recolor. Idempotent per
        canvas via the ``_color_sync_connected`` guard."""
        if canvas is None or getattr(canvas, '_color_sync_connected', False):
            return
        sig = getattr(canvas, 'channel_color_changed', None)
        if sig is None:
            return
        sig.connect(self._on_canvas_channel_color_changed)
        canvas._color_sync_connected = True

    def _on_canvas_channel_color_changed(self, data_id, display_name, color):
        """A curve was recolored on a canvas. Map its display name back to the
        raw ``(fid, ch)`` and write ``navigator._colors`` so the swatch icon
        and every replot/analysis that reads navigator colors stay in sync.

        No-op when the display name resolves to no channel — e.g. a display-
        only filtered overlay (``"[x] ch (LP 50Hz)"``) has no navigator row."""
        resolved = self._resolve_navigator_channel_key(data_id, display_name)
        if resolved is None:
            return
        fid, ch = resolved
        setter = getattr(self.navigator, 'set_channel_colors', None)
        if callable(setter):
            setter({(fid, ch): str(color)})

    def _resolve_navigator_channel_key(self, data_id, display_name):
        """Invert ``fd.get_prefixed_channel(ch) == display_name`` to recover the
        raw ``(fid, ch)`` navigator key. ``data_id`` narrows the search to the
        exact file (multi-file same-display-name collision class); compare via
        ``str`` because the composite key may have stringified the fid."""
        if not display_name:
            return None
        for fid, fd in self.files.items():
            if data_id is not None and str(fid) != str(data_id):
                continue
            columns = getattr(getattr(fd, 'data', None), 'columns', None)
            if columns is None:
                continue
            for ch in columns:
                if fd.get_prefixed_channel(ch) == display_name:
                    return (fid, ch)
        return None

    def _ensure_secondary_range_signal_connected(self):
        canvas = self.chart_stack.secondary_canvas()
        if canvas is None or getattr(canvas, '_view_range_connected', False):
            return
        self._connect_canvas_range_signals(canvas)
        self._connect_channel_color_sync(canvas)
        xrange_changed = getattr(canvas, 'xrange_changed', None)
        if xrange_changed is not None:
            xrange_changed.connect(self._on_secondary_canvas_xrange_changed)
        canvas._view_range_connected = True

    def _capture_current_view(self):
        self._capture_focused_view()

    def _sync_pane_bindings_from_manager(self):
        self._view_focus.bind(
            active=self.view_manager.active,
            partner=self.view_manager.split_with,
        )

    def _view_index_for_canvas(self, canvas):
        if canvas is self.canvas_time:
            return self._primary_view_idx
        secondary = self.chart_stack.secondary_canvas()
        if secondary is not None and canvas is secondary:
            return self._secondary_view_idx
        return None

    def _canvas_for_view_index(self, idx):
        if idx == self._primary_view_idx:
            return self.canvas_time
        if idx == self._secondary_view_idx:
            return self.chart_stack.secondary_canvas()
        return None

    def _capture_canvas_ranges_for_bound_view(self, canvas):
        if getattr(self, '_applying_view', False):
            return
        idx = self._view_index_for_canvas(canvas)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        self._view_bridge.capture_canvas_ranges_into(self.view_manager.get(idx), canvas)

    def _capture_focused_view(self):
        # Time-domain View capture only — analysis modes project a different
        # attachment set onto the navigator; writing that back would corrupt
        # Time View attached/checked/colors (A1). Symmetric with the analysis
        # capture guard that already keys off current_mode.
        if self.chart_stack.current_mode() != 'time':
            return
        # Mid-render the screen is a MIXTURE: the navigator already holds the
        # incoming View's channels while the canvas still shows the outgoing
        # frame (or a half-built one). Capturing that writes another View's
        # channels/xlim into whichever View currently owns the focus — the
        # "View 2 变成 View 3 的内容" / blank-chart corruption. Same reasoning as
        # the `_applying_view` guard on `_capture_canvas_ranges_for_bound_view`;
        # every caller here is a user intent that re-runs on its own later.
        if self._time_render_busy() or getattr(self, '_applying_view', False):
            return
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        state = self.view_manager.get(idx)
        self._view_bridge.capture_controls_into(state, self, canvas)
        self._view_bridge.capture_canvas_ranges_into(state, canvas)

    def _capture_overlay_primary_into_focused_view(self):
        """Persist ``_overlay_primary`` without capturing navigator scope (A1).

        ``设为左轴`` is a time-View field. In analysis mode the navigator
        shows a different attachment set, so full ``_capture_focused_view``
        must stay gated off; this writes only the pick onto the focused
        time View so a later projection / save does not revert it.
        """
        if getattr(self, '_applying_view', False):
            return
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            idx = self.view_manager.active
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        self.view_manager.get(idx).overlay_primary = getattr(
            self, "_overlay_primary", None,
        )

    def _project_view_controls(self, idx):
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        old_applying_view = getattr(self, '_applying_view', False)
        self._applying_view = True
        try:
            self._view_bridge.apply_controls_from_state(
                self.view_manager.get(idx), self, canvas
            )
        finally:
            self._applying_view = old_applying_view
        # Analysis pickers follow each analysis View's own attachments
        # (Stage 1 source isolation). Time View projection must not rebuild
        # analysis candidates — that would re-couple the two scopes.
        state = self.view_manager.get(idx)
        empty = getattr(self.navigator, 'set_empty_state_context', None)
        if callable(empty):
            empty(section_label='时域', view_name=state.name)
        self._sync_record_curve_tree(state)

    def _sync_focus_accent(self):
        idx = self._focused_view_idx
        color = None
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            color = self.view_manager.get(idx).tab_color
        setter = getattr(self.chart_stack, 'set_focus_accent', None)
        if callable(setter):
            setter(color)

    def _hint_focused_pane(self, action_label):
        if not self.chart_stack.split_active():
            return False
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return False
        role = "主栏" if idx == self._primary_view_idx else "副栏"
        name = self.view_manager.get(idx).name
        self.toast(f"{action_label} 作用于 {role} · {name} · 点另一栏可改", "info")
        return True

    def _install_view_shortcuts(self):
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtCore import Qt
        self._view_shortcuts = []
        for i in range(9):
            sc = QShortcut(QKeySequence(f"Alt+{i + 1}"), self)
            sc.setContext(Qt.ApplicationShortcut)
            idx = i
            sc.activated.connect(
                lambda bound=idx: self._switch_view_for_active_section(bound))
            self._view_shortcuts.append(sc)

    def _switch_view_for_active_section(self, idx):
        """Alt+i: switch the view of whatever section is currently shown.

        The time section keeps the cross-view pairing path (``_switch_view``);
        analysis sections (fft/fft_time/frf/order) route to their own manager via
        ``_on_analysis_switch``. Both already guard idx range + no-op on no
        change, so out-of-range Alt keys are safe.
        """
        mode = self.chart_stack.current_mode()
        if mode in ('fft', 'fft_time', 'frf', 'order'):
            self._on_analysis_switch(mode, idx)
        else:
            self._switch_view(idx)

    def _switch_view(self, idx):
        if not (0 <= idx < len(self.view_manager.views)):
            return
        gate = self._time_render_gate()
        if gate is not None and gate.busy:
            # A render owns the canvas. Park the intent (by view id, so a
            # concurrent delete/reorder cannot redirect it) and replay it once
            # the pipeline unwinds; the newest click wins.
            gate.defer_switch(getattr(self.view_manager.get(idx), "view_id", None))
            return
        if gate is not None:
            # An executed switch supersedes anything parked earlier.
            gate.clear_pending_switch()
        if idx == self.view_manager.active:
            return
        self._capture_focused_view()
        self.view_manager.set_active(idx)

    def _apply_active_view(self, idx):
        if not (0 <= idx < len(self.view_manager.views)):
            return
        self._sync_pane_bindings_from_manager()
        partner = self.view_manager.split_with
        if partner is None:
            self.chart_stack.exit_split()
        else:
            self.chart_stack.enter_split()
            self._ensure_secondary_range_signal_connected()
        self._view_focus.focused = idx
        self._sync_focus_accent()
        # The shared navigator belongs to the visible section.  A Time-view
        # restore may still call this method while an analysis section is on
        # screen (notably at the end of project reopen); in that case it must
        # not overwrite the analysis View's projected attachments/empty owner.
        if self.chart_stack.current_mode() == 'time':
            if self.files:
                self._render_view_to_canvas(
                    idx, self.canvas_time, update_primary_ui=True)
                if partner is not None:
                    self._render_view_to_canvas(
                        partner,
                        self.chart_stack.secondary_canvas(),
                        update_primary_ui=False,
                    )
            else:
                self._project_view_controls(idx)

    def _on_view_split(self, other_idx):
        self._capture_focused_view()
        self._sync_pane_bindings_from_manager()
        if other_idx is None:
            self.chart_stack.exit_split()
            self._view_focus.secondary = None
            self._view_focus.focused = self.view_manager.active
            self._sync_focus_accent()
            # F8: mirror `_apply_active_view` — only the time section owns the
            # shared navigator projection. Non-time must not fall through the
            # "no files" else and overwrite an analysis View's empty-state.
            if self.chart_stack.current_mode() == 'time':
                if self.files:
                    self._render_view_to_canvas(
                        self.view_manager.active,
                        self.canvas_time,
                        update_primary_ui=True,
                    )
                else:
                    self._project_view_controls(self.view_manager.active)
            return
        if not (0 <= other_idx < len(self.view_manager.views)):
            self.chart_stack.exit_split()
            return

        self.chart_stack.enter_split()
        self._ensure_secondary_range_signal_connected()
        self._view_focus.focused = self.view_manager.active
        self._sync_focus_accent()
        if self.chart_stack.current_mode() == 'time':
            if self.files:
                self._render_view_to_canvas(
                    self.view_manager.active, self.canvas_time, update_primary_ui=True
                )
                self._render_view_to_canvas(
                    other_idx, self.chart_stack.secondary_canvas(), update_primary_ui=False
                )
            else:
                self._project_view_controls(self.view_manager.active)

    def _on_view_clear_split(self, idx):
        self._capture_focused_view()
        self.view_manager.clear_split_for(idx)

    def _on_time_view_rename(self, idx, name):
        """F10: rename then refresh navigator empty-state for the active View."""
        self.view_manager.rename(idx, name)
        if self.chart_stack.current_mode() != 'time':
            return
        if idx != self.view_manager.active:
            return
        if not (0 <= idx < len(self.view_manager.views)):
            return
        state = self.view_manager.get(idx)
        empty = getattr(self.navigator, 'set_empty_state_context', None)
        if callable(empty):
            empty(section_label='时域', view_name=state.name)

    def _restore_view_xlim(self, canvas, xlim):
        """Restore a View's saved X window unless it no longer frames the data.

        A saved window is always a window INTO the data it was captured on, so
        restoring it verbatim is right whenever the View still draws that data.
        When it does not — the View's files/channels changed, or a re-entrant
        capture wrote another View's zoom into this one — the window can sit
        entirely outside the plotted extent and the chart renders blank with no
        way back: 绘图 rebinds the same curves without touching X, so only
        右键·全图 recovers it. Reuse the reframe predicate the plot-mode toggle
        already uses (``_preserved_xlim_fits_data``) and fall back to the data
        union.

        Both branches leave the View-restore transaction OPEN (2026-08-15
        view-switch quality settlement spec §3.1): ``plot_channels`` already
        set ``_refresh_pending`` when it deferred the first frame for this
        restore, so the caller's ``settle_view_restore()`` -- invoked after Y
        and tick density land -- is what actually flushes. Reframing here and
        then flushing immediately (the old behaviour) would measure ink
        against the not-yet-restored Y, the exact bug that spec fixed for the
        verbatim-restore path.

        Hosts without the predicate (test doubles) keep the verbatim restore.
        """
        if xlim is None:
            return
        fits = getattr(self, '_preserved_xlim_fits_data', None)
        frame = getattr(canvas, 'frame_x_to_data', None)
        keep = True
        if callable(fits) and callable(frame):
            try:
                lo, hi = (float(value) for value in xlim)
            except (TypeError, ValueError):
                lo = hi = None
            if lo is not None:
                keep = bool(fits(canvas, lo, hi))
        if keep:
            canvas.restore_visible_xlim(xlim, flush=False)
            return
        frame()

    def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
        """Project View ``idx`` onto ``canvas``, serialized against re-entry.

        The scope is the whole projection, not just the plot: apply-controls,
        plot, X/Y restore and the navigator re-projection in the tail must all
        describe ONE View, and the plot in the middle pumps the event loop.
        """
        with self._time_render_scope():
            return self._render_view_onto_canvas(
                idx, canvas, update_primary_ui=update_primary_ui,
            )

    def _render_view_onto_canvas(self, idx, canvas, *, update_primary_ui):
        if canvas is None:
            return
        if not (0 <= idx < len(self.view_manager.views)):
            return
        state = self.view_manager.get(idx)
        coord = getattr(self, "_ultraview", None)
        if coord is not None:
            from ..ultraview_state import UltraViewRef

            coord.offer_capture_bound_canvas(
                canvas, incoming_ref=UltraViewRef("time", state.view_id)
            )

        # Snapshot/restore is only for off-screen secondary renders in split
        # mode. Primary view switches must show the target view's cursor state,
        # not the previous view's last readout.
        cursor_pill_snapshot = (
            self.chart_stack.cursor_pill_snapshot()
            if not update_primary_ui
            else None
        )
        restore_idx = self._focused_view_idx
        old_applying_view = getattr(self, '_applying_view', False)
        self._applying_view = True
        rendered = None
        try:
            self._view_bridge.apply_controls_from_state(state, self, canvas)
            if update_primary_ui and state.cursor_mode == 'off':
                self.chart_stack.clear_cursor_pill()
            # Write incoming remark intent before the plot so the plot-channels
            # closeout (not a post-settle second pass) is the single projector.
            restore_remarks = getattr(canvas, "restore_remarks", None)
            if callable(restore_remarks):
                restore_remarks(state.remarks)
            rendered = self._plot_time_on_canvas(
                canvas,
                update_primary_ui=update_primary_ui,
                defer_first_frame=(state.xlim is not None),
            )
            # Restoring a View is ONE transaction (2026-08-15 view-switch
            # quality settlement spec §3.1): X, then Y, then ticks, and only
            # then a single settlement. _restore_view_xlim keeps that contract
            # on both its verbatim-restore and reframe-to-data branches (see
            # its docstring) — settle_view_restore() below is what flushes.
            self._restore_view_xlim(canvas, state.xlim)
            axis_opts = state.axis_opts or {}
            native_ticks = axis_opts.get("native_ticks") or {}
            native_y = native_ticks.get("y") if isinstance(native_ticks, dict) else None
            canvas.restore_visible_ylims(
                state.ylims,
                native_axis_ranges=native_y or None,
            )
            tick_opts = axis_opts.get('tick_density') or {}
            default_x, default_y = DEFAULT_CHART_TICK_DENSITY
            canvas.set_tick_density(
                int(tick_opts.get('x', default_x)),
                int(tick_opts.get('y', default_y)),
            )
            if native_ticks:
                from ..pg_canvas.native_axes import (
                    apply_native_ticks,
                    apply_native_y_ticks,
                    native_tick_levels,
                )
                x_spec = native_ticks.get("x") or {}
                if state.xlim is not None:
                    x_levels = native_tick_levels(
                        state.xlim[0], state.xlim[1],
                        x_spec.get("major"), x_spec.get("grid"),
                    )
                    if not x_levels.adaptive:
                        handles = []
                        getter = getattr(canvas, "_x_tick_axis_handles", None)
                        if callable(getter):
                            handles = list(getter())
                        else:
                            handles = list(getattr(canvas, "axes_list", []) or [])
                        for handle in handles:
                            axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
                            if axis is not None:
                                apply_native_ticks(axis, x_levels)
                apply_native_y_ticks(canvas, native_ticks.get("y") or {})
            canvas.settle_view_restore()
            restore_placement = getattr(canvas, "restore_cursor_placement", None)
            if callable(restore_placement):
                restore_placement(state.cursor_placement)
            if update_primary_ui:
                self._sync_record_curve_tree(state)
        finally:
            self._applying_view = old_applying_view
            # F8: secondary-pane restore must not project time controls while
            # an analysis section owns the shared navigator.
            if (
                restore_idx is not None
                and self.chart_stack.current_mode() == 'time'
            ):
                self._project_view_controls(restore_idx)
            if cursor_pill_snapshot is not None:
                self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)
        if coord is not None:
            from ..ultraview_state import UltraViewRef

            new_ref = UltraViewRef("time", state.view_id)
            coord.bind_canvas(canvas, new_ref)
            coord.request_capture(new_ref, canvas, "time-render")
        return rendered

    def _sync_record_curve_tree(self, state=None) -> None:
        """Project the focused Time View's record-only Y bindings onto ChannelTree.

        ChannelTree owns presentation. This entry is idempotent: Time Section
        off, no files, or no valid Time View always clears stale rows.
        """
        setter = getattr(getattr(self, "navigator", None), "set_record_curve_rows", None)
        if not callable(setter):
            return

        def _clear():
            setter(None, ())

        stack = getattr(self, "chart_stack", None)
        current_mode = getattr(stack, "current_mode", None)
        mode = current_mode() if callable(current_mode) else ""
        if mode != "time" or not getattr(self, "files", None):
            _clear()
            return
        if state is None:
            resolved = None
            getter = getattr(self, "_focused_time_view_state", None)
            if callable(getter):
                resolved = getter()
            if resolved is None:
                vm = getattr(self, "view_manager", None)
                idx = getattr(vm, "active", None) if vm is not None else None
                views = getattr(vm, "views", None) or ()
                if vm is None or idx is None or not (0 <= idx < len(views)):
                    _clear()
                    return
                state = vm.get(idx)
            else:
                state = resolved[1]
        if state is None:
            _clear()
            return
        view_id = str(getattr(state, "view_id", "") or "")
        if not view_id:
            _clear()
            return
        hidden = {
            str(item)
            for item in (getattr(state, "hidden_curve_binding_ids", None) or ())
        }
        rows = []
        for binding in getattr(state, "curve_bindings", None) or ():
            y_ref = getattr(binding, "y_ref", None)
            if getattr(y_ref, "kind", None) != "wwt_record":
                continue
            binding_id = str(getattr(binding, "binding_id", "") or "")
            owner_fid = str(getattr(y_ref, "fid", "") or "")
            record_index = getattr(y_ref, "record_index", None)
            if not binding_id or not owner_fid or record_index is None:
                continue
            rows.append({
                "binding_id": binding_id,
                "owner_fid": owner_fid,
                "record_index": int(record_index),
                "name": str(getattr(binding, "display_name", "") or binding_id),
                "unit": str(getattr(binding, "unit", "") or ""),
                "color": str(getattr(binding, "color", "") or "#64748b"),
                "visible": binding_id not in hidden,
            })
        if not rows:
            _clear()
            return
        setter(view_id, rows)

    def _on_record_curve_visibility_toggled(self, view_id, binding_id, visible):
        vm = getattr(self, "view_manager", None)
        if vm is None or not vm.views:
            return
        idx = vm.active
        if not (0 <= idx < len(vm.views)):
            return
        state = vm.get(idx)
        if str(getattr(state, "view_id", "") or "") != str(view_id or ""):
            return
        bid = str(binding_id or "")
        binding = None
        for item in getattr(state, "curve_bindings", None) or ():
            if str(getattr(item, "binding_id", "") or "") == bid:
                binding = item
                break
        y_ref = getattr(binding, "y_ref", None) if binding is not None else None
        if binding is None or getattr(y_ref, "kind", None) != "wwt_record":
            self._sync_record_curve_tree()
            return
        hidden = [
            str(item)
            for item in (getattr(state, "hidden_curve_binding_ids", None) or [])
        ]
        if visible:
            hidden = [item for item in hidden if item != bid]
        elif bid not in hidden:
            hidden.append(bid)
        state.hidden_curve_binding_ids = hidden
        canvas = self._canvas_for_view_index(idx) or getattr(self, "canvas_time", None)
        self._replot_canvas_for_view(idx, canvas, preserve_xlim=True)
        self._sync_record_curve_tree()

    # -- view tab-bar intent handlers (time section) --------------------
    def _on_view_new(self):
        self._capture_current_view()
        prefs = self.navigator.follow_prefs()
        inherit = (
            prefs.inherit_on_new_view
            and not getattr(self, "_opening_project", False)
            and not getattr(self, "_restoring_project", False)
        )
        template_fids = []
        template_name = ""
        if inherit:
            from .file_scope_follow import resolve_new_view_template

            resolved = self._focused_time_view_state()
            section_att = (
                list(resolved[1].attached_file_ids) if resolved is not None else []
            )
            template_name = resolved[1].name if resolved is not None else ""
            # Time section: same-section template is the focused time View;
            # the time fallback is identical.
            template_fids = resolve_new_view_template(
                section_att, section_att, self.files
            )
        defer_activation = view_activation.defer_new_view_activation_after_pointer_release()
        idx = self.view_manager.new_view(activate=not defer_activation)
        if idx < 0:
            return
        if defer_activation:
            view_id = self.view_manager.get(idx).view_id
            QTimer.singleShot(
                0,
                partial(
                    self._activate_new_time_view_after_pointer_release,
                    view_id,
                    tuple(template_fids),
                    template_name,
                ),
            )
            return
        if inherit and template_fids:
            added = self._attach_files_to_focused_view(template_fids)
            if added:
                self.toast(
                    f"已继承 {len(added)} 个文件 · 来自 {template_name}",
                    "success",
                )

    def _activate_new_time_view_after_pointer_release(
        self, view_id, template_fids, template_name,
    ):
        """Finish a frozen-Windows new-View action after the button release."""
        idx = next(
            (
                index
                for index, state in enumerate(self.view_manager.views)
                if state.view_id == view_id
            ),
            None,
        )
        if idx is None:
            return
        self.view_manager.set_active(idx)
        if template_fids:
            added = self._attach_files_to_focused_view(template_fids)
            if added:
                self.toast(
                    f"已继承 {len(added)} 个文件 · 来自 {template_name}",
                    "success",
                )

    def _on_view_delete(self, idx):
        # 删除 View 会一并丢弃它的通道范围、分屏配对与已加入文件，且无法撤销。
        # 删除是低频、破坏性操作，故每次都确认——不属于会被弹窗打扰的高频动作。
        if not (0 <= idx < len(self.view_manager.views)):
            return
        if len(self.view_manager.views) <= 1:
            return
        if not self._confirm_view_delete(self.view_manager.get(idx).name):
            return
        self._capture_current_view()
        self.view_manager.delete_view(idx)

    def _confirm_view_delete(self, name):
        box = QMessageBox(self)
        box.setWindowTitle("删除 View")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"删除 View「{name}」？")
        box.setInformativeText("该视图的通道范围、分屏与已加入文件将一并移除，且无法撤销。")
        delete = box.addButton("删除", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is delete

    def _on_view_duplicate(self, idx):
        self._capture_current_view()
        self.view_manager.duplicate(idx)

    def _on_view_color(self, idx):
        if not (0 <= idx < len(self.view_manager.views)):
            return
        from PyQt5.QtGui import QColor

        current = QColor(self.view_manager.get(idx).tab_color)
        color = QColorDialog.getColor(current, self, "选择标签颜色")
        if color.isValid():
            self.view_manager.set_color(idx, color.name())
            if idx == self._focused_view_idx:
                self._sync_focus_accent()

    # -- axis opts / range capture helpers --------------------------------

    def _restore_view_axis_opts(self, axis_opts):
        axis_opts = axis_opts or {}
        top = self.inspector.top

        # The range widgets are shared with analysis sections.  Restoring a
        # Time View while FRF/FFT is on screen must not overwrite the
        # analysis section's explicit range with Time View filter state.
        if self.chart_stack.current_mode() == 'time':
            range_opts = axis_opts.get('range_filter') or {}
            range_enabled = bool(range_opts.get('enabled', False))
            range_start = range_opts.get('start', top.spin_start.value())
            range_end = range_opts.get('end', top.spin_end.value())
            old_chk = top.chk_range.blockSignals(True)
            try:
                top.chk_range.setChecked(range_enabled)
            finally:
                top.chk_range.blockSignals(old_chk)
            top.set_range_values(range_start, range_end)
            update_range_rows = getattr(top, '_update_range_rows_visible', None)
            if callable(update_range_rows):
                update_range_rows()

        spec = CustomXAxisSpec.from_axis_opts(axis_opts.get('x_axis'))
        requested_mode = spec.mode
        label = spec.label
        target_fid = spec.source_fid
        target_channel = spec.channel

        use_channel = requested_mode == CHANNEL_MODE
        if use_channel:
            # Candidate construction must see the restored applied spec so it
            # can retain a logical 0/N item or re-inject a legacy exact-source
            # item while the source still exists.
            self._custom_xaxis.adopt(spec)
            self._refresh_xaxis_candidates()
            combo = top._combo_xaxis_ch
            target_payload = selection_payload(spec)
            match_idx = -1
            for i in range(combo.count()):
                if combo.itemData(i) == target_payload:
                    match_idx = i
                    break
            use_channel = match_idx >= 0

        old_mode = top.combo_xaxis.blockSignals(True)
        old_combo = top._combo_xaxis_ch.blockSignals(True)
        old_label = top.edit_xlabel.blockSignals(True)
        _le = top._combo_xaxis_ch.lineEdit()
        _old_le = _le.blockSignals(True) if _le is not None else False
        try:
            if use_channel:
                self._custom_xaxis.adopt(
                    spec, xlabel=label or target_channel,
                )
                top.set_xaxis_mode('channel')
                top._combo_xaxis_ch.setEnabled(True)
                top._combo_xaxis_ch.setCurrentIndex(match_idx)
                top.edit_xlabel.setText(label or '')
            else:
                self._custom_xaxis.adopt(
                    CustomXAxisSpec(label=label), xlabel=label or None,
                )
                top.set_xaxis_mode('time')
                top._combo_xaxis_ch.setEnabled(False)
                _safe_label = label if (label and label != 'Time (s)') else ''
                top.edit_xlabel.setText(_safe_label if requested_mode == 'time' else '')
        finally:
            top.edit_xlabel.blockSignals(old_label)
            top._combo_xaxis_ch.blockSignals(old_combo)
            top.combo_xaxis.blockSignals(old_mode)
            if _le is not None:
                _le.blockSignals(_old_le)
        update_xaxis_row = getattr(top, '_update_xaxis_channel_row_visible', None)
        if callable(update_xaxis_row):
            update_xaxis_row(top.combo_xaxis.currentIndex())

        tick_opts = axis_opts.get('tick_density') or {}
        default_x, default_y = DEFAULT_CHART_TICK_DENSITY
        xt = tick_opts.get('x', default_x)
        yt = tick_opts.get('y', default_y)
        self._set_tick_density_controls_silent(xt, yt)

    def _applied_xaxis_opts(self):
        spec = getattr(self, '_custom_xaxis_spec', None)
        if not isinstance(spec, CustomXAxisSpec):
            fid = getattr(self, '_custom_xaxis_fid', None)
            channel = getattr(self, '_custom_xaxis_ch', None)
            if fid is not None and channel is not None:
                spec = CustomXAxisSpec(
                    mode=CHANNEL_MODE,
                    resolver=EXACT_SOURCE,
                    source_fid=str(fid),
                    channel=str(channel),
                )
            else:
                spec = CustomXAxisSpec()
        label = getattr(self, '_custom_xlabel', None)
        if label is None:
            label = spec.label
        if not label and spec.channel:
            label = spec.channel
        return replace(spec, label=str(label or '')).to_axis_opts()

    def _capture_range_change_into_view(self, state, canvas):
        prev_axis_opts = state.axis_opts or {}
        prev_x_axis = prev_axis_opts.get('x_axis') or self._applied_xaxis_opts()
        self._view_bridge.capture_controls_into(state, self, canvas)
        axis_opts = dict(state.axis_opts or {})
        axis_opts['x_axis'] = prev_x_axis
        state.axis_opts = axis_opts

    def _replot_secondary_preserving_xlim(self):
        """Replot the secondary (compare) canvas after its own plot-mode flip
        (P2 Task 9 1b), preserving that pane's visible X window.

        The secondary holds a compare-view snapshot; its 分屏/叠加 control only
        changes the LAYOUT of that pane, so we redraw the secondary canvas
        in-place (with ``update_primary_ui=False`` so the primary stats strip /
        bookkeeping stay untouched) and re-apply the secondary's X window. No
        secondary canvas (split inactive) → no-op. X preservation follows the
        TimeDomain state-preservation lesson: keep the visible window when the
        new layout's extent still overlaps it."""
        canvas = self.chart_stack.secondary_canvas()
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            state = self.view_manager.get(idx)
            self._view_bridge.capture_controls_into(state, self, canvas)
        self._replot_canvas_for_view(idx, canvas)

    def _replot_canvas_for_view(self, idx, canvas, *, preserve_xlim=True):
        if idx is None or canvas is None:
            return
        cur_xlim = self._safe_capture_xlim_for(canvas) if preserve_xlim else None
        rendered = None
        try:
            rendered = self._render_view_to_canvas(
                idx,
                canvas,
                update_primary_ui=(canvas is self.canvas_time),
            )
        finally:
            if cur_xlim is not None:
                self._safe_restore_xlim_for(canvas, cur_xlim)
            self._capture_canvas_ranges_for_bound_view(canvas)
        return rendered
