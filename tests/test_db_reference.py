"""Pure-domain tests for ``mf4_analyzer.db_reference`` (no PyQt import).

Covers spec ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
sections 5-7 and 14, and plan Step 1.1's literal test names. The resolver's
priority chain (spec S8.1) treats "unit simply absent from the catalog" as
the COMMON case for this project's EPS signals (Nm/rpm/A/deg/V): source
``generic``, reference 1.0, NO warning. ``fallback`` is reserved for a
genuine resolution failure (ambiguous unit-only match across quantities, or
the Pa-without-audio-hint SPL guard) and is the only path carrying a
warning / ``⚠`` marker.
"""
import dataclasses

import pytest

from mf4_analyzer import db_reference


def _entry_by_unit(catalog, quantity, unit):
    q_norm = db_reference.normalize_quantity(quantity)
    u_norm = db_reference.normalize_unit(unit)
    for entry in catalog:
        if db_reference.normalize_quantity(entry.quantity) != q_norm:
            continue
        if u_norm in {db_reference.normalize_unit(a) for a in entry.aliases}:
            return entry
    raise AssertionError(f"no catalog entry for {quantity!r}/{unit!r}")


def test_builtin_db_reference_catalog_matches_spec_values():
    catalog = {e.builtin_id: e for e in db_reference.FACTORY_CATALOG_V1}
    assert set(catalog) == {
        "sound_pressure.pa",
        "acceleration.si",
        "velocity.si",
        "displacement.si",
        "force.si",
        "acceleration.g",
    }

    assert catalog["sound_pressure.pa"].reference == 2e-5
    assert catalog["sound_pressure.pa"].quantity == "sound pressure"
    assert catalog["sound_pressure.pa"].unit == "Pa"

    assert catalog["acceleration.si"].reference == 1e-6
    assert catalog["acceleration.si"].quantity == "acceleration"
    assert set(catalog["acceleration.si"].aliases) >= {"m/s²", "m/s^2", "m/s2"}

    assert catalog["velocity.si"].reference == 1e-9
    assert catalog["velocity.si"].quantity == "velocity"

    assert catalog["displacement.si"].reference == 1e-12
    assert catalog["displacement.si"].quantity == "displacement"

    assert catalog["force.si"].reference == 1e-6
    assert catalog["force.si"].quantity == "force"

    # acceleration.g stores the double-precision expression result, not a
    # rounded display value.
    assert catalog["acceleration.g"].reference == 1e-6 / 9.80665
    assert catalog["acceleration.g"].quantity == "acceleration"
    assert catalog["acceleration.g"].unit == "g"

    for entry in db_reference.FACTORY_CATALOG_V1:
        assert entry.id == entry.builtin_id
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.reference = 0.5


def test_unit_normalization_is_exact_not_substring_based():
    assert (
        db_reference.normalize_unit("m/s²")
        == db_reference.normalize_unit("m/s^2")
        == db_reference.normalize_unit("m/s2")
    )
    assert db_reference.normalize_unit("kg") != db_reference.normalize_unit("g")
    assert db_reference.normalize_unit("kPa") != db_reference.normalize_unit("Pa")
    assert db_reference.normalize_unit(None) == ""
    assert db_reference.normalize_unit("  Pa  ") == db_reference.normalize_unit("pa")

    assert db_reference.normalize_quantity("  Acceleration ") == "acceleration"
    assert db_reference.normalize_quantity(None) == ""

    g_entry = _entry_by_unit(db_reference.FACTORY_CATALOG_V1, "acceleration", "g")
    g_aliases_norm = {db_reference.normalize_unit(a) for a in g_entry.aliases}
    # 'kg' must never exact-match the 'g' alias set (no substring bleed).
    assert db_reference.normalize_unit("kg") not in g_aliases_norm


def test_resolver_priority_manual_metadata_user_system_fallback():
    facts_full = db_reference.ChannelReferenceFacts(
        quantity="acceleration", unit="m/s²", metadata_reference=3e-6,
    )
    user_override = dataclasses.replace(
        _entry_by_unit(db_reference.FACTORY_CATALOG_V1, "acceleration", "m/s²"),
        reference=5e-6,
    )

    # 1) manual always wins, even with metadata/user/system all resolvable.
    manual = db_reference.resolve_db_reference(
        mode="manual",
        manual_value=9e-6,
        facts=facts_full,
        user_catalog=(user_override,),
        prefer_channel_metadata=True,
    )
    assert manual.source == "manual"
    assert manual.value == 9e-6

    # 2) legal channel metadata wins over user/system when preference is on.
    meta = db_reference.resolve_db_reference(
        mode="auto",
        facts=facts_full,
        user_catalog=(user_override,),
        prefer_channel_metadata=True,
    )
    assert meta.source == "metadata"
    assert meta.value == 3e-6

    # 3) user override wins over the system builtin once metadata is off.
    user_only = db_reference.resolve_db_reference(
        mode="auto",
        facts=facts_full,
        user_catalog=(user_override,),
        prefer_channel_metadata=False,
    )
    assert user_only.source == "user"
    assert user_only.value == 5e-6

    # 4) the immutable system builtin applies once there is no user override.
    system_only = db_reference.resolve_db_reference(
        mode="auto",
        facts=facts_full,
        user_catalog=(),
        prefer_channel_metadata=False,
    )
    assert system_only.source == "system"
    assert system_only.value == 1e-6

    # 6) a genuinely ambiguous resolution (unit maps to >1 quantity once the
    # channel quantity is unknown) is fallback+warning, never a silent guess.
    ambiguous_facts = db_reference.ChannelReferenceFacts(quantity="", unit="g")
    mass_like = db_reference.DbReferenceEntry(
        id="mass.grams", quantity="mass", label="Mass (grams)", unit="g",
        aliases=("g",), reference=0.001,
    )
    fallback = db_reference.resolve_db_reference(
        mode="auto",
        facts=ambiguous_facts,
        user_catalog=(mass_like,),
        prefer_channel_metadata=False,
    )
    assert fallback.source == "fallback"
    assert fallback.value == 1.0
    assert fallback.warning


def test_invalid_metadata_falls_through_without_crashing():
    for bad in (float("nan"), float("inf"), float("-inf"), -1.0, 0.0, None, "", "nope"):
        facts_bad = db_reference.ChannelReferenceFacts(
            quantity="acceleration", unit="m/s²", metadata_reference=bad,
        )
        result = db_reference.resolve_db_reference(
            mode="auto", facts=facts_bad, prefer_channel_metadata=True,
        )
        assert result.source == "system"
        assert result.value == 1e-6


def test_pa_without_sound_quantity_or_audio_hint_does_not_assume_spl():
    no_hint = db_reference.ChannelReferenceFacts(quantity="", unit="Pa", is_audio_source=False)
    result_no_hint = db_reference.resolve_db_reference(mode="auto", facts=no_hint)
    assert result_no_hint.source == "fallback"
    assert result_no_hint.value == 1.0
    assert result_no_hint.warning

    with_audio_hint = db_reference.ChannelReferenceFacts(quantity="", unit="Pa", is_audio_source=True)
    result_audio = db_reference.resolve_db_reference(mode="auto", facts=with_audio_hint)
    assert result_audio.source == "system"
    assert result_audio.value == 2e-5

    with_quantity = db_reference.ChannelReferenceFacts(
        quantity="sound pressure", unit="Pa", is_audio_source=False,
    )
    result_quantity = db_reference.resolve_db_reference(mode="auto", facts=with_quantity)
    assert result_quantity.source == "system"
    assert result_quantity.value == 2e-5


def test_unit_not_in_catalog_resolves_generic_without_warning():
    # Common EPS-signal units: not in the acoustics/vibration catalog, and
    # this is the NORMAL case, not an error.
    for unit in ("Nm", "rpm", "A", "deg", "V"):
        facts = db_reference.ChannelReferenceFacts(quantity="", unit=unit)
        result = db_reference.resolve_db_reference(mode="auto", facts=facts)
        assert result.source == "generic", unit
        assert result.value == 1.0
        assert result.warning == ""


def test_generic_label_uses_actual_unit_and_no_warning_marker():
    resolution = db_reference.DbReferenceResolution(
        value=1.0, unit="Nm", quantity="", source="generic",
    )
    label = db_reference.format_amplitude_label(resolution)
    assert label == "Amplitude (dB re 1 Nm)"
    assert "⚠" not in label


def test_generic_empty_unit_label_is_db_re_1():
    resolution = db_reference.DbReferenceResolution(
        value=1.0, unit="", quantity="", source="generic",
    )
    label = db_reference.format_amplitude_label(resolution)
    assert label == "Amplitude (dB re 1)"
    assert "⚠" not in label


def test_ambiguous_unit_only_match_is_fallback_with_warning():
    facts = db_reference.ChannelReferenceFacts(quantity="", unit="g")
    mass_like = db_reference.DbReferenceEntry(
        id="mass.grams", quantity="mass", label="Mass (grams)", unit="g",
        aliases=("g",), reference=0.001,
    )
    result = db_reference.resolve_db_reference(
        mode="auto", facts=facts, user_catalog=(mass_like,),
    )
    assert result.source == "fallback"
    assert result.value == 1.0
    assert result.warning

    label = db_reference.format_amplitude_label(result)
    assert label.endswith("⚠")
    assert "re 1 g" in label


def test_duplicate_quantity_alias_is_rejected():
    dup_entries = (
        db_reference.DbReferenceEntry(
            id="a", quantity="acceleration", label="A", unit="m/s²",
            aliases=("m/s²",), reference=1e-6,
        ),
        db_reference.DbReferenceEntry(
            id="b", quantity="acceleration", label="B", unit="m/s^2",
            aliases=("m/s^2",), reference=2e-6,
        ),
    )
    with pytest.raises(db_reference.DuplicateAliasError):
        db_reference.validate_catalog(dup_entries)

    # Distinct quantities sharing a unit alias are NOT a duplicate-alias
    # authoring error (that's the ambiguous-resolution case instead).
    ok_entries = (
        db_reference.DbReferenceEntry(
            id="a", quantity="acceleration", label="A", unit="g",
            aliases=("g",), reference=1e-6,
        ),
        db_reference.DbReferenceEntry(
            id="b", quantity="mass", label="B", unit="g",
            aliases=("g",), reference=0.001,
        ),
    )
    db_reference.validate_catalog(ok_entries)  # must not raise


def test_validate_catalog_allows_one_entrys_own_alias_spelling_variants():
    """A single entry's OWN alias spelling variants -- e.g.
    ``acceleration.si``'s ``m/s²`` / ``m/s^2`` / ``m/s2``, which all
    normalize to the identical token ``m/s2`` -- are legitimate multi-spelling
    for ONE unit, not a duplicate-alias authoring error. ``validate_catalog``
    must only flag two DIFFERENT entries claiming the same (quantity, alias)
    pair; it must never self-collide on repeated normalized aliases within
    one entry. This is what the module-under-test's own docstring promises
    ("Raise ... if two entries share ..."), and the db_reference.ui settings
    store (Task 2) legitimately calls ``validate_catalog`` on the merged
    system+user catalog, which starts from the untouched
    ``FACTORY_CATALOG_V1`` -- that call must never raise on its own."""
    db_reference.validate_catalog(db_reference.FACTORY_CATALOG_V1)  # must not raise


def test_g_reference_is_si_acceleration_equivalent():
    g_entry = next(
        e for e in db_reference.FACTORY_CATALOG_V1 if e.builtin_id == "acceleration.g"
    )
    assert g_entry.reference == 1e-6 / 9.80665
    assert g_entry.quantity == "acceleration"

    facts = db_reference.ChannelReferenceFacts(quantity="acceleration", unit="g")
    result = db_reference.resolve_db_reference(mode="auto", facts=facts)
    assert result.source == "system"
    assert result.value == pytest.approx(1e-6 / 9.80665)


def test_axis_formatter_emits_db_dba_20upa_and_linear_labels():
    accel = db_reference.DbReferenceResolution(
        value=1e-6, unit="m/s²", quantity="acceleration", source="system",
    )
    assert db_reference.format_amplitude_label(accel) == "Amplitude (dB re 1×10⁻⁶ m/s²)"
    assert (
        db_reference.format_amplitude_label(accel, weighting="A")
        == "Amplitude (dBA re 1×10⁻⁶ m/s²)"
    )

    spl = db_reference.DbReferenceResolution(
        value=2e-5, unit="Pa", quantity="sound pressure", source="system",
    )
    assert (
        db_reference.format_amplitude_label(spl, weighting="A")
        == "Sound pressure (dBA re 20 µPa)"
    )

    linear_a = db_reference.format_amplitude_label(
        accel, weighting="A", output_scale="linear",
    )
    assert linear_a == "A-weighted amplitude (m/s²)"
    assert "dBA" not in linear_a
    assert "dB" not in linear_a

    linear_plain = db_reference.format_amplitude_label(accel, output_scale="linear")
    assert linear_plain == "Amplitude (m/s²)"
    assert "dB" not in linear_plain


def test_mixed_formatter_emits_per_curve_reference():
    assert (
        db_reference.format_amplitude_label(None, mixed=True)
        == "Amplitude (dB · per-curve reference)"
    )
    assert (
        db_reference.format_amplitude_label(None, mixed=True, weighting="A")
        == "Amplitude (dBA · per-curve reference)"
    )


def test_format_reference_note_emits_bare_operand_for_mixed_axis_disclosure():
    """dB-reference-defaults Task 6 (spec §15 C1): a mixed FFT axis needs a
    COMPACT per-curve disclosure -- the bare 'dB[A] re ...' operand, with NO
    leading quantity word and NO fallback '⚠' glyph (the axis/source line
    already carries any warning) -- so a caller can append it to a curve's
    own base label without repeating 'Amplitude'/'Sound pressure' per curve."""
    accel = db_reference.DbReferenceResolution(
        value=1e-6, unit="m/s²", quantity="acceleration", source="system",
    )
    assert db_reference.format_reference_note(accel) == "dB re 1×10⁻⁶ m/s²"
    assert (
        db_reference.format_reference_note(accel, weighting="A")
        == "dBA re 1×10⁻⁶ m/s²"
    )

    spl = db_reference.DbReferenceResolution(
        value=2e-5, unit="Pa", quantity="sound pressure", source="system",
    )
    assert db_reference.format_reference_note(spl) == "dB re 20 µPa"

    fallback = db_reference.DbReferenceResolution(
        value=1.0, unit="widget", quantity="", source="fallback",
        warning="unresolved",
    )
    note = db_reference.format_reference_note(fallback)
    assert note == "dB re 1 widget"
    assert "⚠" not in note
    assert "Amplitude" not in note


def test_reference_validator_requires_finite_positive_value():
    assert db_reference.validate_reference(1e-6) is True
    assert db_reference.validate_reference("2e-5") is True
    assert db_reference.validate_reference(0.0) is False
    assert db_reference.validate_reference(-1.0) is False
    assert db_reference.validate_reference(float("nan")) is False
    assert db_reference.validate_reference(float("inf")) is False
    assert db_reference.validate_reference(float("-inf")) is False
    assert db_reference.validate_reference(None) is False
    assert db_reference.validate_reference("") is False
    assert db_reference.validate_reference("not-a-number") is False


# ---- Extra coverage for the shared legacy-param migration helper (spec
# S2/S3/S4: "value without mode" -> Manual), reused later by View/preset/
# Batch paths (Tasks 4/8/9). Not in plan Step 1.1's literal test-name list,
# but is genuine numeric/state logic and must not skip TDD. ----

def test_migrate_legacy_reference_params_promotes_value_without_mode_to_manual():
    legacy = {"weighting": "A", "db_reference": 5e-6}
    migrated = db_reference.migrate_legacy_reference_params(legacy)
    assert migrated["db_reference_mode"] == "manual"
    assert migrated["db_reference"] == 5e-6
    assert migrated is not legacy  # never mutates the caller's dict
    assert legacy == {"weighting": "A", "db_reference": 5e-6}

    already_new = {"db_reference": 5e-6, "db_reference_mode": "auto"}
    assert db_reference.migrate_legacy_reference_params(already_new) == already_new

    no_reference = {"weighting": None}
    assert db_reference.migrate_legacy_reference_params(no_reference) == no_reference


def test_db_reference_module_has_zero_pyqt_import():
    import ast
    import inspect

    src = inspect.getsource(db_reference)
    tree = ast.parse(src)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert "PyQt5" not in imported_roots
    assert not hasattr(db_reference, "QSettings")


def test_canonicalize_source_unit_reverses_toolchain_encoding():
    """某些工具链把单位标识符安全化：加 ``U_`` 前缀、用大写 ``Y`` 代替 ``/``
    （如 ``U_Nm`` / ``U_degYsec`` / 振动量 ``mYs2``）。还原层用于匹配 + 显示，
    只反转确定性编码，不做单位同义词归一，也不改 ``normalize_unit`` 的精确
    匹配内核。"""
    f = db_reference.canonicalize_source_unit
    # U_ 前缀剥离（真实单位不以 U_ 开头）
    assert f("U_Nm") == "Nm"
    assert f("U_degYsec") == "deg/sec"
    # 被同样改写的振动量还原后能重新命中 ISO 目录
    assert f("mYs2") == "m/s2"
    assert f("mYs") == "m/s"
    # 正常单位原样返回（无前缀、无字母间大写 Y）
    assert f("Nm") == "Nm"
    assert f("m/s²") == "m/s²"
    assert f("m/s^2") == "m/s^2"
    assert f("rpm") == "rpm"
    assert f("") == ""
    assert f(None) == ""
    # 大写 Y 仅在两侧都是字母时才当 /（避免误伤 Yotta 前缀等孤立 Y）
    assert f("Y") == "Y"
    assert f("YHz") == "YHz"
    # 小写 y 不受影响（Gy = gray）
    assert f("Gy") == "Gy"


def test_canonicalized_vibration_unit_resolves_to_catalog_reference():
    """还原后的 ``mYs2`` 应能像 ``m/s2`` 一样命中工厂目录 acceleration（1e-6），
    而非落 generic——证明还原层修的是真正的参考误配、不只是标签。"""
    canon = db_reference.canonicalize_source_unit("mYs2")
    facts = db_reference.ChannelReferenceFacts(quantity="", unit=canon)
    result = db_reference.resolve_db_reference(mode="auto", facts=facts)
    assert result.source == "system"
    assert result.value == pytest.approx(1e-6)
