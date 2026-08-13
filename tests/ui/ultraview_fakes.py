"""Shared UltraView test probes. No product behavior; counting and snapshots only."""
from __future__ import annotations

from collections import Counter
from typing import Any


COMPUTE_ENTRYPOINTS = ("do_fft", "do_fft_time", "do_frf", "do_order_time")
JOB_ENTRYPOINTS = ("submit", "submit_batch")


class ComputeProbe:
    """Count compute / job / cache-write entrypoints on a real or fake window.

    Install wraps the four ``do_*`` methods, ``AnalysisJobService.submit`` /
    ``submit_batch``, and ``_store_analysis_result``. New-key cache writes are
    counted separately from same-key overwrites so UV-A20 can distinguish a
    cache-hit rewrite from a first insert.
    """

    def __init__(self) -> None:
        self.compute_calls: Counter[str] = Counter()
        self.job_calls: Counter[str] = Counter()
        self.store_calls = 0
        self.store_new_key_writes = 0
        self._seen_store_keys: set[Any] = set()
        self._restore_pending_before: frozenset | None = None
        self._installed: list[tuple[Any, str, Any]] = []

    def install(self, window) -> "ComputeProbe":
        for name in COMPUTE_ENTRYPOINTS:
            original = getattr(window, name, None)
            if original is None:
                continue
            setattr(window, name, self._wrap_compute(name, original))
            self._installed.append((window, name, original))

        jobs = getattr(window, "_analysis_jobs", None)
        if jobs is not None:
            for name in JOB_ENTRYPOINTS:
                original = getattr(jobs, name)
                setattr(jobs, name, self._wrap_job(name, original))
                self._installed.append((jobs, name, original))

        original_store = getattr(window, "_store_analysis_result", None)
        if original_store is not None:
            setattr(window, "_store_analysis_result", self._wrap_store(original_store))
            self._installed.append((window, "_store_analysis_result", original_store))

        pending = getattr(window, "_analysis_restore_pending", None)
        if pending is not None:
            self._restore_pending_before = frozenset(pending)
        return self

    def restore(self) -> None:
        for owner, name, original in reversed(self._installed):
            setattr(owner, name, original)
        self._installed.clear()

    def snapshot_restore_pending(self, window) -> frozenset:
        pending = getattr(window, "_analysis_restore_pending", set())
        return frozenset(pending)

    def restore_pending_unchanged(self, window) -> bool:
        if self._restore_pending_before is None:
            return True
        return self.snapshot_restore_pending(window) == self._restore_pending_before

    @property
    def compute_total(self) -> int:
        return int(sum(self.compute_calls.values()))

    @property
    def job_total(self) -> int:
        return int(sum(self.job_calls.values()))

    def _wrap_compute(self, name, original):
        def wrapped(*args, **kwargs):
            self.compute_calls[name] += 1
            return original(*args, **kwargs)

        wrapped.__name__ = getattr(original, "__name__", name)
        return wrapped

    def _wrap_job(self, name, original):
        def wrapped(*args, **kwargs):
            self.job_calls[name] += 1
            return original(*args, **kwargs)

        wrapped.__name__ = getattr(original, "__name__", name)
        return wrapped

    def _wrap_store(self, original):
        def wrapped(section, view_id, pane_idx, key, result):
            self.store_calls += 1
            identity = (section, view_id, pane_idx, key)
            if identity not in self._seen_store_keys:
                self._seen_store_keys.add(identity)
                self.store_new_key_writes += 1
            return original(section, view_id, pane_idx, key, result)

        wrapped.__name__ = getattr(original, "__name__", "_store_analysis_result")
        return wrapped


def snapshot_source_state(window) -> dict[str, Any]:
    """Freeze five managers, pins, cache keys, and active indices.

    Uses each view's ``to_dict()`` so composite channel identity is preserved.
    Do not run the result through ``dict(view.colors)`` / ``{**mapping}``.
    """

    def _manager_snapshot(manager) -> dict[str, Any]:
        views = []
        for view in list(manager.views):
            payload = view.to_dict()
            views.append(
                {
                    "view_id": payload.get("view_id"),
                    "payload": payload,
                }
            )
        return {
            "active": manager.active,
            "view_ids": tuple(item["view_id"] for item in views),
            "views": views,
        }

    managers = {"time": _manager_snapshot(window.view_manager)}
    analysis_managers = getattr(window, "analysis_managers", {}) or {}
    for section in ("fft", "fft_time", "frf", "order"):
        manager = analysis_managers.get(section)
        if manager is not None:
            managers[section] = _manager_snapshot(manager)

    pins = {}
    pin_book = getattr(window, "_analysis_pins", None)
    if pin_book is not None:
        for slot, keys in getattr(pin_book, "_slots", {}).items():
            pins[slot] = frozenset(keys)

    cache_keys = {}
    for section, cache in (getattr(window, "analysis_caches", {}) or {}).items():
        store = getattr(cache, "_store", {})
        cache_keys[section] = tuple(store)

    return {
        "managers": managers,
        "pins": pins,
        "cache_keys": cache_keys,
        "restore_pending": frozenset(
            getattr(window, "_analysis_restore_pending", set())
        ),
        "active_indices": {
            section: payload["active"] for section, payload in managers.items()
        },
    }
