# pg_canvas 切片子图独立与同构去重 · 实施计划(包 C)

> **For agentic workers:** 严格按 C1→C2→C3→C4 顺序执行(风险递增,前面的测试
> 成为后面的安全网)。每个子项:先补测试 → 再动代码 → 全量验证 → 独立 commit。
> 任一子项验收不过 → revert 该子项并停下回报,**不要带伤推进下一项**。

**设计文档:** [2026-08-04-pg-canvas-slice-panel-and-dedup-design.md](../specs/2026-08-04-pg-canvas-slice-panel-and-dedup-design.md)
**前置:** 包 B 已合并(`ui/pg_canvas/analysis_axes.py` 存在)。基线以**包 B 合并后的
main** 为准(本计划行号仍引 `e385ce5a`,Task 0 需重定位)。
分支:`refactor/pg-canvas-slice-and-dedup`。
**`PYTEST` =** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

> **执行记录(2026-08-06):** 分支 `refactor/pg-canvas-slice-and-dedup`,基线
> `ab19622f`,12 个 commit。C1→C4 全部落地,失败集与基线一致。
> **所有「真机截图」步骤按编排要求跳过**(未启动 GUI、未截图,也没有拿 offscreen
> 冒充)——下面标 `[~]` 的即是。改动触碰的可视面清单写在
> `docs/analyzer/verify/pg-slice-dedup-anchors.md` 末节,供 orchestrator 的
> 两侧真机渲染哈希对比扩充场景。量化与失败集见
> `docs/analyzer/verify/pg-slice-dedup-baseline.txt`。
**画布全量 =** `tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_decomposition_characterization.py tests/ui/test_slice_amp_floor_guard.py tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_axis_frame_alignment.py tests/ui/test_pg_remarks.py`

## Task 0: 锚点重定位 + 基线(失配即停)

- [x] **Step 1:** 包 B 合并后行号已漂移。重新定位并记录到
  `docs/analyzer/verify/pg-slice-dedup-anchors.md`:
  - 空态提示三件套:`grep -n "empty_hint\|_reposition_empty" line_canvas.py heatmap_canvas.py`
  - remark 视口层:`grep -n "_remark_item_at_viewport_pos\|_viewport_pos_to_scene"` 两文件
  - 分栏对齐四件套:`grep -n "split_layout_alignment\|_unify_stacked_left_axes"` 两文件
  - 切片带:`grep -n "_slice" heatmap_canvas.py`(盘点全部 `_slice_*` 字段与方法,
    列出「切片专属」与「主图/切片共用」两栏——共用项是 C4 的接口面)
- [x] **Step 2:** 外部消费面:`grep -rn "slice" tests/ui/test_pg_heatmap_canvas.py | head -40`
  与 `grep -rn "_slice\|slice_" mf4_analyzer/ui/chart_stack/ mf4_analyzer/ui/main_window/`
  ——记录哪些切片方法/属性被类外访问(这些必须保留薄委托)。
- [x] **Step 3:** 基线:画布全量存档
  `docs/analyzer/verify/pg-slice-dedup-baseline.txt`(在**当前 main** 上重采,
  未复用旧基线:画布全量 698 passed / 0 failed,`tests/ui/` 3086 passed / 2 failed);
  ~~真机基线截图~~ **跳过**。

## Task C1: 空态提示去重

**Files:** Create `mf4_analyzer/ui/pg_canvas/empty_hint.py`、`tests/ui/test_empty_hint.py`;
Modify `line_canvas.py`、`heatmap_canvas.py`。

- [x] **Step 1(测试先行):** 写 `test_empty_hint.py`(spec D-C1 用例,
  `@pytest.mark.parametrize` 两画布),在**基线**上跑绿,commit。
- [x] **Step 2:** 逐行 diff 两边三件套;差异逐条归类(无意漂移/真实差异)记入
  anchors 文档。实现 `EmptyHintOverlay`,两画布方法变薄委托,签名不变。
- [x] **Step 3:** `PYTEST tests/ui/test_empty_hint.py` + 画布全量,与基线一致。commit。

## Task C2: remark 视口层去重

**Files:** Modify `mf4_analyzer/ui/pg_canvas/remarks.py`、`line_canvas.py`、
`heatmap_canvas.py`、`tests/ui/test_pg_remarks.py`。

- [x] **Step 1(测试先行):** 扩充 `test_pg_remarks.py`(命中/未命中/重叠优先级,
  parametrize 两画布),基线跑绿,commit。
- [x] **Step 2:** `_remark_item_at_viewport_pos`(先 `diff` 确认两边逐字相同——
  不同则停下回报)与 `_viewport_pos_to_scene` 移入 `remarks.py` 模块级函数,
  两画布薄委托。
- [x] **Step 3:** `PYTEST tests/ui/test_pg_remarks.py` + 画布全量。commit。

## Task C3: 分栏对齐去重(差异审计驱动)

**Files:** Modify `mf4_analyzer/ui/pg_canvas/_split_mixin.py`、`line_canvas.py`、
`heatmap_canvas.py`。

- [x] **Step 1(审计):** 四件套逐对 diff(相似度 0.638 / 0.167 / 0.172 / 0.509,
  **没有一对逐字相同**),13 处差异全部定性:10 处可解(5 处文档层分叉、
  4 处在缺守卫的那一侧是恒真空操作、1 处是同一组调用的两种写法)、
  2 处真实差异用钩子吸收、**1 处无法判定**(heatmap 的 `_bottom_collapsed`
  守卫,line 没有)。1 ≤ 2,按计划继续,该处**保留分叉**并用测试钉住两种行为。
  审计表在 anchors 文档。
- [x] **Step 2:** 按审计结论把公共核心提入 `_StackedSplitMixin`(它已是两画布的
  共同基类),画布侧保留差异钩子。
- [x] **Step 3:** `PYTEST tests/ui/test_stacked_left_axis_metrics.py tests/ui/test_subplot_left_axis_metrics.py tests/ui/test_axis_frame_alignment.py tests/ui/test_split_container.py` + 画布全量。
  注意:`main` 上部分 `test_split_*` 本来就红(CLAUDE.md 已知问题)——只要求
  **失败集不变**,不要求转绿;若顺手修好了要在 PR 里单独说明。
- [~] **Step 4(跳过):** 真机:分屏折叠/展开/拖分隔条,对照基线截图。
  ——按编排要求不做真机截图。改动触碰的分栏几何量(左轴共同宽度、底轴高度、
  右侧留白两边**语义相反**、折叠态 unify 差异)已列进 anchors 文档的可视面清单。

## Task C4: 切片子图独立(两步走)

**Files:** Create `mf4_analyzer/ui/pg_canvas/slice_panel.py`、`tests/ui/test_slice_panel.py`;
Modify `heatmap_canvas.py`。

- [x] **Step 1(测试先行):** 写 `test_slice_panel.py`,33 条,**对着现有
  `PgHeatmapCanvas` 的公开切片接口写**,基线跑绿,commit。
  偏差:**未引入 `sliceMoved` / `sliceDirectionChanged`** —— 设计同时要求
  「外部消费者零改动」,而 `chart_stack` 接的是既有的 `slice_picked` /
  `slice_hint_requested`;新造一对平行信号等于披着重构外衣改 API。
- [x] **Step 2(类内聚拢,行为零变化):** 18 个切片专属方法收拢进
  `_SliceStrip(_CanvasBackref)`,函数体逐字未改,原方法全部变薄委托。
  聚合对象名用 `self._slice` —— **`self._slice_panel` 已被信息面板 QWidget 占用**
  (7 处测试直接读)。画布全量 + `test_slice_panel.py` 绿;真机切片操作**跳过**。
- [x] **Step 3(移出文件):** `_SliceStrip` + `_SliceDirToggle` 平移至
  `slice_panel.py`,`heatmap_canvas.py` import 之。同套验证全绿。
- [~] **Step 4(跳过):** 真机完整验收 FFT-Time / Order 两方向 + 拖动切片线。
  ——切片曲线数据、幅值域、marker 角度、右边缘对齐 reserve、信息面板定位与
  窄宽度 toggle 钳制,都已列进 anchors 文档的可视面清单。

## Task 5: 收尾

- [x] **Step 1:** 画布全量 **722 passed / 0 failed**(基线 698,+24 为
  `test_pg_remarks.py` 新增);`tests/ui/` 全量 **3204 passed / 2 failed**
  (基线 3086 / 2)。**失败集完全一致**,仍是 CLAUDE.md 那两条既有红。
  另跑导入边界用例(`_split_mixin` 新增了 `ui_kit.axis_metrics` 依赖):118 passed。
- [x] **Step 2:** `heatmap_canvas.py` **2518 → 1999,−519 行**(目标 −400)。
  C1/C2 范围的实现层逐字重复 **50 行 → 0**(剩下的 10 行全是 2 行薄委托,
  正是计划要求的形态)。明细见 anchors 文档「收尾量化」节。
- [~] **Step 3(不适用):** 未建 PR(编排要求不 push、不合并)。差异审计表与行数
  变化已进 `docs/analyzer/verify/`;真机截图对照改由 orchestrator 的自动化承担,
  本包只交付可视面清单。

## 明确禁止

- 禁止顺手统一滚轮派发(spec 附录已推迟)。
- 禁止动 `canvas.py` 与 `plot_channels`。
- 禁止在 C3 合并「无法判定」的差异——那是 bug 温床,宁可保留分叉并记录。
- 禁止用 offscreen 截图充当真机验收。
