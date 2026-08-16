# 时域 View 标注与双游标工程持久化

- 日期：2026-08-16
- 状态：**已落地，待 Wave 3 真机手验**
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

仅当 `cursor_mode == "dual"` 且 `ax` 为有限数字时写入；否则 `cursor_placement` 为 `null`。`bx` 可为 `null`（只放了 A）。不写 `placing`、不写单游标 x、不写 pill HTML。

恢复：先 `set_cursor_mode_for_canvas(..., "dual")`，再 `restore_placement`；`off` 仍必须清主 pill（既有 split 契约，见 `codex-cursor-pill-view-apply`）。

**D4 · 画布是投影，ViewState 是真相。**

- `AnnotationManager.snapshot_remarks() -> list[dict]`：只从**活着的** Qt 物品抽出 D2 形状；每条物品必须带复合键（见 D6）。
- `restore_remarks(payload)`：先 `clear_remarks()`，再按当前 `_channel_lines` 复合键重绑。通道不在图上 → 跳过这条（数据仍留在 ViewState）。
- `CursorController.snapshot_placement() / restore_placement(payload)` 同理。
- `canvas.clear()` 在 `_glw.clear()` **之前**调用 `clear_remarks()`，禁止悬挂已删物品。`clear()` 仍不重置 `_ax/_bx`（现注释契约）；View 切换靠 ViewState 覆盖落点。

**D5 · Capture 合并（避免隐藏通道丢标注）。**

`view_bridge.capture_controls_into`：

1. 从画布 snapshot 活标注。
2. 保留 `state.remarks` 里那些 `source` 仍属于本 View（`attached_file_ids` 或 `checked`/`hidden_channels`），且未出现在本次 snapshot 的项——覆盖「通道隐藏、轴还在/不在」时 live 列表为空的情况。
3. 用户删掉的点：活列表里没有、且该通道当前可见 → 视为已删，不从旧 state 加回。

判定「当前可见」：`source in checked` 且 `source not in hidden_channels`。

双游标：`cursor_mode=="dual"` 时 snapshot 覆盖 `cursor_placement`；切到 `off`/`single` 时写成 `None`。

**D6 · 复合键必须写进 live remark 字典。**

今天 `_add_remark` 用显示名 `ch` 找轴，物品上不存 `ck`。本批次：

- 添加时写入 `remark["source"] = (fid, channel)`（tuple，与 `ChannelKey` 一致）。
- `_nearest_data_point` 返回值带上 `ck`，不再只返回显示名。
- 恢复时 `_channel_lines.get(ck)`；禁止用显示名当身份。

**D7 · 恢复时机：画布 settle 之后。**

`_render_view_onto_canvas` 在现有事务末尾（`settle_view_restore()` 之后、离开 `_applying_view` 之前）调用 `restore_remarks` + `restore_placement`。不要在 `plot_channels` 内部偷偷读 ViewState（画布不该 import View）。

全量重建和 subplot 对象复用都走这条：复用路径若不 `clear()`，也必须先按**即将生效的** View 语义列表重绑，禁止 View A 的点留在 View B。

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

`set_cursor_mode('off')` 走 `reset_cursor_state()` 清掉 `_ax/_bx`，但
`ViewState.cursor_placement` 不动。于是 off→dual 之后画布是空的，切走再切回来
落点又冒出来——同一份数据两个真相。D4 已经定了「`clear()` 不重置 `_ax/_bx`」，
`off` 应遵循同一语义：**关闭只是不显示，不销毁用户放置的意图**。切到 `off` 仍
必须清主 pill（既有 split 契约不变）。

**D9 · 本批次明确不做。**

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
