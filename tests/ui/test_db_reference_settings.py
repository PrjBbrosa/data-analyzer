"""Isolated-``QSettings`` tests for the versioned dB-reference user catalog
store.

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
section 12. Plan Step 2.1 literal test names:
``docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md``.

CRITICAL: every test constructs its OWN throwaway
``QSettings(path, QSettings.IniFormat)`` under ``tmp_path`` -- NEVER
``QSettings("MF4Analyzer", "DataAnalyzer")``, which would read/write the
real user's settings file.
"""
import dataclasses
import json

import pytest
from PyQt5.QtCore import QSettings

from mf4_analyzer import db_reference
from mf4_analyzer.ui.db_reference_settings import (
    KEY_CATALOG_V1,
    KEY_PREFER_CHANNEL_METADATA,
    DbReferenceCatalogSnapshot,
    DbReferenceSaveResult,
    DbReferenceSettingsStore,
)


def _settings(tmp_path, name="db-reference.ini"):
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


def _by_id(entries):
    """Map every entry by its stable identity (``builtin_id`` for factory
    rows/overrides, ``id`` for custom entries)."""
    return {e.builtin_id or e.id: e for e in entries}


def test_store_first_load_uses_factory_catalog_and_metadata_preference_on(tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    snap = store.snapshot()

    assert snap.system_catalog == db_reference.FACTORY_CATALOG_V1
    assert snap.user_catalog == ()
    assert snap.prefer_channel_metadata is True
    assert snap.revision == 0
    assert store.revision == 0
    assert store.warning == ""


def test_store_round_trip_override_custom_hidden_and_preference(tmp_path):
    ini_path = tmp_path / "round-trip.ini"
    store = DbReferenceSettingsStore(settings=QSettings(str(ini_path), QSettings.IniFormat))

    result = store.save(
        overrides=[{
            "builtin_id": "acceleration.si",
            "label": "振动加速度",
            "unit": "m/s²",
            "aliases": ["m/s²", "m/s^2", "m/s2"],
            "reference": 2e-6,
        }],
        custom=[{
            "id": "user.torque_custom",
            "quantity": "custom",
            "label": "自定义扭矩基准",
            "unit": "Nm",
            "aliases": ["Nm", "N·m"],
            "reference": 1e-3,
        }],
        hidden_builtin_ids=["force.si"],
        prefer_channel_metadata=False,
    )

    assert result == DbReferenceSaveResult(ok=True)
    assert store.revision == 1

    snap = store.snapshot()
    assert snap.prefer_channel_metadata is False

    system_ids = _by_id(snap.system_catalog)
    user_ids = _by_id(snap.user_catalog)

    # force.si is hidden -> gone from BOTH catalogs entirely.
    assert "force.si" not in system_ids
    assert "force.si" not in user_ids

    # acceleration.si is overridden -> moved OUT of system, INTO user.
    assert "acceleration.si" not in system_ids
    overridden = user_ids["acceleration.si"]
    assert overridden.reference == pytest.approx(2e-6)
    assert overridden.label == "振动加速度"
    assert overridden.builtin_id == "acceleration.si"

    custom_entry = user_ids["user.torque_custom"]
    assert custom_entry.builtin_id is None
    assert custom_entry.reference == pytest.approx(1e-3)

    # Untouched builtins remain in system_catalog.
    assert set(system_ids) == {
        "sound_pressure.pa", "velocity.si", "displacement.si", "acceleration.g",
    }

    # Round trip: a brand-new store instance reading the SAME settings path.
    store2 = DbReferenceSettingsStore(settings=QSettings(str(ini_path), QSettings.IniFormat))
    snap2 = store2.snapshot()
    assert snap2.prefer_channel_metadata is False
    assert set(_by_id(snap2.system_catalog)) == set(system_ids)
    assert set(_by_id(snap2.user_catalog)) == set(user_ids)
    assert _by_id(snap2.user_catalog)["acceleration.si"].reference == pytest.approx(2e-6)
    # Revision is in-process ONLY -- a fresh store instance never inherits it.
    assert store2.revision == 0


def test_modified_builtin_is_reported_as_user_override(tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    result = store.save(
        overrides=[{
            "builtin_id": "acceleration.si",
            "label": "振动加速度",
            "unit": "m/s²",
            "aliases": ["m/s²", "m/s^2", "m/s2"],
            "reference": 2e-6,
        }],
        custom=[],
        hidden_builtin_ids=[],
        prefer_channel_metadata=True,
    )
    assert result.ok is True

    snap = store.snapshot()
    resolution = db_reference.resolve_db_reference(
        mode="auto",
        facts=db_reference.ChannelReferenceFacts(quantity="acceleration", unit="m/s²"),
        user_catalog=snap.user_catalog,
        system_catalog=snap.system_catalog,
        prefer_channel_metadata=snap.prefer_channel_metadata,
    )
    assert resolution.source == "user"
    assert resolution.value == pytest.approx(2e-6)


def test_restore_removes_user_delta_but_does_not_implicitly_toggle_preference(tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    store.save(
        overrides=[{
            "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
            "aliases": ["m/s²"], "reference": 2e-6,
        }],
        custom=[{
            "id": "user.x", "quantity": "custom", "label": "x", "unit": "unit",
            "aliases": ["unit"], "reference": 1.0,
        }],
        hidden_builtin_ids=["force.si"],
        prefer_channel_metadata=False,
    )
    assert store.revision == 1

    result = store.restore_factory_defaults()
    assert result == DbReferenceSaveResult(ok=True)
    assert store.revision == 2

    snap = store.snapshot()
    assert snap.system_catalog == db_reference.FACTORY_CATALOG_V1
    assert snap.user_catalog == ()
    # Restore never implicitly toggles the metadata preference back to True.
    assert snap.prefer_channel_metadata is False


def test_malformed_or_unknown_schema_falls_back_without_overwriting_raw_value(tmp_path):
    cases = [
        "{not valid json",
        json.dumps({"schema": 2, "overrides": [], "custom": [], "hidden_builtin_ids": []}),
        json.dumps({
            "schema": 1,
            "overrides": [{
                "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
                "aliases": ["m/s²"], "reference": -5,
            }],
            "custom": [], "hidden_builtin_ids": [],
        }),
        json.dumps({"schema": 1, "overrides": "not-a-list", "custom": [], "hidden_builtin_ids": []}),
    ]
    for i, raw in enumerate(cases):
        settings = _settings(tmp_path, name=f"malformed-{i}.ini")
        settings.setValue(KEY_CATALOG_V1, raw)
        settings.sync()

        store = DbReferenceSettingsStore(settings=settings)

        assert store.warning != "", raw
        snap = store.snapshot()
        assert snap.system_catalog == db_reference.FACTORY_CATALOG_V1, raw
        assert snap.user_catalog == (), raw
        # The raw malformed value must survive completely untouched -- the
        # store never "fixes" it by writing a corrected value back.
        assert settings.value(KEY_CATALOG_V1) == raw, raw


def test_invalid_save_is_atomic_and_keeps_previous_catalog(tmp_path):
    settings = _settings(tmp_path)
    store = DbReferenceSettingsStore(settings=settings)
    before = store.snapshot()

    # (a) structurally invalid reference (NaN fails validate_reference).
    result = store.save(
        overrides=[{
            "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
            "aliases": ["m/s²"], "reference": float("nan"),
        }],
        custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result.ok is False
    assert result.error

    # (b) semantically invalid: duplicate (quantity, alias) against a builtin.
    result2 = store.save(
        overrides=[],
        custom=[{
            "id": "user.dup", "quantity": "acceleration", "label": "dup",
            "unit": "m/s²", "aliases": ["m/s²"], "reference": 1.0,
        }],
        hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result2.ok is False
    assert result2.error

    assert store.snapshot() == before
    assert store.revision == 0
    assert settings.value(KEY_CATALOG_V1, None) is None


def test_catalog_revision_increments_only_after_successful_commit(tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    assert store.revision == 0

    failed = store.save(
        overrides=[{
            "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
            "aliases": ["m/s²"], "reference": -1.0,
        }],
        custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert failed.ok is False
    assert store.revision == 0

    ok = store.save(overrides=[], custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True)
    assert ok.ok is True
    assert store.revision == 1

    restored = store.restore_factory_defaults()
    assert restored.ok is True
    assert store.revision == 2

    failed2 = store.save(
        overrides=[{
            "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
            "aliases": ["m/s²"], "reference": 0,
        }],
        custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert failed2.ok is False
    assert store.revision == 2


def test_catalog_snapshot_is_plain_immutable_data(tmp_path):
    """Task 9 (Batch) injects this snapshot into worker code that must never
    import PyQt/QSettings -- it has to be plain, frozen Python data."""
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    snap = store.snapshot()

    assert isinstance(snap, DbReferenceCatalogSnapshot)
    assert isinstance(snap.system_catalog, tuple)
    assert isinstance(snap.user_catalog, tuple)
    assert all(isinstance(e, db_reference.DbReferenceEntry) for e in snap.system_catalog)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.revision = 99


def test_unknown_builtin_override_id_is_inert(tmp_path):
    """spec S12: 'unknown built-in IDs 不激活' -- a well-formed override
    referencing a builtin_id absent from the factory catalog neither errors
    nor crashes; it simply never participates in resolution."""
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    result = store.save(
        overrides=[{
            "builtin_id": "no_such_builtin",
            "label": "x", "unit": "x", "aliases": ["x"], "reference": 1.0,
        }],
        custom=[], hidden_builtin_ids=["also_unknown"], prefer_channel_metadata=True,
    )
    assert result.ok is True
    snap = store.snapshot()
    assert snap.system_catalog == db_reference.FACTORY_CATALOG_V1
    assert snap.user_catalog == ()
