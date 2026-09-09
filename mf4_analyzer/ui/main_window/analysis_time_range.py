"""Runtime analysis time-range intent: drafts, signatures, derived full bounds.

``PaneState.time_range`` remains the only persisted enabled span. This
controller holds session drafts and source-change review flags. Full bounds
are derived through an injected provider or from already-loaded time axes;
they are never persisted and must not be inferred from a plotted camera or
the longest loaded file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


DISPLAY_ENDPOINT_TOL = 0.0005  # seconds; Spec §6 display quantization
ORIGIN_USER_EDIT = "user_edit"
NOTE_OVERLAY_OWN_FULL = "各信号使用自身全时段"


@dataclass(frozen=True)
class SourceBounds:
    status: str  # ok | unavailable | partial
    display_range: tuple[float, float] | None
    per_source: dict = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimeRangeDraft:
    range: tuple[float, float] | None
    source_signature: object
    origin: str = ORIGIN_USER_EDIT
    valid: bool = True


@dataclass(frozen=True)
class TimeRangeIntent:
    kind: str  # full | draft | enabled | invalid | unavailable
    range: tuple[float, float] | None = None
    display_range: tuple[float, float] | None = None
    draft: TimeRangeDraft | None = None
    needs_review: bool = False
    errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source_signature: object | None = None


def as_channel_key(value):
    if value is None:
        return None
    return (str(value[0]), str(value[1]))


def _finite_pair(value):
    if value is None:
        return None
    try:
        lo = float(value[0])
        hi = float(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None
    return (lo, hi)


def parse_span(value):
    """Return ``(pair_or_none, is_valid_manual_interval)``.

    Unlike ``AnalysisContext.normalize_time_range``, an inverted or empty
    span is kept as a pair so callers can mark invalid instead of full.
    """
    pair = _finite_pair(value)
    if pair is None:
        return None, False
    return pair, pair[1] > pair[0]


def display_ranges_equal(left, right):
    """True when both ends match within 0.0005 s plus a float ulp."""
    a = _finite_pair(left)
    b = _finite_pair(right)
    if a is None or b is None:
        return a is b
    for x, y in zip(a, b):
        ulp = float(np.spacing(max(abs(x), abs(y), 1.0)))
        if abs(x - y) > DISPLAY_ENDPOINT_TOL + ulp:
            return False
    return True


def axis_extent(time_array):
    """Physical first/last of one axis. Empty or non-finite ends → None."""
    if time_array is None:
        return None
    arr = np.asarray(time_array, dtype=float)
    if arr.size == 0:
        return None
    lo = float(arr[0])
    hi = float(arr[-1])
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None
    return (lo, hi)


def envelope_of_ranges(ranges):
    pairs = [pair for pair in (_finite_pair(item) for item in ranges) if pair]
    if not pairs:
        return None
    return (min(pair[0] for pair in pairs), max(pair[1] for pair in pairs))


def common_range(ranges):
    pairs = [pair for pair in (_finite_pair(item) for item in ranges) if pair]
    if not pairs:
        return None
    lo = max(pair[0] for pair in pairs)
    hi = min(pair[1] for pair in pairs)
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi < lo:
        return None
    return (lo, hi)


def enabled_covers_sources(per_source, requested):
    """True only when every target's physical span covers ``requested``."""
    req = _finite_pair(requested)
    if req is None or req[1] <= req[0]:
        return False
    if not per_source:
        return False
    for span in per_source.values():
        src = _finite_pair(span)
        if src is None or src[0] > req[0] or src[1] < req[1]:
            return False
    return True


def make_source_signature(
    section,
    *,
    sources=(),
    rpm_mode=None,
    rpm_source=None,
    input_source=None,
    output_source=None,
    axis_facts=None,
):
    """Opaque hashable identity for one pane's compute targets.

    Channel keys are sorted so the same collection and roles compare equal
    after a reorder. Axis facts are ``(t0, t1, n)`` per source — not display
    names. FRF input/output order is directional; swapping roles changes the
    signature. Order includes ``rpm_mode`` and ``rpm_source``.
    """
    src_keys = tuple(sorted(
        as_channel_key(item) for item in (sources or ()) if item is not None
    ))
    facts_items = []
    if axis_facts:
        mapping = axis_facts.items() if hasattr(axis_facts, "items") else axis_facts
        for key, fact in mapping:
            channel = as_channel_key(key)
            if fact is None:
                facts_items.append((channel, None))
            else:
                t0, t1, n = fact[0], fact[1], fact[2]
                facts_items.append((channel, (float(t0), float(t1), int(n))))
        facts_items.sort(key=lambda item: item[0] or ())
    roles = []
    if str(section) == "order" or rpm_mode is not None or rpm_source is not None:
        roles.append((
            "rpm",
            None if rpm_mode is None else str(rpm_mode),
            as_channel_key(rpm_source),
        ))
    if str(section) == "frf" or input_source is not None or output_source is not None:
        roles.append((
            "io",
            as_channel_key(input_source),
            as_channel_key(output_source),
        ))
    return (str(section), src_keys, tuple(facts_items), tuple(roles))


def bounds_from_axes(section, named_axes):
    """Build ``SourceBounds`` from already-loaded time axes.

    Does not start analysis, rebuild a source axis, or apply a requested
    compute window. FFT overlay keeps per-source spans; the display value is
    their envelope. FRF display is the untrimmed input/output intersection.
    Order uses the signal axis only — do not pass an RPM axis as a target.
    """
    per_source = {}
    errors = []
    usable = []
    for raw_key, axis in named_axes:
        key = as_channel_key(raw_key) if raw_key is not None else raw_key
        extent = axis_extent(axis)
        per_source[key] = extent
        if extent is None:
            errors.append(f"missing source {key!r}")
        else:
            usable.append(extent)

    notes = []
    if str(section) == "frf":
        display = common_range(usable) if len(usable) >= 2 else None
        if errors and usable:
            status = "partial"
        elif errors or display is None:
            status = "unavailable"
            display = None
            if not errors:
                errors.append("FRF pair has no common physical range")
        else:
            status = "ok"
    else:
        display = envelope_of_ranges(usable)
        if errors and usable:
            status = "partial"
        elif errors or display is None:
            status = "unavailable"
            display = None
        else:
            status = "ok"
        if (
            str(section) in {"fft", "fft_time"}
            and status == "ok"
            and len(usable) > 1
        ):
            notes.append(NOTE_OVERLAY_OWN_FULL)

    return SourceBounds(
        status=status,
        display_range=display,
        per_source=per_source,
        notes=tuple(notes),
        errors=tuple(errors),
    )


def order_rpm_alignment_hook(rpm_axis, signal_range):
    """RPM coverage stays in ``_order_rpm_for`` / ``_align_rpm_to_signal_axis``.

    Full bounds are the signal axis only. Later steps may call the existing
    alignment checks; this module must not copy DSP or intersect RPM into
    the displayed full span.
    """
    return None


def _unavailable(reason):
    return SourceBounds(status="unavailable", display_range=None, errors=(reason,))


class AnalysisTimeRangeController:
    """Session owner for analysis time-range drafts and source-change review.

    Enabled spans stay on ``PaneState.time_range``. Query them through
    ``intent_for(..., enabled_range=...)`` or an ``enabled_range_provider``.
    """

    def __init__(self, *, bounds_provider=None, enabled_range_provider=None):
        self._bounds_provider = bounds_provider
        self._enabled_range_provider = enabled_range_provider
        self._drafts = {}
        self._review = {}
        self._signatures = {}

    @staticmethod
    def _key(section, view_id, pane_index):
        return (str(section), str(view_id), int(pane_index))

    def _bounds(self, section, view_id, pane_index):
        if self._bounds_provider is None:
            return _unavailable("no bounds provider")
        bounds = self._bounds_provider(section, view_id, pane_index)
        if bounds is None:
            return _unavailable("bounds provider returned None")
        return bounds

    def _enabled(self, section, view_id, pane_index, enabled_range):
        if enabled_range is not None:
            return enabled_range
        if self._enabled_range_provider is not None:
            return self._enabled_range_provider(section, view_id, pane_index)
        return None

    def source_bounds_for(self, section, view_id, pane_index):
        return self._bounds(section, view_id, pane_index)

    def draft_for(self, section, view_id, pane_index):
        return self._drafts.get(self._key(section, view_id, pane_index))

    def apply_user_edit(self, section, view_id, pane_index, span, source_signature):
        """Record a user-submitted start/end edit. Equal-to-full stays full."""
        key = self._key(section, view_id, pane_index)
        parsed, valid = parse_span(span)
        bounds = self._bounds(section, view_id, pane_index)
        if (
            valid
            and bounds.display_range is not None
            and display_ranges_equal(parsed, bounds.display_range)
        ):
            self._drafts.pop(key, None)
        else:
            self._drafts[key] = TimeRangeDraft(
                range=parsed,
                source_signature=source_signature,
                origin=ORIGIN_USER_EDIT,
                valid=valid,
            )
        self._signatures[key] = source_signature
        return self.intent_for(
            section, view_id, pane_index, source_signature=source_signature,
        )

    def clear_draft(self, section, view_id, pane_index):
        self._drafts.pop(self._key(section, view_id, pane_index), None)
        return self.intent_for(section, view_id, pane_index)

    def note_enabled(self, section, view_id, pane_index, span, source_signature=None):
        """Caller wrote ``PaneState.time_range``. Consume any draft; do not clamp."""
        key = self._key(section, view_id, pane_index)
        self._drafts.pop(key, None)
        self._review[key] = False
        if source_signature is not None:
            self._signatures[key] = source_signature
        return self.intent_for(
            section,
            view_id,
            pane_index,
            enabled_range=span,
            source_signature=source_signature,
        )

    def convert_to_full(self, section, view_id, pane_index):
        key = self._key(section, view_id, pane_index)
        self._drafts.pop(key, None)
        self._review[key] = False
        return self.intent_for(section, view_id, pane_index)

    def on_source_signature_changed(
        self, section, view_id, pane_index, new_signature, *, enabled_range=None,
    ):
        """Drop a stale draft. Keep enabled as requested; flag out-of-coverage."""
        key = self._key(section, view_id, pane_index)
        last = self._signatures.get(key)
        draft = self._drafts.get(key)
        if last is not None and last == new_signature:
            return self.intent_for(
                section,
                view_id,
                pane_index,
                enabled_range=enabled_range,
                source_signature=new_signature,
            )
        if last is not None or (
            draft is not None and draft.source_signature != new_signature
        ):
            self._drafts.pop(key, None)
        self._signatures[key] = new_signature
        enabled = self._enabled(section, view_id, pane_index, enabled_range)
        parsed, valid = parse_span(enabled) if enabled is not None else (None, False)
        if valid:
            self._review[key] = not enabled_covers_sources(
                self._bounds(section, view_id, pane_index).per_source,
                parsed,
            )
        elif enabled is not None:
            self._review[key] = True
        else:
            self._review[key] = False
        return self.intent_for(
            section,
            view_id,
            pane_index,
            enabled_range=enabled_range,
            source_signature=new_signature,
        )

    def clear_pane(self, section, view_id, pane_index):
        self._forget(self._key(section, view_id, pane_index))

    def clear_view(self, section, view_id):
        prefix = (str(section), str(view_id))
        for key in [item for item in self._all_keys() if item[:2] == prefix]:
            self._forget(key)

    def clear_all(self):
        self._drafts.clear()
        self._review.clear()
        self._signatures.clear()

    def _all_keys(self):
        return set(self._drafts) | set(self._review) | set(self._signatures)

    def _forget(self, key):
        self._drafts.pop(key, None)
        self._review.pop(key, None)
        self._signatures.pop(key, None)

    def intent_for(
        self,
        section,
        view_id,
        pane_index,
        *,
        enabled_range=None,
        source_signature=None,
    ):
        key = self._key(section, view_id, pane_index)
        bounds = self._bounds(section, view_id, pane_index)
        draft = self._drafts.get(key)
        review = bool(self._review.get(key))
        enabled = self._enabled(section, view_id, pane_index, enabled_range)
        notes = tuple(bounds.notes)
        errors = tuple(bounds.errors)

        if enabled is not None:
            parsed, valid = parse_span(enabled)
            return TimeRangeIntent(
                kind="enabled" if valid else "invalid",
                range=parsed,
                display_range=bounds.display_range,
                needs_review=review,
                errors=errors if valid else errors + ("invalid enabled range",),
                notes=notes,
                source_signature=source_signature,
            )

        if bounds.status == "unavailable":
            return TimeRangeIntent(
                kind="unavailable",
                display_range=None,
                draft=draft,
                needs_review=review,
                errors=errors,
                notes=notes,
                source_signature=source_signature,
            )

        if draft is not None:
            if not draft.valid or draft.range is None:
                return TimeRangeIntent(
                    kind="invalid",
                    range=draft.range,
                    display_range=bounds.display_range,
                    draft=draft,
                    errors=errors + ("invalid draft range",),
                    notes=notes,
                    source_signature=source_signature or draft.source_signature,
                )
            if (
                bounds.display_range is not None
                and display_ranges_equal(draft.range, bounds.display_range)
            ):
                return TimeRangeIntent(
                    kind="full",
                    display_range=bounds.display_range,
                    notes=notes,
                    errors=errors,
                    source_signature=source_signature,
                )
            return TimeRangeIntent(
                kind="draft",
                range=draft.range,
                display_range=bounds.display_range,
                draft=draft,
                notes=notes,
                errors=errors,
                source_signature=source_signature or draft.source_signature,
            )

        return TimeRangeIntent(
            kind="full",
            display_range=bounds.display_range,
            notes=notes,
            errors=errors,
            source_signature=source_signature,
        )
