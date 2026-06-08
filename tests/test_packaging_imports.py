from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "build" / "spec" / "TraceLab6.5.spec"
WINDOWS_BUILD_SCRIPT = REPO_ROOT / "tools" / "build_windows_folder.ps1"

REQUIRED_HIDDEN_IMPORTS = [
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui.pg_canvases",
    "mf4_analyzer.acquisition_capture",
    "mf4_analyzer.acquisition_capture.thresholds",
    "mf4_analyzer.acquisition_capture.health",
    "mf4_analyzer.acquisition_capture.ring_buffer",
    "mf4_analyzer.acquisition_capture.backends",
    "mf4_analyzer.acquisition_capture.controller",
    "mf4_analyzer.acquisition_capture.writer",
    "mf4_analyzer.acquisition_capture.session",
    "mf4_analyzer.acquisition_capture.search",
    "mf4_analyzer.acquisition_capture.a2l_events",
    "mf4_analyzer.acquisition_capture.config_store",
    "mf4_analyzer.acquisition_capture.preflight_estimates",
    "mf4_analyzer.acquisition_ui",
    "mf4_analyzer.acquisition_ui.main_window",
    "mf4_analyzer.acquisition_ui.state",
    "mf4_analyzer.acquisition_ui.review_modal",
    "mf4_analyzer.acquisition_ui.settings_dialog",
    "mf4_analyzer.acquisition_ui.history_tab",
    "mf4_analyzer.acquisition_ui.replay_tab",
]

WIDGET_MODULES = [
    "mf4_analyzer.acquisition_ui.widgets.health_strip",
    "mf4_analyzer.acquisition_ui.widgets.left_pane",
    "mf4_analyzer.acquisition_ui.widgets.live_cards",
    "mf4_analyzer.acquisition_ui.widgets.live_downsampler",
    "mf4_analyzer.acquisition_ui.widgets.right_panel",
]

PENDING_STAGE_MODULES = {
    "mf4_analyzer.acquisition_ui.settings_dialog",
    "mf4_analyzer.acquisition_ui.history_tab",
    "mf4_analyzer.acquisition_ui.replay_tab",
}


def test_pyinstaller_spec_lists_new_modules_and_style_data():
    if not SPEC_PATH.exists():
        pytest.skip(
            "PyInstaller spec is a build artifact; run "
            "tools/build_windows_folder.ps1 to regenerate before asserting."
        )
    text = SPEC_PATH.read_text(encoding="utf-8")

    for module_name in REQUIRED_HIDDEN_IMPORTS:
        assert module_name in text
    assert "mf4_analyzer.ui_kit.style.qss" not in text
    assert "ui_kit" in text and "style.qss" in text
    assert "widgets.*" not in text
    assert (
        'collect_submodules("mf4_analyzer.acquisition_ui.widgets")' in text
        or "collect_submodules('mf4_analyzer.acquisition_ui.widgets')" in text
        or all(module_name in text for module_name in WIDGET_MODULES)
    )


def test_windows_build_script_lists_new_modules_and_widget_collection():
    text = WINDOWS_BUILD_SCRIPT.read_text(encoding="utf-8")

    for module_name in REQUIRED_HIDDEN_IMPORTS:
        assert module_name in text
    assert "mf4_analyzer\\ui_kit\\style.qss" in text
    assert "widgets.*" not in text
    assert "--collect-submodules" in text
    assert "mf4_analyzer.acquisition_ui.widgets" in text
    assert "pyqtgraph" in text
    assert '"--collect-submodules", "pyqtgraph"' in text


def test_packaging_hidden_import_modules_import_on_this_checkout():
    pending: list[str] = []
    imported: list[str] = []
    for module_name in REQUIRED_HIDDEN_IMPORTS + WIDGET_MODULES:
        if importlib.util.find_spec(module_name) is None:
            if module_name in PENDING_STAGE_MODULES:
                pending.append(module_name)
                continue
            raise AssertionError(f"packaging module is missing: {module_name}")
        importlib.import_module(module_name)
        imported.append(module_name)

    assert imported
    if pending:
        pytest.skip(
            "pending Stage 2-4 Cockpit modules are named in packaging but "
            f"not present in this checkout yet: {pending}"
        )
