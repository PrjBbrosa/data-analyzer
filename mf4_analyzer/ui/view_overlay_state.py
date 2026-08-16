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
    """Deprecated pass-through: return ``normalize_remarks(live)``.

    Annotation intent already includes hidden-channel entries, so D5's
    live/previous/visibility merge has no remaining caller. Kept for one
    compatibility release (2026-08-16 daily-review-followup spec A2).
    """
    del previous, attached_file_ids, checked, hidden_channels
    return normalize_remarks(live)


def normalize_cursor_placement(raw: Any, *, cursor_mode: str) -> dict | None:
    """Persist dual-cursor A/B data coordinates regardless of ``cursor_mode``.

    ``cursor_mode`` remains in the signature for call-site compatibility
    (D3 2026-08-16 revision) and is not used as a filter. Returns
    ``{"ax": float, "bx": float|None}`` when ``ax`` is finite; otherwise
    ``None``. Does not persist ``placing``, single-cursor x, or pill HTML.
    """
    del cursor_mode
    if not isinstance(raw, Mapping):
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
