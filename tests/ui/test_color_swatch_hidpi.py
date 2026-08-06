"""Regression: channel-list + View-tab color swatches must render at the
screen's device pixel ratio.

On a Retina (2x) screen a 14x14 / 12x12 pixmap tagged with the default
devicePixelRatio of 1.0 gets upscaled 2x by Qt at paint time, which smears the
antialiased edge into the jagged/blurry dots the user reported. The fix renders
the buffer at ``ratio x`` physical pixels and tags it via setDevicePixelRatio so
Qt paints it crisp at the logical size.
"""
from PyQt5.QtGui import QPixmap

from mf4_analyzer.ui.widgets import _swatch_pixmap
from mf4_analyzer.ui.view_tabbar import _tab_color_pixmap


def test_swatch_pixmap_renders_at_2x_for_retina(qapp):
    pix = _swatch_pixmap("#ff7f0e", size=14, ratio=2.0)
    assert isinstance(pix, QPixmap)
    # Physical buffer is 2x so AA is computed at full Retina resolution.
    assert pix.width() == 28 and pix.height() == 28
    # Tagged 2x => Qt paints at the 14pt logical size without upscaling.
    assert pix.devicePixelRatioF() == 2.0


def test_swatch_pixmap_stays_1x_on_standard_dpi(qapp):
    pix = _swatch_pixmap("#ff7f0e", size=14, ratio=1.0)
    assert pix.width() == 14 and pix.height() == 14
    assert pix.devicePixelRatioF() == 1.0


def test_tab_color_pixmap_renders_at_2x_for_retina(qapp):
    pix = _tab_color_pixmap("#2d7ff9", ratio=2.0)
    assert pix.width() == 24 and pix.height() == 24
    assert pix.devicePixelRatioF() == 2.0


def test_tab_color_pixmap_invalid_color_still_renders_at_ratio(qapp):
    pix = _tab_color_pixmap("not-a-color", ratio=2.0)
    assert pix.width() == 24 and pix.devicePixelRatioF() == 2.0


def test_swatch_default_path_picks_up_device_ratio(qapp, monkeypatch):
    # ratio=None => read the live screen ratio via the shared helper.  The
    # helper must be patched on ``_swatches`` -- that is the module whose
    # globals ``_swatch_pixmap`` actually reads -- while the call still goes
    # through the ``ui.widgets`` re-export the rest of the app imports.
    import mf4_analyzer.ui.widgets as widgets_mod
    import mf4_analyzer.ui.widgets._swatches as swatches_mod
    monkeypatch.setattr(swatches_mod, "icon_device_pixel_ratio", lambda: 2.0)
    pix = widgets_mod._swatch_pixmap("#abcdef")  # default size, helper ratio
    assert pix.devicePixelRatioF() == 2.0
    assert pix.width() == round(11 * 2.0)  # default size is the compact 11


def test_swatch_default_size_is_compact(qapp):
    # Locks the smaller proportion: the swatch is an 11px logical chip, not the
    # original heavy 14px block.
    assert _swatch_pixmap("#abcdef", ratio=1.0).width() == 11


def test_markup_editor_icons_render_at_device_ratio(qapp, monkeypatch):
    import mf4_analyzer.ui.markup.editor as editor_mod
    monkeypatch.setattr(editor_mod, "icon_device_pixel_ratio", lambda: 2.0)
    # square color dot
    pix = editor_mod.MarkupEditor._icon_canvas(18, 18)
    assert (pix.width(), pix.height()) == (36, 36)
    assert pix.devicePixelRatioF() == 2.0
    # rectangular width/style icons keep their aspect at 2x
    wpix = editor_mod.MarkupEditor._icon_canvas(24, 18)
    assert (wpix.width(), wpix.height()) == (48, 36)
