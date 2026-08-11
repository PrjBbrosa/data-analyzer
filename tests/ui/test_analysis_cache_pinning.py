"""AnalysisResultCache View pinning + single-put funnel guards.

Spec: docs/analyzer/specs/2026-08-11-analysis-cache-view-pinning-spec.md
"""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.analysis_cache import (
    AnalysisResultCache,
    FrfAnalysisResultCache,
)


def test_pinned_entries_survive_unpinned_put_storm():
    pinned = {"keep-a", "keep-b"}
    cache = AnalysisResultCache(
        capacity=2,
        pinned_provider=lambda: pinned,
    )
    cache.put("keep-a", "A")
    cache.put("keep-b", "B")
    for i in range(4):
        cache.put(f"hist-{i}", i)

    assert cache.get("keep-a") == "A"
    assert cache.get("keep-b") == "B"
    assert set(cache._store) == {"keep-a", "keep-b", "hist-2", "hist-3"}


def test_unpinned_capacity_is_lru_by_insertion_order():
    cache = AnalysisResultCache(capacity=2, pinned_provider=lambda: set())
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")  # refresh — same as classic LRU
    cache.put("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_no_provider_matches_classic_lru_byte_for_byte():
    classic = AnalysisResultCache(capacity=2)
    pinned_none = AnalysisResultCache(capacity=2, pinned_provider=None)
    for cache in (classic, pinned_none):
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")
        cache.put("c", 3)
    assert list(classic._store.items()) == list(pinned_none._store.items())


def test_invalidate_fid_and_clear_ignore_pins():
    pinned = {"f1-a", "f2-b"}
    cache = AnalysisResultCache(capacity=4, pinned_provider=lambda: pinned)
    ka = cache.make_key("f1", "a", {})
    kb = cache.make_key("f2", "b", {})
    pinned.clear()
    pinned.update({ka, kb})
    cache.put(ka, 1)
    cache.put(kb, 2)
    cache.invalidate_fid("f1")
    assert cache.get(ka) is None
    assert cache.get(kb) == 2
    cache.clear()
    assert list(cache._store) == []


def test_frf_cache_key_is_hashable_for_pin_sets():
    pinned_holder = []
    cache = FrfAnalysisResultCache(
        capacity=1,
        pinned_provider=lambda: set(pinned_holder),
    )
    key = cache.make_key(("f1", "in"), ("f1", "out"), {"nfft": 256}, (0.0, 1.0))
    pinned_holder.append(key)
    cache.put(key, "keep")
    for i in range(3):
        other = cache.make_key(
            ("f1", "in"), ("f1", f"out-{i}"), {"nfft": 256}, (0.0, 1.0)
        )
        cache.put(other, f"hist-{i}")
    assert cache.get(key) == "keep"
    assert len([k for k in cache._store if k not in pinned_holder]) <= 1


def test_analysis_cache_put_funnel_stays_private_to_store_helper():
    """AST guard: analysis cache writes in main_window go only through helper.

    Indiscriminate rule (no receiver-name allowlist, which has blind spots --
    e.g. ``cache = self.analysis_caches[...]`` aliases outside the three
    mixins this used to special-case, and ``fft_time_cache`` in window.py):
    ANY ``ast.Call`` anywhere in the module's AST (module-level statements
    included, not just inside ``FunctionDef`` bodies) whose ``func`` is an
    ``ast.Attribute`` with ``attr == "put"`` is a violation, unless that same
    ``Call`` node lexically sits inside a ``FunctionDef`` named
    ``_store_analysis_result``.
    """
    def _iter_calls_with_context(node, current_name="<module>"):
        # Yields every ast.Call reachable from ``node``, paired with the name
        # of the nearest enclosing FunctionDef (or "<module>" at top level) --
        # purely for the offender string; the exemption itself is decided by
        # node identity (below), not by this name.
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef) else current_name
            if isinstance(child, ast.Call):
                yield child, current_name
            yield from _iter_calls_with_context(child, name)

    root = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui"
    targets = [
        root / "main_window",
    ]
    offenders = []
    for directory in targets:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # Collect every Call node lexically inside a
            # ``_store_analysis_result`` FunctionDef body -- the sole
            # exemption -- BEFORE walking the whole tree, so the full-tree
            # pass below can check plain node-identity membership.
            exempt_calls = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == (
                    "_store_analysis_result"
                ):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            exempt_calls.add(child)
            for call, enclosing_name in _iter_calls_with_context(tree):
                if call in exempt_calls:
                    continue
                func = call.func
                if not isinstance(func, ast.Attribute) or func.attr != "put":
                    continue
                offenders.append(
                    f"{path.relative_to(root.parent.parent)}:"
                    f"{call.lineno}:{enclosing_name}"
                )
    assert offenders == []
