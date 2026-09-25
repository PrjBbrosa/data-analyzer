"""Stdlib visual facts for the startup panel.

Qt splash and the Windows native launcher both consume this module. It must
not import Qt, numpy, or the UI package. Shared palette tokens come from
``qt_panel_style`` constants, which stay import-safe.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from mf4_analyzer.app_meta import APP_CREDIT, APP_NAME, APP_VERSION
from mf4_analyzer.qt_panel_style import (
    ACCENT_HEX,
    BORDER_RGBA,
    GLOW_BL,
    GLOW_TR,
    INK_HEX,
    PANEL_BASE_RGB,
    SECONDARY_HEX,
    SPECTRUM_STOP_HEX,
    TIP_BODY_HEX,
    TIP_TITLE_HEX,
    WINDOWS_FONT_CANDIDATES,
    WORDMARK_FAMILY,
)

SCHEMA = 1

STAGE_PREPARING = "preparing"
STAGE_LOADING_COMPONENTS = "loading_components"
STAGE_PREPARING_WORKSPACE = "preparing_workspace"
STAGE_LABELS = {
    STAGE_PREPARING: "正在启动 TraceLab…",
    STAGE_LOADING_COMPONENTS: "正在加载分析组件…",
    STAGE_PREPARING_WORKSPACE: "正在准备工作区…",
}
SLOW_STATUS = "启动比平时久一些，请稍候…"
RIGHT_LABEL = "工程数据分析工作台"
CREDIT_LEFT = f"{APP_NAME} · 工程信号与数据分析"
MODE_CAPTIONS = ("时域", "频谱", "时频", "阶次", "频响")

CARD_WIDTH = 640
CARD_HEIGHT = 470
DISPLAY_SCALE_LARGE = 1.5
DISPLAY_SCALE_COMPACT = 1.0
LARGE_SCALE_MIN_AVAILABLE_HEIGHT = 1200
WORK_AREA_MARGIN = 24
CORNER_RADIUS = 13.0
CONTENT_PAD_X = 32.0
SHADOW_PAD = 0.0
SPECTRUM_REF_W = 640.0
SPECTRUM_REF_H = 184.0
SPECTRUM_Y_TOP = 15.0
SPECTRUM_Y_SPAN = 132.0
SPECTRUM_ROWS = 16
SPECTRUM_SAMPLES = 461
TIP_INTERVAL_MS = 5000
SLOW_AFTER_MS = 12000
BREATHE_PERIOD_MS = 5000
RAIL_PERIOD_MS = 2300
SPINNER_PERIOD_MS = 1000
RAIL_FRACTION = 0.32
FRAME_INTERVAL_MS = 33
MAX_STROKE_REF = 1.65

# Splash-specific ink that is not part of the shared panel palette.
TIP_WASH_RGBA = (24, 193, 229, 18)
TIP_BORDER_RGBA = (255, 255, 255, 184)
CREDIT_BG_RGBA = (255, 255, 255, 36)
CREDIT_FG_HEX = "#617e98"
RAIL_TRACK_RGBA = (73, 142, 252, 38)
CAPTION_DOT_HEX = "#17b6df"
SPINNER_TRACK_RGBA = (73, 142, 252, 61)
SPECTRUM_STOPS = (0.0, 0.4, 0.67, 1.0)

FONT_SIZES_PX = {
    "wordmark": 31,
    "version": 11,
    "caption": 9,
    "status": 12,
    "right_label": 10,
    "tip_heading": 10,
    "tip_body": 12,
    "credit": 9,
}
ICON_LOGICAL_PX = 40


@dataclass(frozen=True)
class StartupTip:
    tip_id: str
    title: str
    body: str
    index: int


@dataclass(frozen=True)
class SpectrumLayer:
    points: tuple[tuple[float, float], ...]
    stroke_width: float
    base_opacity: float


def _tip(index: int, title: str, body: str) -> StartupTip:
    return StartupTip(f"tip-{index:02d}", title, body, index - 1)


# Order is the rotation order. IDs are stable positions, not titles.
TIP_RECORDS: tuple[StartupTip, ...] = (
    _tip(1, "找回全局视野", "点 Home 或按 Ctrl+R，查看已绘通道的全部范围。"),
    _tip(2, "缩放与平移", "Ctrl+滚轮缩放时间，Shift+滚轮缩放幅值，拖动平移。"),
    _tip(3, "框选放大", "在图上拖出矩形，时间和幅值一起放大。"),
    _tip(4, "勾选即绘图", "左侧通道树勾选通道，就会画到当前 View。"),
    _tip(5, "拖进来绘图", "把通道拖进绘图区松手，即加入当前 View。"),
    _tip(6, "搜索通道", "通道树和通道下拉框都可以输入关键词查找。"),
    _tip(7, "固定读数", "单游标按 P 固定读数，再点图底 Pn 展开。"),
    _tip(8, "比较两点", "按 Ctrl+5 开双游标，看两点的时间差或幅值差。"),
    _tip(9, "五个工作区", "时域波形、频谱成分、时频变化、阶次转速、频响输入输出。"),
    _tip(10, "阶次看转速", "阶次以电机转速为基准，看频率怎样跟着转速走。"),
    _tip(11, "谱图取切片", "在时频或阶次谱图上点一下，取出该时刻的切片。"),
    _tip(12, "保存现场", "存成 .tlproj 项目，下次接着当前的通道和 View。"),
    _tip(13, "最近的文件", "点「打开」旁的箭头，搜索最近的项目和文件。"),
    _tip(14, "加入当前 View", "点文件卡片右下的 ＋，把已打开文件加入当前 View。"),
    _tip(15, "操作速查", "点底栏「?」搜索操作；悬停顶部按钮可看快捷键。"),
    _tip(16, "图表右键", "右键图面：查看全部、轴范围、网格。"),
    _tip(17, "分屏或叠加", "Ctrl+1 分屏，Ctrl+2 叠加，顺序跟左侧通道树一致。"),
    _tip(18, "多个 View", "时域最多 24 个 View；窄窗口显示编号，悬停看全名。"),
    _tip(19, "运算出新通道", "点通道树下「编辑通道」，可做微分、积分或两通道运算。"),
    _tip(20, "复制带读数", "复制按钮导出的图片会带上游标和读数。"),
    _tip(21, "一次处理多文件", "工具栏「批处理」用同一分析处理多个文件并导出。"),
    _tip(22, "在图上做标记", "打开标注后，左键添加，右键删除最近一个标记。"),
    _tip(23, "换一条横轴", "把通道拖到图最底部的 X 带，换成这路信号做横轴。"),
    _tip(24, "预设分析参数", "预设保存分析参数；切换时可以保留手动调过的坐标。"),
    _tip(25, "视角可回退", "Alt+左退回上一视角，Alt+右前进。Ctrl+Z 仍是撤销编辑。"),
    _tip(26, "看软件说明", "状态栏右侧书本图标打开软件说明书。"),
)

# Compatibility pairs. Identity is ``tip_id``, not this tuple.
TIPS: tuple[tuple[str, str], ...] = tuple(
    (tip.title, tip.body) for tip in TIP_RECORDS
)


def validate_tip_records(records: Sequence[StartupTip]) -> None:
    """Reject an empty list, duplicate ids, or blank copy. Used by the generator."""

    if not records:
        raise ValueError("tip list is empty")
    seen: set[str] = set()
    for record in records:
        tip_id = str(record.tip_id).strip()
        if not tip_id:
            raise ValueError("tip id is empty")
        if tip_id in seen:
            raise ValueError(f"duplicate tip id: {tip_id}")
        seen.add(tip_id)
        if not str(record.title).strip() or not str(record.body).strip():
            raise ValueError(f"tip {tip_id} is missing title or body")
        if int(record.index) < 0:
            raise ValueError(f"tip {tip_id} has a negative index")


def tip_by_id(tip_id: str, records: Sequence[StartupTip] = TIP_RECORDS) -> StartupTip:
    for record in records:
        if record.tip_id == tip_id:
            return record
    raise ValueError(f"unknown tip id: {tip_id!r}")


def choose_opening_index(randrange: Callable[[int], int], *, count: int | None = None) -> int:
    """Pick the session's only random tip index. Call once."""

    total = len(TIP_RECORDS) if count is None else int(count)
    if total <= 0:
        raise ValueError("tip list is empty")
    chosen = int(randrange(total))
    if chosen < 0 or chosen >= total:
        raise ValueError(f"opening tip index out of range: {chosen}")
    return chosen


def tip_index_for_elapsed(
    initial_index: int,
    visible_elapsed_ms: float,
    *,
    count: int | None = None,
    interval_ms: int = TIP_INTERVAL_MS,
) -> int:
    """Tip shown at ``visible_elapsed_ms`` from first present.

    The index is ``floor(elapsed / interval)`` steps after the opening tip.
    It does not re-roll and does not depend on how many timer ticks fired.
    """

    total = len(TIP_RECORDS) if count is None else int(count)
    if total <= 0:
        raise ValueError("tip list is empty")
    if initial_index < 0 or initial_index >= total:
        raise ValueError(f"initial tip index out of range: {initial_index}")
    interval = int(interval_ms)
    if interval <= 0:
        raise ValueError("tip interval must be positive")
    elapsed = 0 if visible_elapsed_ms < 0 else int(visible_elapsed_ms)
    return (int(initial_index) + elapsed // interval) % total


def status_label(
    stage: str,
    visible_elapsed_ms: float,
    *,
    slow: bool = False,
) -> str:
    if stage not in STAGE_LABELS:
        raise ValueError(f"unknown splash stage: {stage!r}")
    elapsed = 0 if visible_elapsed_ms < 0 else int(visible_elapsed_ms)
    if slow or elapsed >= int(SLOW_AFTER_MS):
        return SLOW_STATUS
    return STAGE_LABELS[stage]


def animation_phase(visible_elapsed_ms: float, period_ms: int) -> float:
    """0..1 phase from the first-present clock. Reduced motion stays at 0."""

    period = int(period_ms)
    if period <= 0:
        raise ValueError("animation period must be positive")
    elapsed = 0 if visible_elapsed_ms < 0 else int(visible_elapsed_ms)
    return (elapsed % period) / float(period)


def breathe_opacity(phase: float, *, reduced_motion: bool = False) -> float:
    """Spectrum group opacity. Reduced motion holds the fully visible pose."""

    if reduced_motion:
        return 1.0
    wrapped = float(phase) % 1.0
    return 0.7 + 0.3 * (0.5 + 0.5 * math.cos(wrapped * math.pi * 2.0))


def display_scale_for_work_area(avail_width: float, avail_height: float) -> float:
    """Choose 1.5 or 1.0 from the logical work area, then shrink to fit."""

    max_w = max(160.0, float(avail_width) - WORK_AREA_MARGIN)
    max_h = max(160.0, float(avail_height) - WORK_AREA_MARGIN)
    card_w = float(CARD_WIDTH + 2 * SHADOW_PAD)
    card_h = float(CARD_HEIGHT + 2 * SHADOW_PAD)
    if (
        float(avail_height) >= LARGE_SCALE_MIN_AVAILABLE_HEIGHT
        and card_w * DISPLAY_SCALE_LARGE <= max_w
        and card_h * DISPLAY_SCALE_LARGE <= max_h
    ):
        return DISPLAY_SCALE_LARGE
    need_w = card_w * DISPLAY_SCALE_COMPACT
    need_h = card_h * DISPLAY_SCALE_COMPACT
    if need_w <= max_w and need_h <= max_h:
        return DISPLAY_SCALE_COMPACT
    return DISPLAY_SCALE_COMPACT * min(max_w / need_w, max_h / need_h)


def _compute_spectrum_layers() -> tuple[SpectrumLayer, ...]:
    rows: list[list[tuple[float, float]]] = []
    for row in range(SPECTRUM_ROWS):
        points: list[tuple[float, float]] = []
        for sample in range(SPECTRUM_SAMPLES):
            i = sample / 4.0
            x = 40.0 + i * 4.3 + row * 5.7
            peaks = (
                56.0 * math.exp(-(((i - 34.0 - row * 0.4) / 7.0) ** 2))
                + 90.0 * math.exp(-(((i - 67.0 + row * 0.55) / 8.0) ** 2))
                + 23.0 * math.exp(-(((i - 91.0) / 6.0) ** 2))
            )
            y = (
                150.0
                - row * 4.0
                - peaks * (0.50 + row * 0.035)
                + math.sin(i * 0.35 + row * 0.6) * 2.0
            )
            points.append((x, y))
        rows.append(points)

    ys = [point[1] for row in rows for point in row]
    y_min = min(ys)
    y_max = max(ys)
    span = y_max - y_min if y_max > y_min else 1.0
    layers: list[SpectrumLayer] = []
    for row, points in enumerate(rows):
        mapped = tuple(
            (x, SPECTRUM_Y_TOP + (y - y_min) / span * SPECTRUM_Y_SPAN)
            for x, y in points
        )
        layers.append(
            SpectrumLayer(
                points=mapped,
                stroke_width=MAX_STROKE_REF if row == SPECTRUM_ROWS - 1 else 1.05,
                base_opacity=0.29 + row * 0.044,
            )
        )
    return tuple(layers)


SPECTRUM_LAYERS = _compute_spectrum_layers()


def spectrum_reference_bounds() -> tuple[float, float, float, float]:
    xs = [point[0] for layer in SPECTRUM_LAYERS for point in layer.points]
    ys = [point[1] for layer in SPECTRUM_LAYERS for point in layer.points]
    return min(xs), min(ys), max(xs), max(ys)


def visual_payload() -> dict[str, Any]:
    """Canonical facts hashed into the native resource manifest."""

    return {
        "schema": SCHEMA,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "app_credit": APP_CREDIT,
        "credit_left": CREDIT_LEFT,
        "right_label": RIGHT_LABEL,
        "mode_captions": list(MODE_CAPTIONS),
        "stages": [
            {"id": key, "label": STAGE_LABELS[key]}
            for key in (
                STAGE_PREPARING,
                STAGE_LOADING_COMPONENTS,
                STAGE_PREPARING_WORKSPACE,
            )
        ],
        "slow_status": SLOW_STATUS,
        "tips": [
            {"id": tip.tip_id, "title": tip.title, "body": tip.body, "index": tip.index}
            for tip in TIP_RECORDS
        ],
        "geometry": {
            "card_width": CARD_WIDTH,
            "card_height": CARD_HEIGHT,
            "corner_radius": CORNER_RADIUS,
            "content_pad_x": CONTENT_PAD_X,
            "shadow_pad": SHADOW_PAD,
            "display_scale_large": DISPLAY_SCALE_LARGE,
            "display_scale_compact": DISPLAY_SCALE_COMPACT,
            "large_scale_min_available_height": LARGE_SCALE_MIN_AVAILABLE_HEIGHT,
            "work_area_margin": WORK_AREA_MARGIN,
            "spectrum_rows": SPECTRUM_ROWS,
            "spectrum_samples": SPECTRUM_SAMPLES,
        },
        "motion": {
            "tip_interval_ms": TIP_INTERVAL_MS,
            "slow_after_ms": SLOW_AFTER_MS,
            "breathe_period_ms": BREATHE_PERIOD_MS,
            "rail_period_ms": RAIL_PERIOD_MS,
            "spinner_period_ms": SPINNER_PERIOD_MS,
            "rail_fraction": RAIL_FRACTION,
            "frame_interval_ms": FRAME_INTERVAL_MS,
        },
        "palette": {
            "panel_base_rgb": list(PANEL_BASE_RGB),
            "ink": INK_HEX,
            "secondary": SECONDARY_HEX,
            "accent": ACCENT_HEX,
            "tip_title": TIP_TITLE_HEX,
            "tip_body": TIP_BODY_HEX,
            "border_rgba": list(BORDER_RGBA),
            "glow_tr": list(GLOW_TR),
            "glow_bl": list(GLOW_BL),
            "spectrum_stops": list(SPECTRUM_STOPS),
            "spectrum_stop_hex": list(SPECTRUM_STOP_HEX),
            "wordmark_family": WORDMARK_FAMILY,
            "windows_font_candidates": list(WINDOWS_FONT_CANDIDATES),
        },
        "splash_colors": {
            "tip_wash_rgba": list(TIP_WASH_RGBA),
            "tip_border_rgba": list(TIP_BORDER_RGBA),
            "credit_bg_rgba": list(CREDIT_BG_RGBA),
            "credit_fg": CREDIT_FG_HEX,
            "rail_track_rgba": list(RAIL_TRACK_RGBA),
            "caption_dot": CAPTION_DOT_HEX,
            "spinner_track_rgba": list(SPINNER_TRACK_RGBA),
        },
        "font_sizes_px": dict(FONT_SIZES_PX),
        "icon_logical_px": ICON_LOGICAL_PX,
    }


def content_hash(payload: Mapping[str, Any] | None = None) -> str:
    body = visual_payload() if payload is None else payload
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


validate_tip_records(TIP_RECORDS)
