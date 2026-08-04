# UI 机械拆分热身包 · 实施计划(包 A)

> **For agentic workers:** 按任务逐条执行,checkbox(`- [ ]`)跟踪。四个任务(A1–A4)
> **互相独立**,可单独执行、单独 revert;每任务一个 commit。任何验证失败先对照基线
> 失败集,确认是自己引入的才修;不是自己引入的记录后继续。

**设计文档:** [2026-08-04-ui-mechanical-splits-design.md](../specs/2026-08-04-ui-mechanical-splits-design.md)
**基线:** `main` @ `6236a5fe`。分支:`refactor/ui-mechanical-splits`。
**测试命令前缀(下称 `PYTEST`):** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

## 全局约束

- **纯移动**:除 import 语句与拆分点本身外,函数/类体一行不改;不重排语句、不改名、
  不"顺手优化"。
- 外部 import 路径零改动(spec「已核实的兼容面」一节是硬约束清单)。
- `main` 上 `tests/ui/` 既有红测试(`test_split_*` 等)——Task 0 先记录,不算新账。

---

## Task 0: 锚点核验 + 基线采集

- [ ] **Step 1:** 核验 spec 锚点,任何一条失配 → **停止并回报**,不要凭猜测继续:
  - `grep -n "^class \|^def \|^INTERNAL" mf4_analyzer/ui/widgets/__init__.py`
    应与 spec D-A1 表格一致(:42/:45/:52/:76/:80/:111/:284/:463/:1624/:1670)。
  - `grep -n "^class " mf4_analyzer/ui/dialogs.py` 应为 :54/:607/:635 三类。
  - `grep -n "def read_blf_frames\|def load_blf\|def probe_blf_dbc" mf4_analyzer/io/loader.py`
    确认公开门面方法;BLF 私有帮助函数区间约 L149-515。
  - `mf4_analyzer/ui/chart_stack/cards.py` 中 `_ChartCard.__init__` 为 L106-404。
  - 重跑 spec 兼容面的三条 grep(ui.widgets / ui.dialogs / BLF 符号外部引用),
    确认消费者清单未变。
- [ ] **Step 2:** 跑基线并存档失败集:
  `PYTEST tests/ui/ -q > docs/analyzer/verify/ui-splits-baseline-ui.txt 2>&1 || true`
  `PYTEST tests/test_blf_loader.py tests/test_blf_dbc_candidates.py tests/test_batch_loader_dispatch.py -q`

---

## Task A1: 拆 `ui/widgets/__init__.py`

**Files:** Create `mf4_analyzer/ui/widgets/{_swatches,channel_tree,stats,toast}.py`;
Modify `mf4_analyzer/ui/widgets/__init__.py`;Create `tests/ui/test_widgets_misc.py`。

- [ ] **Step 1(先补测试,红→绿在基线上完成):** 写 `tests/ui/test_widgets_misc.py`
  (spec「新增测试」第 1 条:Toast 显示/自隐/重复调用、StatsStrip 文本与空值、
  StatisticsPanel 冒烟)。写前先读 `Toast`(:1670-1760)与 `StatsStrip`(:1624-1668)
  的真实接口,按实际方法名写断言。在**基线代码**上跑绿后单独 commit。
- [ ] **Step 2:** 按 spec D-A1 表格移动代码。注意:`channel_tree.py` 需要
  `from ._swatches import ...`;各新模块头部 import 按实际使用最小化(从原
  `__init__.py` 头部 L1-41 的 import 里挑)。
- [ ] **Step 3:** `__init__.py` 重写为显式再导出:
  `MultiFileChannelWidget, INTERNAL_FILE_FIDS_MIME, StatsStrip, Toast, StatisticsPanel, _swatch_pixmap, _swatch_icon, _fmt_rate`
  (+ 若 Step 1 核验发现其他被外部引用的名字,一并保留)。
- [ ] **Step 4:** 验证。

Run: `PYTEST tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py tests/ui/test_channel_axis_groups.py tests/ui/test_color_swatch_hidpi.py tests/ui/test_head_hdf_rail.py tests/ui/test_widgets_misc.py tests/ui/test_hints.py -q`

Expected: 全绿(或与基线失败集一致)。

## Task A2: `ui/dialogs.py` → `ui/dialogs/` 包

**Files:** Create `mf4_analyzer/ui/dialogs/{__init__,channel_editor,export,chart_options}.py`;
Delete `mf4_analyzer/ui/dialogs.py`。

- [ ] **Step 1:** 记录 `dialogs.py` 头部 import 清单;三个类按 :54-604 / :607-633 /
  :635-1249 切入三个模块,相对导入 `from .xxx` → `from ..xxx`。
- [ ] **Step 2:** `__init__.py`:docstring(修正过期的 `AxisEdit` 描述)+
  再导出 `ChannelEditorDialog, ExportDialog, ChartOptionsDialog`。
- [ ] **Step 3:** 全仓 grep `ui.dialogs`/`from .dialogs`/`from ..dialogs` 确认所有
  消费者(产品 3 处 + 测试)无需改动即可解析。
- [ ] **Step 4:** 验证。

Run: `PYTEST tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py tests/ui/test_channel_editor_expression.py tests/ui/test_channel_editor_export.py tests/ui/test_expression_help_popup.py tests/ui/test_axis_interaction.py -q`

## Task A3: BLF/DBC → `io/blf_format.py`

**Files:** Create `mf4_analyzer/io/blf_format.py`;Modify `mf4_analyzer/io/loader.py`。

- [ ] **Step 1:** 移动 L149-515 的 BLF 子系统(`BlfDbcProbe` + 8 个函数)到
  `blf_format.py`;`can`/`cantools` 的延迟 import 策略保持在函数体内。
- [ ] **Step 2:** `DataLoader.read_blf_frames` / `load_blf` / `probe_blf_dbc`(以及
  Task 0 核验发现的其他 BLF 公开方法)改为对 `blf_format` 的薄委托,
  **签名与 docstring 逐字保留**。
- [ ] **Step 3:** 验证(BLF 测试在无 python-can 环境会 importorskip,属正常)。

Run: `PYTEST tests/test_blf_loader.py tests/test_blf_dbc_candidates.py tests/test_batch_loader_dispatch.py tests/ui/test_blf_open.py tests/ui/test_blf_batch_import.py -q`

## Task A4: 分解 `_ChartCard.__init__`

**Files:** Create `tests/ui/test_chart_card_construction.py`;
Modify `mf4_analyzer/ui/chart_stack/cards.py`。

- [ ] **Step 1(特征测试先行):** 写 `tests/ui/test_chart_card_construction.py`
  (spec「新增测试」第 2 条):对每个 `chart_mode` 构造 `_ChartCard`
  (canvas 参数用与既有测试相同的构造方式,参考 `tests/ui/test_chart_stack.py`
  的夹具),快照子 widget 类名多重集 + 关键属性存在性。在**基线**上跑绿,单独 commit。
- [ ] **Step 2:** 把 L106-404 按内部注释带切成 `_init_state` / `_build_chrome` /
  `_build_toolbar_routing` / `_wire_hint_rotation` / `_wire_discovery_hooks` /
  `_wire_nudges`(实际边界以代码注释块为准,方法名可据实调整),`__init__`
  按**原语句顺序**依次调用。逐条语句对照,禁止重排。
- [ ] **Step 3:** 验证:特征测试必须原样绿;hint/nudge 行为测试全绿。

Run: `PYTEST tests/ui/test_chart_card_construction.py tests/ui/test_chart_stack.py tests/ui/test_hint_nudges.py tests/ui/test_nudge_card_surfacing.py -q`

---

## Task 5: 收尾

- [ ] **Step 1:** 全量 UI 测试对比 Task 0 基线失败集,新旧差异必须为空
  (新增测试文件除外)。
- [ ] **Step 2:** 真机冒烟(非 offscreen):启动 GUI,打开一个数据文件,确认通道树、
  Toast(触发一次保存工程之类的提示)、统计条、FFT 卡片、通道编辑器对话框、
  图表选项对话框各出现一次且外观无异常。**本包不改行为,此步只为兜底。**
- [ ] **Step 3:** 汇总四项的行数变化与 commit 清单,附在 PR 描述。

Run: `PYTEST tests/ui/ -q`
