"""AnalysisMixin: per-section analysis view routing + cross-cutting helpers.

This mixin owns the V7 per-section view pipeline (capture → switch → apply →
render) for the FFT / Order / FFT-vs-Time analysis sections, plus the
cross-cutting helpers (``_pane_time_range_for``, ``_mask_time_range``,
``_analysis_page``, ``_analysis_cache_key``, ``_analysis_channel_color_map``,
``_capture_active_analysis_view``) that FFTMixin / OrderMixin / FFTTimeMixin
call through ``self.``.  Method-resolution order makes those calls find this
copy regardless of base-class order — there are no name collisions.
"""

import math

import numpy as np

from PyQt5.QtWidgets import QColorDialog
from PyQt5.QtCore import QTimer

from ... import db_reference
from ..compute_feedback import summarize_compute
from .analysis_context import AnalysisContext


# dB-reference-defaults Task 5 (spec §8.2 source tokens). Presentation-only
# mapping for the compound control's source line -- kept local to this UI
# wiring layer rather than in the pure ``db_reference`` module (which owns
# resolution/validation, not Chinese UI copy).
_DB_REFERENCE_SOURCE_LABELS = {
    'manual': '手动覆盖',
    'metadata': '通道 metadata',
    'user': '用户默认',
    'system': '系统默认',
    'generic': '通用默认',
    'fallback': '解析失败回退',
}


def _format_db_reference_source_line(resolution):
    """Spec §10.3 source-line text: ``自动 · <来源> · <quantity>/<unit>``.

    ``generic``/``fallback`` show ``dB re 1 <unit>`` instead of quantity/unit
    (generic is the neutral EPS-unit common case; fallback carries the
    resolver's own warning in the tooltip)."""
    token = _DB_REFERENCE_SOURCE_LABELS.get(resolution.source, resolution.source)
    if resolution.source in ('generic', 'fallback'):
        unit = resolution.unit or ''
        detail = f"dB re 1 {unit}" if unit else "dB re 1"
    else:
        detail = f"{resolution.quantity} / {resolution.unit}".strip(' /')
    text = f"自动 · {token} · {detail}" if detail else f"自动 · {token}"
    tooltip = text
    if resolution.warning:
        tooltip = f"{text}\n{resolution.warning}"
    return text, tooltip


class AnalysisMixin:
    #: Re-entrancy guard: while a view switch is applying state to the UI,
    #: suppress the inspector signal handlers that would otherwise capture the
    #: half-applied controls back into the outgoing view. Owned entirely by
    #: this mixin, so the default lives here rather than in window.__init__
    #: (spec D-E2) -- that keeps the guard to exactly one writing file.
    _applying_analysis_view = False

    # -- helpers delegated to AnalysisContext (spec D-E1) ------------------
    # These bodies moved verbatim onto ``analysis_context.AnalysisContext``,
    # which takes its collaborators as named constructor arguments and is
    # therefore unit-testable without a MainWindow.  The method names stay
    # here so the MRO and all three calling mixins are untouched.

    def _analysis_ctx(self, section):
        return self._analysis_context.section_ctx(section)

    def _analysis_page(self, section):
        return self._analysis_context.page(section)

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
        mgr = self.analysis_managers[section]
        if len(mgr.views) > 1 and 0 <= idx < len(mgr.views):
            state = mgr.get(idx)
            self._analysis_restore_pending.discard((section, state.view_id))
            if section == 'frf':
                for pane_idx in range(len(state.panes)):
                    self._frf_coordinator.invalidate_pane(
                        state.view_id, pane_idx
                    )
        mgr.delete_view(idx)

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
            if section == 'frf' and len(state.panes) > 1:
                self._frf_coordinator.invalidate_pane(state.view_id, 1)
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
        if section in {'fft_time', 'order'}:
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
        if section == 'frf':
            self._capture_frf_canvas_ranges(state)
        # The shared range widgets only represent the visible section.  Saving
        # a project flushes every analysis section, so reading them for an
        # inactive section would overwrite that section's retained range with
        # whichever mode happens to be on screen.
        if self.chart_stack.current_mode() == section:
            self._capture_analysis_time_range(section, state)
        if section in {'fft', 'frf'}:
            self._capture_frequency_cursor_controls(section, state)
        if capture_sources:
            self._capture_analysis_sources(section, state)

    def _on_analysis_view_switched(self, section, idx, *, render=True,
                                   apply_params=True):
        """manager.active_changed → apply the new view's structure, params and
        sources, then render whatever the cache already holds (never compute).

        ``render`` / ``apply_params`` let FFT *mode entry* project Stage 1
        attachments + sources while leaving the signature-aware canvas restore
        to ``_enter_fft_mode`` (which must see live inspector drift such as a
        cross-section weighting default).
        """
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
            # 3. Project this View's attachments + section-local candidates
            #    before echoing sources into live controls.
            if self.chart_stack.current_mode() == section:
                self._project_analysis_attachments(section, state)
            self._refresh_analysis_candidates(section)
            # 4. Params + focused-pane source echo.
            if apply_params:
                apply_params_from_state(self._analysis_ctx(section), state)
            if section in {'fft', 'frf'}:
                self._apply_frequency_cursor_controls(section, state)
            self._apply_analysis_sources(section, state)
            self._apply_analysis_time_range(section, state)
        finally:
            self._applying_analysis_view = False
        # 5. Render from cache only (spec §4: switching never auto-computes).
        if render:
            self._render_analysis_view_from_cache(section, state)

    def _project_analysis_attachments(self, section, state):
        """Project one analysis View's file range onto the shared navigator."""
        attached = [
            fid for fid in state.attached_file_ids if fid in self.files
        ]
        setter = getattr(self.navigator, 'set_attached_file_ids', None)
        if callable(setter):
            setter(attached)
        label = self._analysis_section_label(section)
        empty = getattr(self.navigator, 'set_empty_state_context', None)
        if callable(empty):
            empty(section_label=label, view_name=state.name)
        if section != 'fft':
            # Candidate roles do not own checkbox selection.
            self.navigator.set_checked_channels([])

    def _apply_active_analysis_context(self, section, *, render=True,
                                       apply_params=True):
        """Full-apply the active View of ``section`` after a mode switch."""
        mgr = self.analysis_managers[section]
        if not mgr.views:
            return
        # Reuse the view-switch pipeline against the already-active index so
        # mode entry and View switch stay byte-equivalent for the target.
        self._on_analysis_view_switched(
            section, mgr.active, render=render, apply_params=apply_params
        )

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
        if section in {'fft', 'frf'}:
            self._apply_frequency_cursor_controls(section, state)

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
        return AnalysisContext.normalize_time_range(value)

    def _mask_time_range(self, t, *arrays, time_range=None):
        return self._analysis_context.mask_time_range(
            t, *arrays, time_range=time_range
        )

    @staticmethod
    def _analysis_section_uses_time_range(section):
        return AnalysisContext.section_uses_time_range(section)

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

    def _set_top_range_enabled_silently(self, enabled, *, mode=None):
        top = self.inspector.top
        target_mode = mode or top._range_mode
        top._range_checked_by_mode[target_mode] = bool(enabled)
        # Project restore can apply an analysis view before the toolbar has
        # switched the Inspector into that mode.  Remember that mode's intent
        # without clobbering the visible Time-mode checkbox; checkout later
        # restores the right state as the shared group is reparented.
        if target_mode != top._range_mode:
            return
        old = top.chk_range.blockSignals(True)
        try:
            top.chk_range.setChecked(bool(enabled))
        finally:
            top.chk_range.blockSignals(old)
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
            self._set_top_range_enabled_silently(False, mode=section)
            return
        top.set_range_values(*rng)
        self._set_top_range_enabled_silently(True, mode=section)

    def _pane_time_range_for(self, section, pane_idx=None):
        return self._analysis_context.pane_time_range_for(section, pane_idx)

    def _capture_analysis_sources(self, section, state, pane_idx=None):
        if section == 'fft' and getattr(self, '_opening_project', False):
            # A post-load auto-recompute (QTimer.singleShot(0, ...) queued by
            # open_project) can be drained mid-restore by a LATER
            # QApplication.processEvents() in the SAME open_project() call
            # chain (entering 'time' mode -> _plot_time_on_canvas ->
            # _begin_compute_progress(process_events=True)). By then the
            # shared Time/FFT navigator already holds the Time view's own
            # restored checked channels, not FFT's -- AnalysisViewState.
            # panes[*].sources is the source of truth for a not-yet-focused
            # section while a project is still opening, never the live
            # navigator selection. See docs/lessons-learned/signal-
            # processing/2026-07-12-processevents-drains-queued-recompute-
            # during-restore.md.
            return
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'frf':
            self._capture_frf_sources(state, idx)
            return
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
        if section == 'frf':
            self._apply_frf_sources(state)
            return
        if section == 'fft':
            self.navigator.set_checked_channels(list(pane.sources))
            self._sync_fft_source_summary()
            return
        ctx = self._analysis_ctx(section)
        if pane.sources:
            self._echo_combo_signal(ctx.combo_sig, pane.sources[0])
        else:
            self._clear_combo_selection(ctx.combo_sig)
        if section == 'order':
            if pane.rpm_source is not None:
                self._echo_combo_signal(ctx.combo_rpm, pane.rpm_source)
            else:
                self._clear_combo_selection(ctx.combo_rpm)

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

    @staticmethod
    def _clear_combo_selection(combo):
        """Clear a signal/RPM combo without emitting into PaneState."""
        old = combo.blockSignals(True)
        try:
            # Prefer the explicit "none" row when present; else leave unselected.
            none_idx = -1
            for i in range(combo.count()):
                if combo.itemData(i) is None:
                    none_idx = i
                    break
            combo.setCurrentIndex(none_idx if none_idx >= 0 else -1)
        finally:
            combo.blockSignals(old)

    # -- cache-backed render on switch (Step 3) -------------------------
    def _analysis_compute_params(self, section):
        """Compute-relevant params (cache-key inputs) for the active inspector
        state of ``section``. Display-only knobs are excluded so toggling them
        does not invalidate the cache."""
        ctx = self._analysis_ctx(section)
        p = ctx.get_params()
        if section == 'frf':
            from .frf_coordinator import frf_compute_cache_params
            return frf_compute_cache_params(p)
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
                'weighting': p.get('weighting', 'None'),
            }
        if section == 'fft_time':
            # db_reference is display-only (dB normalisation reference); compute
            # never reads it, so it is excluded from the cache-key inputs.
            return {
                'fs': p.get('fs'),
                'nfft': p.get('nfft'),
                'window': p.get('window'),
                'overlap': p.get('overlap'),
                'remove_mean': p.get('remove_mean'),
                'weighting': p.get('weighting', 'None'),
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
            'rpm_mode': p.get('rpm_mode', 'channel'),
            'manual_rpm': (
                float(p.get('manual_rpm', 1000.0))
                if p.get('rpm_mode', 'channel') == 'manual'
                else None
            ),
            'fs': p.get('fs'),
            'weighting': p.get('weighting', 'None'),
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
            # Fallback: signal not yet available (< 2 samples). Delegate to
            # the primary key function so the key is always byte-identical to
            # the one that will be stored on compute — no field-shape divergence.
            # A synthetic params dict built here previously omitted `weighting`,
            # which caused A-weighted results to share a cache slot with
            # unweighted ones (问题④).
            #
            # Auto-nfft guard (Task 4 regression): in auto-nfft mode get_params()
            # returns nfft=None AND nfft_effective=None because the effective value
            # cannot be resolved without a concrete sample count.  The primary key
            # function does int(p.get('nfft_effective', p.get('nfft'))) — both keys
            # are PRESENT with value None, so .get() returns None and int(None)
            # raises TypeError.  Resolve via the or-chain before delegating;
            # nfft_preview is always a positive integer (inspector sets it from the
            # last sample-count estimate), so it provides a stable fallback.
            p_fb = dict(p)
            p_fb['nfft_effective'] = (
                p.get('nfft_effective')
                or p.get('nfft')
                or p.get('nfft_preview')
            )
            return self._fft_time_analysis_cache_key(fid, ch, p_fb, pane_idx)
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
            elif section == 'frf':
                self.do_frf()
        except Exception:
            self.toast("恢复渲染失败，请手动点计算", "warning")

    def _render_analysis_view_from_cache(self, section, state):
        """Render each pane from cached results; panes whose sources are not all
        cached show an empty state and a 'click 计算' status hint.

        Normally never computes (spec §4). The one exception is the post-load
        auto-recompute: when this (section, view) was queued by open_project
        and still has sources, recompute it once so the saved params + sources
        repopulate the chart, then fall back to the normal cache-render path on
        every subsequent call."""
        from ..analysis_view_state import analysis_view_has_sources

        mgr = self.analysis_managers.get(section)
        if mgr is not None:
            # Persisted view identity, not a mutable list position, owns a
            # restore task. Reordering an inactive view before its deferred
            # callback runs must not redirect compute to another View.
            restore_key = (section, state.view_id)
            if restore_key in self._analysis_restore_pending:
                self._analysis_restore_pending.discard(restore_key)
                if analysis_view_has_sources(section, state):
                    # Defer the recompute to the next event-loop turn instead of
                    # running it inline. open_project drives this for all three
                    # sections mid-restore; a synchronous compute could pop a
                    # blocking QMessageBox (FFT/order compute error) that would
                    # interrupt the half-finished open. Deferring lets the window
                    # finish opening first, so any error surfaces cleanly after.
                    if section == 'frf':
                        # FRF has pane-local directional sources. Restore from
                        # the persisted state directly; ``do_frf`` captures the
                        # focused live combo pair and would erase inactive or
                        # split-pane intent during project opening.
                        QTimer.singleShot(
                            0,
                            lambda view_id=state.view_id:
                            self._recompute_restored_frf_view(view_id),
                        )
                    else:
                        QTimer.singleShot(
                            0,
                            lambda s=section: self._recompute_analysis_section(s),
                        )
                    return
        if section == 'frf':
            self._render_frf_view_from_cache(state)
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
                    if pane.sources:
                        self._show_analysis_empty_hint(canvas)
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
                    self._show_analysis_empty_hint(canvas)
                else:
                    self._render_cached_heatmap(
                        section, canvas, result, source=(fid, ch))
        if any_missing:
            self.statusBar.showMessage("参数/源已就绪，点击计算")

    def _show_analysis_empty_hint(self, canvas):
        canvas.show_empty_hint("点击『计算』生成")

    def _clear_analysis_canvas(self, canvas):
        if hasattr(canvas, 'full_reset'):
            try:
                canvas.full_reset()
            except Exception:
                pass
        if hasattr(canvas, 'clear_empty_hint'):
            try:
                canvas.clear_empty_hint()
            except Exception:
                pass

    # -- dB reference defaults (Task 5): facts adapter + Auto propagation --
    # Spec: docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md §8.
    # Plan: docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md
    # Task 5. Full per-entry/mixed-source conversion + axis labels are Task 6/7 --
    # this only keeps the ONE shared compound control (pre-Task-6 status quo) in
    # sync with the focused pane's source + the shared catalog service.

    def _channel_reference_facts(self, fid, ch):
        return self._analysis_context.channel_reference_facts(fid, ch)

    def _focused_source_for_section(self, section):
        """The ``(fid, ch)`` the section's Inspector control should resolve
        against right now. FFT's checked-channel overlay has no single
        "focused source" pre-Task-6 (mixed per-entry reference is Task 6's
        job) -- fall back to the first checked channel, then the legacy
        single-signal combo. Order/FFT-vs-Time always have exactly one
        live-selected source (``combo_sig``)."""
        if section == 'fft':
            checked = self.navigator.get_checked_channels()
            if checked:
                fid, ch, _color = checked[0]
                return (fid, ch)
            return self.inspector.fft_ctx.current_signal()
        return self._analysis_ctx(section).current_signal()

    def _resolve_db_reference_for_source(self, section, source):
        """Resolve ``section``'s dB reference for ONE specific ``(fid, ch)``
        source, honoring the section's CURRENT View mode (spec §15 C1 /
        plan Task 6 Step 6.2) -- unlike :meth:`_resolve_and_apply_db_reference`
        (which only ever targets the section's single "focused" source and
        writes the result back onto the compound control), this is a PURE
        resolution with no widget side effect, so FFT's checked-channel
        overlay can call it once per (fid, ch) ENTRY -- including sources
        other than the section's focused one -- to convert/label each curve
        with its own reference rather than one global control value (Task 5's
        deferred "Auto-resolve-on-selection-change is NOT yet wired" note).

        Manual mode reuses the single View-level value for every source
        (still resolved through :func:`db_reference.resolve_db_reference` so
        an invalid manual value falls through to the same catalog chain);
        Auto mode resolves fresh per source against the live catalog
        snapshot. Both branches read the SAME snapshot/control so this and
        :meth:`_resolve_and_apply_db_reference` can never silently drift
        apart on the resolution rule itself."""
        return self._analysis_context.resolve_db_reference_for_source(
            section, source
        )

    def _stamp_db_reference_nudge_facts(self, section):
        """Additive metadata stamp feeding the ``nudge.db_ref_manual_default``
        footer nudge (spec 2026-07-12 S5 / A17).

        Attaches ``section``'s CURRENT dB-reference View mode + compound-
        control value, plus whether the section's focused source would
        resolve (under Auto) to a real non-1.0 catalog/metadata reference,
        as a plain ``dict`` attribute on the section's focused-pane canvas.
        ``_ChartCard._nudge_signals`` (chart_stack/cards.py) reads this
        attribute -- never written anywhere else -- to populate
        ``hints.HintState.db_reference_*``. Pure fact carrier: it never
        mutates the control, the cache, or any rendered pixel."""
        ctx = self._analysis_ctx(section)
        control = ctx.db_reference_control
        mode = control.mode()
        value = control.editor.value()
        source = self._focused_source_for_section(section)
        facts = (
            self._channel_reference_facts(*source) if source
            else db_reference.ChannelReferenceFacts(quantity="", unit="")
        )
        snapshot = self.db_reference_store.snapshot()
        # Always probe the AUTO resolution regardless of the section's own
        # current mode -- the nudge's whole point is "here is what Auto would
        # give you", independent of whether the user is currently in Manual.
        auto_resolution = db_reference.resolve_db_reference(
            mode='auto',
            facts=facts,
            user_catalog=snapshot.user_catalog,
            system_catalog=snapshot.system_catalog,
            prefer_channel_metadata=snapshot.prefer_channel_metadata,
        )
        source_resolvable = bool(
            auto_resolution.source in ('metadata', 'user', 'system')
            and not math.isclose(
                auto_resolution.value, 1.0, rel_tol=1e-9, abs_tol=1e-9,
            )
        )
        page = self._analysis_page(section)
        idx = page.focused_index()
        canvas = page.pane_canvas(idx)
        if canvas is None:
            return
        canvas.db_reference_nudge_facts = {
            'mode': mode,
            'value': float(value),
            'source_resolvable': source_resolvable,
        }
        # Unlike the pre-existing situational nudges (colorbar_dead/
        # amp_disparate/...), which refresh the visible footer via a
        # canvas-emitted render signal the card already listens to
        # (chart_rebuilt / levels_rebased), this fact is stamped from
        # OUTSIDE any such signal -- force the same footer refresh here so
        # it never lags a stamp that happens without an accompanying
        # re-render (e.g. a plain View-mode toggle).
        card = page._cards[idx] if 0 <= idx < len(page._cards) else None
        refresh = getattr(card, 'refresh_nudge_state', None)
        if callable(refresh):
            refresh()

    def _resolve_and_apply_db_reference(self, section, *, rerender=False):
        """Auto-resolve ``section``'s dB reference from its currently
        focused/live source + the shared catalog service snapshot, and
        refresh the control's value + source line.

        A Manual View ignores this entirely (spec §8.1 step 1 / §8.4: manual
        is View-level and never re-derives from source/catalog). Never
        dispatches a compute worker -- ``rerender`` only replays the
        section's own existing cache-hit render path so a catalog save (or
        an Auto commit from the shared dialog) can force an immediate
        redraw for the CURRENTLY VISIBLE section without recomputing."""
        ctx = self._analysis_ctx(section)
        control = ctx.db_reference_control
        if control.mode() != 'auto':
            # Manual (or any non-auto) View still needs its nudge facts kept
            # live -- e.g. a focused-source change while the section stays
            # Manual can flip source_resolvable without touching the control.
            self._stamp_db_reference_nudge_facts(section)
            return
        source = self._focused_source_for_section(section)
        resolution = self._resolve_db_reference_for_source(section, source)
        # Widget signals blocked: this is a PROGRAMMATIC Auto refresh, never
        # a user commit, and must not trip the editor's own valueChanged ->
        # cache-hit-rerender wiring (window._connect) nor any preset-changed
        # handler (Task 4's existing blocking pattern, e.g. set_fs's
        # spin_fs.blockSignals around a programmatic setValue).
        control.editor.blockSignals(True)
        try:
            control.editor.setValue(resolution.value)
        finally:
            control.editor.blockSignals(False)
        text, tooltip = _format_db_reference_source_line(resolution)
        control.set_source_text(text, tooltip=tooltip)
        # Nudge facts stamped AFTER the auto value settles so the carried
        # ``value`` matches what is actually shown (the predicate only fires
        # for mode == 'manual' so this is inert while Auto, but keeps the
        # attribute honest for any future consumer).
        self._stamp_db_reference_nudge_facts(section)
        if rerender:
            self._rerender_analysis_section_from_cache(section)

    def _rerender_analysis_section_from_cache(self, section):
        """Redraw ``section``'s active view from whatever the cache already
        holds -- zero compute dispatch (spec §8.3). Reuses each section's
        OWN existing cache-hit render entry point instead of a new one, so
        no cache-consumer logic is duplicated (fft: the spectrum-preserving
        mode-entry gate; fft_time/order: their own do_* entry points, which
        already no-op the worker on a cache hit -- see the existing
        db_reference-editor valueChanged wiring in window._connect)."""
        if section == 'fft':
            self._enter_fft_mode()
        elif section == 'fft_time':
            self.do_fft_time(force=False)
        else:
            self.do_order_time()

    def _on_db_reference_catalog_saved(self, section=None):
        """The shared ``DbReferenceDefaultsDialog`` committed a catalog save
        (spec §8.3): every Auto section re-resolves against the new
        snapshot, but only the CURRENTLY VISIBLE one redraws its canvas --
        the other (hidden) Auto sections just get their control's value/
        source line refreshed with zero canvas touch, so their render
        signature naturally goes stale without a compute dispatch."""
        visible = self.chart_stack.current_mode()
        for sec in ('fft', 'fft_time', 'order'):
            self._resolve_and_apply_db_reference(sec, rerender=(sec == visible))

    def _on_db_reference_view_mode_committed(self, section, mode):
        """The dialog's '当前 View' toggle targets ONLY the section/View that
        was focused when its manage button opened the dialog (spec §11.1)."""
        ctx = self._analysis_ctx(section)
        ctx.db_reference_control.set_mode(mode)
        if mode == 'auto':
            self._resolve_and_apply_db_reference(
                section, rerender=(self.chart_stack.current_mode() == section)
            )
        else:
            # Auto's branch above stamps via _resolve_and_apply_db_reference;
            # a commit BACK to Manual needs the same live nudge-fact refresh
            # (spec S5's self-clear-on-Auto/edit-away needs the reverse too).
            self._stamp_db_reference_nudge_facts(section)
