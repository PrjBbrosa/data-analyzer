"""Qt-free time-domain overlay semantics: remarks and dual-cursor placement.

ViewState holds the lists this module normalizes. Live canvases and
``view_bridge`` are not imported here — this layer must stay free of
PyQt5, pyqtgraph, and ``mf4_analyzer.ui.pg_canvas``.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


_REMARK_NUM_KEYS = ("x", "y", "label_dx", "label_dy")
_REMARK_KNOWN_KEYS = frozenset(("source", *_REMARK_NUM_KEYS))


def raw_channel_name(channel: Any) -> str:
    """Return the navigator/ViewState channel identity from a plot label.

    Time-domain rows are drawn as ``[{short_name}] {channel}``. Persistence
    and D5 merge must use the raw channel, matching ``checked``.
    """
    text = str(channel)
    if text.startswith("[") and "] " in text:
        return text.split("] ", 1)[1]
    return text


def normalize_remark(raw: Any) -> dict | None:
    """Return a JSON-safe remark dict, or ``None`` if the item is illegal.

    Illegal: missing ``source``, ``source`` not a 2-list/tuple, or any of
    ``x`` / ``y`` / ``label_dx`` / ``label_dy`` missing or non-finite.
    Unknown extra keys on the remark object are preserved. ``source`` is
    emitted as a JSON-safe 2-list; never flattened via ``dict(source)``.
    """
    if not isinstance(raw, Mapping):
        return None
    source = _source_two_list(raw.get("source"))
    if source is None:
        return None
    numbers: dict[str, float] = {}
    for key in _REMARK_NUM_KEYS:
        value = _finite_float(raw.get(key))
        if value is None:
            return None
        numbers[key] = value
    out: dict[str, Any] = {
        "source": source,
        "x": numbers["x"],
        "y": numbers["y"],
        "label_dx": numbers["label_dx"],
        "label_dy": numbers["label_dy"],
    }
    for key, value in raw.items():
        if key not in _REMARK_KNOWN_KEYS:
            out[key] = value
    return out


def normalize_remarks(raw: Any) -> list[dict]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    out: list[dict] = []
    for item in raw:
        remark = normalize_remark(item)
        if remark is not None:
            out.append(remark)
    return out


def remap_remarks(remarks: Any, fid_map: Mapping[Any, Any] | None) -> list[dict]:
    """Rewrite each remark ``source[0]`` through ``fid_map``; drop misses."""
    mapping = fid_map if isinstance(fid_map, Mapping) else {}
    out: list[dict] = []
    for remark in normalize_remarks(remarks):
        old_fid = remark["source"][0]
        if old_fid not in mapping:
            continue
        remapped = dict(remark)
        remapped["source"] = [str(mapping[old_fid]), remark["source"][1]]
        out.append(remapped)
    return out


def merge_remarks_for_capture(
    live: Any,
    previous: Any,
    *,
    attached_file_ids: Any = (),
    checked: Any = (),
    hidden_channels: Any = (),
) -> list[dict]:
    """Merge a live canvas snapshot with prior ViewState remarks (spec D5).

    Live items win for every source present in ``live``. Previous items are
    kept only when their source still belongs to this View and is not
    currently visible. A visible source missing from ``live`` is treated as
    a user deletion and is not restored from ``previous``.
    """
    live_norm = normalize_remarks(live)
    prev_norm = normalize_remarks(previous)
    live_sources = {
        key
        for key in (_source_identity(item["source"]) for item in live_norm)
        if key is not None
    }
    attached = {
        str(fid)
        for fid in _as_sequence(attached_file_ids)
        if fid is not None
    }
    checked_keys = _identity_set(checked)
    hidden_keys = _identity_set(hidden_channels)
    kept: list[dict] = []
    for item in prev_norm:
        key = _source_identity(item["source"])
        if key is None or key in live_sources:
            continue
        visible = key in checked_keys and key not in hidden_keys
        if visible:
            continue
        belongs = (
            key[0] in attached
            or key in checked_keys
            or key in hidden_keys
        )
        if belongs:
            kept.append(item)
    return live_norm + kept


def normalize_cursor_placement(raw: Any, *, cursor_mode: str) -> dict | None:
    """Persist dual-cursor A/B data coordinates only.

    Returns ``{"ax": float, "bx": float|None}`` when ``cursor_mode == "dual"``
    and ``ax`` is finite; otherwise ``None``. Does not persist ``placing``,
    single-cursor x, or pill HTML.
    """
    if cursor_mode != "dual" or not isinstance(raw, Mapping):
        return None
    ax = _finite_float(raw.get("ax"))
    if ax is None:
        return None
    if "bx" not in raw or raw.get("bx") is None:
        bx: float | None = None
    else:
        bx = _finite_float(raw.get("bx"))
        if bx is None:
            bx = None
    return {"ax": ax, "bx": bx}


def _as_sequence(value: Any) -> Sequence:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _identity_pair(value: Any) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        return None
    if isinstance(value, (str, bytes, bytearray)):
        return None
    if not isinstance(value, Sequence) or len(value) < 2:
        return None
    fid, channel = value[0], value[1]
    if fid is None or channel is None:
        return None
    return (str(fid), str(channel))


def _identity_set(items: Any) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for item in _as_sequence(items):
        key = _identity_pair(item)
        if key is not None:
            out.add(key)
    return out


def _source_identity(value: Any) -> tuple[str, str] | None:
    two = _source_two_list(value)
    if two is None:
        return None
    return (two[0], two[1])


def _source_two_list(value: Any) -> list[str] | None:
    # Identity is a 2-list like ``checked``. Mappings (including
    # ``_ChannelKeyDict``) are not a source — never ``dict(value)``.
    if isinstance(value, Mapping):
        return None
    if isinstance(value, (str, bytes, bytearray)):
        return None
    if not isinstance(value, Sequence) or len(value) != 2:
        return None
    fid, channel = value
    if fid is None or channel is None:
        return None
    return [str(fid), raw_channel_name(channel)]


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
