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

import ast
import os
from pathlib import Path
import subprocess
import sys

from mf4_analyzer.ui import batch_settings
from mf4_analyzer.ui import inspector_sections as inspector_sections_package
from mf4_analyzer.ui.inspector_sections import _helpers, presets
from mf4_analyzer.ui.inspector_sections import collapsible, persistent_top

REAL_STORE_MARKERS = ("MF4Analyzer", "DataAnalyzer")
_UI_TESTS_DIR = Path(__file__).resolve().parent


def _is_qsettings_constructor(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id == "QSettings"
    ) or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "QSettings"
    )


def _native_qsettings_constructor_calls() -> list[str]:
    """Return UI-test constructors that select a machine-persistent backend.

    The only approved explicit constructor shape in UI tests is
    ``QSettings(path, QSettings.IniFormat)``.  Two string arguments select an
    organization/application native store, and a four-argument NativeFormat
    call does the same even when the organization is test-only.
    """
    calls = []
    for path in sorted(_UI_TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_qsettings_constructor(node):
                continue
            args = node.args
            is_explicit_ini = (
                len(args) == 2
                and isinstance(args[1], ast.Attribute)
                and args[1].attr == "IniFormat"
            )
            is_native_org_app = len(args) == 2 and not is_explicit_ini
            is_native_scoped = (
                len(args) >= 4
                and isinstance(args[0], ast.Attribute)
                and args[0].attr == "NativeFormat"
            )
            if is_native_org_app or is_native_scoped:
                calls.append(f"{path.relative_to(_UI_TESTS_DIR.parent.parent)}:{node.lineno}")
    return calls


def _fixed_qsettings_path_calls() -> list[str]:
    """Return explicit INI stores rooted in a process- or repository-wide path."""
    calls = []
    for path in sorted(_UI_TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_qsettings_constructor(node):
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            has_fixed_root = any(
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and (child.value.startswith("/tmp") or child.value.startswith(".pytmp/"))
                for child in ast.walk(first_arg)
            )
            has_tmpdir_env = any(
                isinstance(child, ast.Subscript)
                and isinstance(child.value, ast.Attribute)
                and isinstance(child.value.value, ast.Name)
                and child.value.value.id == "os"
                and child.value.attr == "environ"
                for child in ast.walk(first_arg)
            )
            if has_fixed_root or has_tmpdir_env:
                calls.append(f"{path.relative_to(_UI_TESTS_DIR.parent.parent)}:{node.lineno}")
    return calls


def test_ui_tests_do_not_construct_native_org_app_qsettings():
    """Native org/app stores outlive an item and can target developer prefs."""
    calls = _native_qsettings_constructor_calls()
    assert not calls, (
        "UI tests must inject QSettings(path, QSettings.IniFormat) below "
        "their current tmp_path instead of constructing native org/app stores: "
        + ", ".join(calls)
    )


def test_ui_tests_do_not_use_fixed_qsettings_paths():
    """An INI must belong to the current item's tmp_path, never shared /tmp."""
    calls = _fixed_qsettings_path_calls()
    assert not calls, (
        "UI tests must build explicit INI paths below their current tmp_path, not "
        "a fixed /tmp, .pytmp, or TMPDIR path: " + ", ".join(calls)
    )


def _assert_item_store(settings, tmp_path, *, label: str) -> Path:
    """Assert that *settings* is an INI file owned by this exact item."""
    file_name = settings.fileName()
    assert not any(marker in file_name for marker in REAL_STORE_MARKERS), (
        f"{label} resolves to {file_name!r}, which looks like the live application store."
    )
    path = Path(file_name).resolve()
    assert path.is_relative_to(tmp_path.resolve()), (
        f"{label} resolves to {file_name!r}, outside this item's tmp_path "
        f"{tmp_path!s}."
    )
    return path


def test_preset_settings_is_redirected_away_from_the_real_store(tmp_path):
    settings = presets._preset_settings()

    assert settings.organizationName() == "", (
        "PresetBar is reading the real organization-scoped store; "
        "tests/ui/conftest.py::_isolate_qsettings is not applying."
    )
    _assert_item_store(settings, tmp_path, label="PresetBar settings")


def test_every_patched_module_and_batch_factory_share_one_item_store(tmp_path):
    """All inspector modules must agree, or half the suite stays unisolated."""
    factories = {
        "package": inspector_sections_package._preset_settings,
        "_helpers": _helpers._preset_settings,
        "presets": presets._preset_settings,
        "collapsible": collapsible._preset_settings,
        "persistent_top": persistent_top._preset_settings,
        "batch": batch_settings._default_settings,
    }
    file_names = {
        name: _assert_item_store(fn(), tmp_path, label=name)
        for name, fn in factories.items()
    }
    assert len(set(file_names.values())) == 1, (
        f"inspector modules resolve settings to different stores: {file_names}"
    )


def test_bare_qsettings_uses_the_current_item_ini_store(tmp_path):
    """The default constructor is safe only when it is scoped to this item."""
    from PyQt5.QtCore import QSettings

    settings = QSettings()
    _assert_item_store(settings, tmp_path, label="bare QSettings")
    settings.setValue("tests/qsettings-isolation/bare", tmp_path.name)
    settings.sync()
    assert settings.value("tests/qsettings-isolation/bare") == tmp_path.name


def test_qsettings_stores_are_invisible_between_ui_items(tmp_path):
    """Run two actual fixture items in a child process and compare their files."""
    child_root = tmp_path / "qsettings-child"
    child_root.mkdir()
    records_path = child_root / "records.txt"
    source_conftest = _UI_TESTS_DIR / "conftest.py"
    (child_root / "conftest.py").write_text(
        "\n".join(
            (
                "import importlib.util",
                f"source = {str(source_conftest)!r}",
                "spec = importlib.util.spec_from_file_location('ui_qsettings_fixture', source)",
                "fixture_module = importlib.util.module_from_spec(spec)",
                "assert spec.loader is not None",
                "spec.loader.exec_module(fixture_module)",
                "_isolate_qsettings = fixture_module._isolate_qsettings",
            )
        ),
        encoding="utf-8",
    )
    (child_root / "test_items.py").write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "from PyQt5.QtCore import QSettings",
                "from mf4_analyzer.ui import batch_settings",
                "from mf4_analyzer.ui import inspector_sections as sections",
                f"RECORDS = Path({str(records_path)!r})",
                "",
                "def _stores(tmp_path):",
                "    stores = {",
                "        'package': sections._preset_settings(),",
                "        'batch': batch_settings._default_settings(),",
                "        'bare': QSettings(),",
                "    }",
                "    paths = {name: Path(store.fileName()).resolve() for name, store in stores.items()}",
                "    assert all(path.is_relative_to(tmp_path.resolve()) for path in paths.values())",
                "    assert paths['package'] == paths['batch']",
                "    return stores, paths",
                "",
                "def test_first_item(tmp_path):",
                "    stores, paths = _stores(tmp_path)",
                "    stores['package'].setValue('tests/cross-item', 'first')",
                "    stores['package'].sync()",
                "    RECORDS.write_text(str(paths['package']), encoding='utf-8')",
                "",
                "def test_second_item(tmp_path):",
                "    stores, paths = _stores(tmp_path)",
                "    assert paths['package'] != Path(RECORDS.read_text(encoding='utf-8')).resolve()",
                "    assert stores['package'].value('tests/cross-item') is None",
            )
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_UI_TESTS_DIR.parent.parent)
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"{child_root / 'test_items.py'}::test_first_item",
            f"{child_root / 'test_items.py'}::test_second_item",
        ],
        cwd=str(_UI_TESTS_DIR.parent.parent),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_ui_item_restores_default_qsettings_format_before_non_ui_item(tmp_path):
    """A UI item must not leave its forced INI default for the next collector."""
    after_ui = tmp_path / "test_after_ui.py"
    after_ui.write_text(
        "\n".join(
            (
                "from PyQt5.QtCore import QSettings",
                "",
                "def test_default_format_is_native_after_ui_item():",
                "    assert QSettings.defaultFormat() == QSettings.NativeFormat",
            )
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_UI_TESTS_DIR.parent.parent)
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/ui/test_qsettings_isolation.py::test_bare_qsettings_uses_the_current_item_ini_store",
            str(after_ui),
        ],
        cwd=str(_UI_TESTS_DIR.parent.parent),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
