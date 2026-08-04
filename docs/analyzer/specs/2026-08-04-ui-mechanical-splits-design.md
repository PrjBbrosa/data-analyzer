# UI 机械拆分热身包 · 设计(包 A)

- 日期:2026-08-04
- 基线:`main` @ `e385ce5a`(v7.9.3 + 通道表达式功能)。**本文所有行号以此 commit 为准。**
  (由 `6236a5fe` 更新;`6bda7ccb` 改动了 `ui/dialogs.py`,A2 锚点已按新基线重取。)
- 来源:2026-08-04 全仓复杂度评审(杂项大文件分诊)。
- 实施计划:[2026-08-04-ui-mechanical-splits-implementation.md](../plans/2026-08-04-ui-mechanical-splits-implementation.md)
- 定位:五个整理包中风险最低的一包,四项互相独立,可任意顺序、任意子集执行。

## 范围与收益

| 项 | 目标文件 | 问题 | 动作 |
| --- | --- | --- | --- |
| A1 | `ui/widgets/__init__.py`(1760 行) | 包 `__init__` 内联 6 个类的完整实现,含互不相干的通道树 / Toast / 统计条 | 拆 4 个模块,`__init__` 归零为再导出 |
| A2 | `ui/dialogs.py`(1256 行) | 三个零耦合对话框同居;L1 docstring 已过期(写着不存在的 `AxisEdit`) | 转成 `ui/dialogs/` 包,三类各自成文件 |
| A3 | `io/loader.py`(1147 行) | BLF/DBC 子系统约 366 行内联(L149-515),而 wwt/zfd/mat 均已外提——委托模式不彻底 | 提 `io/blf_format.py`,`DataLoader` 保留门面 |
| A4 | `ui/chart_stack/cards.py` | `_ChartCard.__init__`(L106-404,299 行)吞掉全部装配;其余 59 个方法健康 | 只拆这一个方法为 `_build_*`/`_wire_*` 序列 |

四项共同性质:**纯结构移动,零行为变化,零公共 API 变化**。

## 已核实的兼容面(拆分的硬约束)

**A1 · `ui.widgets` 的全部外部导入(2026-08-04 grep 核实):**

- 产品侧 4 处:`ui/file_navigator.py:14`(`INTERNAL_FILE_FIDS_MIME`, `MultiFileChannelWidget`)、
  `ui/chart_stack/stack.py:15`(`StatsStrip`)、`ui/markup/editor.py:169` 与
  `ui/main_window/window.py:313`(`Toast`,均为函数内延迟 import)。
- 测试侧:多个文件 import `MultiFileChannelWidget`;
  **`tests/ui/test_color_swatch_hidpi.py:12` 直接 import 私有名 `_swatch_pixmap`**。
- ⇒ `__init__.py` 再导出名单必须至少包含:`MultiFileChannelWidget`、
  `INTERNAL_FILE_FIDS_MIME`、`StatsStrip`、`Toast`、`StatisticsPanel`、`_swatch_pixmap`
  (保守起见把 `_swatch_icon`、`_fmt_rate` 一并列入)。

**A2 · `ui.dialogs` 的消费者:** `ui/_axis_interaction.py:14`(`ChartOptionsDialog`,延迟)、
`ui/drawers/export_sheet.py:5`(`ExportDialog`)、`ui/drawers/channel_editor_drawer.py:5`
(`ChannelEditorDialog`);测试从 `mf4_analyzer.ui.dialogs` import 三个类。
⇒ 用**包替换模块**(`ui/dialogs/__init__.py` 再导出),import 路径逐字不变。

**A3 · BLF 公开面:** `tests/test_blf_loader.py` 调用 `DataLoader.read_blf_frames`、
`DataLoader.load_blf`、`DataLoader.probe_blf_dbc`——这些是**公开类方法**,不是私有函数。
⇒ `DataLoader` 保留同名类方法,委托给 `io/blf_format.py`;内部帮助函数
(`BlfDbcProbe` / `_read_blf_frames` / `_zoh_resample` / `_assemble_blf_channels` /
`_load_dbc_database` / `_decode_can_payload` / `_probe_blf_dbc_frames` /
`_decode_blf_with_dbc` / `_raw_blf_channels`)整体搬迁,仓库内无其他引用(已 grep 核实)。

## 设计决策

**D-A1 · `ui/widgets/` 拆四个模块**

| 新模块 | 内容(基线行号) |
| --- | --- |
| `_swatches.py` | `_fmt_rate`(:45)、`_swatch_pixmap`(:52)、`_swatch_icon`(:76) |
| `channel_tree.py` | `INTERNAL_FILE_FIDS_MIME`(:42)、`_ChannelLeafDelegate`(:111)、`_CheckTolerantTree`(:284)、`MultiFileChannelWidget`(:463-1623) |
| `stats.py` | `StatisticsPanel`(:80)、`StatsStrip`(:1624) |
| `toast.py` | `Toast`(:1670) |

`__init__.py` 归零为显式再导出(上文名单)+ 一行 docstring。既有子模块
(`channel_config_bar.py` 等)不动。

**D-A2 · `ui/dialogs.py` → `ui/dialogs/` 包**

`channel_editor.py`(`ChannelEditorDialog` :54-613)、`export.py`(`ExportDialog` :614-641)、
`chart_options.py`(`ChartOptionsDialog` :642-1256),`__init__.py` 再导出三个类。
原文件内相对导入(`from .xxx`)升一级为 `from ..xxx`(含 :44 新增的
`from .expression_help import ...`)。顺手修掉过期 docstring。
**本包不拆 `ChannelEditorDialog.__init__`(:67-299,233 行)**——那是行为敏感的
UI 装配,留给后续(见非目标)。

**D-A3 · `io/blf_format.py`**

L149-515 整体搬迁为模块级函数;`DataLoader.read_blf_frames` / `load_blf` / `load_blf_raw`
(若存在)/ `probe_blf_dbc` 变为对新模块的薄委托,签名与 docstring 不变。
`can` / `cantools` 的可选依赖 import 策略(当前在函数内延迟)原样保留。

**D-A4 · `_ChartCard.__init__` 分解**

299 行按既有内部注释边界切成有序私有方法(预计:`_init_state()` /
`_build_chrome()` / `_build_toolbar_routing()` / `_wire_hint_rotation()` /
`_wire_discovery_hooks()` / `_wire_nudges()`),`__init__` 只按原顺序依次调用。
**语句顺序逐条保持**——Qt 装配顺序是隐式契约,不重排、不合并、不"顺手优化"。

## 新增测试(按用户要求补 UI 逻辑与接线的空档)

1. **A1 缺口**:`StatsStrip` / `Toast` / `StatisticsPanel` 目前只有间接冒烟。
   新增 `tests/ui/test_widgets_misc.py`:
   - Toast:调用显示接口后可见、文本正确;定时自隐(用 `qtbot.waitUntil` 或直接触发
     其 QTimer)后不可见;连续两次调用不叠加残留。
   - StatsStrip:喂一组统计值,断言标签文本;空值/None 输入不抛异常。
   - StatisticsPanel:构造 + 基本更新路径冒烟。
2. **A4 接线特征测试(先写、后拆)**:新增
   `tests/ui/test_chart_card_construction.py`——对每个 `chart_mode`
   (`''`/`'fft'`/`'fft_time'`/`'order'`)构造 `_ChartCard`,快照:
   (a) 子 widget 的类名多重集;(b) 关键属性存在性清单(hint 轮播计时器、
   诊断 pill、focus bar 等,以基线实测为准);(c) `receivers()` 可数的关键信号
   连接数。**先在基线上让它通过并 commit,再做拆分**——拆完必须原样绿。
3. **A2/A3**:既有覆盖充分(`test_dialogs.py` 681 行、`test_blf_loader.py` 等),
   不新增,靠导入路径不变 + 全量既有测试守护。

## 非目标

- 不拆 `ChannelEditorDialog.__init__`、不动 `channel_config_manager.py`
  (那边缺的是测试,另行处理)。
- 不改任何 UI 行为、文案、布局——本包完成后 `/update-hints` 无需运行。
- 不动 `ui/widgets/` 下既有子模块。

## 验收准则

1. 全量 `tests/ui/` + `tests/`(相关子集)失败集与基线一致;新增三个测试文件全绿。
2. 四个拆分点的外部 import 语句(上文核实清单)在产品与测试代码中**零改动**
   (A4 的新特征测试除外)。
3. `ui/widgets/__init__.py` ≤ 60 行;`ui/dialogs/__init__.py` ≤ 20 行;
   `io/loader.py` 减少 ≥ 330 行;`_ChartCard.__init__` ≤ 40 行。
4. `git log` 上每项一个独立 commit,任何一项可单独 revert。
