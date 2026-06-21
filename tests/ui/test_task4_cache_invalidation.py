"""Task 4 TDD — unified cache-invalidation entry point (问题①) and
fft_time fallback key alignment (问题④).

RED tests written first; they exercise behaviour that does NOT yet exist.

问题①: After rebuild_time_axis changes fd.fs, both `analysis_caches['fft']`
and `analysis_caches['order']` must drop any previously-stored entry for
that fid.  Only `_fft_time_cache_clear_for_fid` was called before; the
`analysis_caches` for 'fft' and 'order' were NOT invalidated.

问题④: The fallback branch in `_analysis_cache_key` (reached when
`_fft_time_effective_params_for_source` returns None because the signal has
fewer than 2 samples) must produce a key that is byte-identical to the one
`_fft_time_analysis_cache_key` would produce for the same param set,
including the `weighting` field.
"""
from __future__ import annotations

import types
from collections import OrderedDict

import pytest

from mf4_analyzer.ui.analysis_cache import AnalysisResultCache
from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin


# ---------------------------------------------------------------------------
# Helpers — minimal MainWindow stub
# ---------------------------------------------------------------------------

class _LRUStore:
    """Mimics the _fft_time_cache dict interface used by _fft_time_cache_clear_for_fid."""
    def __init__(self):
        self._d = OrderedDict()

    def __contains__(self, k):
        return k in self._d

    def __iter__(self):
        return iter(self._d)

    def pop(self, k, *args):
        return self._d.pop(k, *args)

    def __len__(self):
        return len(self._d)


def _make_mw():
    """Build a minimal MainWindow-like object with the mixins we need."""
    # We build a throw-away class that has both FFTTimeMixin and AnalysisMixin
    # behaviour, without pulling in PyQt widgets.
    from mf4_analyzer.ui.main_window._fft_time_mixin import FFTTimeMixin

    class _StubMW(FFTTimeMixin):
        def __init__(self):
            self._fft_time_cache = _LRUStore()
            self.analysis_caches = {
                'fft': AnalysisResultCache(32),
                'fft_time': AnalysisResultCache(12),
                'order': AnalysisResultCache(12),
            }

    mw = _StubMW()
    return mw


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

    def test_clears_lru_fft_time_cache(self):
        """The legacy _fft_time_cache LRU must also be cleared by the new entry point."""
        mw = _make_mw()
        # Manually insert a sentinel keyed under fid='f1'
        stale_key = ('f1', 'ch1', (0.0, 10.0), 1000.0, 512, 'hann', 0.5, False, 'None')
        mw._fft_time_cache._d[stale_key] = 'stale-lru-value'
        assert stale_key in mw._fft_time_cache

        mw._invalidate_all_analysis_caches_for_fid('f1')
        assert stale_key not in mw._fft_time_cache, (
            "_fft_time_cache LRU still holds stale LRU entry after invalidation"
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
