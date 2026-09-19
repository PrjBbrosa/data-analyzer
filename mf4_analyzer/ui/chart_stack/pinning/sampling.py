"""Qt canvas dispatch for pinned-cursor facts.

This adapter is not Qt-free. It may hold the current canvas and call the
canvas's existing sample methods. It does not copy DSP, interpolation, or
FFT, and it does not keep a long-lived sample cache.
"""
from __future__ import annotations

from dataclasses import replace

from ...cursor_display_model import PinnedCursorSample
from ...pg_canvas.frf_canvas import PgFrfCanvas
from ...pg_canvas.line_canvas import PgLineCanvas
from ...pg_canvases import TimeDomainCanvasPG
from ...pinned_cursor_facts import (
    _finite,
    _identity_key,
    _sample_has_hidden,
    _sample_has_numeric,
    _sample_has_unchecked,
)
from ...pinned_cursor_state import PinnedCursorBinding
from ...plot_helpers import _cursor_identity_parts


PIN_STATUS_READY = "ready"
PIN_STATUS_PENDING = "pending"
PIN_STATUS_UNAVAILABLE = "unavailable"
PIN_STATUS_INCOMPATIBLE_AXIS = "incompatible_axis"


class PinSampleEvaluator:
    """Per-call canvas adapter. ``_canvas`` is the last canvas, not a cache."""

    def __init__(self):
        self._canvas = None

    def bind_canvas(self, canvas) -> None:
        self._canvas = canvas

    def evaluate(self, canvas, domain, *, mode, x=None, ax=None, bx=None):
        self._canvas = canvas
        if mode == "single":
            if domain in {"time", "channel"}:
                fn = self.sample_fn(canvas, "evaluate_single_cursor_sample")
                if callable(fn):
                    return fn(x)
                rows = canvas.evaluate_single_cursor(x)
                return self.wrap_channels(domain, "single", x=x, channels=rows)
            fn = getattr(canvas, "evaluate_frequency_cursor_sample", None)
            if callable(fn):
                return fn(x)
            result = canvas.evaluate_frequency_cursor(x)
            if result is None:
                return None
            if domain == "frf":
                return self.wrap_frf("single", result)
            snapped, channels = result
            return self.wrap_channels(
                "frequency", "single", x=snapped, channels=channels,
            )
        if domain in {"time", "channel"}:
            fn = self.sample_fn(canvas, "evaluate_dual_cursor_sample")
            if callable(fn):
                return fn(ax, bx)
            rows = canvas.evaluate_dual_cursor(ax, bx)
            return self.wrap_channels(domain, "dual", ax=ax, bx=bx, channels=rows)
        fn = getattr(canvas, "evaluate_dual_frequency_cursor_sample", None)
        if callable(fn):
            return fn(ax, bx)
        result = canvas.evaluate_dual_frequency_cursor(ax, bx)
        if result is None:
            return None
        if domain == "frf":
            return self.wrap_frf("dual", result)
        a_value, b_value, channels = result
        return self.wrap_channels(
            "frequency", "dual", ax=a_value, bx=b_value, channels=channels,
        )

    def evaluate_intent(self, canvas, intent):
        self._canvas = canvas
        if not self.axis_compatible(canvas, intent):
            return None
        domain = intent.domain
        if intent.mode == "single":
            sample = self.evaluate(canvas, domain, mode="single", x=intent.x)
        else:
            sample = self.evaluate(
                canvas, domain, mode="dual", ax=intent.ax, bx=intent.bx,
            )
        return self.stamp_sample(canvas, sample)

    @staticmethod
    def sample_fn(canvas, name):
        fn = getattr(canvas, name, None)
        if callable(fn):
            return fn
        cursor = getattr(canvas, "_cursor", None)
        fn = getattr(cursor, name, None)
        return fn if callable(fn) else None

    @staticmethod
    def wrap_channels(domain, mode, *, x=None, ax=None, bx=None, channels=()):
        return PinnedCursorSample(
            domain=domain,
            mode=mode,
            x=_finite(x),
            ax=_finite(ax),
            bx=_finite(bx),
            channels=tuple(channels or ()),
        )

    @staticmethod
    def wrap_frf(mode, sample):
        if sample is None:
            return None
        if mode == "single":
            return PinnedCursorSample(
                domain="frf",
                mode="single",
                x=_finite(getattr(sample, "frequency_hz", None)),
                frf_sample=sample,
            )
        return PinnedCursorSample(
            domain="frf",
            mode="dual",
            ax=None if sample.a is None else _finite(sample.a.frequency_hz),
            bx=None if sample.b is None else _finite(sample.b.frequency_hz),
            frf_sample=sample,
        )

    @staticmethod
    def sample_has_result(sample) -> bool:
        if sample is None:
            return False
        if getattr(sample, "frf_sample", None) is not None:
            return True
        if tuple(getattr(sample, "channels", ()) or ()):
            return True
        return bool(str(getattr(sample, "diagnostic", "") or "").strip())

    def axis_status(self, canvas, intent) -> str:
        if not self.axis_compatible(canvas, intent):
            return PIN_STATUS_INCOMPATIBLE_AXIS
        if self.log_unavailable(canvas, intent):
            return PIN_STATUS_UNAVAILABLE
        return PIN_STATUS_READY

    def status_for_sample(self, canvas, intent, sample) -> str:
        status = self.axis_status(canvas, intent)
        if status != PIN_STATUS_READY:
            return status
        if sample is None or (
            not _sample_has_numeric(sample)
            and not _sample_has_hidden(sample)
            and not _sample_has_unchecked(sample)
        ):
            return PIN_STATUS_UNAVAILABLE
        return PIN_STATUS_READY

    def axis_compatible(self, canvas, intent) -> bool:
        current = self.domain_for(canvas)
        if intent.domain in {"frequency", "frf"}:
            return current == intent.domain
        if intent.domain == "time":
            return current == "time"
        if intent.domain == "channel":
            if current != "channel":
                return False
            wanted = intent.axis_identity
            if wanted is None:
                return True
            return self.axis_identity(canvas, "channel") == wanted
        return current == intent.domain

    def log_unavailable(self, canvas, intent) -> bool:
        checker = getattr(canvas, "_is_log_frequency", None)
        if not callable(checker) or not checker():
            return False
        if intent.domain not in {"frequency", "frf"}:
            return False
        values = (intent.x,) if intent.mode == "single" else (intent.ax, intent.bx)
        return any(
            value is not None and _finite(value) is not None and value <= 0
            for value in values
        )

    @staticmethod
    def canvas_compute_pending(canvas) -> bool:
        state = getattr(canvas, "state", None)
        token = state() if callable(state) else None
        return token in {"progress", "stale"}

    def canvas_generations(self, canvas):
        self._canvas = canvas
        binding = getattr(canvas, "_spectrum_display_generation", None)
        if binding is None:
            binding = getattr(canvas, "_interaction_generation", None)
        revision = getattr(canvas, "_spectrum_display_revision", None)
        if revision is None:
            revision = getattr(canvas, "_cursor_data_revision", None)
        if revision is None:
            cursor = getattr(canvas, "_cursor", None)
            revision = getattr(cursor, "_cursor_data_revision", None)
        try:
            binding = int(binding) if binding is not None else None
        except (TypeError, ValueError):
            binding = None
        try:
            revision = int(revision) if revision is not None else None
        except (TypeError, ValueError):
            revision = None
        return binding, revision

    def stamp_sample(self, canvas, sample):
        if sample is None or not isinstance(sample, PinnedCursorSample):
            return sample
        generation, revision = self.canvas_generations(canvas)
        updates = {}
        if sample.binding_generation is None and generation is not None:
            updates["binding_generation"] = generation
        if sample.data_revision is None and revision is not None:
            updates["data_revision"] = revision
        return replace(sample, **updates) if updates else sample

    @staticmethod
    def sample_matches_generation(sample, generation, revision) -> bool:
        if sample is None:
            return False
        sample_gen = getattr(sample, "binding_generation", None)
        sample_rev = getattr(sample, "data_revision", None)
        if sample_gen is not None and generation is not None and sample_gen != generation:
            return False
        if sample_rev is not None and revision is not None and sample_rev != revision:
            return False
        return True

    def bound_identity_keys(self, canvas):
        self._canvas = canvas
        keys = set()
        lines = getattr(canvas, "_channel_lines", None)
        items = getattr(lines, "composite_items", None)
        if callable(items):
            for channel_key, name, _values in items():
                key = _identity_key(channel_key)
                if key is not None:
                    keys.add(key)
            return keys
        data = getattr(canvas, "channel_data", None)
        if data is not None and hasattr(data, "items"):
            for name in data:
                key = _identity_key(name)
                if key is not None:
                    keys.add(key)
        entries = getattr(canvas, "_entries", None) or ()
        for entry in entries:
            identity = entry.get("identity") if isinstance(entry, dict) else None
            if identity is None and isinstance(entry, dict):
                fid = entry.get("fid")
                channel = entry.get("channel")
                binding_id = entry.get("binding_id") or ""
                if fid and channel:
                    identity = (fid, channel, binding_id) if binding_id else (fid, channel)
            key = _identity_key(identity)
            if key is not None:
                keys.add(key)
        return keys

    def hidden_identity_keys(self, canvas):
        self._canvas = canvas
        keys = set()
        cursor = getattr(canvas, "_cursor", None)
        hidden = getattr(cursor, "_hidden_channel_names", None)
        names = hidden() if callable(hidden) else ()
        for item in names or ():
            key = _identity_key(item)
            if key is not None:
                keys.add(key)
        return keys

    def domain_for(self, canvas) -> str | None:
        self._canvas = canvas
        if isinstance(canvas, PgFrfCanvas):
            return "frf"
        if isinstance(canvas, PgLineCanvas):
            return "frequency"
        if isinstance(canvas, TimeDomainCanvasPG):
            checker = getattr(canvas, "cursor_x_mode", None)
            if callable(checker) and checker():
                return "channel"
            return "time"
        return None

    @staticmethod
    def bindings_from_sample(sample) -> tuple[PinnedCursorBinding, ...]:
        if sample is None:
            return ()
        out = []
        seen = set()
        for channel in getattr(sample, "channels", ()) or ():
            identity = getattr(channel, "identity", None)
            fid = channel_name = binding_id = ""
            if isinstance(identity, (tuple, list)) and len(identity) >= 2:
                fid = str(identity[0] or "")
                channel_name = str(identity[1] or "")
                if len(identity) >= 3 and identity[2]:
                    binding_id = str(identity[2])
            else:
                parsed_fid, parsed_channel = _cursor_identity_parts(identity)
                fid = str(parsed_fid or "")
                channel_name = str(parsed_channel or "")
            if not channel_name:
                channel_name = str(getattr(channel, "channel_label", "") or "")
            if not fid or not channel_name:
                continue
            key = (fid, channel_name, binding_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(PinnedCursorBinding(
                fid=fid, channel=channel_name, binding_id=binding_id,
            ))
        return tuple(out)

    @staticmethod
    def axis_identity(canvas, domain):
        if domain != "channel":
            return None
        ctx = getattr(getattr(canvas, "_cursor", None), "x_axis_context", None)
        identity = getattr(ctx, "identity", None)
        if isinstance(identity, tuple) and len(identity) == 2:
            fid, channel = identity
            if fid and channel:
                return (str(fid), str(channel))
        return None

    @staticmethod
    def x_unit(canvas, domain) -> str:
        if domain == "time":
            return "s"
        if domain in {"frequency", "frf"}:
            return "Hz"
        ctx = getattr(getattr(canvas, "_cursor", None), "x_axis_context", None)
        unit = str(getattr(ctx, "unit", "") or "").strip()
        return unit
