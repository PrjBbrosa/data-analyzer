"""Shared DPR helper contracts (UV-A16 call-site uniqueness)."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtGui import QColor, QImage, QPixmap

from mf4_analyzer.ui.chart_stack._helpers import _pixmap_as_device_pixels
from mf4_analyzer.ui.image_utils import (
    pixmap_as_device_pixel_image,
    pixmap_as_device_pixels,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "mf4_analyzer" / "ui"
_CALL_SITES = (
    UI_ROOT / "chart_stack" / "_helpers.py",
    UI_ROOT / "analysis_section_page.py",
    UI_ROOT / "markup" / "editor.py",
)


def _pixmap(width: int, height: int, *, dpr: float = 1.0, color: str = "#cc0000") -> QPixmap:
    pix = QPixmap(width, height)
    pix.fill(QColor(color))
    pix.setDevicePixelRatio(dpr)
    return pix


def test_dpr_1_and_2_preserve_raw_width_and_height(qapp):
    for dpr, width, height in ((1.0, 120, 80), (2.0, 200, 100), (2.0, 8, 8)):
        pix = _pixmap(width, height, dpr=dpr)
        image = pixmap_as_device_pixel_image(pix)
        assert image is not None
        assert abs(image.devicePixelRatioF() - 1.0) < 1e-9
        assert image.width() == width
        assert image.height() == height
        wrapped = pixmap_as_device_pixels(pix)
        assert wrapped is not None
        assert abs(wrapped.devicePixelRatioF() - 1.0) < 1e-9
        assert wrapped.width() == width
        assert wrapped.height() == height


def test_qimage_input_is_normalized_to_premultiplied_32bit(qapp):
    source = QImage(40, 20, QImage.Format_RGB32)
    source.fill(QColor("#2244aa"))
    source.setDevicePixelRatio(2.0)
    image = pixmap_as_device_pixel_image(source)
    assert image is not None
    assert image.format() == QImage.Format_ARGB32_Premultiplied
    assert abs(image.devicePixelRatioF() - 1.0) < 1e-9
    assert image.width() == 40
    assert image.height() == 20


def test_none_and_null_return_none(qapp):
    assert pixmap_as_device_pixel_image(None) is None
    assert pixmap_as_device_pixels(None) is None
    assert pixmap_as_device_pixel_image(QPixmap()) is None
    assert pixmap_as_device_pixels(QPixmap()) is None
    assert pixmap_as_device_pixel_image(QImage()) is None


def test_small_images_are_not_rejected_by_helper(qapp):
    for width, height in ((1, 1), (7, 100), (100, 7)):
        image = pixmap_as_device_pixel_image(_pixmap(width, height))
        assert image is not None
        assert image.width() == width
        assert image.height() == height


def test_helpers_wrapper_preserves_none_and_null_identity(qapp):
    assert _pixmap_as_device_pixels(None) is None
    null = QPixmap()
    assert null.isNull()
    assert _pixmap_as_device_pixels(null) is null
    hidpi = _pixmap(80, 40, dpr=2.0)
    out = _pixmap_as_device_pixels(hidpi)
    assert out is not None
    assert abs(out.devicePixelRatioF() - 1.0) < 1e-9
    assert out.width() == 80
    assert out.height() == 40


def test_no_fourth_dpr_normalize_implementation():
    helper = (UI_ROOT / "image_utils.py").read_text(encoding="utf-8")
    assert "def pixmap_as_device_pixel_image" in helper
    assert "setDevicePixelRatio(1.0)" in helper

    for path in _CALL_SITES:
        text = path.read_text(encoding="utf-8")
        assert "setDevicePixelRatio(1.0)" not in text, path
        assert "pixmap_as_device_pixels" in text
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "setDevicePixelRatio"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and arg.value in (1, 1.0):
                raise AssertionError(f"{path} still normalizes DPR locally")
