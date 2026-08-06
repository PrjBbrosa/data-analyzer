# ChartStack 与标注编辑器瘦身 · 实施计划(包 D)

> **For agentic workers:** 两条线(D1/D2 = stack,D3/D4/D5 = markup)互相独立。
> 每任务:测试先行 → 搬代码 → 验证 → 独立 commit。可选任务(D2/D5)闸门不满足
> 就跳过,不算失败。

**设计文档:** [2026-08-04-chartstack-markup-slimming-design.md](../specs/2026-08-04-chartstack-markup-slimming-design.md)
**基线:** `main` @ `e385ce5a`。分支:`refactor/chartstack-markup-slimming`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

## Task 0: 锚点核验 + 基线(失配即停)

- [x] **Step 1:** **通读 `mf4_analyzer/ui/chart_stack/cursor_pill.py` 现有内容**
  (本计划多处并入它,必须先知道里面已有什么、避免命名冲突)。
- [x] **Step 2:** 核验 stack.py pill 区方法清单(spec 锚点 :1032-1305)与
  editor.py 各带(:394/:701/:901/:1163/:1212/:1282/:1325)。
- [x] **Step 3:** 纯度审计:对六个格式化方法逐个 grep 方法体内的 `self.`,记录
  每处 self 依赖(预期:`_single_cursor_channel_color` 可能查通道颜色)。结论存
  `docs/analyzer/verify/chartstack-markup-anchors.md`。
- [x] **Step 4:** 采集测试语料:`grep -rn "cursor_pill\|_format_cursor\|dual_cursor" tests/ui/test_chart_stack.py | head -30`,
  记录既有 pill 测试与其中的文本 fixture,供 Task 1 复用。
- [x] **Step 5:** 基线:
  `PYTEST tests/ui/test_chart_stack.py tests/ui/test_markup_editor.py tests/ui/test_copy_thumbnail.py tests/ui/test_chart_stack_stats_visibility.py -q > docs/analyzer/verify/chartstack-markup-baseline.txt 2>&1 || true`
  真机基线截图:单/双游标 pill、标注编辑器工具栏,存
  `docs/analyzer/evidence/chartstack-markup/baseline/`。

## Task D1: pill 格式化并入 `cursor_pill.py`

**Files:** Modify `mf4_analyzer/ui/chart_stack/cursor_pill.py`、`stack.py`;
Create `tests/ui/test_cursor_pill_formatting.py`。

- [x] **Step 1(测试先行):** 按 spec D-D1 写格式化测试。语料来源:Task 0 Step 4
  的既有 fixture;不够则真机/offscreen 跑一次游标操作,把 `_on_cursor_info`
  收到的真实字符串打印采集。期望值实测固化。基线跑绿,commit。
- [x] **Step 2:** 六个方法移为 `cursor_pill.py` 模块级函数;self 依赖按 Task 0
  Step 3 的审计改成显式参数;`ChartStack` 保留同名薄委托。
- [x] **Step 3:** 验证。

Run: `PYTEST tests/ui/test_cursor_pill_formatting.py tests/ui/test_chart_stack.py -q`

## Task D2(可选,闸门 = D1 全绿): pill 定位收拢为控制器

> **2026-08-06:跳过。** 闸门(D1 全绿)满足,但耦合实测显示收益不成立:
> `_secondary_card` 在 stack.py 有 76 处引用、`_time_card` 41 处,且 `_pill_secondary`
> 由分屏入口(:639)创建——控制器拿不到所有权,只能反向引用逐个转发,是位移不是接缝。
> 加上本次执行跳过真机,而 pill 定位正是 offscreen 验不了的那类。理由详见
> `docs/analyzer/verify/chartstack-markup-anchors.md` §6.2。

**Files:** Modify `cursor_pill.py`、`stack.py`。

- [ ] **Step 1:** `_reposition_pill` / `_reposition_one_pill` / `_pill_for_canvas` /
  snapshot 四件套 / `_on_cursor_info` 等回调收拢为 `CursorPillController`;
  `ChartStack` 公开面(`cursor_pill_snapshot` / `restore_cursor_pill_snapshot` /
  `cursor_pill_text` / `cursor_pill_visible` / `clear_cursor_pill`)保留薄委托。
- [ ] **Step 2:** `PYTEST tests/ui/test_chart_stack.py -q` 与基线一致;真机核对
  pill 随缩放/分屏/切 View 的位置行为。红了 → revert 本任务,停在 D1。

## Task D3: 标注序列化 → `markup/serialization.py`

**Files:** Create `mf4_analyzer/ui/markup/serialization.py`、
`tests/ui/test_markup_serialization.py`;Modify `mf4_analyzer/ui/markup/editor.py`。

- [x] **Step 1(测试先行):** 按 spec D-D3 写往返测试(每种图元 + 字段逐项比对)。
  **向后兼容用例:** 在基线代码上对每种图元跑一次 `_serialize_item`,把输出 payload
  作为常量固化进测试,断言新代码 `deserialize` 后字段正确。基线跑绿,commit。
- [x] **Step 2:** 两个方法移为模块级函数(item 类型判定所需的 import 一并);
  editor 薄委托。
- [x] **Step 3:** 验证。

Run: `PYTEST tests/ui/test_markup_serialization.py tests/ui/test_markup_editor.py -q`

## Task D4: 工具栏构建 → `markup/toolbar.py`

**Files:** Create `mf4_analyzer/ui/markup/toolbar.py`;Modify `editor.py`;
Modify(新增用例)`tests/ui/test_markup_editor.py` 或新文件。

- [x] **Step 1(接线特征测试先行):** 新增用例:构造 `MarkupEditor`,快照工具栏
  按钮清单(objectName/文本/checkable/初始态)与样式面板控件清单。基线跑绿,commit。
- [x] **Step 2:** `_build_toolbar` / `_build_style_panel` / 图标生成(:1282-1324)
  移入 `toolbar.py`,以「传入 editor 回调/信号」的方式接线;**按钮创建顺序与
  connect 顺序逐条保持**。
- [x] **Step 3:** 特征测试原样绿 + `test_markup_editor.py` 与基线一致;真机打开
  编辑器对照工具栏截图。
  > 特征测试 36 条搬后原样绿,未改一字。**真机部分按编排跳过**,可视面见
  > anchors §6.6-B。另:图标生成未移出,原因见 anchors §6.3。

Run: `PYTEST tests/ui/test_markup_editor.py -q`

## Task D5(可选,闸门 = D3+D4 全绿): 手柄几何 → `markup/handles.py`

- [x] **Step 1:** 审计 :901-1096:分「纯几何」(命中判定/缩放矩形计算)与
  「QGraphicsItem 耦合」两栏。纯几何部分移出并补直接单测(典型:四角/边中点
  命中、等比缩放、裁剪钳制);耦合部分留在 editor。
- [x] **Step 2:** `PYTEST tests/ui/test_markup_editor.py -q` + 真机:拖动矩形手柄、
  裁剪、缩放文字,行为与基线一致。红了 → revert 本任务。
  > pytest 部分完成(68 passed,与基线一致),并新增 `tests/ui/test_markup_handles.py`
  > 35 条纯几何直接单测。**真机部分按编排跳过**,可视面见 anchors §6.6-D。

## Task 6: 收尾

- [x] **Step 1:** 全量对比基线失败集(Task 0 Step 5 同一命令),差异为空
  (新增测试除外)。
- [ ] **Step 2:** 真机完整过一遍 spec 验收第 4 条(pill + 标注编辑器全流程),
  截图存 `.../evidence/chartstack-markup/after/`。
  > **2026-08-06:本次执行按编排要求跳过所有真机核对**(不启动 GUI、不截图、
  > 不用 offscreen 冒充视觉验收),改由 orchestrator 做两侧自动化渲染对比。
  > 本包改动触碰的可视面清单见
  > `docs/analyzer/verify/chartstack-markup-anchors.md` §6.6。**此项仍未完成。**
- [x] **Step 3:** PR 描述:行数变化、纯度审计表、向后兼容 payload 说明。

## 明确禁止

- 禁止动 `keyPressEvent`、焦点管理带(:364-602)、`_ChartCard`(那是包 A 的事)。
- 禁止改 pill 的 HTML 输出内容("顺手美化"格式化输出 = 行为变化)。
- 序列化字段名与结构一个都不许改——磁盘上有用户已保存的标注。
