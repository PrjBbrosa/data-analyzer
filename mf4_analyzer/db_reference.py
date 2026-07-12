"""Pure dB-reference domain: catalog, unit/quantity normalization, resolver
and label formatters shared by FFT / FFT-vs-Time / Order and Batch.

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
(sections 5-7, 8, 14). This module has **ZERO PyQt import** and touches no
QSettings — it is consumed by both the interactive UI (through a thin
QSettings-backed store, see ``mf4_analyzer/ui/db_reference_settings.py``) and
by Batch worker code, which must never import PyQt.

``db_reference`` (the resolved value), ``db_reference_mode`` and catalog
revision are all display-only: they are NEVER part of a compute cache key
(see ``docs/lessons-learned/signal-processing/2026-06-21-cache-key-dataclass-field-binding-and-phantom-fields.md``).
Only ``weighting`` is compute-relevant.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


# ---------------------------------------------------------------------------
# Pure domain types (spec S5.2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DbReferenceEntry:
    """One catalog row: a physical quantity/unit mapped to a 0 dB reference.

    ``id`` is the entry's stable identifier (equal to ``builtin_id`` for
    factory rows; a ``user.*``-style string for custom user rows).
    ``builtin_id`` is ``None`` for user-authored custom entries and is set
    for factory rows and their user overrides (same stable id, edited
    ``reference``/``label``/``aliases``).
    """

    id: str
    quantity: str
    label: str
    unit: str
    aliases: tuple[str, ...]
    reference: float
    builtin_id: str | None = None


@dataclass(frozen=True)
class ChannelReferenceFacts:
    """Facts read from a channel/source, never from sample arrays.

    ``metadata_reference`` is untrusted raw metadata (may be missing,
    non-numeric, NaN, zero, or negative) and MUST pass through
    :func:`validate_reference` before use.
    """

    quantity: str
    unit: str
    metadata_reference: object = None
    is_audio_source: bool = False


@dataclass(frozen=True)
class DbReferenceResolution:
    """The resolver's result for one source at one point in time.

    ``source`` is one of ``manual | metadata | user | system | generic |
    fallback`` (spec S8.2). ``warning`` is non-empty ONLY for ``fallback``
    (a genuine resolution failure) — ``generic`` (unit simply absent from
    the catalog, the common EPS-unit case) never carries a warning.
    """

    value: float
    unit: str
    quantity: str
    source: str
    warning: str = ""


class DuplicateAliasError(ValueError):
    """Raised when a catalog has two entries sharing (quantity, alias).

    Spec R2: "duplicate (quantity, alias) 是保存错误，不允许 last-one-wins."
    """


# ---------------------------------------------------------------------------
# Immutable factory catalog (spec S6.1)
# ---------------------------------------------------------------------------

FACTORY_CATALOG_V1: tuple[DbReferenceEntry, ...] = (
    DbReferenceEntry(
        id="sound_pressure.pa",
        quantity="sound pressure",
        label="Sound pressure (ISO/HEAD compatible)",
        unit="Pa",
        aliases=("Pa",),
        reference=2e-5,
        builtin_id="sound_pressure.pa",
    ),
    DbReferenceEntry(
        id="acceleration.si",
        quantity="acceleration",
        label="Acceleration (ISO/HEAD compatible)",
        unit="m/s²",
        aliases=("m/s²", "m/s^2", "m/s2"),
        reference=1e-6,
        builtin_id="acceleration.si",
    ),
    DbReferenceEntry(
        id="velocity.si",
        quantity="velocity",
        label="Velocity (ISO/HEAD compatible)",
        unit="m/s",
        aliases=("m/s",),
        reference=1e-9,
        builtin_id="velocity.si",
    ),
    DbReferenceEntry(
        id="displacement.si",
        quantity="displacement",
        label="Displacement (ISO/HEAD compatible)",
        unit="m",
        aliases=("m",),
        reference=1e-12,
        builtin_id="displacement.si",
    ),
    DbReferenceEntry(
        id="force.si",
        quantity="force",
        label="Force (ISO/HEAD compatible)",
        unit="N",
        aliases=("N",),
        reference=1e-6,
        builtin_id="force.si",
    ),
    DbReferenceEntry(
        id="acceleration.g",
        quantity="acceleration",
        label="Acceleration g (SI-equivalent compatibility value)",
        unit="g",
        aliases=("g",),
        # Double-precision expression result — never the rounded display
        # value (spec S6.1 footnote).
        reference=1e-6 / 9.80665,
        builtin_id="acceleration.g",
    ),
)


# ---------------------------------------------------------------------------
# Unit / quantity normalization (spec S7 R1/R2) — EXACT match, no substring.
# ---------------------------------------------------------------------------

def normalize_unit(unit):
    """Normalize a unit string for exact alias matching.

    Trims + casefolds, folds the Unicode superscripts ``²``/``³`` to plain
    digits, drops the ``^`` exponent marker and any internal whitespace, so
    ``m/s²`` / ``m/s^2`` / ``m/s2`` all collapse to one canonical token.
    Intentionally exact-match only: ``g`` must never collapse onto ``kg``/
    ``deg``, nor ``Pa`` onto ``kPa`` — normalization never does substring
    matching, only canonical-form equality.
    """
    if unit is None:
        return ''
    s = str(unit).strip().lower()
    s = (
        s.replace('²', '2')
         .replace('³', '3')
         .replace('^', '')
    )
    s = ''.join(s.split())
    return s


def normalize_quantity(quantity):
    """Normalize a quantity string: trim + casefold. ``None`` -> ``''``."""
    if quantity is None:
        return ''
    return str(quantity).strip().lower()


# ---------------------------------------------------------------------------
# Reference validation (spec S7 R3)
# ---------------------------------------------------------------------------

def validate_reference(value):
    """``True`` iff ``value`` is float-convertible, finite, AND > 0.

    NaN, ±Inf, empty string, zero, negative and unparsable values are all
    invalid. This is the ONE validator every resolution path (manual edit,
    channel metadata, catalog row) must pass through before use — no call
    site may silently coerce an invalid denominator (e.g. via
    ``max(reference, 1e-12)``).
    """
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(f):
        return False
    return f > 0.0


# ---------------------------------------------------------------------------
# Catalog validation (spec R2 duplicate-alias guard)
# ---------------------------------------------------------------------------

def validate_catalog(entries):
    """Raise :class:`DuplicateAliasError` if TWO DIFFERENT entries share a
    ``(normalized quantity, normalized alias)`` pair.

    Distinct quantities sharing the same unit alias (e.g. acceleration 'g'
    vs. mass 'g') are NOT a duplicate — that is the ambiguous-*resolution*
    case handled by :func:`resolve_db_reference`, not an authoring error.

    A single entry's OWN alias list may (and typically does) contain several
    spellings of the same unit that normalize to one token — e.g.
    ``acceleration.si``'s ``m/s²`` / ``m/s^2`` / ``m/s2`` — that is legitimate
    multi-spelling for ONE unit, not a duplicate; alias norms are de-duplicated
    PER ENTRY before the cross-entry check so an entry never collides with
    its own repeated spelling variants.
    """
    seen = set()
    for entry in entries:
        q_norm = normalize_quantity(entry.quantity)
        entry_alias_norms = {normalize_unit(alias) for alias in entry.aliases}
        for alias_norm in entry_alias_norms:
            key = (q_norm, alias_norm)
            if key in seen:
                raise DuplicateAliasError(
                    f"duplicate (quantity, alias) pair: {key!r}"
                )
            seen.add(key)


# ---------------------------------------------------------------------------
# Resolver (spec S8.1 priority chain)
# ---------------------------------------------------------------------------

_FALLBACK_WARNING = "单位或物理量解析失败，已回退为 dB re 1（生效前请核对通道单位）。"


def _alias_norms(entry):
    return {normalize_unit(a) for a in entry.aliases}


def _match_catalog_entry(facts, tagged_catalog):
    """Look up ``facts`` against ``tagged_catalog`` (an ordered iterable of
    ``(DbReferenceEntry, origin)`` pairs; earlier entries win ties, so
    callers order user overrides before system builtins).

    Returns ``(entry_or_None, origin_or_None, ambiguous_bool)``.
    """
    quantity_norm = normalize_quantity(facts.quantity)
    unit_norm = normalize_unit(facts.unit)
    if not unit_norm:
        return None, None, False

    if quantity_norm:
        for entry, origin in tagged_catalog:
            if normalize_quantity(entry.quantity) != quantity_norm:
                continue
            if unit_norm in _alias_norms(entry):
                return entry, origin, False
        return None, None, False

    # R2: quantity missing -> unit-only match, allowed only when the
    # normalized unit maps to exactly one DISTINCT quantity in the
    # effective catalog.
    unit_hits = [
        (entry, origin) for entry, origin in tagged_catalog
        if unit_norm in _alias_norms(entry)
    ]
    if not unit_hits:
        return None, None, False

    distinct_quantities = {normalize_quantity(e.quantity) for e, _ in unit_hits}
    if len(distinct_quantities) > 1:
        return None, None, True

    # Pa-specific SPL guard (R2): never silently assume "sound pressure"
    # for a bare Pa unit without an explicit audio-source hint.
    if (
        unit_norm == "pa"
        and distinct_quantities == {"sound pressure"}
        and not facts.is_audio_source
    ):
        return None, None, True

    entry, origin = unit_hits[0]
    return entry, origin, False


def resolve_db_reference(
    *,
    mode="auto",
    manual_value=None,
    facts=None,
    user_catalog=(),
    system_catalog=FACTORY_CATALOG_V1,
    prefer_channel_metadata=True,
):
    """Resolve the effective dB reference for one source (spec S8.1).

    Priority: ``manual`` View value > legal channel ``metadata`` (only when
    ``prefer_channel_metadata``) > ``user`` catalog override/custom entry >
    unhidden immutable ``system`` builtin > ``generic`` (unit simply absent
    from the catalog — the COMMON case for EPS units like Nm/rpm/A/deg/V:
    reference 1.0, NO warning) > ``fallback`` (a genuine resolution failure
    — ambiguous unit-only match across quantities, or the Pa-without-hint
    SPL guard: reference 1.0, WITH a visible warning).

    ``user_catalog`` / ``system_catalog`` are already-effective entry lists
    (hidden ids filtered, overrides merged) — this function does not know
    about QSettings/persistence, only about resolving one snapshot.
    """
    if facts is None:
        facts = ChannelReferenceFacts(quantity="", unit="")

    if mode == "manual":
        if manual_value is not None and validate_reference(manual_value):
            return DbReferenceResolution(
                value=float(manual_value),
                unit=facts.unit,
                quantity=facts.quantity,
                source="manual",
            )
        # Invalid/missing manual value should never crash the resolver —
        # the editor (Task 3) already rejects invalid commits before this
        # point; defensively fall through to the rest of the chain instead
        # of raising.

    if prefer_channel_metadata:
        meta = facts.metadata_reference
        if meta is not None and validate_reference(meta):
            return DbReferenceResolution(
                value=float(meta),
                unit=facts.unit,
                quantity=facts.quantity,
                source="metadata",
            )

    tagged = [(e, "user") for e in user_catalog] + [
        (e, "system") for e in system_catalog
    ]
    match, origin, ambiguous = _match_catalog_entry(facts, tagged)
    if ambiguous:
        return DbReferenceResolution(
            value=1.0,
            unit=facts.unit,
            quantity=facts.quantity,
            source="fallback",
            warning=_FALLBACK_WARNING,
        )
    if match is not None:
        return DbReferenceResolution(
            value=match.reference,
            unit=match.unit,
            quantity=match.quantity,
            source=origin,
        )

    # Unit not in the (effective) catalog at all -> generic, no warning.
    return DbReferenceResolution(
        value=1.0,
        unit=facts.unit,
        quantity=facts.quantity,
        source="generic",
    )


# ---------------------------------------------------------------------------
# Label formatters (spec S14)
# ---------------------------------------------------------------------------

_QUANTITY_DISPLAY_WORD = {
    "sound pressure": "Sound pressure",
}
_DEFAULT_DISPLAY_WORD = "Amplitude"

_SUPERSCRIPT_TRANS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _display_word(quantity):
    return _QUANTITY_DISPLAY_WORD.get(normalize_quantity(quantity), _DEFAULT_DISPLAY_WORD)


def _scientific_parts(value):
    if value == 0:
        return 0.0, 0
    text = f"{value:.10e}"
    mantissa_str, exp_str = text.split("e")
    return float(mantissa_str), int(exp_str)


def format_reference_pretty(value, unit=""):
    """Human-readable ``c×10ⁿ unit`` (or the well-known ``20 µPa``).

    ``editor`` text (:func:`format_reference_editor`) and this ``pretty``
    text are two formatters over the SAME float — the pretty label is never
    written back into the editor (spec I1).
    """
    value = float(value)
    unit = unit or ""
    if normalize_unit(unit) == "pa" and value == 2e-5:
        return "20 µPa"
    mantissa, exponent = _scientific_parts(value)
    mantissa_text = f"{mantissa:.6g}"
    exponent_text = str(exponent).translate(_SUPERSCRIPT_TRANS)
    body = f"{mantissa_text}×10{exponent_text}"
    return f"{body} {unit}" if unit else body


def format_reference_editor(value):
    """Compact editor text for a reference float: ``1e-6``, not ``1e-06``.

    Round-trips through ``float()``; scientific notation is trimmed to the
    shortest unambiguous mantissa/exponent form.
    """
    value = float(value)
    if value == 0:
        return "0"
    text = f"{value:.10g}"
    if "e" in text:
        mantissa, exp = text.split("e")
        exp_i = int(exp)
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        text = f"{mantissa}e{exp_i}"
    return text


def _reference_text(resolution):
    """The ``re ...`` operand text for a non-mixed amplitude label."""
    if resolution.source in ("generic", "fallback"):
        unit = resolution.unit or ""
        return f"1 {unit}" if unit else "1"
    return format_reference_pretty(resolution.value, resolution.unit)


def _db_reference_operand(resolution, weighting=None):
    """The bare ``dB[A] re <reference>`` phrase for ONE resolution.

    Shared by :func:`format_amplitude_label`'s non-mixed branch and
    :func:`format_reference_note` (spec S14 / S15 C1's mixed-axis per-curve
    disclosure) so both stay byte-identical on the ``dB[A]``-token and
    reference-pretty-print rules — no renderer/canvas hand-rolls its own
    ``f"dB re {...}"`` string (spec S14: "禁止在 renderer、canvas、batch 内
    继续拼接各自的 ``Amplitude (dB)``").
    """
    db_token = "dBA" if weighting == "A" else "dB"
    return f"{db_token} re {_reference_text(resolution)}"


def format_amplitude_label(resolution, *, weighting=None, output_scale="db", mixed=False):
    """The canonical axis/colorbar amplitude label (spec S14.1).

    ``resolution`` may be ``None`` only when ``mixed=True`` (a mixed-source
    axis has no single reference to describe). ``⚠`` is appended ONLY when
    ``resolution.source == 'fallback'`` — never for ``generic`` (spec S14.2:
    "``generic`` 不得使用 warning 配色或 ``⚠`` 标记").
    """
    output_scale = (output_scale or "db").strip().lower()
    is_a_weighted = weighting == "A"

    if output_scale == "linear":
        unit = resolution.unit if resolution is not None else ""
        if is_a_weighted:
            return f"A-weighted amplitude ({unit})"
        return f"Amplitude ({unit})" if unit else "Amplitude"

    if mixed:
        db_token = "dBA" if is_a_weighted else "dB"
        return f"Amplitude ({db_token} · per-curve reference)"

    word = _display_word(resolution.quantity)
    label = f"{word} ({_db_reference_operand(resolution, weighting)})"
    if resolution.source == "fallback":
        label = f"{label} ⚠"
    return label


def format_reference_note(resolution, *, weighting=None):
    """Compact per-curve ``dB[A] re <reference>`` disclosure phrase.

    Used by a MIXED-reference FFT axis (spec S15 C1): "mixed：axis 使用
    per-curve reference；每条 legend/curve label ... 显示自己的 dB[A] re
    ..."。No leading quantity word and no fallback ``⚠`` glyph (the axis/
    source line already surfaces any resolution warning) — callers append
    this to a curve's own base label, e.g. ``f"{base_label} · {note}"``.
    ``resolution`` must not be ``None``.
    """
    return _db_reference_operand(resolution, weighting=weighting)


# ---------------------------------------------------------------------------
# Shared legacy-param migration helper (spec S2/S3/S4) — reused later by
# View/preset/Batch paths (Tasks 4/8/9). A value WITHOUT a mode is always
# the old, pre-Auto/Manual authoritative display reference -> Manual.
# ---------------------------------------------------------------------------

def migrate_legacy_reference_params(params):
    """Return a NEW dict: inject ``db_reference_mode='manual'`` iff
    ``params`` has ``db_reference`` but no ``db_reference_mode``.

    Never mutates ``params``. Params missing ``db_reference`` entirely are
    returned unchanged (copy) — they must not gain an injected mode/value.
    """
    out = dict(params)
    if "db_reference" in out and "db_reference_mode" not in out:
        out["db_reference_mode"] = "manual"
    return out
