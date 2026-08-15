# UltraView 适配、缩放与浮层消隐三处修正 实施计划

**设计**：`docs/analyzer/specs/2026-08-15-ultraview-fit-zoom-and-dismiss-fixes-spec.md`
（先读 spec，本文只写执行序，不复述依据）。
**基线**：`claude/ultraview-library-geometry-material@27e0cf90`。

**Goal:** 四条用户报出的缺陷各自收口——「按原图比例」改为 contain（只缩不放）；
画布空白点击能关掉未 pin 的浮层；「适应」适应**内容**并居中；缩放上限 200% → 300%。
不放宽任何既有护栏，不改 LOD 三档、不改 `ZOOM_MIN`、不动预览内存帽。

**Architecture:** 改动集中在四个点：`free_grid.fit_rect_for_aspect()` 的候选集与
排序键；`FreeGridBoard.mousePressEvent` 空白分支转发一次 canvas-click；
`page.zoom_fit()` 改用内容包围盒 + `zoom_to_rect` + `_apply_zoom_and_center`；
`viewport.ZOOM_MAX` 一行常量加三处文案。

**Tech Stack:** Python 3.12，PyQt5，pyqtgraph，pytest-qt，仓库 venv。
Qt 用例：`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q`。
本批**全部可离屏验收**（几何 + 事件路由），只有 §4 的预览观感留一次真机目视。

**基线纪律：** 动手前先跑
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_layouts.py \
  tests/ui/test_quickref.py
```
记下失败数。已知既有红：`tests/ui_kit/test_qss_palette_ratchet.py::
test_distinct_hex_literals_may_only_shrink`（distinct hex 261 > 上限 244，
`380e5ac2` 干净树上即红，属 UltraView 配色债，**不在本批**）。

---

## File Structure

- Modify `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py` — `fit_rect_for_aspect`
  候选集加上界 + 排序键改 `(误差, -面积)`。
- Modify `mf4_analyzer/ui/chart_stack/ultraview/widgets.py` — `FreeGridBoard.mousePressEvent`
  空白分支转发 canvas-click；`FreeGridBoard.content_rect_1x()`；`BoardGrid` 同类检查与
  `content_rect_1x()`。
- Modify `mf4_analyzer/ui/chart_stack/ultraview/chrome.py` — `_close_from_canvas_click`
  提升为公开 `close_from_canvas_click()`（保留私有别名一轮，避免外部引用断裂）。
- Modify `mf4_analyzer/ui/chart_stack/ultraview/page.py` — `notify_canvas_click()`
  转发；`zoom_fit()` 改内容适应。
- Modify `mf4_analyzer/ui/chart_stack/ultraview/viewport.py` — `ZOOM_MAX = 3.0`。
- Modify `mf4_analyzer/ui/quickref.py`、`mf4_analyzer/help/ultraview-guide.html` — 文案 300%。
- Modify tests：`test_ultraview_free_grid.py`、`test_ultraview_page.py`、
  `test_ultraview_viewport.py`、`test_quickref.py`。

每个 Task 先写红测再实现（TDD）；只跑对应文件，收尾 Task 5 跑全量两条命令。

---

### Task 0: 复现脚本入库

**Files:** Add `docs/analyzer/verify/2026-08-15-ultraview-fit-zoom-probes/probe_current.py`
+ `baseline.txt` + `README.md`。

- [ ] 一个脚本三段，照 spec §1.1 / §2.1 / §3.1 的三张表各打印一遍（离屏即可，
      脚本内自设 `QT_QPA_PLATFORM=offscreen`）：
      ① `fit_rect_for_aspect` 对 4×6 / 10×3 / 6×4 / 2×2 四个起点的输出与像素；
      ② 建 `_Harness`，分别向「自由网格内部空白」「网格之外的视口带」派发 press，
         打印命中 widget 链与 `is_library_visible()` 前后值；
      ③ 建 4 卡自由网格，打印 `unzoomed_size()` / 内容包围盒 / `_content_fit_rect()`
         / `zoom_fit()` 后的 zoom 与 `_fit_origin()`。
- [ ] 跑一遍存 `baseline.txt`（改前）。README 写明「本批是逻辑缺陷，离屏证据充分；
      唯一真机项是 300% 下的预览观感」。

**Done:** 三段输出与 spec 表逐项对上。

---

### Task 1: 「按原图比例」改为 contain（只缩不放）

**Files:** `free_grid.py`、`tests/ui/test_ultraview_free_grid.py`。

- [ ] 红测（新增，与既有 `test_fit_rect_for_aspect_prefers_matching_span` 并存）：
  1. `test_fit_rect_for_aspect_never_grows`：对 4×6 / 10×3 / 6×4 三个起点、同一
     原图 (1000, 800)，断言结果 `column_span ≤ origin.column_span`、
     `row_span ≤ origin.row_span`，且**三者互不相同**（改前全是 7×8）。
  2. `test_fit_rect_for_aspect_matches_user_contract`：用 spec §1.2 的两个判据造
     等价网格情形——宽为瓶颈时保列压行、高为瓶颈时保行压列。
  3. `test_fit_rect_for_aspect_prefers_the_largest_span_on_a_tie`：构造同比值的大小
     两组跨度，断言取大的。
  4. `test_fit_rect_for_aspect_result_is_a_subset`：结果矩形被原矩形包含（原点不动 +
     跨度只减），因此不可能与邻卡重叠。
- [ ] 实现：候选 `col_span in [GRID_MIN_COLUMN_SPAN, origin.column_span]`、
      `row_span in [GRID_MIN_ROW_SPAN, origin.row_span]`；键 `(abs(ratio - target), -area)`。
      保留 `chrome_height` 扣除与 `rect_to_pixels` 口径不变。docstring 改写为
      contain 语义并指向 spec §1。
- [ ] 既有 `test_fit_rect_for_aspect_prefers_matching_span`（origin 4×3）**先不改**，
      跑一遍确认仍绿（预期：wide→4×2、tall→1×3、square→2×3，三条断言都成立）；
      若不绿，先确认是语义冲突还是用例写死了旧行为，按 spec §1.3 判定，不放宽。
- [ ] `… -m pytest -q tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py`

**Done:** 四条新测绿，既有用例失败数不增。

---

### Task 2: 画布空白点击关闭未 pin 的浮层

**Files:** `chrome.py`、`page.py`、`widgets.py`、`tests/ui/test_ultraview_page.py`。

- [ ] 红测：
  1. `test_free_grid_blank_press_dismisses_the_library`：`_Harness` → 开库 →
     向自由网格**内部**空白点派发 press → `is_library_visible()` 为 False。
     （改前：连点两次都为 True。）
  2. `test_pinned_library_survives_a_blank_canvas_press`：pin 后同样操作 → 仍可见。
  3. `test_blank_press_during_drag_defers_the_dismiss`：`page._on_drag_started("ref")`
     后 press → 仍可见且 `_deferred_panel_close` 已置位；`_on_drag_finished()` 后关闭。
  4. `test_card_press_does_not_dismiss_the_library`：落在卡片上的 press 维持现状。
  5. `test_blank_press_still_clears_selection_and_starts_marquee`：原有行为不回退。
  6. 模板模式同名一条（若 `BoardGrid` 也自行 accept 空白 press）。
- [ ] 实现：`CanvasHost._close_from_canvas_click` → 公开 `close_from_canvas_click()`
      （私有名保留为别名一轮）；`UltraViewPage.notify_canvas_click()` 转发到
      `self._canvas_host.close_from_canvas_click()`；`FreeGridBoard.mousePressEvent`
      空白分支开头经 `_page_of(self)` 调用它，再做既有的清选中 / `begin_marquee`。
      **不新增信号、不新增 `.connect(lambda`。**
- [ ] `… -m pytest -q tests/ui/test_ultraview_page.py tests/ui/test_ultraview_free_grid.py tests/ui/test_no_lambda_signal_connections.py`

**Done:** 六条新测绿；pin 与拖拽两条例外都有守卫。

---

### Task 3: 缩放上限 200% → 300%

**Files:** `viewport.py`、`quickref.py`、`help/ultraview-guide.html`、
`tests/ui/test_ultraview_viewport.py`、`tests/ui/test_quickref.py`。

先于 Task 4 落地，好让 Task 4 的验收能断言「单卡适应顶到 300%」。

- [ ] 红测：`test_zoom_clamps_at_three_hundred_percent`：`clamp_zoom(5.0) == ZOOM_MAX`
      且 `ZOOM_MAX == 3.0`、`zoom_percent(ZOOM_MAX) == 300`。
- [ ] 实现：`ZOOM_MAX = 3.0`。`ZOOM_MIN` / `ZOOM_BUTTON_STEP` / LOD 三档不动。
- [ ] 既有用例改字面量为常量（spec §4 表）：`viewport.set_zoom(3.0) == ZOOM_MAX`
      改喂 `5.0`；`set_board_zoom(2.0) == ZOOM_MAX` 两处（约 215 / 922）与 983-988
      一处改用 `ZOOM_MAX`。**这是把用例从"钉住旧上限"改成"钉住 clamp 语义"，
      不是放宽**——提交信息里写清。
- [ ] 文案两处：`quickref.py:510` 与 `help/ultraview-guide.html:111` 的「25%–200%」
      → 「25%–300%」；`tests/ui/test_quickref.py` 若断言了该串，同步。
- [ ] `… -m pytest -q tests/ui/test_ultraview_viewport.py tests/ui/test_quickref.py tests/ui/test_help_content.py`

**Done:** 上限用例绿；三处文案与常量一致。

---

### Task 4: 「适应」改为适应内容并居中

**Files:** `widgets.py`、`page.py`、`tests/ui/test_ultraview_viewport.py`。

- [ ] 红测：
  1. `test_zoom_fit_fills_the_safe_zone_with_content`：4 卡自由网格 → `zoom_fit()`
     后，卡片包围盒在安全区里至少一维占 ≥ 80%（改前实测 ~57%）。
  2. `test_zoom_fit_centers_content_in_the_safe_zone`：内容中心与安全区中心
     对齐（±2 px）。
  3. `test_zoom_fit_on_an_empty_board_keeps_the_logical_canvas_fit`：空板走现状分支。
  4. `test_zoom_fit_single_card_hits_the_zoom_ceiling`：单卡 → `board_zoom() == ZOOM_MAX`
     （依赖 Task 3 的 3.0）。
  5. 模板模式一条同类。
- [ ] 实现：`FreeGridBoard.content_rect_1x()`（placements 的 `rect_to_pixels` 并集，
      用 `_base_metrics`）、`BoardGrid.content_rect_1x()`（已占用 slot 的
      `unzoomed_slot_rect` 并集），无内容返回 `None`；`page.zoom_fit()` 改为：
      内容盒 `None` → 现状 `_park_zoom(fit_zoom(...))`；否则
      `zoom_to_rect(content, (fit.width, fit.height), margin=0.08)` →
      `_apply_zoom_and_center(zoom, center)`。**视口尺寸取 `_content_fit_rect()`
      而非原始视口**（spec §3.3 第 3 条，与 `zoom_to_card` 的故意区别，写进注释）。
- [ ] 既有 `test_fit_and_zoom_to_card_end_state`（约 647 行）断言
      `board_zoom() == fit_zoom(unzoomed_size, fit)` —— 按新语义改成内容适应的期望值；
      改的是"适应"的定义，不是放宽断言，提交信息写清。
- [ ] 既有 `test_canvas_is_full_bleed_and_fit_parks_cards_in_the_safe_zone`
      **一行不改必须照过**（居中是在安全区内居中）。
- [ ] `… -m pytest -q tests/ui/test_ultraview_viewport.py tests/ui/test_ultraview_page.py tests/ui/test_ultraview_layouts.py`

**Done:** 五条新测绿；安全区契约用例零改动照过。

---

### Task 5: 收尾

- [ ] 重跑 Task 0 探针存 `after.txt`，逐项对 spec §6 验收表打勾；README 补"改后"列。
- [ ] 真机目视一次（唯一真机项）：300% 下卡片预览的软化程度是否可接受；结论写进
      spec §4 已知副作用段。若不可接受，**不在本批调帽**，另立 follow-up。
- [ ] 全量两条命令：`--ignore=tests/acquisition_ui` 跑主体，另起一条单跑
      `tests/acquisition_ui`；对照 CLAUDE.md 基线（主体 7046 passed / 24 skipped /
      11 failed = 9 顺序污染 + 2 条 `380e5ac2` 既有红），**新增红为零**。前后各
      `git status --porcelain` 对账。
- [ ] `/update-hints` 核对：本批改了「按原图比例」「适应」「缩放范围」三处可感知
      行为，`ui/hints.py` 与 `ui/quickref.py` 的描述需与新语义一致（quickref 的
      「尺寸预设」「画布缩放 / 平移」两行）。
- [ ] spec 顶部状态改「已实施」+ 实施注记表（验收项 / 改前 / 改后 / 判定）；
      plan 勾选项打勾。
- [ ] 提交粒度：Task 1 / 2 / 3 / 4 / 5 各一 commit，信息引用 spec 节号。

---

## 风险与回退

- **contain 后卡片可能很小**（极端比例原图 + 窄卡）：下限由既有 `GRID_MIN_*_SPAN`
  兜住；用户已确认接受"只缩不放"。
- **空白 press 关浮层打断框选视线**：若真机手感不佳，改为 release 时关——回退点单一。
- **适应居中改变肌肉记忆**：左上停靠是 `94934485` 引入的新行为，本批是修正而非二次翻转。
- **300% 预览变软**：位图预览固有代价（`MAX_PREVIEW_RAW_EDGE = 1600`）。本批不动
  抓图分辨率与内存帽；要治另立一批（涉及 residency 分级与内存策略）。
- **四条互不耦合**，可逐条回退；Task 3 是一行常量。
