"""Curated chart hint registry.

The chart bar consumes this module instead of parsing design docs or keeping
free-floating hint strings in widget code.
"""
import unicodedata
from dataclasses import dataclass, field

from PyQt5.QtCore import QSettings


DISCOVERED_SETTINGS_KEY = "chartHints/discovered"


# The footer shares one bar between a left (rotating gesture) slot and a right
# (discovery) slot that hug opposite edges. Each line must therefore stay short
# enough that the two do not collide on a normal-width chart, so every registry
# hint is capped at HINT_MAX_WIDTH *full-width units*: CJK ideographs and
# full-width punctuation count 1; narrow ASCII/Latin glyphs (letters, digits,
# spaces, "·", "→") count 0, since they render at ~half width and are not what
# drives a hint past the bar. ``test_hints`` enforces this on ``all_hints()`` so
# new hints stay within budget at definition time. (On a too-narrow window the
# left slot simply elides — see chart_stack's bottom hint bar.)
HINT_MAX_WIDTH = 18


def hint_display_width(text):
    """Full-width-glyph count of ``text`` (the bottom-bar length budget).

    East-Asian Wide (``W``) and Fullwidth (``F``) characters count 1; every
    other character counts 0. See ``HINT_MAX_WIDTH`` for the rationale.
    """
    return sum(
        1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F")
    )


# Variable-dwell rotation tuning. The footer shows one rotating hint at a time;
# higher-priority hints linger longer so the important gestures stay readable
# while low-frequency tips still get a brief turn each lap.
_DWELL_BASE_MS = 4000
_DWELL_PER_PRIORITY_MS = 80
_DWELL_MIN_MS = 3500
_DWELL_MAX_MS = 13000

# "The longer you use it, the quieter it gets." A rotating hint whose gesture the
# user keeps performing loses weight each session-use and is dropped from the
# pool entirely once it has been used / discovered enough times. recently_used is
# a session set (no count), so a single repeat demotes; a persisted ``discovered``
# id (mark_discovered) is treated as a full retirement of its rotating echo.
_USED_WEIGHT_PENALTY = 60
_RETIRE_AFTER_USES = 1  # a session-used rotating hint drops out for that session


@dataclass(frozen=True)
class Hint:
    id: str
    text: str
    surface: str
    scope: str = "chart"
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
    # Both optional: when left None they fall back to priority-derived defaults so
    # every legacy hint keeps its old rotation behavior unchanged.
    dwell_ms: int | None = None  # how long this hint lingers in the footer
    weight: int | None = None    # rotation-pool ordering weight (defaults to priority)
    # When a discovery id retires this rotating hint's "echo" (e.g. the base-gesture
    # anchor for a capability the user has now exercised), name it here.
    retire_when_discovered: str | None = None

    def effective_dwell_ms(self) -> int:
        if self.dwell_ms is not None:
            base = int(self.dwell_ms)
        else:
            base = _DWELL_BASE_MS + max(0, int(self.priority)) * _DWELL_PER_PRIORITY_MS
        return max(_DWELL_MIN_MS, min(_DWELL_MAX_MS, base))

    def base_weight(self) -> int:
        return int(self.weight) if self.weight is not None else int(self.priority)


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
    "home": "Ctrl+R",
    "back": "Ctrl+Z",
    "forward": "Ctrl+Shift+Z",
    "pan": "Ctrl+G",
    "zoom": "Ctrl+B",
}

TIME_CARD_SHORTCUTS = (
    ("btn_subplot", "分屏", "Ctrl+1"),
    ("btn_overlay", "叠加", "Ctrl+2"),
    ("cursor_off", "游标关", "Ctrl+3"),
    ("cursor_single", "单游标", "Ctrl+4"),
    ("cursor_dual", "双游标", "Ctrl+5"),
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
        id="toolbar.shortcuts_exist",
        text="顶部按钮支持快捷键，悬停按钮即可查看",
        surface="discovery",
        retire_on="shortcut",
        priority=100,
    ),
    Hint(
        id="chart.copy_image",
        text="复制按钮导出带游标读数的图片并标注",
        surface="discovery",
        retire_on="copy_image",
        priority=95,
    ),
    Hint(
        id="chart.right_click_menu",
        text="右键图表 → 查看全部 · 轴范围 · 网格",
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
        text="图表可后退/前进到上一个视图（Ctrl+Z）",
        surface="discovery",
        retire_on="view_history",
        priority=60,
        ship="later",
    ),
    Hint(
        id="markup.capabilities",
        text="箭头移动标注 · 双击编辑文本 · 单键切换工具",
        surface="discovery",
        scope="markup",
        retire_on="markup_open",
        priority=40,
        ship="now",
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
    # ---- Anchor hints (base gestures, folded into the rotation pool) ----
    # These replace the old static persistent label. They are the longest-dwell,
    # highest-weight entries so the universal base gesture stays readable on every
    # lap, while the section text matches what that section's wheel actually does.
    # Line charts (time + FFT spectrum) honour Ctrl→X / Shift→Y in their wheel
    # dispatch; the spectrogram heatmaps (FFT-vs-Time / Order) do too once the
    # heatmap wheel dispatch is wired, but their headline gesture is slice/colorbar.
    Hint(
        id="anchor.line_wheel",
        text="Ctrl / Shift + 滚轮 缩放 X / Y",
        surface="anchor",
        modes=frozenset({"time", "fft"}),
        priority=70,
        dwell_ms=12000,
        weight=130,
    ),
    Hint(
        id="anchor.heatmap_gesture",
        text="点击谱图取切片 · 拖 colorbar 调色阶",
        surface="anchor",
        modes=frozenset({"fft_time", "order"}),
        priority=70,
        dwell_ms=12000,
        weight=130,
    ),
    # ---- Section-specific hidden-gesture tips ----
    # Spectrogram (FFT-vs-Time / Order): slice picking, marker drag, colorbar
    # scaling/reset, and the draggable map/slice divider. Gated to the heatmap
    # sections so they only surface on the right pages.
    Hint(
        id="spectrogram.colorbar_scale",
        text="拖 colorbar 调色阶 · 双击重置",
        surface="context",
        tier="A",
        modes=frozenset({"fft_time", "order"}),
        chart_kinds=frozenset({"fft_time", "order"}),
        priority=70,
        retire_when_discovered="spectrogram.colorbar",
    ),
    Hint(
        id="spectrogram.divider",
        text="拖分隔条调谱图/切片高度 · 双击重置",
        surface="context",
        tier="A",
        modes=frozenset({"fft_time", "order"}),
        chart_kinds=frozenset({"fft_time", "order"}),
        priority=60,
        retire_when_discovered="spectrogram.divider",
    ),
    Hint(
        id="order.slice",
        text="点击谱图某一时刻 → 查看该阶次切片",
        surface="context",
        modes=frozenset({"order"}),
        chart_kinds=frozenset({"order"}),
        priority=100,
        retire_when_discovered="spectrogram.slice_pick",
    ),
    # FFT time-domain preview (lives on the FFT spectrum line card, below the
    # spectrum): click a curve to choose the source, and the preview honours
    # Ctrl/Shift wheel zoom independently of the spectrum above it.
    Hint(
        id="fft.preview_pick_source",
        text="点击上方频谱曲线 → 选为下方时域预览的源",
        surface="context",
        tier="A",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=75,
        retire_when_discovered="fft.preview_source",
    ),
    Hint(
        id="fft.preview_wheel",
        text="预览图内 Ctrl/Shift+滚轮 独立缩放",
        surface="context",
        tier="A",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=55,
    ),
    # Annotation gesture, gated on annotation mode, for the FFT-vs-Time + Order
    # cards as well (the existing annotation.mode hint only covers fft + order).
    Hint(
        id="annotation.mode_fft_time",
        text="左键添加标注 · 右键删除最近一处",
        surface="context",
        modes=frozenset({"fft_time"}),
        requires=frozenset({"annotation_on"}),
        priority=100,
    ),
)


# Discovery-style tips that are surfaced by an in-app gesture (mark_discovered /
# flash) rather than the rotating pool. They live in the registry so the wiring
# in chart_stack / inspector points at a single source of truth for the text.
_FLASH_TIPS = {
    "spectrogram.slice_pick": "已取该帧切片 · 也可拖动切片标记线移动取样位置",
    "spectrogram.colorbar": "拖 colorbar 调色阶 · 双击 colorbar 可重置范围",
    "spectrogram.divider": "拖上下分隔条调高度 · 双击重置 · 底部可折叠/展开",
    "fft.preview_source": "已选为时域预览的源 · 预览图支持 Ctrl/Shift 滚轮独立缩放",
    "preset.right_click": "预设槽右键可保存 / 重命名 / 重置为默认",
}


def flash_tip(tip_id):
    """Return the curated flash-tip text for ``tip_id`` (or None)."""
    return _FLASH_TIPS.get(tip_id)


def all_hints():
    return _HINTS


def persistent_hints():
    return tuple(hint.text for hint in _HINTS if hint.surface == "persistent")


def shortcut_tooltip(action_key):
    return _SHORTCUTS.get(action_key)


def context_hints(state, scope="chart"):
    matches = [
        hint for hint in _HINTS
        if hint.surface == "context"
        and hint.scope == scope
        and hint.id not in state.recently_used
        and not _retired_by_discovery(hint, state)
        and _matches_state(hint, state)
    ]
    return tuple(sorted(matches, key=_context_sort_key))


def rotation_hints(state, scope="chart"):
    """The full footer rotation pool for one lap.

    Merges the per-section ``anchor`` base-gesture hints with the ``context``
    tips and orders them by effective weight (descending), so the important
    base gesture leads and lingers while low-frequency tips still get a short
    turn each lap. The result is single-lap, mode-gated, and decays with use:

    * a context tip whose gesture the user just performed (id in
      ``recently_used``) drops out for the session;
    * a context tip whose capability has been discovered across sessions
      (``retire_when_discovered`` id in ``discovered``) drops out for good;
    * an ``anchor`` never disappears (the base gesture must stay reachable) but
      loses weight once used so it rotates to the back of the lap.
    """
    pool = []
    for hint in _HINTS:
        if hint.scope != scope:
            continue
        if hint.surface not in ("anchor", "context"):
            continue
        if not _matches_state(hint, state):
            continue
        if _retired_by_discovery(hint, state):
            continue
        used = hint.id in state.recently_used
        if used and hint.surface != "anchor":
            # Used-enough tips drop out of the lap (the system gets quieter as
            # the user demonstrates the gesture).
            if _RETIRE_AFTER_USES <= 1:
                continue
        pool.append((hint, used))
    return tuple(
        hint for hint, _used in sorted(pool, key=_rotation_sort_key)
    )


def rotation_dwell_ms(hint):
    """Variable dwell for the rotating footer hint (priority-derived default)."""
    if hint is None:
        return _DWELL_BASE_MS
    return hint.effective_dwell_ms()


def _effective_rotation_weight(hint, used):
    weight = hint.base_weight()
    if used:
        # Anchors stay in the lap (they reach here only when surface == anchor)
        # but sink toward the back once their gesture has been performed.
        weight -= _USED_WEIGHT_PENALTY
    return weight


def _rotation_sort_key(entry):
    hint, used = entry
    # Higher weight first; anchors before equal-weight context; stable by id.
    surface_rank = 0 if hint.surface == "anchor" else 1
    return (-_effective_rotation_weight(hint, used), surface_rank, hint.id)


def _retired_by_discovery(hint, state):
    echo = getattr(hint, "retire_when_discovered", None)
    return bool(echo) and echo in state.discovered


def discovery_hint(state, scope="chart"):
    candidates = [
        hint for hint in _HINTS
        if hint.surface == "discovery"
        and hint.scope == scope
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
