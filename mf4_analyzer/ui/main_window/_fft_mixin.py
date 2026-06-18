"""FFTMixin: FFT spectrum compute, cache, and render methods for MainWindow."""

import numpy as np

from PyQt5.QtWidgets import QApplication, QMessageBox

from ...signal import FFTAnalyzer, resolve_nfft, energy_band_fmax
from ._sentinel import _INSPECTOR_TIME_RANGE


class FFTMixin:
    """Domain mixin: FFT spectrum calculation, caching, and rendering.

    All methods here become MainWindow instance methods.  They may only
    reference ``self.*`` attributes created in ``MainWindow.__init__`` or
    ``_init_ui``.

    Sentinel note: ``_INSPECTOR_TIME_RANGE`` is imported from
    ``._sentinel`` (the same object as in window.py), so identity
    comparisons across mixin and window code work correctly.
    """

    @staticmethod
    def _resolve_fft_effective_params(fft_params, n_samples, fs):
        """Return FFT spectrum params with effective NFFT when auto is resolvable.

        Averaged and peak-hold spectrum modes need a concrete segment length.
        Single-frame auto keeps the legacy whole-segment ``nfft=None``
        semantics, letting ``FFTAnalyzer.compute_fft`` use the signal length.
        """
        out = dict(fft_params)
        nfft = out.get('nfft')
        auto = (
            nfft is None
            or out.get('nfft_mode') == 'auto'
            or str(nfft) == '自动'
        )
        avg_mode = out.get('avg_mode', '单帧')
        if auto:
            out['nfft_mode'] = 'auto'
            out['t_win_s'] = float(out.get('t_win_s', 1.5))
            if avg_mode in {'线性平均', '峰值保持'}:
                overlap = float(out.get('avg_overlap', 50)) / 100.0
                effective = resolve_nfft(
                    fs,
                    n_samples,
                    out.get('t_win_s', 1.5),
                    overlap,
                )
                out['nfft'] = int(effective)
                out['nfft_effective'] = int(effective)
            else:
                out['nfft'] = None
                out['nfft_effective'] = None
        else:
            effective = int(nfft)
            out['nfft'] = effective
            out['nfft_effective'] = effective
            out['nfft_mode'] = 'fixed'
        return out

    @staticmethod
    def _fft_compute_cache_params(fft_params):
        return {
            'window': fft_params.get('window'),
            'nfft': fft_params.get('nfft_effective', fft_params.get('nfft')),
            'avg_mode': fft_params.get('avg_mode', '单帧'),
            'avg_overlap': fft_params.get('avg_overlap', 50),
        }

    def _fft_analysis_cache_key(self, fid, ch, fft_params, time_range):
        params = self._fft_compute_cache_params(fft_params)
        params['time_range'] = time_range
        return self.analysis_caches['fft'].make_key(fid, ch, params)

    def _fft_effective_params_for_source(self, fft_params, fid, ch, time_range):
        sig, fs = self._fft_fetch_signal(fid, ch, time_range=time_range)
        if sig is None or fs is None or len(sig) <= 0:
            return dict(fft_params)
        return self._resolve_fft_effective_params(fft_params, len(sig), fs)

    def _fft_compute_arrays(self, sig, fs, fft_params):
        """Run the FFT compute branch (Welch avg / peak-hold / single-frame)
        on a single signal, returning raw display-independent ``(freq, amp,
        psd)``. Algorithm calls are byte-identical to the legacy do_fft."""
        fft_params = self._resolve_fft_effective_params(
            fft_params, len(sig), fs)
        win = fft_params['window']
        nfft = fft_params.get('nfft_effective', fft_params.get('nfft'))
        avg_mode = fft_params.get('avg_mode', '单帧')
        overlap_pct = int(fft_params.get('avg_overlap', 50))
        avg_overlap = max(0.0, min(0.95, overlap_pct / 100.0))
        if avg_mode == '线性平均':
            freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win, int(nfft), avg_overlap)
        elif avg_mode == '峰值保持':
            freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap)
            psd = amp ** 2
        else:
            freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
            _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)
        return freq, amp, psd

    def _fft_fetch_signal(self, fid, ch, time_range=_INSPECTOR_TIME_RANGE):
        """Fetch + range-gate a single FFT source's signal. Returns
        ``(sig, fs)`` or ``(None, None)`` when unavailable."""
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        sig = fd.data[ch].values
        t = fd.time_array
        if (
            time_range is _INSPECTOR_TIME_RANGE
            and self.inspector.top.range_enabled()
        ):
            time_range = self.inspector.top.range_values()
        if time_range is _INSPECTOR_TIME_RANGE:
            time_range = None
        if time_range is not None and t is not None:
            _t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return sig, fd.fs

    def do_fft(self):
        """Compute the ACTIVE FFT view: every source of every pane.

        Compute semantics (spec §4): the button computes the whole active
        view. Each pane overlays N curves (its sources); each source is cached
        on a (fid, ch, compute-params) key so re-render / view-switch is free.

        Back-compat: when the focused pane has no navigator-checked sources
        (or they are not fetchable), fall back to the legacy single-signal
        ``_get_sig()`` path so the existing single-signal UX + tests are
        unchanged.
        """
        self._capture_active_analysis_view('fft')
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        page = self.chart_stack.page_fft
        fft_params = self.inspector.fft_ctx.current_params()
        cache = self.analysis_caches['fft']
        colors = self._analysis_channel_color_map()

        any_rendered = False
        any_multi = False
        for pane_idx in range(page.pane_count()):
            if pane_idx >= len(state.panes):
                break
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_multi = True
            entries = []
            time_range = self._pane_time_range_for('fft', pane_idx)
            for fid, ch in sources:
                sig, fs = self._fft_fetch_signal(
                    fid, ch, time_range=time_range)
                if sig is None or len(sig) < 10:
                    continue
                fd = self.files.get(fid)
                if not self._check_uniform_or_prompt(fd, 'fft'):
                    continue
                sig, fs = self._fft_fetch_signal(
                    fid, ch, time_range=time_range)
                if sig is None or len(sig) < 10:
                    continue
                effective_params = self._resolve_fft_effective_params(
                    fft_params, len(sig), fs)
                key = self._fft_analysis_cache_key(
                    fid, ch, effective_params, time_range)
                result = cache.get(key)
                if result is None:
                    try:
                        result = self._fft_compute_arrays(
                            sig, fs, effective_params)
                    except Exception as e:
                        QMessageBox.critical(self, 'FFT错误', str(e))
                        continue
                    cache.put(key, result)
                entries.append(self._fft_entry_from_cache(
                    result, fid, ch, colors.get((fid, ch)),
                    time_range=time_range))
            if entries:
                self._plot_fft_entries(entries, page.pane_canvas(pane_idx))
                any_rendered = True

        if any_multi:
            if any_rendered:
                self.statusBar.showMessage('FFT 完成')
                self.toast('FFT 完成', 'success')
            return
        # ---- legacy single-signal fallback (no navigator-checked sources) ----
        self._do_fft_single()

    def _do_fft_single(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10:
            self.toast("请选择有效信号", "warning"); return
        # Pre-flight: route non-uniform axes through the rebuild popover
        # BEFORE running the FFT. ``compute_fft`` itself does not consume
        # ``t`` (it samples by index + fs), so the FFT path used to
        # silently produce garbage from a jittered axis -- this gate
        # makes the FFT vs Time pre-flight (H1 root cause) consistent
        # across all spectral entry points (H3 mitigation).
        mode = self.toolbar.current_mode()
        ctx_mode = 'fft' if mode == 'fft' else 'order'
        sig_data = (
            self.inspector.fft_ctx.current_signal()
            if ctx_mode == 'fft'
            else self.inspector.order_ctx.current_signal()
        )
        fid = sig_data[0] if sig_data else None
        fd = self.files.get(fid) if fid else None
        if not self._check_uniform_or_prompt(fd, ctx_mode):
            return
        # Re-fetch t/sig: the popover Accept branch rebuilt
        # ``fd.time_array`` to ``arange(n)/fs``, so the local ``t`` we
        # captured before the popover is now stale.
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10:
            self.toast("请选择有效信号", "warning"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]
            sig = sig[m]
        fft_params = self.inspector.fft_ctx.current_params()
        fs = self.inspector.fft_ctx.fs()
        fft_params = self._resolve_fft_effective_params(
            fft_params, len(sig), fs)
        win = fft_params['window']
        nfft = fft_params['nfft']
        overlap = fft_params['overlap']

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            freq, amp, _psd = self._fft_compute_arrays(sig, fs, fft_params)

            x_auto = bool(fft_params.get('x_auto', fft_params.get('autoscale', True)))
            x_min = float(fft_params.get('x_min', 0.0))
            x_max = float(fft_params.get('x_max', 0.0))
            if x_auto:
                xlim = (0.0, self._fft_auto_xlim(freq, amp))
            elif x_max > x_min:
                xlim = (x_min, x_max)
            else:
                xlim = (0.0, fs / 2)
            y_auto = bool(fft_params.get('y_auto', True))
            y_min = float(fft_params.get('y_min', 0.0))
            y_max = float(fft_params.get('y_max', 0.0))

            # Wave 2 / SP2 / Task 2.3: per-subplot Linear/dB toggle.
            amp_y = fft_params.get('amp_y', 'Linear')
            if amp_y == 'dB':
                amp_disp = 20 * np.log10(
                    np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)
                )
            else:
                amp_disp = amp

            sig_label = self.inspector.fft_ctx.combo_sig.currentText()
            entry = {
                'label': sig_label,
                'color': '#2563eb',
                'freq': freq,
                'amp': amp_disp,
                'amp_for_xlim': amp,
                'time': t,
                'signal': sig,
            }
            self.canvas_fft.plot_spectra(
                [entry],
                xlim=xlim,
                amp_label='Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
                title=f'FFT - {sig_label} (窗:{win}, NFFT:{nfft or "auto"})',
                y_auto=y_auto, y_min=y_min, y_max=y_max,
            )
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
            self._remember_batch_preset(
                "当前 FFT",
                "fft",
                self.inspector.fft_ctx.current_signal(),
                {
                    'fs': fs,
                    'window': win,
                    'nfft': nfft,
                    'overlap': overlap,
                },
            )
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
            self.toast(f"FFT 完成 · 峰值 {freq[pi]:.2f} Hz", "success")
        except Exception as e:
            QMessageBox.critical(self, 'FFT错误', str(e))
