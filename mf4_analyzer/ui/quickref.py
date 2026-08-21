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
            QuickRow("打开数据 / 项目", gesture="工具栏「打开」"),
            QuickRow(
                "支持格式",
                sub="MF4 · MDF · BLF · ASCII · TDMS · WWT · ZFD · MAT · 表格 · HDF · 音视频",
            ),
            QuickRow("BLF / CANoe ASC 报文解码", sub="需配 DBC；界面写「完整匹配」和/或「抽样解码」，不以估算帧数充精确计数。ASC 回退进度只升不降，100% 只在帧交付后"),
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
            QuickRow(
                "保存会话",
                sub="主按钮保存当前工程；箭头展开另存为",
                gesture="工具栏「保存」",
            ),
            QuickRow(
                "操作速查",
                sub="底栏默认只留问号；滚动文字提示可在本面板打开「底部提示」",
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
                "总览",
                sub="独立面板，只读对照已有预览：不计算；左上 Board 弹层管理多个 Board，左侧窄轨打开 View 库、自由网格、布局、筛选和未放置；View 库可钉住以免点画布时收起；右上浮岛开关标题/来源、当前工程所有 Board 的卡片操作常驻（保存项目后保留）、复制导出和演示；取消卡片操作常驻后，悬停或键盘聚焦卡片才显示操作；右下浮岛控制概览与缩放；停手后跟上图面，含游标读数与标注",
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
                sub="按各来源匹配同名通道；失败只占位/跳过该来源，不回滚成时间轴",
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
                "时间范围「全部」",
                sub="X 轴回到图面已绘通道的最长全程，不是全局最长文件；不勾选过滤",
                gesture="Inspector「全部」",
            ),
            QuickRow("后退 / 前进视图", keys=(_sc("back"),)),
            QuickRow(
                "时域 View",
                sub="最多 12 个；窄窗口先显示编号，悬停看全名，再用「»」切换收纳的 View",
            ),
            QuickRow(
                "图表角落的质量小圆点",
                sub="绿=抗锯齿已完成，黄=等待空闲刷新，红=未激活（悬停看原因：绘制量超预算 / "
                    "曲线密度 / 实测帧超时）；切 View 或算完先出图再平滑，属正常",
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
            QuickRow(
                "调整文件 / 通道顺序",
                sub="拖文件卡片或通道树文件根节点移动整个文件块；拖通道只改同一来源内顺序。分屏与叠加都跟左侧顺序，画布内不能拖行",
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
                sub="替换为… · 移到未放置 · 复制本卡图像 · 尺寸预设；过期才出现同步。打开、聚焦、按原图比例和移除在右上角胶囊",
            ),
            QuickRow(
                "总览画布右键",
                sub="空白处：适应内容、100%、概览、自动排版（保留尺寸，可撤销）、复制图片、导出 PNG",
            ),
        ),
    ),
    QuickGroup(
        title="总览 · Board 与自由网格",
        rows=(
            QuickRow(
                "View 库",
                sub="空板时左侧实心按钮是添加入口，画布旁会提示「从左侧 View 库添加对比」。钉住后点画布不收起，Esc 仍关闭。按分析类型直接浏览，标题可折叠，＋加入或移出 Board",
                gesture="库标题图钉",
            ),
            QuickRow(
                "多个 Board",
                sub="左上名称旁打开弹层：点行切换、拖拽排序、行尾复制/删除；双击名称或 F2 重命名；＋ 新建，最多 20 个",
                gesture="Board 名称 ▾",
            ),
            QuickRow(
                "9 / 12 图模板",
                sub="3×3 与 4×3；窗口不够时滚动，不把卡片压到不可读",
            ),
            QuickRow(
                "自由网格",
                sub="新 Board 默认自由网格。左侧窄轨按钮切回模板；12 列是基准网格和导出标尺，不是日常拖动墙。工作区随内容扩展，四向可平移；左键空白框选、右键拖动画布；拖到边缘自动平移并扩展画布。最多 24 张已放置、200 个 View。整数网格；直接拖动移动，选中后拖边角改尺寸；Shift 点选多张；拖动预览最终落点与被推移卡（完整 ghost）；移动不改任何卡尺寸、缩放只改本卡；硬拒绝会说明原因和下一步，不弹框。导出 PNG 按已放置内容裁切，与适应内容同口径",
                keys=("Shift",),
            ),
            QuickRow(
                "指针",
                sub="自由网格创作段首位。主点击进入最近一次指针模式，首次为鼠标。箭头打开鼠标/激光笔两行。鼠标可选择、移动、缩放；激光笔只显示红色聚焦点，不选择、不创建、不写入标注或撤销。V 始终回到鼠标；Esc 先取消编辑/草稿/弹层，再退出激光笔。空间键和中键仍可平移",
                keys=("V", "Esc"),
            ),
            QuickRow(
                "便签 Sticky",
                sub="左侧创作段指针 / N / T / S / P。按 V 或 Esc 回到鼠标指针。N 单击打开 16 色便签，选色一次放置，底部 Stack 连续放置。点空白创建并立即编辑，拖框按起止尺寸创建。空内容退出不保存、不进撤销；有内容后 Ctrl/Cmd+Enter 提交，Esc 取消。不计算、不改源 View",
                keys=("N",),
            ),
            QuickRow(
                "文字 Text",
                sub="T 进入文字，不弹空层。点空白创建自适应宽文本框并立即编辑，拖动先定换行宽度。中文输入法组合期间快捷键不抢。选中后贴对象的图标栏整框改字体/字号/B/I/U/对齐/列表/颜色/底色/链接，不伪装局部富文本。放置一次回选择；双击按钮才连续。空内容退出不保存、不进撤销；非空提交一条历史。上限 6000 字。V 或 Esc 回到选择",
                keys=("T",),
            ),
            QuickRow(
                "形状 Shape",
                sub="S 单击打开形状与连接线目录：每行图标、名称、快捷键三列，含直线、箭头、折线与矩形/圆角矩形/椭圆/菱形/三角。L 直达最近连接线。点空白创建默认 4×3，拖动定尺寸；Shift 保持比例，Alt 从中心，Cmd/Ctrl 暂停吸附。选中后图标栏改填充/描边/线宽/虚线/圆角。双击或选中后输入编辑内嵌文字。P 打开纵向画笔：钢笔/荧光笔/整笔擦除/套索和 3 个圆形笔触预设（同时表示颜色和粗细），再点当前预设才改线宽和颜色",
                keys=("S",),
            ),
            QuickRow(
                "已有连线与笔画",
                sub="连接线从 S 选择或按 L 直达；画笔从 P 选择。旧项目里的连接线和笔画仍会显示、选中后可改属性或删除，保存重开不丢对象",
            ),
            QuickRow(
                "多选 · 对齐",
                sub="Shift 点选或框选多个作者对象后可左/中/右/上/中/下对齐，以及水平/垂直分布。卡片与作者混选只保留移动、复制、删除、锁定，不做危险批量样式。锁定和未知对象不改内容、不从板上丢掉。Ctrl/Cmd+D 复制，Ctrl/Cmd+C/V 按类型粘贴并分配新 id",
                keys=("Ctrl+D", "Shift"),
            ),
            QuickRow(
                "键盘微调",
                sub="选中作者对象后方向键微调，Shift 加大。Option+方向键移动卡片，Option+Shift+方向键改尺寸",
                keys=("Option", "Shift"),
            ),
            QuickRow(
                "替换卡片",
                sub="自由网格中，库或托盘拖到已有卡上停留约 0.6 秒出现替换环，环内松手替换；未出现环则在释放点附近插入。右键「替换为…」",
                gesture="拖入并悬停",
            ),
            QuickRow(
                "尺寸预设",
                sub="小 / 标准 / 宽 / 高 / 大 / 横幅在右键尺寸预设；「按原图比例」在右上角，按当前预览尺度收紧卡片外壳去贴图像宽高比，去掉上下或左右留白，不整板重选一张更大或更小的卡；放不下则拒绝并保持原布局，不静默改邻卡。模板模式下该操作不可用",
                gesture="卡片右键 / 右上角",
            ),
            QuickRow(
                "撤销 / 重做",
                sub="直接移动、调整或从当前 Board 移除后可使用 Ctrl/Cmd+Z / Ctrl+Shift+Z 恢复或重做；移除不删除源 View。一次重排对应一次撤销，可恢复全部受影响卡片",
                keys=("Ctrl+Z", "Ctrl+Shift+Z"),
            ),
            QuickRow(
                "画布缩放 / 平移",
                sub="每次打开或切换 Board 都自动适应内容。Ctrl+滚轮或触控板捏合以光标为锚，范围 25%–300%；左键按住空白框选，右键按住拖动画布；空格+拖、中键拖或手掌也可四向平移；拖到边缘自动平移并扩展画布。工具栏 − / % / ＋ / 适应 / 100%。12 列基准网格是卡片 1× 标尺；导出 PNG 按已放置内容裁切，与适应内容同口径，缩放不改变卡片长宽比。适应内容把已放置卡片居中填满点阵画布，最高 300%；100% 保持当前中心。双击卡片临时聚焦最高 300%，Esc 返回。≥60% 完整卡片，40%–59% 紧凑（藏页脚、留预览与类型），低于 40% 标题卡。整板概览仍可点卡片跳转。画布空白右击可适应、自动排版、复制或导出",
                keys=("Ctrl", "滚轮"),
            ),
            QuickRow(
                "源已变化",
                sub="预览与当前图面不一致（缩放、游标、标注或结果）。点同步抓取最新画面，不重新计算。左侧工具栏「一键更新源」可一次更新全部已变化预览",
                gesture="卡片「同步」 / 左栏「一键更新源」",
            ),
            QuickRow(
                "缩略图 / 整板概览",
                sub="自由网格且出现真实滚动条时才显示右下角 minimap；模板、概览、演示或面板打开时隐藏。整板概览点卡片回到阅读位置",
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
