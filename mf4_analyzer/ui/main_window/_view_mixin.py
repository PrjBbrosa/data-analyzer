"""ViewMixin: time-domain split-view switch / capture / render pipeline."""

from dataclasses import replace

from PyQt5.QtWidgets import QColorDialog, QMessageBox

from ..time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    CustomXAxisSpec,
    selection_payload,
)


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
        active = self.view_manager.active
        partner = self.view_manager.split_with
        self._primary_view_idx = active
        self._secondary_view_idx = partner
        if partner is None:
            self._focused_view_idx = active
        elif self._focused_view_idx not in (active, partner):
            self._focused_view_idx = active

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
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        state = self.view_manager.get(idx)
        self._view_bridge.capture_controls_into(state, self, canvas)
        self._view_bridge.capture_canvas_ranges_into(state, canvas)

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
        for i in range(6):
            sc = QShortcut(QKeySequence(f"Alt+{i + 1}"), self)
            sc.setContext(Qt.ApplicationShortcut)
            idx = i
            sc.activated.connect(
                lambda bound=idx: self._switch_view_for_active_section(bound))
            self._view_shortcuts.append(sc)

    def _switch_view_for_active_section(self, idx):
        """Alt+i: switch the view of whatever section is currently shown.

        The time section keeps the cross-view pairing path (``_switch_view``);
        analysis sections (fft/fft_time/order) route to their own manager via
        ``_on_analysis_switch``. Both already guard idx range + no-op on no
        change, so out-of-range Alt keys are safe.
        """
        mode = self.chart_stack.current_mode()
        if mode in ('fft', 'fft_time', 'order'):
            self._on_analysis_switch(mode, idx)
        else:
            self._switch_view(idx)

    def _switch_view(self, idx):
        if idx == self.view_manager.active:
            return
        if not (0 <= idx < len(self.view_manager.views)):
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
        self._focused_view_idx = idx
        self._sync_focus_accent()
        if self.files and self.chart_stack.current_mode() == 'time':
            self._render_view_to_canvas(idx, self.canvas_time, update_primary_ui=True)
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
            self._secondary_view_idx = None
            self._focused_view_idx = self.view_manager.active
            self._sync_focus_accent()
            if self.files and self.chart_stack.current_mode() == 'time':
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
        self._focused_view_idx = self.view_manager.active
        self._sync_focus_accent()
        if self.files and self.chart_stack.current_mode() == 'time':
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

    def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
        if canvas is None:
            return
        if not (0 <= idx < len(self.view_manager.views)):
            return
        state = self.view_manager.get(idx)

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
        try:
            self._view_bridge.apply_controls_from_state(state, self, canvas)
            if update_primary_ui and state.cursor_mode == 'off':
                self.chart_stack.clear_cursor_pill()
            rendered = self._plot_time_on_canvas(
                canvas,
                update_primary_ui=update_primary_ui,
                defer_first_frame=(state.xlim is not None),
            )
            canvas.restore_visible_xlim(state.xlim)
            canvas.restore_visible_ylims(state.ylims)
            tick_opts = (state.axis_opts or {}).get('tick_density') or {}
            canvas.set_tick_density(
                int(tick_opts.get('x', 10)),
                int(tick_opts.get('y', 6)),
            )
        finally:
            self._applying_view = old_applying_view
            if restore_idx is not None:
                self._project_view_controls(restore_idx)
            if cursor_pill_snapshot is not None:
                self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)
        return rendered

    # -- view tab-bar intent handlers (time section) --------------------
    def _on_view_new(self):
        self._capture_current_view()
        self.view_manager.new_view()

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
            self._custom_xaxis_spec = spec
            self._custom_xaxis_fid = (
                target_fid if spec.resolver == EXACT_SOURCE else None
            )
            self._custom_xaxis_ch = (
                target_channel if spec.resolver == EXACT_SOURCE else None
            )
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
                self._custom_xaxis_spec = spec
                self._custom_xaxis_fid = (
                    target_fid if spec.resolver == EXACT_SOURCE else None
                )
                self._custom_xaxis_ch = (
                    target_channel if spec.resolver == EXACT_SOURCE else None
                )
                self._custom_xlabel = label or target_channel
                top.set_xaxis_mode('channel')
                top._combo_xaxis_ch.setEnabled(True)
                top._combo_xaxis_ch.setCurrentIndex(match_idx)
                top.edit_xlabel.setText(label or '')
            else:
                self._custom_xaxis_spec = CustomXAxisSpec(label=label)
                self._custom_xaxis_fid = None
                self._custom_xaxis_ch = None
                self._custom_xlabel = label or None
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
        xt = tick_opts.get('x', 10)
        yt = tick_opts.get('y', 6)
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
