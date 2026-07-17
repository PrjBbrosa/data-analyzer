"""操作速查 (Quick-Reference) catalog — pure data the panel renders.

This is the single structured source for the in-app "一屏看全所有操作" panel
(see ``docs/superpowers/specs/2026-06-25-operations-quickref-panel-design.md``).
It is intentionally free of any Qt import so the catalog can be imported and
asserted on without a QApplication.

Keyboard chips are NOT hardcoded: every shortcut string is pulled from the
shortcut registry in :mod:`mf4_analyzer.ui.hints` via the :func:`_sc` helper, so
a rebind in the registry flows here automatically and a missing key surfaces as
a ``KeyError`` instead of a silently blank chip.

Distinct chip kinds (the panel styles them differently, per the design):

* ``keys`` — a tuple of keyboard chips (gray kbd style), joined with ``+`` / ``/``
  exactly as written (each element is one chip).
* ``gesture`` — a single mouse-gesture chip (blue pill).

A row may carry both (e.g. 复位视图 = ``Ctrl+R`` keyboard chip OR a 双击 gesture).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from . import hints


def _sc(action_key: str) -> str:
    """Resolve a shortcut string from the hints registry — the single source.

    Raises ``KeyError`` if the key is unknown, so a renamed/removed registry
    entry surfaces loudly at import time instead of rendering a blank chip.
    """
    value = hints.shortcut_tooltip(action_key)
    if not value:
        raise KeyError(
            f"quickref: shortcut key {action_key!r} is not in hints registry"
        )
    return value


@dataclass(frozen=True)
class QuickRow:
    """One operation row in a group.

    desc    — primary action description (always present).
    sub     — optional one-line secondary detail (rendered smaller/dimmer).
    keys    — tuple of keyboard chips (gray kbd style); each element is one chip.
    gesture — optional single mouse-gesture chip (blue pill).
    soon    — True attaches an "即将" badge (staged-but-unshipped capability).
    accent  — optional per-row left-bar color hex (used by the modes group).
    """

    desc: str
    sub: str = ""
    keys: Tuple[str, ...] = ()
    gesture: str = ""
    soon: bool = False
    accent: str = ""


@dataclass(frozen=True)
class QuickGroup:
    """A titled group of rows.

    title — section heading.
    rows  — ordered rows.
    note  — optional right-aligned header note (e.g. "不知道用哪个？先看这里").
    wide  — True spans two grid columns (the 四个分析模式 group).
    """

    title: str
    rows: Tuple[QuickRow, ...]
    note: str = ""
    wide: bool = False


# Per-mode accent colors (match the mockup's four left color bars: blue/orange/
# green/violet). These are CHART/data accents, intentionally distinct from the
# UI chrome accent (#1769e0) so they read as mode tags, not selection chrome.
_MODE_TIME = "#3f7fc4"
_MODE_FFT = "#e0883c"
_MODE_FFT_TIME = "#6a8f4f"
_MODE_ORDER = "#9b6bd0"


QUICKREF: Tuple[QuickGroup, ...] = (
    # 1 — 开始 · 文件
    QuickGroup(
        title="开始 · 文件",
        rows=(
            QuickRow("打开数据 / 项目", gesture="工具栏「打开」"),
            QuickRow(
                "支持格式",
                sub="MF4 · MDF · BLF · ASCII · TDMS · WWT · ZFD · MAT · 表格 · HDF · 音视频",
            ),
            QuickRow("BLF 报文解码", sub="需配 DBC 文件"),
            QuickRow("保存会话", gesture=".tlproj 项目"),
            QuickRow("软件说明书", gesture="右下角 📖"),
        ),
    ),
    # 2 — 四个分析模式 (wide, spans two columns)
    QuickGroup(
        title="四个分析模式",
        note="不知道用哪个？先看这里",
        wide=True,
        rows=(
            QuickRow(
                "时域",
                sub="看信号随时间变化（波形、对比、统计）",
                accent=_MODE_TIME,
            ),
            QuickRow(
                "FFT",
                sub="看频率成分有多少（频谱、可平均）",
                accent=_MODE_FFT,
            ),
            QuickRow(
                "FFT-时间",
                sub="看频率随时间怎么变（谱图 / 热力图）",
                accent=_MODE_FFT_TIME,
            ),
            QuickRow(
                "阶次",
                sub="按电机转速跟踪频率（EPS 电机转速为 base）",
                accent=_MODE_ORDER,
            ),
        ),
    ),
    # 3 — 图表手势
    QuickGroup(
        title="图表手势",
        rows=(
            QuickRow("缩放 X", keys=("Ctrl", "滚轮")),
            QuickRow("缩放 Y", keys=("Shift", "滚轮")),
            QuickRow(
                "框选缩放",
                sub="X/Y 同缩，所有通道各自按比例",
                gesture="拖框",
            ),
            QuickRow("平移", gesture="直接拖动"),
            QuickRow(
                "单独调某通道 Y（叠加）",
                gesture="滚轮停在该通道 Y 轴上",
                sub="Shift+滚轮缩放，平滚轮平移",
            ),
            QuickRow(
                "编辑某曲线颜色/坐标（叠加）",
                gesture="双击曲线或其 Y 轴",
            ),
            QuickRow("复位视图", keys=(_sc("home"),), gesture="双击"),
            QuickRow("后退 / 前进视图", keys=(_sc("back"),)),
            QuickRow("时域 View", sub="最多 12 个；窄窗口点「»」切换收纳的 View"),
        ),
    ),
    # 4 — 快捷键
    QuickGroup(
        title="快捷键",
        rows=(
            QuickRow(
                "分屏 / 叠加",
                keys=(_sc("btn_subplot"), _sc("btn_overlay")),
            ),
            QuickRow(
                "游标 关 / 单 / 双",
                keys=(_sc("cursor_off"), _sc("cursor_single"), _sc("cursor_dual")),
            ),
            QuickRow(
                "平移 / 框选模式",
                keys=(_sc("pan"), _sc("zoom")),
            ),
            QuickRow("复位主视图", keys=(_sc("home"),)),
            QuickRow("顶部按钮的快捷键", sub="悬停按钮即显示"),
        ),
    ),
    # 5 — 通道树（左侧）
    QuickGroup(
        title="通道树（左侧）",
        rows=(
            QuickRow("绘制 / 取消通道", gesture="勾选复选框"),
            QuickRow("设为叠加图左轴", gesture="右键通道"),
            QuickRow(
                "合并为共轴比幅值",
                keys=("Ctrl/Shift",),
                gesture="多选右键",
            ),
        ),
    ),
    # 6 — 游标
    QuickGroup(
        title="游标",
        rows=(
            QuickRow("单游标", keys=(_sc("cursor_single"),)),
            QuickRow(
                "双游标",
                sub="点 A 点 B → ΔT 与区间统计",
                keys=(_sc("cursor_dual"),),
            ),
        ),
    ),
    # 7 — 谱图（FFT-时间 / 阶次）
    QuickGroup(
        title="谱图（FFT-时间 / 阶次）",
        rows=(
            QuickRow("取频率 / 阶次切片", gesture="点击谱图某时刻"),
            QuickRow("调色阶", sub="双击重置", gesture="拖 colorbar"),
            QuickRow("调谱图/切片高度", sub="双击重置", gesture="拖分隔条"),
        ),
    ),
    # 8 — dB 参考（FFT / FFT-时间 / 阶次）
    QuickGroup(
        title="dB 参考（FFT / FFT-时间 / 阶次）",
        rows=(
            QuickRow(
                "A / M 徽标",
                sub="蓝色 A = 随通道自动跟随 · 琥珀 M = 手动锁定",
            ),
            QuickRow(
                "手输数值",
                sub="回车 / 失焦提交 → 自动切换为手动",
            ),
            QuickRow(
                "管理默认值",
                sub="新增/编辑单位的系统与用户默认参考值",
                gesture="tune 按钮",
            ),
        ),
    ),
    # 9 — 标注
    QuickGroup(
        title="标注",
        rows=(
            QuickRow("开启标注", gesture="工具栏按钮"),
            QuickRow("添加 / 删除最近", gesture="左键加 · 右键删"),
        ),
    ),
    # 10 — 预设
    QuickGroup(
        title="预设",
        rows=(
            QuickRow("保存当前分析参数", gesture="预设槽"),
            QuickRow("重命名 / 重置", gesture="右键预设槽"),
        ),
    ),
    # 11 — 导出 · 复制
    QuickGroup(
        title="导出 · 复制",
        rows=(
            QuickRow(
                "复制为图片",
                sub="含游标线和读数，可标注",
                gesture="复制按钮",
            ),
            QuickRow("导出 Excel", sub="选定通道，可限时间段"),
            QuickRow(
                "导出图像 / 数据",
                sub="PNG · SVG · CSV",
                gesture="右键 → 导出",
            ),
        ),
    ),
    # 12 — 右键菜单
    QuickGroup(
        title="右键菜单",
        rows=(
            QuickRow(
                "图表右键",
                sub="查看全部 · 轴范围 · 鼠标模式 · 网格 · 自定义动作",
            ),
            QuickRow(
                "换绑自定义动作",
                sub="复制 / 上一步 / 下一步 / 导出",
                gesture="鼠标行第三槽▾",
            ),
            QuickRow("通道右键", sub="设左轴 / 共轴"),
        ),
    ),
)


def search_text(row: QuickRow) -> str:
    """Lowercased haystack for live filtering (desc + sub + every chip)."""
    parts = [row.desc, row.sub, *row.keys]
    if row.gesture:
        parts.append(row.gesture)
    return " ".join(p for p in parts if p).lower()
