"""Chart-appearance identity registry and public canvas operations.

Identity is stored on this collaborator only. It is rebuilt from row metadata
on bind / selection-delta / clear and is never persisted or mirrored onto
MainWindow. Unknown or colliding identities return unavailable with a reason;
this module does not guess the first fid or a display-name prefix.
"""

from __future__ import annotations

import logging
import math

from mf4_analyzer.diagnostics import throttled
from mf4_analyzer.ui._axis_handle import snapshot_axis_appearance
from mf4_analyzer.ui.chart_appearance_model import (
    KIND_BINDING,
    KIND_CHANNEL,
    KIND_COMPANION,
    REASON_AMBIGUOUS_IDENTITY,
    REASON_MERGED_CURVE_KEY,
    REASON_MISSING_IDENTITY,
    REASON_UNKNOWN_HANDLE,
    AppearanceRef,
    ChartAppearanceSnapshot,
    ChartAppearanceTarget,
    appearance_companion_color_key,
    appearance_ref_fingerprint,
    available_group_target,
    normalize_resolved_chart_appearance,
    parse_appearance_ref,
    target_from_ref,
    unavailable_target,
)
from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref


_LOG = logging.getLogger(__name__)


def _parse_plot_row(row):
    if len(row) >= 8 and isinstance(row[7], dict):
        name, visible, t, sig, color, unit, data_id, meta = row[:8]
    elif len(row) >= 7:
        name, visible, t, sig, color, unit, data_id = row[:7]
        meta = None
    else:
        name, visible, t, sig, color, unit = row[:6]
        data_id = None
        meta = None
    return name, visible, t, sig, color, unit, data_id, dict(meta or {})


class AppearanceManager(_CanvasBackref):
    """Stable appearance identity + apply/repair helpers for TimeDomainCanvasPG."""

    _owned_names = frozenset({
        "_identities",
        "_ambiguous_curve_keys",
        "_merged_curve_keys",
    })

    _delegate_names = frozenset({
        "appearance_target_for_handle",
        "companion_source_key",
        "snapshot_chart_appearance",
        "apply_chart_appearance",
        "repair_chart_appearance_ranges",
        "reset",
        "sync_from_rows",
        "sync_from_parsed",
        "emit_typed_color_if_unique",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self._identities: dict[str, AppearanceRef] = {}
        self._ambiguous_curve_keys: set[str] = set()
        self._merged_curve_keys: set[str] = set()

    def reset(self):
        self._identities = {}
        self._ambiguous_curve_keys = set()
        self._merged_curve_keys = set()

    def sync_from_rows(self, rows):
        """Rebuild the identity registry from plot rows currently being bound.

        Walk the raw row list so two same-fid/same-display records can still
        be detected as a merged-key collision after curve storage overwrites.
        """
        seen_refs: dict[str, AppearanceRef] = {}
        merged: set[str] = set()
        parsed: dict[str, dict] = {}
        for row in rows or []:
            name, _visible, _t, _sig, _color, _unit, data_id, meta = _parse_plot_row(row)
            key = _view_state_channel_key(data_id, name)
            ref = parse_appearance_ref(meta)
            previous = seen_refs.get(key)
            collided = bool(parsed.get(key, {}).get("appearance_collision"))
            if (
                previous is not None
                and ref is not None
                and previous.fingerprint() != ref.fingerprint()
            ):
                collided = True
                merged.add(key)
            if ref is not None and key not in merged:
                seen_refs[key] = ref
            parsed[key] = {
                "appearance_ref": None if collided else ref,
                "appearance_fingerprint": appearance_ref_fingerprint(meta),
                "appearance_collision": collided,
            }
        for key in merged:
            parsed[key] = {
                "appearance_ref": None,
                "appearance_fingerprint": (),
                "appearance_collision": True,
            }
        self.sync_from_parsed(parsed)

    def sync_from_parsed(self, parsed):
        """Sync identities for currently bound curves.

        Incoming rows that share a composite curve key but disagree on
        appearance identity are marked merged/ambiguous. The canvas key schema
        is not expanded; those handles return unavailable rather than picking
        a winner.
        """
        identities: dict[str, AppearanceRef] = {}
        ambiguous: set[str] = set()
        merged: set[str] = set()
        incoming = parsed or {}

        seen_refs: dict[str, AppearanceRef] = {}
        for key, info in incoming.items():
            collided = bool(isinstance(info, dict) and info.get("appearance_collision"))
            ref = info.get("appearance_ref") if isinstance(info, dict) else None
            if not isinstance(ref, AppearanceRef):
                ref = parse_appearance_ref(info)
            if collided:
                merged.add(key)
                ambiguous.add(key)
                continue
            if ref is None:
                continue
            previous = seen_refs.get(key)
            if previous is not None and previous.fingerprint() != ref.fingerprint():
                ambiguous.add(key)
                merged.add(key)
                continue
            seen_refs[key] = ref

        bound_keys = set()
        composite_items = getattr(self._channel_lines, "composite_items", None)
        if callable(composite_items):
            try:
                bound_keys = {ck for ck, _name, _pair in composite_items()}
            except (AttributeError, RuntimeError, TypeError):
                bound_keys = set()

        for key in bound_keys:
            if key in merged:
                ambiguous.add(key)
                continue
            ref = seen_refs.get(key)
            if isinstance(ref, AppearanceRef):
                identities[key] = ref

        self._identities = identities
        self._ambiguous_curve_keys = ambiguous
        self._merged_curve_keys = merged

    def appearance_target_for_handle(self, handle) -> ChartAppearanceTarget:
        if handle is None:
            return self._unavailable(REASON_UNKNOWN_HANDLE)
        axes = list(getattr(self, "axes_list", None) or [])
        if handle not in axes:
            return self._unavailable(REASON_UNKNOWN_HANDLE)

        gid = getattr(handle, "axis_group", None)
        if gid:
            target = available_group_target(gid)
            if target.available:
                return target
            return self._unavailable(REASON_MISSING_IDENTITY)

        refs: list[AppearanceRef] = []
        saw_bound = False
        saw_missing = False
        saw_merged = False
        composite_items = getattr(self._channel_lines, "composite_items", None)
        companions = getattr(self, "_companion_names", set()) or set()
        if not callable(composite_items):
            return self._unavailable(REASON_MISSING_IDENTITY)
        try:
            items = list(composite_items())
        except (AttributeError, RuntimeError, TypeError):
            return self._unavailable(REASON_MISSING_IDENTITY)
        for ck, _name, pair in items:
            owner = pair[0] if pair else None
            if owner is not handle:
                continue
            if ck in companions:
                continue
            saw_bound = True
            if ck in self._merged_curve_keys:
                saw_merged = True
                continue
            if ck in self._ambiguous_curve_keys:
                return self._unavailable(REASON_AMBIGUOUS_IDENTITY)
            ref = self._identities.get(ck)
            if ref is None or ref.kind == KIND_COMPANION:
                saw_missing = True
                continue
            refs.append(ref)

        if saw_merged:
            return self._unavailable(REASON_MERGED_CURVE_KEY)
        if not saw_bound:
            return self._unavailable(REASON_MISSING_IDENTITY)
        if saw_missing and not refs:
            return self._unavailable(REASON_MISSING_IDENTITY)
        if saw_missing:
            return self._unavailable(REASON_AMBIGUOUS_IDENTITY)
        unique = {ref.fingerprint() for ref in refs}
        if len(unique) != 1:
            return self._unavailable(REASON_AMBIGUOUS_IDENTITY)
        target = target_from_ref(refs[0])
        if not target.available:
            return self._unavailable(target.reason or REASON_MISSING_IDENTITY)
        return target

    def companion_source_key(self, curve_key):
        """Return the companion's exact ``(fid, channel)`` source, or None."""
        if curve_key is None:
            return None
        key = str(curve_key)
        resolved = key
        lookup = getattr(self._channel_lines, "composite_key_for", None)
        if callable(lookup):
            resolved = lookup(key) or key
        if resolved in self._merged_curve_keys or resolved in self._ambiguous_curve_keys:
            return None
        ref = self._identities.get(resolved)
        if ref is None:
            return None
        return ref.source_pair()

    def snapshot_chart_appearance(self, handle) -> ChartAppearanceSnapshot:
        target = self.appearance_target_for_handle(handle)
        fields = {
            "title": "",
            "xlabel": "",
            "y_label": "",
            "x_scale": "linear",
            "y_scale": "linear",
            "grid": False,
        }
        if handle is not None:
            try:
                fields.update(snapshot_axis_appearance(handle))
            except (AttributeError, RuntimeError, TypeError):
                pass
        master = getattr(self, "_x_master_handle", None)
        shares_x = master is not None
        if shares_x:
            try:
                master_fields = snapshot_axis_appearance(master)
            except (AttributeError, RuntimeError, TypeError):
                master_fields = {}
            fields["x_scale"] = master_fields.get("x_scale", fields.get("x_scale"))
        return ChartAppearanceSnapshot(
            target=target,
            x_scale="log" if fields.get("x_scale") == "log" else "linear",
            y_scale="log" if fields.get("y_scale") == "log" else "linear",
            title=str(fields.get("title") or ""),
            y_label=str(fields.get("y_label") or ""),
            grid=bool(fields.get("grid")),
            xlabel=str(fields.get("xlabel") or ""),
            owns_xlabel=self._handle_owns_time_xlabel(handle),
            shares_x=shares_x,
        )

    def apply_chart_appearance(self, resolved_specs) -> None:
        """Apply already-resolved specs using existing setters. No user signals."""
        specs = normalize_resolved_chart_appearance(resolved_specs)
        handles = list(getattr(self, "axes_list", None) or [])
        x_scale = specs.x_scale
        if x_scale is not None:
            scale_targets = []
            master = getattr(self, "_x_master_handle", None)
            if master is not None:
                scale_targets.append(master)
            scale_targets.extend(handles)
            seen = set()
            for handle in scale_targets:
                if handle is None or id(handle) in seen:
                    continue
                seen.add(id(handle))
                self._set_scale_if_changed(handle, "x", x_scale)
        for handle, spec in ((item.handle, dict(item.spec or {})) for item in specs.axes):
            if handle is None:
                continue
            if "y_scale" in spec:
                y_scale = "log" if spec.get("y_scale") == "log" else "linear"
                self._set_scale_if_changed(handle, "y", y_scale)
            if x_scale == "log":
                self._autoscale_log_axis_if_invalid(handle, "x")
            if spec.get("y_scale") == "log":
                self._autoscale_log_axis_if_invalid(handle, "y")
            if "title" in spec:
                setter = getattr(handle, "set_title", None)
                if callable(setter):
                    setter(spec.get("title") or "")
            if "y_label" in spec:
                setter = getattr(handle, "set_ylabel", None)
                if callable(setter):
                    setter(spec.get("y_label") or "")
                self._hide_inside_labels_for_handle(handle)
            if "grid" in spec:
                setter = getattr(handle, "grid", None)
                if callable(setter):
                    setter(bool(spec.get("grid")))
        master = getattr(self, "_x_master_handle", None)
        if master is not None and x_scale == "log":
            self._autoscale_log_axis_if_invalid(master, "x")

    def repair_chart_appearance_ranges(self, resolved_specs) -> None:
        """Final-range log repair only. Does not settle or retune the quiet timer."""
        specs = normalize_resolved_chart_appearance(resolved_specs)
        if specs.x_scale == "log":
            primary = getattr(self, "_primary_xaxis_ax", None)
            if primary is not None:
                self._autoscale_log_axis_if_invalid(
                    primary, "x", limits_are_log_space=True,
                )
        for handle, spec in ((item.handle, dict(item.spec or {})) for item in specs.axes):
            if handle is None:
                continue
            if spec.get("y_scale") == "log":
                self._autoscale_log_axis_if_invalid(
                    handle, "y", limits_are_log_space=True,
                )

    def emit_typed_color_if_unique(self, channel_key, color) -> None:
        """Emit the typed identity recolor signal only when the curve is unique.

        MainWindow writes navigator / View colors from this signal only.
        ``channel_color_changed`` stays for compatibility and must not also
        write the same action.
        """
        signal = getattr(self._c, "appearance_color_changed", None)
        emit = getattr(signal, "emit", None)
        if not callable(emit):
            return
        key = str(channel_key)
        lookup = getattr(self._channel_lines, "composite_key_for", None)
        if callable(lookup):
            key = lookup(key) or key
        if key in self._ambiguous_curve_keys or key in self._merged_curve_keys:
            return
        ref = self._identities.get(key)
        if ref is None:
            return
        if ref.kind == KIND_COMPANION:
            source = ref.source_pair()
            encoded = appearance_companion_color_key(*source) if source else ""
            if encoded:
                emit(encoded, str(color))
            return
        if ref.kind not in {KIND_CHANNEL, KIND_BINDING}:
            return
        target = target_from_ref(ref)
        if not target.available:
            return
        emit(target.encoded_key, str(color))

    def _unavailable(self, reason: str) -> ChartAppearanceTarget:
        target = unavailable_target(reason)
        throttled(
            _LOG,
            f"appearance-unavailable:{target.reason}",
            logging.INFO,
            "chart appearance target unavailable: %s",
            target.reason,
        )
        return target

    def _handle_owns_time_xlabel(self, handle) -> bool:
        if handle is None:
            return False
        if getattr(self, "_overlay_mode", False):
            return True
        axes = list(getattr(self, "axes_list", None) or [])
        return bool(axes) and handle is axes[-1]

    @staticmethod
    def _set_scale_if_changed(handle, axis, scale):
        setter = getattr(handle, f"set_{axis}scale", None)
        getter = getattr(handle, f"get_{axis}scale", None)
        current = getter() if callable(getter) else None
        if callable(setter) and current != scale:
            setter(scale)

    @staticmethod
    def _autoscale_log_axis_if_invalid(handle, axis, *, limits_are_log_space=False):
        """Autoscale a log axis whose current limits cannot be displayed.

        ``apply_chart_appearance`` runs before range restore, while the
        ViewBox still holds the linear engineering span. A non-positive end
        there cannot survive ``setLogMode``.

        ``repair_chart_appearance_ranges`` runs after restore. Those limits
        are already ViewBox coordinates: log mode stores ``log10`` of the
        engineering value, so ``0`` is engineering ``1`` and a negative end
        is a positive fraction. Treating ``<= 0`` as illegal there wipes a
        valid ``1…100`` decade back to autoscale.
        """
        getter = getattr(handle, f"get_{axis}lim", None)
        autoscale = getattr(handle, "autoscale", None)
        if not callable(getter) or not callable(autoscale):
            return
        try:
            lo, hi = getter()
            lo_f = float(lo)
            hi_f = float(hi)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        invalid = (
            not math.isfinite(lo_f)
            or not math.isfinite(hi_f)
            or lo_f >= hi_f
        )
        if not limits_are_log_space:
            invalid = invalid or lo_f <= 0.0 or hi_f <= 0.0
        if invalid:
            try:
                autoscale(axis=axis)
            except (TypeError, ValueError):
                return

    def _hide_inside_labels_for_handle(self, handle):
        labels = getattr(self, "_inside_label_items", None) or []
        owners = getattr(self, "_inside_label_handles", None) or []
        for owner, item in zip(owners, labels):
            if owner is not handle:
                continue
            setter = getattr(item, "setVisible", None)
            if not callable(setter):
                continue
            try:
                setter(False)
            except (AttributeError, RuntimeError):
                continue
