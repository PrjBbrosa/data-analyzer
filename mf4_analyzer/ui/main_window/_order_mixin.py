"""OrderMixin: COT Order analysis worker dispatch and render methods."""

import numpy as np

from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QThread

from ...signal import assess_speed_for_order, resolve_order_nfft
from ...signal.spectrogram import SpectrogramAnalyzer
from ..compute_feedback import ComputeOutcome
from ._sentinel import _INSPECTOR_TIME_RANGE


class OrderMixin:
    """Domain mixin: COT Order spectrum calculation, queue dispatch, and render.

    ``QThread`` lookups use the ``sys.modules`` pattern so
    ``monkeypatch.setattr(mw_mod, 'QThread', ...)`` in the test suite
    reaches the call site even though the import is in this sub-file.
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
                       t_sig=None):
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
        if not rpm_source:
            return None
        fid, ch = rpm_source
        if fid not in self.files:
            return None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None
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

    @staticmethod
    def _order_revolutions(rpm, t):
        """Total revolutions over ``t`` = ∫|rpm|/60 dt (trapezoid).

        Returns ``0.0`` for degenerate input (too few / non-finite samples or
        non-increasing time). Single source of truth shared by the COT angle
        sample count and the inspector auto-NFFT preview provider.
        """
        rpm_arr = np.asarray(rpm, dtype=float).reshape(-1)
        t_arr = np.asarray(t, dtype=float).reshape(-1)
        n = min(rpm_arr.size, t_arr.size)
        if n < 2:
            return 0.0
        rpm_arr = rpm_arr[:n]
        t_arr = t_arr[:n]
        finite = np.isfinite(rpm_arr) & np.isfinite(t_arr)
        rpm_arr = rpm_arr[finite]
        t_arr = t_arr[finite]
        if rpm_arr.size < 2:
            return 0.0
        dt = np.diff(t_arr)
        valid_dt = np.isfinite(dt) & (dt > 0.0)
        if not np.any(valid_dt):
            return 0.0
        abs_rpm = np.abs(rpm_arr)
        revs = np.sum(
            0.5
            * (abs_rpm[:-1][valid_dt] + abs_rpm[1:][valid_dt])
            / 60.0
            * dt[valid_dt]
        )
        if not np.isfinite(revs) or revs <= 0.0:
            return 0.0
        return float(revs)

    @staticmethod
    def _order_angle_sample_count(samples_per_rev, rpm, t):
        revs = OrderMixin._order_revolutions(rpm, t)
        if revs <= 0.0:
            return 1
        return max(1, int(round(float(samples_per_rev) * revs)))

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
            n_angle = OrderMixin._order_angle_sample_count(
                samples_per_rev,
                rpm,
                t,
            )
            effective = resolve_order_nfft(
                samples_per_rev,
                out.get('order_res', 0.05),
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
        # 规约：凡进入 COT 计算的用户可调参数都必须在此登记，否则改了不刷新。
        # window is a COTParams field consumed by COTOrderAnalyzer.compute
        # (it builds the analysis window from it); registering it here keeps
        # the key field-aligned with the dataclass so a window change forces a
        # recompute instead of reusing a result built with the old window.
        return {
            'nfft': int(nfft),
            'nfft_mode': p.get('nfft_mode', 'fixed'),
            'window': p.get('window', 'hanning'),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': p.get('samples_per_rev'),
            'rpm_factor': p.get('rpm_factor'),
            'fs': p.get('fs'),
            'weighting': str(p.get('weighting', 'None')),
            'rpm_source': list(rpm_source) if rpm_source else None,
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
            rpm_source, len(sig), time_range=time_range, t_sig=t)
        if rpm is None:
            return None
        fs = self.inspector.order_ctx.fs()
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

    def do_order_time(self):
        """Compute the WHOLE active Order view — every pane (V7b).

        Each pane carries one signal source ``(fid, ch)`` plus its own
        ``rpm_source``. For every pane we build the analysis cache key and
        either render a cache HIT onto that pane's canvas immediately, or
        enqueue a ``(pane_idx, fid, ch, rpm_source)`` job. The focused pane
        is enqueued first. Miss jobs run sequentially on ONE shared worker
        QThread; :meth:`_on_order_thread_done` pumps the next. A single
        (non-split) pane yields one job, identical to the V7 path.

        Re-entry while a worker is running drops the whole new request with
        ``正在计算…``. A pane whose source/rpm is unfetchable is skipped
        without aborting the queue.
        """
        # V7 Step 5: capture the active Order view (params + per-pane sources +
        # rpm_source) so a later view switch renders from analysis_caches.
        self._capture_active_analysis_view('order')
        # Re-entry guard: a previous compute / queue is still running.
        if getattr(self, '_order_thread', None) is not None and self._order_thread.isRunning():
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
        queue = []
        any_source = False
        outcome = ComputeOutcome()
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
                cache.put(analysis_key, cached)
                self._render_order_on(page.pane_canvas(pane_idx), cached)
                outcome.cached += 1
            else:
                queue.append((pane_idx, fid, ch, rpm_source))

        if not queue:
            if not any_source:
                # No captured pane source → legacy inspector-selection path so
                # the standalone-signal UX + existing tests are unchanged.
                self._do_order_time_single()
                return
            self._emit_compute_feedback(outcome, section_label="时间-阶次")
            return

        self._order_queue = queue
        self._order_outcome = outcome
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")
        self._start_next_order_job()

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
        self._order_queue = []
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")
        if not self._dispatch_order_job(
                page.focused_index(), sig_data[0], sig_data[1],
                tuple(rpm_data) if rpm_data else None):
            self.inspector.order_ctx.set_progress("")

    def _start_next_order_job(self):
        """Dispatch the head Order job, skipping unfetchable sources."""
        while self._order_queue:
            pane_idx, fid, ch, rpm_source = self._order_queue.pop(0)
            if self._dispatch_order_job(pane_idx, fid, ch, rpm_source):
                return
        # Queue drained.
        self.inspector.order_ctx.set_progress("")
        self._finish_order_outcome_feedback()

    def _finish_order_outcome_feedback(self):
        outcome = getattr(self, '_order_outcome', None)
        if outcome is None:
            return
        self._emit_compute_feedback(outcome, section_label="时间-阶次")
        self._order_outcome = None

    def _dispatch_order_job(self, pane_idx, fid, ch, rpm_source):
        """Fetch the ``(fid, ch)`` signal + ``rpm_source`` rpm, then start the
        shared COT worker, rendering onto ``page.pane_canvas(pane_idx)``.
        Returns True if a worker started, False if the source was skipped."""
        from ...signal.order_cot import COTOrderAnalyzer, COTParams
        time_range = self._pane_time_range_for('order', pane_idx)
        t, sig = self._order_sig_for((fid, ch), time_range=time_range)
        if sig is None:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("源通道缺失")
            return False
        if len(sig) < 100:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("信号过短")
            return False
        rpm = self._order_rpm_for(
            rpm_source, len(sig), time_range=time_range, t_sig=t)
        if rpm is None:
            outcome = getattr(self, '_order_outcome', None)
            if outcome is not None:
                outcome.skipped.append("缺转速")
            return False
        self._warn_if_order_speed_unsuitable(rpm)
        fs = self.inspector.order_ctx.fs()
        order_params = self.inspector.order_ctx.current_params()
        op = dict(self.inspector.order_ctx.get_params())
        op['samples_per_rev'] = int(order_params.get('samples_per_rev', 256))
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
                window=op.get('window', 'hanning'),
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
            else:
                QMessageBox.critical(self, "错误", str(e))
            return False
        # Stash the analysis cache key + render target for this job.
        self._order_analysis_key = self._order_analysis_cache_key(
            fid,
            ch,
            op,
            rpm_source=tuple(rpm_source) if rpm_source else None,
            time_range=time_range,
        )
        self._order_render_pane = pane_idx

        from ..analysis_worker import AnalysisComputeWorker
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QThread = getattr(_pkg, 'QThread', QThread) if _pkg is not None else QThread

        def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
            return COTOrderAnalyzer.compute(_sig, _rpm, _t, _p,
                                            cancel_token=worker.cancelled)

        worker = AnalysisComputeWorker(job)
        thread = _QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_order_finished)
        worker.failed.connect(self._on_order_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_order_thread_done)
        self._order_thread = thread
        self._order_worker = worker
        thread.start()
        return True

    def _render_order_on(self, canvas, result):
        """Multi-pane variant: draw an Order COT ``result`` on an arbitrary
        order heatmap canvas using the current OrderContextual display knobs.
        Pure canvas draw — no preset/status side-effects (those stay in
        ``_render_order_time``)."""
        from ..pg_canvas.heatmap_canvas import time_axis_display_extent

        title = (
            f"时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} "
            f"(分辨率:{result.params.order_res})"
        )
        ctx = self.inspector.order_ctx
        order_params = ctx.current_params() if hasattr(ctx, 'current_params') else {}
        amp_mode_token = (
            'amplitude_db'
            if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
            else 'amplitude'
        )
        # Pre-convert dB outside the canvas so the canvas does not re-normalise
        # to its own peak (which would make the colorbar unpredictable and break
        # z_floor/z_ceiling color mapping). In Linear mode pass the raw matrix.
        matrix = result.amplitude.T
        plot_amp_mode = amp_mode_token
        cbar_label = 'Amplitude'
        if amp_mode_token == 'amplitude_db':
            db_ref = max(float(order_params.get('db_reference', 1.0)), 1e-12)
            matrix = SpectrogramAnalyzer.amplitude_to_db(matrix, reference=db_ref)
            plot_amp_mode = 'amplitude'
            cbar_label = f'Amplitude (dB re {db_ref:g})'

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
        if z_auto and amp_mode_token == 'amplitude_db':
            from ..pg_canvas.heatmap_canvas import _auto_db_window
            vmin_override, vmax_override = _auto_db_window(matrix)

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
            cmap='turbo',
            interp='bilinear',
            cbar_label=cbar_label,
            amplitude_mode=plot_amp_mode,
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
        # Seed the order slice (default 按阶次 / Y is most useful, but keep the
        # current direction if the user already switched it).
        if getattr(canvas, '_slice_curve', None) is not None:
            canvas._seed_slice()
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)

    def _render_order_time(self, result, *, emit_feedback=True):
        # Wave 3 / Task 3.2: pull HEAD-parity display knobs from the
        # OrderContextual. Inspector exposes amplitude_mode ∈
        # {'Amplitude dB', 'Amplitude'} and dynamic ∈
        # {'30 dB', '50 dB', '80 dB', 'Auto'}; canvas expects the
        # internal token 'amplitude_db' / 'amplitude' for the first.
        # `result.amplitude` is (frames, orders) → transpose so imshow
        # gets (rows=Y_orders, cols=X_times); x_extent=times, y_extent=orders.
        self._render_order_on(self.canvas_order, result)
        self._remember_batch_preset(
            "当前时间-阶次", "order_time",
            self.inspector.order_ctx.current_signal(),
            {
                'fs': result.params.fs,
                'nfft': result.params.nfft,
                'max_order': result.params.max_order,
                'order_res': result.params.order_res,
                'time_res': result.params.time_res,
                'rpm_factor': self.inspector.order_ctx.rpm_factor(),
            },
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

    def _on_order_finished(self, result):
        analysis_key = getattr(self, '_order_analysis_key', None)
        if analysis_key is not None:
            self.analysis_caches['order'].put(analysis_key, result)
        outcome = getattr(self, '_order_outcome', None)
        if outcome is not None:
            outcome.computed += 1
        # V7b: render onto the SPECIFIC pane this job was computed for.
        # ``_render_order_time`` (preset + status + toast side-effects) runs
        # only for the primary pane (0); compare panes get a pure canvas draw.
        page = self._analysis_page('order')
        pane_idx = getattr(self, '_order_render_pane', 0)
        if pane_idx == 0:
            self._render_order_time(result, emit_feedback=outcome is None)
        elif pane_idx < page.pane_count():
            self._render_order_on(page.pane_canvas(pane_idx), result)
        else:
            self._render_order_time(result, emit_feedback=outcome is None)
        # Clear the in-progress label only when no more jobs are queued; the
        # thread-done pump re-sets it for the next job otherwise.
        if not self._order_queue:
            self.inspector.order_ctx.set_progress("")

    def _on_order_failed(self, message):
        # A single pane's failure must not abort the queue; the wired
        # ``failed -> thread.quit -> _on_order_thread_done`` pump advances to
        # the next job. Surface the error but keep going.
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
        if not self._order_queue:
            self.inspector.order_ctx.set_progress("")

    def _on_order_thread_done(self):
        self._order_thread = None
        self._order_worker = None
        if self._order_queue:
            self._start_next_order_job()
        else:
            self._finish_order_outcome_feedback()
