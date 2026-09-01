"""Curated chart hint registry.

The chart bar consumes this module instead of parsing design docs or keeping
free-floating hint strings in widget code.
"""
import math
import unicodedata
from dataclasses import dataclass, field

from PyQt5.QtCore import QSettings


DISCOVERED_SETTINGS_KEY = "chartHints/discovered"
ROTATION_START_KEY = "chartHints/rotationStart"


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

# Longer Inspector copy of ``time.drop_set_xaxis``. The footer discovery
# slot stays short (HINT_MAX_WIDTH); this sentence sits under the 横坐标
# 「应用」 button and can be dismissed into that footer.
XAXIS_DROP_PANEL_HINT = "可直接把通道拖到图底横坐标带，替换当前横坐标"
XAXIS_DROP_PANEL_DISMISSED_TOAST = "已收藏到左下角帮助提示"


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
    # ---- Situational signals (drive the ``nudge`` surface). These describe the
    # current DATA situation, not the page mode, so the footer can proactively
    # point at a capability the moment it becomes useful. All default to a calm
    # value so existing callers/tests are unaffected. ----
    channel_count: int = 0      # plotted channels (overlay/subplot)
    same_unit: bool = False     # all plotted channels share one unit
    has_axis_group: bool = False  # at least one shared-axis (共轴) group exists
    amp_disparate: bool = False  # one curve dwarfed by another (range ratio big)
    colorbar_dead: bool = False  # heatmap colour window collapsed to ~one colour
    clipped: bool = False        # a plotted signal looks saturated / clipped
    # dB-reference-defaults migration nudge (spec 2026-07-12 S5): the section's
    # CURRENT analysis View mode/value ("manual"/"auto" + the compound
    # control's numeric value) plus whether the focused source's Auto
    # resolution would actually differ from the legacy 1.0 default. All three
    # are read off the live Inspector/resolver state at signal-feed time, not
    # derived here -- this dataclass only carries the raw facts so the
    # predicate stays a pure, testable function of them.
    db_reference_mode: str = ""
    db_reference_value: float = 1.0
    db_reference_source_resolvable: bool = False


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
        id="toolbar.save_as_menu",
        text="保存旁箭头可另存为",
        surface="discovery",
        retire_on="save_as",
        priority=40,
    ),
    Hint(
        id="chart.copy_image",
        text="复制按钮导出带游标读数的图片并标注",
        surface="discovery",
        retire_on="copy_image",
        priority=95,
    ),
    Hint(
        id="channel.export_wwt_storage",
        text="通道编辑可导 WWT 无损·紧凑",
        surface="discovery",
        retire_on="export_wwt",
        priority=70,
    ),
    Hint(
        id="file.wwt_create_views",
        text="WWT 按 WinWert 窗口创建时域 View",
        surface="discovery",
        retire_on="wwt_create_views",
        priority=65,
    ),
    Hint(
        id="file.wwt_batch_choice",
        text="剩余 WWT 可沿用本次选择",
        surface="discovery",
        retire_on="wwt_batch_choice",
        priority=44,
    ),
    Hint(
        id="time.custom_x_paths",
        text="游标显示设置管极值点与差值；− 收 mini；X↑/X↓",
        surface="discovery",
        modes=frozenset({"time"}),
        retire_on="custom_x_dual_cursor",
        priority=43,
    ),
    Hint(
        id="chart.toolbar_pan",
        text="窄工具栏可横滑查看更多",
        surface="discovery",
        modes=frozenset({"time", "fft", "fft_time", "order", "frf"}),
        priority=41,
    ),
    Hint(
        id="time.record_curve_eye",
        text="所属文件下眼睛可单条隐藏",
        surface="discovery",
        modes=frozenset({"time"}),
        retire_on="record_curve_eye",
        priority=46,
    ),
    Hint(
        id="analysis.viewport_keep",
        text="分析图缩放会随 View 保存",
        surface="discovery",
        modes=frozenset({"fft", "fft_time", "order"}),
        retire_on="analysis_viewport",
        priority=54,
    ),
    Hint(
        id="ultraview.unplaced_badge",
        text="未放置角标直达托盘",
        surface="discovery",
        modes=frozenset({"time", "fft", "fft_time", "frf", "order"}),
        retire_on="ultraview_unplaced_badge",
        priority=56,
    ),
    Hint(
        id="chart.right_click_menu",
        text="右键图表 → 查看全部 · 轴范围 · 网格",
        surface="discovery",
        retire_on="chart_context_menu",
        priority=90,
    ),
    Hint(
        id="chart.custom_action_slot",
        text="右键鼠标行▾ → 换绑常用动作",
        surface="discovery",
        retire_on="custom_action_rebind",
        priority=50,
    ),
    Hint(
        id="chart.range_tab",
        text="轴范围 Tab 切换起止",
        surface="discovery",
        retire_on="range_tab",
        priority=49,
    ),
    Hint(
        id="batch.export_options",
        text="切片≤4仅FFT-时间/阶次 · 完成后开输出目录会记住",
        surface="discovery",
        retire_on="batch_open",
        priority=45,
    ),
    Hint(
        id="channel.right_click",
        text="左侧通道右键 → 设为叠加图左轴",
        surface="discovery",
        retire_on="channel_context_menu",
        priority=80,
    ),
    Hint(
        id="time.drop_join_view",
        text="拖通道到绘图区即可加入 View",
        surface="discovery",
        modes=frozenset({"time"}),
        priority=83,
    ),
    Hint(
        id="time.drop_set_xaxis",
        text="拖到底部横坐标带设为 X",
        surface="discovery",
        modes=frozenset({"time"}),
        priority=82,
    ),
    Hint(
        id="time.nav_reorder",
        text="通道树拖文件/通道排序，画布内不能拖行",
        surface="discovery",
        modes=frozenset({"time"}),
        priority=79,
    ),
    Hint(
        id="file.scope_follow",
        text="链接=文件范围跟随（加载/新建/切分析）",
        surface="discovery",
        priority=78,
    ),
    Hint(
        id="view.history",
        text="图表可后退/前进到上一个视图（Ctrl+Z）",
        surface="discovery",
        retire_on="view_history",
        priority=60,
        ship="later",
    ),
    # ---- 时域 View 标签栏紧凑态 (12-View 扩容 4abd5f4, shipped 2026-07-16) ----
    # Narrowing the window flips the tab bar to dot + ordinal labels
    # (view_tabbar._set_density), so the View NAMES disappear and live only in
    # the tooltip. The first narrow drag reads as "我的 View 名字哪去了", not
    # "这是紧凑模式" — the confusion this answers, exactly like the sibling
    # view.history entry above. Deliberately NOT a nudge: a nudge gates on a
    # HintState data signal fed by _ChartCard._nudge_signals(), and the tab bar
    # is a sibling widget that feeds nothing into that state.
    # Priority 65 seats it below coaxis.merge / channel.export_wwt_storage
    # (both 70) and above the custom-action slot (50). Retired by
    # view_tabbar._mark_compact_tabs_discovered() from BOTH the compact
    # tab's tooltip and the » menu — the
    # overflow menu alone would never fire for a row that compacts without
    # overflowing. The 24 cap and the » menu itself live in the quickref panel
    # (时域 View row); repeating them here would just be footer noise.
    Hint(
        id="view.compact_tabs",
        text="窄窗口 View 标签只剩编号，悬停可看全名",
        surface="discovery",
        modes=frozenset({"time"}),
        retire_on="view_tab_compact_seen",
        priority=65,
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
        text="双击曲线或其 Y 轴 → 改颜色/范围",
        surface="context",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay"}),
        priority=100,
    ),
    Hint(
        id="subplot.wheel_target",
        text="滚轮作用于鼠标所在分屏图",
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
    # ---- 频响（FRF）----
    # The explicit toolbar control enables the shared three-plot frequency
    # cursor. The threshold only affects presentation; the explicit action
    # copies a time range once and is never a live pan/zoom subscription.
    Hint(
        id="frf.linked_cursor",
        text="工具栏：关/单/双游标，三图双游标读数 Δf",
        surface="context",
        modes=frozenset({"frf"}),
        priority=120,
        dwell_ms=8000,
    ),
    Hint(
        id="fft.frequency_cursor",
        text="频谱工具栏：关/单/双游标，双游标读 Δf",
        surface="context",
        modes=frozenset({"fft"}),
        priority=120,
        dwell_ms=8000,
    ),
    Hint(
        id="frf.coherence_display_only",
        text="相干阈值只影响显示，不改数据",
        surface="context",
        modes=frozenset({"frf"}),
        priority=110,
    ),
    Hint(
        id="frf.custom_x_limit",
        text="自定义 X 不是秒，不能作频响范围",
        surface="context",
        modes=frozenset({"frf"}),
        priority=90,
    ),
    Hint(
        id="frf.view_in_time_domain",
        text="时域查看新建或复用对应 View",
        surface="context",
        modes=frozenset({"frf"}),
        priority=80,
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
        modes=frozenset({"fft", "frf", "order"}),
        requires=frozenset({"annotation_on"}),
        priority=100,
    ),
    Hint(
        id="subplot.shift_y",
        text="Shift + 滚轮：缩放鼠标所在分屏图 Y 轴",
        surface="context",
        tier="A",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"subplot"}),
        priority=80,
    ),
    Hint(
        id="zoom.guard",
        text="框选 → X/Y 同缩 · 各通道按比例缩 Y",
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
    # spectrum): click a curve to choose the source; preview Y follows the
    # TimeDomain overlay wheel contract (plain=pan, Shift=zoom, gutter=one axis).
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
        text="预览：平滚轮平移 Y · Shift 缩放 Y · Ctrl 缩放 X",
        surface="context",
        tier="A",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=55,
    ),
    Hint(
        id="fft.time_range_manual",
        text="预览缩放只改起止；勾选后才用于计算",
        surface="context",
        tier="A",
        modes=frozenset({"fft"}),
        priority=70,
    ),
    Hint(
        id="analysis.time_range_confirm",
        text="局部起止未勾选时，计算前会询问",
        surface="context",
        tier="A",
        modes=frozenset({"fft", "fft_time", "order", "frf"}),
        priority=68,
    ),
    Hint(
        id="fft.preview_axis_gutter",
        text="滚轮停在预览左/右 Y 轴上 → 只调该通道",
        surface="context",
        tier="B",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=50,
    ),
    Hint(
        id="fft.preview_left_axis",
        text="预览右键曲线/右轴 → 设为左轴",
        surface="context",
        tier="B",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=48,
    ),
    Hint(
        id="fft.preview_dblclick",
        text="双击预览曲线或 Y 轴 → 编辑颜色/坐标",
        surface="context",
        tier="B",
        modes=frozenset({"fft"}),
        chart_kinds=frozenset({"fft"}),
        priority=46,
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
    # ---- 分析信号选择范围 (View-scoped pickers) ----
    # The 信号 pickers used to enumerate every loaded file; they now offer only
    # the active analysis section View's attached files (not the time View).
    # The failure this answers is silent: files open globally, one in the
    # analysis View, and the user searches for a channel that simply is not
    # listed. Nothing on screen explains the scope, and there is no gesture to
    # discover — so this is a context hint on the analysis sections rather than
    # a discovery entry that retires once exercised.
    # Deliberately NOT a nudge: nudge predicates read HintState signals fed by
    # _ChartCard._nudge_signals(), and View attachment is navigator state that
    # never reaches it (same reasoning as view.compact_tabs above).
    # Priority 75 seats it under the sections' headline gestures (slice at 100)
    # and level with fft.preview_pick_source.
    Hint(
        id="analysis.view_scope",
        text="分析按当前分析 View 列文件；× 从该 View 移除",
        surface="context",
        modes=frozenset({"fft", "fft_time", "frf", "order"}),
        priority=75,
    ),
    # ---- 共轴组 (shared-axis groups): shipped 2026-06-27. Designed in
    # 2026-06-24-overlay-shared-axis-and-channel-indent-design.md, landed and
    # user-verified on-device. coaxis.merge is a discovery hint retired by the
    # channel-tree axis-group menu opening (mark_discovered("coaxis.merge") in
    # MultiFileChannelWidget._on_context_menu); coaxis.gesture is a context tier-A
    # tip. Both apply to overlay AND subplot (shared Y = compare amplitude).
    Hint(
        id="coaxis.merge",
        text="多选通道右键可合并为共轴比幅值",
        surface="discovery",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay", "subplot"}),
        retire_on="axis_group_menu",
        priority=70,
    ),
    Hint(
        id="coaxis.gesture",
        text="Ctrl/Shift 多选通道，右键合并为共轴",
        surface="context",
        tier="A",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay", "subplot"}),
        priority=70,
    ),
    # ---- Situational nudges (surface="nudge"): condition-gated, shown in the
    # footer's discovery slot only while their data predicate (see
    # _NUDGE_PREDICATES) holds. They self-clear when the situation clears and
    # retire for good once the capability is discovered. ----
    Hint(
        id="nudge.coaxis",
        text="通道多？多选右键合并共轴比幅值",
        surface="nudge",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay", "subplot"}),
        priority=80,
        retire_when_discovered="coaxis.merge",
    ),
    Hint(
        id="nudge.colorbar_dead",
        text="画面发黑？双击 colorbar 重置色阶",
        surface="nudge",
        modes=frozenset({"fft_time", "order"}),
        chart_kinds=frozenset({"fft_time", "order"}),
        priority=75,
        retire_when_discovered="spectrogram.colorbar",
    ),
    Hint(
        id="nudge.amp_disparate",
        text="某条太小？滚轮停在它 Y 轴上单独放大",
        surface="nudge",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay"}),
        priority=70,
    ),
    Hint(
        id="nudge.too_many",
        text="通道太多？Ctrl+1 切分屏更清晰",
        surface="nudge",
        modes=frozenset({"time"}),
        plot_modes=frozenset({"overlay"}),
        priority=60,
    ),
    Hint(
        id="nudge.clipped",
        text="信号疑似裁剪，峰值可能失真",
        surface="nudge",
        modes=frozenset({"time"}),
        priority=40,
    ),
    # dB-reference-defaults Task 10A (spec S5): every pre-existing View/preset/
    # project migrates to a manual View pinned at the old 1.0 default (spec
    # §13 S5 -- intentional, not a bug). Without this nudge those users would
    # never discover the new Auto (随通道自动) mode. Self-clears the moment the
    # user switches to Auto or edits the manual value away from 1.0 (no
    # retire_when_discovered needed -- unlike coaxis/colorbar_dead, the
    # underlying config fact itself flips, same as amp_disparate/clipped).
    Hint(
        id="nudge.db_ref_manual_default",
        text="手动dB参考1.0，可切自动",
        surface="nudge",
        modes=frozenset({"fft", "fft_time", "order"}),
        priority=50,
    ),
    Hint(
        id="ultraview.view_rail",
        text="View 栏右侧 UltraView 可打开只读总览",
        surface="discovery",
        modes=frozenset({"time", "fft", "fft_time", "frf", "order"}),
        priority=58,
    ),
    Hint(
        id="ultraview.add_from_tab",
        text="View 标签右键可加入总览",
        surface="discovery",
        modes=frozenset({"time", "fft", "fft_time", "frf", "order"}),
        priority=55,
    ),
    Hint(
        id="ultraview.empty_board",
        text="空板时左侧实心按钮打开 View 库添加对比",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=92,
    ),
    Hint(
        id="ultraview.card_action_visibility",
        text="右上显示可设卡片操作常驻或悬停",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=68,
    ),
    Hint(
        id="ultraview.direct_manip",
        text="直接拖卡片即可移动，不必再按 Option",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=91,
    ),
    Hint(
        id="ultraview.readonly",
        text="总览只读，不重新计算",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=90,
    ),
    Hint(
        id="ultraview.sticky",
        text="N 单击开 16 色便签，Stack 连续放",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=87,
    ),
    Hint(
        id="ultraview.text",
        text="T 点画布加文字，整框改格式",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=86,
    ),
    Hint(
        id="ultraview.shapes",
        text="S 开形状与连接线，L 直达直线",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=85,
    ),
    Hint(
        id="ultraview.existing_markup",
        text="P 开画笔三笔触，V/Esc 回选择",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=84,
    ),
    Hint(
        id="ultraview.oneshot",
        text="一次回选择，双击固定才连续",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=82,
    ),
    Hint(
        id="ultraview.pointer",
        text="整块单击指针，弹出鼠标/激光笔",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=84,
    ),
    Hint(
        id="ultraview.laser",
        text="激光笔仅换光标；选择、移动、缩放不变",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=83,
    ),
    Hint(
        id="ultraview.select_keys",
        text="V 保持光标样式进入选择，Esc 清选择",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=83,
    ),
    Hint(
        id="ultraview.multiselect",
        text="多选可对齐分布，Ctrl+D 复制",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=81,
    ),
    Hint(
        id="ultraview.free_grid",
        text="自由网格可扩展，窄轨切回模板",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=88,
    ),
    Hint(
        id="ultraview.resize",
        text="选中后拖边角改尺寸，便签可成正方形",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=87,
    ),
    Hint(
        id="ultraview.avoid",
        text="拖到边缘可扩展；硬拒绝会说明下一步",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=85,
    ),
    Hint(
        id="ultraview.replace_ring",
        text="拖入卡面出替换环，否则附近插入",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=84,
    ),
    Hint(
        id="ultraview.undo",
        text="移动、调整或移除可用 Ctrl/Cmd+Z 撤销",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=86,
    ),
    Hint(
        id="ultraview.preset",
        text="右键尺寸预设，按原图比例在右上角",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=84,
    ),
    Hint(
        id="ultraview.autofit",
        text="按原图比例只收紧当前卡",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=83,
    ),
    Hint(
        id="ultraview.minimap",
        text="缩略图仅自由网格滚动时出现",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=83,
    ),
    Hint(
        id="ultraview.zoom",
        text="切板适应内容≤300%，100%不挪中心",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=89,
    ),
    Hint(
        id="ultraview.inspect",
        text="双击临时聚焦≤300%，Esc返回",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=88,
    ),
    Hint(
        id="ultraview.pan",
        text="左键框选，右键拖动画布，四向可平移",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=89,
    ),
    Hint(
        id="ultraview.remove",
        text="从 Board 移除不删源 View",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=85,
    ),
    Hint(
        id="ultraview.lod",
        text="六成完整四成紧凑，更低标题仍见类型",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=88,
    ),
    Hint(
        id="ultraview.boards",
        text="Board 弹层点行切换，拖拽复制或删除",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=82,
    ),
    Hint(
        id="ultraview.limits",
        text="已放24张、成员200；12列是标尺",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=81,
    ),
    Hint(
        id="ultraview.card_menu",
        text="右上打开聚焦，更多可锁定",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=80,
    ),
    Hint(
        id="ultraview.board_menu",
        text="空白右击智能排版或紧凑排列",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=80,
    ),
    Hint(
        id="ultraview.sync",
        text="源已变化时可同步最新预览",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=79,
    ),
    Hint(
        id="ultraview.resolution",
        text="预览偏低时打开源 View 更新",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=77,
    ),
    Hint(
        id="ultraview.sync_all",
        text="左栏可一键更新已变化源",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=78,
    ),
    Hint(
        id="ultraview.escape",
        text="Esc 取消拖动、清选、退出聚焦与演示",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=70,
    ),
    Hint(
        id="ultraview.export",
        text="导出 PNG 按适应内容裁切，不含空白底板",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=60,
    ),
    Hint(
        id="ultraview.tray",
        text="左侧窄轨的未放置入口保留全部托盘动作",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=50,
    ),
    Hint(
        id="ultraview.statuses",
        text="卡片四态：新、旧、缺、孤儿",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=45,
    ),
    Hint(
        id="ultraview.presentation",
        text="右上浮岛进入演示并隐藏编辑控件，Esc 退出",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=40,
    ),
    Hint(
        id="ultraview.display",
        text="显示：标题/来源；常驻操作随工程保存",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=35,
    ),
    Hint(
        id="ultraview.library_fold",
        text="View 库按类型分组，标题可折叠",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=33,
    ),
    Hint(
        id="ultraview.library_pin",
        text="View 库钉住后点画布不收起，Esc 仍关闭",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=33,
    ),
    Hint(
        id="ultraview.library_toggle",
        text="View 库浮层中可将 View 加入或移出 Board",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=32,
    ),
    Hint(
        id="ultraview.idle",
        text="停手后跟上图面，含游标标注",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=32,
    ),
    Hint(
        id="ultraview.filter",
        text="左侧漏斗筛选；不一致会提示",
        surface="context",
        modes=frozenset({"ultraview"}),
        priority=82,
    ),
)


# Situational-nudge predicates over HintState data signals, keyed by hint id.
# Kept beside the registry so the trigger condition lives next to the text.
_NUDGE_PREDICATES = {
    "nudge.coaxis": lambda s: (
        s.channel_count >= 4 and s.same_unit and not s.has_axis_group
    ),
    "nudge.colorbar_dead": lambda s: s.colorbar_dead,
    "nudge.amp_disparate": lambda s: s.amp_disparate and not s.has_axis_group,
    "nudge.too_many": lambda s: s.channel_count >= 8,
    "nudge.clipped": lambda s: s.clipped,
    "nudge.db_ref_manual_default": lambda s: (
        s.db_reference_mode == "manual"
        and math.isclose(s.db_reference_value, 1.0, rel_tol=1e-9, abs_tol=1e-9)
        and s.db_reference_source_resolvable
    ),
}


# Discovery-style tips that are surfaced by an in-app gesture (mark_discovered /
# flash) rather than the rotating pool. They live in the registry so the wiring
# in chart_stack / inspector points at a single source of truth for the text.
_FLASH_TIPS = {
    "spectrogram.slice_pick": "已取该帧切片 · 也可拖动切片标记线移动取样位置",
    "spectrogram.colorbar": "拖 colorbar 调色阶 · 双击 colorbar 可重置范围",
    "spectrogram.divider": "拖上下分隔条调高度 · 双击重置 · 底部可折叠/展开",
    "fft.preview_source": "已选为时域预览的源 · 平滚轮平移 Y · Shift/Ctrl 缩放 · 右键可设左轴",
    "preset.right_click": "预设槽右键可保存 / 重命名 / 重置为默认",
}


def flash_tip(tip_id):
    """Return the curated flash-tip text for ``tip_id`` (or None)."""
    return _FLASH_TIPS.get(tip_id)


def hint_text(hint_id):
    """Return the registry text for ``hint_id``, or ``None`` if unknown."""
    for hint in _HINTS:
        if hint.id == hint_id:
            return hint.text
    return None


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
        and _is_shipped(hint)
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
        if not _is_shipped(hint):
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


def _is_shipped(hint):
    """A hint with ``ship != "now"`` is registered but surfaced nowhere yet.

    Used to pre-stage hints for in-flight features: the entry lives in the
    registry (tracked, width-checked) but is filtered out of every surface
    (discovery, context, rotation) until its ``ship`` flips to ``"now"``.
    """
    return hint.ship == "now"


def discovery_hint(state, scope="chart"):
    candidates = [
        hint for hint in _HINTS
        if hint.surface == "discovery"
        and hint.scope == scope
        and _is_shipped(hint)
        and hint.id not in state.discovered
        and _matches_state(hint, state)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda hint: -hint.priority)[0]


def nudge_hint(state, scope="chart"):
    """The single highest-priority situational nudge for ``state`` (or None).

    A nudge surfaces only while its data predicate holds (so it self-clears when
    the situation clears) and it has not been retired by discovery. It is a
    separate surface from discovery/context/rotation — see ``_NUDGE_PREDICATES``
    for the trigger conditions.
    """
    candidates = [
        hint for hint in _HINTS
        if hint.surface == "nudge"
        and hint.scope == scope
        and _is_shipped(hint)
        and hint.id not in state.discovered
        and not _retired_by_discovery(hint, state)
        and _matches_state(hint, state)
        and _nudge_predicate_ok(hint, state)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda hint: -hint.priority)[0]


def _nudge_predicate_ok(hint, state):
    pred = _NUDGE_PREDICATES.get(hint.id)
    return bool(pred(state)) if pred is not None else False


def next_rotation_start(settings):
    """Return the persisted rotation-start offset, then advance it by one.

    The footer pool still leads with the high-weight anchor, but the card enters
    the lap at this round-robin offset so a fresh open does not always show the
    same (wheel-zoom) anchor first. Deterministic and persisted across sessions;
    a garbage stored value resets cleanly to 0.
    """
    raw = settings.value(ROTATION_START_KEY, 0)
    try:
        start = int(raw)
    except (TypeError, ValueError):
        start = 0
    if start < 0:
        start = 0
    settings.setValue(ROTATION_START_KEY, start + 1)
    settings.sync()
    return start


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
