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
from .command_registry import CommandId


def command_shortcut_text(command_id: CommandId) -> str:
    """Project command shortcut copy through the shared hints adapter."""
    return hints.command_shortcut_text(command_id)


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
    wide  — True spans two grid columns (the 五个分析工作区 + 总览 group).
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
_MODE_ULTRAVIEW = "#5b6775"


QUICKREF: Tuple[QuickGroup, ...] = (
    # 1 — 开始 · 文件
    QuickGroup(
        title="开始 · 文件",
        rows=(
            QuickRow(
                "打开数据 / 项目",
                sub="箭头可搜索最近 10 个项目与 40 个文件；按文件名或路径筛选；缺失项灰显不可打开；可清除记录。",
                keys=(command_shortcut_text(CommandId.OPEN_RECENT),),
                gesture="工具栏「打开」",
            ),
            QuickRow(
                "支持格式",
                sub="MF4 · MDF · BLF · ASCII · TDMS · WWT · ZFD · MAT · 表格 · HDF · 音视频",
            ),
            QuickRow(
                "WWT WinWert 视图",
                sub="按 WinWert 窗口创建时域 View 并绘图，不会自动加入 UltraView 或改变 Board；之后可正常使用 TraceLab Canvas。需要总览时手动把 View 加入 UltraView，再用智能排版；选择「仅加载数据」则不创建 View。",
            ),
            QuickRow(
                "WinWert 曲线自带横坐标",
                sub="record-only 或独立 XY 曲线在右侧显示「曲线自带」，使用文件内各自绑定的 X；原始首帧可以裁剪完整数据，点 Home 仍可查看全部。",
            ),
            QuickRow("BLF / CANoe ASC 报文解码", sub="选择 DBC；界面会标注「完整匹配」或「抽样解码」。ASC 进度只增不减。"),
            QuickRow(
                "把文件加入当前 View",
                sub="上方是全局已打开，下方是当前 View；打开后拖入才能画图或分析。Enter/Space 激活当前行，F2 重命名。",
                gesture="从文件列表拖到通道树",
            ),
            QuickRow(
                "文件范围跟随",
                sub="链接菜单：新文件加入当前 View、建 View 继承、切换分析填充空 View；全关即不跟随。",
                gesture="文件区链接图标",
            ),
            QuickRow(
                "保存会话",
                sub="主按钮保存当前工程；箭头展开另存为。有未保存更改时可保存、不保存或取消。",
                gesture="工具栏「保存」",
            ),
            QuickRow(
                "操作速查",
                sub="底栏默认只留问号；滚动文字提示可在本面板打开「底部提示」。Esc 先清空搜索，再按一次关闭。",
                gesture="底栏「?」或键盘 ?",
            ),
            QuickRow("软件说明书", gesture="状态栏右侧书本图标"),
        ),
    ),
    # 2 — 五个分析工作区 + 只读总览 (wide, spans two columns)
    QuickGroup(
        title="五个分析工作区 + 总览",
        note="总览是独立面板，只读，不是第六种算法",
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
            QuickRow(
                "有效事实卡",
                sub="计算后显示实际 Fs / NFFT / Δf / 窗长 / 帧数。自动优先 4096 点；低 Fs 按窗长适配。点数缩短与统计不足分开提示，零填充不会提高物理分辨率。",
            ),
            QuickRow(
                "自动 NFFT",
                sub="分段频谱与时频在普通采样率下优先 4096；时频至少 4 个真实时间帧。多来源按每源解析，摘要显示范围。",
            ),
            QuickRow(
                "总览",
                sub="独立只读面板，对照已有预览、不计算；右上可让当前工程所有 Board 的卡片操作常驻（保存项目后保留）。停手后更新图面，保留游标与标注。",
                gesture="各工作区 View 栏最右侧 UltraView",
                accent=_MODE_ULTRAVIEW,
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
                "拖通道加入当前 View",
                sub="松手在绘图区即勾选并绘图；已在 View 中则只聚焦，不重复",
                gesture="拖到绘图区",
            ),
            QuickRow(
                "拖通道设为横坐标",
                sub="拖到底部 X 带替换横轴；按来源匹配同名通道，失败仅占位或跳过该来源。",
                gesture="拖到最底部 X 带",
            ),
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
            QuickRow(
                "复位视图",
                keys=(_sc("home"),),
                gesture="双击",
                sub="回到图面已绘通道范围，不是已加载文件里最长的那条",
            ),
            QuickRow(
                "分析图缩放保持",
                sub="频谱 / 时频 / 阶次的平移、滚轮、框选和查看全部会随 View 保存；点计算才按 Inspector 重成图",
            ),
            QuickRow(
                "时间范围「全部」",
                sub="X 轴回到图面已绘通道的最长全程，不是全局最长文件；不勾选过滤",
                gesture="Inspector「全部」",
            ),
            QuickRow(
                "视角后退 / 前进",
                keys=(_sc("back"), _sc("forward")),
                sub=(
                    f"{_sc('back')} / {_sc('forward')}：视角后退 / 前进；"
                    "Ctrl/Cmd+Z 保留给编辑撤销。"
                ),
            ),
            QuickRow(
                "时域 View",
                sub="最多 24 个；窄窗口先显示编号，悬停看全名；「⋯」始终可管理全部 View，变为「»N」时 N 是未显示的 View 数；面板可逐项关闭、关闭其他或关闭全部",
            ),
            QuickRow(
                "View 标签关闭",
                sub="当前 View 悬停色标出现 ×；其他 View 的色标首次点击只切换，移出再进入后才可关闭。名称区仍用于切换和双击重命名，F2 也可重命名。面板内 × 直接关闭。至少保留一个 View；关闭其他保留当前，关闭全部后留下一个空白 View。",
            ),
            QuickRow(
                "图表角落的质量小圆点",
                sub="绿=精细显示，黄=正在细化，蓝=流畅预览（按墨迹预算关闭抗锯齿），"
                    "灰=无曲线，红=绘制异常（密度不可读取 / 实测帧超时）；悬停看原因。"
                    "切 View 或算完先出图再平滑，属正常",
            ),
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
                "撤销 / 重做",
                sub="只作用于当前编辑区域（标注 / 总览）；无历史时不回退图表。Ctrl/Cmd+Z 保留给编辑撤销。",
            ),
            QuickRow(
                "切换当前分区 View",
                keys=(_sc("next_view"), _sc("previous_view"), "Alt+1…9"),
                sub="前/后切当前分区；第 10–24 个走标签栏或「⋯」管理面板；显示「»N」时 N 是未显示数",
            ),
            QuickRow(
                "重命名当前行",
                keys=("F2",),
                sub="View、配置或列表中的当前可编辑行",
            ),
            QuickRow("顶部按钮的快捷键", sub="悬停按钮即显示"),
            QuickRow(
                "窄窗口工具栏",
                sub="点左右箭头或使用鼠标滚轮；触摸板可横向滑动，空白处仍可拖动；按钮顺序不变。",
            ),
        ),
    ),
    # 5 — 通道树（左侧）
    QuickGroup(
        title="通道树（左侧）",
        rows=(
            QuickRow(
                "绘制 / 取消通道",
                sub="鼠标勾选仍可用；Enter/Space 切换当前行。",
                keys=("Enter", "Space"),
                gesture="勾选复选框",
            ),
            QuickRow(
                "WinWert 原始辅助线",
                sub="所属文件下的 WinWert 原始记录；眼睛只隐藏当前时域 View 的辅助线，不改普通通道或源文件；关闭/移除后同步消失。",
                gesture="左侧树眼睛",
            ),
            QuickRow(
                "调整文件 / 通道顺序",
                sub="拖文件卡片或通道树文件根节点排整个文件块；拖通道只改同源顺序。Alt+Up/Down 亦可调文件顺序。分屏/叠加跟左侧顺序，画布内不能拖行。",
                gesture="左侧拖动",
            ),
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
                sub="d/dt · ∫dt · ×系数 · +偏移 · 滑动平均（窗长=样点数）· |x| →「创建通道」；参数旁 ? 看帮助",
            ),
            QuickRow(
                "双通道运算",
                sub="A+B · A−B · A×B · A÷B · max/min → 同样点「创建通道」",
            ),
            QuickRow(
                "自定义表达式",
                sub="运算选「自定义表达式…」；A / B / t 加括号系数与 "
                    "sqrt abs log min max mean where，^ 为幂",
            ),
            QuickRow(
                "表达式 / 参数帮助卡片",
                sub="示例与说明一览，可拖到旁边边看边填",
                gesture="点输入旁「?」",
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
            QuickRow(
                "单游标",
                sub="时间轴显示当前位置；Custom X 显示当前位置的 X↑ / X↓ 分支值。",
                keys=(_sc("cursor_single"),),
            ),
            QuickRow(
                "双游标",
                sub="点 A、B：时间轴显示 ΔT/1/ΔT；Custom X 显示单位/ΔX。无法可靠区分会提示。",
                keys=(_sc("cursor_dual"),),
            ),
            QuickRow(
                "游标显示设置",
                sub="游标旁设置可独立开关最小值点、最大值点与双游标 Min / Max / Avg / 差值；− 把读数收成 mini。读数面板本身不弹出 tooltip。全局同步所有分屏。",
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
            QuickRow(
                "切片跟随谱图视野",
                sub="Inspector 该轴为自动时；手动范围仍以 Inspector 为准",
                gesture="缩放 / 平移 / Home",
            ),
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
                sub="WWT 无损 float64 · 紧凑 int16（约 1/4 体积）；保留采样率，时域显示",
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
                "运行警告",
                sub="结果区汇总本次运行警告；任务行悬停只显示该行自己的警告",
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
                sub="查看全部（已绘通道，非全局最长文件） · 轴范围 · 鼠标模式 · 网格 · 自定义动作",
            ),
            QuickRow(
                "轴范围起止",
                sub="输入起点后 Tab 到终点，不必再点；时域 / 频谱 / 时频 / 频响同一面板",
                gesture="Tab",
            ),
            QuickRow(
                "换绑自定义动作",
                sub="复制 / 上一步 / 下一步 / 导出",
                gesture="鼠标行第三槽▾",
            ),
            QuickRow("通道右键", sub="设左轴 / 共轴"),
            QuickRow(
                "View 标签右键",
                sub="加入总览：只读对照已有预览，不重新计算",
            ),
            QuickRow(
                "总览卡片右键",
                sub="替换为…、移到未放置、复制图、尺寸预设；过期才显示同步。右上角可打开、聚焦、按原图比例或移除；更多菜单锁定/解锁。",
            ),
            QuickRow(
                "总览画布右键",
                sub="空白右击：适应内容、100%、概览、智能排版、紧凑排列、复制/导出。适应内容只缩放画布；智能排版可撤销，锁定卡不移动。按原图比例只收紧当前卡。",
            ),
        ),
    ),
    QuickGroup(
        title="总览 · Board 与自由网格",
        rows=(
            QuickRow(
                "View 库",
                sub="空板点左侧实心按钮；「从左侧 View 库添加对比」。可钉住，按类型浏览，＋加入/移出 Board。",
                gesture="库标题图钉",
            ),
            QuickRow(
                "多个 Board",
                sub="名称 ▾：点行切换、拖拽排序、行尾复制/删除；双击或 F2 改名，＋新建（最多 20 个）。",
                gesture="Board 名称 ▾",
            ),
            QuickRow(
                "9 / 12 图模板",
                sub="3×3 与 4×3；窗口不够时滚动，不把卡片压到不可读",
            ),
            QuickRow(
                "自由网格",
                sub="新 Board 默认自由网格；12 列为基准网格和导出标尺。四向平移、空白框选，直接拖动、边角缩放、Shift 多选；预览显示 ghost。最多 24 张卡/200 个 View，导出按已放置内容裁切。",
                keys=("Shift",),
            ),
            QuickRow(
                "指针",
                sub="整块单击选鼠标/激光笔；两者都能选择、移动、缩放，激光笔是发光圆点。V 保持选择，Esc 取消后清选；空格或中键平移。",
                keys=("V", "Esc"),
            ),
            QuickRow(
                "便签 Sticky",
                sub="创作键 N / T / S / P。N 开 16 色便签，点空白即编辑，Stack 连续放置；V 或 Esc 回鼠标。空内容不保存，Ctrl/Cmd+Enter 提交；不计算、不改源 View。",
                keys=("N",),
            ),
            QuickRow(
                "文字 Text",
                sub="T 开文字；点空白即编辑、拖动定宽。选中后图标栏改字体、字号、对齐和颜色；非空提交一条历史，V 或 Esc 返回。",
                keys=("T",),
            ),
            QuickRow(
                "形状 Shape",
                sub="S 选形状与连接线（直线、箭头、矩形等），L 直达连接线；拖动定尺寸。选中后图标栏改样式，P 打开画笔。",
                keys=("S",),
            ),
            QuickRow(
                "已有连线与笔画",
                sub="从 S 或 L 选连接线、P 选画笔。旧项目的连线和笔画仍会显示；可改属性或删除，保存重开不丢。",
            ),
            QuickRow(
                "多选 · 对齐",
                sub="Shift 点选/框选后对齐或分布；卡片与作者混选仅移动、删除、锁定。Ctrl/Cmd+D 复制，Ctrl/Cmd+C/V 粘贴。",
                keys=("Ctrl+D", "Shift"),
            ),
            QuickRow(
                "键盘微调",
                sub="选中作者对象后方向键微调，Shift 加大。Option+方向键移动卡片，Option+Shift+方向键改尺寸",
                keys=("Option", "Shift"),
            ),
            QuickRow(
                "锁定卡片",
                sub="更多菜单锁定/解锁；后续智能排版保留位置。锁定卡片占用空间时布局不变，保存项目后重开不会自动重排。",
                gesture="卡片更多菜单",
            ),
            QuickRow(
                "替换卡片",
                sub="库/托盘拖到卡上约 0.6 秒出现替换环；环内松手替换，否则附近插入。也可右键「替换为…」。",
                gesture="拖入并悬停",
            ),
            QuickRow(
                "尺寸预设",
                sub="右键有小/标准/宽/高/大/横幅。右上「按原图比例」按当前预览尺度只收紧本卡；放不下保持布局，模板不可用。",
                gesture="卡片右键 / 右上角",
            ),
            QuickRow(
                "撤销 / 重做",
                sub="只作用于当前编辑区域；无历史时不回退图表。移动、调整或移除可 Ctrl/Cmd+Z / Ctrl+Shift+Z；移除不删除源 View。一次智能排版或紧凑排列都可撤销。",
                keys=("Ctrl+Z", "Ctrl+Shift+Z"),
            ),
            QuickRow(
                "画布缩放 / 平移",
                sub="切换 Board 自动适应内容。Ctrl+滚轮/捏合缩放 25%–300%；空白框选，右键/空格/中键四向平移。适应内容只缩放画布并居中，100% 保持中心；双击卡片临时聚焦，Esc 返回。低缩放显示标题卡；空白右击可智能排版、紧凑排列、复制/导出。",
                keys=("Ctrl", "滚轮"),
            ),
            QuickRow(
                "源已变化",
                sub="预览与图面不同可点同步，不重新计算；「一键更新源」批量刷新。分辨率偏低时打开源 View 再更新，不触发智能排版。",
                gesture="卡片「同步」 / 左栏「一键更新源」",
            ),
            QuickRow(
                "缩略图 / 整板概览",
                sub="自由网格有滚动条时显示右下 minimap；整板概览点卡片回到阅读位置。",
                gesture="工具栏「概览」",
            ),
        ),
    ),
)


def search_text(row: QuickRow) -> str:
    """Lowercased haystack for live filtering (desc + sub + every chip)."""
    parts = [row.desc, row.sub, *row.keys]
    if row.gesture:
        parts.append(row.gesture)
    return " ".join(p for p in parts if p).lower()
