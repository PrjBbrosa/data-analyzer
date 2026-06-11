"""Per-section LRU result cache (spec §6.4).

Generalizes main_window's _fft_time_cache (capacity 12). Keys hash only
compute-relevant params — callers must pass the filtered dict (the
existing _fft_time_cache_key convention: display-only knobs excluded).
"""
from __future__ import annotations

import json
from collections import OrderedDict


class AnalysisResultCache:
    def __init__(self, capacity: int):
        self._capacity = int(capacity)
        self._store: OrderedDict = OrderedDict()

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
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)

    def invalidate_fid(self, fid: str) -> None:
        fid = str(fid)
        for key in [k for k in self._store if k[0] == fid]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()
