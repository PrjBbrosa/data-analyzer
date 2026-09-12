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
from . import view_activation

from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text

from ... import db_reference
from ..compute_feedback import summarize_compute
from .analysis_context import AnalysisContext
from .analysis_time_range import (
    display_ranges_equal,
    enabled_covers_sources,
    make_source_signature,
    parse_span,
    validate_requested_span,
)

logger = logging.getLogger(__name__)

def _format_seconds_endpoint(value):
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_span_seconds(span):
    pair, _valid = parse_span(span) if span is not None else (None, False)
    if pair is None:
        try:
            return (
                f"{_format_seconds_endpoint(span[0])}"
                f"–{_format_seconds_endpoint(span[1])} 秒"
            )
        except (TypeError, ValueError, IndexError):
            return "无效范围"
    return (
        f"{_format_seconds_endpoint(pair[0])}"
        f"–{_format_seconds_endpoint(pair[1])} 秒"
    )


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
        manager = self.analysis_managers[section]
        defer_activation = view_activation.defer_new_view_activation_after_pointer_release()
        idx = manager.new_view(activate=not defer_activation)
        if idx < 0:
            return
        if defer_activation:
            view_id = manager.get(idx).view_id
            QTimer.singleShot(
                0,
                partial(
                    self._activate_new_analysis_view_after_pointer_release,
                    section,
                    view_id,
                    tuple(template_fids),
                    template_name,
                ),
            )
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

    def _activate_new_analysis_view_after_pointer_release(
        self, section, view_id, template_fids, template_name,
    ):
        """Finish a frozen-Windows analysis-View action after pointer release."""
        manager = self.analysis_managers.get(section)
        if manager is None:
            return
        idx = next(
            (
                index
                for index, state in enumerate(manager.views)
                if state.view_id == view_id
            ),
            None,
        )
        if idx is None:
            return
        manager.set_active(idx)
        if template_fids:
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
            self._forget_analysis_view(
                section, state.view_id, len(getattr(state, "panes", ()))
            )
        mgr.delete_view(idx)

    def _forget_analysis_view(self, section, view_id, pane_count=1):
        self._analysis_restore_pending.discard((section, view_id))
        self._drop_analysis_view_pins(section, view_id)
        ctrl = getattr(getattr(self, "_analysis_context", None), "time_range", None)
        if ctrl is not None:
            ctrl.clear_view(section, view_id)
        if section == "frf":
            for pane_idx in range(max(1, int(pane_count or 1))):
                self._frf_coordinator.invalidate_pane(view_id, pane_idx)

    def _on_analysis_close_others(self, section, keep_view_id):
        mgr = self.analysis_managers[section]
        keep_idx = next(
            (
                idx
                for idx, state in enumerate(mgr.views)
                if str(state.view_id) == str(keep_view_id)
            ),
            -1,
        )
        if keep_idx < 0 or len(mgr.views) <= 1:
            return
        keep = mgr.get(keep_idx)
        if not self._confirm_close_other_views(
            len(mgr.views) - 1, keep_idx + 1, keep.name
        ):
            return
        self._capture_active_analysis_view(section)
        removed_meta = [
            (state.view_id, len(getattr(state, "panes", ())))
            for state in mgr.views
            if str(state.view_id) != str(keep.view_id)
        ]
        for view_id, pane_count in removed_meta:
            self._forget_analysis_view(section, view_id, pane_count)
        mgr.retain_only_view(str(keep.view_id))

    def _on_analysis_close_all(self, section):
        mgr = self.analysis_managers[section]
        count = len(mgr.views)
        if count <= 1:
            return
        if not self._confirm_close_all_views(count):
            return
        for state in list(mgr.views):
            self._forget_analysis_view(
                section, state.view_id, len(getattr(state, "panes", ()))
            )
        mgr.reset_to_single_default()

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
                ctrl = getattr(
                    getattr(self, "_analysis_context", None), "time_range", None,
                )
                if ctrl is not None:
                    ctrl.clear_pane(section, state.view_id, 1)
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
        if section in {'fft', 'fft_time', 'order'}:
            self._wire_analysis_viewport_intent(page.pane_canvas(0), section, 0)
            self._wire_analysis_viewport_intent(page.pane_canvas(1), section, 1)
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

    def _analysis_xy_fingerprint(self, params):
        params = params or {}
        return (
            bool(params.get("x_auto", params.get("autoscale", True))),
            params.get("x_min"),
            params.get("x_max"),
            bool(params.get("y_auto", True)),
            params.get("y_min"),
            params.get("y_max"),
        )

    def _clear_analysis_view_viewports(self, state, axes=("x", "y")):
        for pane in state.panes:
            for axis in axes:
                setattr(pane, axis + "lim", None)
                pane.viewport_origin[axis] = "auto"

    def _wire_analysis_viewport_intent(self, canvas, section, pane_idx):
        """Consume the axis-aware event only; old signal remains public compatibility."""
        canvas.analysis_range_adapter = (
            partial(self._analysis_range_policy, section, pane_idx),
            partial(self._apply_analysis_range_policy, section, pane_idx),
        )
        signal = getattr(canvas, "viewport_action_committed", None)
        if signal is None or getattr(canvas, "_viewport_intent_wired", False):
            return
        signal.connect(partial(self._on_analysis_viewport_intent, section, pane_idx))
        canvas._viewport_intent_wired = True

    def _analysis_range_policy(self, section, pane_idx):
        state = self.analysis_managers[section].get(self.analysis_managers[section].active)
        return {**state.params, "viewport_origin": dict(state.panes[pane_idx].viewport_origin)}

    def _apply_analysis_range_policy(self, section, pane_idx, policies):
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        patch = {}
        for axis, (auto, limits) in policies.items():
            patch[axis + "_auto"] = auto
            if not auto:
                patch[axis + "_min"], patch[axis + "_max"] = limits
        ctx = self._analysis_ctx(section)
        ctx.apply_params(patch)
        state.params = dict(ctx.current_params())
        if self._project_dirty is not None:
            self._project_dirty.mark_user_mutation()
        self._clear_analysis_view_viewports(state, tuple(policies))
        self._render_analysis_view_from_cache(section, state)

    def _on_analysis_viewport_intent(self, section, pane_idx, action="user", axes=("x", "y")):
        if action not in {"user", "home"} or any(axis not in {"x", "y"} for axis in axes):
            raise ValueError("Invalid analysis viewport action")
        if self._applying_analysis_view or self.chart_stack.current_mode() != section:
            return
        mgr = self.analysis_managers.get(section)
        if mgr is None or not mgr.views:
            return
        state = mgr.get(mgr.active)
        self._commit_analysis_pane_viewport(section, state, pane_idx, action, axes)
        if self._project_dirty is not None:
            self._project_dirty.mark_user_mutation()
        page = self._analysis_page(section)
        sibling = 1 - int(pane_idx)
        if "x" in axes and state.compare.get("x_linked", True) and sibling < page.pane_count() and sibling < len(state.panes):
            self._commit_analysis_pane_viewport(section, state, sibling, action, ("x",))

    def _commit_analysis_pane_viewport(self, section, state, pane_idx, action=None, axes=("x", "y")):
        page = self._analysis_page(section)
        if pane_idx >= page.pane_count() or pane_idx >= len(state.panes):
            return
        captured = page.pane_canvas(pane_idx).capture_xy_viewport()
        if captured is None:
            return
        pane = state.panes[pane_idx]
        for axis, limits in zip(("x", "y"), captured):
            if axis in axes:
                setattr(pane, axis + "lim", limits)
                if action is not None:
                    pane.viewport_origin[axis] = action

    def _capture_analysis_xy_viewports(self, section, state):
        if section in {"fft", "fft_time", "order"}:
            page = self._analysis_page(section)
            for pane_idx in range(min(page.pane_count(), len(state.panes))):
                self._commit_analysis_pane_viewport(section, state, pane_idx)

    def _restore_analysis_pane_viewport(self, section, state, pane_idx, canvas):
        from ...ui_kit.ticks_math import finite_non_degenerate_range, ranges_overlap

        if section not in {"fft", "fft_time", "order"} or canvas is None or pane_idx >= len(state.panes):
            return
        pane = state.panes[pane_idx]
        current = canvas.capture_xy_viewport()
        if current is None:
            return
        data = canvas.data_xy_extents()
        target = list(current)
        changed = False
        for index, axis in enumerate(("x", "y")):
            if pane.viewport_origin[axis] == "auto":
                continue
            saved = getattr(pane, axis + "lim")
            extent = data[index] if data else None
            try:
                valid = saved is not None and finite_non_degenerate_range(*saved) is not None and (extent is None or ranges_overlap(saved, extent))
            except (TypeError, ValueError, IndexError):
                valid = False
            if valid:
                target[index] = saved
                changed = True
            else:
                setattr(pane, axis + "lim", None)
                pane.viewport_origin[axis] = "auto"
        if changed:
            canvas.restore_xy_viewport(*target)

    def _restore_analysis_canvas_viewport(self, section, canvas):
        managers = getattr(self, "analysis_managers", None) or {}
        mgr = managers.get(section)
        if mgr is None or not mgr.views or canvas is None:
            return
        page = self._analysis_page(section)
        state = mgr.get(mgr.active)
        for pane_idx in range(min(page.pane_count(), len(state.panes))):
            if page.pane_canvas(pane_idx) is canvas:
                self._restore_analysis_pane_viewport(
                    section, state, pane_idx, canvas
                )
                return

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
        elif section in {'fft', 'fft_time', 'order'}:
            self._capture_analysis_xy_viewports(section, state)
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
        bar = getattr(ctx, 'preset_bar', None)
        if getattr(bar, 'is_transaction_open', False):
            return None
        mgr = self.analysis_managers[section]
        if not mgr.views:
            return None
        params_getter = getattr(ctx, 'current_params', ctx.get_params)
        state = mgr.get(mgr.active)
        state.params = dict(params_getter())
        holder = getattr(self, "_project_dirty", None)
        if holder is not None:
            holder.mark_user_mutation()
        return state

    def _on_preset_committed(self, section, _baseline=None):
        """Sync complete View payload after a successful user preset transaction."""
        if getattr(self, '_applying_analysis_view', False):
            return
        if hasattr(self, '_analysis_context'):
            ctx = self._analysis_ctx(section)
            sync = self._analysis_context.sync_committed_preset
        else:
            ctx_name = 'fft_time_ctx' if section == 'fft_time' else f'{section}_ctx'
            ctx = getattr(getattr(self, 'inspector', None), ctx_name, None)
            if ctx is None:
                return
            from ..analysis_view_bridge import capture_params_to_state

            def sync(_section, state, _ctx=ctx):
                capture_params_to_state(_ctx, state)

        mgr = (getattr(self, 'analysis_managers', None) or {}).get(section)
        if mgr is None or not getattr(mgr, 'views', None):
            return
        state = mgr.get(mgr.active)
        before_params = dict(state.params or {})
        sync(section, state)
        holder = getattr(self, '_project_dirty', None)
        if holder is not None:
            holder.mark_user_mutation()
        params_changed = before_params != dict(state.params or {})
        if params_changed:
            self._mark_section_effective_facts_stale(section)
            if section == 'order':
                self._commit_live_analysis_sources(section)
            dirty_frf = getattr(self, '_dirty_frf_pane', None)
            if section == 'frf' and callable(dirty_frf):
                for pane_idx in range(len(state.panes)):
                    dirty_frf(state, pane_idx)
        chart_stack = getattr(self, 'chart_stack', None)
        current_mode = (
            chart_stack.current_mode() if chart_stack is not None else None
        )
        if current_mode != section:
            return
        if section == 'frf' and params_changed and hasattr(ctx, 'display_params'):
            page = self._analysis_page(section)
            display = ctx.display_params()
            for idx in range(min(page.pane_count(), len(state.panes))):
                page.pane_canvas(idx).set_display_params(display)
            return
        if (
            section in {'fft', 'fft_time', 'order'}
            and self._analysis_changed_range_axes(before_params, state.params, section)
        ):
            self._clear_analysis_view_viewports(state, self._analysis_changed_range_axes(before_params, state.params, section))
            self._render_analysis_view_from_cache(section, state)

    def _on_analysis_compute_params_changed(self, section, _params):
        """Record a compute edit without implicitly submitting a new job."""
        self._sync_active_analysis_params(section)
        self._mark_section_effective_facts_stale(section)
        if section == "order":
            self._commit_live_analysis_sources(section)

    def _effective_facts_health(self, sig, fid=None, sources=None):
        """Caller-filled health fields for an effective-facts dataclass."""
        arr = np.asarray(sig, dtype=float) if sig is not None else np.array([])
        nan_count = int(arr.size - np.count_nonzero(np.isfinite(arr))) if arr.size else 0
        finite = arr[np.isfinite(arr)] if arr.size else arr
        is_constant = bool(finite.size > 0 and float(np.ptp(finite)) == 0.0)
        time_axis = None
        fd = self.files.get(fid) if fid is not None else None
        prov = getattr(fd, "time_axis_provenance", None) if fd is not None else None
        if prov is not None and getattr(prov, "reason", None) == "auto_nonuniform":
            time_axis = prov.to_dict() if hasattr(prov, "to_dict") else dict(prov)
        fs_values = []
        for src in sources or ():
            if not src:
                continue
            sfd = self.files.get(src[0])
            if sfd is None:
                continue
            try:
                fs_v = float(sfd.fs)
            except (TypeError, ValueError, AttributeError):
                continue
            if np.isfinite(fs_v) and fs_v > 0:
                fs_values.append(fs_v)
        fs_conflict = False
        if len(fs_values) > 1:
            ref = fs_values[0]
            scale = max(abs(ref), 1.0)
            fs_conflict = any(
                abs(v - ref) > 1e-9 * max(scale, abs(v)) for v in fs_values[1:]
            )
        return {
            "nan_count": nan_count,
            "is_constant": is_constant,
            "time_axis": time_axis,
            "fs_conflict": fs_conflict,
        }, fs_values

    def _publish_analysis_effective_facts(
        self, ctx, facts, *, sig=None, fid=None, sources=(), extra_warnings=(),
    ):
        """Stamp health onto ``facts`` and push to the Inspector card."""
        if ctx is None or not hasattr(ctx, "set_effective_facts"):
            return
        if facts is None:
            ctx.clear_effective_facts()
            return
        from dataclasses import replace

        health, fs_values = self._effective_facts_health(
            sig, fid=fid, sources=sources,
        )
        health["time_axis"] = getattr(facts, "time_axis", None)
        try:
            facts = replace(facts, **health)
        except TypeError:
            pass
        warnings = list(extra_warnings)
        if getattr(facts, "fs_conflict", False) and fs_values:
            pretty = ", ".join(f"{v:g} Hz" for v in fs_values)
            warnings.append(f"多源 Fs 冲突：{pretty}")
        ctx.set_effective_facts(facts, warnings)

    def _sync_section_effective_facts(self, section, state=None):
        sync = getattr(self, f"_sync_{section}_effective_facts", None)
        if callable(sync):
            sync(state)

    def _mark_section_effective_facts_stale(self, section):
        ctx_name = "fft_time_ctx" if section == "fft_time" else f"{section}_ctx"
        ctx = getattr(self.inspector, ctx_name, None)
        marker = getattr(ctx, "mark_effective_facts_stale", None)
        if callable(marker):
            marker()

    def _analysis_changed_range_axes(self, before, after, section="fft"):
        old, new = self._analysis_xy_fingerprint(before), self._analysis_xy_fingerprint(after)
        axes = [axis for axis, start in (("x", 0), ("y", 3)) if old[start:start+3] != new[start:start+3]]
        if section == "fft" and any(before.get(key) != after.get(key) for key in ("amp_y", "amplitude_mode", "db_reference", "db_reference_mode", "unit", "unit_mode")) and "y" not in axes:
            axes.append("y")
        return tuple(axes)

    def _on_analysis_display_params_changed(self, section, _params):
        """Clear only changed axis policy; presentation redraw retains intent."""
        axes = ()
        if section in {"fft", "fft_time", "order"} and not self._applying_analysis_view and self.chart_stack.current_mode() == section:
            mgr = self.analysis_managers.get(section)
            if mgr is not None and mgr.views:
                axes = self._analysis_changed_range_axes(mgr.get(mgr.active).params, _params, section)
        state = self._sync_active_analysis_params(section)
        if state is not None and axes:
            self._clear_analysis_view_viewports(state, axes)
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
        dirty = getattr(self, "_project_dirty", None)
        if dirty is not None:
            dirty.begin_restore()
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
            if dirty is not None:
                dirty.end_restore()
        # 5. Render from cache only (spec §4: switching never auto-computes).
        if render:
            self._render_analysis_view_from_cache(section, state)
        self._sync_section_effective_facts(section, state)

    def _project_analysis_attachments(self, section, state):
        """Project one analysis View's file range onto the shared navigator."""
        invalidate = getattr(self.navigator, "invalidate_channel_filter_context", None)
        if callable(invalidate):
            invalidate()
        attached = [
            fid for fid in state.attached_file_ids if fid in self.files
        ]
        setter = getattr(self.navigator, 'set_attached_file_ids', None)
        if callable(setter):
            setter(attached)
        label = self._analysis_section_label(section)
        set_attachment_context = getattr(
            self.navigator, "set_attachment_context", None,
        )
        if callable(set_attachment_context):
            set_attachment_context(section_label=label, view_name=state.name)
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
        self._sync_section_effective_facts(section, state)

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
        holder = getattr(self, "_project_dirty", None)
        if holder is not None:
            holder.mark_user_mutation()

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

    def _analysis_time_range_draft_is_local(self, section=None, pane_idx=None):
        """Return ``(lo, hi)`` for a matching-signature user draft on one pane.

        Programmatic ``set_range_values`` is not a draft. The retired 1%
        plotted-extent heuristic must not be used. Invalid drafts are
        reported by the compute preflight, not this facade.
        """
        mode = section or self.chart_stack.current_mode()
        if not self._analysis_section_uses_time_range(mode):
            return None
        mgr = self.analysis_managers.get(mode)
        if mgr is None or not mgr.views:
            return None
        state, idx = self._analysis_range_target(mode, pane_idx=pane_idx)
        pane = state.panes[idx]
        if pane.time_range is not None:
            return None
        page = self._analysis_page(mode)
        if (
            idx == page.focused_index()
            and self.inspector.top.range_enabled()
        ):
            return None
        ctrl = self._analysis_context.time_range
        draft = ctrl.draft_for(mode, state.view_id, idx)
        if draft is None or draft.range is None or not draft.valid:
            return None
        signature = self._analysis_source_signature_for_pane(mode, pane, state)
        if draft.source_signature != signature:
            return None
        bounds = ctrl.source_bounds_for(mode, state.view_id, idx)
        if (
            bounds.display_range is not None
            and display_ranges_equal(draft.range, bounds.display_range)
        ):
            return None
        coverage = validate_requested_span(
            bounds.per_source,
            draft.range,
            bounds_status=bounds.status,
            bounds_errors=bounds.errors,
        )
        if not coverage.ok:
            return None
        return draft.range

    def _analysis_time_range_confirm_text(self, items, *, review_only):
        lines = []
        multi = len(items) > 1
        for item in items:
            span = _format_span_seconds(item.get("range"))
            display = item.get("display_range")
            kind = item.get("kind")
            prefix = (
                f"窗格 {int(item.get('pane_idx', 0)) + 1}：" if multi else ""
            )
            if kind == "invalid_enabled":
                lines.append(f"{prefix}已启用时间范围无效。")
            elif kind == "review":
                available = (
                    f"可用范围 {_format_span_seconds(display)}"
                    if display is not None
                    else "当前来源可用范围"
                )
                lines.append(f"{prefix}已启用范围 {span} 超出{available}。")
            elif kind == "invalid_draft":
                if multi:
                    lines.append(f"{prefix}{span}（草稿无效，不能直接启用）")
                else:
                    lines.append(
                        f"你调整了时间范围为 {span}，但尚未启用。"
                        "当前草稿无效，不能直接启用。"
                    )
            elif kind == "uncovered_draft":
                available = (
                    f"可用范围 {_format_span_seconds(display)}"
                    if display is not None
                    else "当前来源可用范围"
                )
                detail = "；".join(
                    str(err) for err in (item.get("errors") or ()) if err
                )
                extra = f"（{detail}）" if detail else ""
                lines.append(
                    f"{prefix}选定范围 {span} 超出{available}{extra}。"
                )
            elif multi:
                lines.append(f"{prefix}{span}")
            else:
                lines.append(
                    f"你调整了时间范围为 {span}，但尚未启用。"
                    "此次计算使用哪个范围？"
                )
        if multi and review_only:
            lines.append("使用新来源全时段，还是返回调整？")
        elif multi:
            lines.append("你调整了时间范围，但尚未启用。此次计算使用哪个范围？")
        elif review_only:
            lines.append("使用新来源全时段，还是返回调整？")
        return "\n".join(line for line in lines if line)

    def _ask_use_local_time_range(self, lo, hi, conflicts=None):
        """Modal confirm for drafts / out-of-coverage enabled ranges.

        Returns ``'local'`` / ``'full'`` / ``'adjust'`` / ``'cancel'``.
        Tests monkeypatch this seam. Default button is cancel. Full span
        is a normal role, never ``DestructiveRole``.
        """
        items = list(conflicts or ())
        if not items:
            items = [{
                "pane_idx": 0,
                "kind": "draft",
                "range": (lo, hi),
                "display_range": None,
            }]
        kinds = {item.get("kind") for item in items}
        review_only = kinds <= {"review", "invalid_enabled"}
        local_ok = kinds == {"draft"}
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(
            "已启用范围需要复核" if review_only else "未启用选定时间范围"
        )
        box.setText(self._analysis_time_range_confirm_text(
            items, review_only=review_only,
        ))
        local_btn = None
        adjust_btn = None
        if review_only:
            full_btn = box.addButton("使用新来源全时段", QMessageBox.ActionRole)
            adjust_btn = box.addButton("返回调整", QMessageBox.AcceptRole)
        else:
            local_btn = box.addButton("用选定范围", QMessageBox.AcceptRole)
            local_btn.setEnabled(bool(local_ok))
            full_btn = box.addButton("用全时段", QMessageBox.ActionRole)
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setEscapeButton(cancel_btn)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is local_btn:
            return "local"
        if clicked is full_btn:
            return "full"
        if clicked is adjust_btn:
            return "adjust"
        return "cancel"

    def _iter_analysis_compute_pane_indices(self, section, state):
        page = self._analysis_page(section)
        count = min(page.pane_count(), len(state.panes))
        if count <= 0:
            return []
        if str(section) == "frf":
            return [min(page.focused_index(), count - 1)]
        return list(range(count))

    @staticmethod
    def _pane_has_compute_source(section, pane):
        if str(section) == "frf":
            return (
                getattr(pane, "input_source", None) is not None
                and getattr(pane, "output_source", None) is not None
            )
        return bool(getattr(pane, "sources", None))

    def _analysis_compute_live_identity(self, section):
        if section == "fft":
            checked = []
            getter = getattr(self.navigator, "get_checked_channels", None)
            if callable(getter):
                for item in getter() or ():
                    if len(item) >= 2:
                        checked.append((item[0], item[1]))
            return ("fft", tuple(checked))
        if section in {"fft_time", "order"}:
            ctx = self._analysis_ctx(section)
            getter = getattr(ctx, "current_signal", None)
            sig = getter() if callable(getter) else None
            return (section, tuple(sig) if sig else None)
        if section == "frf":
            ctx = self._analysis_ctx(section)
            pair_fn = getattr(ctx, "pair", None)
            pair = pair_fn() if callable(pair_fn) else (None, None)
            inp, out = pair if pair is not None else (None, None)
            return (
                "frf",
                tuple(inp) if inp else None,
                tuple(out) if out else None,
            )
        return (section,)

    def _analysis_compute_fingerprint(self, section, state, targets):
        mgr = self.analysis_managers[section]
        return (
            str(getattr(state, "view_id", "")),
            getattr(mgr, "active", None),
            self._analysis_compute_live_identity(section),
            tuple(
                (
                    item["pane_idx"],
                    item["signature"],
                    tuple(item["sources"]),
                    item["input_source"],
                    item["output_source"],
                    item["rpm_source"],
                )
                for item in targets
            ),
        )

    def _snapshot_analysis_compute_targets(self, section):
        mgr = self.analysis_managers.get(section)
        if mgr is None or not mgr.views:
            return None
        state = mgr.get(mgr.active)
        ctrl = self._analysis_context.time_range
        targets = []
        for idx in self._iter_analysis_compute_pane_indices(section, state):
            pane = state.panes[idx]
            signature = self._analysis_source_signature_for_pane(
                section, pane, state
            )
            draft = ctrl.draft_for(section, state.view_id, idx)
            if not (
                self._pane_has_compute_source(section, pane)
                or draft is not None
                or pane.time_range is not None
            ):
                continue
            targets.append({
                "pane_idx": idx,
                "signature": signature,
                "sources": [tuple(item) for item in (pane.sources or ())],
                "input_source": getattr(pane, "input_source", None),
                "output_source": getattr(pane, "output_source", None),
                "rpm_source": getattr(pane, "rpm_source", None),
            })
        return state, targets, self._analysis_compute_fingerprint(
            section, state, targets
        )

    def _analysis_time_range_conflicts(self, section, state, targets):
        ctrl = self._analysis_context.time_range
        conflicts = []
        for target in targets:
            idx = target["pane_idx"]
            pane = state.panes[idx]
            signature = target["signature"]
            bounds = ctrl.source_bounds_for(section, state.view_id, idx)
            draft = ctrl.draft_for(section, state.view_id, idx)
            if (
                draft is not None
                and draft.source_signature == signature
                and (draft.range is None or not draft.valid)
            ):
                conflicts.append({
                    "pane_idx": idx,
                    "kind": "invalid_draft",
                    "range": draft.range,
                    "display_range": bounds.display_range,
                    "signature": signature,
                    "reason": "invalid_draft",
                    "errors": ("invalid draft range",),
                })
                continue
            enabled = pane.time_range
            if enabled is not None:
                validation = validate_requested_span(
                    bounds.per_source,
                    enabled,
                    bounds_status=bounds.status,
                    bounds_errors=bounds.errors,
                )
                if validation.reason in {"unparseable", "unordered", "missing"}:
                    conflicts.append({
                        "pane_idx": idx,
                        "kind": "invalid_enabled",
                        "range": validation.span if validation.span is not None else enabled,
                        "display_range": bounds.display_range,
                        "signature": signature,
                        "reason": validation.reason,
                        "errors": validation.errors,
                    })
                    continue
                intent = ctrl.intent_for(
                    section,
                    state.view_id,
                    idx,
                    enabled_range=enabled,
                    source_signature=signature,
                )
                if intent.needs_review or not validation.ok:
                    conflicts.append({
                        "pane_idx": idx,
                        "kind": "review",
                        "range": validation.span,
                        "display_range": bounds.display_range,
                        "signature": signature,
                        "reason": validation.reason,
                        "errors": validation.errors or intent.errors,
                    })
                continue
            if draft is None or draft.source_signature != signature:
                continue
            if (
                bounds.display_range is not None
                and display_ranges_equal(draft.range, bounds.display_range)
            ):
                continue
            validation = validate_requested_span(
                bounds.per_source,
                draft.range,
                bounds_status=bounds.status,
                bounds_errors=bounds.errors,
            )
            if not validation.ok:
                conflicts.append({
                    "pane_idx": idx,
                    "kind": "uncovered_draft",
                    "range": draft.range,
                    "display_range": bounds.display_range,
                    "signature": signature,
                    "reason": validation.reason,
                    "errors": validation.errors,
                })
                continue
            conflicts.append({
                "pane_idx": idx,
                "kind": "draft",
                "range": draft.range,
                "display_range": bounds.display_range,
                "signature": signature,
                "reason": "ok",
                "errors": (),
            })
        return conflicts

    def _freeze_analysis_time_range_candidates(
        self, section, state, conflicts, choice,
    ):
        """Validate every target before the first pane write."""
        ctrl = self._analysis_context.time_range
        candidates = []
        for item in conflicts:
            idx = item["pane_idx"]
            pane = state.panes[idx]
            signature = item.get("signature")
            if signature is None:
                signature = self._analysis_source_signature_for_pane(
                    section, pane, state
                )
            bounds = ctrl.source_bounds_for(section, state.view_id, idx)
            if choice == "local":
                validation = validate_requested_span(
                    bounds.per_source,
                    item.get("range"),
                    bounds_status=bounds.status,
                    bounds_errors=bounds.errors,
                )
                if not validation.ok:
                    return None
                candidates.append({
                    "pane_idx": idx,
                    "pane": pane,
                    "signature": signature,
                    "new_range": validation.span,
                    "action": "enable",
                })
                continue
            if bounds.status == "unavailable":
                return None
            candidates.append({
                "pane_idx": idx,
                "pane": pane,
                "signature": signature,
                "new_range": None,
                "action": "full",
            })
        return candidates

    def _commit_analysis_time_range_choice(
        self, section, state, conflicts, choice,
    ):
        candidates = self._freeze_analysis_time_range_candidates(
            section, state, conflicts, choice,
        )
        if candidates is None:
            return False
        ctrl = self._analysis_context.time_range
        dirty = getattr(self, "_dirty_frf_pane", None)
        frf_changed = []
        for item in candidates:
            pane = item["pane"]
            idx = item["pane_idx"]
            signature = item["signature"]
            before = pane.time_range
            if item["action"] == "enable":
                pane.time_range = item["new_range"]
                ctrl.note_enabled(
                    section, state.view_id, idx, item["new_range"], signature
                )
            else:
                pane.time_range = None
                ctrl.convert_to_full(section, state.view_id, idx)
            if section == "frf" and pane.time_range != before:
                frf_changed.append(idx)
        if section == "frf" and frf_changed and callable(dirty):
            first = True
            for idx in frf_changed:
                dirty(state, idx, clear_effective=first)
                first = False
        self._apply_analysis_time_range(section, state)
        return True

    def _offer_analysis_time_range_before_compute(self, section):
        """User-click preflight: flush, freeze targets, one confirm, commit.

        Restore auto-recompute and Batch must not call this. Workers keep
        consuming ``pane.time_range`` after the transaction.
        """
        if not self._analysis_section_uses_time_range(section):
            return True
        self._flush_pending_analysis_range_edit(section)
        snapshot = self._snapshot_analysis_compute_targets(section)
        if snapshot is None:
            return True
        state, targets, fingerprint = snapshot
        conflicts = self._analysis_time_range_conflicts(section, state, targets)
        if not conflicts:
            return True
        first = conflicts[0].get("range") or (0.0, 0.0)
        try:
            lo, hi = float(first[0]), float(first[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = 0.0, 0.0
        choice = self._ask_use_local_time_range(lo, hi, conflicts)
        if choice in (None, "cancel", "adjust"):
            return False
        now = self._snapshot_analysis_compute_targets(section)
        if now is None or now[2] != fingerprint:
            return False
        state = now[0]
        if choice == "local":
            if any(item.get("kind") != "draft" for item in conflicts):
                return False
            return self._commit_analysis_time_range_choice(
                section, state, conflicts, "local"
            )
        if choice == "full":
            return self._commit_analysis_time_range_choice(
                section, state, conflicts, "full"
            )
        return False

    def _analysis_restore_time_range_block_reason(self, section, state, pane_idx):
        """Reason to skip restore recompute, or ``None``.

        Ignores drafts and never opens a confirm dialog. Invalid or
        out-of-coverage enabled spans must not silently become full.
        """
        if not self._analysis_section_uses_time_range(section):
            return None
        pane = state.panes[pane_idx]
        if pane.time_range is None:
            return None
        parsed, valid = parse_span(pane.time_range)
        if not valid:
            return "已启用时间范围无效，已停止自动计算"
        ctrl = self._analysis_context.time_range
        bounds = ctrl.source_bounds_for(section, state.view_id, pane_idx)
        if bounds.status == "unavailable":
            return "当前来源时间范围不可用，已停止自动计算"
        if not enabled_covers_sources(bounds.per_source, parsed):
            return "已启用时间范围超出当前来源，已停止自动计算"
        return None

    def _resolve_job_time_range(self, section, time_range, pane_idx=None):
        """Workers consume ``pane.time_range``, never an unchecked spin draft."""
        from ._sentinel import _INSPECTOR_TIME_RANGE
        if time_range is not _INSPECTOR_TIME_RANGE:
            return time_range
        return self._pane_time_range_for(section, pane_idx)

    def _analysis_range_target(self, section, state=None, pane_idx=None):
        mgr = self.analysis_managers[section]
        if state is None:
            state = mgr.get(mgr.active)
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), max(len(state.panes) - 1, 0))
        return state, idx

    def _axis_facts_for_sources(self, sources):
        ctx = getattr(self, "_analysis_context", None)
        getter = getattr(ctx, "axis_facts_for_sources", None)
        if callable(getter):
            return getter(sources)
        from .analysis_time_range import axis_facts_from_files
        return axis_facts_from_files(getattr(self, "files", None) or {}, sources)

    def _analysis_source_signature_for_pane(self, section, pane, state=None):
        sources = list(getattr(pane, "sources", None) or ())
        input_source = getattr(pane, "input_source", None)
        output_source = getattr(pane, "output_source", None)
        rpm_source = getattr(pane, "rpm_source", None)
        named = list(sources)
        for extra in (input_source, output_source, rpm_source):
            if extra is not None:
                named.append(extra)
        rpm_mode = None
        if str(section) == "order":
            if state is not None:
                rpm_mode = (getattr(state, "params", None) or {}).get("rpm_mode")
            if rpm_mode is None:
                ctx = self._analysis_ctx(section)
                getter = getattr(ctx, "rpm_mode", None)
                rpm_mode = getter() if callable(getter) else None
        return make_source_signature(
            section,
            sources=sources,
            rpm_mode=rpm_mode,
            rpm_source=rpm_source,
            input_source=input_source,
            output_source=output_source,
            axis_facts=self._axis_facts_for_sources(named),
        )

    def _silent_project_range_values(self, lo, hi):
        top = self.inspector.top
        try:
            lo_f = float(lo)
            hi_f = float(hi)
        except (TypeError, ValueError):
            return
        cur_min = min(top.spin_start.minimum(), top.spin_end.minimum())
        cur_max = max(top.spin_start.maximum(), top.spin_end.maximum())
        # Expand only so a longer source is not clamped back to a stale max
        # (R1 leftover 43.061). Do not shrink to the source span.
        top.set_range_limits(min(cur_min, lo_f, hi_f), max(cur_max, lo_f, hi_f))
        top.set_range_values(lo_f, hi_f)

    def _project_top_from_time_range_intent(self, section, intent, *, enabled=False):
        kind = intent.kind
        top = self.inspector.top
        if kind == "unavailable":
            self._set_top_range_enabled_silently(False, mode=section)
            top.set_range_values(0.0, 0.0)
        elif kind == "enabled":
            if intent.range is not None:
                self._silent_project_range_values(*intent.range)
            self._set_top_range_enabled_silently(True, mode=section)
        elif kind == "draft":
            if intent.range is not None:
                self._silent_project_range_values(*intent.range)
            self._set_top_range_enabled_silently(False, mode=section)
        elif kind == "invalid":
            if intent.range is not None:
                self._silent_project_range_values(*intent.range)
            self._set_top_range_enabled_silently(bool(enabled), mode=section)
        else:
            self._set_top_range_enabled_silently(False, mode=section)
            if intent.display_range is not None:
                self._silent_project_range_values(*intent.display_range)
        top.set_range_intent_status(
            kind,
            needs_review=bool(getattr(intent, "needs_review", False)),
            errors=tuple(getattr(intent, "errors", ()) or ()),
            notes=tuple(getattr(intent, "notes", ()) or ()),
        )

    def _project_committed_time_range_intent(self, section, intent):
        if intent is None or not self._analysis_section_uses_time_range(section):
            return
        state, idx = self._analysis_range_target(section)
        pane = state.panes[idx]
        self._project_top_from_time_range_intent(
            section, intent, enabled=pane.time_range is not None,
        )

    def _apply_user_range_commit(self, span):
        if getattr(self, "_applying_analysis_view", False):
            return None
        if getattr(self, "_applying_view", False):
            return None
        mode = self.chart_stack.current_mode()
        if mode not in getattr(self, "analysis_managers", {}):
            return None
        intent = self._commit_analysis_user_range(mode, span)
        self._project_committed_time_range_intent(mode, intent)
        return intent

    def _commit_analysis_user_range(
        self, section, span, *, state=None, pane_idx=None,
    ):
        if not self._analysis_section_uses_time_range(section):
            return None
        state, idx = self._analysis_range_target(section, state, pane_idx)
        pane = state.panes[idx]
        view_id = state.view_id
        signature = self._analysis_source_signature_for_pane(section, pane, state)
        ctrl = self._analysis_context.time_range
        intent = ctrl.apply_user_edit(section, view_id, idx, span, signature)
        parsed, valid = parse_span(span)
        if not valid:
            return intent
        # Checkbox-on is owned by ``_enable_focused_analysis_time_range``.
        # A just-checked box during flush must not write the pane here, or
        # enable would then treat "no draft" as source-full and overwrite.
        if pane.time_range is None:
            return intent
        before = pane.time_range
        pane.time_range = parsed
        intent = ctrl.note_enabled(
            section, view_id, idx, pane.time_range, signature,
        )
        if section == "frf" and pane.time_range != before:
            dirty = getattr(self, "_dirty_frf_pane", None)
            if callable(dirty):
                dirty(state, idx, clear_effective=True)
        return intent

    def _flush_pending_analysis_range_edit(
        self, section=None, *, state=None, pane_idx=None,
    ):
        top = getattr(getattr(self, "inspector", None), "top", None)
        flush = getattr(top, "flush_pending_range_edit", None)
        if not callable(flush):
            return None
        query_fn = getattr(top, "query_range_edit", None)
        query = query_fn() if callable(query_fn) else None
        pending = flush(emit=False)
        mode = section or self.chart_stack.current_mode()
        if mode not in getattr(self, "analysis_managers", {}):
            return pending
        if query is not None and getattr(query, "status", None) == "invalid_edit":
            self._commit_analysis_user_range(
                mode, query.span, state=state, pane_idx=pane_idx,
            )
            return None
        if pending is None:
            return None
        self._commit_analysis_user_range(
            mode, pending, state=state, pane_idx=pane_idx,
        )
        return pending

    def _convert_analysis_time_range_to_full(
        self, section, state=None, pane_idx=None,
    ):
        state, idx = self._analysis_range_target(section, state, pane_idx)
        state.panes[idx].time_range = None
        self._analysis_context.time_range.convert_to_full(
            section, state.view_id, idx,
        )
        self._apply_analysis_time_range(section, state)

    def _enable_focused_analysis_time_range(self, section, state, pane_idx):
        """Checkbox on: valid draft, else exact source full. Invalid stays draft."""
        self._flush_pending_analysis_range_edit(
            section, state=state, pane_idx=pane_idx,
        )
        pane = state.panes[pane_idx]
        ctrl = self._analysis_context.time_range
        view_id = state.view_id
        draft = ctrl.draft_for(section, view_id, pane_idx)
        if draft is not None and (not draft.valid or draft.range is None):
            self._set_top_range_enabled_silently(False, mode=section)
            intent = ctrl.intent_for(
                section,
                view_id,
                pane_idx,
                enabled_range=pane.time_range,
                source_signature=draft.source_signature,
            )
            self._project_top_from_time_range_intent(
                section, intent, enabled=False,
            )
            return
        if draft is not None and draft.valid and draft.range is not None:
            bounds = ctrl.source_bounds_for(section, view_id, pane_idx)
            coverage = validate_requested_span(
                bounds.per_source,
                draft.range,
                bounds_status=bounds.status,
                bounds_errors=bounds.errors,
            )
            if not coverage.ok:
                self._set_top_range_enabled_silently(False, mode=section)
                intent = ctrl.intent_for(
                    section,
                    view_id,
                    pane_idx,
                    enabled_range=pane.time_range,
                    source_signature=draft.source_signature,
                )
                self._project_top_from_time_range_intent(
                    section, intent, enabled=False,
                )
                return
            pane.time_range = draft.range
            intent = ctrl.note_enabled(
                section, view_id, pane_idx, draft.range, draft.source_signature,
            )
            self._project_top_from_time_range_intent(
                section, intent, enabled=True,
            )
            return
        if pane.time_range is not None:
            signature = self._analysis_source_signature_for_pane(
                section, pane, state
            )
            intent = ctrl.intent_for(
                section,
                view_id,
                pane_idx,
                enabled_range=pane.time_range,
                source_signature=signature,
            )
            self._project_top_from_time_range_intent(
                section, intent, enabled=True,
            )
            return
        bounds = ctrl.source_bounds_for(section, view_id, pane_idx)
        parsed, valid = parse_span(bounds.display_range)
        if valid:
            coverage = validate_requested_span(
                bounds.per_source,
                parsed,
                bounds_status=bounds.status,
                bounds_errors=bounds.errors,
            )
            if not coverage.ok:
                self._set_top_range_enabled_silently(False, mode=section)
                intent = ctrl.intent_for(section, view_id, pane_idx)
                self._project_top_from_time_range_intent(
                    section, intent, enabled=False,
                )
                return
            pane.time_range = parsed
            signature = self._analysis_source_signature_for_pane(
                section, pane, state
            )
            intent = ctrl.note_enabled(
                section, view_id, pane_idx, parsed, signature,
            )
            self._project_top_from_time_range_intent(
                section, intent, enabled=True,
            )
            return
        pane.time_range = None
        self._set_top_range_enabled_silently(False, mode=section)
        intent = ctrl.intent_for(section, view_id, pane_idx)
        self._project_top_from_time_range_intent(
            section, intent, enabled=False,
        )

    def _capture_analysis_time_range(self, section, state, pane_idx=None):
        if not self._analysis_section_uses_time_range(section):
            return
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        self._flush_pending_analysis_range_edit(
            section, state=state, pane_idx=idx,
        )
        pane = state.panes[idx]
        top = self.inspector.top
        if top.range_enabled():
            # Already-enabled model keeps its exact tuple. Do not write
            # display-rounded spin.value() back. set_range_from_span arms
            # the checkbox without a model yet — persist that span once.
            if pane.time_range is not None:
                return
            parsed, valid = parse_span(top.range_values())
            if not valid:
                return
            pane.time_range = parsed
            signature = self._analysis_source_signature_for_pane(
                section, pane, state
            )
            self._analysis_context.time_range.note_enabled(
                section, state.view_id, idx, pane.time_range, signature,
            )
            return
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

    def _sync_analysis_time_range_after_sources(
        self, section, state, pane_idx=None, *, project=True,
    ):
        """Record a pane source signature. Project only the focused visible pane.

        Signature changes drop a stale draft and flag enabled spans that the
        new source does not cover. Never clamps ``pane.time_range`` and never
        opens the compute confirm dialog.
        """
        if not self._analysis_section_uses_time_range(section):
            return None
        ctrl = getattr(getattr(self, "_analysis_context", None), "time_range", None)
        if ctrl is None or not getattr(state, "panes", None):
            return None
        if pane_idx is None:
            page = self._analysis_page(section)
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        signature = self._analysis_source_signature_for_pane(section, pane, state)
        intent = ctrl.on_source_signature_changed(
            section,
            state.view_id,
            idx,
            signature,
            enabled_range=pane.time_range,
        )
        if not project:
            return intent
        if self.chart_stack.current_mode() != section:
            return intent
        page = self._analysis_page(section)
        focused = min(page.focused_index(), len(state.panes) - 1)
        if idx != focused:
            return intent
        self._project_top_from_time_range_intent(
            section, intent, enabled=pane.time_range is not None,
        )
        return intent

    def _commit_live_analysis_sources(self, section, state=None, pane_idx=None):
        """Capture the live source widgets and project the focused pane."""
        if getattr(self, "_applying_analysis_view", False):
            return
        if getattr(self, "_opening_project", False):
            return
        if getattr(self, "_restoring_project", False):
            return
        if not self._analysis_section_uses_time_range(section):
            return
        if self.chart_stack.current_mode() != section:
            return
        mgr = self.analysis_managers[section]
        if not mgr.views:
            return
        if state is None:
            state = mgr.get(mgr.active)
        self._capture_analysis_sources(section, state, pane_idx=pane_idx)
        self._apply_analysis_time_range(section, state)

    def _refresh_analysis_time_range_after_source_loss(
        self, section=None, state=None,
    ):
        """Re-validate every affected pane after a file/channel drop."""
        ctrl = getattr(getattr(self, "_analysis_context", None), "time_range", None)
        if ctrl is None:
            return
        if section is not None and state is not None:
            for idx in range(len(getattr(state, "panes", ()) or ())):
                self._sync_analysis_time_range_after_sources(
                    section, state, idx, project=False,
                )
            if self.chart_stack.current_mode() == section:
                self._apply_analysis_time_range(section, state)
            return
        for sec, mgr in (getattr(self, "analysis_managers", None) or {}).items():
            if not self._analysis_section_uses_time_range(sec):
                continue
            for view in mgr.views:
                for idx in range(len(getattr(view, "panes", ()) or ())):
                    self._sync_analysis_time_range_after_sources(
                        sec, view, idx, project=False,
                    )
        mode = self.chart_stack.current_mode()
        if mode in (getattr(self, "analysis_managers", None) or {}):
            mgr = self.analysis_managers[mode]
            if mgr.views:
                self._apply_analysis_time_range(mode, mgr.get(mgr.active))

    def _apply_analysis_time_range(self, section, state):
        if not self._analysis_section_uses_time_range(section):
            return
        self._sync_analysis_time_range_after_sources(
            section, state, project=True,
        )

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
            self._sync_analysis_time_range_after_sources(
                section, state, idx, project=False,
            )
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
        self._sync_analysis_time_range_after_sources(
            section, state, idx, project=False,
        )

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
            # Auto-nfft without samples: do not disguise nfft_preview as an
            # actual NFFT. Keep nfft None and put intent on the facts signature
            # so different targets still miss, and int(None) is no longer used.
            p_fb = dict(p)
            auto_unresolved = (
                p_fb.get('nfft_mode') == 'auto'
                and p_fb.get('nfft_effective') is None
                and p_fb.get('nfft') is None
            )
            if auto_unresolved and p_fb.get('nfft_facts_signature') is None:
                from ...signal import nfft_facts_signature, requested_auto_nfft
                from ...signal.analysis_defaults import (
                    AUTO_NFFT_POLICY_VERSION,
                    DEFAULT_FFT_T_WIN_S,
                )
                t_win = p_fb.get('t_win_s', DEFAULT_FFT_T_WIN_S)
                requested = p_fb.get('nfft_preview')
                if requested is None:
                    try:
                        requested = requested_auto_nfft(
                            p_fb.get('fs'), t_win, purpose='fft_time',
                        )
                    except (TypeError, ValueError):
                        requested = None
                p_fb['nfft_facts_signature'] = nfft_facts_signature(
                    nfft_mode='auto',
                    policy_version=AUTO_NFFT_POLICY_VERSION,
                    t_win_s=t_win,
                    requested_nfft=requested,
                    effective_nfft=None,
                    n_samples=None,
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
        self._sync_section_effective_facts(section, state)

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
