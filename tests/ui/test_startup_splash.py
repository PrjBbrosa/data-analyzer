"""Focused tests for the independent B-view ``StartupSplash``.

Visual geometry and peak-pixel checks use offscreen ``grab()``; they do not
assert CSS/QSS color strings alone. No MainWindow construction.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QImage
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.app_meta import APP_CREDIT, APP_NAME, APP_VERSION
from mf4_analyzer.ui import startup_splash as splash_module
from mf4_analyzer.ui.startup_splash import (
    CARD_HEIGHT,
    CARD_WIDTH,
    DISPLAY_SCALE_COMPACT,
    DISPLAY_SCALE_LARGE,
    SHADOW_PAD,
    STAGE_LOADING_COMPONENTS,
    STAGE_PREPARING,
    STAGE_PREPARING_WORKSPACE,
    TIPS,
    StartupSplash,
    display_scale_for_work_area,
    spectrum_reference_bounds,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = REPO_ROOT / ".state" / "startup-splash"
SCREENSHOT_PATH = SCREENSHOT_DIR / "b-view.png"

# Sky-glass background samples that must NOT be the peak ink.
_BG_SAMPLES = {
    QColor("#f4faff").name().lower(),
    QColor("#ffffff").name().lower(),
}


@pytest.fixture
def splash_host(qtbot, qapp):
    """Own the splash under an explicit parent so teardown drains cleanly."""
    del qapp
    host = QWidget()
    host.setObjectName("startupSplashTestHost")
    qtbot.addWidget(host)
    splash = StartupSplash(host)
    qtbot.addWidget(splash)
    splash.set_reduced_motion(True)  # deterministic for geometry tests
    splash.show()
    qtbot.waitExposed(splash)
    host.show()
    yield splash, host
    splash.close_splash()


def _image_pixels_per_logical(image: QImage) -> float:
    """Device pixels per widget-logical pixel stored on this image."""
    ratio = float(image.devicePixelRatio() or 0.0)
    return ratio if ratio > 0.0 else 1.0


def _grab(splash: StartupSplash) -> QImage:
    pix = splash.grab()
    assert not pix.isNull()
    ratio = float(pix.devicePixelRatio() or 1.0)
    if ratio <= 0.0:
        ratio = 1.0
    image = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    assert not image.isNull()
    # convertToFormat can drop the pixmap ratio while width stays in device pixels.
    if abs(float(image.devicePixelRatio() or 0.0) - ratio) > 1e-4:
        image.setDevicePixelRatio(ratio)
    return image


def _sample(image: QImage, pt: QPointF) -> QColor:
    """Map a widget-logical point onto this image, then read that device pixel.

    A paint buffer created at ``splash.size()`` has ratio 1, so the mapping
    stays 1:1. A ``grab()`` image uses its own ratio. Callers that want the
    physical corner of the image pass raw ``pixelColor`` indexes instead.
    """
    scale = _image_pixels_per_logical(image)
    x = int(round(float(pt.x()) * scale))
    y = int(round(float(pt.y()) * scale))
    x = max(0, min(image.width() - 1, x))
    y = max(0, min(image.height() - 1, y))
    return image.pixelColor(x, y)


def _assert_peak_spectrum_ink(splash: StartupSplash, image: QImage) -> None:
    """Peak neighborhood is widget-logical; ``_sample`` converts to image pixels."""
    peak = splash.peak_sample_point()
    ink_hits = 0
    bg_hits = 0
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            color = _sample(image, peak + QPointF(dx, dy))
            if color.alpha() < 20:
                continue
            name = color.name().lower()
            if name in _BG_SAMPLES:
                bg_hits += 1
                continue
            if color.blue() >= 120 and color.red() < color.blue() and color.value() < 250:
                ink_hits += 1
    assert ink_hits >= 3, (
        f"peak at {peak.x():.1f},{peak.y():.1f} lacks spectrum ink "
        f"(ink={ink_hits}, bg={bg_hits}, sample={_sample(image, peak).name()}, "
        f"image={image.width()}x{image.height()} dpr={_image_pixels_per_logical(image):.3f})"
    )
    above = _sample(image, peak + QPointF(0, -3))
    at = _sample(image, peak)
    assert at.name().lower() != above.name().lower() or at.blue() > above.blue()


def _assert_outer_shadow_clear(image: QImage, card) -> None:
    """Corners are raw image pixels. The sample below the card is logical, scaled.

    Alpha below 40 is the existing edge antialias fringe and is not widened.
    """
    samples = [
        image.pixelColor(0, 0),
        image.pixelColor(1, 1),
        image.pixelColor(2, 0),
        image.pixelColor(0, 2),
    ]
    for color in samples:
        assert color.alpha() < 40, color.name()
        if color.alpha() > 0:
            assert color.value() > 180 or color.alpha() < 20
    scale = _image_pixels_per_logical(image)
    edge_y = int(round(float(card.bottom()) * scale))
    below_y = min(image.height() - 1, edge_y + 2)
    below_x = int(round(float(card.center().x()) * scale))
    below_x = max(0, min(image.width() - 1, below_x))
    below = image.pixelColor(below_x, below_y)
    if below_y > edge_y:
        assert below.alpha() < 40


def test_spectrum_does_not_add_a_rectangular_blue_backing(splash_host):
    """The HTML has only spectrum strokes, not a second tinted rectangle."""
    from PyQt5.QtGui import QPainter

    splash, _ = splash_host
    image = QImage(splash.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    splash._paint_spectrum(painter)
    painter.end()
    rect = splash._spectrum_rect()
    # Below the wave paths and above captions: no graph or text ink here.
    point = QPointF(rect.center().x(), rect.bottom() - splash._s(28))
    assert _sample(image, point).alpha() == 0


def test_card_starts_with_neutral_white_not_uniform_blue(splash_host):
    from PyQt5.QtGui import QPainter

    splash, _ = splash_host
    image = QImage(splash.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    splash._paint_card(painter, splash._card_rect())
    painter.end()
    color = _sample(image, QPointF(splash.width() * .1, splash.height() * .15))
    assert color.red() >= 250
    assert color.blue() - color.red() <= 5


def test_stage_copy_and_right_label(splash_host):
    splash, _host = splash_host
    assert splash.status_text() == "正在启动 TraceLab…"
    splash.set_stage(STAGE_LOADING_COMPONENTS)
    assert splash.status_text() == "正在加载分析组件…"
    splash.set_stage(STAGE_PREPARING_WORKSPACE)
    assert splash.status_text() == "正在准备工作区…"
    splash.set_slow(True)
    assert splash.status_text() == "启动比平时久一些，请稍候…"
    # Remembered stage stays; never "已就绪".
    splash.set_slow(False)
    assert splash.status_text() == "正在准备工作区…"
    assert "已就绪" not in splash.status_text()


def test_opening_tip_is_chosen_at_random(qtbot, monkeypatch):
    """Each splash picks one tip up front instead of always starting at 0."""
    monkeypatch.setattr(
        "mf4_analyzer.ui.startup_splash.random.randrange",
        lambda stop: 3 if stop == len(TIPS) else 0,
    )
    host = QWidget()
    host.setObjectName("startupSplashRandomTipHost")
    qtbot.addWidget(host)
    splash = StartupSplash(host)
    qtbot.addWidget(splash)
    assert splash.tip_index == 3


def test_injected_tip_and_clock_do_not_reroll_on_stage_or_redraw(qtbot):
    elapsed = {"ms": 0.0}
    host = QWidget()
    qtbot.addWidget(host)
    splash = StartupSplash(
        host,
        initial_tip_id="tip-01",
        elapsed_ms=lambda: elapsed["ms"],
    )
    qtbot.addWidget(splash)
    assert splash.tip_index == 0
    splash.set_stage(STAGE_PREPARING_WORKSPACE)
    splash.resize(640, 470)
    splash._on_tick()
    assert splash.tip_index == 0
    elapsed["ms"] = 4999
    splash._on_tick()
    assert splash.tip_index == 0
    assert splash.status_text() == "正在准备工作区…"
    elapsed["ms"] = 5000
    splash._on_tick()
    assert splash.tip_index == 1
    elapsed["ms"] = 10000
    splash._on_tick()
    assert splash.tip_index == 2
    elapsed["ms"] = 12000
    splash._on_tick()
    assert splash.tip_index == 2
    assert splash.status_text() == "启动比平时久一些，请稍候…"
    with pytest.raises(ValueError):
        StartupSplash(host, initial_tip_id="tip-missing")


def test_meta_and_tips_match_contract():
    assert APP_NAME == "TraceLab"
    assert APP_VERSION.startswith("v")
    assert APP_CREDIT
    assert len(TIPS) >= 20
    assert TIPS[0][0] == "找回全局视野"
    assert "Home" in TIPS[0][1]
    titles = {title for title, _body in TIPS}
    assert {"操作速查", "阶次看转速", "一次处理多文件", "固定读数"} <= titles
    assert any("电机转速" in body for _title, body in TIPS)


def test_every_tip_fits_the_compact_card(qapp):
    """Bodies stay inside the 1× tip band, including on a 1080p desktop."""
    del qapp
    from PyQt5.QtCore import Qt

    from mf4_analyzer.qt_panel_style import (
        FONT_ROLE_BODY,
        FONT_ROLE_TITLE,
        panel_font_metrics,
    )

    scale = 1.0

    def _s(value: float) -> float:
        return value * scale

    content_w = (CARD_WIDTH - 64) * scale
    dots_w = 0.0
    for index in range(len(TIPS)):
        dots_w += _s(12.0 if index == 0 else 4.0)
        if index:
            dots_w += _s(4.0)
    title_budget = content_w - _s(18.0) - dots_w - _s(10.0)
    heading_px = max(8, int(round(_s(10.0))))
    body_px = max(9, int(round(_s(12.0))))
    heading = panel_font_metrics(FONT_ROLE_TITLE, pixel_size=heading_px, bold=True)
    body_metrics = panel_font_metrics(FONT_ROLE_BODY, pixel_size=body_px)
    body_h = _s(92.0) - _s(17.0 + 8.0 + 14.0) - _s(10.0)
    assert title_budget > 80
    for title, body in TIPS:
        assert heading.horizontalAdvance(title) <= title_budget + 1, title
        rect = body_metrics.boundingRect(
            0,
            0,
            int(content_w),
            4000,
            int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop),
            body,
        )
        assert rect.height() <= body_h + 1, (title, rect.height(), body_h)


def test_spectrum_reference_y_in_svg_band():
    _xmin, ymin, _xmax, ymax = spectrum_reference_bounds()
    assert ymin >= 15.0 - 1e-6
    assert ymax <= 15.0 + 132.0 + 1e-6


def test_path_stroke_bounds_inside_spectrum(splash_host):
    splash, _host = splash_host
    rect = splash.spectrum_draw_rect()
    paths = splash.spectrum_paths_widget()
    widths = splash.spectrum_stroke_widths_widget()
    assert len(paths) == 16
    assert len(widths) == 16
    for path, width in zip(paths, widths):
        half = width * 0.5
        for i in range(path.elementCount()):
            el = path.elementAt(i)
            assert rect.left() - 0.5 <= el.x - half
            assert el.x + half <= rect.right() + 0.5
            assert rect.top() - 0.5 <= el.y - half
            assert el.y + half <= rect.bottom() + 0.5


def test_peak_pixel_is_not_clipped_flat(splash_host):
    splash, _host = splash_host
    _assert_peak_spectrum_ink(splash, _grab(splash))


def test_all_tips_fit_in_tip_band(splash_host, qtbot):
    splash, _host = splash_host
    card = splash.card_rect_logical()
    for index, (title, body) in enumerate(TIPS):
        splash._tip_index = index
        splash.update()
        qtbot.wait(16)
        image = _grab(splash)
        # Tip band is the lower card region above credit (~33 logical).
        tip_bottom = int(card.bottom() - 33 * splash._scale)
        tip_top = int(tip_bottom - 92 * splash._scale)
        tip_left = int(card.left() + 32 * splash._scale)
        tip_right = int(card.right() - 32 * splash._scale)
        assert tip_top >= int(card.top())
        # Non-transparent ink must exist inside the tip band (title/body).
        # Stride is in widget pixels. A step of 8 was tuned for the enlarged
        # card and misses the compact 1.0 glyphs.
        ink = 0
        # ``tip_*`` is widget-logical. Step 2 logical px, then convert.
        for y in range(tip_top + 4, tip_bottom - 4, 2):
            for x in range(tip_left, tip_right, 2):
                c = _sample(image, QPointF(x, y))
                if c.alpha() < 30:
                    continue
                # Tip title/body are darker blue-greys.
                if c.red() < 120 and c.blue() < 160 and c.value() < 140:
                    ink += 1
        assert ink >= 8, f"tip {index} ({title!r}) left too little ink in band"
        # Body string must be representable without expanding the card.
        assert splash.height() >= int(CARD_HEIGHT * 0.85)
        assert body


def test_font_change_rebuilds_paths_once(splash_host, qtbot):
    splash, _host = splash_host
    before = splash.path_build_count
    font = QFont(splash.font())
    font.setPointSize(font.pointSize() + 1 if font.pointSize() > 0 else 13)
    splash.setFont(font)
    qtbot.wait(20)
    splash.update()
    qtbot.wait(20)
    assert splash.path_build_count >= before + 1


def test_animation_ticks_do_not_rebuild_paths(splash_host, qtbot):
    splash, _host = splash_host
    splash.set_reduced_motion(False)
    splash.show()
    qtbot.waitExposed(splash)
    # Force a known baseline after show/layout.
    splash._rebuild_paths_if_needed(force=True)
    baseline = splash.path_build_count
    for _ in range(12):
        splash._on_tick()
    assert splash.path_build_count == baseline


def test_close_stops_timer_and_blocks_callbacks(splash_host, qtbot):
    splash, _host = splash_host
    splash.set_reduced_motion(False)
    splash.show()
    qtbot.waitExposed(splash)
    assert splash._timer.isActive()
    calls = {"n": 0}
    original = splash._on_tick

    def counting_tick():
        calls["n"] += 1
        original()

    splash._timer.timeout.disconnect(splash._on_tick)
    splash._timer.timeout.connect(counting_tick)
    splash.close_splash()
    assert splash.is_splash_closed
    assert not splash._timer.isActive()
    before = calls["n"]
    # Emitting after close must not reach the handler (disconnected).
    splash._timer.timeout.emit()
    assert calls["n"] == before
    # Direct guard: closed splash ignores tick.
    tip_before = splash.tip_index
    splash._on_tick()
    assert splash.tip_index == tip_before


def test_splash_remembers_the_screen_it_was_centered_on(splash_host):
    splash, _host = splash_host
    screen = splash._target_screen()
    assert screen is not None
    avail = screen.availableGeometry()
    assert splash.launch_screen_rect() == (
        avail.x(),
        avail.y(),
        avail.width(),
        avail.height(),
    )


def test_panel_scale_follows_the_work_area_without_changing_ratio(splash_host):
    splash, _host = splash_host
    card = splash.card_rect_logical()
    assert abs(card.width() / card.height() - CARD_WIDTH / CARD_HEIGHT) < 0.02
    screen = splash._target_screen()
    assert screen is not None
    avail = screen.availableGeometry()
    expected = display_scale_for_work_area(avail.width(), avail.height())
    assert abs(splash._scale - expected) < 0.02
    assert splash.width() <= avail.width()
    assert splash.height() <= avail.height()


def test_large_logical_desktop_uses_one_and_a_half_and_1080p_uses_one():
    """5K Mac default points stay at 1.5; a 1080p work area stays at 1.0."""
    # Full 2560×1440 and the same desktop after a menu bar + dock.
    assert display_scale_for_work_area(2560, 1440) == DISPLAY_SCALE_LARGE
    assert display_scale_for_work_area(2560, 1320) == DISPLAY_SCALE_LARGE
    # 1080p at 100% and at 150% (logical 1280×720), with and without a taskbar.
    assert display_scale_for_work_area(1920, 1080) == DISPLAY_SCALE_COMPACT
    assert display_scale_for_work_area(1920, 1032) == DISPLAY_SCALE_COMPACT
    assert display_scale_for_work_area(1280, 720) == DISPLAY_SCALE_COMPACT
    assert display_scale_for_work_area(1280, 672) == DISPLAY_SCALE_COMPACT


def test_compact_card_shrinks_only_when_the_work_area_cannot_hold_it():
    scale = display_scale_for_work_area(700, 480)
    assert scale < DISPLAY_SCALE_COMPACT
    assert (CARD_WIDTH + 2 * SHADOW_PAD) * scale <= 700 - 24
    assert (CARD_HEIGHT + 2 * SHADOW_PAD) * scale <= 480 - 24


def test_card_logical_width_and_frameless(splash_host):
    splash, _host = splash_host
    card = splash.card_rect_logical()
    assert abs(card.width() / max(splash._scale, 1e-6) - CARD_WIDTH) < 1.0
    assert card.height() / max(splash._scale, 1e-6) >= CARD_HEIGHT * 0.9
    flags = splash.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert splash.testAttribute(Qt.WA_TranslucentBackground)


def test_screenshot_saved_and_geometry_asserted(splash_host):
    splash, _host = splash_host
    splash.set_stage(STAGE_PREPARING)
    splash.set_reduced_motion(True)
    splash.update()
    image = _grab(splash)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    assert image.save(str(SCREENSHOT_PATH), "PNG")
    assert SCREENSHOT_PATH.is_file()
    assert SCREENSHOT_PATH.stat().st_size > 1000

    # Geometry: card region is sky-glass blue-white, not pure white; AA corners
    # outside the rounded card stay transparent (frameless shell).
    card = splash.card_rect_logical()
    centre = _sample(image, card.center())
    assert centre.name().lower() != "#ffffff"
    assert centre.red() > 180 and centre.blue() > 200

    # Image-pixel corner, not a widget-logical point. One opaque device
    # pixel fails. Alpha < 40 is the existing antialias fringe, not widened.
    corner = image.pixelColor(1, 1)
    assert corner.alpha() < 40

    peak = splash.peak_sample_point()
    peak_color = _sample(image, peak)
    assert peak_color.name().lower() not in _BG_SAMPLES
    assert peak_color.blue() > peak_color.red()


def test_no_self_painted_outer_shadow(splash_host):
    """Outer drop-shadow layers are removed; shell pixels outside the card stay clear."""
    splash, _host = splash_host
    image = _grab(splash)
    _assert_outer_shadow_clear(image, splash.card_rect_logical())


def test_windows_splash_keeps_the_rounded_shell_without_dwm_backdrop(
    splash_host, monkeypatch, qtbot
):
    splash, _host = splash_host
    monkeypatch.setattr(splash_module.platform, "system", lambda: "Windows")

    def unexpected_backdrop(*_args, **_kwargs):
        pytest.fail("Windows DWM backdrop would fill the rectangular shell corners")

    monkeypatch.setattr(splash_module, "apply_native_panel_surface", unexpected_backdrop)
    splash.hide()
    splash.show()
    qtbot.waitExposed(splash)
    splash._apply_panel_surface(force=True)


def test_card_has_an_inner_highlight_and_lighter_lower_left(splash_host):
    from PyQt5.QtGui import QPainter

    splash, _host = splash_host
    image = QImage(splash.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    splash._paint_card(painter, splash.card_rect_logical())
    painter.end()

    x = image.width() // 2
    top_rim = image.pixelColor(x, 1)
    top_inner = image.pixelColor(x, 16)
    assert top_rim.red() >= top_inner.red() + 3

    bottom_rim = image.pixelColor(x, image.height() - 2)
    bottom_inner = image.pixelColor(x, image.height() - 16)
    assert bottom_rim.red() <= bottom_inner.red() - 3

    lower_left = image.pixelColor(int(image.width() * .13), int(image.height() * .75))
    assert lower_left.red() >= 240


def test_invalid_stage_rejected(splash_host):
    splash, _host = splash_host
    with pytest.raises(ValueError):
        splash.set_stage("ready")


def test_module_avoids_forbidden_imports():
    """Static guard: startup_splash must stay free of heavy UI deps."""
    import ast

    src = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui" / "startup_splash.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "mf4_analyzer.ui.widgets",
        "mf4_analyzer.ui_kit",
        "mf4_analyzer.ui.main_window",
        "pyqtgraph",
        "numpy",
        "pandas",
    )
    for name in imported:
        for prefix in forbidden:
            assert name != prefix and not name.startswith(prefix + "."), name
    # Lightweight panel helper is allowed.
    assert any(
        name == "mf4_analyzer.qt_panel_style" or name.startswith("mf4_analyzer.qt_panel_style.")
        for name in imported
    )


def _tick_at(splash: StartupSplash, now_ms: float) -> None:
    splash._last_tick_ms = 0.0
    splash._elapsed_ms = lambda: now_ms
    splash._on_tick()


def test_detect_system_reduced_motion_darwin_windows_and_failure(monkeypatch):
    import platform
    import subprocess
    import sys

    from mf4_analyzer.ui.startup_splash import detect_system_reduced_motion

    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def fake_defaults(args, **_kwargs):
        assert args == ["defaults", "read", "com.apple.universalaccess", "reduceMotion"]
        return fake_defaults.value

    fake_defaults.value = "1\n"
    monkeypatch.setattr(subprocess, "check_output", fake_defaults)
    assert detect_system_reduced_motion() is True
    fake_defaults.value = "true\n"
    assert detect_system_reduced_motion() is True
    fake_defaults.value = "0\n"
    assert detect_system_reduced_motion() is False

    def failed(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "defaults")

    monkeypatch.setattr(subprocess, "check_output", failed)
    assert detect_system_reduced_motion() is False

    class _Int:
        def __init__(self, value: int) -> None:
            self.value = value

    class _User32:
        ok = 1
        animation = 0

        @staticmethod
        def SystemParametersInfoW(action, _param, value, _flags):
            assert action == 0x1042
            if _User32.ok == 0:
                return 0
            value.value = _User32.animation
            return 1

    class _Ctypes:
        c_int = _Int
        windll = type("windll", (), {"user32": _User32})

        @staticmethod
        def byref(obj):
            return obj

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "ctypes", _Ctypes)
    _User32.animation = 0
    _User32.ok = 1
    assert detect_system_reduced_motion() is True
    _User32.animation = 1
    assert detect_system_reduced_motion() is False
    _User32.ok = 0
    assert detect_system_reduced_motion() is False

    def spi_failed(*_args, **_kwargs):
        raise OSError("spi unavailable")

    monkeypatch.setattr(_User32, "SystemParametersInfoW", staticmethod(spi_failed))
    assert detect_system_reduced_motion() is False


def test_macos_auto_gate_stays_off_until_splash_is_explicit(monkeypatch):
    from mf4_analyzer.startup_feedback import ENV_SPLASH, splash_enabled

    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv(ENV_SPLASH, "auto")
    assert splash_enabled(hidden=False, layout_probe=False, platform="darwin") is False
    monkeypatch.setenv(ENV_SPLASH, "0")
    assert splash_enabled(hidden=False, layout_probe=False, platform="darwin") is False
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is False
    monkeypatch.setenv(ENV_SPLASH, "1")
    assert splash_enabled(hidden=False, layout_probe=False, platform="darwin") is True
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is True


def test_explicit_reduced_motion_freezes_phases_and_keeps_stage_text(qtbot, monkeypatch):
    from mf4_analyzer.startup_visual_contract import FRAME_INTERVAL_MS, STAGE_LABELS

    monkeypatch.setattr(splash_module, "detect_system_reduced_motion", lambda: False)
    splash = StartupSplash()
    qtbot.addWidget(splash)
    assert splash._reduced_motion is False
    splash.set_reduced_motion(True)
    splash.show()
    qtbot.waitExposed(splash)
    try:
        assert splash._timer.isActive()
        assert splash._timer.interval() == FRAME_INTERVAL_MS
        splash.set_stage(STAGE_PREPARING)
        assert splash.status_text() == STAGE_LABELS[STAGE_PREPARING]
        splash.set_stage(STAGE_LOADING_COMPONENTS)
        assert splash.status_text() == STAGE_LABELS[STAGE_LOADING_COMPONENTS]
        _tick_at(splash, 200.0)
        assert splash._breathe_phase == 0.0
        assert splash._rail_phase == 0.0
        assert splash._spinner_phase == 0.0
        assert splash._timer.isActive()
        splash.set_reduced_motion(False)
        _tick_at(splash, 200.0)
        assert splash._spinner_phase > 0.0
        assert splash._breathe_phase > 0.0
        assert splash.status_text() == STAGE_LABELS[STAGE_LOADING_COMPONENTS]
    finally:
        splash.close_splash()


def test_detector_failure_plays_motion_until_explicit_reduce(qtbot, monkeypatch):
    import subprocess

    from mf4_analyzer.startup_visual_contract import STAGE_LABELS

    monkeypatch.setattr(splash_module.platform, "system", lambda: "Darwin")

    def failed(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "defaults")

    monkeypatch.setattr(splash_module.subprocess, "check_output", failed)
    splash = StartupSplash()
    qtbot.addWidget(splash)
    assert splash._reduced_motion is False
    splash.show()
    qtbot.waitExposed(splash)
    try:
        _tick_at(splash, 200.0)
        assert splash._spinner_phase > 0.0
        splash.set_reduced_motion(True)
        assert splash._breathe_phase == 0.0
        assert splash._spinner_phase == 0.0
        _tick_at(splash, 400.0)
        assert splash._spinner_phase == 0.0
        splash.set_stage(STAGE_PREPARING_WORKSPACE)
        assert splash.status_text() == STAGE_LABELS[STAGE_PREPARING_WORKSPACE]
        assert splash._timer.isActive()
    finally:
        splash.close_splash()


def run_dpr_pixel_probe() -> int:
    """Fresh-process peak and shadow check. DPI env is already set by the parent.

    Returns 0 when the requested scale was applied and the pixels match,
    2 when this platform did not apply ``QT_SCALE_FACTOR`` (caller skips),
    and raises when the pixels themselves regress.
    """
    import os

    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.qt_app_support import configure_high_dpi

    if QApplication.instance() is not None:
        print("UNSUPPORTED: QApplication existed before DPI attributes")
        return 2
    configure_high_dpi()
    app = QApplication([])
    requested = float(os.environ.get("QT_SCALE_FACTOR", "1") or "1")
    splash = StartupSplash()
    splash.set_reduced_motion(True)
    splash.show()
    app.processEvents()
    try:
        image = _grab(splash)
        widget_dpr = float(splash.devicePixelRatioF() or 0.0)
        image_dpr = _image_pixels_per_logical(image)
        print(
            "dpr_probe "
            f"requested={requested:.4f} widget_dpr={widget_dpr:.4f} "
            f"image_dpr={image_dpr:.4f} widget_w={splash.width()} "
            f"image_w={image.width()} image_h={image.height()}"
        )
        applied = abs(widget_dpr - requested) <= 0.08 or abs(image_dpr - requested) <= 0.08
        if not applied:
            print("UNSUPPORTED: platform did not apply QT_SCALE_FACTOR")
            return 2
        expected_w = int(round(splash.width() * image_dpr))
        assert abs(image.width() - expected_w) <= 1, (
            f"image width {image.width()} != widget {splash.width()} * dpr {image_dpr:.4f}"
        )
        _assert_peak_spectrum_ink(splash, image)
        _assert_outer_shadow_clear(image, splash.card_rect_logical())
    finally:
        splash.close_splash()
        app.processEvents()
    return 0


@pytest.mark.parametrize("scale", ["1", "2", "1.5"])
def test_peak_and_shadow_pixels_follow_image_dpr(scale):
    """Each scale is a new process so Qt DPI attributes exist before QApplication."""
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["QT_SCALE_FACTOR"] = scale
    env["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    env["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MPLCONFIGDIR"] = "/tmp"
    env["TMPDIR"] = "/tmp"
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.pop("QT_SCREEN_SCALE_FACTORS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.ui.test_startup_splash import run_dpr_pixel_probe; "
            "raise SystemExit(run_dpr_pixel_probe())",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    detail = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 2:
        pytest.skip(detail.strip() or f"DPR scale {scale} unsupported")
    assert result.returncode == 0, detail
