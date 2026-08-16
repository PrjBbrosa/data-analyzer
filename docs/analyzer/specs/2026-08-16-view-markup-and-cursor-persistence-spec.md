# 时域 View 标注与双游标工程持久化

- 日期：2026-08-16
- 状态：**已落地；D3 / D4 / D5 / D11 于 2026-08-16 按当日评审修订**（见
  [daily-review-followup-spec](2026-08-16-daily-review-followup-spec.md) §A）
- 基线：`25e8f8b7`（TraceLab 8.0.0）。工作区当时另有一组 UltraView 未提交改动，本批次**禁止**碰 `ui/chart_stack/ultraview/**`。
- 实施计划：[2026-08-16-view-markup-and-cursor-persistence-plan.md](../plans/2026-08-16-view-markup-and-cursor-persistence-plan.md)

## 0. 一句话

图上的点标注和双游标 A/B 落点是 View 的用户内容，必须变成与 Qt 无关的语义数据，跟 View 走、能进 `.tlproj`、打开后按复合通道身份重绑。游标读数面板（pill）的 HTML、单游标 hover、标注工具开关都不进工程。

## 1. 问题

`.tlproj` 今天存文件引用、通道勾选、`cursor_mode`、轴窗和分析参数。帮助页写「画面原样还原」，但：

1. **点标注**活在画布 Qt 物品上（`vb` / `dot` / `text` / `leader` + `data_x/y`），没有 `(fid, channel)`，不进 `ViewState`。
2. 时域 `plot_channels()` 先 `clear()` → `_glw.clear()`，ViewBox 拆掉；`clear()` **不** `clear_remarks()`，列表可能挂已删对象。切 View / overlay 重建后标注视觉消失。
3. **游标 pill** 被明确排除在 ViewState 外，只给分屏离屏渲染做 snapshot。新 View 不得带走上一 View 的 pill。
4. 双游标 A/B（`CursorController._ax/_bx`）是用户放置的意图，工程不写。单游标是 hover，存最后鼠标位置没有分析意义。
5. 分析画布每次 `plot_spectra` / `set_result` 都会 `clear_remarks()`；打开工程会重算。分析区不在本批次。

## 2. 产品契约

### 要恢复

| 内容 | 归属 | 重开后 |
|---|---|---|
| 点标注（通道、数据坐标、标签相对锚点偏移） | 每个时域 View | 绑到该 View 当前画布上仍存在的曲线 |
| 双游标 A/B 数据坐标 | 每个时域 View | `cursor_mode=="dual"` 时重画竖线并**重算** pill 读数 |
| `cursor_mode` | 已有 | 行为不变 |

### 不要恢复

- 标注工具开/关（卡片级工具态，一节共享）
- 单游标 hover 竖线和当时数字
- pill 的 HTML 原文、mini/full、拖放位置（chrome，本批次不做）
- 分析区标注 / 频率双游标落点
- 截图编辑器（`ui/markup/`）里的图片标注
- UltraView 板级便签/箭头（另一份 spec）

### 身份

标注不是「文件属性」。一块图可混多个文件。身份是 **View + 复合通道键 `(fid, channel)`**。显示名、缩短标签、tooltip 不得当 key。打开工程会重发 fid，必须走现有 `remap_view_fids`。

### 失败语义

缺文件、通道已不在该 View、数据空、非有限坐标 → **丢这条**，不崩溃、不 `min(len)` 偷裁、不把点贴到别的同名通道上。不为此弹 toast 风暴；工程级缺文件仍走现有 restore health。

## 3. 设计决策

**D1 · 语义层独立成 Qt-free 模块，ViewState 只持有。**

新建 `mf4_analyzer/ui/view_overlay_state.py`（无 PyQt5 / pyqtgraph）。`ViewState` 末尾追加两个缺省字段，不改变旧位置构造：

- `remarks: list[dict]`
- `cursor_placement: dict | None`

顶层 `.tlproj` `schema_version` **保持 2**。旧工程缺字段 = 空标注、无落点。

**D2 · 标注 JSON 形状（list of objects，不是 dict key）。**

```json
{
  "source": ["fid", "channel"],
  "x": 1.25,
  "y": 3.5,
  "label_dx": 0.08,
  "label_dy": 0.4
}
```

- `source` 与 `checked` 相同的 2-list，**不要**用 ylims 那种 JSON 字符串当 list 元素的 key。
- `x`/`y` 为放置用的数据坐标。恢复时按该通道现数据对 `x` 做最近采样吸附，**用吸附后的 y**（文件若变了，不坚持旧 y）。
- `label_dx`/`label_dy` = 标签 `text.pos` 减锚点 `(x, y)`，数据空间。缺省则按现 ViewBox 范围用现有 6% / 8% 启发式。
- 不存颜色、单位、HTML、ViewBox。颜色/单位从活曲线派生，标签走现有 `format_remark_label`。
- 非法项（缺 source、非 2-list、非有限数字）丢弃。对象上的未知键保留（前向兼容），规范化函数不得 `dict(source)` 打扁 `_ChannelKeyDict`。

**D3 · 双游标 JSON。**

```json
{ "ax": 1.0, "bx": 2.5 }
```

仅当 `ax` 为有限数字时写入；否则 `cursor_placement` 为 `null`。**不再按
`cursor_mode == "dual"` 门禁**（2026-08-16 修订：见 daily-review-followup-spec §A3）。
`bx` 可为 `null`（只放了 A）。不写 `placing`、不写单游标 x、不写 pill HTML。
`normalize_cursor_placement` 保留 `cursor_mode` 形参以兼容调用方，但不再用它过滤。

恢复：先按 View 的 `cursor_mode` 设显示，再 `restore_placement`；`off` 仍必须清主 pill（既有 split 契约，见 `codex-cursor-pill-view-apply`）。空 / 非法 payload 必须清 `_ax/_bx`（见 D11）。

**D4 · 画布持有意图列表，Qt 物品只是投影。**

（2026-08-16 修订：见 daily-review-followup-spec §A2。原「ViewState 是真相、
画布只投影」只覆盖了 View 事务；非事务重绘会 `clear_remarks()` 把意图一起清掉。）

- `AnnotationManager` 持有 Qt-free `_intent`（D2 形状）。`snapshot_remarks()` 返回意图列表，对仍有活投影的条目回读 `label_dx/dy` 与 `x/y`。
- `restore_remarks(payload)`：规范化后整体替换意图并立即投影。通道不在图上 → 意图保留不画。
- `clear_remarks()` 仍是全清（意图 + 物品）。`canvas.clear()` 改调 `_drop_remark_projection()`，只拆 Qt 物品。
- `plot_channels` 收口（紧邻 `_restore_dual_cursor_items`）调用 `_project_remarks()`，非 View 事务的重绘自动回来。
- `CursorController.snapshot_placement()` 不看 `_dual`。`restore_placement(None/非法)` 清空落点（见 D11）。
- `clear()` 仍不重置 `_ax/_bx`（现注释契约）；View 切换靠 `restore_placement` 覆盖或清空。

**D5 · Capture 不再合并推断（2026-08-16 修订：见 daily-review-followup-spec §A2）。**

意图列表已经是 View 作用域且含隐藏通道条目，D5 原先「live 没有 = 用户删了 /
隐藏通道从 previous 加回」的推断没有存在理由。

`view_bridge.capture_controls_into`：`state.remarks = normalize_remarks(snapshot)`。
`merge_remarks_for_capture` 标 deprecated，语义改为直通 `normalize_remarks(live)`。

双游标：`snapshot_placement()` 只要 `ax` 有限就写，不看 `cursor_mode`（与 D3 修订一致）。

**D6 · 复合键必须写进 live remark 字典。**

今天 `_add_remark` 用显示名 `ch` 找轴，物品上不存 `ck`。本批次：

- 添加时写入 `remark["source"] = (fid, channel)`（tuple，与 `ChannelKey` 一致）。
- `_nearest_data_point` 返回值带上 `ck`，不再只返回显示名。
- 恢复时 `_channel_lines.get(ck)`；禁止用显示名当身份。

**D7 · 恢复时机：标注意图在 plot 之前写入，投影由 plot 收口统一做。**

`_render_view_onto_canvas` 把 `restore_remarks(state.remarks)` 放在
`_plot_time_on_canvas` **之前**（只写意图；`clear()` 不丢意图，plot 收口
`_project_remarks()` 一次投影）。`restore_placement` 仍在 `settle_view_restore()`
之后、离开 `_applying_view` 之前。不要在 `plot_channels` 内部偷偷读 ViewState（画布不该 import View）。

**D8 · remap 走 project_io 现入口。**

`remap_view_fids` 改写每条 `remarks[].source[0]` 和不必需的嵌套；fid 不在 `fid_map` 则丢该项。`cursor_placement` 无 fid，原样保留。分析 `remap_analysis_view_fids` 本批次不动。

**D10 · pill 读数的重算触发点是「重绘收口」，不是 restore。**

§2 契约写的是「重画竖线并**重算** pill 读数」。Wave 1–2 只在
`restore_placement()`（View 渲染事务）和鼠标点击里调 `_emit_dual_cursor_html()`，
于是任何**不经 View 事务的重绘**——勾选/取消通道、`plot_time()`、overlay⇄subplot
切换——都只重画了 A/B 竖线，读数面板停在重绘前那一刻：新通道不出现，旧通道数值
不更新。实测（2026-08-16）：1 通道下放好 A/B，勾第 2 个通道重绘后
`channel_data` 已有 2 条，pill 仍只有 1 行；手动调一次 `_emit_dual_cursor_html()`
立刻变 2 行——计算是对的，只是没人调。

规则：**曲线集合或数据变了，读数必须跟着重算。** 时域画布在重绘收口处（曲线与
`channel_data` 都已就绪之后）统一调一次；`_ax` 为空或非 dual 时该调用是 no-op。
不要把这个调用散到各个调用方（`plot_time` / navigator / 模式切换）去补。

**D11 · 落点的生命周期只有一个真相。**

（2026-08-16 修订：见 daily-review-followup-spec §A3。原 D11 只让画布在 off 时
保留 `_ax/_bx`，但 `snapshot_placement` / `to_dict` / capture 仍按 dual 门禁
写成 None，一次保存就丢意图；`restore_placement(None)` 又是 no-op，View A
落点会漏进新建的 View B。）

- `set_dual_cursor_mode(False)` 只隐藏 A/B，不销毁 `_ax/_bx`。
- `snapshot_placement()` / `normalize_cursor_placement` / `to_dict` 不看模式。
- `restore_placement(None/非法)` **清空** `_ax/_bx`、隐藏 A/B 与极值标记、
  `_placing="A"`；dual 时 emit 一次让 pill 回到「Click A」。这是 View 事务里
  唯一能防止跨 View 泄漏的地方。
- `reset_cursor_state()` 仍是显式抹除。
- 切到 `off` 仍必须清主 pill（既有 split 契约不变）。

**D9 · 本批次明确不做。** （分析区标注与频率双游标随后由
`2026-08-16-analysis-overlay-persistence-spec.md` 落地，取代本条。）

- 分析 View / FRF / 频谱 / 热图标注与频率双游标
- pill mini/full 与用户拖位
- `annotation_enabled`
- 顶层 schema bump
- MainWindow 新增多文件赋值属性
- `.connect(lambda` 新增
- 帮助页大改版；只在「工程里存了什么」补一句（Wave 2）

## 4. 模块边界

| 模块 | 职责 |
|---|---|
| `ui/view_overlay_state.py` | 规范化、校验、fid remap；无 Qt |
| `ui/view_state.py` | 持有字段；`to_dict`/`from_dict` 委托 overlay 模块 |
| `ui/project_io.py` | `remap_view_fids` 调 overlay remap |
| `ui/pg_canvas/annotations.py` | snapshot/restore；source 写入 live 物品 |
| `ui/pg_canvas/remarks.py` | 标签偏移读写辅助（仍无 View 知识） |
| `ui/pg_canvas/cursor.py` | dual placement snapshot/restore |
| `ui/pg_canvas/canvas.py` | `clear()` 先清标注；公开 `snapshot_remarks` / `restore_remarks` / placement 包装 |
| `ui/view_bridge.py` | capture/apply 唯一进出 UI 的缝 |
| `ui/main_window/_view_mixin.py` | settle 之后 restore |

画布协作者的 `_owned_names` / `_delegate_names` 若新增托管属性，同步 `tests/ui/test_pg_canvas_backref_invariants.py`。优先把 snapshot 做成方法、不新增写穿宿主的属性。

## 5. 验证

聚焦（每 Task 只跑自己的）：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_view_overlay_state.py \
  tests/test_project_io.py \
  tests/ui/test_view_state.py \
  tests/ui/test_view_bridge.py \
  tests/ui/test_pg_timedomain_remarks.py \
  tests/ui/test_pg_cursor_placement.py \
  tests/ui/test_project_session.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_split_routing.py \
  tests/ui/test_split_per_pane_controls.py
```

机械护栏：`test_pg_canvas_backref_invariants.py`、`test_main_window_state_ownership.py`（若动 mixin 赋值）、`test_no_lambda_signal_connections.py`（若新 connect）。

不跑全量。不改 ink 常量。真机：时域加点 + 双游标 → 保存 → 重开，点仍在原通道、A/B 竖线在、pill 数字是重算的。

**判据必须是用户能看见的量。** Wave 1–2 的游标用例只断言 `_ax`/`_bx` 和
`_cursor_a_items`，全绿，但读数面板实际是陈旧的（见 D10）。注意
`restore_placement()` 把 `_ax/_bx` 写在 `if not self._dual: return` **之前**——
就算竖线没画、pill 没 emit，断言 `_ax/_bx` 的用例照样绿。凡是契约里写了「用户
看得到」的东西（pill 行数与内容、竖线可见性、标注落点像素），护栏就必须断言那个
量本身，不能用内部状态代替。
