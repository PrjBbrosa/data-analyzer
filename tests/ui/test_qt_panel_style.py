"""Behavior tests for ``mf4_analyzer.qt_panel_style`` (fonts + native surface).

Native Acrylic appearance on real Windows is NOT asserted here — only the
support / failure / release contract with injectable fakes.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QWidget

from mf4_analyzer import qt_panel_style as style


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def host(qtbot, qapp):
    del qapp
    widget = QWidget()
    widget.setObjectName("qtPanelStyleHost")
    qtbot.addWidget(widget)
    yield widget
    style.release_native_panel_surface(widget)
    widget.close()


def test_module_import_avoids_heavy_deps():
    """Top-level import must stay stdlib-only; PyQt/ctypes stay function-local."""
    src = REPO_ROOT / "mf4_analyzer" / "qt_panel_style.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    top_level = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.append(node.module)
    assert set(top_level) <= {"sys", "typing", "__future__"}
    forbidden_prefixes = (
        "PyQt5",
        "numpy",
        "pandas",
        "pyqtgraph",
        "mf4_analyzer.ui",
        "mf4_analyzer.ui_kit",
        "ctypes",
        "winreg",
    )
    for name in top_level:
        for prefix in forbidden_prefixes:
            assert name != prefix and not name.startswith(prefix + "."), name


def test_glass_alpha_contract():
    assert style.GLASS_ALPHA == 191
    assert style.FROST_REFERENCE_PX == 25
    assert style.glass_alpha(fallback=False) == 191
    assert style.glass_alpha(fallback=True) == style.FALLBACK_GLASS_ALPHA
    fill = style.glass_fill_color(fallback=False)
    assert fill.red() == 244 and fill.green() == 250 and fill.blue() == 255
    assert fill.alpha() == 191
    assert style.SPECTRUM_STOP_HEX == (
        "#17b6df",
        "#1e85ed",
        "#5773ed",
        "#23bbd0",
    )


def test_panel_font_roles_regular_and_bold(qapp):
    del qapp
    style.reset_panel_font_family_cache()
    family = style.resolve_panel_font_family()
    assert family

    body = style.panel_font(style.FONT_ROLE_BODY, pixel_size=13)
    bold = style.panel_font(style.FONT_ROLE_EMPHASIS, pixel_size=13, bold=True)
    assert body.pixelSize() == 13
    assert bold.pixelSize() == 13
    assert not body.bold()
    assert body.weight() <= QFont.Normal
    assert bold.bold() or bold.weight() >= QFont.DemiBold
    # Same family strategy for mixed CJK/ASCII body text.
    assert body.family() == family or body.families()
    metrics = style.panel_font_metrics(style.FONT_ROLE_BODY, pixel_size=13)
    assert metrics.horizontalAdvance("Home Pn 12") > 0
    assert metrics.horizontalAdvance("启动面板") > 0


def test_apply_unsupported_platform_returns_fallback(host):
    state = style.apply_native_panel_surface(
        host,
        platform="darwin",
        force=True,
    )
    assert not state.applied
    assert state.fallback
    assert state.reason == "unsupported_platform"
    assert style.uses_opaque_fallback(host)


def test_apply_high_contrast_and_transparency_disabled(host):
    state = style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=True,
        transparency_enabled=True,
        hwnd=0x1234,
        force=True,
    )
    assert state.reason == "high_contrast"
    assert not state.applied

    state = style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=False,
        hwnd=0x1234,
        force=True,
    )
    assert state.reason == "transparency_disabled"
    assert not state.applied


class _FakeDwm:
    def __init__(self, hr: int = 0):
        self.hr = hr
        self.calls = []

    def DwmSetWindowAttribute(self, hwnd, attr, value_ptr, size):  # noqa: N802
        self.calls.append((int(hwnd), int(attr), int(size)))
        return self.hr


def test_apply_success_path_with_fake_dwm(host):
    fake = _FakeDwm(hr=0)
    state = style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0xABCD,
        dwmapi=fake,
        force=True,
    )
    assert state.applied
    assert not state.fallback
    assert state.reason == ""
    assert fake.calls
    assert fake.calls[0][0] == 0xABCD
    assert fake.calls[0][1] == 38  # DWMWA_SYSTEMBACKDROP_TYPE
    # Backdrop type must be the official TRANSIENTWINDOW enum (3), never 15.
    assert style._DWMSBT_TRANSIENTWINDOW == 3
    assert style._DWMSBT_TRANSIENTWINDOW != 15


def test_apply_dwm_failure_falls_back(host):
    fake = _FakeDwm(hr=0x80004005)
    state = style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0xABCD,
        dwmapi=fake,
        force=True,
    )
    assert not state.applied
    assert state.reason == "dwm_failed"
    assert state.fallback


def test_release_is_idempotent(host):
    fake = _FakeDwm(hr=0)
    style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0x1111,
        dwmapi=fake,
        force=True,
    )
    style.release_native_panel_surface(host, dwmapi=fake, hwnd=0x1111)
    style.release_native_panel_surface(host, dwmapi=fake, hwnd=0x1111)
    assert style.uses_opaque_fallback(host)
    # Second apply with force re-runs Win32 once.
    before = len(fake.calls)
    style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0x1111,
        dwmapi=fake,
        force=True,
    )
    assert len(fake.calls) > before


def test_apply_is_idempotent_without_force(host):
    fake = _FakeDwm(hr=0)
    style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0x2222,
        dwmapi=fake,
        force=True,
    )
    n = len(fake.calls)
    style.apply_native_panel_surface(
        host,
        platform="win32",
        build_number=22621,
        high_contrast=False,
        transparency_enabled=True,
        hwnd=0x2222,
        dwmapi=fake,
        force=False,
    )
    assert len(fake.calls) == n
