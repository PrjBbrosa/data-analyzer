"""Per-section analysis result cache with optional View pinning.

Capacity is the **unpinned** entry budget (LRU). Entries currently bound by any
View stay resident regardless of that budget — see
``docs/analyzer/specs/2026-08-11-analysis-cache-view-pinning-spec.md``.

Without a ``pinned_provider`` the store behaves as a classic capacity-sized
LRU, matching the historical contract used by existing unit tests.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class AnalysisResultCache:
    def __init__(
        self,
        capacity: int,
        *,
        pinned_provider: Callable[[], Any] | None = None,
    ):
        self._capacity = int(capacity)
        self._store: OrderedDict = OrderedDict()
        self._pinned_provider = pinned_provider

    def make_key(self, fid: str, channel: str, params: dict) -> tuple:
        blob = json.dumps(params, sort_keys=True, default=str)
        return (str(fid), str(channel), blob)

    def get(self, key):
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key, result) -> None:
        self._store[key] = result
        self._store.move_to_end(key)
        pinned = (
            frozenset(self._pinned_provider())
            if self._pinned_provider is not None
            else frozenset()
        )
        # Insertion order of OrderedDict is the LRU order (oldest first).
        unpinned = [k for k in self._store if k not in pinned]
        while len(unpinned) > self._capacity:
            del self._store[unpinned.pop(0)]

    def invalidate_fid(self, fid: str) -> None:
        """Drop every entry for ``fid``, including pinned ones.

        Pinning is a residency policy, not a correctness barrier — a closed
        file's results must not survive.
        """
        fid = str(fid)
        for key in [k for k in self._store if k[0] == fid]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()


@dataclass(frozen=True)
class FrfCacheKey:
    """Directional identity for one cached SISO FRF result.

    The readable channel labels are carried only as part of their composite
    ``(fid, channel)`` identities.  Keeping the endpoints in named fields
    makes symmetric invalidation explicit and avoids depending on tuple
    offsets that belong to :class:`AnalysisResultCache`'s one-source shape.
    """

    input_fid: str
    input_channel: str
    output_fid: str
    output_channel: str
    effective_time_range: tuple[float, float] | None
    compute_params_blob: str


class FrfAnalysisResultCache(AnalysisResultCache):
    """LRU store keyed by both directional FRF endpoints."""

    @staticmethod
    def _coerce_source(source) -> tuple[str, str]:
        try:
            fid, channel = source
        except (TypeError, ValueError) as exc:
            raise ValueError("FRF source must be a (fid, channel) pair") from exc
        return str(fid), str(channel)

    @staticmethod
    def _coerce_time_range(value) -> tuple[float, float] | None:
        if value is None:
            return None
        try:
            start, end = value
        except (TypeError, ValueError) as exc:
            raise ValueError("FRF time range must be a two-value pair") from exc
        return float(start), float(end)

    def make_key(
        self,
        input_source,
        output_source,
        compute_params: Mapping[str, Any],
        effective_time_range,
    ) -> FrfCacheKey:
        input_fid, input_channel = self._coerce_source(input_source)
        output_fid, output_channel = self._coerce_source(output_source)
        blob = json.dumps(dict(compute_params), sort_keys=True, default=str)
        return FrfCacheKey(
            input_fid=input_fid,
            input_channel=input_channel,
            output_fid=output_fid,
            output_channel=output_channel,
            effective_time_range=self._coerce_time_range(effective_time_range),
            compute_params_blob=blob,
        )

    def invalidate_fid(self, fid: str) -> None:
        fid = str(fid)
        for key in [
            key
            for key in self._store
            if key.input_fid == fid or key.output_fid == fid
        ]:
            del self._store[key]
