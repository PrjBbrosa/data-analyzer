"""AnalysisMixin: per-section analysis view routing + cross-cutting helpers.

This mixin owns the V7 per-section view pipeline (capture → switch → apply →
render) for the FFT / Order / FFT-vs-Time analysis sections, plus the
cross-cutting helpers (``_pane_time_range_for``, ``_mask_time_range``,
``_analysis_page``, ``_analysis_cache_key``, ``_analysis_channel_color_map``,
``_capture_active_analysis_view``) that FFTMixin / OrderMixin / FFTTimeMixin
call through ``self.``.  Method-resolution order makes those calls find this
copy regardless of base-class order — there are no name collisions.
"""

import numpy as np

from PyQt5.QtWidgets import QColorDialog
from PyQt5.QtCore import QTimer

from ..compute_feedback import summarize_compute


class AnalysisMixin:
    def _analysis_ctx(self, section):
        return {
            'fft': self.inspector.fft_ctx,
            'fft_time': self.inspector.fft_time_ctx,
            'order': self.inspector.order_ctx,
        }[section]

    def _analysis_page(self, section):
        return {
            'fft': self.chart_stack.page_fft,
            'fft_time': self.chart_stack.page_fft_time,
            'order': self.chart_stack.page_order,
        }[section]

    def _emit_compute_feedback(self, outcome, *, busy=False, section_label="计算"):
        res = summarize_compute(
            outcome,
            busy=busy,
            section_label=section_label,
        )
        if res is None:
            return False
        level, msg = res
        self.toast(msg, level)
        self.statusBar.showMessage(msg)
        return True

    # -- tab-bar intent handlers (capture outgoing view first) ----------
    def _on_analysis_switch(self, section, idx):
        mgr = self.analysis_managers[section]
        if idx == mgr.active:
            return
        self._capture_active_analysis_view(section)
        mgr.set_active(idx)

    def _on_analysis_new(self, section):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].new_view()

    def _on_analysis_delete(self, section, idx):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].delete_view(idx)

    def _on_analysis_duplicate(self, section, idx):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].duplicate(idx)

    def _on_analysis_color(self, section, idx):
        mgr = self.analysis_managers[section]
        if not (0 <= idx < len(mgr.views)):
            return
        from PyQt5.QtGui import QColor
        current = QColor(mgr.get(idx).tab_color)
        color = QColorDialog.getColor(current, self, "选择标签颜色")
        if color.isValid():
            mgr.set_color(idx, color.name())

    def _on_analysis_split(self, section, on):
        """split_requested / clear_split_requested → add / remove pane 2 of the
        ACTIVE view of this section."""
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        page = self._analysis_page(section)
        if on:
            if state.add_pane():
                page.enter_split()
                self._connect_new_pane(section, page)
        else:
            state.remove_second_pane()
            page.exit_split()

    def _connect_new_pane(self, section, page):
        """Wire copy/annotation relays for a freshly split pane card so the
        compare pane behaves like pane 0."""
        if page.pane_count() < 2:
            return
        self.chart_stack._connect_analysis_card_signals(page._cards[1])
        if section == 'fft':
            self._connect_fft_preview_range_signal(page.pane_canvas(1), 1)
        # V8: pane 1's colorbar-drag → inspector Z echo (heatmap sections).
        # Guarded against double-wiring across repeated splits via a marker on
        # the canvas (enter_split builds a fresh card each time, so a stale
        # connection on a destroyed canvas is never reused — but a duplicate
        # connect on the same long-lived canvas would double-fire).
        if section != 'fft':
            canvas = page.pane_canvas(1)
            if not getattr(canvas, '_levels_echo_wired', False):
                canvas.levels_changed.connect(
                    lambda lo, hi: self._on_analysis_levels_dragged(
                        section, 1, lo, hi))
                canvas._levels_echo_wired = True

    def _connect_fft_preview_range_signal(self, canvas, pane_idx):
        signal = getattr(canvas, 'time_preview_range_changed', None)
        if signal is None or getattr(canvas, '_fft_preview_range_wired', False):
            return
        signal.connect(
            lambda lo, hi, idx=pane_idx: self._on_fft_preview_range_changed(
                idx, lo, hi))
        canvas._fft_preview_range_wired = True

    # -- view-switch pipeline (capture → switch → apply → render) -------
    def _capture_active_analysis_view(self, section, *, capture_sources=True):
        from ..analysis_view_bridge import capture_params_to_state
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        capture_params_to_state(self._analysis_ctx(section), state)
        self._capture_analysis_time_range(section, state)
        if capture_sources:
            self._capture_analysis_sources(section, state)

    def _on_analysis_view_switched(self, section, idx):
        """manager.active_changed → apply the new view's structure, params and
        sources, then render whatever the cache already holds (never compute)."""
        from ..analysis_view_bridge import apply_params_from_state
        mgr = self.analysis_managers[section]
        if not (0 <= idx < len(mgr.views)):
            return
        state = mgr.get(idx)
        page = self._analysis_page(section)
        self._applying_analysis_view = True
        try:
            # 1. Align the pane structure to the view (1 or 2 panes).
            if len(state.panes) == 2 and page.pane_count() == 1:
                page.enter_split()
                self._connect_new_pane(section, page)
            elif len(state.panes) == 1 and page.pane_count() == 2:
                page.exit_split()
            # 2. Compare options (state is the source of truth; enter_split
            #    above may have emitted a non-edge link_toggled — we ignore
            #    that signal entirely and drive set_linked from state here).
            #    V8 closes the loop: set_levels_locked is now also state-driven,
            #    and the toggle buttons are re-seeded from state.compare (under
            #    _applying_analysis_view, so the resulting button edges do not
            #    write back onto the state we just read).
            x_linked = bool(state.compare.get('x_linked', True))
            levels_locked = bool(state.compare.get('levels_locked', True))
            page.set_linked(x_linked)
            page.set_levels_locked(levels_locked)
            page.sync_compare_buttons(
                x_linked=x_linked, levels_locked=levels_locked)
            # 3. Params + focused-pane source echo.
            apply_params_from_state(self._analysis_ctx(section), state)
            self._apply_analysis_sources(section, state)
            self._apply_analysis_time_range(section, state)
        finally:
            self._applying_analysis_view = False
        # 4. Render from cache only (spec §4: switching never auto-computes).
        self._render_analysis_view_from_cache(section, state)

    def _on_analysis_focus_changed(self, section, idx):
        """A pane click changed the focused pane: capture the source selection
        into the PREVIOUS focused pane, then echo the now-focused pane's
        source back into the inspector / navigator."""
        if self._applying_analysis_view:
            return
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        page = self._analysis_page(section)
        old_idx = min(page.previous_focused_index(), len(state.panes) - 1)
        self._capture_analysis_sources(section, state, pane_idx=old_idx)
        self._capture_analysis_time_range(section, state, pane_idx=old_idx)
        self._apply_analysis_sources(section, state)
        self._apply_analysis_time_range(section, state)

    def _on_analysis_compare_toggled(self, section, key, on):
        """A page compare toggle (联动缩放 / 锁定色阶) flipped → persist it onto
        the active view's ``state.compare`` so a later view switch reads it
        back (V8 write-back loop: toggle → state → _on_analysis_view_switched
        reads state to drive set_linked / set_levels_locked)."""
        if self._applying_analysis_view:
            return
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        state.compare[key] = bool(on)

    def _on_analysis_levels_dragged(self, section, pane_idx, lo, hi):
        """User dragged a heatmap colorbar → echo (lo, hi) into the inspector
        Z controls (manual range). Only the FOCUSED pane's drag drives the
        inspector, since the inspector mirrors the focused pane. fft (line
        section) has no colorbar so it never reaches here.

        The two-pane *canvas* sync under a level lock is handled entirely
        inside the page (_on_locked_levels_changed); this path is strictly
        canvas → inspector, so the two never fight: the page mutates the
        sibling canvas's levels, MainWindow mutates the inspector spinboxes.
        apply_params here is an existing inspector API called with corrected
        args — no algorithm/loader is touched."""
        if self._applying_analysis_view:
            return
        page = self._analysis_page(section)
        if pane_idx != page.focused_index():
            return
        ctx = self._analysis_ctx(section)
        ctx.apply_params({
            'z_auto': False,
            'z_floor': float(lo),
            'z_ceiling': float(hi),
        })

    # -- source routing (Step 4) ----------------------------------------
    @staticmethod
    def _normalize_analysis_time_range(value):
        if not value:
            return None
        try:
            lo = float(value[0])
            hi = float(value[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (lo, hi)

    def _mask_time_range(self, t, *arrays, time_range=None):
        rng = self._normalize_analysis_time_range(time_range)
        if rng is None or t is None:
            return (t, *arrays)
        lo, hi = rng
        mask = (t >= lo) & (t <= hi)
        masked = [arr[mask] for arr in arrays]
        return (t[mask], *masked)

    @staticmethod
    def _analysis_section_uses_time_range(section):
        return section in {"fft", "fft_time", "order"}

    def _capture_analysis_time_range(self, section, state, pane_idx=None):
        if not self._analysis_section_uses_time_range(section):
            return
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        if self.inspector.top.range_enabled():
            pane.time_range = self._normalize_analysis_time_range(
                self.inspector.top.range_values()
            )
        else:
            pane.time_range = None

    def _set_top_range_enabled_silently(self, enabled):
        top = self.inspector.top
        old = top.chk_range.blockSignals(True)
        try:
            top.chk_range.setChecked(bool(enabled))
        finally:
            top.chk_range.blockSignals(old)
        top._range_checked_by_mode[top._range_mode] = bool(enabled)
        update = getattr(top, "_update_range_rows_visible", None)
        if callable(update):
            update()

    def _apply_analysis_time_range(self, section, state):
        if not self._analysis_section_uses_time_range(section):
            return
        page = self._analysis_page(section)
        idx = min(page.focused_index(), len(state.panes) - 1)
        rng = self._normalize_analysis_time_range(state.panes[idx].time_range)
        top = self.inspector.top
        if rng is None:
            self._set_top_range_enabled_silently(False)
            return
        top.set_range_from_span(*rng)

    def _pane_time_range_for(self, section, pane_idx=None):
        if not self._analysis_section_uses_time_range(section):
            return None
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        if pane_idx is None:
            page = self._analysis_page(section)
            pane_idx = page.focused_index()
        if not (0 <= int(pane_idx) < len(state.panes)):
            return None
        return self._normalize_analysis_time_range(
            state.panes[int(pane_idx)].time_range
        )

    def _capture_analysis_sources(self, section, state, pane_idx=None):
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'fft':
            checked = self.navigator.get_checked_channels()
            pane.sources = [(fid, ch) for fid, ch, _color in checked]
            self._sync_fft_source_summary(checked)
        else:
            ctx = self._analysis_ctx(section)
            sig = ctx.current_signal()
            pane.sources = [tuple(sig)] if sig else []
            if section == 'order':
                rpm = ctx.current_rpm()
                pane.rpm_source = tuple(rpm) if rpm else None

    def _analysis_channel_color_map(self):
        colors = {}
        getter = getattr(self.navigator, 'get_channel_colors', None)
        if callable(getter):
            for key, color in getter().items():
                try:
                    fid, ch = key[:2]
                except (TypeError, ValueError):
                    continue
                colors[(fid, ch)] = color
        for row in self.navigator.get_checked_channels():
            try:
                fid, ch, color = row[:3]
            except (TypeError, ValueError):
                continue
            colors[(fid, ch)] = color
        return colors

    def _apply_analysis_sources(self, section, state):
        page = self._analysis_page(section)
        idx = min(page.focused_index(), len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'fft':
            self.navigator.set_checked_channels(list(pane.sources))
            self._sync_fft_source_summary()
        else:
            ctx = self._analysis_ctx(section)
            if pane.sources:
                self._echo_combo_signal(ctx.combo_sig, pane.sources[0])
            if section == 'order' and pane.rpm_source is not None:
                self._echo_combo_signal(ctx.combo_rpm, pane.rpm_source)

    @staticmethod
    def _echo_combo_signal(combo, key):
        """Select ``key`` (a (fid, ch) tuple) in a SearchableComboBox by its
        userData, tolerating list/tuple shape drift."""
        if key is None:
            return
        target = tuple(key)
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is not None and tuple(data) == target:
                combo.setCurrentIndex(i)
                return

    # -- cache-backed render on switch (Step 3) -------------------------
    def _analysis_compute_params(self, section):
        """Compute-relevant params (cache-key inputs) for the active inspector
        state of ``section``. Display-only knobs are excluded so toggling them
        does not invalidate the cache."""
        ctx = self._analysis_ctx(section)
        p = ctx.get_params()
        if section == 'fft':
            # Compute inputs for FFT spectra are window / nfft / averaging mode
            # + averaging overlap (see _fft_compute_arrays). The plain
            # ``overlap`` knob feeds only batch presets, NOT the spectrum
            # compute, so it is excluded from the key (and its get/apply
            # fraction-vs-percent asymmetry would make the key unstable).
            cp = ctx.current_params()
            return {
                'window': p.get('window'),
                'nfft': p.get('nfft'),
                'nfft_mode': p.get('nfft_mode'),
                't_win_s': p.get('t_win_s', 1.5),
                'avg_mode': cp.get('avg_mode', '单帧'),
                'avg_overlap': cp.get('avg_overlap', 50),
            }
        if section == 'fft_time':
            return {
                'fs': p.get('fs'),
                'nfft': p.get('nfft'),
                'window': p.get('window'),
                'overlap': p.get('overlap'),
                'remove_mean': p.get('remove_mean'),
                'db_reference': p.get('db_reference', 1.0),
            }
        # order: COT params + rpm_source must both be in the key (changing the
        # RPM channel must NOT hit an old result).
        return {
            'nfft': p.get('nfft'),
            'nfft_mode': p.get('nfft_mode'),
            'nfft_preview': p.get('nfft_preview'),
            'nfft_effective': p.get('nfft_effective'),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': ctx.current_params().get('samples_per_rev'),
            'rpm_factor': p.get('rpm_factor'),
            'fs': p.get('fs'),
        }

    def _analysis_cache_key(self, section, fid, ch, rpm_source=None, pane_idx=None):
        cache = self.analysis_caches[section]
        if section == 'fft_time':
            p = self.inspector.fft_time_ctx.get_params()
            time_range = self._pane_time_range_for(section, pane_idx)
            prepared = self._fft_time_effective_params_for_source(
                p, fid, ch, time_range)
            if prepared is not None:
                effective_p, _effective_time_range = prepared
                return self._fft_time_analysis_cache_key(
                    fid, ch, effective_p, pane_idx)
            params = {
                'fs': p.get('fs'),
                'nfft': int(
                    p.get('nfft_effective')
                    or p.get('nfft')
                    or p.get('nfft_preview')
                ),
                'window': p.get('window'),
                'overlap': p.get('overlap'),
                'remove_mean': p.get('remove_mean'),
                'db_reference': p.get('db_reference', 1.0),
                'time_range': time_range,
            }
            return cache.make_key(fid, ch, params)
        if section == 'fft':
            time_range = self._pane_time_range_for(section, pane_idx)
            params = self._fft_effective_params_for_source(
                self._analysis_compute_params(section),
                fid,
                ch,
                time_range,
            )
            return self._fft_analysis_cache_key(fid, ch, params, time_range)
        if section == 'order':
            time_range = self._pane_time_range_for(section, pane_idx)
            params = self._analysis_compute_params(section)
            effective = self._order_effective_params_for_source(
                params,
                fid,
                ch,
                rpm_source,
                time_range,
            )
            if effective is not None:
                params = effective
            return self._order_analysis_cache_key(
                fid,
                ch,
                params,
                rpm_source,
                time_range,
            )
        params = dict(self._analysis_compute_params(section))
        if section in {'fft', 'fft_time', 'order'}:
            params['time_range'] = self._pane_time_range_for(section, pane_idx)
        return cache.make_key(fid, ch, params)

    def _recompute_analysis_section(self, section):
        """Dispatch the active view's compute for ``section`` (used by the
        post-load auto-recompute path). Reuses the same entry points as the
        计算 buttons, so caching / rendering / split-pane handling are shared.

        Runs deferred (QTimer.singleShot) from the restore path; guard the whole
        dispatch so a compute failure can never bubble out of the event-loop
        callback and tear down the freshly opened project."""
        try:
            if section == 'fft':
                self.do_fft()
            elif section == 'order':
                self.do_order_time()
            elif section == 'fft_time':
                self.do_fft_time()
        except Exception:
            pass

    def _render_analysis_view_from_cache(self, section, state):
        """Render each pane from cached results; panes whose sources are not all
        cached show an empty state and a 'click 计算' status hint.

        Normally never computes (spec §4). The one exception is the post-load
        auto-recompute: when this (section, view) was queued by open_project
        and still has sources, recompute it once so the saved params + sources
        repopulate the chart, then fall back to the normal cache-render path on
        every subsequent call."""
        mgr = self.analysis_managers.get(section)
        if mgr is not None:
            restore_key = (section, mgr.active)
            if restore_key in self._analysis_restore_pending:
                self._analysis_restore_pending.discard(restore_key)
                if any(p.sources for p in state.panes):
                    # Defer the recompute to the next event-loop turn instead of
                    # running it inline. open_project drives this for all three
                    # sections mid-restore; a synchronous compute could pop a
                    # blocking QMessageBox (FFT/order compute error) that would
                    # interrupt the half-finished open. Deferring lets the window
                    # finish opening first, so any error surfaces cleanly after.
                    QTimer.singleShot(
                        0, lambda s=section: self._recompute_analysis_section(s))
                    return
        page = self._analysis_page(section)
        any_missing = False
        for pane_idx in range(page.pane_count()):
            if pane_idx >= len(state.panes):
                break
            pane = state.panes[pane_idx]
            canvas = page.pane_canvas(pane_idx)
            cache = self.analysis_caches[section]
            if section == 'fft':
                entries = []
                colors = self._analysis_channel_color_map()
                time_range = self._pane_time_range_for(section, pane_idx)
                for fid, ch in pane.sources:
                    key = self._analysis_cache_key(
                        section, fid, ch, pane_idx=pane_idx)
                    result = cache.get(key)
                    if result is None:
                        any_missing = True
                        continue
                    entries.append(self._fft_entry_from_cache(
                        result, fid, ch, colors.get((fid, ch)),
                        time_range=time_range))
                if entries:
                    self._plot_fft_entries(entries, canvas)
                else:
                    # No cached curves (empty sources, or all sources missing
                    # from the cache) -> empty canvas state.
                    self._clear_analysis_canvas(canvas)
            else:
                if not pane.sources:
                    self._clear_analysis_canvas(canvas)
                    continue
                fid, ch = pane.sources[0]
                key = self._analysis_cache_key(
                    section, fid, ch,
                    rpm_source=pane.rpm_source if section == 'order' else None,
                    pane_idx=pane_idx)
                result = cache.get(key)
                if result is None:
                    any_missing = True
                    self._clear_analysis_canvas(canvas)
                else:
                    self._render_cached_heatmap(section, canvas, result)
        if any_missing:
            self.statusBar.showMessage("参数/源已就绪，点击计算")

    def _clear_analysis_canvas(self, canvas):
        if hasattr(canvas, 'full_reset'):
            try:
                canvas.full_reset()
            except Exception:
                pass
