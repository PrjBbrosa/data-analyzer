"""Shared pure helpers for pyqtgraph time-domain canvas modules."""

from __future__ import annotations

import json

from mf4_analyzer.ui.plot_helpers import _compact_axis_label


def _subplot_ylabel_text(name, unit):
    """Subplot left-axis label: compact channel name plus unit suffix."""
    compact = _compact_axis_label(name, unit, max_chars=20)
    return f"{compact}" + (f" ({unit})" if unit else "")


def _view_state_channel_key(data_id, name):
    stable_data_id = None if data_id is None else str(data_id)
    return json.dumps(
        [stable_data_id, str(name)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class _ChannelKeyDict(dict):
    """Channel-keyed mapping whose IDENTITY is the composite ``(data_id, name)``
    key but whose iteration/display surface stays the human-readable channel
    ``name``.

    Why this exists (multi-file same-name root fix):
        Time-domain channel names are prefixed with the source file's
        ``[short_name]`` so two files normally produce distinct names. When two
        filenames collapse to the same truncated ``short_name`` (file_data.py
        head-truncation), the prefixed names ALSO collide — keying the storage
        dict on ``name`` then makes the second-bound channel OVERWRITE the
        first, orphaning the first curve. Checking-all-then-unchecking one then
        makes a surviving curve vanish because its storage slot was clobbered.

    Design:
        * Storage is keyed by the composite key string from
          ``_view_state_channel_key(data_id, name)`` — distinct files never
          collide even when their display ``name`` is identical (the ROOT fix,
          not a probability reduction).
        * ``__setitem__`` is called with the composite key by the binding code
          and records the display ``name`` via ``set_with_label``; plain
          ``d[composite] = value`` still works (label falls back to the parsed
          name embedded in the composite key).
        * Reads (``__getitem__`` / ``get`` / ``__contains__`` / ``pop``) accept
          EITHER the composite key OR a bare/prefixed display ``name``. A bare
          name resolves to its (unique) composite entry; this keeps every
          existing ``canvas.channel_data["torque"]`` / ``_channel_lines["ch0"]``
          call site and test working unchanged.
        * Iteration (``items`` / ``keys`` / ``values`` / ``__iter__``) yields
          the DISPLAY name as the key for the display/stats/cursor/annotation
          consumers that treat the key as a label. BOTH colliding entries are
          still yielded as separate pairs (no curve is dropped) because the
          underlying storage holds two distinct composite keys.
        * Identity-sensitive consumers (the viewport-envelope cache in
          renderer.py) must key their per-line caches by the COMPOSITE key, not
          the display name, or two same-named channels cross-contaminate. Use
          :meth:`composite_items` (yields ``(composite_key, display_name,
          value)``) on those hot paths.
    """

    def __init__(self, *args, **kwargs):
        self._labels: dict = {}
        self._name_index: dict = {}
        super().__init__()
        if args or kwargs:
            for k, v in dict(*args, **kwargs).items():
                self[k] = v

    # -- internal helpers ------------------------------------------------
    @staticmethod
    def _looks_composite(key) -> bool:
        if not isinstance(key, str):
            return False
        try:
            parsed = json.loads(key)
        except (ValueError, TypeError):
            return False
        return isinstance(parsed, list) and len(parsed) == 2

    @staticmethod
    def _label_from_composite(key):
        try:
            parsed = json.loads(key)
            return str(parsed[1])
        except (ValueError, TypeError, IndexError):
            return key

    def _resolve(self, key):
        """Map ``key`` (composite OR bare display name) to a stored composite
        key, or ``None`` when absent."""
        if dict.__contains__(self, key):
            return key
        bucket = self._name_index.get(key)
        if bucket:
            # Last-bound wins for an ambiguous bare-name read; storage still
            # holds every colliding entry so iteration never drops one.
            return bucket[-1]
        return None

    def _register_label(self, composite_key, label):
        self._labels[composite_key] = label
        bucket = self._name_index.setdefault(label, [])
        if composite_key not in bucket:
            bucket.append(composite_key)

    def _drop_label(self, composite_key):
        label = self._labels.pop(composite_key, None)
        bucket = self._name_index.get(label)
        if bucket and composite_key in bucket:
            bucket.remove(composite_key)
            if not bucket:
                self._name_index.pop(label, None)

    # -- write surface ---------------------------------------------------
    def set_with_label(self, composite_key, label, value):
        """Store ``value`` under ``composite_key`` and remember ``label`` as the
        display name yielded during iteration / bare-name lookups."""
        dict.__setitem__(self, composite_key, value)
        self._register_label(composite_key, str(label))

    def __setitem__(self, key, value):
        # A bare-name write updates the existing composite slot when one is
        # resolvable; otherwise the key is taken as-is (composite or literal).
        composite_key = self._resolve(key)
        if composite_key is None:
            composite_key = key
        dict.__setitem__(self, composite_key, value)
        if composite_key not in self._labels:
            label = (
                self._label_from_composite(composite_key)
                if self._looks_composite(composite_key)
                else str(composite_key)
            )
            self._register_label(composite_key, label)

    def __delitem__(self, key):
        composite_key = self._resolve(key)
        if composite_key is None:
            raise KeyError(key)
        dict.__delitem__(self, composite_key)
        self._drop_label(composite_key)

    def pop(self, key, *default):
        composite_key = self._resolve(key)
        if composite_key is None:
            if default:
                return default[0]
            raise KeyError(key)
        value = dict.pop(self, composite_key)
        self._drop_label(composite_key)
        return value

    def clear(self):
        dict.clear(self)
        self._labels.clear()
        self._name_index.clear()

    # -- read surface ----------------------------------------------------
    def __getitem__(self, key):
        composite_key = self._resolve(key)
        if composite_key is None:
            raise KeyError(key)
        return dict.__getitem__(self, composite_key)

    def get(self, key, default=None):
        composite_key = self._resolve(key)
        if composite_key is None:
            return default
        return dict.__getitem__(self, composite_key)

    def __contains__(self, key):
        return self._resolve(key) is not None

    def display_label(self, key, default=None):
        """Return the display name for ``key`` (composite or bare)."""
        composite_key = self._resolve(key)
        if composite_key is None:
            return default
        return self._labels.get(composite_key, composite_key)

    def composite_key_for(self, key):
        """Return the stored composite key for ``key`` (composite or bare)."""
        return self._resolve(key)

    # -- iteration (display-name surface) --------------------------------
    def __iter__(self):
        for composite_key in dict.__iter__(self):
            yield self._labels.get(composite_key, composite_key)

    def keys(self):
        return list(self.__iter__())

    def values(self):
        return [dict.__getitem__(self, ck) for ck in dict.__iter__(self)]

    def items(self):
        return [
            (self._labels.get(ck, ck), dict.__getitem__(self, ck))
            for ck in dict.__iter__(self)
        ]

    def composite_items(self):
        """Yield ``(composite_key, display_name, value)`` for identity-sensitive
        consumers (the viewport-envelope cache) that must key per-(data_id,name)
        and NOT per display name (which can collide across files)."""
        for composite_key in list(dict.__iter__(self)):
            yield (
                composite_key,
                self._labels.get(composite_key, composite_key),
                dict.__getitem__(self, composite_key),
            )


def _hide_native_auto_button(plot) -> None:
    """Hide pyqtgraph's built-in lower-left auto-range button."""
    hide = getattr(plot, "hideButtons", None)
    if callable(hide):
        hide()


def show_major_grid_left_bottom_only(plot, *, x=True, y=True, alpha=0.25):
    """Enable major grid on left+bottom and force top/right OFF."""
    plot.showGrid(x=bool(x), y=bool(y), alpha=alpha)
    for name in ("top", "right"):
        try:
            plot.getAxis(name).setGrid(False)
        except Exception:
            pass
