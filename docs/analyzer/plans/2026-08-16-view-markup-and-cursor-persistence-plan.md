# 时域标注与双游标工程持久化 · 实施计划

> 状态：**Wave 1–3 已落地**（2026-08-16）。D3 / D4 / D5 / D11 于 2026-08-16
> 按 [daily-review-followup-spec](../specs/2026-08-16-daily-review-followup-spec.md) §A 修订；
> 真机手验并入 followup plan Task 16。
> 设计以 spec 为准。身份修正：标注 `source` 存原始通道名，不是 `[short] channel`。
>
> 2026-08-16 复测：持久化与 View 切换主链通过。随后 Wave 3 补上 D10（重绘收口
> 重算 pill）和 D11（off 不销毁落点）；offscreen 聚焦 94 passed，真机两条还没手验。
>
> **设计**：`docs/analyzer/specs/2026-08-16-view-markup-and-cursor-persistence-spec.md`
> **基线**：`25e8f8b7`。工作区另有 UltraView 脏文件，本批次 **禁止** 修改
> `mf4_analyzer/ui/chart_stack/ultraview/**`、`tests/ui/test_ultraview_*.py`、
> `docs/lessons-learned/**`。不要 `git checkout` 别人的文件，不要提交。

**Goal:** 时域 View 的点标注和双游标 A/B 能随 `.tlproj` 保存/打开/切 View 恢复；
pill HTML、单游标 hover、分析区、标注工具开关不做。

**并行约束：** Wave 1 三个 Task 文件集合不相交，可三路同时施工。Wave 2 依赖
Wave 1 的公开 API 形状（spec D2/D3/D4），合入后再开。Agent 不得扩自己的文件名单。

---

## File Structure

| Task | 可写文件 | 禁止 |
|---|---|---|
| 1 语义层 | **Add** `mf4_analyzer/ui/view_overlay_state.py`；**Add** `tests/test_view_overlay_state.py`；**Modify** `view_state.py`、`project_io.py`、`tests/ui/test_view_state.py`、`tests/test_project_io.py` | 画布、view_bridge、MainWindow |
| 2 标注投影 | **Modify** `pg_canvas/annotations.py`、`remarks.py`、`canvas.py`；**Add** `tests/ui/test_pg_timedomain_remarks.py` | view_state、project_io、view_bridge、cursor.py |
| 3 双游标投影 | **Modify** `pg_canvas/cursor.py`；**Add** `tests/ui/test_pg_cursor_placement.py` | canvas.py、view_state、annotations |
| 4 接线 | **Modify** `view_bridge.py`、`_view_mixin.py`；**Modify** `tests/ui/test_view_bridge.py`、`tests/ui/test_project_session.py`；必要时 `tests/ui/test_split_routing.py` | UltraView、分析 mixin |
| 5 帮助一句 | `mf4_analyzer/help/TraceLab-使用说明.html` + 其契约测试若被钉住 | 不改 hints/quickref（无新手势） |

每个 Task 先红后绿。本机：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q <本 Task 文件>
```

---

### Task 1：Qt-free 语义层 + ViewState 字段 + fid remap

**并行：Wave 1。已完成**（[语义层](a521b7b6-b31f-4df0-b409-f41ed6c62e99)，87 passed）。

- [x] 新增 `view_overlay_state.py`（禁止 import PyQt5 / pyqtgraph / `mf4_analyzer.ui.pg_canvas`）：
  - `normalize_remark(raw) -> dict | None`
  - `normalize_remarks(raw) -> list[dict]`
  - `remap_remarks(remarks, fid_map) -> list[dict]`
  - `normalize_cursor_placement(raw, *, cursor_mode: str) -> dict | None`
  - 非法项丢弃；未知键保留在 remark 对象上；`source` 输出为 JSON 安全的 2-list。
  持久化层要求四数齐全；缺 `label_dx/dy` 的项在此丢弃。6%/8% 缺省只留给画布 restore。
  `bx` 非法时写成 `null`，不丢整个 placement。
- [x] `ViewState` 在 `view_id` **之后**追加 `remarks`（default `[]`）和
  `cursor_placement`（default `None`）。`to_dict`/`from_dict` 走 normalize。
  旧 payload 缺字段 = 空。不要改 `SCHEMA_VERSION`。
- [x] `remap_view_fids` 对每个 view 调 `remap_remarks`；`cursor_placement` 原样拷。
- [x] 测试（新文件为主，旧文件只加用例）：
  - 合法 round-trip、缺字段、非有限、短 source、未知键保留
  - `cursor_mode != "dual"` 或 `ax` 缺失 → `None`
  - remap 改 fid、缺 fid 丢点、cursor_placement 不丢
  - 既有 `test_viewstate_roundtrips_through_dict` 的 `again == st` 必须仍绿
    （新字段缺省为空即可）

**Verify:**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_view_overlay_state.py tests/ui/test_view_state.py tests/test_project_io.py
```

---

### Task 2：时域画布标注 snapshot / restore / clear 对称

**并行：Wave 1。已完成**（[标注投影](47e42087-438c-4349-a5f1-1934198ad841)；新文件 9 passed，既有 `-k remark` 8 passed，backref 护栏绿）。

- [x] `_nearest_data_point` / `_add_remark`：live remark 写入 `remark["source"] = (fid, ch)`。
  找轴用复合键，不用显示名。返回值末尾追加 `ck`，不改前 5 项顺序。
- [x] `AnnotationManager.snapshot_remarks() -> list[dict]`：D2 形状；`sip.isdeleted`
  的物品跳过；`label_dx/dy` 从 `text.pos - (data_x, data_y)`。四数齐全。
- [x] `restore_remarks(payload)`：`clear_remarks()` 后按 `_channel_lines` 复合键
  重绑；通道不在则跳过；x 吸附到该通道最近采样，y 用吸附点；缺偏移用现有 6%/8%。
- [x] `canvas.clear()`：在 `_glw.clear()` **之前** `clear_remarks()`。
- [x] 公开包装：`canvas.snapshot_remarks` / `restore_remarks`。同文件可加
  cursor placement 的 **getattr 防护** 包装（方法名 `snapshot_cursor_placement` /
  `restore_cursor_placement`，内部 `getattr(self._cursor, "snapshot_placement", None)`），
  以便 Wave 2 有宿主入口；Task 3 尚未合入时包装必须 no-op 而不是 AttributeError。
- [x] 若新增 `_owned_names`，同步 `test_pg_canvas_backref_invariants.py`。优先不新增写穿属性。
  snapshot/restore 进了 `_delegate_names`，未扩 `_owned_names`。
- [x] **Add** `tests/ui/test_pg_timedomain_remarks.py`

**Verify:**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_timedomain_remarks.py tests/ui/test_pg_canvas_backref_invariants.py
```

---

### Task 3：双游标 placement snapshot / restore

**并行：Wave 1。已完成**（[游标投影](cdd66222-1dd6-4df3-aabb-967d725e7cff)，35 passed）。
只改 `cursor.py` + 新测试文件。不要改 `canvas.py`（Task 2 的 getattr 包装是宿主入口）。

- [x] `CursorController.snapshot_placement() -> dict | None`：仅 `_dual` 且 `_ax`
  有限时返回 `{"ax": float, "bx": float|None}`。
- [x] `restore_placement(payload)`：校验后写 `_ax/_bx`，若 dual 已开则重画 A/B 线
  并 emit 读数。payload 空/`None` 不把 dual 关了（模式由 ViewState.cursor_mode 管）。
  恢复时额外同步 `_placing`（只 A → `"B"`，A+B → `"A"`），快照仍不含该字段。
- [x] 不改 `clear()` 保留 placement 的现契约；不改 pill 几何。
- [x] **Add** `tests/ui/test_pg_cursor_placement.py`：
  1. single 模式 snapshot 为 None
  2. dual 放 A+B → snapshot 数值
  3. `reset_cursor_state` 后 snapshot 为 None
  4. restore 后 `_ax/_bx` 恢复且有竖线物品

**Verify:**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_cursor_placement.py tests/ui/test_split_routing.py \
  tests/ui/test_split_per_pane_controls.py
```

split 两套是既有 pill 路由护栏，本 Task 不应改红。

---

### Task 4：view_bridge + 渲染事务接线 + 工程 round-trip

**Wave 2。已完成**（[接线](2e24fdfb-1ca7-4b2d-9f47-c918cdddc2cb) 122 passed；随后修正显示名身份，聚焦 123 passed）。

- [x] `capture_controls_into`：spec D5 合并标注；D3 写 `cursor_placement`。
  写入 ViewState 前走 `normalize_remarks`：画布 snapshot 必须带齐 `x/y/label_dx/label_dy`，
  否则语义层会丢整条（缺省偏移只允许出现在 `restore_remarks`，不进 `.tlproj`）。
- [x] `apply_controls_from_state`：只恢复 `cursor_mode`（已有）。标注和 dual 落点
  **不要**在 apply 里做——轴还没建。
- [x] `_render_view_onto_canvas`：`settle_view_restore()` 之后、
  `_applying_view` 仍为 True 时：`restore_remarks(state.remarks)` 然后
  `restore_cursor_placement(state.cursor_placement)`。
  `cursor_mode=="off"` 清主 pill 的既有分支保留。
- [x] 新 View / duplicate：`from_dict` 已拷 remarks；duplicate 后两 View 独立，
  之后编辑互不影响（capture 按 idx）。
- [x] 测试：
  - `test_view_bridge.py`：capture 合并隐藏通道、删除可见点不复活
  - `test_project_session.py`：加点 + dual A/B → `save_project` → 新
    `MainWindow.open_project` → 标注条数/source/x、`cursor_mode=="dual"`、
    `_ax/_bx` 一致
  - 切 View：View1 有点、View2 无点，来回切不串
- [x] 身份：`source[1]` 必须是 navigator 的原始通道名。画布行是
  `[{short_name}] channel`；`normalize_remark` / snapshot / restore 按 fid + 原始名
  匹配，D5 才能把「可见通道上删点」和「隐藏通道保留」分清。

**Review 补记（2026-08-16）：本 Task 的验证清单漏了 spec §2 契约的后半句。**
上面的用例只断言 `state.cursor_placement`、`cursor._ax/_bx` 和
`_cursor_a_items` 可见，**没有一条断言 pill 的内容**。而
`restore_placement()` 把 `_ax/_bx` 写在 `if not self._dual: return` 之前，所以
即使竖线没画、pill 没 emit，这些断言也会绿——护栏结构性地测不到用户看见的那
一半。Wave 3 Task C 补齐；本 Task 其余部分（D5 合并、D7 时机、身份）复测有效，
不回退。

**Verify:**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_view_bridge.py tests/ui/test_project_session.py \
  tests/ui/test_split_routing.py tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_main_window_state_ownership.py
```

---

### Task 5：帮助「工程里存了什么」补一句

**Wave 2。已完成**（[帮助](8fb21107-8396-4c70-845b-7a969e26b4cf)，`test_help_content.py` 26 passed，契约未钉旧句故未改测试）。

- [x] 只改 project 卡片第一段：点标注和双游标位置会进工程，单游标读数和标注工具开关不会。
- [x] 不改 `hints.py` / `quickref.py`。不升版本。

---

## Wave 3：读数重算 + 落点生命周期 + 用户可见量护栏

**为什么有 Wave 3。** 用户实测「游标和标注还是没完全接上，双游标读数面板不显示」。
2026-08-16 复测把范围收窄到两条，主链本身是好的：

| 路径 | 结果 |
|---|---|
| 重开工程（`open_project`） | ✅ dual 开、A/B 竖线可见、pill 可见且 full、逐通道行齐全、可继续点击 |
| 切到别的 View 再切回 | ✅ 同上；新 View 不带走上一 View 的游标 |
| 重绘后标注 | ✅ 仍是活 Qt 物件（`live=1, snap=1`），未悬挂 |
| **勾选第 2 个通道后重绘** | ❌ `channel_data` 已有 2 条，pill 仍只有 `[a] rpm` 一行 |
| **dual → off → dual** | ❌ `_ax=None`、pill 消失，但 ViewState 里 `cursor_placement` 还在 |

根因已定位：手动调一次 `_emit_dual_cursor_html()`，行数立刻从 1 变 2——**计算是
对的，重绘后没人调用它**（spec D10）。

Wave 3 三个 Task 文件集合不相交，可并行。Task C 依赖 A/B 的行为，最后合。

### Task A：重绘收口处重算读数（spec D10）

**已完成**（[Wave 3 游标收口](95fc8248-8588-46d0-8183-79429e161992)）。收口点：
`TimeDomainCanvasPG._restore_dual_cursor_items` 末尾。

- [x] 在时域画布重绘的**收口点**（曲线与 `channel_data` 都已就绪之后）调一次
  `_emit_dual_cursor_html()`；`_ax` 为空或非 dual 时 no-op。找到那一个收口点，
  **不要**散到 `plot_time` / navigator / 模式切换各调用方去补。
- [x] A/B 竖线在重绘后按新的 axes 集合重建（多通道 subplot 下每个 axes 一条）。
  今天 `lines=2/2` 说明这部分已经对，别改坏。
- [x] 不改 pill 几何、不碰 mini/full、不动 split 的 pill 路由。
- 可写：`pg_canvas/canvas.py`、`pg_canvas/cursor.py`；禁止：view_bridge、_view_mixin、view_state。

### Task B：`off` 不销毁落点（spec D11）

**已完成**（同上，串行合入）。`set_dual_cursor_mode(False)` 只隐藏并清 pill，
保留 `_ax/_bx/_placing`；True 且 `_ax` 有限时重画竖线并重算读数。

- [x] `set_cursor_mode('off')` 不再清 `_ax/_bx`——与 D4「`clear()` 不重置」同语义。
  切到 `off` **仍必须清主 pill**（既有 split 契约，`codex-cursor-pill-view-apply`）。
- [x] `off → dual` 后竖线和读数按现存 `_ax/_bx` 回来。
- [x] `reset_cursor_state()` 的语义保持「显式重置」，仍清落点；确认它现在的调用方
  里哪些是「用户显式重置」、哪些只是「切模式」，后者不该调。
- [x] `snapshot_placement()` 在 `off` 下仍返回 None（D3 不变，落点只在 dual 时进工程）。
- 可写：`pg_canvas/cursor.py`（与 Task A 同文件，二选一先合或同一 agent 串行做）；
  禁止：canvas.py、view_bridge、view_state。

> ⚠️ Task A 和 Task B 都改 `cursor.py`。要么同一个 agent 串行做，要么 A 先合 B 再开。
> 不要两路并行写同一文件——本仓库刚因并行写同文件出过一次事故。

### Task C：护栏改判据——断言用户看得见的量（spec §5）

**已完成**（TDD：改生产前 `test_pg_cursor_placement.py` 2 failed / 6 passed）。

- [x] `tests/ui/test_pg_cursor_placement.py`：现有 5 条只测 `_ax/_bx` 和线，**保留**，
  再补 pill 内容断言：dual 放好 A/B 后 pill 行数 == 可见通道数、行名与
  `channel_data` 键一致。
- [x] 新增「重绘后重算」用例（Task A 的红→绿）：1 通道放 A/B → 勾第 2 个通道重绘 →
  **pill 行数变 2 且含新通道名**。这条在 Task A 之前必须是红的，否则判据没选对。
- [x] 新增「off→dual 落点还在」用例（Task B 的红→绿）。
- [x] `tests/ui/test_project_session.py::test_project_roundtrip_restores_remarks_and_dual_cursor`
  末尾补 pill 断言（重开后 pill 可见、行数与通道数一致）——今天它只到竖线可见为止。
- [x] 每条新用例都要**先验证「回退实现后它会红」**再算数。
- 可写：`tests/ui/test_pg_cursor_placement.py`、`tests/ui/test_project_session.py`；
  禁止：任何生产代码。

**Verify（Wave 3 合完一起跑）:**
```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_pg_cursor_placement.py tests/ui/test_project_session.py \
  tests/ui/test_view_bridge.py tests/ui/test_split_routing.py \
  tests/ui/test_split_per_pane_controls.py tests/ui/test_pg_canvas_backref_invariants.py
```

真机（`QT_QPA_PLATFORM=cocoa`）手验：多通道时域放 A/B → 勾一个新通道 → 读数面板
当场多出这一行；切 off 再切 dual，落点还在。

---

## 收尾

- [x] `git diff --check`：本批次文件无空白错误。UltraView 脏文件仍在工作区，不要夹带提交。
- [x] 不跑全量。不提交（除非用户明确要求）。Wave 3 聚焦套件 94 passed。
- [x] 真机手验（人工）：时域 overlay 两点标注 + 双游标 → 保存 → 重开；切 View 再回来。
  2026-08-16 复测通过（offscreen + cocoa）。
- [ ] Wave 3 真机手验：「重绘后读数跟着变」和「off→dual 落点还在」。

## 显式不做（本 plan 结束仍不做）

分析区标注与频率双游标、pill chrome、`annotation_enabled`、UltraView 板级标注、
截图 markup 编辑器、顶层 schema bump。
