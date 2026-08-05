# pg_canvas 公共轴层提取 · 实施计划(包 B)

> **For agentic workers:** 按任务逐条执行,checkbox 跟踪。第一阶段(Task 0–4)必做;
> 第二阶段(Task 5)有闸门,闸门不满足就停在 Task 4,**不算失败**。

**设计文档:** [2026-08-04-pg-canvas-shared-axes-design.md](../specs/2026-08-04-pg-canvas-shared-axes-design.md)
**基线:** `main` @ `e385ce5a`。分支:`refactor/pg-canvas-shared-axes`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

## 全局约束

- **函数体逐字平移**,不改名、不改签名、不合并、不"顺手修"。发现疑似 bug 只记录,不修。
- 不触碰 `canvas.py`;不触碰 `PgHeatmapCanvas` / `PgLineCanvas` 方法体(import 区除外)。
- 每任务一个 commit;移动(Task 2)与测试新增(Task 1)分开提交。

---

## Task 0: 锚点核验 + 基线采集(失配即停)

- [x] **Step 1:** 核验移动清单锚点:
  `grep -n "^def \|^class \|^_AUTO\|^_SLICE" mf4_analyzer/ui/pg_canvas/heatmap_canvas.py | awk -F: '$1 < 830'`
  应与 spec「移动清单」三组一致(组 1+2 共 19 个符号,行号 :260-:784)。
  → 19/19 符号行号逐一吻合,零失配。
- [x] **Step 2:** 核验反向导入现场:`sed -n '29,44p' mf4_analyzer/ui/pg_canvas/line_canvas.py`
  应为「3 个来自 canvas 的 AA 常量 + 8 个来自 heatmap 的符号」。→ 吻合。
- [x] **Step 3:** **monkeypatch 风险清单**(spec D-B2 风险点):
  `grep -rn "heatmap_canvas" tests/ | grep -i "monkeypatch\|setattr\|patch"`,
  并对组 1+2 的每个符号名 `grep -rn "<符号>" tests/`。逐条记录:哪个测试、patch 的
  是哪个模块路径、行使的是哪个画布。存入
  `docs/analyzer/verify/pg-shared-axes-patch-audit.md`。
  → **零命中**:全仓无测试 monkeypatch `heatmap_canvas` 模块属性,D-B2 风险不成立,
  Task 3 Step 2 为空操作。附带发现 7 个必须随迁的私有常量(见审计文件末节)。
- [x] **Step 4:** 基线失败集:
  `PYTEST tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_axis_frame_alignment.py tests/ui/test_axis_grid_label_slack.py tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_colorbar_reset.py tests/ui/test_slice_amp_floor_guard.py tests/ui/test_pg_canvas_decomposition_characterization.py -q > docs/analyzer/verify/pg-shared-axes-baseline.txt 2>&1 || true`
- [~] **Step 5:** 真机基线截图 —— **本次执行跳过**(编排方指示:执行者不启动 GUI、
  不截图,绝不以 offscreen 冒充真机验收)。改为交付「待人工真机验收清单」,由人执行。
  Step 4 的 offscreen 基线(706 passed / 0 failed)仅作测试基线,不构成视觉验收。

## Task 1: 纯函数直接单测(先行,红→绿在基线上)

**Files:** Create `tests/ui/test_analysis_axes.py`

- [x] **Step 1:** 按 spec D-B3 的用例清单编写,**当前先 import 自 `heatmap_canvas`**,
  文件头注释注明「Task 2 落地后 import 改指 `analysis_axes`」。
  断言值以基线实测为准(先跑一次函数看真实输出再固化,不要凭直觉写期望值)。
  → 53 条用例,全部期望值由基线探针实测固化。
- [x] **Step 2:** 跑绿,单独 commit。→ 53 passed。

Run: `PYTEST tests/ui/test_analysis_axes.py -q`

## Task 2: 创建 `analysis_axes.py` 并平移(核心动作)

**Files:** Create `mf4_analyzer/ui/pg_canvas/analysis_axes.py`;
Modify `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`(只动 import 区与删除被移动块)。

- [x] **Step 1:** 新建 `analysis_axes.py`:docstring(spec D-B1 措辞)+ 从
  `heatmap_canvas.py` **剪切**组 1+2 的 19 个符号,函数体逐字不动。头部 import
  从 heatmap 现有头部挑选实际需要的(pg / QtCore / numpy / `GridLabelSlackAxisItem` 等),
  最小化。→ 19 个符号 + 7 个随迁私有常量,共 536 行逐字平移;新模块 pyflakes 零告警。
- [x] **Step 2:** `heatmap_canvas.py` 顶部加
  `from .analysis_axes import (<19 个符号>)  # noqa: F401 — 兼容旧路径与 monkeypatch`,
  内部调用点**一律不改写**。→ 再导出 26 个名字(19 + 7 常量);模块路径用绝对形式
  以匹配本文件其余 import 的既有风格,语义与计划所写等价。
- [x] **Step 3:** `PYTEST tests/ui/test_pg_heatmap_canvas.py -q` 与基线一致;
  `git diff --color-moved=dimmed-zebra` 人工确认移动块零字符变化。
  → 211 passed(含新增 53 条);逐行比对确认移动载荷 536 行**字节级相同**;
  heatmap 侧新增行只有 import 区,函数体零改动。

## Task 3: line_canvas 切换 import,消除依赖倒置

**Files:** Modify `mf4_analyzer/ui/pg_canvas/line_canvas.py`(仅 :35-44 一处);
按 Task 0 Step 3 的审计结论,可能修改个别测试的 patch 目标。

- [x] **Step 1:** `from .heatmap_canvas import (...)` → `from .analysis_axes import (...)`。
- [~] **Step 2:** 审计清单里「patch heatmap 路径 + 行使 line 行为」的测试,把 patch
  目标改为 `analysis_axes`;每处改动在 commit message 里逐条列出。
  → **空操作**:Task 0 Step 3 审计结论为全仓零 monkeypatch 命中,无测试需要改。
  仅有的两处「引用 heatmap 路径 + 行使 line 行为」(`test_pg_line_canvas.py:1107`
  与 `:2063`)是值绑定 import 而非 patch,经再导出解析到同一对象,按纪律不动。
- [x] **Step 3:** 验证倒置消除:
  `grep "from .heatmap_canvas import" mf4_analyzer/ui/pg_canvas/line_canvas.py` → 空。
  → 零命中。文件内仅剩 `:1756` 一处 docstring 文字引用(指向仍留在 heatmap 的
  `_activate_graphics_layout`,叙述依然准确),不属于 import,不动。
- [x] **Step 4:** Task 1 的测试文件把 import 改指 `analysis_axes`。

Run: `PYTEST tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_axes.py -q`

## Task 4: 第一阶段收尾验收

- [x] **Step 1:** 全套画布测试对比基线失败集(Task 0 Step 4 同一命令),差异必须为空。
  → 基线 `706 passed, 1 deselected`;改动后 `706 passed, 1 deselected`。**差异为空**。
  额外扫了 12 个引用 heatmap_canvas 的测试文件(493 passed)与
  `test_main_window_smoke.py` + 两条 import 边界测试(127 passed),全绿。
- [x] **Step 2:** 像素守护:`PYTEST tests/ui/test_pg_canvas_decomposition_characterization.py -q` 绿。
  → 10 passed。
- [~] **Step 3:** 真机复验 —— **本次执行跳过**,交人工。执行者不启动 GUI、不截图;
  offscreen 结果**不构成**视觉验收(CLAUDE.md 明令)。待办清单见交付报告
  「待人工真机验收清单」。**本步未完成 = 第一阶段尚未正式收尾。**
- [x] **Step 4:** 量化核对:`heatmap_canvas.py` 减少 ≥500 行;PR 描述附
  patch-audit 文件与截图对照。
  → `heatmap_canvas.py` 3021 → 2518(**-503**,达标);新增 `analysis_axes.py` 572 行;
  `line_canvas.py` 2235 行不变(仅 1 行 import 改动)。截图对照待人工补。

## Task 5(可选,闸门见 spec D-B4): 中立层下沉

- [x] **Step 0(闸门):** Task 4 全部通过才可开始;否则停止,本包到此收尾。
  → **闸门不满足,本包停在 Task 4,Task 5 未执行**(计划已声明这不算失败)。
  理由:Task 4 Step 3(真机复验)按编排要求交人工,尚未完成;spec 第一阶段验收
  准则第 5 条「真机验收」因此仍未签收,而 D-B4 闸门第 1 条要求「第一阶段已收尾」。
  中立层下沉是又一次结构位移,应当在视觉验收签收之后再启动。
- [ ] **Step 1:** Create `mf4_analyzer/qt_analysis_shared.py`,从 `analysis_axes.py`
  剪切 `_robust_db_ceiling` / `_auto_db_window` / `_slice_amp_bounds` /
  `_SLICE_MAX_SPAN_DB` / `_SmoothImageItem`;`analysis_axes.py` 改为再导出
  (`from ..qt_analysis_shared import ...`——注意包层级,`analysis_axes` 在
  `ui/pg_canvas/` 下,需 `from mf4_analyzer.qt_analysis_shared import`)。
- [ ] **Step 2:** 断言中立性:子进程 `import mf4_analyzer.qt_analysis_shared` 后
  `sys.modules` 无 `mf4_analyzer.ui`(仿 `tests/test_batch_render_import_boundary.py`
  写一条新测试放进该文件)。
- [ ] **Step 3:** `PYTEST tests/test_batch_render_import_boundary.py tests/ui/test_analysis_axes.py tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py -q`
  全部与基线一致。**不改 `batch_render_qt` 任何文件**(那是批处理第三步的事)。

---

## 明确禁止(执行者签收)

- 禁止顺手收敛三套 tick 密度实现(spec 附录已显式推迟)。
- 禁止把组 3(热图专属符号)一并搬走。
- 禁止在移动时"改进"函数(哪怕只是加类型注解)。

**执行者签收(2026-08-06):三条均已遵守。**
- 三套 tick 密度实现原样保留:`_apply_target_bottom_ticks` 与
  `_tick_counts_to_density` 逐字平移,`canvas.py` / `tick_density.py` /
  `batch_render_qt` 一律未触碰,`heatmap_canvas.py:264-268` 那段"重抄原因"注释
  也随函数原样搬走,未作任何调和。
- 组 3 全部留在 `heatmap_canvas.py`:colormap 块、`_AxisShim`、`_NamedColorMap`、
  `_HeatmapMappable`、`_HeatmapAxisHandle`、`_SliceDirToggle`,外加夹在移动区间
  中段但归属热图的 `_EMPTY_X_RANGE` / `_EMPTY_Y_RANGE`。
- 移动块零改动:536 行载荷经逐行比对确认与移动前**字节级相同**(不改名、不改签名、
  不加类型注解、不重排语句)。发现的 `time_axis_display_extent` 潜在缺陷
  (`params=None` 默认值触发 `AttributeError`)按「只记录不修」处理,写成
  characterization 用例钉住现状,未改产品代码。
