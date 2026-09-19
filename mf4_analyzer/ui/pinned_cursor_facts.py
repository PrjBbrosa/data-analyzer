"""Qt-free pinned-cursor identity, reconcile, and diagnostic-row rules.

Sampling adapters, canvas dispatch, and HTML stay out of this module.
Bound and hidden identity pools are explicit parameters; nothing here
reads a canvas, host, or Qt object.
"""
from __future__ import annotations

import math
from dataclasses import replace

from .cursor_display_model import CursorDisplayChannel, PinnedCursorSample
from .plot_helpers import _cursor_identity_parts


HIDDEN_CHANNEL_TEXT = "已隐藏"
UNCHECKED_TEXT = "未勾选"
UNAVAILABLE_TEXT = "无数据"


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _reconcile_sample(intent, sample, *, bound, hidden):
    if not intent.bindings:
        return sample, intent, False
    evaluated = {}
    for channel in tuple(getattr(sample, "channels", ()) or ()) if sample is not None else ():
        key = _identity_key(getattr(channel, "identity", None))
        if key is not None:
            evaluated[key] = channel
    kept_bindings = []
    channels = []
    for binding in intent.bindings:
        key = _binding_key(binding)
        is_bound = _key_in(key, bound)
        is_hidden = _key_in(key, hidden)
        kept_bindings.append(binding)
        if not is_bound and not is_hidden:
            channels.append(
                _hidden_channel_row(binding, None, diagnostic=UNCHECKED_TEXT)
            )
            continue
        match = evaluated.get(key)
        if match is None:
            for ekey, channel in evaluated.items():
                if _key_in(key, {ekey}):
                    match = channel
                    break
        if is_hidden:
            channels.append(_hidden_channel_row(binding, match))
            continue
        if match is not None:
            channels.append(match)
            continue
        channels.append(_hidden_channel_row(binding, None, diagnostic=UNAVAILABLE_TEXT))
    if not kept_bindings:
        return None, intent, True
    next_intent = intent
    if tuple(kept_bindings) != intent.bindings:
        next_intent = replace(intent, bindings=tuple(kept_bindings))
    if sample is None:
        sample = PinnedCursorSample(
            domain=intent.domain,
            mode=intent.mode,
            x=intent.x,
            ax=intent.ax,
            bx=intent.bx,
            channels=tuple(channels),
        )
    else:
        extrema = tuple(
            item for item in (getattr(sample, "extrema", ()) or ())
            if not _key_in(
                _identity_key(getattr(item, "identity", None)), hidden,
            )
        )
        sample = replace(sample, channels=tuple(channels), extrema=extrema)
    return sample, next_intent, False


def _binding_key(binding):
    fid = str(binding.fid)
    channel = str(binding.channel)
    binding_id = str(getattr(binding, "binding_id", "") or "")
    if binding_id:
        return (fid, channel, binding_id)
    return (fid, channel)


def _key_in(key, pool) -> bool:
    """Existing match contract: exact key, else fid+channel ignoring binding_id.

    A 2-tuple and a 3-tuple that share fid+channel currently match each
    other. Distinct binding_id values also match via that fallback. Do not
    "tighten" this without a recorded mismatch and an explicit scope decision.
    """
    if key is None or not pool:
        return False
    if key in pool:
        return True
    fid, channel = key[0], key[1]
    if not fid or not channel:
        return False
    return any(
        item[0] == fid and item[1] == channel
        for item in pool
    )


def _hidden_channel_row(binding, existing, diagnostic=HIDDEN_CHANNEL_TEXT):
    if existing is not None and isinstance(existing, CursorDisplayChannel):
        return replace(
            existing,
            current_value=None,
            delta=None,
            min_value=None,
            max_value=None,
            avg_value=None,
            branches=(),
            diagnostic=diagnostic,
        )
    return CursorDisplayChannel(
        identity=(
            (binding.fid, binding.channel, binding.binding_id)
            if binding.binding_id else (binding.fid, binding.channel)
        ),
        source_label="",
        channel_label=binding.channel,
        diagnostic=diagnostic,
    )


def _sample_has_numeric(sample) -> bool:
    if sample is None:
        return False
    if getattr(sample, "frf_sample", None) is not None:
        return True
    skip = {HIDDEN_CHANNEL_TEXT, UNAVAILABLE_TEXT, UNCHECKED_TEXT}
    for channel in tuple(getattr(sample, "channels", ()) or ()):
        if str(getattr(channel, "diagnostic", "") or "") in skip:
            continue
        if getattr(channel, "current_value", None) is not None:
            return True
        if getattr(channel, "value", None) is not None:
            return True
        if getattr(channel, "a_value", None) is not None:
            return True
        if getattr(channel, "min_value", None) is not None:
            return True
        if tuple(getattr(channel, "branches", ()) or ()):
            return True
        if str(getattr(channel, "diagnostic", "") or ""):
            return True
    return False


def _sample_has_hidden(sample) -> bool:
    for channel in tuple(getattr(sample, "channels", ()) or ()):
        if str(getattr(channel, "diagnostic", "") or "") == HIDDEN_CHANNEL_TEXT:
            return True
    return False


def _sample_has_unchecked(sample) -> bool:
    for channel in tuple(getattr(sample, "channels", ()) or ()):
        if str(getattr(channel, "diagnostic", "") or "") == UNCHECKED_TEXT:
            return True
    return False


def _hidden_keys_from_sample(sample):
    keys = set()
    skip = {HIDDEN_CHANNEL_TEXT, UNCHECKED_TEXT}
    for channel in tuple(getattr(sample, "channels", ()) or ()) if sample is not None else ():
        if str(getattr(channel, "diagnostic", "") or "") not in skip:
            continue
        key = _identity_key(getattr(channel, "identity", None))
        if key is not None:
            keys.add(key)
    return keys


def _identity_key(identity):
    if identity is None:
        return None
    if isinstance(identity, (tuple, list)) and len(identity) >= 2:
        fid = "" if identity[0] is None else str(identity[0])
        channel = "" if identity[1] is None else str(identity[1])
        binding_id = ""
        if len(identity) >= 3 and identity[2]:
            binding_id = str(identity[2])
        if fid and channel:
            return (fid, channel, binding_id) if binding_id else (fid, channel)
        return None
    fid, channel = _cursor_identity_parts(identity)
    if fid and channel:
        return (str(fid), str(channel))
    return None
