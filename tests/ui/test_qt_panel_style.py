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
    assert style.glass_alpha(fallback=True) == 255  # no sharp text leaks without blur
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


@pytest.fixture
def cocoa_calls(monkeypatch):
    from mf4_analyzer import qt_panel_cocoa as cocoa

    class Runtime:
        def objc_getClass(self, name):
            return 10

    calls = []

    def send(receiver, selector, result=None, types=(), values=()):
        calls.append((receiver, selector))
        return {"superview": 20, "alloc": 30, "initWithFrame:": 30}.get(selector, 0)

    monkeypatch.setattr(cocoa, "_runtime", Runtime)
    monkeypatch.setattr(cocoa, "_send", send)
    return calls


def test_cocoa_release_disconnects_destroyed_callback(host, cocoa_calls):
    from PyQt5.QtCore import QCoreApplication, QEvent
    from mf4_analyzer.qt_panel_cocoa import CocoaBackdrop

    before = host.receivers(host.destroyed)
    for _ in range(5):
        native = CocoaBackdrop(host)
        try:
            assert native.applied
            assert host.receivers(host.destroyed) > before
        finally:
            native.release()
        native.release()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert host.receivers(host.destroyed) == before
    assert sum(selector == "release" for _, selector in cocoa_calls) == 5


def test_cocoa_destroy_releases_view_once(qapp, cocoa_calls):
    from PyQt5 import sip
    from mf4_analyzer.qt_panel_cocoa import CocoaBackdrop

    widget = QWidget()
    native = CocoaBackdrop(widget)
    try:
        sip.delete(widget)
    finally:
        native.release()
    assert not native.applied
    assert sum(selector == "release" for _, selector in cocoa_calls) == 1


def test_cocoa_respects_reduce_transparency(host, cocoa_calls, monkeypatch):
    from mf4_analyzer import qt_panel_cocoa as cocoa

    send = cocoa._send

    def reduced(receiver, selector, *args, **kwargs):
        if selector == "accessibilityDisplayShouldReduceTransparency":
            return True
        return send(receiver, selector, *args, **kwargs)

    monkeypatch.setattr(cocoa, "_send", reduced)
    native = cocoa.CocoaBackdrop(host)
    assert not native.applied
    assert native.reason == "transparency_disabled"
    native.release()
    assert not any(selector == "alloc" for _, selector in cocoa_calls)


def test_cocoa_surface_force_replaces_and_releases(host, cocoa_calls, monkeypatch):
    from PyQt5.QtGui import QGuiApplication

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "cocoa"))
    first = style.apply_native_panel_surface(host, platform="darwin")
    try:
        assert first.applied
        assert style.apply_native_panel_surface(host, platform="darwin") is first
        second = style.apply_native_panel_surface(host, platform="darwin", force=True)
        assert second.applied
        assert not first.native.applied
    finally:
        style.release_native_panel_surface(host)
    assert style.uses_opaque_fallback(host)
    assert sum(selector == "release" for _, selector in cocoa_calls) == 2


def test_cocoa_runtime_unavailable_uses_opaque_surface(host, monkeypatch):
    from PyQt5.QtGui import QGuiApplication
    from mf4_analyzer import qt_panel_cocoa as cocoa

    def missing():
        raise OSError("runtime unavailable")

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "cocoa"))
    monkeypatch.setattr(cocoa, "_runtime", missing)
    state = style.apply_native_panel_surface(host, platform="darwin")
    assert not state.applied
    assert state.reason == "cocoa_unavailable"
    assert style.uses_opaque_fallback(host)
