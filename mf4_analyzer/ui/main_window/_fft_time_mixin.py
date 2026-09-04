"""FFTTimeMixin: FFT-vs-Time (spectrogram) compute, cache, dispatch, render."""

import numpy as np

from ... import db_reference
from ...signal import resolve_nfft
from ...signal.analysis_defaults import DEFAULT_FFT_T_WIN_S
from ...signal.fft import unconstrained_window_nfft
from ...signal.spectrogram import spectrogram_facts_from_result
from ..pg_canvas.heatmap_canvas import DEFAULT_HEATMAP_CMAP
from ..compute_feedback import ComputeOutcome
from ._sentinel import _INSPECTOR_TIME_RANGE
from .fft_time_coordinator import make_fft_time_analysis_key
from .ultraview_coordinator import notify_ultraview_plot


class FFTTimeMixin:
    """Domain adapter for FFT-vs-Time input collection and rendering.

    Shared worker lifecycle, FIFO queueing and per-section progress accounting
    belong to ``AnalysisJobService``.  Each submitted job carries its own
    opaque context so completion never reads a mutable window-wide pending
    record.
    """

    @staticmethod
    def _resolve_fft_time_effective_params(p, n_samples):
        """Return FFT-vs-Time params with a concrete integer NFFT.

        ``FFTTimeContextual`` may emit ``nfft=None`` for auto mode because the
        real sample count is unknown at collection time. Resolve it only after
        the caller has applied the active time-range mask.
        """
        out = dict(p)
        auto = out.get('nfft') is None or out.get('nfft_mode') == 'auto'
        if auto:
            effective = resolve_nfft(
                out['fs'],
                n_samples,
                out.get('t_win_s', DEFAULT_FFT_T_WIN_S),
                out['overlap'],
            )
            out['nfft'] = int(effective)
            out['nfft_effective'] = int(effective)
            out['nfft_mode'] = 'auto'
        else:
            effective = int(out['nfft'])
            out['nfft'] = effective
            out['nfft_effective'] = effective
            out['nfft_mode'] = 'fixed'
        return out

    def _fft_time_analysis_cache_key(self, fid, ch, p, time_range=None):
        """Build the shared FFT-vs-Time compute key.

        New coordinator callers always pass ``time_range`` explicitly.  The
        integer compatibility branch keeps older cache-restoration callers on
        the same pane-local contract while they still pass a pane index.
        """
        if isinstance(time_range, int):
            time_range = self._pane_time_range_for('fft_time', time_range)
        params = {
            'fs': p.get('fs'),
            'nfft': int(p.get('nfft_effective', p.get('nfft'))),
            'window': p.get('window'),
            'overlap': p.get('overlap'),
            'remove_mean': p.get('remove_mean'),
            'weighting': str(p.get('weighting', 'None')),
        }
        return make_fft_time_analysis_key(
            self.analysis_caches['fft_time'].make_key,
            fid,
            ch,
            params,
            time_range,
        )

    def _fft_time_effective_params_for_source(self, p, fid, ch, time_range):
        """Resolve params for cache lookup without starting a worker."""
        _fid, _ch, t, sig, _fd = self._fft_time_signal_for((fid, ch))
        if sig is None or len(sig) < 2:
            return None
        rng = self._normalize_analysis_time_range(time_range)
        if rng is not None:
            _t, sig = self._mask_time_range(t, sig, time_range=rng)
            if len(sig) < 2:
                return None
            compute_time_range = rng
        else:
            compute_time_range = (float(t[0]), float(t[-1]))
        return (
            self._resolve_fft_time_effective_params(p, len(sig)),
            compute_time_range,
        )

    def _invalidate_all_analysis_caches_for_fid(self, fid):
        """Single entry point: drop ALL per-fid cache entries whenever a
        compute input changes for that file (e.g. time-axis rebuild, channel
        edit, file close).

        Every ``AnalysisResultCache`` in ``self.analysis_caches`` ('fft',
        'fft_time', 'order') is invalidated via ``invalidate_fid``.
        """
        for section, cache in self.analysis_caches.items():
            if section == 'fft_time':
                coordinator = getattr(self, '_fft_time_coordinator', None)
                if coordinator is not None:
                    coordinator.invalidate_fid(fid)
                    continue
            if section == 'frf':
                coordinator = getattr(self, '_frf_coordinator', None)
                if coordinator is not None:
                    coordinator.invalidate_fid(fid)
                    continue
            cache.invalidate_fid(fid)
        for section in ('fft', 'fft_time', 'order'):
            sync = getattr(self, f'_sync_{section}_effective_facts', None)
            if callable(sync):
                sync()

    def _get_fft_time_signal(self):
        """Resolve the (fid, channel, time, signal, file_data) tuple
        for the currently-selected fft_time signal.

        Adapts to this repo's ``FileData`` API: ``fd.data`` is the
        DataFrame (NOT ``fd.df``), ``fd.time_array`` is the time axis,
        ``fd.channel_units`` carries unit strings (NOT ``fd.units``).
        Returns ``(None,) * 5`` when no usable selection exists so
        ``do_fft_time`` can surface a single warning and bail.
        """
        data = self.inspector.fft_time_ctx.current_signal()
        return self._fft_time_signal_for(data)

    def _fft_time_signal_for(self, source):
        """Resolve the (fid, channel, time, signal, file_data) tuple for an
        explicit ``(fid, ch)`` source. V7b: the split-heatmap queue needs to
        fetch a NON-focused pane's source directly, not the inspector's
        current selection. Returns ``(None,) * 5`` when the source is
        unavailable so the queue can skip that job without aborting the rest.
        """
        if not source:
            return None, None, None, None, None
        fid, ch = source
        if fid not in self.files:
            return None, None, None, None, None
        fd = self.files[fid]
        if not hasattr(fd, 'data') or ch not in fd.data.columns:
            return None, None, None, None, None
        t = np.asarray(fd.time_array, dtype=float)
        sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
        return fid, ch, t, sig, fd

    def _fft_time_preview_n_samples(self):
        """Sample count for the FFT-vs-Time auto-NFFT summary, or ``None``.

        Pull-based hook registered via
        ``FFTTimeContextual.set_auto_nfft_provider``: returns the
        inspector-time-range-gated length of the current spectrogram source so
        the collapsed 自动(N) tracks ``_resolve_fft_time_effective_params`` (same
        ``resolve_nfft``). Returns ``None`` when unavailable. Never raises — it
        feeds a paint path.
        """
        try:
            source = self.inspector.fft_time_ctx.current_signal()
            _fid, _ch, t, sig, _fd = self._fft_time_signal_for(source)
            if sig is None or len(sig) < 2:
                return None
            top = self.inspector.top
            if top.range_enabled():
                _t, sig = self._mask_time_range(
                    t, sig, time_range=top.range_values()
                )
                if sig is None or len(sig) < 2:
                    return None
            return int(len(sig))
        except Exception:
            return None

    @staticmethod
    def _normalize_freq_range(p):
        """Translate the panel's ``freq_*`` fields into the canvas's
        ``freq_range`` tuple, with a clamp against contradictory
        ``freq_max <= freq_min`` input.

        Returns ``None`` to mean "auto" (canvas falls back to Nyquist).
        Reviewer Important #3: when a user toggles auto off and leaves
        ``freq_max == 0`` while raising ``freq_min``, the panel emits
        ``(lo>0, hi=0)``; the canvas's silent fallback is correct but
        confusing. We force ``hi=0`` (auto) whenever ``hi <= lo`` AND
        ``hi > 0``, and treat the entire pair as auto so the canvas
        reuses its existing fallback rather than receiving the bogus
        pair. Documented in
        ``docs/superpowers/reports/2026-04-25-fft-vs-time-T5-mainwindow-sync-compute.md``.
        """
        if p.get('freq_auto', True):
            return None
        lo = float(p.get('freq_min', 0.0))
        hi = float(p.get('freq_max', 0.0))
        # If freq_max is 0 it already means "auto / use Nyquist" per
        # FFTTimeContextual contract — pass the (lo, 0) pair through.
        # If freq_max > 0 but <= freq_min, the user input is
        # contradictory; force auto so the canvas does not silently
        # invert or collapse the range.
        if hi > 0 and hi <= lo:
            return None
        return (lo, hi)

    def _recompute_restored_fft_time_view(self, view_id):
        """Dispatch persisted FFT-vs-Time panes without reading live combos."""
        state = self._analysis_state_by_id("fft_time", view_id)
        if state is None:
            return
        compute_p = self._compute_params_overlay_state("fft_time", state)
        ctx = self.inspector.fft_time_ctx
        display_getter = getattr(ctx, "display_params", None)
        display_live = display_getter() if callable(display_getter) else {}
        saved = dict(state.params or {})
        display_p = dict(display_live)
        display_p.update({key: saved[key] for key in display_p if key in saved})
        candidates = []
        for pane_idx, pane in enumerate(state.panes):
            sources = pane.sources
            if not sources:
                continue
            fid, ch = sources[0]
            time_range = self._normalize_analysis_time_range(pane.time_range)
            prepared = self._fft_time_effective_params_for_source(
                compute_p, fid, ch, time_range
            )
            if prepared is None:
                continue
            effective_compute_p, _compute_time_range = prepared
            render_p = {**effective_compute_p, **display_p}
            candidates.append({
                "fid": fid,
                "channel": ch,
                "params": dict(effective_compute_p),
                "pane_idx": pane_idx,
                "time_range": time_range,
                "render_params": dict(render_p),
                "source": (fid, ch),
                "force": False,
                "view_id": state.view_id,
                "job_factory": lambda pane_idx=pane_idx, fid=fid, ch=ch,
                raw_params=dict(compute_p), display_params=dict(display_p),
                time_range=time_range: self._build_fft_time_job(
                    pane_idx, fid, ch, raw_params, time_range=time_range,
                    display_params=display_params,
                ),
            })
        if candidates:
            self._fft_time_coordinator.request_batch(candidates)

    def do_fft_time(self, force=False):
        """Compute and render the FFT-vs-Time spectrogram(s) for the active view.

        The mixin collects pane-local plain candidate dictionaries only.  The
        coordinator owns cache probing, service submission, pending state, and
        result caching; ``job_factory`` defers non-uniform-axis preflight until
        a true cache miss so a cache hit has no compute-side effects.
        """
        if not self._offer_analysis_time_range_before_compute('fft_time'):
            return
        self._capture_active_analysis_view('fft_time')
        if self._analysis_jobs.is_running('fft_time'):
            self._emit_compute_feedback(
                ComputeOutcome(),
                busy=True,
                section_label="FFT-vs-Time",
            )
            return
        self._fft_time_outcome = None
        mgr = self.analysis_managers['fft_time']
        state = mgr.get(mgr.active)
        self._clear_analysis_view_viewports(state)
        page = self._analysis_page('fft_time')
        ctx = self.inspector.fft_time_ctx
        compute_getter = getattr(ctx, 'compute_params', None)
        compute_p = (
            compute_getter() if callable(compute_getter) else ctx.get_params()
        )
        display_getter = getattr(ctx, 'display_params', None)
        display_p = (
            display_getter() if callable(display_getter) else ctx.get_params()
        )

        focus = page.focused_index()
        pane_order = sorted(
            range(min(page.pane_count(), len(state.panes))),
            key=lambda i: (i != focus, i),
        )
        candidates = []
        any_source = False
        outcome = ComputeOutcome()
        self._fft_time_outcome = outcome
        for pane_idx in pane_order:
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_source = True
            fid, ch = sources[0]
            render_p = {**compute_p, **display_p}
            time_range = self._pane_time_range_for('fft_time', pane_idx)
            prepared = self._fft_time_effective_params_for_source(
                compute_p, fid, ch, time_range)
            if prepared is None:
                outcome.skipped.append('源通道缺失或样本不足')
                candidates.append({
                    'fid': fid,
                    'channel': ch,
                    'params': dict(compute_p),
                    'pane_idx': pane_idx,
                    'time_range': time_range,
                    'job': None,
                    'render_params': dict(render_p),
                    'source': (fid, ch),
                    'force': force,
                    'view_id': state.view_id,
                })
                continue
            effective_compute_p, _compute_time_range = prepared
            render_p = {**effective_compute_p, **display_p}
            candidates.append({
                'fid': fid,
                'channel': ch,
                'params': dict(effective_compute_p),
                'pane_idx': pane_idx,
                'time_range': time_range,
                'render_params': dict(render_p),
                'source': (fid, ch),
                'force': force,
                'view_id': state.view_id,
                'job_factory': lambda pane_idx=pane_idx, fid=fid, ch=ch,
                raw_params=dict(compute_p), display_params=dict(display_p), \
                time_range=time_range: self._build_fft_time_job(
                    pane_idx, fid, ch, raw_params, time_range=time_range,
                    display_params=display_params,
                ),
            })

        if not candidates:
            if not any_source:
                self._fft_time_outcome = None
                self._do_fft_time_single(force=force)
                return
            self._emit_compute_feedback(outcome, section_label="FFT-vs-Time")
            self._fft_time_outcome = None
            return

        queued = self._fft_time_coordinator.request_batch(candidates)
        if queued == 0:
            self._finish_fft_time_outcome_feedback()

    def _do_fft_time_single(self, force=False):
        """Legacy single-source FFT-vs-Time path: compute the inspector's
        currently-selected signal onto the primary canvas. Kept so a view
        whose panes have no captured source (e.g. a brand-new heatmap view
        before the navigator/inspector echo wires a source) still computes
        the inspector selection, matching pre-V7b behaviour and tests.

        Fetches via :meth:`_get_fft_time_signal` (the inspector-selection
        getter, which standalone-signal tests monkeypatch) rather than the
        per-pane ``_fft_time_signal_for`` used by the split queue.
        """
        page = self._analysis_page('fft_time')
        pane_idx = page.focused_index()
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        ctx = self.inspector.fft_time_ctx
        compute_getter = getattr(ctx, 'compute_params', None)
        compute_p = (
            compute_getter() if callable(compute_getter) else ctx.get_params()
        )
        display_getter = getattr(ctx, 'display_params', None)
        display_p = (
            display_getter() if callable(display_getter) else ctx.get_params()
        )
        compute_time_range = (
            self.inspector.top.range_values()
            if self.inspector.top.range_enabled() else None
        )
        rng = self._normalize_analysis_time_range(compute_time_range)
        if rng is not None:
            t, sig = self._mask_time_range(t, sig, time_range=rng)
        if sig is None or len(sig) < 2:
            self.toast("当前范围内样本不足", "warning")
            return
        effective_compute_p = self._resolve_fft_time_effective_params(
            compute_p, len(sig))
        render_p = {**effective_compute_p, **display_p}
        self._fft_time_outcome = None
        mgr = self.analysis_managers['fft_time']
        view_id = mgr.get(mgr.active).view_id
        self._fft_time_coordinator.request_batch([{
            'fid': fid,
            'channel': ch,
            'params': dict(effective_compute_p),
            'pane_idx': pane_idx,
            'time_range': self._pane_time_range_for('fft_time', pane_idx),
            'render_params': dict(render_p),
            'source': (fid, ch),
            'force': force,
            'view_id': view_id,
            'job_factory': lambda: self._build_fft_time_job(
                pane_idx, fid, ch, dict(compute_p), time_range=compute_time_range,
                signal_getter=self._get_fft_time_signal,
                display_params=dict(display_p),
            ),
        }])

    def _on_fft_time_batch_started(self, total, first_ctx):
        """Create the UI token before service submission can finish skips."""
        if self._analysis_jobs.progress_token("fft_time") is None:
            self._analysis_jobs.set_progress_token(
                "fft_time",
                self._begin_compute_progress(
                    "FFT-时间 1/%d" % total,
                    total=1000,
                    process_events=False,
                ),
            )
        p = first_ctx.get('render_params') or {}
        nfft = p.get('nfft_effective', p.get('nfft'))
        self.statusBar.showMessage(
            f"正在计算… · NFFT {nfft}" if nfft is not None else "正在计算…"
        )

    def _finish_fft_time_outcome_feedback(self):
        outcome = getattr(self, '_fft_time_outcome', None)
        if outcome is None:
            return
        self._emit_compute_feedback(outcome, section_label="FFT-vs-Time")
        self._fft_time_outcome = None

    def _record_fft_time_skip(self, reason):
        outcome = getattr(self, '_fft_time_outcome', None)
        if outcome is not None:
            outcome.skipped.append(reason)

    def _build_fft_time_job(
        self, pane_idx, fid, ch, raw_params, *, time_range=_INSPECTOR_TIME_RANGE,
        signal_getter=None, display_params=None,
    ):
        """Prepare one job and its immutable completion context, or skip it."""
        from ...signal import SpectrogramParams
        if signal_getter is None:
            signal_getter = lambda: self._fft_time_signal_for((fid, ch))
        fid, ch, t, sig, fd = signal_getter()
        if sig is None:
            self._record_fft_time_skip("源通道缺失")
            return None
        if len(sig) < 2:
            self._record_fft_time_skip("信号过短")
            return None
        preflight_fs = getattr(fd, 'fs', None)
        # Pre-flight uniformity gate (T2, 2026-04-26): rebuild a non-uniform
        # time axis BEFORE dispatching the worker. Best-effort per pane —
        # a failed rebuild skips this job, not the whole queue.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            self._record_fft_time_skip("时间轴非均匀")
            return None
        # The rebuild may have rewritten ``fd.time_array``; re-fetch.
        fid, ch, t, sig, fd = signal_getter()
        if sig is None:
            self._record_fft_time_skip("源通道缺失")
            return None
        if len(sig) < 2:
            self._record_fft_time_skip("信号过短")
            return None
        rebuilt_fs = getattr(fd, 'fs', None)
        if rebuilt_fs is not None and rebuilt_fs != preflight_fs:
            raw_params = dict(raw_params, fs=float(rebuilt_fs))
        if (
            time_range is _INSPECTOR_TIME_RANGE
            and self.inspector.top.range_enabled()
        ):
            time_range = self.inspector.top.range_values()
        if time_range is _INSPECTOR_TIME_RANGE:
            time_range = None
        rng = self._normalize_analysis_time_range(time_range)
        if rng is not None:
            t, sig = self._mask_time_range(t, sig, time_range=rng)
            if len(sig) < 2:
                self._record_fft_time_skip("样本不足")
                return None
        p = self._resolve_fft_time_effective_params(raw_params, len(sig))
        # SpectrogramParams is the cache key on the analyzer side; build
        # it from compute-relevant fields only (db_reference is display-only
        # and lives render-side, so it is intentionally not passed here).
        params = SpectrogramParams(
            fs=float(p['fs']),
            nfft=int(p['nfft_effective']),
            window=str(p['window']),
            overlap=float(p['overlap']),
            remove_mean=bool(p['remove_mean']),
            weighting=str(p.get('weighting', 'None')),
        )
        unit = ''
        if fd is not None and hasattr(fd, 'channel_units'):
            unit = fd.channel_units.get(ch, '') or ''
        auto = raw_params.get('nfft') is None or raw_params.get('nfft_mode') == 'auto'
        if auto:
            nfft_requested = unconstrained_window_nfft(
                p.get('fs'), p.get('t_win_s', DEFAULT_FFT_T_WIN_S),
            )
            if nfft_requested is None:
                nfft_requested = int(p['nfft_effective'])
        else:
            nfft_requested = int(p['nfft_effective'])
        n_samples = len(sig)

        def job(
            worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit,
            _requested=nfft_requested, _n_samples=n_samples,
        ):
            from ...signal import SpectrogramAnalyzer
            result = SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )
            result.effective = spectrogram_facts_from_result(
                result,
                nfft_requested=_requested,
                n_samples=_n_samples,
            )
            return result

        render_params = {**p, **dict(display_params or {})}
        return job, {
            'fid': fid,
            'channel': ch,
            'params': p,
            'render_params': render_params,
            'source': (fid, ch),
        }

    def _render_fft_time(self, result, p, source=None):
        """Apply display-only options and draw on the primary canvas.

        Display fields are NOT part of the cache key; this is the sole
        place they are read.
        """
        self._render_fft_time_on(self.canvas_fft_time, result, p, source=source)

    def _fft_time_label_resolution(self, source, p):
        """Resolve this render's dB reference (spec §15 C2, Task 7): each
        pane's SINGLE source resolves independently -- honoring the section's
        current Auto/Manual View mode -- rather than reusing the FOCUSED
        pane's control value for a non-focused pane's render.

        ``source`` is ``None`` only for direct-call test doubles that never
        wire a real ``(fid, ch)`` (e.g. bare-canvas smoke tests); those keep
        the historical ``p['db_reference']`` numeric default degraded through
        the shared validator so existing callers are unaffected.
        """
        if source is not None:
            return self._resolve_db_reference_for_source('fft_time', source)
        return db_reference.degraded_numeric_resolution(p)

    def _render_fft_time_on(self, canvas, result, p, source=None):
        """Multi-pane variant: render ``result`` on an arbitrary FFT-vs-Time
        heatmap canvas with display options from ``p``. ``source`` is the
        ``(fid, ch)`` this specific pane/result came from -- required for a
        per-pane-accurate dB-reference resolution (spec §15 C2)."""
        if bool(p.get('freq_auto', p.get('y_auto', True))):
            freq_range = self._fft_time_auto_freq_range(result)
        else:
            freq_range = self._normalize_freq_range(p)
        # Wave 5: legacy ``dynamic: str`` is gone; we forward the explicit
        # z_auto / z_floor / z_ceiling triplet that FFTTimeContextual now
        # emits, plus y_auto / y_min / y_max for the manual Y override
        # (precedes freq_range on the canvas). amplitude_mode is already
        # the canvas's lowercase token ('amplitude_db' / 'amplitude') in
        # FFTTimeContextual.get_params, so no translation needed.
        z_auto = bool(p.get('z_auto', False))
        setter = getattr(canvas, "set_overlay_source", None)
        if callable(setter):
            setter(source)
        amp_mode = p['amplitude_mode']
        # weighting: prefer the COMPUTED result's own SpectrogramParams (the
        # authoritative value actually used to build this matrix) over the
        # current inspector combo, which may have drifted since compute.
        result_params = getattr(result, 'params', None)
        weighting = str(getattr(result_params, 'weighting', None)
                        or p.get('weighting', 'None'))
        output_scale = 'db' if amp_mode == 'amplitude_db' else 'linear'
        resolution = self._fft_time_label_resolution(source, p)
        amplitude_label = db_reference.format_amplitude_label(
            resolution, weighting=weighting, output_scale=output_scale)
        # Reference-aware readout/remark suffix (spec §15 C2): only in dB
        # mode -- Linear has no reference concept, so leave it None and let
        # the canvas fall back to the channel unit (historical behaviour).
        z_unit_suffix = (
            db_reference.format_reference_note(resolution, weighting=weighting)
            if output_scale == 'db' else None
        )
        canvas.plot_result(
            result,
            amplitude_mode=amp_mode,
            cmap=getattr(canvas, '_cmap_name', DEFAULT_HEATMAP_CMAP),
            z_auto=z_auto,
            z_floor=float(p.get('z_floor', -80.0)),
            z_ceiling=float(p.get('z_ceiling', 0.0)),
            freq_range=freq_range,
            interp='bilinear',
            x_auto=bool(p.get('x_auto', True)),
            x_min=float(p.get('x_min', 0.0)),
            x_max=float(p.get('x_max', 0.0)),
            y_auto=bool(p.get('y_auto', True)),
            y_min=float(p.get('y_min', 0.0)),
            y_max=float(p.get('y_max', 0.0)),
            # db_reference is display-only: source it from the resolved
            # reference at RENDER time so changing it re-renders from cache
            # without a recompute (it is absent from SpectrogramParams + the
            # cache key). resolve_db_reference always returns a validated,
            # positive value -- no separate max(..., 1e-12) coercion needed.
            db_reference=resolution.value,
            amplitude_label=amplitude_label,
            colorbar_label=amplitude_label,
            z_unit_suffix=z_unit_suffix,
        )
        # Write the auto-computed absolute levels back into the inspector
        # spins (blockSignals so we don't trigger a recompute).  This makes
        # the current display window the single source of truth: when the
        # user later un-ticks "自动", the spins already hold the exact same
        # values that are on screen, so switching auto→manual is jump-free.
        if z_auto and amp_mode == 'amplitude_db':
            auto_lvls = getattr(canvas, '_last_auto_levels', None)
            if auto_lvls is not None:
                ctx = self.inspector.fft_time_ctx
                for spin, val in (
                    (ctx.spin_z_floor, auto_lvls[0]),
                    (ctx.spin_z_ceiling, auto_lvls[1]),
                ):
                    spin.blockSignals(True)
                    spin.setValue(val)
                    spin.blockSignals(False)
        elif not z_auto and amp_mode == 'amplitude_db':
            # Spec §8.3.1: the reference changed since this canvas's last
            # render and a MANUAL window was in effect -- plot_result already
            # shifted vmin/vmax by the matching delta; persist the shifted
            # numbers into the spins so they don't silently drift back to
            # the pre-shift values on the next unrelated re-render.
            shifted = getattr(canvas, '_last_manual_levels_shifted', None)
            if shifted is not None:
                ctx = self.inspector.fft_time_ctx
                for spin, val in (
                    (ctx.spin_z_floor, shifted[0]),
                    (ctx.spin_z_ceiling, shifted[1]),
                ):
                    spin.blockSignals(True)
                    spin.setValue(val)
                    spin.blockSignals(False)
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)
        notify_ultraview_plot(self, "fft_time", "fft-time-plot")
        self._restore_analysis_canvas_viewport("fft_time", canvas)

    # ---- FFT vs Time coordinator events --------------------------------
    def _on_fft_time_render_requested(self, ctx, result, cache_hit):
        """Render a cache hit or freshly computed result for its own pane.

        The coordinator stores cache/pin under the dispatch-time ``view_id``
        before emitting this signal.  When that View is no longer active we
        skip only the live draw (A7); switching back restores via
        ``_render_analysis_view_from_cache``.
        """
        p = ctx.get('render_params') or {}
        pane_idx = ctx.get('pane_idx')
        source = ctx.get('source')
        outcome = getattr(self, '_fft_time_outcome', None)
        if outcome is not None:
            if cache_hit:
                outcome.cached += 1
            else:
                outcome.computed += 1
        if not self._analysis_ctx_targets_active_view('fft_time', ctx):
            return
        if p is not None:
            page = self._analysis_page('fft_time')
            if pane_idx is not None and pane_idx < page.pane_count():
                self._render_fft_time_on(
                    page.pane_canvas(pane_idx), result, p, source=source)
            else:
                self._render_fft_time(result, p, source=source)
        nfft = getattr(getattr(result, 'params', None), 'nfft', None)
        suffix = f" · NFFT {int(nfft)}" if nfft is not None else ""
        if cache_hit:
            self.statusBar.showMessage(
                "使用缓存结果 · "
                f"{result.metadata.get('frames', 0)} frames{suffix}"
            )
        else:
            self.statusBar.showMessage(
                f"FFT vs Time 完成 · {result.metadata.get('frames', 0)} frames"
                f"{suffix}"
            )
        self._sync_fft_time_effective_facts()

    def _sync_fft_time_effective_facts(self, state=None):
        """Re-fill the Inspector facts card from the focused spectrogram."""
        ctx = self.inspector.fft_time_ctx
        if state is None:
            mgr = self.analysis_managers.get('fft_time')
            if mgr is None or not mgr.views:
                ctx.clear_effective_facts()
                return
            state = mgr.get(mgr.active)
        page = self._analysis_page('fft_time')
        idx = page.focused_index()
        if state is None or not (0 <= idx < len(state.panes)):
            ctx.clear_effective_facts()
            return
        pane = state.panes[idx]
        sources = list(pane.sources)
        if not sources:
            ctx.clear_effective_facts()
            return
        fid, ch = sources[0]
        time_range = self._pane_time_range_for('fft_time', idx)
        prepared = self._fft_time_effective_params_for_source(
            self.inspector.fft_time_ctx.compute_params()
            if hasattr(self.inspector.fft_time_ctx, 'compute_params')
            else self.inspector.fft_time_ctx.get_params(),
            fid, ch, time_range,
        )
        if prepared is None:
            ctx.clear_effective_facts()
            return
        effective_p, _rng = prepared
        key = self._fft_time_analysis_cache_key(
            fid, ch, effective_p, time_range,
        )
        result = self.analysis_caches['fft_time'].get(key)
        facts = getattr(result, 'effective', None) if result is not None else None
        if facts is None and result is not None:
            nfft_requested = unconstrained_window_nfft(
                getattr(getattr(result, 'params', None), 'fs', None),
                DEFAULT_FFT_T_WIN_S,
            )
            _fid, _ch, _t, sig, _fd = self._fft_time_signal_for((fid, ch))
            n_samples = int(len(sig)) if sig is not None else 0
            facts = spectrogram_facts_from_result(
                result, nfft_requested=nfft_requested, n_samples=n_samples,
            )
        if facts is None:
            ctx.clear_effective_facts()
            return
        _fid, _ch, _t, sig, _fd = self._fft_time_signal_for((fid, ch))
        self._publish_analysis_effective_facts(
            ctx, facts, sig=sig, fid=fid, sources=sources,
        )

    def _on_fft_time_failed(self, _ctx, message):
        """Coordinator failure — keep the previous chart on screen.

        Mirrors the synchronous T5 error pattern: ``toast(error)`` plus
        a status-bar message; the canvas is NEVER cleared so the user
        keeps the last-known-good chart while debugging the input.

        Cancel is also routed here (the analyzer raises
        ``RuntimeError('spectrogram computation cancelled')`` when
        ``cancel_token`` returns truthy) — the message string itself
        carries the distinction, no separate signal needed.

        T2 (2026-04-26) removed the in-handler auto-rebuild + retry
        branch that previously handled ``non-uniform time axis``
        errors. Non-uniform inputs are now caught synchronously by
        :meth:`_check_uniform_or_prompt` BEFORE worker dispatch (see
        ``do_fft_time``). The handler's earlier ``_fft_time_retry_pending``
        flag had a latent lifecycle bug (cleared in the deferred
        ``_retry``'s ``finally`` before the next worker could fail);
        deleting the retry path eliminates that risk and simplifies the
        contract: every worker failure now surfaces verbatim. If the
        worker still raises ``non-uniform time axis`` (e.g. a future
        regression or a genuinely racy axis mutation), the message
        surfaces as a normal error toast and the user can click
        重建时间轴 manually.
        """
        msg = str(message)
        outcome = getattr(self, '_fft_time_outcome', None)
        if outcome is not None:
            outcome.failed += 1
        else:
            self.toast(msg, "error")
        self.statusBar.showMessage(f"FFT vs Time 错误: {message}")

    def _on_fft_time_job_progress(self, done, total):
        """Project service-owned batch progress onto the existing UI bar."""
        token = self._analysis_jobs.progress_token('fft_time')
        if token is None:
            return
        completed, total_jobs = self._analysis_jobs.progress_counts('fft_time')
        total_jobs = max(1, total_jobs)
        job_index = min(completed + 1, total_jobs)
        label = f"FFT-时间 {job_index}/{total_jobs}"
        self._update_compute_progress(
            done, total, label=label, token=token,
        )
        if done == total and not self._analysis_jobs.is_running('fft_time'):
            self._finish_compute_progress(token=token)
            self._analysis_jobs.clear_progress_token('fft_time')
            self._finish_fft_time_outcome_feedback()
            self._finish_analysis_restore_if_idle()
