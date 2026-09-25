"""Independent B-view startup splash: 「晴空蓝白」.

Display-only widget. No MainWindow / ui_kit / pyqtgraph / widgets imports.
Controller / child-process wiring lives elsewhere (Task 2+).
May import the lightweight ``mf4_analyzer.qt_panel_style`` helper (no numpy).
"""
from __future__ import annotations

import math
import platform
import random
import subprocess
from typing import Callable, Optional, Sequence, Tuple

from PyQt5.QtCore import (
    QElapsedTimer,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.app_meta import APP_CREDIT, APP_NAME, APP_VERSION, asset_path
from mf4_analyzer.startup_visual_contract import (
    BREATHE_PERIOD_MS as _BREATHE_PERIOD_MS,
    CARD_HEIGHT,
    CARD_WIDTH,
    CONTENT_PAD_X,
    CORNER_RADIUS,
    CREDIT_BG_RGBA,
    CREDIT_FG_HEX,
    CREDIT_LEFT as _CREDIT_LEFT,
    DISPLAY_SCALE_COMPACT,
    DISPLAY_SCALE_LARGE,
    FRAME_INTERVAL_MS as _FPS_INTERVAL_MS,
    MAX_STROKE_REF as _MAX_STROKE_REF,
    MODE_CAPTIONS as _MODE_CAPTIONS,
    RAIL_FRACTION as _RAIL_FRACTION,
    RAIL_PERIOD_MS as _RAIL_PERIOD_MS,
    RAIL_TRACK_RGBA,
    RIGHT_LABEL as _RIGHT_LABEL,
    SHADOW_PAD,
    SLOW_AFTER_MS as _SLOW_AFTER_MS,
    SLOW_STATUS as _SLOW_STATUS,
    SPECTRUM_LAYERS as _SPECTRUM_LAYERS,
    SPECTRUM_REF_H,
    SPECTRUM_REF_W,
    SPINNER_TRACK_RGBA,
    STAGE_LABELS as _STAGE_LABELS,
    STAGE_LOADING_COMPONENTS,
    STAGE_PREPARING,
    STAGE_PREPARING_WORKSPACE,
    TIP_BORDER_RGBA,
    TIP_INTERVAL_MS as _TIP_INTERVAL_MS,
    TIP_WASH_RGBA,
    TIPS,
    CAPTION_DOT_HEX,
    choose_opening_index,
    display_scale_for_work_area,
    spectrum_reference_bounds,
    status_label,
    tip_by_id,
    tip_index_for_elapsed,
)
from mf4_analyzer.qt_panel_style import (
    FONT_ROLE_BODY,
    FONT_ROLE_CAPTION,
    FONT_ROLE_CREDIT,
    FONT_ROLE_EMPHASIS,
    FONT_ROLE_TITLE,
    FONT_ROLE_WORDMARK,
    apply_native_panel_surface,
    paint_panel_fill,
    panel_color,
    panel_font,
    panel_font_metrics,
    release_native_panel_surface,
    spectrum_stop_colors,
    uses_opaque_fallback,
)

# Stage copy, geometry, tips, and spectrum points live in
# startup_visual_contract. Names below stay as the splash's public aliases.

_VALID_STAGES = frozenset(
    {STAGE_PREPARING, STAGE_LOADING_COMPONENTS, STAGE_PREPARING_WORKSPACE}
)
_INK = panel_color("ink")
_SECONDARY = panel_color("secondary")
_ACCENT = panel_color("accent")
_TIP_TITLE = panel_color("tip_title")
_TIP_BODY = panel_color("tip_body")
_CAPTION_FG = panel_color("secondary")
_TIP_BG = QColor(*TIP_WASH_RGBA)
_TIP_BORDER = QColor(*TIP_BORDER_RGBA)
_CREDIT_BG = QColor(*CREDIT_BG_RGBA)
_CREDIT_FG = QColor(CREDIT_FG_HEX)
_RAIL_TRACK = QColor(*RAIL_TRACK_RGBA)
_CAPTION_DOT = QColor(CAPTION_DOT_HEX)
_SPINNER_TRACK = QColor(*SPINNER_TRACK_RGBA)
_SPECTRUM_STOPS = tuple(
    (stop, color)
    for stop, color in zip((0.0, 0.4, 0.67, 1.0), spectrum_stop_colors())
)


def detect_system_reduced_motion() -> bool:
    """Best-effort read of the OS reduce-motion preference."""
    system = platform.system()
    if system == "Darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5,
            )
            return out.strip().lower() in {"1", "true", "yes"}
        except (OSError, subprocess.SubprocessError):
            return False
    if system == "Windows":
        try:
            import ctypes

            # SPI_GETCLIENTAREAANIMATION — when False, treat as reduced motion.
            value = ctypes.c_int(1)
            ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
                0x1042, 0, ctypes.byref(value), 0
            )
            if ok:
                return not bool(value.value)
        except (AttributeError, OSError, ValueError):
            return False
    return False


def _load_brand_pixmap(logical_size: int, dpr: float) -> QPixmap:
    """Pick the nearest bundled PNG and scale for the current DPR."""
    target_px = max(1, int(round(logical_size * max(dpr, 1.0))))
    candidates = (16, 32, 48, 64, 128, 256, 512, 1024)
    best = min(candidates, key=lambda s: abs(s - target_px))
    path = asset_path("icons", f"tracelab_{best}.png")
    image = QImage(str(path))
    if image.isNull():
        return QPixmap()
    scaled = image.scaled(
        target_px,
        target_px,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    pix = QPixmap.fromImage(scaled)
    pix.setDevicePixelRatio(max(dpr, 1.0))
    return pix


class StartupSplash(QWidget):
    """Frameless B-view splash: brand, spectrum, status, tips, credit."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        initial_tip_id: Optional[str] = None,
        elapsed_ms: Optional[Callable[[], float]] = None,
    ) -> None:
        if initial_tip_id is not None:
            opening_index = tip_by_id(initial_tip_id).index
        elif TIPS:
            opening_index = choose_opening_index(random.randrange)
        else:
            opening_index = 0
        super().__init__(parent)
        self.setObjectName("startupSplash")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)

        self._stage = STAGE_PREPARING
        self._slow = False
        self._reduced_motion = detect_system_reduced_motion()
        self._closed = False
        self._opening_index = opening_index
        self._tip_index = opening_index
        self._elapsed_ms = elapsed_ms
        self._breathe_phase = 0.0
        self._rail_phase = 0.0
        self._spinner_phase = 0.0
        self._scale = DISPLAY_SCALE_COMPACT
        self._launch_screen_rect: Optional[Tuple[int, int, int, int]] = None
        self._path_build_count = 0
        self._cached_paths: list[QPainterPath] = []
        self._cached_path_key: Optional[Tuple[float, float, float, float, float]] = None
        self._brand_pix = QPixmap()
        self._brand_key: Optional[Tuple[int, float]] = None

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_tick_ms = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(_FPS_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        self._apply_preferred_size()
        self._ensure_brand_pixmap()
        self._rebuild_paths_if_needed()

    # --- Public API ---------------------------------------------------------

    def set_stage(self, stage: str) -> None:
        if stage not in _VALID_STAGES:
            raise ValueError(f"unknown splash stage: {stage!r}")
        if self._closed:
            return
        self._stage = stage
        self.update()

    def set_slow(self, slow: bool) -> None:
        if self._closed:
            return
        self._slow = bool(slow)
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        if self._closed:
            return
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._breathe_phase = 0.0
            self._rail_phase = 0.0
            self._spinner_phase = 0.0
        self.update()

    def close_splash(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._timer.isActive():
            self._timer.stop()
        try:
            self._timer.timeout.disconnect()
        except TypeError:
            pass
        release_native_panel_surface(self)
        self.hide()
        self.close()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self._closed:
            return
        # Readable on first show — no fade-in wait.
        self._apply_preferred_size()
        self._center_on_screen()
        # Use native glass where its window bounds match our rounded surface.
        # Windows uses the opaque, self-painted path for clean corners.
        self.setProperty("panelCornerRadius", self._s(CORNER_RADIUS))
        self._apply_panel_surface()
        if not self._timer.isActive() and not self._reduced_motion:
            self._last_tick_ms = self._now_ms()
            self._timer.start()
        elif self._reduced_motion and self._timer.isActive():
            self._timer.stop()
        # Tip rotation still needs a slow timer even in reduced motion.
        if self._reduced_motion and not self._timer.isActive():
            self._last_tick_ms = self._now_ms()
            self._timer.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.close_splash()
        super().closeEvent(event)

    # --- Test / inspection helpers (not part of the frozen product API) -----

    @property
    def path_build_count(self) -> int:
        return self._path_build_count

    @property
    def tip_index(self) -> int:
        return self._tip_index

    @property
    def is_splash_closed(self) -> bool:
        return self._closed

    def _now_ms(self) -> float:
        if self._elapsed_ms is not None:
            return float(self._elapsed_ms())
        return float(self._clock.elapsed())

    def status_text(self) -> str:
        return status_label(self._stage, self._now_ms(), slow=self._slow)

    def card_rect_logical(self) -> QRectF:
        return self._card_rect()

    def spectrum_draw_rect(self) -> QRectF:
        return self._spectrum_rect()

    def spectrum_paths_widget(self) -> Sequence[QPainterPath]:
        self._rebuild_paths_if_needed()
        return tuple(self._cached_paths)

    def spectrum_stroke_widths_widget(self) -> Tuple[float, ...]:
        scale = self._spectrum_map_scale()
        return tuple(layer.stroke_width * scale for layer in _SPECTRUM_LAYERS)

    def peak_sample_point(self) -> QPointF:
        """Widget-space sample of the highest peak (minimum Y) across layers."""
        paths = self.spectrum_paths_widget()
        best: Optional[QPointF] = None
        best_y = float("inf")
        for path in paths:
            for i in range(path.elementCount()):
                el = path.elementAt(i)
                if el.y < best_y:
                    best_y = el.y
                    best = QPointF(el.x, el.y)
        assert best is not None
        return best

    # --- Geometry -----------------------------------------------------------

    def _target_screen(self):
        if QGuiApplication.instance() is None:
            return None
        screen = None
        if hasattr(QGuiApplication, "screenAt"):
            screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen

    def _apply_preferred_size(self) -> None:
        screen = self._target_screen()
        if screen is None:
            self._scale = DISPLAY_SCALE_COMPACT
        else:
            avail = screen.availableGeometry()
            self._scale = display_scale_for_work_area(avail.width(), avail.height())
        w = int(round((CARD_WIDTH + 2 * SHADOW_PAD) * self._scale))
        h = int(round((CARD_HEIGHT + 2 * SHADOW_PAD) * self._scale))
        self.setFixedSize(max(1, w), max(1, h))

    def launch_screen_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Work area the splash was centered on, in virtual-desktop coordinates."""

        return self._launch_screen_rect

    def _center_on_screen(self) -> None:
        screen = self._target_screen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self._launch_screen_rect = (
            int(avail.x()),
            int(avail.y()),
            int(avail.width()),
            int(avail.height()),
        )
        frame = self.frameGeometry()
        frame.moveCenter(avail.center())
        self.move(frame.topLeft())

    def _s(self, value: float) -> float:
        return value * self._scale

    def _card_rect(self) -> QRectF:
        return QRectF(
            self._s(SHADOW_PAD),
            self._s(SHADOW_PAD),
            self._s(CARD_WIDTH),
            self._s(CARD_HEIGHT),
        )

    def _content_left(self) -> float:
        return self._card_rect().left() + self._s(CONTENT_PAD_X)

    def _content_right(self) -> float:
        return self._card_rect().right() - self._s(CONTENT_PAD_X)

    def _content_width(self) -> float:
        return self._content_right() - self._content_left()

    def _spectrum_rect(self) -> QRectF:
        """Inner spectrum art rect (logical 640×184 area inside the card)."""
        card = self._card_rect()
        top = card.top() + self._s(30.0 + 40.0 + 15.0)  # head pad + icon + gap
        height = self._s(198.0)
        return QRectF(card.left(), top, card.width(), height)

    def _spectrum_map_scale(self) -> float:
        rect = self._spectrum_rect()
        # Inset by scaled stroke half-width so peaks + stroke stay inside.
        half = (_MAX_STROKE_REF / 2.0) * (rect.width() / SPECTRUM_REF_W)
        usable_w = max(1.0, rect.width() - 2.0 * half)
        usable_h = max(1.0, rect.height() - 2.0 * half)
        return min(usable_w / SPECTRUM_REF_W, usable_h / SPECTRUM_REF_H)

    def _spectrum_map_origin(self) -> Tuple[float, float]:
        rect = self._spectrum_rect()
        scale = self._spectrum_map_scale()
        half = (_MAX_STROKE_REF / 2.0) * scale
        # Center the reference frame inside the usable inset.
        mapped_w = SPECTRUM_REF_W * scale
        mapped_h = SPECTRUM_REF_H * scale
        ox = rect.left() + half + (rect.width() - 2.0 * half - mapped_w) * 0.5
        oy = rect.top() + half + (rect.height() - 2.0 * half - mapped_h) * 0.5
        return ox, oy

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._ensure_brand_pixmap()
        self._rebuild_paths_if_needed(force=True)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        from PyQt5.QtCore import QEvent

        watched = {QEvent.FontChange, QEvent.StyleChange}
        screen_change = getattr(QEvent, "ScreenChangeInternal", None)
        if screen_change is not None:
            watched.add(screen_change)
        if event.type() in watched:
            self._ensure_brand_pixmap(force=True)
            self._rebuild_paths_if_needed(force=True)
            if self.isVisible() and not self._closed:
                self._apply_panel_surface(force=True)

    def _apply_panel_surface(self, *, force: bool = False) -> None:
        # Windows DWM draws Acrylic behind the entire rectangular HWND. The
        # card's antialiased transparent corners expose that rectangular layer.
        # Keep the Windows splash opaque inside its own rounded painted path.
        if platform.system() != "Windows":
            apply_native_panel_surface(self, force=force)

    # --- Animation tick -----------------------------------------------------

    def _on_tick(self) -> None:
        if self._closed:
            return
        now = self._now_ms()
        delta = max(0.0, now - self._last_tick_ms)
        self._last_tick_ms = now

        if not self._reduced_motion:
            self._breathe_phase = (self._breathe_phase + delta / _BREATHE_PERIOD_MS) % 1.0
            self._rail_phase = (self._rail_phase + delta / _RAIL_PERIOD_MS) % 1.0
            self._spinner_phase = (self._spinner_phase + delta / 1000.0) % 1.0

        # floor(elapsed / interval) from the opening tip. A paused UI jumps to
        # the current tip instead of replaying the missed ones.
        if TIPS:
            self._tip_index = tip_index_for_elapsed(self._opening_index, now)

        self.update()

    # --- Path cache ---------------------------------------------------------

    def _path_cache_key(self) -> Tuple[float, float, float, float, float]:
        rect = self._spectrum_rect()
        dpr = float(self.devicePixelRatioF())
        return (rect.x(), rect.y(), rect.width(), rect.height(), dpr)

    def _rebuild_paths_if_needed(self, force: bool = False) -> None:
        key = self._path_cache_key()
        if not force and key == self._cached_path_key and self._cached_paths:
            return
        ox, oy = self._spectrum_map_origin()
        scale = self._spectrum_map_scale()
        paths: list[QPainterPath] = []
        for layer in _SPECTRUM_LAYERS:
            path = QPainterPath()
            first = True
            for x, y in layer.points:
                pt = QPointF(ox + x * scale, oy + y * scale)
                if first:
                    path.moveTo(pt)
                    first = False
                else:
                    path.lineTo(pt)
            paths.append(path)
        self._cached_paths = paths
        self._cached_path_key = key
        self._path_build_count += 1

    def _ensure_brand_pixmap(self, force: bool = False) -> None:
        dpr = float(self.devicePixelRatioF())
        logical = int(round(self._s(40.0)))
        key = (logical, round(dpr, 3))
        if not force and key == self._brand_key and not self._brand_pix.isNull():
            return
        self._brand_pix = _load_brand_pixmap(logical, dpr)
        self._brand_key = key

    # --- Painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self._closed:
            return
        self._rebuild_paths_if_needed()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        card = self._card_rect()
        self._paint_card(painter, card)
        self._paint_header(painter, card)
        self._paint_spectrum(painter)
        self._paint_loading(painter, card)
        self._paint_tips(painter, card)
        self._paint_credit(painter, card)
        painter.end()

    def _paint_card(self, painter: QPainter, card: QRectF) -> None:
        path = paint_panel_fill(
            painter,
            card,
            self._s(CORNER_RADIUS),
            fallback=uses_opaque_fallback(self),
            bl_glow_scale=0.40,
        )
        edge = QLinearGradient(card.left(), card.top(), card.left(), card.bottom())
        edge.setColorAt(0.0, QColor(83, 132, 187, 58))
        edge.setColorAt(1.0, QColor(63, 108, 164, 86))
        pen = QPen()
        pen.setBrush(edge)
        pen.setWidthF(max(1.0, self._s(1.0)))
        painter.strokePath(path, pen)
        painter.save()
        painter.setClipPath(path)
        # Depth lives inside the rounded surface; it cannot leave a square
        # shadow in the transparent window corners.
        depth = QLinearGradient(card.left(), card.top(), card.left(), card.bottom())
        depth.setColorAt(0.0, QColor(255, 255, 255, 50))
        depth.setColorAt(0.55, QColor(255, 255, 255, 0))
        depth.setColorAt(1.0, QColor(53, 101, 159, 9))
        painter.fillPath(path, depth)

        inset = self._s(1.0)
        rim = QPainterPath()
        rim.addRoundedRect(
            card.adjusted(inset, inset, -inset, -inset),
            self._s(CORNER_RADIUS - 1.0),
            self._s(CORNER_RADIUS - 1.0),
        )
        rim_color = QLinearGradient(card.left(), card.top(), card.left(), card.bottom())
        rim_color.setColorAt(0.0, QColor(255, 255, 255, 230))
        rim_color.setColorAt(0.6, QColor(255, 255, 255, 45))
        rim_color.setColorAt(1.0, QColor(63, 108, 164, 75))
        rim_pen = QPen()
        rim_pen.setBrush(rim_color)
        rim_pen.setWidthF(max(1.0, self._s(1.2)))
        painter.strokePath(rim, rim_pen)
        painter.restore()
        # Clip subsequent chrome to the rounded card.
        painter.setClipPath(path)

    def _paint_header(self, painter: QPainter, card: QRectF) -> None:
        left = self._content_left()
        top = card.top() + self._s(30.0)
        icon_size = self._s(40.0)
        if not self._brand_pix.isNull():
            painter.drawPixmap(QPointF(left, top), self._brand_pix)

        word_px = max(12, int(round(self._s(31.0))))
        word_font = panel_font(FONT_ROLE_WORDMARK, pixel_size=word_px)
        painter.setFont(word_font)
        painter.setPen(_INK)
        word_x = left + icon_size + self._s(12.0)
        metrics = panel_font_metrics(FONT_ROLE_WORDMARK, pixel_size=word_px)
        word_y = top + (icon_size + metrics.ascent() - metrics.descent()) * 0.5
        painter.drawText(QPointF(word_x, word_y), APP_NAME)

        ver_px = max(9, int(round(self._s(11.0))))
        ver_font = panel_font(FONT_ROLE_CAPTION, pixel_size=ver_px)
        painter.setFont(ver_font)
        painter.setPen(_SECONDARY)
        ver_metrics = panel_font_metrics(FONT_ROLE_CAPTION, pixel_size=ver_px)
        ver_text = APP_VERSION
        ver_x = self._content_right() - ver_metrics.horizontalAdvance(ver_text)
        ver_y = top + self._s(4.0) + ver_metrics.ascent()
        painter.drawText(QPointF(ver_x, ver_y), ver_text)

    def _paint_spectrum(self, painter: QPainter) -> None:
        rect = self._spectrum_rect()
        ox, oy = self._spectrum_map_origin()
        scale = self._spectrum_map_scale()
        grad = QLinearGradient(ox, oy, ox + SPECTRUM_REF_W * scale, oy)
        for stop, color in _SPECTRUM_STOPS:
            grad.setColorAt(stop, color)

        if self._reduced_motion:
            group_alpha = 1.0
        else:
            # 0.7 ↔ 1.0 over ~5 s (ease-in-out via cosine).
            group_alpha = 0.7 + 0.3 * (
                0.5 + 0.5 * math.cos(self._breathe_phase * math.pi * 2.0)
            )

        for layer, path in zip(_SPECTRUM_LAYERS, self._cached_paths):
            alpha = max(0.0, min(1.0, layer.base_opacity * group_alpha))
            brush_pen = QPen()
            brush_pen.setBrush(grad)
            brush_pen.setWidthF(layer.stroke_width * scale)
            brush_pen.setCapStyle(Qt.RoundCap)
            brush_pen.setJoinStyle(Qt.RoundJoin)
            painter.save()
            painter.setOpacity(alpha)
            painter.strokePath(path, brush_pen)
            painter.restore()

        # Mode captions along the bottom of the spectrum band.
        cap_px = max(8, int(round(self._s(9.0))))
        cap_font = panel_font(FONT_ROLE_CAPTION, pixel_size=cap_px)
        painter.setFont(cap_font)
        painter.setPen(_CAPTION_FG)
        metrics = panel_font_metrics(FONT_ROLE_CAPTION, pixel_size=cap_px)
        y = rect.bottom() - self._s(12.0)
        x = self._content_left()
        for label in _MODE_CAPTIONS:
            # Dot
            painter.setBrush(_CAPTION_DOT)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                QPointF(x + self._s(2.0), y - metrics.ascent() * 0.35),
                self._s(2.0),
                self._s(2.0),
            )
            painter.setPen(_CAPTION_FG)
            painter.drawText(QPointF(x + self._s(10.0), y), label)
            x += self._s(16.0) + metrics.horizontalAdvance(label) + self._s(10.0)

    def _paint_loading(self, painter: QPainter, card: QRectF) -> None:
        spectrum = self._spectrum_rect()
        # loading block sits under spectrum; demo padding-bottom 21.
        row_top = spectrum.bottom() + self._s(8.0)
        left = self._content_left()
        right = self._content_right()

        # Spinner
        spin_r = self._s(6.5)
        cx = left + spin_r
        cy = row_top + self._s(11.0)
        track = QPen(_SPINNER_TRACK, max(1.0, self._s(1.5)))
        painter.setPen(track)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), spin_r, spin_r)
        if not self._reduced_motion:
            accent = QPen(_ACCENT, max(1.0, self._s(1.5)), Qt.SolidLine, Qt.RoundCap)
            painter.setPen(accent)
            span = 90 * 16  # Qt uses 1/16 degree units
            start = int((-self._spinner_phase * 360 - 90) * 16)
            painter.drawArc(
                QRectF(cx - spin_r, cy - spin_r, spin_r * 2, spin_r * 2),
                start,
                -span,
            )
        else:
            # Static accent arc segment.
            accent = QPen(_ACCENT, max(1.0, self._s(1.5)), Qt.SolidLine, Qt.RoundCap)
            painter.setPen(accent)
            painter.drawArc(
                QRectF(cx - spin_r, cy - spin_r, spin_r * 2, spin_r * 2),
                90 * 16,
                -90 * 16,
            )

        status_px = max(10, int(round(self._s(12.0))))
        status_font = panel_font(FONT_ROLE_EMPHASIS, pixel_size=status_px, bold=True)
        painter.setFont(status_font)
        painter.setPen(
            _ACCENT if (self._slow or self._now_ms() >= _SLOW_AFTER_MS) else _INK
        )
        status = self.status_text()
        sm = panel_font_metrics(FONT_ROLE_EMPHASIS, pixel_size=status_px, bold=True)
        status_x = left + spin_r * 2 + self._s(9.0)
        status_y = cy + sm.ascent() * 0.35
        painter.drawText(QPointF(status_x, status_y), status)

        right_px = max(8, int(round(self._s(10.0))))
        right_font = panel_font(FONT_ROLE_CAPTION, pixel_size=right_px)
        painter.setFont(right_font)
        painter.setPen(_SECONDARY)
        rm = panel_font_metrics(FONT_ROLE_CAPTION, pixel_size=right_px)
        painter.drawText(
            QPointF(right - rm.horizontalAdvance(_RIGHT_LABEL), status_y),
            _RIGHT_LABEL,
        )

        # Indeterminate rail
        rail_top = row_top + self._s(22.0) + self._s(13.0)
        rail_h = max(1.0, self._s(2.0))
        rail = QRectF(left, rail_top, right - left, rail_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_RAIL_TRACK)
        painter.drawRoundedRect(rail, rail_h, rail_h)
        seg_w = rail.width() * _RAIL_FRACTION
        if self._reduced_motion:
            seg_x = rail.left() + (rail.width() - seg_w) * 0.35
        else:
            # Ease-in-out travel: -105% → 415% of segment width (demo keyframes).
            t = self._rail_phase
            eased = 0.5 - 0.5 * math.cos(t * math.pi)  # 0..1 smooth
            travel = -1.05 + eased * (4.15 + 1.05)
            seg_x = rail.left() + travel * seg_w
        painter.setBrush(_ACCENT)
        painter.drawRoundedRect(QRectF(seg_x, rail.top(), seg_w, rail_h), rail_h, rail_h)

    def _paint_tips(self, painter: QPainter, card: QRectF) -> None:
        # Tip box sits above credit; credit ~33 logical, tip min-height 92.
        credit_h = self._s(33.0)
        tip_h = self._s(92.0)
        tip = QRectF(
            card.left(),
            card.bottom() - credit_h - tip_h,
            card.width(),
            tip_h,
        )
        wash = QLinearGradient(tip.topLeft(), tip.bottomRight())
        wash.setColorAt(0, _TIP_BG)
        wash.setColorAt(1, QColor(73, 142, 252, 20))
        painter.fillRect(tip, wash)
        painter.setPen(QPen(_TIP_BORDER, max(1.0, self._s(1.0))))
        painter.drawLine(tip.topLeft(), tip.topRight())

        left = self._content_left()
        right = self._content_right()
        title, body = TIPS[self._tip_index]

        heading_px = max(8, int(round(self._s(10.0))))
        heading_font = panel_font(FONT_ROLE_TITLE, pixel_size=heading_px, bold=True)
        painter.setFont(heading_font)
        hm = panel_font_metrics(FONT_ROLE_TITLE, pixel_size=heading_px, bold=True)
        head_y = tip.top() + self._s(17.0) + hm.ascent()

        # Dot indicators first so the title can elide against their reserved width.
        dots_gap = self._s(4.0)
        dots_w = 0.0
        for i in range(len(TIPS)):
            dots_w += self._s(12.0 if i == self._tip_index else 4.0)
            if i:
                dots_w += dots_gap
        dot_y = head_y - hm.ascent() * 0.4
        dot_x = right
        for i in range(len(TIPS) - 1, -1, -1):
            on = i == self._tip_index
            w = self._s(12.0 if on else 4.0)
            h = self._s(4.0)
            dot_x -= w
            painter.setPen(Qt.NoPen)
            painter.setBrush(_ACCENT if on else QColor(73, 142, 252, 64))
            painter.drawRoundedRect(
                QRectF(dot_x, dot_y - h * 0.5, w, h), h * 0.5, h * 0.5
            )
            dot_x -= dots_gap

        # Bulb + title (elided so it never covers the dots).
        bulb_cx = left + self._s(6.0)
        bulb_cy = head_y - hm.ascent() * 0.35
        self._draw_bulb(painter, bulb_cx, bulb_cy, self._s(6.0))
        painter.setPen(_TIP_TITLE)
        painter.setFont(heading_font)
        title_left = left + self._s(18.0)
        title_right = right - dots_w - self._s(10.0)
        elided = hm.elidedText(title, Qt.ElideRight, max(8, int(title_right - title_left)))
        painter.drawText(QPointF(title_left, head_y), elided)

        body_px = max(9, int(round(self._s(12.0))))
        body_font = panel_font(FONT_ROLE_BODY, pixel_size=body_px)
        painter.setFont(body_font)
        painter.setPen(_TIP_BODY)
        body_rect = QRectF(
            left,
            tip.top() + self._s(17.0 + 8.0 + 14.0),
            right - left,
            tip.bottom() - (tip.top() + self._s(17.0 + 8.0 + 14.0)) - self._s(10.0),
        )
        painter.drawText(body_rect, int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop), body)

    def _draw_bulb(self, painter: QPainter, cx: float, cy: float, r: float) -> None:
        painter.save()
        pen = QPen(_TIP_TITLE, max(1.0, r * 0.18), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy - r * 0.15), r * 0.55, r * 0.55)
        painter.drawLine(QPointF(cx - r * 0.35, cy + r * 0.55), QPointF(cx + r * 0.35, cy + r * 0.55))
        painter.drawLine(QPointF(cx - r * 0.25, cy + r * 0.8), QPointF(cx + r * 0.25, cy + r * 0.8))
        painter.restore()

    def _paint_credit(self, painter: QPainter, card: QRectF) -> None:
        credit_h = self._s(33.0)
        credit = QRectF(card.left(), card.bottom() - credit_h, card.width(), credit_h)
        # Bottom corners already clipped to card path.
        painter.setPen(Qt.NoPen)
        painter.setBrush(_CREDIT_BG)
        painter.drawRect(credit)

        credit_px = max(7, int(round(self._s(9.0))))
        font = panel_font(FONT_ROLE_CREDIT, pixel_size=credit_px)
        painter.setFont(font)
        painter.setPen(_CREDIT_FG)
        metrics = panel_font_metrics(FONT_ROLE_CREDIT, pixel_size=credit_px)
        y = credit.center().y() + metrics.ascent() * 0.35
        painter.drawText(QPointF(self._content_left(), y), _CREDIT_LEFT)
        painter.drawText(
            QPointF(self._content_right() - metrics.horizontalAdvance(APP_CREDIT), y),
            APP_CREDIT,
        )


__all__ = [
    "APP_CREDIT",
    "APP_NAME",
    "APP_VERSION",
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "DISPLAY_SCALE_COMPACT",
    "DISPLAY_SCALE_LARGE",
    "STAGE_LOADING_COMPONENTS",
    "STAGE_PREPARING",
    "STAGE_PREPARING_WORKSPACE",
    "StartupSplash",
    "TIPS",
    "detect_system_reduced_motion",
    "display_scale_for_work_area",
    "spectrum_reference_bounds",
]
