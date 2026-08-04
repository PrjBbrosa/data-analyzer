# pg_canvas 切片子图独立与同构去重 · 实施计划(包 C)

> **For agentic workers:** 严格按 C1→C2→C3→C4 顺序执行(风险递增,前面的测试
> 成为后面的安全网)。每个子项:先补测试 → 再动代码 → 全量验证 → 独立 commit。
> 任一子项验收不过 → revert 该子项并停下回报,**不要带伤推进下一项**。

**设计文档:** [2026-08-04-pg-canvas-slice-panel-and-dedup-design.md](../specs/2026-08-04-pg-canvas-slice-panel-and-dedup-design.md)
**前置:** 包 B 已合并(`ui/pg_canvas/analysis_axes.py` 存在)。基线以**包 B 合并后的
main** 为准(本计划行号仍引 `e385ce5a`,Task 0 需重定位)。
分支:`refactor/pg-canvas-slice-and-dedup`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`
**画布全量 =** `tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_decomposition_characterization.py tests/ui/test_slice_amp_floor_guard.py tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_axis_frame_alignment.py tests/ui/test_pg_remarks.py`

## Task 0: 锚点重定位 + 基线(失配即停)

- [ ] **Step 1:** 包 B 合并后行号已漂移。重新定位并记录到
  `docs/analyzer/verify/pg-slice-dedup-anchors.md`:
  - 空态提示三件套:`grep -n "empty_hint\|_reposition_empty" line_canvas.py heatmap_canvas.py`
  - remark 视口层:`grep -n "_remark_item_at_viewport_pos\|_viewport_pos_to_scene"` 两文件
  - 分栏对齐四件套:`grep -n "split_layout_alignment\|_unify_stacked_left_axes"` 两文件
  - 切片带:`grep -n "_slice" heatmap_canvas.py`(盘点全部 `_slice_*` 字段与方法,
    列出「切片专属」与「主图/切片共用」两栏——共用项是 C4 的接口面)
- [ ] **Step 2:** 外部消费面:`grep -rn "slice" tests/ui/test_pg_heatmap_canvas.py | head -40`
  与 `grep -rn "_slice\|slice_" mf4_analyzer/ui/chart_stack/ mf4_analyzer/ui/main_window/`
  ——记录哪些切片方法/属性被类外访问(这些必须保留薄委托)。
- [ ] **Step 3:** 基线:画布全量存档
  `docs/analyzer/verify/pg-slice-dedup-baseline.txt`;真机基线截图
  (FFT-Time + Order,各开/关切片,分屏折叠/展开)存
  `docs/analyzer/evidence/pg-slice-dedup/baseline/`。

## Task C1: 空态提示去重

**Files:** Create `mf4_analyzer/ui/pg_canvas/empty_hint.py`、`tests/ui/test_empty_hint.py`;
Modify `line_canvas.py`、`heatmap_canvas.py`。

- [ ] **Step 1(测试先行):** 写 `test_empty_hint.py`(spec D-C1 用例,
  `@pytest.mark.parametrize` 两画布),在**基线**上跑绿,commit。
- [ ] **Step 2:** 逐行 diff 两边三件套;差异逐条归类(无意漂移/真实差异)记入
  anchors 文档。实现 `EmptyHintOverlay`,两画布方法变薄委托,签名不变。
- [ ] **Step 3:** `PYTEST tests/ui/test_empty_hint.py` + 画布全量,与基线一致。commit。

## Task C2: remark 视口层去重

**Files:** Modify `mf4_analyzer/ui/pg_canvas/remarks.py`、`line_canvas.py`、
`heatmap_canvas.py`、`tests/ui/test_pg_remarks.py`。

- [ ] **Step 1(测试先行):** 扩充 `test_pg_remarks.py`(命中/未命中/重叠优先级,
  parametrize 两画布),基线跑绿,commit。
- [ ] **Step 2:** `_remark_item_at_viewport_pos`(先 `diff` 确认两边逐字相同——
  不同则停下回报)与 `_viewport_pos_to_scene` 移入 `remarks.py` 模块级函数,
  两画布薄委托。
- [ ] **Step 3:** `PYTEST tests/ui/test_pg_remarks.py` + 画布全量。commit。

## Task C3: 分栏对齐去重(差异审计驱动)

**Files:** Modify `mf4_analyzer/ui/pg_canvas/_split_mixin.py`、`line_canvas.py`、
`heatmap_canvas.py`。

- [ ] **Step 1(审计):** 对四件套逐对生成 diff,每处差异写结论:
  (a) 无意漂移 → 统一到哪一边、为什么;(b) 真实差异 → 用什么参数/钩子吸收。
  审计表进 anchors 文档。**若「无法判定」的差异超过 2 处 → 停下回报,不合并。**
- [ ] **Step 2:** 按审计结论把公共核心提入 `_StackedSplitMixin`(它已是两画布的
  共同基类),画布侧保留差异钩子。
- [ ] **Step 3:** `PYTEST tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_subplot_left_axis_metrics.py tests/ui/test_axis_frame_alignment.py tests/ui/test_split_container.py` + 画布全量。
  注意:`main` 上部分 `test_split_*` 本来就红(CLAUDE.md 已知问题)——只要求
  **失败集不变**,不要求转绿;若顺手修好了要在 PR 里单独说明。
- [ ] **Step 4:** 真机:分屏折叠/展开/拖分隔条,对照基线截图。commit。

## Task C4: 切片子图独立(两步走)

**Files:** Create `mf4_analyzer/ui/pg_canvas/slice_panel.py`、`tests/ui/test_slice_panel.py`;
Modify `heatmap_canvas.py`。

- [ ] **Step 1(测试先行):** 写 `test_slice_panel.py`(spec D-C4 用例——方向切换、
  索引钳制、拖动命中、`sliceMoved` 载荷),**先对着现有 `PgHeatmapCanvas` 的
  公开切片接口写**,基线跑绿,commit。
- [ ] **Step 2(类内聚拢,行为零变化):** 在 `heatmap_canvas.py` 内新建内部类,
  把 Task 0 盘点为「切片专属」的方法与 `_slice_*` 字段收拢为 `self._slice_panel`;
  原方法全部变薄委托(外部与测试零改动)。跑画布全量 + `test_slice_panel.py`
  + 真机切片操作。commit。**此步红了 → revert,停下回报。**
- [ ] **Step 3(移出文件):** 内部类平移至 `slice_panel.py`(`_SliceDirToggle` 一并),
  `heatmap_canvas.py` import 之。跑同 Step 2 全套验证。commit。
- [ ] **Step 4:** 真机完整验收:FFT-Time 与 Order 各一张,两个切片方向、拖动切片线、
  开关切片行,对照基线截图(几何、图例、幅值范围、高亮带);截图存
  `.../evidence/pg-slice-dedup/after/`。

## Task 5: 收尾

- [ ] **Step 1:** 画布全量 + `tests/ui/` 全量,对比基线失败集,差异为空
  (新增测试除外)。
- [ ] **Step 2:** 量化:`heatmap_canvas.py` 较包 B 后再减 ≥400 行;C1/C2 范围的
  逐字重复对归零(用 Task 0 的 grep 复查)。
- [ ] **Step 3:** PR 描述附:差异审计表、真机截图对照、行数变化。

## 明确禁止

- 禁止顺手统一滚轮派发(spec 附录已推迟)。
- 禁止动 `canvas.py` 与 `plot_channels`。
- 禁止在 C3 合并「无法判定」的差异——那是 bug 温床,宁可保留分叉并记录。
- 禁止用 offscreen 截图充当真机验收。
