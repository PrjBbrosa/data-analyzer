"""AnalysisResultCache: keying, LRU eviction, fid invalidation."""
from mf4_analyzer.ui.analysis_cache import AnalysisResultCache


def test_put_get_round_trip():
    c = AnalysisResultCache(capacity=2)
    k = c.make_key("f1", "vib", {"nfft": 1024, "window": "hanning"})
    c.put(k, "RESULT")
    assert c.get(k) == "RESULT"


def test_key_ignores_order_and_is_param_sensitive():
    c = AnalysisResultCache(capacity=2)
    k1 = c.make_key("f1", "vib", {"a": 1, "b": 2})
    k2 = c.make_key("f1", "vib", {"b": 2, "a": 1})
    k3 = c.make_key("f1", "vib", {"a": 1, "b": 3})
    assert k1 == k2 and k1 != k3


def test_lru_eviction():
    c = AnalysisResultCache(capacity=2)
    k1, k2, k3 = (c.make_key("f", str(i), {}) for i in range(3))
    c.put(k1, 1); c.put(k2, 2)
    c.get(k1)            # refresh k1
    c.put(k3, 3)         # evicts k2
    assert c.get(k1) == 1 and c.get(k2) is None and c.get(k3) == 3


def test_invalidate_fid():
    c = AnalysisResultCache(capacity=4)
    ka = c.make_key("f1", "a", {})
    kb = c.make_key("f2", "b", {})
    c.put(ka, 1); c.put(kb, 2)
    c.invalidate_fid("f1")
    assert c.get(ka) is None and c.get(kb) == 2
