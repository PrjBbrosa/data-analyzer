"""Failure-path contracts for QSS subcontrol icon resources."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from PyQt5.QtCore import QRect
from PyQt5.QtGui import QColor, QFontDatabase, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QHBoxLayout, QWidget

import mf4_analyzer.ui_kit.icons as icons
import mf4_analyzer.ui_kit.stylesheet as stylesheet


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _qss_placeholders() -> set[str]:
    template = (Path(icons.__file__).resolve().parent / "style.qss").read_text(
        encoding="utf-8"
    )
    return set(re.findall(r"\{\{(ICON_[A-Z0-9_]+)\}\}", template))


def _cache_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_near(color: QColor, expected: str, tolerance: int = 52) -> bool:
    target = QColor(expected)
    return (
        color.alpha() > 100
        and abs(color.red() - target.red()) <= tolerance
        and abs(color.green() - target.green()) <= tolerance
        and abs(color.blue() - target.blue()) <= tolerance
    )


def _contains_near(image: QImage, rect: QRect, color: str) -> bool:
    bounds = rect.intersected(QRect(0, 0, image.width(), image.height()))
    return any(
        _is_near(image.pixelColor(x, y), color)
        for y in range(bounds.top(), bounds.bottom() + 1)
        for x in range(bounds.left(), bounds.right() + 1)
    )


def test_healthy_cache_is_decodable_and_not_rewritten(qapp, tmp_path, monkeypatch):
    cache_dir = tmp_path / "中文 cache icons"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))

    first = icons.ensure_icon_cache()
    expected = {placeholder for placeholder, _name, _color in icons._ARROW_SPECS}
    assert set(first) == expected
    assert _qss_placeholders() <= set(first)
    assert all("\\" not in path for path in first.values())
    assert all(icons._png_status(Path(path)) == "valid" for path in first.values())
    mtimes = {path: Path(path).stat().st_mtime_ns for path in first.values()}

    assert icons.ensure_icon_cache() == first
    assert {path: Path(path).stat().st_mtime_ns for path in first.values()} == mtimes


def test_undecodable_nonempty_cache_png_is_regenerated(qapp, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))
    paths = icons.ensure_icon_cache()
    damaged = Path(paths["ICON_COMBO_DOWN_REST"])
    damaged.write_bytes(b"not a png, but not empty")

    regenerated = icons.ensure_icon_cache()
    assert regenerated["ICON_COMBO_DOWN_REST"] == str(damaged).replace("\\", "/")
    assert icons._png_status(damaged) == "valid"


def test_save_false_uses_decodable_packaged_fallback(qapp, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))
    import qtawesome as qta

    class _PixmapSaveFalse:
        def isNull(self):
            return False

        def setDevicePixelRatio(self, _ratio):
            pass

        def save(self, *_args):
            return False

    class _IconSaveFalse:
        def pixmap(self, *_args):
            return _PixmapSaveFalse()

    monkeypatch.setattr(qta, "icon", lambda *_args, **_kwargs: _IconSaveFalse())
    paths = icons.ensure_icon_cache()
    fallbacks = icons.packaged_icon_fallback_paths()

    assert paths == fallbacks
    assert not list(cache_dir.glob("*.png"))
    assert all(icons._png_status(Path(path)) == "valid" for path in paths.values())


def test_cache_write_permission_error_uses_packaged_fallback(qapp, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))
    import qtawesome as qta

    class _PixmapWriteDenied:
        def isNull(self):
            return False

        def setDevicePixelRatio(self, _ratio):
            pass

        def save(self, *_args):
            raise PermissionError("cache file write denied")

    class _IconWriteDenied:
        def pixmap(self, *_args):
            return _PixmapWriteDenied()

    monkeypatch.setattr(qta, "icon", lambda *_args, **_kwargs: _IconWriteDenied())
    assert icons.ensure_icon_cache() == icons.packaged_icon_fallback_paths()


def test_cache_directory_io_failure_renders_combo_and_checked_box(qapp, tmp_path, monkeypatch):
    def _deny_cache():
        raise PermissionError("cache directory denied")

    monkeypatch.setattr(icons, "_icon_cache_dir", _deny_cache)
    monkeypatch.setattr(stylesheet, "install_combo_popup_shell", lambda _app: None)
    monkeypatch.setattr(stylesheet, "install_message_box_button_roles", lambda _app: None)
    before = qapp.styleSheet()
    host = QWidget()
    layout = QHBoxLayout(host)
    combo = QComboBox(host)
    combo.addItem("选择")
    check = QCheckBox("启用", host)
    check.setChecked(True)
    layout.addWidget(combo)
    layout.addWidget(check)
    try:
        stylesheet.load_stylesheet(qapp)
        assert "{{ICON_" not in qapp.styleSheet()
        host.resize(260, 48)
        host.show()
        qapp.processEvents()
        image = host.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        combo_pos = combo.mapTo(host, combo.rect().topLeft())
        check_pos = check.mapTo(host, check.rect().topLeft())
        combo_arrow = QRect(combo_pos.x() + combo.width() - 20, combo_pos.y() + 7, 14, 18)
        check_indicator = QRect(check_pos.x(), check_pos.y() + 7, 17, 17)
        assert _contains_near(image, combo_arrow, "#475569")
        assert _contains_near(image, check_indicator, "#ffffff")
    finally:
        qapp.setStyleSheet(before)
        host.deleteLater()
        qapp.processEvents()


def test_font_registration_failure_uses_packaged_fallbacks_and_renders_qss(
    qapp, tmp_path, monkeypatch
):
    """A failed qtawesome font registration must not abort QSS installation."""
    cache_dir = tmp_path / "empty-cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))

    import qtawesome as qta

    # Start from an empty qtawesome singleton so this exercises its real lazy
    # font-loading path rather than a font retained by an earlier test.
    monkeypatch.setitem(qta._resource, "iconic", None)
    monkeypatch.setattr(QFontDatabase, "addApplicationFontFromData", lambda _data: -1)
    monkeypatch.setattr(stylesheet, "install_combo_popup_shell", lambda _app: None)
    monkeypatch.setattr(stylesheet, "install_message_box_button_roles", lambda _app: None)

    fallbacks = icons.packaged_icon_fallback_paths()
    before = qapp.styleSheet()
    host = QWidget()
    layout = QHBoxLayout(host)
    combo = QComboBox(host)
    combo.addItem("选择")
    check = QCheckBox("启用", host)
    check.setChecked(True)
    layout.addWidget(combo)
    layout.addWidget(check)
    try:
        stylesheet.load_stylesheet(qapp)
        assert "{{ICON_" not in qapp.styleSheet()
        assert set(fallbacks) == {placeholder for placeholder, _name, _color in icons._ARROW_SPECS}
        assert all(icons._png_status(Path(path)) == "valid" for path in fallbacks.values())
        assert fallbacks["ICON_COMBO_DOWN_REST"] in qapp.styleSheet()
        assert fallbacks["ICON_CHECKBOX_CHECKED"] in qapp.styleSheet()
        assert not list(cache_dir.glob("*.png"))

        host.resize(260, 48)
        host.show()
        qapp.processEvents()
        image = host.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        combo_pos = combo.mapTo(host, combo.rect().topLeft())
        check_pos = check.mapTo(host, check.rect().topLeft())
        combo_arrow = QRect(combo_pos.x() + combo.width() - 20, combo_pos.y() + 7, 14, 18)
        check_indicator = QRect(check_pos.x(), check_pos.y() + 7, 17, 17)
        assert _contains_near(image, combo_arrow, "#475569")
        assert _contains_near(image, check_indicator, "#ffffff")
    finally:
        qapp.setStyleSheet(before)
        host.deleteLater()
        qapp.processEvents()


def test_font_resource_read_failure_uses_decodable_packaged_fallbacks(
    qapp, tmp_path, monkeypatch
):
    """Known font-resource IO errors must degrade to every bundled glyph."""
    cache_dir = tmp_path / "empty-cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))

    import qtawesome as qta

    monkeypatch.setitem(qta._resource, "iconic", None)
    monkeypatch.setattr(
        qta.IconicFont,
        "_get_fonts_directory",
        lambda _self: str(tmp_path / "missing-qtawesome-fonts"),
    )

    paths = icons.ensure_icon_cache()
    assert paths == icons.packaged_icon_fallback_paths()
    assert len(paths) == len(icons._ARROW_SPECS) == 14
    assert all(icons._png_status(Path(path)) == "valid" for path in paths.values())
    assert not list(cache_dir.glob("*.png"))


def test_unknown_qtawesome_icon_is_not_downgraded_to_a_packaged_fallback(
    qapp, tmp_path, monkeypatch
):
    """Only known font/resource faults are recoverable; bad icon names are bugs."""
    cache_dir = tmp_path / "empty-cache"
    monkeypatch.setattr(icons, "_icon_cache_dir", lambda: _cache_dir(cache_dir))
    placeholder = "ICON_UNKNOWN"
    packaged = next(iter(icons.packaged_icon_fallback_paths().values()))
    monkeypatch.setattr(
        icons,
        "_ARROW_SPECS",
        ((placeholder, "mdi6.this-icon-does-not-exist", "#475569"),),
    )
    monkeypatch.setattr(icons, "packaged_icon_fallback_paths", lambda: {placeholder: packaged})

    with pytest.raises(Exception, match="Invalid icon name"):
        icons.ensure_icon_cache()


def test_missing_packaged_fallback_is_a_release_resource_failure(qapp, monkeypatch):
    monkeypatch.setattr(icons, "_PACKAGED_FALLBACK_DIR", Path("/not-a-real-qss-icon-resource"))
    with pytest.raises(icons.IconFallbackResourceError, match="release-resource failure"):
        icons.ensure_icon_cache()
