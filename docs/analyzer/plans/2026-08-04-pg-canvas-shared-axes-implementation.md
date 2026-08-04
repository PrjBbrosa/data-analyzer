# pg_canvas 公共轴层提取 · 实施计划(包 B)

> **For agentic workers:** 按任务逐条执行,checkbox 跟踪。第一阶段(Task 0–4)必做;
> 第二阶段(Task 5)有闸门,闸门不满足就停在 Task 4,**不算失败**。

**设计文档:** [2026-08-04-pg-canvas-shared-axes-design.md](../specs/2026-08-04-pg-canvas-shared-axes-design.md)
**基线:** `main` @ `6236a5fe`。分支:`refactor/pg-canvas-shared-axes`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

## 全局约束

- **函数体逐字平移**,不改名、不改签名、不合并、不"顺手修"。发现疑似 bug 只记录,不修。
- 不触碰 `canvas.py`;不触碰 `PgHeatmapCanvas` / `PgLineCanvas` 方法体(import 区除外)。
- 每任务一个 commit;移动(Task 2)与测试新增(Task 1)分开提交。

---

## Task 0: 锚点核验 + 基线采集(失配即停)

- [ ] **Step 1:** 核验移动清单锚点:
  `grep -n "^def \|^class \|^_AUTO\|^_SLICE" mf4_analyzer/ui/pg_canvas/heatmap_canvas.py | awk -F: '$1 < 830'`
  应与 spec「移动清单」三组一致(组 1+2 共 19 个符号,行号 :260-:784)。
- [ ] **Step 2:** 核验反向导入现场:`sed -n '29,44p' mf4_analyzer/ui/pg_canvas/line_canvas.py`
  应为「3 个来自 canvas 的 AA 常量 + 8 个来自 heatmap 的符号」。
- [ ] **Step 3:** **monkeypatch 风险清单**(spec D-B2 风险点):
  `grep -rn "heatmap_canvas" tests/ | grep -i "monkeypatch\|setattr\|patch"`,
  并对组 1+2 的每个符号名 `grep -rn "<符号>" tests/`。逐条记录:哪个测试、patch 的
  是哪个模块路径、行使的是哪个画布。存入
  `docs/analyzer/verify/pg-shared-axes-patch-audit.md`。
- [ ] **Step 4:** 基线失败集:
  `PYTEST tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_axis_frame_alignment.py tests/ui/test_axis_grid_label_slack.py tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_colorbar_reset.py tests/ui/test_slice_amp_floor_guard.py tests/ui/test_pg_canvas_decomposition_characterization.py -q > docs/analyzer/verify/pg-shared-axes-baseline.txt 2>&1 || true`
- [ ] **Step 5:** 真机基线截图(macOS 原生,非 offscreen):启动 GUI,对同一份测试数据
  各出一张 FFT / FFT-Time / Order 图,截图存 `docs/analyzer/evidence/pg-shared-axes/baseline/`。
  (可参考 `scripts/` 内既有截图辅助;没有就手动截,文件名注明图种。)

## Task 1: 纯函数直接单测(先行,红→绿在基线上)

**Files:** Create `tests/ui/test_analysis_axes.py`

- [ ] **Step 1:** 按 spec D-B3 的用例清单编写,**当前先 import 自 `heatmap_canvas`**,
  文件头注释注明「Task 2 落地后 import 改指 `analysis_axes`」。
  断言值以基线实测为准(先跑一次函数看真实输出再固化,不要凭直觉写期望值)。
- [ ] **Step 2:** 跑绿,单独 commit。

Run: `PYTEST tests/ui/test_analysis_axes.py -q`

## Task 2: 创建 `analysis_axes.py` 并平移(核心动作)

**Files:** Create `mf4_analyzer/ui/pg_canvas/analysis_axes.py`;
Modify `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`(只动 import 区与删除被移动块)。

- [ ] **Step 1:** 新建 `analysis_axes.py`:docstring(spec D-B1 措辞)+ 从
  `heatmap_canvas.py` **剪切**组 1+2 的 19 个符号,函数体逐字不动。头部 import
  从 heatmap 现有头部挑选实际需要的(pg / QtCore / numpy / `GridLabelSlackAxisItem` 等),
  最小化。
- [ ] **Step 2:** `heatmap_canvas.py` 顶部加
  `from .analysis_axes import (<19 个符号>)  # noqa: F401 — 兼容旧路径与 monkeypatch`,
  内部调用点**一律不改写**。
- [ ] **Step 3:** `PYTEST tests/ui/test_pg_heatmap_canvas.py -q` 与基线一致;
  `git diff --color-moved=dimmed-zebra` 人工确认移动块零字符变化。

## Task 3: line_canvas 切换 import,消除依赖倒置

**Files:** Modify `mf4_analyzer/ui/pg_canvas/line_canvas.py`(仅 :35-44 一处);
按 Task 0 Step 3 的审计结论,可能修改个别测试的 patch 目标。

- [ ] **Step 1:** `from .heatmap_canvas import (...)` → `from .analysis_axes import (...)`。
- [ ] **Step 2:** 审计清单里「patch heatmap 路径 + 行使 line 行为」的测试,把 patch
  目标改为 `analysis_axes`;每处改动在 commit message 里逐条列出。
- [ ] **Step 3:** 验证倒置消除:
  `grep "from .heatmap_canvas import" mf4_analyzer/ui/pg_canvas/line_canvas.py` → 空。
- [ ] **Step 4:** Task 1 的测试文件把 import 改指 `analysis_axes`。

Run: `PYTEST tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_axes.py -q`

## Task 4: 第一阶段收尾验收

- [ ] **Step 1:** 全套画布测试对比基线失败集(Task 0 Step 4 同一命令),差异必须为空。
- [ ] **Step 2:** 像素守护:`PYTEST tests/ui/test_pg_canvas_decomposition_characterization.py -q` 绿。
- [ ] **Step 3:** 真机复验:重复 Task 0 Step 5 的三张图,与基线截图并排目视核对
  (轴框、刻度数量与位置、colorbar、字号),存 `.../evidence/pg-shared-axes/after/`。
  **有任何肉眼可辨差异 → 停下排查,不得以 offscreen 结果替代。**
- [ ] **Step 4:** 量化核对:`heatmap_canvas.py` 减少 ≥500 行;PR 描述附
  patch-audit 文件与截图对照。

## Task 5(可选,闸门见 spec D-B4): 中立层下沉

- [ ] **Step 0(闸门):** Task 4 全部通过才可开始;否则停止,本包到此收尾。
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
