"""OrderMixin: COT Order analysis worker dispatch and render methods."""

import numpy as np

from PyQt5.QtWidgets import QMessageBox

from ... import db_reference
from ...signal import (
    assess_speed_for_order,
    order_angle_sample_count,
    resolve_order_nfft,
    revolutions_from_rpm,
)
from ...signal.analysis_defaults import DEFAULT_ANALYSIS_WINDOW, DEFAULT_ORDER_RES
from ...signal.spectrogram import SpectrogramAnalyzer
from ..pg_canvas.heatmap_canvas import DEFAULT_HEATMAP_CMAP, DEFAULT_HEATMAP_INTERP
from ...qt_analysis_shared import amplitude_mode_is_db
from ..compute_feedback import ComputeOutcome
from ._sentinel import _INSPECTOR_TIME_RANGE
from .ultraview_coordinator import notify_ultraview_plot


class OrderMixin:
    """Domain adapter for COT Order input collection and rendering.

    ``AnalysisJobService`` owns worker lifecycle, FIFO queueing and progress;
    every job carries its own cache/render context back to this mixin.
    """

    def _order_sig_for(self, source, time_range=_INSPECTOR_TIME_RANGE):
        """Fetch + range-gate an explicit Order signal source ``(fid, ch)``.
        Returns ``(t, sig)`` or ``(None, None)``. V7b: the split queue must
        fetch a NON-focused pane's source, not the inspector selection."""
        if not source:
            return None, None
        fid, ch = source
        if fid not in self.files:
            return None, None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None, None
        t = fd.time_array
        sig = fd.data[ch].values
        if (
            time_range is _INSPECTOR_TIME_RANGE
            and self.inspector.top.range_enabled()
        ):
            time_range = self.inspector.top.range_values()
        if time_range is _INSPECTOR_TIME_RANGE:
            time_range = None
        if time_range is not None and t is not None:
            t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return t, sig

    def _order_rpm_for(self, rpm_source, n, time_range=_INSPECTOR_TIME_RANGE,
                       t_sig=None, *, params=None):
        """Fetch + range-gate + scale an explicit Order RPM source. ``n`` is
        the signal length the rpm must match. Returns the scaled rpm array or
        ``None`` (caller skips the pane). The scale factor is the current
        inspector ``rpm_factor`` — shared across panes like the COT params.

        Multi-rate support: when the (range-gated) motor-speed channel does
        NOT match the signal length ``n`` and a signal time axis ``t_sig`` is
        supplied, the motor speed is interpolated onto ``t_sig`` (e.g. a 1 kHz
        speed channel upsampled to a 48 kHz signal axis). This NEVER downsamples
        the wideband signal — it only raises the speed to the signal's rate so
        the COT core sees three equal-length, same-time-base arrays. The motor
        speed's own time axis must be strictly increasing; otherwise alignment
        is unsafe and the pane is skipped (``None``), matching the prior
        length-mismatch behaviour. EPS: ``rpm`` is the motor speed (order base).
        """
        ctx = self.inspector.order_ctx
        p = params if isinstance(params, dict) else None
        rpm_mode = None if p is None else p.get('rpm_mode')
        if rpm_mode is None:
            rpm_mode = getattr(ctx, 'rpm_mode', lambda: 'channel')()
        if rpm_mode == 'manual':
            if p is not None and 'manual_rpm' in p:
                value = float(p['manual_rpm'])
            else:
                value = float(ctx.manual_rpm())
            return np.full(int(n), value, dtype=float)
        if not rpm_source:
            return None
        fid, ch = rpm_source
        if fid not in self.files:
            return None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None
        if p is not None and 'rpm_factor' in p:
            factor = p['rpm_factor']
        else:
            factor = self.inspector.order_ctx.rpm_factor()
        rpm = fd.data[ch].values.copy() * factor
        t_rpm = fd.time_array
        if (
            time_range is _INSPECTOR_TIME_RANGE
            and self.inspector.top.range_enabled()
        ):
            time_range = self.inspector.top.range_values()
        if time_range is _INSPECTOR_TIME_RANGE:
            time_range = None
        if time_range is not None and t_rpm is not None:
            t_rpm, rpm = self._mask_time_range(
                t_rpm, rpm, time_range=time_range)
        if len(rpm) != n:
            aligned = self._align_rpm_to_signal_axis(rpm, t_rpm, t_sig, n)
            if aligned is None:
                return None
            return aligned
        return rpm

    @staticmethod
    def _align_rpm_to_signal_axis(rpm, t_rpm, t_sig, n):
        """Interpolate motor speed ``rpm`` (on its own axis ``t_rpm``) onto the
        signal time axis ``t_sig`` so the result is length ``n``. Returns the
        aligned array, or ``None`` when alignment is unsafe (missing/degenerate
        time axes, or either axis not strictly increasing). Pure upsample/
        resample of the speed channel — the signal is never touched.

        Same-source files share the time origin and overlapping span, so
        ``np.interp`` (which clamps to endpoint values outside the range) is
        safe without extrapolation here.
        """
        if t_sig is None or t_rpm is None:
            return None
        t_sig_arr = np.asarray(t_sig, dtype=float).reshape(-1)
        t_rpm_arr = np.asarray(t_rpm, dtype=float).reshape(-1)
        rpm_arr = np.asarray(rpm, dtype=float).reshape(-1)
        if t_sig_arr.size != n or t_rpm_arr.size != rpm_arr.size:
            return None
        if t_rpm_arr.size < 2 or t_sig_arr.size < 2:
            return None
        if not np.all(np.isfinite(t_rpm_arr)) or not np.all(np.isfinite(t_sig_arr)):
            return None
        # Both the source (xp) and the query (x) axes must be strictly
        # increasing for np.interp to be well-defined / monotone-safe.
        if np.any(np.diff(t_rpm_arr) <= 0) or np.any(np.diff(t_sig_arr) <= 0):
            return None
        aligned = np.interp(t_sig_arr, t_rpm_arr, rpm_arr)
        if aligned.size != n:
            return None
        return aligned

    # Revolution counting and the angle-domain sample count are pure numerics
    # shared with the batch auto-NFFT resolver, so they live in
    # ``signal.adaptive``.  These two names stay as thin delegations because
    # they are the window-side contract the inspector preview provider and the
    # existing tests call.
    _order_revolutions = staticmethod(revolutions_from_rpm)
    _order_angle_sample_count = staticmethod(order_angle_sample_count)

    def _order_preview_revs(self):
        """Revolution count for the inspector auto-NFFT preview, or ``None``.

        Pull-based hook registered via ``OrderContextual.set_auto_nfft_provider``:
        fetches the currently selected order signal + RPM (gated to the inspector
        time range, mirroring ``_order_effective_params_for_source``) and returns
        total revolutions, so the displayed 自动(N) tracks ``resolve_order_nfft``
        instead of the data-blind ``samples_per_rev / order_res`` upper bound.
        Returns ``None`` when no usable selection/data exists (the preview then
        falls back to the naive estimate). Never raises — it feeds a paint path.
        """
        try:
            t, sig = self._order_sig_for(self.inspector.order_ctx.current_signal())
            if sig is None or len(sig) < 2:
                return None
            rpm = self._order_rpm_for(
                self.inspector.order_ctx.current_rpm(), len(sig), t_sig=t
            )
            if rpm is None:
                return None
            fs = float(self.inspector.order_ctx.fs())
            t_arr = np.asarray(t, dtype=float) if t is not None else np.array([])
            if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
                t_arr = np.arange(len(sig), dtype=float) / fs
            revs = self._order_revolutions(rpm, t_arr)
            return revs if revs > 0.0 else None
        except Exception:
            return None

    @staticmethod
    def _resolve_order_effective_params(p, rpm, t):
        """Return COT params with a concrete NFFT for auto mode."""
        out = dict(p)
        nfft = out.get('nfft')
        auto = (
            nfft is None
            or out.get('nfft_mode') == 'auto'
            or str(nfft) == '自动'
        )
        samples_per_rev = int(out.get('samples_per_rev', 256))
        out['samples_per_rev'] = samples_per_rev
        if auto:
            n_angle = order_angle_sample_count(
                samples_per_rev,
                rpm,
                t,
            )
            effective = resolve_order_nfft(
                samples_per_rev,
                out.get('order_res', DEFAULT_ORDER_RES),
                n_angle,
                overlap=0.75,
            )
            out['nfft'] = int(effective)
            out['nfft_effective'] = int(effective)
            out['nfft_mode'] = 'auto'
            out['n_angle_samples'] = int(n_angle)
        else:
            effective = int(nfft)
            out['nfft'] = effective
            out['nfft_effective'] = effective
            out['nfft_mode'] = 'fixed'
        return out

    @staticmethod
    def _order_compute_cache_params(p, rpm_source, time_range):
        nfft = p.get('nfft_effective', p.get('nfft'))
        if nfft is None:
            nfft = p.get('nfft_preview') or 256
        rpm_mode = p.get('rpm_mode', 'channel')
        # 规约：凡进入 COT 计算的用户可调参数都必须在此登记，否则改了不刷新。
        # window is a COTParams field consumed by COTOrderAnalyzer.compute
        # (it builds the analysis window from it); registering it here keeps
        # the key field-aligned with the dataclass so a window change forces a
        # recompute instead of reusing a result built with the old window.
        return {
            'nfft': int(nfft),
            'nfft_mode': p.get('nfft_mode', 'fixed'),
            'window': p.get('window', DEFAULT_ANALYSIS_WINDOW),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': p.get('samples_per_rev'),
            'rpm_factor': p.get('rpm_factor'),
            'rpm_mode': rpm_mode,
            'manual_rpm': (
                float(p.get('manual_rpm', 1000.0))
                if rpm_mode == 'manual'
                else None
            ),
            'fs': p.get('fs'),
            'weighting': str(p.get('weighting', 'None')),
            'rpm_source': (
                None
                if rpm_mode == 'manual'
                else list(rpm_source) if rpm_source else None
            ),
            'time_range': time_range,
        }

    def _order_analysis_cache_key(self, fid, ch, p, rpm_source, time_range):
        return self.analysis_caches['order'].make_key(
            fid,
            ch,
            self._order_compute_cache_params(p, rpm_source, time_range),
        )

    def _order_effective_params_for_source(self, p, fid, ch, rpm_source, time_range):
        t, sig = self._order_sig_for((fid, ch), time_range=time_range)
        if sig is None or len(sig) < 100:
            return None
        rpm = self._order_rpm_for(
            rpm_source, len(sig), time_range=time_range, t_sig=t, params=p)
        if rpm is None:
            return None
        fs = p.get('fs') or self.inspector.order_ctx.fs()
        t_arr = np.asarray(t, dtype=float) if t is not None else np.array([])
        if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
            t_arr = np.arange(len(sig), dtype=float) / float(fs)
        return self._resolve_order_effective_params(p, rpm, t_arr)

    def _warn_if_order_speed_unsuitable(self, rpm):
        ok, message = assess_speed_for_order(rpm)
        if ok:
            return True
        self.toast(message, "warning")
        self.statusBar.showMessage(message)
        return False

    def _recompute_restored_order_view(self, view_id):
        """Fill the Order cache from persisted panes; plot only if active."""
        state = self._analysis_state_by_id("order", view_id)
        if state is None:
            return
        mgr = self.analysis_managers["order"]
        is_active = mgr.get(mgr.active) is state
        plot_live = is_active and self.chart_stack.current_mode() == "order"
        page = self._analysis_page("order")
        cache = self.analysis_caches["order"]
        jobs = []
        for pane_idx, pane in enumerate(state.panes):
            sources = pane.sources
            if not sources:
                continue
            fid, ch = sources[0]
            rpm_source = pane.rpm_source
            built = self._build_order_job(
                pane_idx, fid, ch, rpm_source, state=state, warn=False
            )
            if built is None:
                continue
            _job, ctx = built
            analysis_key = ctx.get("analysis_key")
            cached = cache.get(analysis_key) if analysis_key is not None else None
            if cached is not None:
                self._store_analysis_result(
                    "order", state.view_id, pane_idx, analysis_key, cached
                )
                if plot_live and pane_idx < page.pane_count():
                    self._render_order_on(
                        page.pane_canvas(pane_idx), cached, source=(fid, ch)
                    )
                continue
            jobs.append(built)
        if jobs:
            self._start_order_batch(jobs)

    def do_order_time(self):
        """Compute the WHOLE active Order view — every pane (V7b).

        Each pane carries one signal source ``(fid, ch)`` plus its own
        ``rpm_source``. For every pane we build the analysis cache key and
        either render a cache HIT onto that pane's canvas immediately, or
        submit a context-carrying service job. The focused pane is submitted
        first; a single (non-split) pane yields one job.

        Re-entry while a worker is running drops the whole new request with
        ``正在计算…``. A pane whose source/rpm is unfetchable is skipped
        without aborting the queue.
        """
        # V7 Step 5: capture the active Order view (params + per-pane sources +
        # rpm_source) so a later view switch renders from analysis_caches.
        if not self._offer_analysis_time_range_before_compute('order'):
            return
        self._capture_active_analysis_view('order')
        # Preserve the established UI policy: a second click reports busy and
        # drops rather than implicitly replacing the active batch.
        if self._analysis_jobs.is_running('order'):
            self._emit_compute_feedback(
                ComputeOutcome(),
                busy=True,
                section_label="时间-阶次",
            )
            return
        self._order_outcome = None
        mgr = self.analysis_managers['order']
        state = mgr.get(mgr.active)
        page = self._analysis_page('order')
        cache = self.analysis_caches['order']

        focus = page.focused_index()
        pane_order = sorted(
            range(min(page.pane_count(), len(state.panes))),
            key=lambda i: (i != focus, i),
        )
        jobs = []
        any_source = False
        outcome = ComputeOutcome()
        self._order_outcome = outcome
        for pane_idx in pane_order:
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_source = True
            fid, ch = sources[0]
            rpm_source = state.panes[pane_idx].rpm_source
            analysis_key = self._analysis_cache_key(
                'order', fid, ch,
                rpm_source=tuple(rpm_source) if rpm_source else None,
                pane_idx=pane_idx)
            cached = cache.get(analysis_key)
            if cached is not None:
                self._store_analysis_result(
                    'order', state.view_id, pane_idx, analysis_key, cached)
                self._render_order_on(
                    page.pane_canvas(pane_idx), cached, source=(fid, ch))
                outcome.cached += 1
            else:
                built = self._build_order_job(pane_idx, fid, ch, rpm_source)
                jobs.append(built if built is not None else (None, {'pane_idx': pane_idx}))

        if not jobs:
            if not any_source:
                self._order_outcome = None
                # No captured pane source → legacy inspector-selection path so
                # the standalone-signal UX + existing tests are unchanged.
                self._do_order_time_single()
                return
            self._emit_compute_feedback(outcome, section_label="时间-阶次")
            self._order_outcome = None
            return

        self._start_order_batch(jobs)

    def _do_order_time_single(self):
        """Legacy single-source Order path: compute the inspector's selected
        signal/rpm onto the primary canvas. Kept for the standalone-signal UX
        and the pre-V7b tests."""
        sig_data = self.inspector.order_ctx.current_signal()
        rpm_data = self.inspector.order_ctx.current_rpm()
        if not sig_data:
            self.toast("请选择有效信号", "warning")
            return
        page = self._analysis_page('order')
        built = self._build_order_job(
            page.focused_index(), sig_data[0], sig_data[1],
            tuple(rpm_data) if rpm_data else None,
        )
        if built is None:
            self.inspector.order_ctx.set_progress("")
            return
        self._order_outcome = None
        self._start_order_batch([built])

    def _start_order_batch(self, jobs):
        total = len(jobs)
        if self._analysis_jobs.progress_token('order') is None:
            self._analysis_jobs.set_progress_token(
                'order',
                self._begin_compute_progress(
                    "阶次 1/%d" % total,
                    total=1000,
                    process_events=False,
                ),
            )
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")
        self._analysis_jobs.submit_batch('order', jobs)

    def _finish_order_outcome_feedback(self):
        outcome = getattr(self, '_order_outcome', None)
        if outcome is None:
            return
        self._emit_compute_feedback(outcome, section_label="时间-阶次")
        self._order_outcome = None

    def _build_order_job(self, pane_idx, fid, ch, rpm_source, *, state=None,
                         warn=True):
        """Prepare one COT job and its immutable render/cache context."""
        from ...signal.order_cot import COTOrderAnalyzer, COTParams
        if state is not None:
            pane = state.panes[pane_idx]
            time_range = self._normalize_analysis_time_range(pane.time_range)
            op = self._compute_params_overlay_state('order', state)
            view_id = state.view_id
        else:
            time_range = self._pane_time_range_for('order', pane_idx)
            op = dict(self.inspector.order_ctx.compute_params())
            view_id = self.analysis_managers['order'].get(
                self.analysis_managers['order'].active
            ).view_id
        t, sig = self._order_sig_for((fid, ch), time_range=time_range)
        if sig is None:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("源通道缺失")
            return None
        if len(sig) < 100:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("信号过短")
            return None
        rpm = self._order_rpm_for(
            rpm_source, len(sig), time_range=time_range, t_sig=t, params=op)
        if rpm is None:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("缺转速")
            return None
        if warn:
            self._warn_if_order_speed_unsuitable(rpm)
        fs = op.get('fs') or self.inspector.order_ctx.fs()
        # Audit fix R6/C7: COT requires strictly monotonic ``t``; synthesise a
        # uniform grid from the inspector fs when the timestamps are degenerate.
        t_arr = np.asarray(t, dtype=float) if t is not None else np.array([])
        if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
            t_arr = np.arange(len(sig), dtype=float) / float(fs)
        op = self._resolve_order_effective_params(op, rpm, t_arr)
        try:
            p = COTParams(
                samples_per_rev=int(op.get('samples_per_rev', 256)),
                nfft=int(op.get('nfft_effective', op['nfft'])),
                window=op.get('window', DEFAULT_ANALYSIS_WINDOW),
                max_order=float(op['max_order']),
                order_res=float(op['order_res']),
                time_res=float(op['time_res']),
                fs=fs,
                weighting=str(op.get('weighting', 'None')),
            )
        except Exception as e:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.failed += 1
            elif warn:
                QMessageBox.critical(self, "错误", str(e))
            return None
        analysis_key = self._order_analysis_cache_key(
            fid,
            ch,
            op,
            rpm_source=tuple(rpm_source) if rpm_source else None,
            time_range=time_range,
        )
        ctx = {
            'analysis_key': analysis_key,
            'pane_idx': pane_idx,
            'source': (fid, ch),
            # Capture at dispatch: completion may land after the user switched
            # Views, so the callback must not read the then-active view.
            'view_id': view_id,
        }

        def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
            return COTOrderAnalyzer.compute(
                _sig,
                _rpm,
                _t,
                _p,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        return job, ctx

    def _order_label_resolution(self, source, order_params):
        """Resolve this render's dB reference (spec §15 C3, Task 7): each
        pane's SINGLE source resolves independently -- honoring the
        section's current Auto/Manual View mode -- rather than reusing the
        FOCUSED pane's control value for a non-focused pane's render.

        ``source`` is ``None`` only for direct-call test doubles that never
        wire a real ``(fid, ch)``; those keep the historical
        ``order_params['db_reference']`` numeric default degraded through
        the shared validator so existing callers are unaffected.
        """
        if source is not None:
            return self._resolve_db_reference_for_source('order', source)
        return db_reference.degraded_numeric_resolution(order_params)

    def _render_order_on(self, canvas, result, source=None):
        """Multi-pane variant: draw an Order COT ``result`` on an arbitrary
        order heatmap canvas using the current OrderContextual display knobs.
        Pure canvas draw — no preset/status side-effects (those stay in
        ``_render_order_time``). ``source`` is the ``(fid, ch)`` this
        specific pane/result came from -- required for a per-pane-accurate
        dB-reference resolution (spec §15 C3)."""
        from ..pg_canvas.heatmap_canvas import time_axis_display_extent

        title = (
            f"时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} "
            f"(分辨率:{result.params.order_res})"
        )
        ctx = self.inspector.order_ctx
        order_params = ctx.current_params() if hasattr(ctx, 'current_params') else {}
        amp_mode_token = (
            'amplitude_db'
            if amplitude_mode_is_db(
                order_params.get('amplitude_mode', 'Amplitude dB')
            )
            else 'amplitude'
        )
        # weighting: prefer the COMPUTED result's own COTParams (the
        # authoritative value actually used to build this matrix) over the
        # current inspector combo, which may have drifted since compute.
        result_params = getattr(result, 'params', None)
        weighting = str(getattr(result_params, 'weighting', None)
                        or order_params.get('weighting', 'None'))
        output_scale = 'db' if amp_mode_token == 'amplitude_db' else 'linear'
        resolution = self._order_label_resolution(source, order_params)
        amplitude_label = db_reference.format_amplitude_label(
            resolution, weighting=weighting, output_scale=output_scale)
        # Reference-aware readout/remark suffix (spec §15 C3): only in dB
        # mode -- Linear has no reference concept, so leave it None and let
        # the canvas fall back to the channel unit (historical behaviour).
        z_unit_suffix = (
            db_reference.format_reference_note(resolution, weighting=weighting)
            if output_scale == 'db' else None
        )

        # Pre-convert dB outside the canvas so the canvas does not re-normalise
        # to its own peak (which would make the colorbar unpredictable and break
        # z_floor/z_ceiling color mapping). In Linear mode pass the raw matrix.
        matrix = result.amplitude.T
        plot_amp_mode = amp_mode_token
        cbar_label = amplitude_label
        # Spec §8.3.1: diff THIS render's reference against the last one
        # THIS canvas actually used, so a manual window can be shifted by
        # the same delta as the (unclipped) matrix -- getattr-guarded so a
        # bare test double canvas without the method keeps the pre-Task-7
        # behaviour (no shift, no crash).
        reference_delta = None
        if amp_mode_token == 'amplitude_db':
            db_ref = resolution.value
            matrix = SpectrogramAnalyzer.amplitude_to_db(matrix, reference=db_ref)
            plot_amp_mode = 'amplitude'
            delta_fn = getattr(canvas, 'reference_delta_since_last_render', None)
            if callable(delta_fn):
                reference_delta = delta_fn(db_ref)

        z_auto = bool(order_params.get('z_auto', False))
        z_floor = float(order_params.get('z_floor', -30.0))
        z_ceiling = float(order_params.get('z_ceiling', 0.0))

        # For the dB path: compute auto levels using the same fixed-SPAN
        # anchor used by plot_result — [ceiling - AUTO_SPAN_DB, ceiling] in
        # absolute dB — and pass them as explicit vmin/vmax so the canvas
        # does not fall back to the full data range (which may span 80+ dB
        # of noise floor).  This makes Order's auto/manual transition as
        # jump-free as FFT-vs-Time's.  The ceiling is a robust high
        # percentile (NOT the literal max) so a lone transient peak does not
        # drag the window up and bury the bulk below the floor — parity with
        # plot_result's _robust_db_ceiling.
        vmin_override = None
        vmax_override = None
        shifted_manual_levels = None
        if amp_mode_token == 'amplitude_db':
            if z_auto:
                from ..pg_canvas.heatmap_canvas import _auto_db_window
                window = _auto_db_window(matrix)
                if window is not None:
                    vmin_override, vmax_override = window
            elif reference_delta is not None:
                # An already-tuned MANUAL window must track the SAME shift
                # as the (unclipped) matrix above, else the map goes
                # black/blank when the effective reference changes.
                z_floor += reference_delta
                z_ceiling += reference_delta
                shifted_manual_levels = (z_floor, z_ceiling)

        # Pin the amplitude mode so the slice's amplitude-axis label reads
        # 'Amplitude (dB)' vs 'Amplitude' correctly (Order renders through
        # plot_or_update_heatmap, which does not set it like plot_result does).
        canvas._amplitude_mode = amp_mode_token
        canvas.plot_or_update_heatmap(
            matrix=matrix,
            x_extent=time_axis_display_extent(
                result.times,
                params=getattr(result, 'params', None),
                metadata=getattr(result, 'metadata', None),
                fallback=(float(result.times[0]), float(result.times[-1])),
            ),
            y_extent=(float(result.orders[0]), float(result.orders[-1])),
            x_label='Time (s)',
            y_label='Order',
            title=title,
            cmap=getattr(canvas, '_cmap_name', DEFAULT_HEATMAP_CMAP),
            interp=DEFAULT_HEATMAP_INTERP,
            cbar_label=cbar_label,
            amplitude_mode=plot_amp_mode,
            amplitude_label=amplitude_label,
            z_unit_suffix=z_unit_suffix,
            z_auto=z_auto,
            z_floor=z_floor,
            z_ceiling=z_ceiling,
            vmin=vmin_override,
            vmax=vmax_override,
            x_auto=bool(order_params.get('x_auto', True)),
            x_min=float(order_params.get('x_min', 0.0)),
            x_max=float(order_params.get('x_max', 0.0)),
            y_auto=bool(order_params.get('y_auto', True)),
            y_min=float(order_params.get('y_min', 0.0)),
            y_max=float(order_params.get('y_max', 0.0)),
            x_coords=result.times, y_coords=result.orders,
        )
        # Write the auto-computed absolute levels back into the inspector
        # spins (blockSignals) so that auto→manual is jump-free for Order
        # as well (parity with FFT-vs-Time).
        if z_auto and amp_mode_token == 'amplitude_db' and vmin_override is not None:
            for spin, val in (
                (ctx.spin_z_floor, vmin_override),
                (ctx.spin_z_ceiling, vmax_override),
            ):
                spin.blockSignals(True)
                spin.setValue(val)
                spin.blockSignals(False)
        elif shifted_manual_levels is not None:
            # Spec §8.3.1: persist the shifted manual window so it doesn't
            # silently drift back to the pre-shift numbers on the next
            # unrelated re-render.
            for spin, val in (
                (ctx.spin_z_floor, shifted_manual_levels[0]),
                (ctx.spin_z_ceiling, shifted_manual_levels[1]),
            ):
                spin.blockSignals(True)
                spin.setValue(val)
                spin.blockSignals(False)
        # Seed the order slice (default 按阶次 / Y is most useful, but keep the
        # current direction if the user already switched it).
        if getattr(canvas, '_slice_curve', None) is not None:
            canvas._seed_slice()
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)
        notify_ultraview_plot(self, "order", "order-plot")

    def _render_order_time(self, result, *, emit_feedback=True, source=None):
        # Wave 3 / Task 3.2: pull HEAD-parity display knobs from the
        # OrderContextual. Inspector exposes amplitude_mode ∈
        # {'Amplitude dB', 'Amplitude'} and dynamic ∈
        # {'30 dB', '50 dB', '80 dB', 'Auto'}; canvas expects the
        # internal token 'amplitude_db' / 'amplitude' for the first.
        # `result.amplitude` is (frames, orders) → transpose so imshow
        # gets (rows=Y_orders, cols=X_times); x_extent=times, y_extent=orders.
        self._render_order_on(self.canvas_order, result, source=source)
        batch_params = dict(self.inspector.order_ctx.current_params())
        batch_params['fs'] = result.params.fs
        batch_params['rpm_factor'] = self.inspector.order_ctx.rpm_factor()
        self._remember_batch_preset(
            "当前时间-阶次", "order_time",
            self.inspector.order_ctx.current_signal(),
            batch_params,
            rpm_signal=self.inspector.order_ctx.current_rpm(),
        )
        if emit_feedback:
            self.statusBar.showMessage(
                f'完成 | {len(result.times)} 时间点 × {len(result.orders)} 阶次'
            )
            self.toast(
                f"时间-阶次谱完成 · {len(result.times)} × {len(result.orders)}",
                "success",
            )

    def _on_order_job_finished(self, ctx, result):
        analysis_key = ctx.get('analysis_key')
        if analysis_key is not None:
            self._store_analysis_result(
                'order',
                ctx.get('view_id'),
                ctx.get('pane_idx', 0),
                analysis_key,
                result,
            )
        outcome = getattr(self, '_order_outcome', None)
        if outcome is not None:
            outcome.computed += 1
        # A7: cache/pin above uses dispatch-time view_id; only skip the live
        # page draw when the user has already switched away.
        if not self._analysis_ctx_targets_active_view('order', ctx):
            return
        # V7b: render onto the SPECIFIC pane this job was computed for.
        # ``_render_order_time`` (preset + status + toast side-effects) runs
        # only for the primary pane (0); compare panes get a pure canvas draw.
        page = self._analysis_page('order')
        pane_idx = ctx.get('pane_idx', 0)
        source = ctx.get('source')
        if pane_idx == 0:
            self._render_order_time(
                result, emit_feedback=outcome is None, source=source)
        elif pane_idx < page.pane_count():
            self._render_order_on(
                page.pane_canvas(pane_idx), result, source=source)
        else:
            self._render_order_time(
                result, emit_feedback=outcome is None, source=source)
    def _on_order_job_failed(self, _ctx, message):
        # A single pane's failure must not abort the service FIFO batch.
        #
        # V8 minor: use the non-modal ``toast`` (symmetric with
        # ``_on_fft_time_failed``) instead of ``QMessageBox.critical``. A
        # modal exec() raised mid-queue spins a nested event loop that can
        # re-enter the compute pump (and hangs under offscreen Qt with no
        # user to click OK — lesson qmessagebox-static-warning-hangs-offscreen).
        msg = str(message)
        outcome = getattr(self, '_order_outcome', None)
        if outcome is not None:
            outcome.failed += 1
        else:
            self.toast(msg, "error")
        self.statusBar.showMessage(f"阶次分析错误: {msg}")

    def _on_order_job_progress(self, done, total):
        """Project service-owned batch progress onto the existing UI bar."""
        token = self._analysis_jobs.progress_token('order')
        if token is None:
            return
        completed, total_jobs = self._analysis_jobs.progress_counts('order')
        total_jobs = max(1, total_jobs)
        job_index = min(completed + 1, total_jobs)
        label = f"阶次 {job_index}/{total_jobs}"
        self._update_compute_progress(
            done, total, label=label, token=token,
        )
        if done == total and not self._analysis_jobs.is_running('order'):
            self._finish_compute_progress(token=token)
            self._analysis_jobs.clear_progress_token('order')
            self.inspector.order_ctx.set_progress("")
            self._finish_order_outcome_feedback()
            self._finish_analysis_restore_if_idle()
