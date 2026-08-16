"""AnalysisMixin: per-section analysis view routing + cross-cutting helpers.

This mixin owns the V7 per-section view pipeline (capture → switch → apply →
render) for the FFT / Order / FFT-vs-Time analysis sections, plus the
cross-cutting helpers (``_pane_time_range_for``, ``_mask_time_range``,
``_analysis_page``, ``_analysis_cache_key``, ``_analysis_channel_color_map``,
``_capture_active_analysis_view``) that FFTMixin / OrderMixin / FFTTimeMixin
call through ``self.``.  Method-resolution order makes those calls find this
copy regardless of base-class order — there are no name collisions.
"""

import logging
import math
from functools import partial

import numpy as np

from PyQt5.QtWidgets import QColorDialog, QMessageBox
from PyQt5.QtCore import QTimer

from .ultraview_coordinator import notify_ultraview_plot

from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text

from ... import db_reference
from ..compute_feedback import summarize_compute
from .analysis_context import AnalysisContext

logger = logging.getLogger(__name__)

# Relative tolerance vs full data span when deciding whether unchecked
# start/end spinboxes are a "local draft" worth confirming before compute.
_TIME_RANGE_DRAFT_LOCAL_TOL = 0.01


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

    def _on_analysis_view_rename(self, section, idx, name):
        """F10: rename then refresh navigator empty-state for the active View."""
        mgr = self.analysis_managers[section]
        mgr.rename(idx, name)
        if self.chart_stack.current_mode() != section:
            return
        if idx != mgr.active:
            return
        if not (0 <= idx < len(mgr.views)):
            return
        state = mgr.get(idx)
        empty = getattr(self.navigator, 'set_empty_state_context', None)
        if callable(empty):
            empty(
                section_label=self._analysis_section_label(section),
                view_name=state.name,
            )

    def _on_analysis_new(self, section):
        self._capture_active_analysis_view(section)
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

            mgr = self.analysis_managers[section]
            section_state = mgr.get(mgr.active) if mgr.views else None
            section_att = (
                list(section_state.attached_file_ids)
                if section_state is not None
                else []
            )
            time_resolved = self._focused_time_view_state()
            time_att = (
                list(time_resolved[1].attached_file_ids)
                if time_resolved is not None
                else []
            )
            template_fids = resolve_new_view_template(
                section_att, time_att, self.files
            )
            section_only = resolve_new_view_template(
                section_att, [], self.files
            )
            if section_only and section_state is not None:
                template_name = section_state.name
            elif time_resolved is not None:
                template_name = time_resolved[1].name
        idx = self.analysis_managers[section].new_view()
        if idx < 0:
            return
        if inherit and template_fids:
            added = self._attach_files_to_active_analysis_view(
                section, template_fids
            )
            if added:
                self.toast(
                    f"已继承 {len(added)} 个文件 · 来自 {template_name}",
                    "success",
                )

    def _on_analysis_delete(self, section, idx):
        self._capture_active_analysis_view(section)
        mgr = self.analysis_managers[section]
        if len(mgr.views) > 1 and 0 <= idx < len(mgr.views):
            state = mgr.get(idx)
            self._analysis_restore_pending.discard((section, state.view_id))
            # Drop pin bookkeeping before the view disappears so later LRU
            # passes treat its results as unowned history (spec §5).
            self._drop_analysis_view_pins(section, state.view_id)
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
            if len(state.panes) > 1:
                # Drop pane-1 residency before the pane disappears from state
                # (F13). FRF also bumps its coordinator generation so an
                # in-flight pane-1 completion cannot repopulate cache.
                if section == 'frf':
                    self._frf_coordinator.invalidate_pane(state.view_id, 1)
                if section in {'fft', 'fft_time', 'order', 'frf'}:
                    self._replace_analysis_pane_pins(
                        section, state.view_id, 1, ())
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
            self._wire_heatmap_levels_echo(page.pane_canvas(1), section, 1)

    def _wire_heatmap_levels_echo(self, canvas, section, pane_idx):
        """Echo colorbar drag and double-click restore into the inspector.

        ``partial`` rather than ``lambda`` so the connect-lambda ratchet
        stays shrink-only. Both signals share the same handler: restore is
        a finished window, not an in-progress drag, but the inspector write
        (silent ``apply_params``) is identical.
        """
        if canvas is None or getattr(canvas, '_levels_echo_wired', False):
            return
        echo = partial(self._on_analysis_levels_dragged, section, pane_idx)
        canvas.levels_changed.connect(echo)
        restored = getattr(canvas, 'colorbar_restored', None)
        if restored is not None:
            restored.connect(echo)
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
        self._capture_analysis_overlay(section, state)
        if capture_sources:
            self._capture_analysis_sources(section, state)

    def _capture_analysis_overlay(self, section, state):
        from ..analysis_view_bridge import capture_overlay_from_canvas

        page = self._analysis_page(section)
        if not getattr(page, "_overlay_session_bound", False):
            return
        for pane_idx in range(min(page.pane_count(), len(state.panes))):
            capture_overlay_from_canvas(
                page.pane_canvas(pane_idx), state.panes[pane_idx],
            )

    def _apply_analysis_overlay(self, section, state):
        from ..analysis_view_bridge import apply_overlay_to_canvas

        page = self._analysis_page(section)
        page._overlay_session_bound = True
        for pane_idx in range(min(page.pane_count(), len(state.panes))):
            apply_overlay_to_canvas(
                page.pane_canvas(pane_idx), state.panes[pane_idx],
            )

    def _sync_active_analysis_params(self, section):
        """Persist the active contextual's full View payload immediately.

        The shared Inspector is a projection.  A user edit must therefore
        update the focused View's complete ledger at the event boundary rather
        than waiting for the next View switch or project save to capture it.
        """
        if self._applying_analysis_view:
            return None
        # Shared Inspector controls may be updated by another section while
        # this analysis page is hidden (for example, source/default routing).
        # Only the visible section represents an intentional edit to its
        # active View; a hidden projection must be restored from that View on
        # re-entry rather than overwriting its ledger.
        if self.chart_stack.current_mode() != section:
            return None
        # Lightweight mixin probes from older tests/extensions predate
        # AnalysisContext.  Preserve their inspector-only seam while real
        # MainWindow instances continue through the owning context facade.
        if hasattr(self, '_analysis_context'):
            ctx = self._analysis_ctx(section)
        else:
            ctx = getattr(self.inspector, f'{section}_ctx')
        if getattr(ctx, '_applying_preset', False):
            return None
        mgr = self.analysis_managers[section]
        if not mgr.views:
            return None
        params_getter = getattr(ctx, 'current_params', ctx.get_params)
        state = mgr.get(mgr.active)
        state.params = dict(params_getter())
        return state

    def _on_analysis_compute_params_changed(self, section, _params):
        """Record a compute edit without implicitly submitting a new job."""
        self._sync_active_analysis_params(section)

    def _on_analysis_display_params_changed(self, section, _params):
        """Record a display edit and redraw only the visible active View."""
        state = self._sync_active_analysis_params(section)
        if state is not None and self.chart_stack.current_mode() == section:
            self._render_analysis_view_from_cache(section, state)

    def _on_fft_display_params_changed(self, value):
        """Compatibility slot for the original FFT amplitude-unit wiring."""
        self._on_analysis_display_params_changed('fft', value)

    def _on_analysis_view_switched(self, section, idx, *, render=True,
                                   apply_params=True):
        """manager.active_changed → apply the new view's structure, params and
        sources, then render whatever the cache already holds (never compute).

        ``render`` / ``apply_params`` let FFT *mode entry* apply the target
        View's params/sources while deferring canvas restore to
        ``_enter_fft_mode`` (signature-aware reuse). Params must always be
        applied on mode entry so live Inspector values cannot overwrite the
        destination View.
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
            self._apply_analysis_overlay(section, state)
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
        # apply_params is silent (no display_params_changed → no replot).
        # Persist the View ledger here so a later view-switch still sees
        # the dragged / restored window.
        self._sync_active_analysis_params(section)

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

    def _analysis_time_range_draft_is_local(self):
        """Return ``(lo, hi)`` when start/end is an unchecked local draft.

        A draft is "local" when「使用选定时间范围」is off and the spinbox span
        is a proper subset of the **plotted** data extent (beyond a 1%
        tolerance). Returns ``None`` when already armed, invalid, or ≈ full
        plotted extent — those cases should not interrupt compute with a
        confirm dialog.
        """
        top = self.inspector.top
        if top.range_enabled():
            return None
        try:
            lo = float(top.spin_start.value())
            hi = float(top.spin_end.value())
        except (TypeError, ValueError):
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        extent = getattr(self, '_plotted_time_extent', None) or getattr(
            self, '_time_data_extent', None
        )
        if not callable(extent):
            return None
        full_lo, full_hi = extent()
        full_span = float(full_hi) - float(full_lo)
        if not (np.isfinite(full_span) and full_span > 0):
            return None
        tol = _TIME_RANGE_DRAFT_LOCAL_TOL * full_span
        # ≈ full extent → no prompt (user did not draft a window).
        if lo <= full_lo + tol and hi >= full_hi - tol:
            return None
        # Must overlap the data at all; pure out-of-range drafts skip the ask.
        if hi <= full_lo + tol or lo >= full_hi - tol:
            return None
        return (lo, hi)

    def _ask_use_local_time_range(self, lo, hi):
        """Modal confirm for an unchecked local draft. Returns
        ``'local'`` / ``'full'`` / ``'cancel'``. Tests monkeypatch this."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("未启用选定时间范围")
        box.setText(
            f"开始/结束为 {lo:g}–{hi:g} s，但未勾选「使用选定时间范围」。\n"
            "是否按该局部范围计算？"
        )
        local_btn = box.addButton("用局部范围", QMessageBox.AcceptRole)
        full_btn = box.addButton("用全时段", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(local_btn)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is local_btn:
            return 'local'
        if clicked is full_btn:
            return 'full'
        return 'cancel'

    def _offer_analysis_time_range_before_compute(self, section):
        """Gate user-initiated analysis compute on an unchecked local draft.

        Returns ``True`` to proceed, ``False`` to abort. Selecting「用局部范围」
        arms the shared checkbox (via ``set_range_from_span``) so the following
        ``_capture_active_analysis_view`` writes ``pane.time_range``. Call
        **before** capture on ``do_fft`` / ``do_fft_time`` / ``do_order_time`` /
        ``do_frf`` only — not on project-restore auto-recompute or Batch.
        """
        if not self._analysis_section_uses_time_range(section):
            return True
        draft = self._analysis_time_range_draft_is_local()
        if draft is None:
            return True
        lo, hi = draft
        choice = self._ask_use_local_time_range(lo, hi)
        if choice == 'cancel':
            return False
        if choice == 'local':
            self.inspector.top.set_range_from_span(lo, hi)
        return True

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
            if checked:
                pane.sources = [(fid, ch) for fid, ch, _color in checked]
            else:
                ctx = self._analysis_ctx(section)
                sig = ctx.current_signal() if hasattr(ctx, 'current_signal') else None
                try:
                    fid, ch = sig[0], sig[1]
                except (TypeError, ValueError, IndexError):
                    pane.sources = []
                else:
                    pane.sources = [(fid, ch)] if fid in self.files else []
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
        if hasattr(self, '_analysis_context'):
            ctx = self._analysis_ctx(section)
        else:
            ctx = getattr(self.inspector, f'{section}_ctx')
        compute_params = getattr(ctx, 'compute_params', None)
        p = compute_params() if callable(compute_params) else ctx.get_params()
        if section == 'frf':
            from .frf_coordinator import frf_compute_cache_params
            return frf_compute_cache_params(p)
        return p

    def _analysis_cache_key(self, section, fid, ch, rpm_source=None, pane_idx=None):
        cache = self.analysis_caches[section]
        if section == 'fft_time':
            p = self._analysis_compute_params('fft_time')
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
        """Dispatch the active view's compute for ``section``.

        Used by tests and as a fallback for an explicit section-wide
        recompute. Project restore uses ``_recompute_restored_analysis_view``
        keyed by persisted ``view_id`` so inactive Views are not redirected
        onto live Inspector state.
        """
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

    def _analysis_state_by_id(self, section, view_id):
        mgr = self.analysis_managers.get(section)
        if mgr is None:
            return None
        target = str(view_id or "")
        for state in mgr.views:
            if state.view_id == target:
                return state
        return None

    def _compute_params_overlay_state(self, section, state):
        """Merge persisted View params onto the live compute-params schema.

        Inactive restore must not ``apply_params`` onto the shared Inspector.
        Overlaying saved keys onto the current schema keeps cache identity
        aligned with a later apply/get round-trip of the same View.
        """
        live = dict(self._analysis_compute_params(section))
        saved = dict(getattr(state, "params", None) or {})
        live.update({key: saved[key] for key in live if key in saved})
        return live

    def _analysis_restore_widgets_alive(self):
        from PyQt5 import sip
        try:
            if sip.isdeleted(self):
                return False
            bar = getattr(self, "_compute_progress", None)
            if bar is None or sip.isdeleted(bar):
                return False
        except (RuntimeError, TypeError):
            return False
        return True

    def _abort_analysis_restore(self):
        """Drop the restore pump so a closing window cannot paint a dead bar."""
        self._analysis_restore_queue = []
        self._analysis_restore_total = 0
        jobs = getattr(self, "_analysis_jobs", None)
        if jobs is not None:
            jobs.clear_progress_token("restore")

    def _dispatch_pending_analysis_restore(self):
        """Recompute queued Views one event-loop turn at a time.

        Scheduling every View as ``singleShot(0)`` made them all run in one
        drained burst (nested inside time-plot ``processEvents``), which froze
        the GUI and showed the macOS beachball. One View per timer tick lets
        Cocoa run, and one restore progress token owns the status bar.
        """
        pending = list(self._analysis_restore_pending)
        if not pending:
            return

        def _is_active(section, view_id):
            mgr = self.analysis_managers.get(section)
            if mgr is None or not mgr.views:
                return False
            return str(mgr.get(mgr.active).view_id) == str(view_id)

        pending.sort(
            key=lambda item: (0 if _is_active(*item) else 1, item[0], item[1])
        )
        self._analysis_restore_queue = pending
        self._analysis_restore_total = len(pending)
        token = self._begin_compute_progress(
            "正在恢复分析 0/%d" % len(pending),
            total=len(pending),
            process_events=False,
        )
        self._analysis_jobs.set_progress_token("restore", token)
        self._compute_progress.repaint()
        QTimer.singleShot(0, self._pump_analysis_restore)

    def _analysis_restore_workers_busy(self):
        jobs = getattr(self, "_analysis_jobs", None)
        if jobs is None:
            return False
        return any(
            jobs.is_busy(section)
            for section in ("fft_time", "order", "frf")
        )

    def _update_analysis_restore_progress(self, *, flush_events=False):
        if not self._analysis_restore_widgets_alive():
            self._abort_analysis_restore()
            return
        token = self._restore_progress_token()
        if token is None:
            return
        total = int(getattr(self, "_analysis_restore_total", 0) or 0)
        remaining = len(getattr(self, "_analysis_restore_queue", None) or [])
        done = max(0, total - remaining)
        if total <= 0:
            return
        self._update_compute_progress(
            done,
            total,
            label="正在恢复分析 %d/%d" % (done, total),
            token=token,
            flush_events=flush_events,
        )

    def _pump_analysis_restore(self):
        if not self._analysis_restore_widgets_alive():
            self._abort_analysis_restore()
            return
        queue = getattr(self, "_analysis_restore_queue", None)
        if not queue:
            self._finish_analysis_restore_if_idle()
            return
        section, view_id = queue.pop(0)
        self._recompute_restored_analysis_view(section, view_id)
        self._update_analysis_restore_progress()
        QTimer.singleShot(0, self._pump_analysis_restore)

    def _finish_analysis_restore_if_idle(self):
        if not self._analysis_restore_widgets_alive():
            self._abort_analysis_restore()
            return
        queue = getattr(self, "_analysis_restore_queue", None)
        if queue:
            return
        if self._analysis_restore_workers_busy():
            return
        token = self._analysis_jobs.clear_progress_token("restore")
        self._analysis_restore_queue = []
        self._analysis_restore_total = 0
        if token is None:
            return
        # Token was gated in `_finish_compute_progress` while registered.
        self._finish_compute_progress(token=token)

    def _recompute_restored_analysis_view(self, section, view_id):
        """Restore one View from persisted pane state, never live capture."""
        key = (section, view_id)
        if key not in self._analysis_restore_pending:
            return
        self._analysis_restore_pending.discard(key)
        try:
            if section == 'frf':
                self._recompute_restored_frf_view(view_id)
            elif section == 'fft':
                self._recompute_restored_fft_view(view_id)
            elif section == 'fft_time':
                self._recompute_restored_fft_time_view(view_id)
            elif section == 'order':
                self._recompute_restored_order_view(view_id)
        except Exception:
            self.toast("恢复渲染失败，请手动点计算", "warning")

    # -- analysis cache pinning (spec 2026-08-11) -----------------------------
    # Pin bookkeeping records the *real* cache keys that render/put already
    # hold. Never re-derive keys from state.params alone (Qt round-trip can
    # diverge). Pinning is residency only — invalidate_fid still deletes
    # pinned entries, and dead pin keys are left to the next render replace.
    # Mutations go through AnalysisPinBook methods (holder), not bare dict
    # writes on self._analysis_pins.

    def _pinned_keys_for_section(self, section):
        return self._analysis_pins.pinned_keys(section)

    def _analysis_ctx_targets_active_view(self, section, ctx) -> bool:
        """True when ``ctx['view_id']`` is still this section's active View.

        Async completions always cache/pin under the *dispatch-time*
        ``view_id`` (see ``fft_time_coordinator`` / order job ctx).  Drawing
        onto the live page, however, must only happen while that View is
        still active — otherwise a slow job finishing after a tab switch
        paints the wrong chart (A7).  Callers keep ``_store_analysis_result``
        outside this gate so the inactive View can restore from cache.
        """
        mgr = self.analysis_managers.get(section)
        if mgr is None or not mgr.views:
            return False
        active = mgr.get(mgr.active)
        return str(ctx.get("view_id") or "") == str(active.view_id)

    def _store_analysis_result(self, section, view_id, pane_idx, key, result):
        """Single write funnel: cache put always, pin append only when
        ``view_id`` names a real View (spec §4.1/§4.1 footnote).

        A ``None`` view_id means the dispatch path that produced this result
        never attached a real View identity to its ctx/candidate dict — pin
        bookkeeping keys off ``str(view_id)``, so pinning here would wedge
        the result into a permanent ``('<section>', 'None', pane_idx)`` slot
        that render-time replace can never reach (it only ever replaces real
        view_id slots). Cache the result anyway so it is not lost, skip the
        pin, and log so a future dispatch path that forgets to carry
        view_id is not a silent permanent-pin leak.
        """
        self.analysis_caches[section].put(key, result)
        if view_id is None:
            logger.warning(
                "_store_analysis_result: view_id is None for section=%r "
                "pane_idx=%r key=%r -- result cached but not pinned",
                section, pane_idx, key,
            )
        else:
            self._analysis_pins.add(section, view_id, pane_idx, key)
        uv = getattr(self, "_ultraview", None)
        if uv is not None:
            uv.notify_result_stored(section, view_id, pane_idx, key, result)

    def _replace_analysis_pane_pins(self, section, view_id, pane_idx, keys):
        """Replace one pane's pin set with the keys enumerated at render time."""
        self._analysis_pins.replace(section, view_id, pane_idx, keys)

    def _drop_analysis_view_pins(self, section, view_id):
        self._analysis_pins.drop_view(section, view_id)

    def _clear_analysis_section_pins(self, section):
        self._analysis_pins.clear_section(section)

    def _render_analysis_view_from_cache(self, section, state):
        """Render each pane from cached results; panes whose sources are not all
        cached show an empty state and a 'click 计算' status hint.

        Normally never computes (spec §4). After ``open_project`` every
        source-bearing View is dispatched by ``view_id``. If this View is
        still pending when it first becomes visible (tab switch before the
        timer), schedule that same restore once, then fall back to cache.
        """
        from ..analysis_view_state import analysis_view_has_sources

        mgr = self.analysis_managers.get(section)
        if mgr is not None:
            # Persisted view identity, not a mutable list position, owns a
            # restore task. Reordering an inactive view before its deferred
            # callback runs must not redirect compute to another View.
            restore_key = (section, state.view_id)
            if restore_key in self._analysis_restore_pending:
                if getattr(self, "_opening_project", False):
                    # open_project dispatches every pending View after the
                    # window finishes opening. Do not compute mid-restore.
                    pass
                elif analysis_view_has_sources(section, state):
                    QTimer.singleShot(
                        0,
                        lambda s=section, v=state.view_id:
                        self._recompute_restored_analysis_view(s, v),
                    )
                    return
        if section == 'frf':
            self._render_frf_view_from_cache(state)
            return
        page = self._analysis_page(section)
        any_missing = False
        enumerated_panes = set()
        for pane_idx in range(page.pane_count()):
            if pane_idx >= len(state.panes):
                break
            enumerated_panes.add(pane_idx)
            pane = state.panes[pane_idx]
            canvas = page.pane_canvas(pane_idx)
            cache = self.analysis_caches[section]
            if section == 'fft':
                entries = []
                pane_keys = []
                colors = self._analysis_channel_color_map()
                time_range = self._pane_time_range_for(section, pane_idx)
                for fid, ch in pane.sources:
                    key = self._analysis_cache_key(
                        section, fid, ch, pane_idx=pane_idx)
                    pane_keys.append(key)
                    result = cache.get(key)
                    if result is None:
                        any_missing = True
                        continue
                    entries.append(self._fft_entry_from_cache(
                        result, fid, ch, colors.get((fid, ch)),
                        time_range=time_range))
                self._replace_analysis_pane_pins(
                    section, state.view_id, pane_idx, pane_keys)
                if entries:
                    self._plot_fft_entries(entries, canvas)
                else:
                    # No cached curves (empty sources, or all sources missing
                    # from the cache) -> empty canvas state.  A source can be
                    # intentionally selected before its first FFT compute;
                    # returning to that View must still restore its lower
                    # time-domain preview after the pane sources are applied.
                    self._clear_analysis_canvas(canvas)
                    self._rebind_pane_overlay(canvas, pane)
                    if pane.sources:
                        if pane_idx == page.focused_index():
                            self._refresh_fft_time_preview(
                                clear_spectrum=False)
                        self._show_analysis_empty_hint(canvas)
            else:
                if not pane.sources:
                    self._clear_analysis_canvas(canvas)
                    self._rebind_pane_overlay(canvas, pane)
                    self._replace_analysis_pane_pins(
                        section, state.view_id, pane_idx, ())
                    continue
                fid, ch = pane.sources[0]
                key = self._analysis_cache_key(
                    section, fid, ch,
                    rpm_source=pane.rpm_source if section == 'order' else None,
                    pane_idx=pane_idx)
                # Record binding intent even on miss so a later put is already
                # protected (spec §4).
                self._replace_analysis_pane_pins(
                    section, state.view_id, pane_idx, (key,))
                result = cache.get(key)
                if result is None:
                    any_missing = True
                    self._clear_analysis_canvas(canvas)
                    self._rebind_pane_overlay(canvas, pane)
                    self._show_analysis_empty_hint(canvas)
                else:
                    self._render_cached_heatmap(
                        section, canvas, result, source=(fid, ch))
        # Panes not visited this render (e.g. split cleared) drop their pins.
        for pane_idx in range(len(state.panes)):
            if pane_idx not in enumerated_panes:
                self._replace_analysis_pane_pins(
                    section, state.view_id, pane_idx, ())
        if any_missing:
            self.statusBar.showMessage("参数/源已就绪，点击计算")
        notify_ultraview_plot(self, section, "analysis-restore-plot")

    def _rebind_pane_overlay(self, canvas, pane) -> None:
        from ..analysis_view_bridge import apply_overlay_to_canvas

        apply_overlay_to_canvas(canvas, pane)

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
