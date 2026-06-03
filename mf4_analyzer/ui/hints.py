"""Curated chart hint registry.

The chart bar consumes this module instead of parsing design docs or keeping
free-floating hint strings in widget code.
"""
from dataclasses import dataclass, field

from PyQt5.QtCore import QSettings


DISCOVERED_SETTINGS_KEY = "chartHints/discovered"


@dataclass(frozen=True)
class Hint:
    id: str
    text: str
    surface: str
    tier: str = "S"
    modes: frozenset[str] = field(default_factory=frozenset)
    plot_modes: frozenset[str] = field(default_factory=frozenset)
    cursor_modes: frozenset[str] = field(default_factory=frozenset)
    mouse_modes: frozenset[str] = field(default_factory=frozenset)
    chart_kinds: frozenset[str] = field(default_factory=frozenset)
    requires: frozenset[str] = field(default_factory=frozenset)
    retire_on: str | None = None
    priority: int = 50
    ship: str = "now"


@dataclass(frozen=True)
class HintState:
    mode: str = ""
    plot_mode: str = ""
    cursor_mode: str = "off"
    mouse_mode: str = ""
    chart_kind: str = ""
    annotation_on: bool = False
    discovered: frozenset[str] = field(default_factory=frozenset)
    recently_used: frozenset[str] = field(default_factory=frozenset)


NAV_SHORTCUTS = {
    "home": "Alt+R",
    "back": "Alt+Z",
    "forward": "Alt+Shift+Z",
    "pan": "Alt+G",
    "zoom": "Alt+B",
}

TIME_CARD_SHORTCUTS = (
    ("btn_subplot", "分屏", "Alt+1"),
    ("btn_overlay", "叠加", "Alt+2"),
    ("cursor_off", "游标关", "Alt+3"),
    ("cursor_single", "单游标", "Alt+4"),
    ("cursor_dual", "双游标", "Alt+5"),
)

_SHORTCUTS = {
    **NAV_SHORTCUTS,
    **{key: shortcut for key, _label, shortcut in TIME_CARD_SHORTCUTS},
}

_HINTS = (
    Hint(
        id="wheel.zoom_x",
        text="Ctrl + 滚轮 缩放 X",
        surface="persistent",
        priority=100,
    ),
    Hint(
        id="wheel.zoom_y",
        text="Shift + 滚轮 缩放 Y",
        surface="persistent",
        priority=90,
    ),
    Hint(
        id="chart.options",
        text="双击图面 打开图表选项",
        surface="persistent",
        priority=80,
    ),
    Hint(
        id="toolbar.shortcuts_exist",
        text="顶部按钮支持快捷键，悬停按钮即可查看",
        surface="discovery",
        retire_on="shortcut",
        priority=100,
    ),
    Hint(
        id="chart.copy_image",
        text="复制按钮可导出带游标读数的图片，并打开标注编辑器",
        surface="discovery",
        retire_on="copy_image",
        priority=95,
    ),
    Hint(
        id="chart.right_click_menu",
        text="右键图表 → 查看全部 · 轴范围 · 网格 等选项",
        surface="discovery",
        retire_on="chart_context_menu",
        priority=90,
    ),
    Hint(
        id="channel.right_click",
        text="左侧通道右键 → 设为叠加图左轴",
        surface="discovery",
        retire_on="channel_context_menu",
        priority=80,
    ),
    Hint(
        id="view.history",
        text="图表可后退/前进到上一个视图（Alt+Z）",
        surface="discovery",
        retire_on="view_history",
        priority=60,
        ship="later",
    ),
    Hint(
        id="markup.capabilities",
        text="裁剪 / 箭头 / 文字 / 序号，支持撤销",
        surface="discovery",
        retire_on="markup_open",
        priority=40,
        ship="later",
    ),
    Hint(
        id="overlay.drag_y",
        text="点击曲线后拖动 → 单独调该通道 Y 轴",
        surface="context",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay"}),
        priority=100,
    ),
    Hint(
        id="subplot.wheel_target",
        text="滚轮作用于鼠标所在子图",
        surface="context",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"subplot"}),
        priority=100,
    ),
    Hint(
        id="cursor.dual_ab",
        text="点 A 点 B → 显示 ΔT 与区间统计",
        surface="context",
        modes=frozenset({"time"}),
        cursor_modes=frozenset({"dual"}),
        priority=120,
    ),
    Hint(
        id="spectrogram.slice",
        text="点击谱图某一时刻 → 查看该帧频率切片",
        surface="context",
        modes=frozenset({"fft_time"}),
        chart_kinds=frozenset({"fft_time"}),
        priority=100,
    ),
    Hint(
        id="annotation.mode",
        text="左键添加标注 · 右键删除最近一处",
        surface="context",
        modes=frozenset({"fft", "order"}),
        requires=frozenset({"annotation_on"}),
        priority=100,
    ),
    Hint(
        id="subplot.shift_y",
        text="Shift + 滚轮 缩放当前子图 Y",
        surface="context",
        tier="A",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"subplot"}),
        priority=80,
    ),
    Hint(
        id="zoom.guard",
        text="框选缩放时，拖框优先于选择曲线",
        surface="context",
        tier="A",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay"}),
        mouse_modes=frozenset({"zoom"}),
        priority=80,
    ),
)


def all_hints():
    return _HINTS


def persistent_hints():
    return tuple(hint.text for hint in _HINTS if hint.surface == "persistent")


def shortcut_tooltip(action_key):
    return _SHORTCUTS.get(action_key)


def context_hints(state):
    matches = [
        hint for hint in _HINTS
        if hint.surface == "context"
        and hint.id not in state.recently_used
        and _matches_state(hint, state)
    ]
    return tuple(sorted(matches, key=_context_sort_key))


def discovery_hint(state):
    candidates = [
        hint for hint in _HINTS
        if hint.surface == "discovery"
        and hint.ship == "now"
        and hint.id not in state.discovered
        and _matches_state(hint, state)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda hint: -hint.priority)[0]


def load_discovered(settings=None):
    settings = settings or QSettings()
    value = settings.value(DISCOVERED_SETTINGS_KEY, "")
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = str(value).replace(",", "\n").splitlines()
    return frozenset(part.strip() for part in parts if part and part.strip())


def mark_discovered(settings, hint_id):
    discovered = set(load_discovered(settings))
    discovered.add(hint_id)
    settings.setValue(DISCOVERED_SETTINGS_KEY, "\n".join(sorted(discovered)))
    settings.sync()
    return frozenset(discovered)


def _matches_state(hint, state):
    if hint.modes and state.mode not in hint.modes:
        return False
    if hint.plot_modes and state.plot_mode not in hint.plot_modes:
        return False
    if hint.cursor_modes and state.cursor_mode not in hint.cursor_modes:
        return False
    if hint.mouse_modes and state.mouse_mode not in hint.mouse_modes:
        return False
    if hint.chart_kinds and state.chart_kind not in hint.chart_kinds:
        return False
    if "annotation_on" in hint.requires and not state.annotation_on:
        return False
    return True


def _context_sort_key(hint):
    tier_rank = 0 if hint.tier == "S" else 1
    return (tier_rank, -hint.priority, hint.id)
