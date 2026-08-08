"""Analysis result caches: keying, LRU eviction, fid invalidation."""
from mf4_analyzer.ui.analysis_cache import (
    AnalysisResultCache,
    FrfAnalysisResultCache,
)


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


def test_frf_cache_key_is_directional_and_param_order_stable():
    cache = FrfAnalysisResultCache(capacity=4)
    forward = cache.make_key(
        ("f1", "input"),
        ("f1", "output"),
        {"window": "hanning", "overlap": 0.5},
        (0.0, 2.0),
    )
    reordered = cache.make_key(
        ("f1", "input"),
        ("f1", "output"),
        {"overlap": 0.5, "window": "hanning"},
        (0.0, 2.0),
    )
    reverse = cache.make_key(
        ("f1", "output"),
        ("f1", "input"),
        {"window": "hanning", "overlap": 0.5},
        (0.0, 2.0),
    )

    assert forward == reordered
    assert forward != reverse


def test_frf_cache_keeps_duplicate_labels_from_different_sources_distinct():
    cache = FrfAnalysisResultCache(capacity=4)
    first = cache.make_key(("f1", "sig"), ("f1", "resp"), {}, None)
    second = cache.make_key(("f2", "sig"), ("f2", "resp"), {}, None)

    assert first != second


def test_frf_cache_invalidates_when_either_endpoint_fid_changes():
    cache = FrfAnalysisResultCache(capacity=4)
    input_match = cache.make_key(("f1", "in"), ("f2", "out"), {}, None)
    output_match = cache.make_key(("f3", "in"), ("f1", "out"), {}, None)
    survivor = cache.make_key(("f3", "in"), ("f2", "out"), {}, None)
    for key in (input_match, output_match, survivor):
        cache.put(key, key)

    cache.invalidate_fid("f1")

    assert cache.get(input_match) is None
    assert cache.get(output_match) is None
    assert cache.get(survivor) == survivor


def test_frf_cache_lru_capacity_matches_other_analysis_caches():
    cache = FrfAnalysisResultCache(capacity=2)
    keys = [
        cache.make_key(("f", "in"), ("f", f"out-{index}"), {}, None)
        for index in range(3)
    ]
    cache.put(keys[0], 0)
    cache.put(keys[1], 1)
    cache.get(keys[0])
    cache.put(keys[2], 2)

    assert cache.get(keys[0]) == 0
    assert cache.get(keys[1]) is None
    assert cache.get(keys[2]) == 2
