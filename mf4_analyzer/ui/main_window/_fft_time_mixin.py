"""FFTTimeMixin: FFT-vs-Time (spectrogram) compute, cache, dispatch, render."""

import numpy as np

from PyQt5.QtCore import QThread

from ...signal import resolve_nfft
from ..compute_feedback import ComputeOutcome
from ._sentinel import _INSPECTOR_TIME_RANGE


class FFTTimeMixin:
    """Domain mixin: FFT-vs-Time spectrogram compute, LRU cache, worker
    dispatch, and render.

    The per-session LRU cache (``self._fft_time_cache`` +
    ``self._fft_time_cache_capacity``) and the worker/queue fields
    (``self._fft_time_thread`` etc.) are created in ``MainWindow.__init__``.

    ``QThread`` is resolved via ``sys.modules`` at call time so
    ``monkeypatch.setattr(mw_mod, 'QThread', ...)`` reaches this sub-file.
    The shared static helpers ``_fft_time_auto_freq_range`` /
    ``_fft_auto_xlim`` remain on MainWindow (window.py) and resolve through
    the MRO via ``self.``.
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
                out.get('t_win_s', 1.5),
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

    def _fft_time_analysis_cache_key(self, fid, ch, p, pane_idx):
        cache = self.analysis_caches['fft_time']
        params = {
            'fs': p.get('fs'),
            'nfft': int(p.get('nfft_effective', p.get('nfft'))),
            'window': p.get('window'),
            'overlap': p.get('overlap'),
            'remove_mean': p.get('remove_mean'),
            'db_reference': p.get('db_reference', 1.0),
            'time_range': self._pane_time_range_for('fft_time', pane_idx),
        }
        return cache.make_key(fid, ch, params)

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
            effective_time_range = rng
        else:
            effective_time_range = (float(t[0]), float(t[-1]))
        return (
            self._resolve_fft_time_effective_params(p, len(sig)),
            effective_time_range,
        )

    def _fft_time_cache_key(self, params):
        """Build the LRU cache key from compute-relevant fields ONLY.

        Display options (``amplitude_mode``, ``cmap``, ``dynamic``,
        ``freq_auto``, ``freq_min``, ``freq_max``) are deliberately
        absent so toggling them re-renders without recomputing.
        """
        nfft = params.get('nfft_effective', params.get('nfft'))
        if nfft is None or str(nfft) == '自动':
            raise ValueError('FFT-vs-Time cache key requires effective nfft')
        return (
            params.get('fid'),
            params.get('channel'),
            tuple(params.get('time_range') or (None, None)),
            float(params.get('fs')),
            int(nfft),
            str(params.get('window')),
            float(params.get('overlap')),
            bool(params.get('remove_mean')),
            float(params.get('db_reference', 1.0)),
        )

    def _fft_time_cache_get(self, key):
        if key not in self._fft_time_cache:
            return None
        # LRU: pop and reinsert so the most-recently-used entry is at
        # the OrderedDict tail.
        value = self._fft_time_cache.pop(key)
        self._fft_time_cache[key] = value
        return value

    def _fft_time_cache_put(self, key, result):
        if key in self._fft_time_cache:
            self._fft_time_cache.pop(key)
        self._fft_time_cache[key] = result
        while len(self._fft_time_cache) > self._fft_time_cache_capacity:
            # popitem(last=False) is the LRU eviction (oldest first).
            self._fft_time_cache.popitem(last=False)

    def _fft_time_cache_clear_for_fid(self, fid):
        """Drop every cache entry keyed under ``fid``.

        Used by per-file invalidation hooks (file load, single-file
        close, time-axis rebuild, custom-x change) so a freshly
        modified file does not see stale results from a prior open.
        Cache key shape (per ``_fft_time_cache_key``):
        ``(fid, channel, time_range_tuple, fs, nfft, window, overlap,
        remove_mean, db_reference)`` — ``key[0]`` is the fid.
        """
        keys = [k for k in self._fft_time_cache if k[0] == fid]
        for k in keys:
            self._fft_time_cache.pop(k, None)

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

    def do_fft_time(self, force=False):
        """Compute and render the FFT-vs-Time spectrogram(s) for the active view.

        V7b: computes the WHOLE active view — every pane, not just the
        focused one. Each pane carries one heatmap source ``(fid, ch)``.
        For every pane we build the analysis cache key and either:
          * cache HIT  → render that result on the pane's own canvas
            immediately (synchronous, no thread); or
          * cache MISS → enqueue a ``(pane_idx, fid, ch)`` job.
        The focused pane is enqueued first so the user's primary chart
        appears first. The miss jobs run sequentially on ONE shared worker
        QThread (no concurrent threads): :meth:`_start_next_fft_time_job`
        dispatches the head job, :meth:`_on_fft_time_finished` caches +
        renders onto ``page.pane_canvas(job_pane_idx)``, then
        :meth:`_on_fft_time_thread_done` drives the next job. A single
        pane (non-split) view yields exactly one job, so behaviour is
        identical to the V7 focused-single-pane path.

        ``force=True`` bypasses the LRU cache. Re-entry while a worker is
        still running is dropped with a ``正在计算…`` status message
        (the whole new request is discarded; we do not interleave a new
        view's jobs into a running queue). On compute failure the OLD
        chart for that pane stays visible — the failed handler does NOT
        clear the canvas — and the next queued job still runs.
        """
        # V7 Step 5: capture the active view's params + per-pane sources so a
        # later view switch renders from analysis_caches.
        self._capture_active_analysis_view('fft_time')
        # Re-entry guard: a previous compute / queue is still on the thread.
        # We drop the whole new request rather than interleaving jobs.
        if (
            self._fft_time_thread is not None
            and self._fft_time_thread.isRunning()
        ):
            self._emit_compute_feedback(
                ComputeOutcome(),
                busy=True,
                section_label="FFT-vs-Time",
            )
            return
        mgr = self.analysis_managers['fft_time']
        state = mgr.get(mgr.active)
        page = self._analysis_page('fft_time')
        p = self.inspector.fft_time_ctx.get_params()
        cache = self.analysis_caches['fft_time']

        # Build the job list: focused pane first so its chart appears first.
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
            cached = None
            analysis_key = None
            render_p = p
            time_range = self._pane_time_range_for('fft_time', pane_idx)
            prepared = self._fft_time_effective_params_for_source(
                p, fid, ch, time_range)
            if prepared is not None:
                render_p, effective_time_range = prepared
                analysis_key = self._fft_time_analysis_cache_key(
                    fid, ch, render_p, pane_idx)
                if not force:
                    cached = cache.get(analysis_key)
                    if cached is None:
                        key_params = dict(
                            render_p,
                            fid=fid,
                            channel=ch,
                            time_range=effective_time_range,
                        )
                        cached = self._fft_time_cache_get(
                            self._fft_time_cache_key(key_params))
                    if cached is not None and analysis_key is not None:
                        cache.put(analysis_key, cached)
            if cached is not None:
                self._render_fft_time_on(
                    page.pane_canvas(pane_idx), cached, render_p)
                outcome.cached += 1
            else:
                queue.append((pane_idx, fid, ch))

        if not queue:
            if not any_source:
                # No pane has a source selected → legacy single-source path
                # so the standalone-signal UX + existing tests are unchanged.
                self._do_fft_time_single(force=force)
                return
            self._emit_compute_feedback(outcome, section_label="FFT-vs-Time")
            return

        self._fft_time_queue = queue
        self._fft_time_outcome = outcome
        self._start_next_fft_time_job()

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
        from ...signal import SpectrogramParams
        self._fft_time_queue = []
        page = self._analysis_page('fft_time')
        pane_idx = page.focused_index()
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        # Pre-flight uniformity gate (T2, 2026-04-26): rebuild a non-uniform
        # time axis BEFORE dispatching the worker.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            return
        # The rebuild may have rewritten ``fd.time_array``; re-fetch.
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        p = self.inspector.fft_time_ctx.get_params()
        if self.inspector.top.range_enabled():
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]; sig = sig[m]
            if len(sig) < 2:
                self.toast("当前范围内样本不足", "warning")
                return
            time_range = (float(lo), float(hi))
        else:
            time_range = (float(t[0]), float(t[-1]))
        p = self._resolve_fft_time_effective_params(p, len(sig))
        key_params = dict(p, fid=fid, channel=ch, time_range=time_range)
        key = self._fft_time_cache_key(key_params)
        analysis_key = self._fft_time_analysis_cache_key(
            fid, ch, p, pane_idx)
        cached = None if force else self._fft_time_cache_get(key)
        if cached is None and not force:
            cached = self.analysis_caches['fft_time'].get(analysis_key)
        if cached is not None:
            # Cache hit stays on the main thread — no worker needed.
            self.analysis_caches['fft_time'].put(analysis_key, cached)
            self._render_fft_time(cached, p)
            self.statusBar.showMessage(
                "使用缓存结果 · "
                f"{cached.metadata.get('frames', 0)} frames · "
                f"NFFT {p['nfft_effective']}"
            )
            return
        params = SpectrogramParams(
            fs=float(p['fs']),
            nfft=int(p['nfft_effective']),
            window=str(p['window']),
            overlap=float(p['overlap']),
            remove_mean=bool(p['remove_mean']),
            db_reference=float(p.get('db_reference', 1.0)),
        )
        unit = ''
        if fd is not None and hasattr(fd, 'channel_units'):
            unit = fd.channel_units.get(ch, '') or ''
        self._fft_time_pending = {
            'cache_key': key,
            'render_params': p,
            'analysis_key': analysis_key,
            'pane_idx': pane_idx,
        }

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ...signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        self._start_fft_time_worker(job)

    def _start_next_fft_time_job(self):
        """Dispatch the head job of the FFT-vs-Time queue, skipping jobs whose
        source has become unfetchable. Stops (queue empty) when none remain."""
        page = self._analysis_page('fft_time')
        while self._fft_time_queue:
            pane_idx, fid, ch = self._fft_time_queue.pop(0)
            time_range = self._pane_time_range_for('fft_time', pane_idx)
            if self._dispatch_fft_time_job(
                pane_idx, fid, ch, time_range=time_range
            ):
                return
        # Queue drained.
        self._finish_fft_time_outcome_feedback()

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

    def _dispatch_fft_time_job(
        self, pane_idx, fid, ch, force=False,
        time_range=_INSPECTOR_TIME_RANGE,
    ):
        """Fetch + range-gate the ``(fid, ch)`` source, then start the shared
        worker for it, rendering onto ``page.pane_canvas(pane_idx)`` when done.
        Returns True if a worker was started, False if the source was skipped
        (caller advances to the next queued job)."""
        from ...signal import SpectrogramParams
        fid, ch, t, sig, fd = self._fft_time_signal_for((fid, ch))
        if sig is None:
            self._record_fft_time_skip("源通道缺失")
            return False
        if len(sig) < 2:
            self._record_fft_time_skip("信号过短")
            return False
        # Pre-flight uniformity gate (T2, 2026-04-26): rebuild a non-uniform
        # time axis BEFORE dispatching the worker. Best-effort per pane —
        # a failed rebuild skips this job, not the whole queue.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            self._record_fft_time_skip("时间轴非均匀")
            return False
        # The rebuild may have rewritten ``fd.time_array``; re-fetch.
        fid, ch, t, sig, fd = self._fft_time_signal_for((fid, ch))
        if sig is None:
            self._record_fft_time_skip("源通道缺失")
            return False
        if len(sig) < 2:
            self._record_fft_time_skip("信号过短")
            return False
        p = self.inspector.fft_time_ctx.get_params()
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
                return False
            effective_time_range = rng
        else:
            effective_time_range = (float(t[0]), float(t[-1]))
        p = self._resolve_fft_time_effective_params(p, len(sig))
        key_params = dict(
            p, fid=fid, channel=ch, time_range=effective_time_range)
        key = self._fft_time_cache_key(key_params)
        analysis_key = self._fft_time_analysis_cache_key(
            fid, ch, p, pane_idx)
        # SpectrogramParams is the cache key on the analyzer side; build
        # it from compute-relevant fields only.
        params = SpectrogramParams(
            fs=float(p['fs']),
            nfft=int(p['nfft_effective']),
            window=str(p['window']),
            overlap=float(p['overlap']),
            remove_mean=bool(p['remove_mean']),
            db_reference=float(p.get('db_reference', 1.0)),
        )
        unit = ''
        if fd is not None and hasattr(fd, 'channel_units'):
            unit = fd.channel_units.get(ch, '') or ''
        # Stash everything the finished handler needs to cache + render the
        # RIGHT pane. ``pane_idx`` is the load-bearing field: the finished
        # handler renders onto ``page.pane_canvas(pane_idx)``, never pane 0.
        self._fft_time_pending = {
            'cache_key': key,
            'render_params': p,
            'analysis_key': analysis_key,
            'pane_idx': pane_idx,
        }

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ...signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        self._start_fft_time_worker(job)
        return True

    def _start_fft_time_worker(self, job):
        """Wire + start the shared FFT-vs-Time worker/QThread for ``job``.
        The caller has already populated ``self._fft_time_pending`` (incl. the
        render ``pane_idx``)."""
        from ..analysis_worker import AnalysisComputeWorker
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QThread = getattr(_pkg, 'QThread', QThread) if _pkg is not None else QThread
        worker = AnalysisComputeWorker(job)
        thread = _QThread(self)
        worker.moveToThread(thread)
        # Standard QThread cleanup chain. The order matters:
        #   started -> run        : entry point lives on the worker thread
        #   finished/failed -> quit: stops the event loop on the worker thread
        #   finished -> handler   : runs on the MAIN thread (AutoConnection
        #                           across threads = QueuedConnection)
        #   thread.finished -> deleteLater (worker, thread)
        #   thread.finished -> _on_fft_time_thread_done : clears refs + pumps
        #                       the next queued job
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_fft_time_finished)
        worker.failed.connect(self._on_fft_time_failed)
        worker.progress.connect(self._on_fft_time_progress)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_fft_time_thread_done)
        self._fft_time_thread = thread
        self._fft_time_worker = worker
        pending = getattr(self, '_fft_time_pending', None) or {}
        p = pending.get('render_params') or {}
        nfft = p.get('nfft_effective', p.get('nfft'))
        if nfft is not None:
            self.statusBar.showMessage(f"正在计算… · NFFT {nfft}")
        else:
            self.statusBar.showMessage("正在计算…")
        thread.start()

    def _render_fft_time(self, result, p):
        """Apply display-only options and draw on the primary canvas.

        Display fields are NOT part of the cache key; this is the sole
        place they are read.
        """
        self._render_fft_time_on(self.canvas_fft_time, result, p)

    def _render_fft_time_on(self, canvas, result, p):
        """Multi-pane variant: render ``result`` on an arbitrary FFT-vs-Time
        heatmap canvas with display options from ``p``."""
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
        canvas.plot_result(
            result,
            amplitude_mode=p['amplitude_mode'],
            cmap=p['cmap'],
            z_auto=bool(p.get('z_auto', False)),
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
        )
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)

    def _on_fft_time_cursor_info(self, text):
        """Surface PgHeatmapCanvas hover readout in the status bar.

        Empty text (cursor outside the heatmap scene or before a result
        is plotted) restores the active-file summary so the bar does not
        remain blank. Reviewer Important #1.
        """
        if text:
            self.statusBar.showMessage(text)
        else:
            # Restore default status when the cursor leaves the plot.
            self._update_info()

    # ---- FFT vs Time worker callbacks (Plan Task 7) ----
    def _on_fft_time_finished(self, result):
        """Worker reported success — cache + render on the main thread.

        Runs on the main thread (Qt cross-thread signals default to
        ``QueuedConnection``), so it is safe to touch the LRU cache and
        the pyqtgraph canvas here.
        """
        pending = getattr(self, '_fft_time_pending', None) or {}
        key = pending.get('cache_key')
        p = pending.get('render_params')
        analysis_key = pending.get('analysis_key')
        pane_idx = pending.get('pane_idx')
        if key is not None:
            self._fft_time_cache_put(key, result)
        if analysis_key is not None:
            self.analysis_caches['fft_time'].put(analysis_key, result)
        outcome = getattr(self, '_fft_time_outcome', None)
        if outcome is not None:
            outcome.computed += 1
        if p is not None:
            # V7b: render onto the SPECIFIC pane this job was computed for,
            # never the focused pane / pane 0. ``pane_idx`` falls back to the
            # primary canvas only when the queue never set it (legacy path).
            page = self._analysis_page('fft_time')
            if pane_idx is not None and pane_idx < page.pane_count():
                self._render_fft_time_on(page.pane_canvas(pane_idx), result, p)
            else:
                self._render_fft_time(result, p)
        nfft = getattr(getattr(result, 'params', None), 'nfft', None)
        suffix = f" · NFFT {int(nfft)}" if nfft is not None else ""
        self.statusBar.showMessage(
            f"FFT vs Time 完成 · {result.metadata.get('frames', 0)} frames"
            f"{suffix}"
        )

    def _on_fft_time_failed(self, message):
        """Worker reported failure — keep the previous chart on screen.

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

    def _on_fft_time_progress(self, current, total):
        """Optional per-frame progress hook.

        Phase 1 has no progress dialog — this exists so future tasks
        (T8 export, T9 progress bar) can subscribe without rewiring.
        Signature mirrors the analyzer's ``progress_callback`` contract.
        """
        # Intentionally no UI updates in Phase 1. A status-bar update
        # here would compete with ``正在计算…`` and the cursor readout,
        # which is more user-visible noise than value.
        pass

    def _on_fft_time_thread_done(self):
        """Worker thread emitted ``finished`` — clear refs, then pump the
        next queued job.

        Both ``worker`` and ``thread`` are scheduled for deleteLater
        before this slot fires (per the connect order in
        :meth:`_dispatch_fft_time_job`); we drop the local references so the
        re-entry guard in :meth:`do_fft_time` lets the next compute through,
        then dispatch the next job in the split queue (V7b). The refs MUST be
        cleared before :meth:`_start_next_fft_time_job` so the new job's
        ``thread.isRunning()`` re-entry guard does not see the just-finished
        thread.
        """
        self._fft_time_thread = None
        self._fft_time_worker = None
        if self._fft_time_queue:
            self._start_next_fft_time_job()
        else:
            self._finish_fft_time_outcome_feedback()
