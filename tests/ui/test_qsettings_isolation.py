"""Guard: the UI suite never touches the real MF4Analyzer preference store.

``tests/ui/conftest.py::_isolate_qsettings`` is the only thing standing
between this suite and the developer's live ``MF4Analyzer/DataAnalyzer``
settings. When it stops applying, nothing announces it — widgets happily read
and write the real store, so tests start depending on (and mutating) whatever
the developer's machine happens to hold. That is exactly how
``test_builtin_preset_bar_custom_slot_saves_and_loads_without_builtin_toggle``
became order-dependent: a stale ``test_kind_builtin_custom/preset_custom/4``
entry left in the real store made an empty slot read as filled.

This test states the invariant directly, so a lost fixture surfaces as one
obvious red test instead of as inexplicable failures elsewhere (or as silent
writes to the developer's preferences). The collection-level cause that broke
it before is covered by ``tests/test_conftest_autouse_scope.py``.
"""

from mf4_analyzer.ui.inspector_sections import _helpers, presets
from mf4_analyzer.ui.inspector_sections import collapsible, persistent_top

REAL_STORE_MARKERS = ("MF4Analyzer", "DataAnalyzer")


def test_preset_settings_is_redirected_away_from_the_real_store(tmp_path):
    settings = presets._preset_settings()

    assert settings.organizationName() == "", (
        "PresetBar is reading the real organization-scoped store; "
        "tests/ui/conftest.py::_isolate_qsettings is not applying."
    )
    file_name = settings.fileName()
    assert not any(marker in file_name for marker in REAL_STORE_MARKERS), (
        f"PresetBar settings resolve to {file_name!r}, which looks like the "
        f"live application store."
    )
    assert file_name.startswith(str(tmp_path.parent.parent)), (
        f"PresetBar settings resolve to {file_name!r}, outside the per-test "
        f"temporary directory."
    )


def test_every_patched_module_shares_one_redirected_store():
    """All inspector modules must agree, or half the suite stays unisolated."""
    factories = {
        "_helpers": _helpers._preset_settings,
        "presets": presets._preset_settings,
        "collapsible": collapsible._preset_settings,
        "persistent_top": persistent_top._preset_settings,
    }
    file_names = {name: fn().fileName() for name, fn in factories.items()}
    assert len(set(file_names.values())) == 1, (
        f"inspector modules resolve settings to different stores: {file_names}"
    )
