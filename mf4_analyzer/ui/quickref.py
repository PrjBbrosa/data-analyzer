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
    wide  — True spans two grid columns (the 五个分析模式 group).
    """

    title: str
    rows: Tuple[QuickRow, ...]
    note: str = ""
    wide: bool = False


# Per-mode accent colors (blue/orange/green/teal/violet). These are CHART/data
# accents, intentionally distinct from the
# UI chrome accent (#1769e0) so they read as mode tags, not selection chrome.
_MODE_TIME = "#3f7fc4"
_MODE_FFT = "#e0883c"
_MODE_FFT_TIME = "#6a8f4f"
_MODE_FRF = "#168f91"
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
            QuickRow("BLF / CANoe ASC 报文解码", sub="需配 DBC 文件"),
            QuickRow(
                "把文件加入当前 View",
                sub="上方=全局已打开；下方=当前模式的当前 View。打开只是载入，要画图/分析得先加入",
                gesture="从文件列表拖到通道树",
            ),
            QuickRow(
                "文件范围跟随",
                sub="链接菜单三项：新文件加入当前 View · 新建 View 继承文件范围 · 切换分析时填充空 View（全关=不跟随）",
                gesture="文件区链接图标",
            ),
            QuickRow("保存会话", gesture=".tlproj 项目"),
            QuickRow("软件说明书", gesture="右下角 📖"),
        ),
    ),
    # 2 — 五个分析模式 (wide, spans two columns)
    QuickGroup(
        title="五个分析模式",
        note="不知道用哪个？先看这里",
        wide=True,
        rows=(
            QuickRow(
                "时域",
                sub="看信号随时间变化（波形、对比、统计）",
                accent=_MODE_TIME,
            ),
            QuickRow(
                "频谱",
                sub="看频率成分有多少（频谱、可平均）",
                accent=_MODE_FFT,
            ),
            QuickRow(
                "时频",
                sub="看频率随时间怎么变（谱图 / 热力图）",
                accent=_MODE_FFT_TIME,
            ),
            QuickRow(
                "阶次",
                sub="按电机转速跟踪频率（EPS 电机转速为 base）",
                accent=_MODE_ORDER,
            ),
            QuickRow(
                "频响",
                sub="频响（FRF / 系统辨识）：看输出相对输入",
                accent=_MODE_FRF,
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
                "FFT 时域预览",
                gesture="平滚轮 / Y 轴槽 / 右键 / 双击",
                sub="平移·Shift缩Y·Ctrl缩X；缩放只改起止，勾选才用于计算；轴槽单通道；设左轴",
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
            QuickRow(
                "切换当前分区 View",
                keys=("Alt+1…9",),
                sub="第 10–12 个走标签栏或 » 溢出菜单",
            ),
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
                sub="Ctrl+单击不连续多选；Shift+单击连续范围",
                gesture="多选后右键",
            ),
            QuickRow(
                "看通道全名",
                sub="名字过长时中间省略，首尾都保留",
                gesture="悬停通道名",
            ),
            QuickRow(
                "分析信号的可选范围",
                sub="FFT / 时频 / 频响 / 阶次各自只列该分析 View 已加入的文件，不跟随时域 View",
            ),
            QuickRow(
                "从当前 View 移除文件",
                sub="时域、频谱、时频、频响、阶次都可用；文件行右侧悬停显示 ×",
                gesture="点击「显示」列的 ×",
            ),
        ),
    ),
    # 6 — 通道编辑（派生通道）
    QuickGroup(
        title="通道编辑（派生通道）",
        rows=(
            QuickRow("打开通道编辑", gesture="通道树下方「编辑通道」"),
            QuickRow(
                "单通道运算",
                sub="d/dt · ∫dt · ×系数 · +偏移 · 滑动平均 · |x|",
            ),
            QuickRow(
                "双通道运算",
                sub="A+B · A−B · A×B · A÷B · max(A,B) · min(A,B)",
            ),
            QuickRow(
                "自定义表达式",
                sub="运算选「自定义表达式…」；A / B / t 加括号系数与 "
                    "sqrt abs log min max mean where，^ 为幂",
            ),
            QuickRow(
                "表达式帮助卡片",
                sub="示例与全部函数一览，可拖到旁边边看边写",
                gesture="点表达式右侧「?」",
            ),
            QuickRow(
                "删除通道",
                sub="在「导出 / 删除」区勾选通道，点红色删除；确定才生效",
            ),
        ),
    ),
    # 7 — 游标
    QuickGroup(
        title="游标",
        rows=(
            QuickRow("单游标", keys=(_sc("cursor_single"),)),
            QuickRow(
                "双游标",
                sub="点 A 点 B → ΔT 与区间统计",
                keys=(_sc("cursor_dual"),),
            ),
            QuickRow(
                "频谱 / 频响游标",
                sub="工具栏选关 / 单 / 双；双游标读 A/B、突出 Δf 与 ΔY；每个 pane 记住，默认关闭",
            ),
        ),
    ),
    # 8 — 谱图（FFT-时间 / 阶次）
    QuickGroup(
        title="谱图（FFT-时间 / 阶次）",
        rows=(
            QuickRow("取频率 / 阶次切片", gesture="点击谱图某时刻"),
            QuickRow("调色阶", sub="双击重置", gesture="拖 colorbar"),
            QuickRow("调谱图/切片高度", sub="双击重置", gesture="拖分隔条"),
        ),
    ),
    # 9 — dB 参考（FFT / FFT-时间 / 阶次）
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
    # 10 — 标注
    QuickGroup(
        title="标注",
        rows=(
            QuickRow(
                "开启标注",
                sub="时域、频谱、时频、频响、阶次图表均可用",
                gesture="工具栏按钮",
            ),
            QuickRow("添加 / 删除最近", gesture="左键加 · 右键删"),
            QuickRow("清除当前图表标注", gesture="工具栏橡皮擦按钮"),
        ),
    ),
    # 11 — 预设
    QuickGroup(
        title="预设",
        rows=(
            QuickRow("保存当前分析参数", gesture="预设槽"),
            QuickRow("重命名 / 重置", gesture="右键预设槽"),
        ),
    ),
    # 12 — 导出 · 复制
    QuickGroup(
        title="导出 · 复制",
        rows=(
            QuickRow(
                "复制为图片",
                sub="含游标线和读数，可标注",
                gesture="复制按钮",
            ),
            QuickRow(
                "导出 Excel / WWT",
                sub="WWT：任意格式转 WinWert，保留原采样率，按时域显示",
            ),
            QuickRow(
                "导出图像 / 数据",
                sub="PNG · SVG · CSV",
                gesture="右键 → 导出",
            ),
        ),
    ),
    # 13 — 批处理
    QuickGroup(
        title="批处理",
        rows=(
            QuickRow("打开批处理", gesture="工具栏「批处理」"),
            QuickRow(
                "添加来源",
                sub="从已打开的文件选，或直接从磁盘添加",
                gesture="+ 已加载 / + 从磁盘…",
            ),
            QuickRow(
                "选目标信号",
                sub="点开后直接打字筛选；再点条目勾选 / 取消",
                gesture="目标信号行",
            ),
            QuickRow(
                "批量勾选",
                sub="全选当前筛选结果 · 清空全部已选",
                gesture="弹层底部",
            ),
            QuickRow(
                "已选摘要",
                sub="收起后只显示第一个信号名 +「+N」徽章，悬停看全部",
            ),
            QuickRow(
                "RPM 通道",
                sub="单选，只能选一个通道；系数把原始值换算成 RPM",
            ),
            QuickRow(
                "频响输入 / 输出配对",
                sub="同一来源（logical source）内选一个输入和多个输出；不把跨来源通道配成一对",
            ),
            QuickRow(
                "频响缺通道策略",
                sub="common 要求每个来源都有完整配对；available_per_source 明确跳过并告警",
            ),
            QuickRow(
                "频响图片组织",
                sub="每对一张（默认）· 按来源叠加 · 按输入/输出对叠加",
            ),
            QuickRow(
                "刻度与字体",
                sub="疏 / 标准 / 密 三档 + 字号缩放，只影响导出图片",
                gesture="刻度与字体",
            ),
            QuickRow(
                "导出切片",
                sub="仅 FFT-时间 / 阶次；最多 4 个位置，中英文逗号均可，叠加对比；数据文件同步改成切片结果",
            ),
            QuickRow(
                "完成后打开输出目录",
                sub="可开关；选择会记住，并作为导出偏好自动带到下次",
            ),
            QuickRow(
                "记住导出偏好",
                sub="输出目录、导出内容、刻度与字体自动带到下次；文件与信号不记",
                gesture="恢复默认",
            ),
            QuickRow(
                "存 / 读方案",
                sub="整套批处理设置存成 JSON，与分析预设槽相互独立",
                gesture="导入方案… / 导出方案…",
            ),
        ),
    ),
    # 14 — 右键菜单
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
