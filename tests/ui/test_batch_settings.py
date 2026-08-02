"""Isolated-``QSettings`` tests for the batch panel's remembered display prefs.

Plan: ``docs/analyzer/plans/2026-08-02-batch-settings-persistence-plan.md``
step 5 (literal test names).

CRITICAL: every test constructs its OWN throwaway
``QSettings(path, QSettings.IniFormat)`` under ``tmp_path`` -- NEVER
``QSettings("MF4Analyzer", "DataAnalyzer")``, which would read/write the real
user's settings file.
"""
import json

from PyQt5.QtCore import QSettings

from mf4_analyzer.batch import BatchOutput
from mf4_analyzer.batch_render_style import (
    DEFAULT_FONT_SCALE,
    DEFAULT_TICK_DENSITY_X,
    DEFAULT_TICK_DENSITY_Y,
    MAX_TICK_DENSITY_X,
    MIN_TICK_DENSITY_Y,
)
from mf4_analyzer.ui.batch_settings import (
    KEY_PANEL_PREFS_V1,
    RUNTIME_OUTPUT_FIELDS,
    BatchPanelPrefs,
    BatchPanelPrefsStore,
)


def _settings(tmp_path, name="batch-prefs.ini"):
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


def _write_raw(tmp_path, payload, name="batch-prefs.ini"):
    """Put a hand-built value under the store's key, bypassing ``save``."""
    settings = _settings(tmp_path, name)
    settings.setValue(KEY_PANEL_PREFS_V1, payload)
    settings.sync()


def _default_render_style():
    return {
        "tick_density_x": DEFAULT_TICK_DENSITY_X,
        "tick_density_y": DEFAULT_TICK_DENSITY_Y,
        "font_scale": DEFAULT_FONT_SCALE,
    }


# ---------------------------------------------------------------------------
# Store round-trip and fault tolerance
# ---------------------------------------------------------------------------

def test_prefs_round_trip(tmp_path):
    store = BatchPanelPrefsStore(settings=_settings(tmp_path))
    prefs = BatchPanelPrefs(
        directory=str(tmp_path / "exports"),
        render_style={
            "tick_density_x": 22, "tick_density_y": 7, "font_scale": 1.35,
        },
        outputs={
            "export_data": False,
            "export_image": True,
            "data_format": "csv",
            "image_format": "png",
            "image_size": "2560x1440",
            "image_width": 2560,
            "image_height": 1440,
            "image_dpi": 220,
            "image_background": "transparent",
            "image_line_width": 2.25,
            "conflict_policy": "overwrite",
            "write_manifest": False,
        },
    )

    store.save(prefs)
    reloaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    assert reloaded.directory == str(tmp_path / "exports")
    assert reloaded.render_style == {
        "tick_density_x": 22, "tick_density_y": 7, "font_scale": 1.35,
    }
    assert reloaded.outputs == prefs.outputs
    assert reloaded == prefs


def test_load_returns_defaults_when_key_absent(tmp_path):
    loaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    assert loaded == BatchPanelPrefs()
    assert loaded.directory == ""
    assert loaded.render_style == _default_render_style()
    # The output defaults are BatchOutput's own, minus the runtime fields.
    defaults = BatchOutput()
    assert loaded.outputs["export_data"] is defaults.export_data
    assert loaded.outputs["image_dpi"] == defaults.image_dpi
    assert not set(RUNTIME_OUTPUT_FIELDS) & set(loaded.outputs)


def test_load_survives_unknown_schema_version(tmp_path):
    _write_raw(tmp_path, json.dumps({
        "schema": 999,
        "directory": "/tmp/from-the-future",
        "render_style": {"tick_density_x": 31},
        "outputs": {"export_data": False},
    }))

    loaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    assert loaded == BatchPanelPrefs()
    assert loaded.directory == ""
    assert loaded.render_style["tick_density_x"] == DEFAULT_TICK_DENSITY_X


def test_load_survives_corrupt_json(tmp_path):
    _write_raw(tmp_path, "{not json at all,,,")

    loaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    assert loaded == BatchPanelPrefs()


def test_load_survives_wrong_typed_fields(tmp_path):
    """A hand-edited payload must degrade per field, never abort the load."""
    _write_raw(tmp_path, json.dumps({
        "schema": 1,
        "directory": ["not", "a", "string"],
        "render_style": "not a mapping",
        "outputs": {
            "export_data": "nope",
            "image_dpi": "three hundred",
            "image_line_width": None,
            "unknown_future_field": 42,
        },
    }))

    loaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    defaults = BatchOutput()
    assert loaded.directory == ""
    assert loaded.render_style == _default_render_style()
    assert loaded.outputs["export_data"] is defaults.export_data
    assert loaded.outputs["image_dpi"] == defaults.image_dpi
    assert loaded.outputs["image_line_width"] == defaults.image_line_width
    assert "unknown_future_field" not in loaded.outputs
    # Whatever this returns must still be constructible as a BatchOutput.
    assert isinstance(loaded.as_output(), BatchOutput)


def test_save_omits_runtime_fields(tmp_path):
    """``resume_policy`` / ``requested_image_format`` / ``migration_warnings``
    are run-time diagnostics, not preferences -- they must never reach disk
    even when handed to ``save`` inside the outputs dict (which is exactly
    what ``dataclasses.asdict(BatchOutput(...))`` produces)."""
    import dataclasses

    store = BatchPanelPrefsStore(settings=_settings(tmp_path))
    store.save(BatchPanelPrefs(outputs=dataclasses.asdict(BatchOutput(
        resume_policy="skip_existing",
        requested_image_format="svg",
        migration_warnings=("图片格式 svg 不受支持",),
    ))))

    raw = _settings(tmp_path).value(KEY_PANEL_PREFS_V1)
    payload = json.loads(raw)

    for field in RUNTIME_OUTPUT_FIELDS:
        assert field not in payload["outputs"]
        assert field not in raw
    assert "skip_existing" not in raw
    assert "svg" not in raw
    # A fresh BatchOutput built from the payload carries pristine runtime
    # fields rather than the previous run's.
    restored = BatchPanelPrefsStore(settings=_settings(tmp_path)).load().as_output()
    assert restored.resume_policy == "none"
    assert restored.requested_image_format is None
    assert restored.migration_warnings == ()


def test_out_of_range_values_are_clamped(tmp_path):
    _write_raw(tmp_path, json.dumps({
        "schema": 1,
        "directory": "",
        "render_style": {
            "tick_density_x": 999, "tick_density_y": -4, "font_scale": 99.0,
        },
        "outputs": {},
    }))

    loaded = BatchPanelPrefsStore(settings=_settings(tmp_path)).load()

    assert loaded.render_style["tick_density_x"] == MAX_TICK_DENSITY_X
    assert loaded.render_style["tick_density_y"] == MIN_TICK_DENSITY_Y
    assert loaded.render_style["font_scale"] == 2.5


def test_clear_forgets_everything_the_store_wrote(tmp_path):
    store = BatchPanelPrefsStore(settings=_settings(tmp_path))
    store.save(BatchPanelPrefs(directory=str(tmp_path / "exports")))
    assert _settings(tmp_path).value(KEY_PANEL_PREFS_V1) is not None

    store.clear()

    assert _settings(tmp_path).value(KEY_PANEL_PREFS_V1) is None
    assert BatchPanelPrefsStore(settings=_settings(tmp_path)).load() == BatchPanelPrefs()
