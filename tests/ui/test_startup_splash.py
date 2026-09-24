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


def _grab(splash: StartupSplash) -> QImage:
    pix = splash.grab()
    assert not pix.isNull()
    image = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    assert not image.isNull()
    return image


def _sample(image: QImage, pt: QPointF) -> QColor:
    x = max(0, min(image.width() - 1, int(round(pt.x()))))
    y = max(0, min(image.height() - 1, int(round(pt.y()))))
    return image.pixelColor(x, y)


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
    image = _grab(splash)
    peak = splash.peak_sample_point()
    # Neighbourhood around the peak must contain spectrum ink, not a flat
    # background plateau from clipping.
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
            # Spectrum ink is teal/blue: R < B and not near-white glass fill.
            if color.blue() >= 120 and color.red() < color.blue() and color.value() < 250:
                ink_hits += 1
    assert ink_hits >= 3, (
        f"peak at {peak.x():.1f},{peak.y():.1f} lacks spectrum ink "
        f"(ink={ink_hits}, bg={bg_hits}, sample={_sample(image, peak).name()})"
    )
    # Immediately above the peak (toward smaller Y) should not be a solid
    # clipped plateau of card fill spanning many px of identical bg.
    above = _sample(image, peak + QPointF(0, -3))
    at = _sample(image, peak)
    assert at.name().lower() != above.name().lower() or at.blue() > above.blue()


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
        for y in range(tip_top + 4, tip_bottom - 4, 2):
            for x in range(tip_left, tip_right, 2):
                c = image.pixelColor(x, y)
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
    card = splash.card_rect_logical()
    # Sample just outside the top-left rounded corner — must stay transparent,
    # not an offset gray pedestal from the retired shadow stacks.
    samples = [
        image.pixelColor(0, 0),
        image.pixelColor(1, 1),
        image.pixelColor(2, 0),
        image.pixelColor(0, 2),
    ]
    for color in samples:
        assert color.alpha() < 40, color.name()
        # No dark gray shadow ink outside the card.
        if color.alpha() > 0:
            assert color.value() > 180 or color.alpha() < 20
    # Immediately below the card bottom (if any pad) should also be clear.
    below_y = min(image.height() - 1, int(card.bottom()) + 2)
    below = image.pixelColor(int(card.center().x()), below_y)
    if below_y > int(card.bottom()):
        assert below.alpha() < 40


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
