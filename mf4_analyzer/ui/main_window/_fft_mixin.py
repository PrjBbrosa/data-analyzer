"""FFTMixin: FFT spectrum compute, cache, and render methods for MainWindow."""

import inspect

import numpy as np

from PyQt5.QtCore import QEventLoop
from PyQt5.QtWidgets import QApplication, QMessageBox

from ... import db_reference
from ...signal import (
    AutoNfftBlockedError,
    FFTAnalyzer,
    energy_band_fmax,
    nfft_facts_signature,
    nfft_facts_signature_from_decision,
    raise_if_auto_nfft_blocked,
    requested_auto_nfft,
    resolve_auto_nfft,
)
from ...signal.analysis_defaults import (
    AUTO_NFFT_POLICY_VERSION,
    DEFAULT_FFT_T_WIN_S,
    normalize_overlap_fraction,
)
from ...signal.fft import build_fft_effective_facts
from ...signal.spectrogram import SpectrogramAnalyzer
from ..compute_feedback import ComputeOutcome
from ._sentinel import _INSPECTOR_TIME_RANGE
from .ultraview_coordinator import notify_ultraview_plot

_SEGMENTED_AVG_MODES = frozenset({'线性平均', '峰值保持'})


def _fft_is_auto_nfft(fft_params):
    nfft = fft_params.get('nfft')
    return (
        nfft is None
        or fft_params.get('nfft_mode') == 'auto'
        or str(nfft) == '自动'
    )


def _auto_nfft_skip_reason(error):
    decision = getattr(error, 'decision', None)
    codes = tuple(getattr(decision, 'reasons', ()) or ())
    if 'insufficient_samples' in codes:
        return "样本不足无法自动确定 NFFT"
    if 'insufficient_time_frames' in codes:
        return "时间帧不足无法自动确定 NFFT"
    return "Auto-NFFT 不可计算"


def _blocked_auto_nfft_lines(decision):
    codes = tuple(getattr(decision, 'reasons', ()) or ())
    if 'insufficient_samples' in codes:
        return ("不可计算：可用样本不足 64",)
    if codes:
        return (f"不可计算：{', '.join(codes)}",)
    return ("不可计算：Auto-NFFT 无法给出分段长度",)


class _FftComputeResult(tuple):
    """``(freq, amp, psd)`` plus a frozen facts payload.

    Subclassing tuple keeps ``freq, amp, psd = result`` and
    ``_fft_entry_from_cache`` unpacking working for cached 3-tuples.
    """

    def __new__(cls, freq, amp, psd, effective=None):
        obj = tuple.__new__(cls, (freq, amp, psd))
        obj.effective = effective
        return obj


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
    def _amplitude_to_db(amp, reference):
        """Convert linear amplitude to dB relative to ``reference``.

        Delegates to ``SpectrogramAnalyzer.amplitude_to_db`` — the single
        authority for the ``20 * log10(max(amp, tiny) / ref)`` formula.
        Callers MUST pass an already-validated positive ``reference`` (spec
        §7 R3 / plan Task 6 Step 6.4) — e.g. a
        ``db_reference.DbReferenceResolution.value`` from
        ``resolve_db_reference``, whose priority chain guarantees a finite
        positive float at every branch (manual/metadata are gated by
        ``validate_reference``; catalog/generic/fallback are fixed positive
        constants). The old ``max(reference, 1e-12)`` denominator coercion
        is gone — spec §7 R3 forbids silently substituting an invalid
        reference; ``SpectrogramAnalyzer.amplitude_to_db`` itself raises on
        a non-positive reference instead. Display-only transform —
        ``amp_for_xlim`` (auto x-limit) is computed from the linear
        amplitude before calling this; numerator (amp) zero-protection
        stays inside that helper (``np.maximum(amp, tiny)``).
        """
        return SpectrogramAnalyzer.amplitude_to_db(amp, reference=float(reference))

    @staticmethod
    def _resolve_fft_effective_params(fft_params, n_samples, fs):
        """Return FFT spectrum params with effective NFFT when auto is resolvable.

        Averaged and peak-hold Auto consume ``resolve_auto_nfft``; they never
        copy the 4096 formula and never fall back to legacy ``resolve_nfft``.
        Single-frame auto keeps whole-selection ``nfft=None``.
        """
        out = dict(fft_params)
        # fs is a real compute input (FFTAnalyzer.compute_fft(sig, fs, ...)):
        # it sets the frequency axis and PSD scaling. Stamp the effective fs
        # (from fd.fs) onto the params here — the single point every cache-key
        # path flows through — so _fft_compute_cache_params can key on it. In
        # single-frame mode nfft stays None, so without fs in the key a Fs
        # change (e.g. after 重建时间轴) would hit the stale OLD-fs result.
        out['fs'] = float(fs)
        n_samples = int(n_samples)
        auto = _fft_is_auto_nfft(out)
        avg_mode = out.get('avg_mode', '单帧')
        out['nfft_decision'] = None
        if auto:
            out['nfft_mode'] = 'auto'
            out['t_win_s'] = float(out.get('t_win_s', DEFAULT_FFT_T_WIN_S))
            if avg_mode in _SEGMENTED_AVG_MODES:
                overlap = normalize_overlap_fraction(
                    out.get('avg_overlap', 50), default=50)
                decision = resolve_auto_nfft(
                    fs,
                    n_samples,
                    out['t_win_s'],
                    overlap,
                    purpose='fft_segmented',
                )
                out['nfft_decision'] = decision
                out['nfft_status'] = decision.status
                out['nfft_facts_signature'] = nfft_facts_signature_from_decision(
                    decision,
                    t_win_s=out['t_win_s'],
                    policy_version=AUTO_NFFT_POLICY_VERSION,
                )
                if decision.status == 'blocked' or decision.effective_nfft is None:
                    out['nfft'] = None
                    out['nfft_effective'] = None
                else:
                    out['nfft'] = int(decision.effective_nfft)
                    out['nfft_effective'] = int(decision.effective_nfft)
            else:
                out['nfft'] = None
                out['nfft_effective'] = None
                out['nfft_status'] = None
                out['nfft_facts_signature'] = nfft_facts_signature(
                    nfft_mode='auto',
                    requested_nfft=n_samples,
                    effective_nfft=n_samples,
                    n_samples=n_samples,
                )
        else:
            effective = int(out.get('nfft'))
            out['nfft'] = effective
            out['nfft_effective'] = effective
            out['nfft_mode'] = 'fixed'
            out['nfft_status'] = None
            out['nfft_facts_signature'] = nfft_facts_signature(
                nfft_mode='fixed',
                requested_nfft=effective,
                effective_nfft=effective,
                n_samples=n_samples,
            )
        return out

    @staticmethod
    def _fft_compute_cache_params(fft_params):
        return {
            'window': fft_params.get('window'),
            'nfft': fft_params.get('nfft_effective', fft_params.get('nfft')),
            # fs is a compute input (frequency axis + PSD scaling). Stamped by
            # _resolve_fft_effective_params from fd.fs; keyed here so a Fs change
            # in single-frame mode (nfft=None) still invalidates the cache.
            'fs': fft_params.get('fs'),
            'avg_mode': fft_params.get('avg_mode', '单帧'),
            'avg_overlap': fft_params.get('avg_overlap', 50),
            'weighting': str(fft_params.get('weighting', 'None')),
            # D8: same effective NFFT with a different t_win_s / Auto vs Fixed
            # must miss. Display-only knobs stay out of this dict.
            'nfft_facts_signature': fft_params.get('nfft_facts_signature'),
        }

    @staticmethod
    def _call_fft_analyzer(func, *args, weighting='None', **kwargs):
        try:
            accepts_weighting = 'weighting' in inspect.signature(func).parameters
        except (TypeError, ValueError):
            accepts_weighting = False
        if accepts_weighting:
            kwargs['weighting'] = weighting
        return func(*args, **kwargs)

    def _fft_analysis_cache_key(self, fid, ch, fft_params, time_range):
        params = self._fft_compute_cache_params(fft_params)
        params['time_range'] = time_range
        return self.analysis_caches['fft'].make_key(fid, ch, params)

    def _fft_effective_params_for_source(self, fft_params, fid, ch, time_range):
        sig, fs = self._fft_fetch_signal(fid, ch, time_range=time_range, params=fft_params)
        if sig is None or fs is None or len(sig) <= 0:
            out = dict(fft_params)
            # Stamp fs when available so the fallback key distinguishes signals
            # at different sample-rates (aligns with the fft_time compute-params
            # contract where fs is always included; _analysis_compute_params('fft')
            # omits fs, so without this stamp fs=None enters the cache key and a
            # sample-rate change on an unavailable source goes undetected).
            if fs is not None:
                out['fs'] = float(fs)
            auto = _fft_is_auto_nfft(out)
            avg_mode = out.get('avg_mode', '单帧')
            out['nfft_decision'] = None
            if auto:
                out['nfft_mode'] = 'auto'
                out['t_win_s'] = float(out.get('t_win_s', DEFAULT_FFT_T_WIN_S))
                out['nfft'] = None
                out['nfft_effective'] = None
                requested = None
                if avg_mode in _SEGMENTED_AVG_MODES and fs is not None:
                    try:
                        requested = requested_auto_nfft(
                            float(fs), out['t_win_s'], purpose='fft_segmented',
                        )
                    except ValueError:
                        requested = None
                    out['nfft_facts_signature'] = nfft_facts_signature(
                        nfft_mode='auto',
                        policy_version=AUTO_NFFT_POLICY_VERSION,
                        t_win_s=out['t_win_s'],
                        requested_nfft=requested,
                    )
                else:
                    out['nfft_facts_signature'] = nfft_facts_signature(
                        nfft_mode='auto',
                    )
            else:
                try:
                    effective = int(out.get('nfft'))
                except (TypeError, ValueError):
                    effective = None
                out['nfft_mode'] = 'fixed'
                out['nfft_facts_signature'] = nfft_facts_signature(
                    nfft_mode='fixed',
                    requested_nfft=effective,
                    effective_nfft=effective,
                )
            return out
        return self._resolve_fft_effective_params(fft_params, len(sig), fs)

    def _fft_compute_arrays(self, sig, fs, fft_params, *, time=None):
        """Run the FFT compute branch (Welch avg / peak-hold / single-frame)
        on a single signal, returning raw display-independent ``(freq, amp,
        psd)`` plus frozen effective facts. Algorithm calls are byte-identical
        to the legacy do_fft; the extra facts payload rides on a tuple
        subclass so existing 3-unpack sites keep working."""
        fft_params = self._resolve_fft_effective_params(
            fft_params, len(sig), fs)
        win = fft_params['window']
        avg_mode = fft_params.get('avg_mode', '单帧')
        avg_overlap = normalize_overlap_fraction(
            fft_params.get('avg_overlap', 50), default=50)
        weighting = str(fft_params.get('weighting', 'None'))
        auto = fft_params.get('nfft_mode') == 'auto'
        decision = fft_params.get('nfft_decision')
        decision_for_facts = None
        if auto and avg_mode in _SEGMENTED_AVG_MODES:
            if decision is None:
                raise ValueError("Auto-NFFT decision missing for segmented FFT")
            raise_if_auto_nfft_blocked(decision)
            nfft = int(decision.effective_nfft)
            nfft_requested = int(decision.requested_nfft)
            decision_for_facts = decision
        else:
            nfft = fft_params.get('nfft_effective', fft_params.get('nfft'))
            if avg_mode == '单帧':
                nfft_requested = len(sig) if auto else int(nfft)
            else:
                nfft_requested = int(nfft)
        if avg_mode == '线性平均':
            # The Inspector presents the requested/actual NFFT and resolution
            # change. Pass the real Welch segment length so this expected GUI
            # adjustment does not also emit the direct-API clamp warning.
            nfft = min(int(nfft), len(sig))
            freq, amp, psd = self._call_fft_analyzer(
                FFTAnalyzer.compute_averaged_fft,
                sig, fs, win, int(nfft), avg_overlap,
                weighting=weighting)
        elif avg_mode == '峰值保持':
            freq, amp = self._call_fft_analyzer(
                FFTAnalyzer.compute_peak_hold_fft,
                sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap,
                weighting=weighting)
            psd = amp ** 2
        else:
            freq, amp = self._call_fft_analyzer(
                FFTAnalyzer.compute_fft, sig, fs, win, nfft,
                weighting=weighting)
            _, psd = self._call_fft_analyzer(
                FFTAnalyzer.compute_psd, sig, fs, win, nfft,
                weighting=weighting)
        facts = build_fft_effective_facts(
            sig, fs,
            window=win,
            nfft=nfft,
            avg_mode=avg_mode,
            overlap=avg_overlap,
            weighting=weighting,
            nfft_requested=nfft_requested,
            # Welch's half-spectrum length cannot distinguish odd and even
            # segment lengths (1281 and 1280 both yield 640 bins). Its actual
            # segment length above is authoritative for the displayed facts.
            freq=None if avg_mode == '线性平均' else freq,
            time=time,
            time_axis=fft_params.get('analysis_time_axis'),
            nfft_mode=fft_params.get('nfft_mode'),
            decision=decision_for_facts,
        )
        return _FftComputeResult(freq, amp, psd, facts)

    def _sync_fft_effective_facts(self, state=None):
        """Re-fill the Inspector facts card from every focused-pane source."""
        from dataclasses import replace

        ctx = self.inspector.fft_ctx
        if state is None:
            mgr = self.analysis_managers.get('fft')
            if mgr is None or not mgr.views:
                ctx.clear_effective_facts()
                return
            state = mgr.get(mgr.active)
        page = self._analysis_page('fft')
        idx = page.focused_index()
        if state is None or not (0 <= idx < len(state.panes)):
            ctx.clear_effective_facts()
            return
        pane = state.panes[idx]
        sources = list(pane.sources)
        if not sources:
            ctx.clear_effective_facts()
            return
        time_range = self._pane_time_range_for('fft', idx)
        fft_params = self.inspector.fft_ctx.compute_params()
        groups = []
        extra_warnings = []
        any_content = False
        for fid, ch in sources:
            header = f"{fid} · {ch}"
            sig, _fs = self._fft_fetch_signal(fid, ch, time_range=time_range)
            params = self._fft_effective_params_for_source(
                fft_params, fid, ch, time_range,
            )
            decision = params.get('nfft_decision')
            blocked = (
                params.get('nfft_status') == 'blocked'
                or getattr(decision, 'status', None) == 'blocked'
            )
            if blocked:
                groups.append((header, None, _blocked_auto_nfft_lines(decision)))
                any_content = True
                continue
            key = self._fft_analysis_cache_key(fid, ch, params, time_range)
            result = self.analysis_caches['fft'].get(key)
            facts = getattr(result, 'effective', None) if result is not None else None
            if facts is None:
                continue
            health, _fs_values = self._effective_facts_health(
                sig, fid=fid, sources=sources,
            )
            health["time_axis"] = getattr(facts, "time_axis", None)
            try:
                facts = replace(facts, **health)
            except TypeError:
                pass
            groups.append((header, facts, ()))
            any_content = True
        groups = [item for item in groups if item[1] is not None or item[2]]
        _health, fs_values = self._effective_facts_health(
            None, sources=sources,
        )
        if _health.get('fs_conflict') and fs_values:
            pretty = ", ".join(f"{v:g} Hz" for v in fs_values)
            extra_warnings.append(f"多源 Fs 冲突：{pretty}")
        if not any_content or not groups:
            ctx.clear_effective_facts()
            return
        if len(groups) == 1 and groups[0][1] is not None:
            ctx.set_effective_facts(groups[0][1], extra_warnings)
            return
        setter = getattr(ctx, 'set_effective_facts_groups', None)
        if callable(setter):
            setter(groups, extra_warnings)
            return
        facts = next((item[1] for item in groups if item[1] is not None), None)
        if facts is None:
            ctx.clear_effective_facts()
            return
        ctx.set_effective_facts(facts, extra_warnings)

    def _fft_time_facts_for_source(self, fid, ch, time_range, params):
        from ...analysis_time_axis import prepare_analysis_time_axis
        fd = self.files[fid]
        t, sig = fd.time_array, fd.data[ch].values
        if time_range is not None:
            t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return prepare_analysis_time_axis(
            t, fd.fs,
            time_source=getattr(fd, '_time_source', 'column'), materialize=False,
        )[2]

    def _fft_fetch_signal(self, fid, ch, time_range=_INSPECTOR_TIME_RANGE, *, params=None):
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
            t, sig = self._mask_time_range(t, sig, time_range=time_range)
        from ...analysis_time_axis import prepare_analysis_time_axis
        if params is None:
            params = self.inspector.fft_ctx.compute_params()
        _axis, fs, _facts = prepare_analysis_time_axis(
            t, fd.fs, materialize=False)
        return sig, fs

    def _fft_preview_sources(self):
        """Focused-pane ``(fid, ch)`` identities, else the inspector combo."""
        sources = []
        mgr = getattr(self, 'analysis_managers', None)
        fft_mgr = mgr.get('fft') if isinstance(mgr, dict) else None
        idx = 0
        if fft_mgr is not None and getattr(fft_mgr, 'views', None):
            state = fft_mgr.get(fft_mgr.active)
            page_fn = getattr(self, '_analysis_page', None)
            if callable(page_fn):
                page = page_fn('fft')
                focused = getattr(page, 'focused_index', None)
                if callable(focused):
                    idx = int(focused())
            if state is not None and 0 <= idx < len(state.panes):
                sources = list(state.panes[idx].sources)
        if sources:
            return sources, idx
        ctx = getattr(getattr(self, 'inspector', None), 'fft_ctx', None)
        current = getattr(ctx, 'current_signal', None)
        source = current() if callable(current) else None
        if source:
            return [source], idx
        return [], idx

    def _fft_preview_source_rows(self):
        """Per-source sample/fs rows for Auto-NFFT preview. Paint-path safe."""
        sources, idx = self._fft_preview_sources()
        if not sources:
            return []
        time_range = _INSPECTOR_TIME_RANGE
        pane_range = getattr(self, '_pane_time_range_for', None)
        if callable(pane_range):
            try:
                time_range = pane_range('fft', idx)
            except (TypeError, ValueError, AttributeError):
                time_range = _INSPECTOR_TIME_RANGE
        rows = []
        for source in sources:
            try:
                fid, ch = source
            except (TypeError, ValueError):
                continue
            sig, fs = self._fft_fetch_signal(fid, ch, time_range=time_range)
            n_samples = None
            if sig is not None and len(sig) >= 2:
                n_samples = int(len(sig))
            fs_val = None
            if fs is not None:
                try:
                    fs_val = float(fs)
                except (TypeError, ValueError):
                    fs_val = None
                if fs_val is None or not np.isfinite(fs_val) or fs_val <= 0.0:
                    fs_val = None
            rows.append({
                'fid': fid,
                'ch': ch,
                'n_samples': n_samples,
                'fs': fs_val,
            })
        return rows

    def _fft_preview_n_samples(self):
        """Sample count(s) for the FFT auto-NFFT summary, or ``None``.

        Pull-based hook registered via ``FFTContextual.set_auto_nfft_provider``.
        A single source still returns its (range-gated) integer length so
        existing callers keep working. Multiple pane sources return a list of
        ``{fid, ch, n_samples, fs}`` rows so preview can resolve each identity
        instead of copying the first source's NFFT. Returns ``None`` when
        unavailable. Never raises — it feeds a paint path.
        """
        try:
            rows = self._fft_preview_source_rows()
            if not rows:
                return None
            if len(rows) == 1:
                n_samples = rows[0].get('n_samples')
                if n_samples is None or int(n_samples) < 2:
                    return None
                return int(n_samples)
            return rows
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError):
            return None

    def _recompute_restored_fft_view(self, view_id):
        """Fill the FFT cache from persisted pane sources; plot only if active."""
        state = self._analysis_state_by_id("fft", view_id)
        if state is None:
            return
        fft_params = self._compute_params_overlay_state("fft", state)
        cache = self.analysis_caches["fft"]
        colors = self._analysis_channel_color_map()
        mgr = self.analysis_managers["fft"]
        is_active = mgr.get(mgr.active) is state
        plot_live = is_active and self.chart_stack.current_mode() == "fft"
        page = self.chart_stack.page_fft
        for pane_idx, pane in enumerate(state.panes):
            sources = list(pane.sources)
            if not sources:
                continue
            time_range = self._normalize_analysis_time_range(pane.time_range)
            entries = []
            pane_keys = []
            for fid, ch in sources:
                fd = self.files.get(fid)
                if not self._check_uniform_or_prompt(fd, "fft"):
                    continue
                sig, fs = self._fft_fetch_signal(
                    fid, ch, time_range=time_range, params=fft_params)
                if sig is None or len(sig) < 10:
                    continue
                effective_params = self._resolve_fft_effective_params(
                    fft_params, len(sig), fs
                )
                effective_params['analysis_time_axis'] = self._fft_time_facts_for_source(
                    fid, ch, time_range, fft_params)
                key = self._fft_analysis_cache_key(
                    fid, ch, effective_params, time_range
                )
                pane_keys.append(key)
                result = cache.get(key)
                if result is None:
                    result = self._fft_compute_arrays(sig, fs, effective_params)
                self._store_analysis_result(
                    "fft", state.view_id, pane_idx, key, result
                )
                if plot_live:
                    entries.append(
                        self._fft_entry_from_cache(
                            result,
                            fid,
                            ch,
                            colors.get((fid, ch)),
                            time_range=time_range,
                        )
                    )
                updater = getattr(self, "_update_analysis_restore_progress", None)
                if callable(updater):
                    updater(flush_events=True)
            self._replace_analysis_pane_pins(
                "fft", state.view_id, pane_idx, pane_keys
            )
            if plot_live and pane_idx < page.pane_count() and entries:
                self._plot_fft_entries(entries, page.pane_canvas(pane_idx))
                notify_ultraview_plot(self, "fft", "fft-plot")
        if plot_live:
            self._sync_fft_effective_facts(state)

    def do_fft(self):
        """Compute the ACTIVE FFT view: every source of every pane.

        Compute semantics (spec §4): the button computes the whole active
        view. Each pane overlays N curves (its sources); each source is cached
        on a (fid, ch, compute-params) key so re-render / view-switch is free.

        Back-compat: when no pane has captured sources, fall back to the
        legacy single-signal ``_get_sig()`` path so the existing
        single-signal UX + tests are unchanged. Captured-but-unfetchable
        sources are summarized as skipped instead.
        """
        if not self._offer_analysis_time_range_before_compute('fft'):
            return
        self._capture_active_analysis_view('fft')
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        self._clear_analysis_view_viewports(state)
        page = self.chart_stack.page_fft
        fft_params = self.inspector.fft_ctx.compute_params()
        cache = self.analysis_caches['fft']
        colors = self._analysis_channel_color_map()

        any_multi = False
        outcome = ComputeOutcome()
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
                fd = self.files.get(fid)
                if not self._check_uniform_or_prompt(fd, 'fft'):
                    outcome.skipped.append("时间轴无效")
                    continue
                sig, fs = self._fft_fetch_signal(
                    fid, ch, time_range=time_range, params=fft_params)
                if sig is None:
                    outcome.skipped.append("源通道缺失")
                    continue
                if len(sig) < 10:
                    outcome.skipped.append("信号过短")
                    continue
                effective_params = self._resolve_fft_effective_params(
                    fft_params, len(sig), fs)
                effective_params['analysis_time_axis'] = self._fft_time_facts_for_source(
                    fid, ch, time_range, fft_params)
                key = self._fft_analysis_cache_key(
                    fid, ch, effective_params, time_range)
                result = cache.get(key)
                if result is None:
                    try:
                        progress_token = self._begin_compute_progress("FFT 计算中")
                        try:
                            result = self._fft_compute_arrays(
                                sig, fs, effective_params)
                        finally:
                            self._finish_compute_progress(token=progress_token)
                    except AutoNfftBlockedError as e:
                        outcome.skipped.append(_auto_nfft_skip_reason(e))
                        continue
                    except Exception as e:
                        outcome.failed += 1
                        QMessageBox.critical(self, 'FFT错误', str(e))
                        continue
                    self._store_analysis_result(
                        'fft', state.view_id, pane_idx, key, result)
                    outcome.computed += 1
                else:
                    outcome.cached += 1
                entries.append(self._fft_entry_from_cache(
                    result, fid, ch, colors.get((fid, ch)),
                    time_range=time_range))
            if entries:
                self._plot_fft_entries(entries, page.pane_canvas(pane_idx))
                notify_ultraview_plot(self, "fft", "fft-plot")
        self._sync_fft_effective_facts(state)

        if any_multi:
            if not self._emit_compute_feedback(outcome, section_label="FFT"):
                self._do_fft_single()
            return
        # ---- legacy single-signal fallback (no navigator-checked sources) ----
        self._do_fft_single()

    def _do_fft_single(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10:
            self.toast("请选择有效信号", "warning"); return
        # Validate original source timing; reconstruction is local below,
        # after applying the physical time selection.
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
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]
            sig = sig[m]
        from ...analysis_time_axis import prepare_analysis_time_axis
        fft_params = self.inspector.fft_ctx.compute_params()
        t, fs, time_facts = prepare_analysis_time_axis(
            t, fs)
        fft_params = self._resolve_fft_effective_params(
            fft_params, len(sig), fs)
        fft_params['analysis_time_axis'] = time_facts
        win = fft_params['window']
        nfft = fft_params['nfft']

        progress_token = self._begin_compute_progress("FFT 计算中")
        error = None
        blocked_error = None
        try:
            self.statusBar.showMessage('计算FFT...');
            # Paint the status message only. A bare pump would run a queued
            # View/section click inside this compute (see lesson
            # pyqt-ui/2026-08-15-progress-pump-makes-the-render-reentrant).
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

            result = self._fft_compute_arrays(sig, fs, fft_params, time=t)
            freq, amp, _psd = result
            self._publish_analysis_effective_facts(
                self.inspector.fft_ctx,
                getattr(result, 'effective', None),
                sig=sig,
                fid=fid,
                sources=(sig_data,) if sig_data else (),
            )

            display_params = self.inspector.fft_ctx.display_params()
            x_auto = bool(display_params.get('x_auto', display_params.get('autoscale', True)))
            x_min = float(display_params.get('x_min', 0.0))
            x_max = float(display_params.get('x_max', 0.0))
            if x_auto:
                xlim = (0.0, self._fft_auto_xlim(freq, amp))
            elif x_max > x_min:
                xlim = (x_min, x_max)
            else:
                xlim = (0.0, fs / 2)
            y_auto = bool(display_params.get('y_auto', True))
            y_min = float(display_params.get('y_min', 0.0))
            y_max = float(display_params.get('y_max', 0.0))

            # Wave 2 / SP2 / Task 2.3: per-subplot Linear/dB toggle.
            amp_y = display_params.get('amp_y', 'Linear')
            weighting = fft_params.get('weighting', 'None')
            # dB-reference-defaults Task 11 (spec A9/A17 classification):
            # resolve THIS source's own reference through the same pure
            # resolver the checked-source overlay path uses
            # (_fft_entry_from_cache / _resolve_db_reference_for_source),
            # and format the axis label with the shared canonical formatter
            # (db_reference.format_amplitude_label) instead of a bare
            # 'Amplitude (dB)'/'Amplitude' hard-code -- otherwise this
            # back-compat single-signal fallback silently drops the dBA
            # disclosure an A-weighted render requires (spec stop-gate).
            resolution = self._resolve_db_reference_for_source(
                'fft', sig_data)
            if amp_y == 'dB':
                amp_disp = self._amplitude_to_db(amp, resolution.value)
            else:
                amp_disp = amp
            amp_label = db_reference.format_amplitude_label(
                resolution, weighting=weighting,
                output_scale='db' if amp_y == 'dB' else 'linear',
            )

            sig_label = self.inspector.fft_ctx.combo_sig.currentText()
            entry = {
                'label': sig_label,
                'color': '#2563eb',
                'freq': freq,
                'amp': amp_disp,
                'amp_for_xlim': amp,
                'time': t,
                'signal': sig,
                'fid': sig_data[0] if sig_data else None,
                'channel': sig_data[1] if sig_data else None,
            }
            self.canvas_fft.plot_spectra(
                [entry],
                xlim=xlim,
                amp_label=amp_label,
                title=f'FFT - {sig_label} (窗:{win}, NFFT:{nfft or "auto"})',
                y_auto=y_auto, y_min=y_min, y_max=y_max,
            )
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
            notify_ultraview_plot(self, "fft", "fft-single-plot")
            batch_params = dict(self.inspector.fft_ctx.current_params())
            batch_params['fs'] = fs
            self._remember_batch_preset(
                "当前 FFT",
                "fft",
                self.inspector.fft_ctx.current_signal(),
                batch_params,
            )
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
            self.toast(f"FFT 完成 · 峰值 {freq[pi]:.2f} Hz", "success")
        except AutoNfftBlockedError as e:
            blocked_error = e
        except Exception as e:
            error = e
        finally:
            self._finish_compute_progress(token=progress_token)
        if blocked_error is not None:
            self.toast(_auto_nfft_skip_reason(blocked_error), "warning")
            self.statusBar.showMessage(str(blocked_error))
            ctx = self.inspector.fft_ctx
            setter = getattr(ctx, 'set_effective_facts_groups', None)
            header = (
                f"{sig_data[0]} · {sig_data[1]}" if sig_data else "当前信号"
            )
            if callable(setter):
                setter(
                    [(header, None, _blocked_auto_nfft_lines(blocked_error.decision))],
                    (),
                )
            return
        if error is not None:
            QMessageBox.critical(self, 'FFT错误', str(error))
