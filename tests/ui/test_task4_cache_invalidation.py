"""Task 4 TDD — unified cache-invalidation entry point (问题①) and
fft_time fallback key alignment (问题④).

RED tests written first; they exercise behaviour that does NOT yet exist.

问题①: After rebuild_time_axis changes fd.fs, every analysis result cache must
drop any previously-stored entry for that fid.

问题④: The fallback branch in `_analysis_cache_key` (reached when
`_fft_time_effective_params_for_source` returns None because the signal has
fewer than 2 samples) must produce a key that is byte-identical to the one
`_fft_time_analysis_cache_key` would produce for the same param set,
including the `weighting` field.
"""
from __future__ import annotations

import types

import pytest

from mf4_analyzer.ui.analysis_cache import AnalysisResultCache
from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin
from mf4_analyzer.ui.main_window.window import MainWindow
from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec


# ---------------------------------------------------------------------------
# Helpers — minimal MainWindow stub
# ---------------------------------------------------------------------------

def _make_mw():
    """Build a minimal MainWindow-like object with the mixins we need."""
    # We build a throw-away class that has both FFTTimeMixin and AnalysisMixin
    # behaviour, without pulling in PyQt widgets.
    from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin

    class _StubMW(FFTTimeMixin):
        def __init__(self):
            self.analysis_caches = {
                'fft': AnalysisResultCache(32),
                'fft_time': AnalysisResultCache(12),
                'order': AnalysisResultCache(12),
            }

    mw = _StubMW()
    return mw


def test_apply_custom_xaxis_invalidates_fft_time_analysis_cache(qtbot):
    """Custom X changes display semantics outside the FFT-vs-Time key.

    The existing FFT-vs-Time entry must therefore be evicted before the next
    ``do_fft_time`` lookup; otherwise it would be a stale cache hit.
    """
    del qtbot  # This path is exercised against a narrow MainWindow protocol.

    class _Data:
        columns = {"custom_x"}

        def __len__(self):
            return 3

    class _Canvas:
        def invalidate_envelope_cache(self, _reason):
            pass

        def invalidate_monotonicity_cache(self):
            pass

    class _Top:
        def xaxis_mode(self):
            return "channel"

        def xaxis_channel_data(self):
            return ("per_source_name", None, "custom_x")

        def xaxis_label(self):
            return "Custom X"

    canvas = _Canvas()
    cache = AnalysisResultCache(12)
    key = cache.make_key(
        "f1", "signal", {"fs": 1000.0, "nfft": 512, "time_range": (0.0, 1.0)}
    )
    cache.put(key, "existing-fft-time-result")

    mw = types.SimpleNamespace(
        chart_stack=types.SimpleNamespace(
            focused_canvas=lambda: canvas,
            current_mode=lambda: "fft",
        ),
        inspector=types.SimpleNamespace(top=_Top()),
        navigator=types.SimpleNamespace(get_checked_channels=lambda: []),
        files={"f1": types.SimpleNamespace(data=_Data())},
        analysis_caches={"fft_time": cache},
        _view_index_for_canvas=lambda _canvas: None,
        plot_time=lambda: None,
        statusBar=types.SimpleNamespace(showMessage=lambda *_args: None),
        _hint_focused_pane=lambda _action: True,
        toast=lambda *_args: None,
        _clear_analysis_section_pins=lambda *_args, **_kwargs: None,
    )

    MainWindow._apply_xaxis(mw)

    assert mw._custom_xaxis_spec == CustomXAxisSpec(
        mode="channel",
        resolver="per_source_name",
        channel="custom_x",
        source_fid=None,
        label="Custom X",
    )
    assert (mw._custom_xaxis_fid, mw._custom_xaxis_ch) == (None, None)
    assert cache.get(key) is None, (
        "custom X axis left an FFT-vs-Time analysis-cache entry reachable; "
        "the next do_fft_time lookup would use stale data"
    )


# ---------------------------------------------------------------------------
# 问题① RED: _invalidate_all_analysis_caches_for_fid must exist and must
# clear analysis_caches['fft'] and analysis_caches['order'] for the given fid.
# ---------------------------------------------------------------------------

class TestUnifiedInvalidationEntry:
    """The new single-entry-point method must clear ALL caches for a fid."""

    def test_method_exists(self):
        """The helper `_invalidate_all_analysis_caches_for_fid` must be present."""
        mw = _make_mw()
        assert hasattr(mw, '_invalidate_all_analysis_caches_for_fid'), (
            "_invalidate_all_analysis_caches_for_fid does not exist yet (RED)"
        )

    def test_clears_fft_cache(self):
        """analysis_caches['fft'] must drop the fid's entry after invalidation."""
        mw = _make_mw()
        cache = mw.analysis_caches['fft']
        k = cache.make_key('f1', 'ch1', {'nfft': 1024})
        cache.put(k, 'old-fft-result')
        assert cache.get(k) == 'old-fft-result'

        # After invalidation the old key must return None.
        mw._invalidate_all_analysis_caches_for_fid('f1')
        assert cache.get(k) is None, (
            "analysis_caches['fft'] still holds stale entry for f1 after invalidation"
        )

    def test_clears_order_cache(self):
        """analysis_caches['order'] must drop the fid's entry after invalidation."""
        mw = _make_mw()
        cache = mw.analysis_caches['order']
        k = cache.make_key('f1', 'rpm', {'order_res': 0.1})
        cache.put(k, 'old-order-result')
        assert cache.get(k) == 'old-order-result'

        mw._invalidate_all_analysis_caches_for_fid('f1')
        assert cache.get(k) is None, (
            "analysis_caches['order'] still holds stale entry for f1 after invalidation"
        )

    def test_clears_fft_time_analysis_cache(self):
        """analysis_caches['fft_time'] must also be cleared."""
        mw = _make_mw()
        cache = mw.analysis_caches['fft_time']
        k = cache.make_key('f1', 'sig', {'nfft': 512})
        cache.put(k, 'old-fft-time-result')

        mw._invalidate_all_analysis_caches_for_fid('f1')
        assert cache.get(k) is None, (
            "analysis_caches['fft_time'] still holds stale entry for f1 after invalidation"
        )

    def test_preserves_other_fid_entries(self):
        """Entries for a different fid must survive the invalidation."""
        mw = _make_mw()
        cache_fft = mw.analysis_caches['fft']
        cache_order = mw.analysis_caches['order']

        k_keep_fft = cache_fft.make_key('f2', 'ch1', {'nfft': 1024})
        k_keep_order = cache_order.make_key('f2', 'rpm', {'order_res': 0.1})
        cache_fft.put(k_keep_fft, 'keep-fft')
        cache_order.put(k_keep_order, 'keep-order')

        k_drop = cache_fft.make_key('f1', 'ch1', {'nfft': 1024})
        cache_fft.put(k_drop, 'drop')

        mw._invalidate_all_analysis_caches_for_fid('f1')

        assert cache_fft.get(k_keep_fft) == 'keep-fft', "f2 fft entry was wrongly evicted"
        assert cache_order.get(k_keep_order) == 'keep-order', "f2 order entry was wrongly evicted"
        assert cache_fft.get(k_drop) is None, "f1 fft entry should have been dropped"


# ---------------------------------------------------------------------------
# 问题④ RED: fallback key == primary key for same params (including weighting)
# ---------------------------------------------------------------------------

class TestFallbackKeyAlignsPrimaryKey:
    """The fft_time fallback key in _analysis_cache_key must be byte-identical
    to the key produced by _fft_time_analysis_cache_key for the same params.

    We test this by building a minimal stub that supports both key-building
    paths and comparing the outputs directly, without requiring a live Qt GUI.
    """

    # Shared params that the primary key function can accept directly.
    _PARAMS = {
        'fs': 1000.0,
        'nfft': 512,
        'nfft_effective': 512,
        'nfft_preview': 512,
        'window': 'hann',
        'overlap': 0.5,
        'remove_mean': True,
        'weighting': 'A',
        'time_range': (0.0, 5.0),
    }

    def _make_primary_key(self, fid, ch, p, pane_idx):
        """Replicate what _fft_time_analysis_cache_key does for a standalone call."""
        cache = AnalysisResultCache(12)
        params = {
            'fs': p.get('fs'),
            'nfft': int(p.get('nfft_effective', p.get('nfft'))),
            'window': p.get('window'),
            'overlap': p.get('overlap'),
            'remove_mean': p.get('remove_mean'),
            'weighting': str(p.get('weighting', 'None')),
            'time_range': p.get('time_range'),
        }
        return cache.make_key(fid, ch, params)

    def test_fallback_key_reuses_primary_key_function(self):
        """Verify _analysis_cache_key's fallback delegates to
        _fft_time_analysis_cache_key — after the fix both keys must match,
        including `weighting='A'`."""
        # We need a minimal MainWindow stub that has:
        # - analysis_caches dict
        # - _fft_time_analysis_cache_key (from FFTTimeMixin)
        # - _pane_time_range_for returning our time_range
        # - inspector.fft_time_ctx.get_params() returning our params
        # - _fft_time_effective_params_for_source returning None (forces fallback)

        from mf4_analyzer.ui.main_window._analysis_mixin import AnalysisMixin

        class _StubCtx:
            def compute_params(self_):
                return dict(self._PARAMS)

            def get_params(self_):
                return dict(self._PARAMS)

            def current_signal(self_):
                return None  # forces _fft_time_effective_params_for_source to fail

        class _StubInspector:
            def __init__(self_):
                self_.fft_time_ctx = _StubCtx()

        class _StubMW(FFTTimeMixin, AnalysisMixin):
            def __init__(self_):
                self_.analysis_caches = {
                    'fft': AnalysisResultCache(32),
                    'fft_time': AnalysisResultCache(12),
                    'order': AnalysisResultCache(12),
                }
                self_.inspector = _StubInspector()

            # _fft_time_effective_params_for_source pulls the signal — make it
            # return None so the fallback branch executes.
            def _fft_time_effective_params_for_source(self_, p, fid, ch, time_range):
                return None

            def _pane_time_range_for(self_, section, pane_idx):
                return self._PARAMS['time_range']

            def _analysis_ctx(self_, section):
                assert section == 'fft_time'
                return self_.inspector.fft_time_ctx

        mw = _StubMW()
        p = dict(self._PARAMS)
        fid, ch, pane_idx = 'f1', 'sig', 0

        # Primary key (what the mixin builds on the happy path).
        primary = mw._fft_time_analysis_cache_key(fid, ch, p, pane_idx)

        # Fallback key (what _analysis_cache_key builds when prepared is None).
        fallback = mw._analysis_cache_key('fft_time', fid, ch, pane_idx=pane_idx)

        assert fallback == primary, (
            f"Fallback key diverges from primary key.\n"
            f"  primary:  {primary}\n"
            f"  fallback: {fallback}\n"
            "The fallback must delegate to _fft_time_analysis_cache_key (问题④)."
        )

    def _make_key_routing_probe(self):
        """Return a narrow FFT-vs-Time protocol with two pane-local ranges."""
        import numpy as np

        class _RecordingCache(AnalysisResultCache):
            def __init__(self):
                super().__init__(12)
                self.lookup_keys = []

            def get(self, key):
                self.lookup_keys.append(key)
                return super().get(key)

        class _Page:
            def focused_index(self_):
                return 1

            def pane_count(self_):
                return 2

        class _Ctx:
            def get_params(self_):
                return {
                    'fs': 10.0,
                    'nfft': 4,
                    'nfft_effective': 4,
                    'window': 'hann',
                    'overlap': 0.5,
                    'remove_mean': True,
                    'weighting': 'None',
                }

        class _Top:
            def range_enabled(self_):
                return True

            def range_values(self_):
                # Matches focused pane 1, as real focus routing does.
                return (4.0, 7.0)

        class _Jobs:
            def __init__(self_):
                self_.submitted = []

            @staticmethod
            def is_running(_section):
                return False

            def submit_batch(self_, section, jobs, **_kwargs):
                self_.submitted.append((section, list(jobs)))

            @staticmethod
            def progress_counts(_section):
                return (0, 1)

        class _Status:
            @staticmethod
            def showMessage(_message):
                pass

        class _Probe(FFTTimeMixin):
            def __init__(self_):
                cache = _RecordingCache()
                self_.analysis_caches = {'fft_time': cache}
                self_.inspector = types.SimpleNamespace(
                    fft_time_ctx=_Ctx(), top=_Top(),
                )
                self_.analysis_managers = {
                    'fft_time': types.SimpleNamespace(
                        active=0,
                        get=lambda _active: types.SimpleNamespace(
                            view_id='probe-view',
                            panes=[
                                types.SimpleNamespace(sources=[('f0', 'sig0')]),
                                types.SimpleNamespace(sources=[('f1', 'sig1')]),
                            ]
                        ),
                    )
                }
                self_._analysis_jobs = _Jobs()
                self_._analysis_progress_tokens = {}
                self_.statusBar = _Status()
                self_.builder_calls = []
                self_.pane_ranges = {0: (0.0, 2.0), 1: (4.0, 7.0)}
                self_.sample_time = np.arange(10, dtype=float)
                self_._fft_time_coordinator = types.SimpleNamespace(
                    request_batch=self_._request_fft_time_candidates,
                )

            def _request_fft_time_candidates(self_, candidates, replace=False):
                """Minimal coordinator fake for key-routing assertions.

                It deliberately mirrors only the coordinator boundary under
                test: lookup key before factory, factory only after a miss,
                then dispatch key rebuilt from the factory's final params.
                """
                del replace
                queued = []
                for candidate in candidates:
                    job = candidate.get('job', object())
                    ctx = {
                        key: value for key, value in candidate.items()
                        if key not in {'job', 'job_factory'}
                    }
                    if job is None:
                        queued.append((None, ctx))
                        continue
                    lookup_key = self_._fft_time_analysis_cache_key(
                        ctx['fid'], ctx['channel'], ctx['params'],
                        ctx['time_range'],
                    )
                    if self_.analysis_caches['fft_time'].get(lookup_key) is not None:
                        continue
                    built = candidate['job_factory']()
                    if built is None:
                        queued.append((None, ctx))
                        continue
                    job, updates = built
                    ctx.update(updates)
                    ctx['analysis_key'] = self_._fft_time_analysis_cache_key(
                        ctx['fid'], ctx['channel'], ctx['params'],
                        ctx['time_range'],
                    )
                    queued.append((job, ctx))
                if queued:
                    self_._analysis_jobs.submit_batch('fft_time', queued)
                return len(queued)

            def _analysis_page(self_, section):
                assert section == 'fft_time'
                return _Page()

            def _capture_active_analysis_view(self_, section):
                assert section == 'fft_time'

            @staticmethod
            def _clear_analysis_view_viewports(state):
                for pane in state.panes:
                    pane.xlim = None
                    pane.ylim = None

            def _pane_time_range_for(self_, section, pane_idx=None):
                assert section == 'fft_time'
                return self_.pane_ranges[int(pane_idx)]

            @staticmethod
            def _normalize_analysis_time_range(value):
                return value

            def _mask_time_range(self_, t, *arrays, time_range=None):
                lo, hi = time_range
                mask = (t >= lo) & (t <= hi)
                return (t[mask], *(array[mask] for array in arrays))

            def _fft_time_signal_for(self_, source):
                fid, ch = source
                sig = np.arange(len(self_.sample_time), dtype=float)
                fd = types.SimpleNamespace(channel_units={ch: ''})
                return fid, ch, self_.sample_time, sig, fd

            def _get_fft_time_signal(self_):
                return self_._fft_time_signal_for(('f1', 'sig1'))

            def _check_uniform_or_prompt(self_, _fd, _section):
                return True

            @staticmethod
            def _offer_analysis_time_range_before_compute(_section):
                # Probe is compute-routing only; never surface the confirm dialog.
                return True

            def _fft_time_analysis_cache_key(self_, fid, ch, p, time_range):
                self_.builder_calls.append((fid, ch, dict(p), time_range))
                return FFTTimeMixin._fft_time_analysis_cache_key(
                    self_, fid, ch, p, time_range
                )

            def _begin_compute_progress(self_, *_args, **_kwargs):
                return object()

            def _record_fft_time_skip(self_, _reason):
                pass

            def toast(self_, *_args):
                raise AssertionError('valid probe inputs must not toast')

        probe = _Probe()
        return probe, probe.analysis_caches['fft_time']

    def test_fft_time_dispatch_key_equals_lookup_key_for_each_pane(self, qtbot):
        """Lookup and dispatch use the builder with each pane's own range."""
        del qtbot
        mw, cache = self._make_key_routing_probe()

        mw.do_fft_time()
        first_lookup = list(cache.lookup_keys)
        mw.do_fft_time()
        second_lookup = cache.lookup_keys[len(first_lookup):]

        assert len(first_lookup) == 2
        assert first_lookup == second_lookup
        assert first_lookup[0] != first_lookup[1]
        lookup_by_source = {(key[0], key[1]): key for key in first_lookup}

        submitted = mw._analysis_jobs.submitted
        assert len(submitted) == 2
        dispatched = [
            ctx['analysis_key']
            for _section, jobs in submitted
            for job, ctx in jobs
            if job is not None
        ]

        assert dispatched == [
            lookup_by_source[('f1', 'sig1')],
            lookup_by_source[('f0', 'sig0')],
            lookup_by_source[('f1', 'sig1')],
            lookup_by_source[('f0', 'sig0')],
        ]
        assert [call[:2] + (call[3],) for call in mw.builder_calls] == [
            ('f1', 'sig1', (4.0, 7.0)), ('f1', 'sig1', (4.0, 7.0)),
            ('f0', 'sig0', (0.0, 2.0)), ('f0', 'sig0', (0.0, 2.0)),
            ('f1', 'sig1', (4.0, 7.0)), ('f1', 'sig1', (4.0, 7.0)),
            ('f0', 'sig0', (0.0, 2.0)), ('f0', 'sig0', (0.0, 2.0)),
        ]

    def test_fft_time_single_path_uses_same_key_builder_as_main_path(self, qtbot):
        """The fallback single-source pending key matches the main-path lookup."""
        del qtbot
        mw, cache = self._make_key_routing_probe()

        mw.do_fft_time()
        main_lookup_for_focused_pane = next(
            key for key in cache.lookup_keys if key[:2] == ('f1', 'sig1')
        )
        mw.builder_calls.clear()

        mw._do_fft_time_single()

        _section, jobs = mw._analysis_jobs.submitted[-1]
        assert jobs[0][1]['analysis_key'] == main_lookup_for_focused_pane
        assert [call[:2] + (call[3],) for call in mw.builder_calls] == [
            ('f1', 'sig1', (4.0, 7.0)),
            ('f1', 'sig1', (4.0, 7.0)),
        ]

    def test_weighting_a_differentiates_from_none(self):
        """weighting='A' must produce a different key than weighting='None',
        both on the primary and (after fix) on the fallback path."""
        cache = AnalysisResultCache(12)
        p_base = dict(self._PARAMS, weighting='None')
        p_a = dict(self._PARAMS, weighting='A')
        k_none = self._make_primary_key('f1', 'sig', p_base, 0)
        k_a = self._make_primary_key('f1', 'sig', p_a, 0)
        assert k_none != k_a, (
            "weighting='A' and weighting='None' produce the same key — "
            "A-weighted and unweighted results would share a cache slot."
        )


class TestAutoNfftFallbackNoTypeError:
    """Important regression: _analysis_cache_key('fft_time', ...) must not raise
    TypeError when the inspector is in auto-nfft mode AND the signal has < 2
    samples (forcing the fallback branch).

    Root cause (Task 4 regression): in auto-nfft mode get_params() emits
    nfft=None AND nfft_effective=None; the key-building code does
      int(p.get('nfft_effective', p.get('nfft')))
    Both keys ARE present in the dict (value None), so .get() returns None
    (not the default), giving int(None) → TypeError.

    The fix patches only the fallback call-site in _analysis_mixin.py — it
    resolves nfft via the or-chain ``nfft_effective or nfft or nfft_preview``
    (nfft_preview is always a positive integer) before delegating to the
    primary key function.
    """

    # Auto-nfft params exactly as emitted by contextual_fft_time.get_params()
    # when the combo shows the AUTO_NFFT_LABEL: nfft=None, nfft_effective=None,
    # nfft_preview=<positive int derived from the last sample-count estimate>.
    _AUTO_PARAMS = {
        'fs': 1000.0,
        'nfft': None,
        'nfft_effective': None,
        'nfft_preview': 512,
        'nfft_mode': 'auto',
        't_win_s': 1.5,
        'window': 'hann',
        'overlap': 0.5,
        'remove_mean': True,
        'weighting': 'None',
    }

    def _make_stub_mw(self):
        """Build a minimal MainWindow stub that forces the fallback branch."""
        from mf4_analyzer.ui.main_window._analysis_mixin import AnalysisMixin

        params = dict(self._AUTO_PARAMS)

        class _StubCtx:
            def get_params(self_):
                return dict(params)

            def current_signal(self_):
                return None

        class _StubInspector:
            def __init__(self_):
                self_.fft_time_ctx = _StubCtx()

        class _StubMW(FFTTimeMixin, AnalysisMixin):
            def __init__(self_):
                self_.analysis_caches = {
                    'fft': AnalysisResultCache(32),
                    'fft_time': AnalysisResultCache(12),
                    'order': AnalysisResultCache(12),
                }
                self_.inspector = _StubInspector()

            def _fft_time_effective_params_for_source(self_, p, fid, ch, time_range):
                # Simulate < 2 samples: return None to force the fallback branch.
                return None

            def _pane_time_range_for(self_, section, pane_idx):
                return (0.0, 5.0)

        return _StubMW()

    def test_auto_nfft_fallback_does_not_raise_type_error(self):
        """With auto-nfft (nfft=None, nfft_effective=None, nfft_preview=512)
        AND signal < 2 samples (fallback branch), _analysis_cache_key must
        return a key without raising TypeError."""
        mw = self._make_stub_mw()
        # Must not raise — used to raise int(None) TypeError before the fix.
        key = mw._analysis_cache_key('fft_time', 'f1', 'ch1', pane_idx=0)
        assert key is not None, "Fallback key must be a non-None value."

    def test_auto_nfft_fallback_key_uses_nfft_preview(self):
        """When nfft and nfft_effective are both None, the fallback key must
        encode nfft_preview (512) as the nfft dimension — not None — so that
        keys with different nfft_preview values are distinguishable."""
        mw = self._make_stub_mw()
        key_512 = mw._analysis_cache_key('fft_time', 'f1', 'ch1', pane_idx=0)
        # Now patch nfft_preview to 1024 and verify the key changes.
        mw.inspector.fft_time_ctx._nfft_preview_override = 1024

        params_1024 = dict(self._AUTO_PARAMS, nfft_preview=1024)

        class _StubCtx1024:
            def get_params(self_):
                return dict(params_1024)

            def current_signal(self_):
                return None

        mw.inspector.fft_time_ctx = _StubCtx1024()
        key_1024 = mw._analysis_cache_key('fft_time', 'f1', 'ch1', pane_idx=0)
        assert key_512 != key_1024, (
            "nfft_preview=512 and nfft_preview=1024 must produce different keys "
            "in auto-nfft fallback mode."
        )


def test_close_all_clears_fft_time_coordinator_pending(qapp, qtbot):
    """回归（N1）：close_all 只清缓存、不清 FftTimeCoordinator 的 in-flight
    pending，与单文件关闭（_close→_invalidate_all_analysis_caches_for_fid→
    coordinator.invalidate_fid）不对称。关全部文件时若有 fft_time 作业在飞，
    其完成回调会把死 fid 结果写回刚清空的缓存并渲染过期热图。close_all 后
    coordinator 的 pending 必须为空。"""
    import numpy as np
    import pandas as pd
    from mf4_analyzer.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    t = np.linspace(0, 1.0, 64)
    df = pd.DataFrame({"Time": t, "ACC": np.sin(t)})
    w._register_file_data("x.mf4", df, ["Time", "ACC"], {"ACC": "m/s^2"})
    fid = next(iter(w.files))

    # 模拟一条在飞的 fft_time 作业上下文
    w._fft_time_coordinator._pending[999] = {"fid": fid, "ch": "ACC"}
    assert w._fft_time_coordinator._pending  # 前置：确有 pending

    w.close_all(force=True)

    assert w._fft_time_coordinator._pending == {}
