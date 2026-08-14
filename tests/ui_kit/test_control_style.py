"""Contract tests for the shared semantic control-style foundation."""
from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt5.QtWidgets import QApplication, QPushButton

from mf4_analyzer.ui_kit.control_style import (
    CONTROL_COLORS,
    CONTROL_HEIGHT_EXCEPTIONS,
    CONTROL_HEIGHTS,
    CONTROL_QSS_TOKENS,
    CONTROL_ROLES,
    control_content_min_height,
    set_control_role,
)
import mf4_analyzer.ui_kit.stylesheet as stylesheet
from mf4_analyzer.ui_kit.icons import render_qss_template


_REPO_ROOT = Path(__file__).resolve().parents[2]
_QSS_PATH = _REPO_ROOT / "mf4_analyzer" / "ui_kit" / "style.qss"

_EXPECTED_COLOR_TOKENS = {
    "CONTROL_ACCENT",
    "CONTROL_ACCENT_HI",
    "CONTROL_ACCENT_DARK",
    "CONTROL_ACCENT_BORDER",
    "CONTROL_ACCENT_WASH",
    "CONTROL_SURFACE_TOP",
    "CONTROL_SURFACE_BOTTOM",
    "CONTROL_LINE",
    "CONTROL_LINE_HOVER",
    "CONTROL_TEXT",
    "CONTROL_TEXT_MUTED",
    "CONTROL_DANGER",
    "CONTROL_DANGER_WASH",
    "CONTROL_DISABLED_BG",
    "CONTROL_DISABLED_LINE",
    "CONTROL_ACCENT_LINE_SOFT",
    "CONTROL_TRACK",
    "CONTROL_TRACK_LINE",
    "CONTROL_SELECT_LINE",
    "CONTROL_TEXT_ON_SELECT",
}


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_standard_roles_are_stable_and_unique():
    assert CONTROL_ROLES == (
        "primary", "secondary", "quiet", "icon", "danger", "choice",
    )
    assert len(CONTROL_ROLES) == len(set(CONTROL_ROLES))


def test_colors_and_qss_tokens_have_one_source_of_truth():
    assert set(CONTROL_COLORS) == _EXPECTED_COLOR_TOKENS
    assert all(re.fullmatch(r"#[0-9A-F]{6}", value) for value in CONTROL_COLORS.values())

    for key, value in CONTROL_COLORS.items():
        assert CONTROL_QSS_TOKENS[key] == value
    assert set(CONTROL_QSS_TOKENS) > set(CONTROL_COLORS)
    assert CONTROL_QSS_TOKENS["CONTROL_H_BASE"] == "32px"


def test_height_tracks_and_qss_content_conversion_have_one_source_of_truth():
    assert dict(CONTROL_HEIGHTS) == {"compact": 24, "base": 32, "cta": 36}
    assert len(set(CONTROL_HEIGHTS.values())) == len(CONTROL_HEIGHTS)

    assert control_content_min_height("compact", vertical_padding=2) == 18
    assert control_content_min_height("base", vertical_padding=4) == 22
    assert control_content_min_height("base", vertical_padding=3) == 24
    assert control_content_min_height("cta", vertical_padding=4) == 26
    assert CONTROL_QSS_TOKENS["CONTROL_H_BASE_BUTTON_CONTENT"] == "22px"
    assert CONTROL_QSS_TOKENS["CONTROL_H_BASE_INPUT_CONTENT"] == "24px"

    with pytest.raises(ValueError, match="Unknown control size"):
        control_content_min_height("oversized", vertical_padding=0)


def test_height_exception_allowlist_is_explicit_and_documented():
    assert CONTROL_HEIGHT_EXCEPTIONS
    assert all(selector and reason for selector, reason in CONTROL_HEIGHT_EXCEPTIONS.items())
    assert "QToolButton#inspectorCollapser" in CONTROL_HEIGHT_EXCEPTIONS
    assert "QPushButton#channelConfigSave" in CONTROL_HEIGHT_EXCEPTIONS
    assert "QComboBox#channelConfigCombo" in CONTROL_HEIGHT_EXCEPTIONS


def test_set_control_role_sets_properties_and_repolishes(qapp):
    button = QPushButton("Apply")
    try:
        set_control_role(button, "primary", size="cta")
        assert button.property("role") == "primary"
        assert button.property("controlSize") == "cta"

        set_control_role(button, "quiet")
        assert button.property("role") == "quiet"
    finally:
        button.deleteLater()


def test_set_control_role_rejects_unknown_semantics(qapp):
    button = QPushButton("Apply")
    try:
        with pytest.raises(ValueError, match="Unknown control role"):
            set_control_role(button, "tool")
        with pytest.raises(ValueError, match="Unknown control size"):
            set_control_role(button, "primary", size="oversized")
    finally:
        button.deleteLater()


def test_control_style_import_stays_below_product_ui_layers():
    probe = """
import sys
import mf4_analyzer.ui_kit.control_style
forbidden = (
    'mf4_analyzer.ui',
    'mf4_analyzer.acquisition_ui',
)
loaded = [
    name for name in sys.modules for prefix in forbidden
    if name == prefix or name.startswith(prefix + '.')
]
raise SystemExit(1 if loaded else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_stylesheet_merges_control_and_icon_tokens_without_api_churn(monkeypatch):
    captured: dict[str, str] = {}

    class _Application:
        def setStyleSheet(self, value):
            captured["stylesheet"] = value

    monkeypatch.setattr(stylesheet, "ensure_icon_cache", lambda: {"ICON_COMBO_DOWN_REST": "/tmp/down.png"})
    monkeypatch.setattr(stylesheet, "install_combo_popup_shell", lambda app: None)
    monkeypatch.setattr(stylesheet, "install_message_box_button_roles", lambda app: None)

    stylesheet.load_stylesheet(_Application())

    assert "{{CONTROL_" not in captured["stylesheet"]
    assert "{{ICON_COMBO_DOWN_REST}}" not in captured["stylesheet"]
    assert tuple(inspect.signature(render_qss_template).parameters) == (
        "template_text", "icon_paths",
    )
    assert render_qss_template("{{ICON_COMBO_DOWN_REST}}", {"ICON_COMBO_DOWN_REST": "x"}) == "x"


def test_generic_button_qss_uses_control_tokens_and_has_no_tool_alias():
    qss = _QSS_PATH.read_text(encoding="utf-8")
    button_block = qss[
        qss.index('QPushButton[role="primary"]')
        :qss.index("QMessageBox QPushButton")
    ]

    assert not re.search(r"#[0-9a-fA-F]{6}", button_block)
    for role in CONTROL_ROLES:
        for state in ("", ":hover", ":pressed", ":disabled", ":checked"):
            selector = f'QPushButton[role="{role}"]{state}'
            assert selector in button_block, selector
            selector = f'QToolButton[role="{role}"]{state}'
            assert selector in button_block, selector

    assert '[role="tool"]' not in button_block
    for legacy_role in ("accent", "create", "destructive"):
        assert f'[role="{legacy_role}"]' in button_block
