# 五个 UI 问题诊断报告（仅诊断，不含修复）

- 日期：2026-06-01
- 分支：`plan/pyqtgraph-timedomain-migration`
- 范围：复制图片编辑器、时域纵轴、双 cursor、复制内容、下拉菜单圆角
- 结论速览：5 个现象 **4 个是真实 bug**（#1/#2/#4/#5），**#3 是尚未实现的功能**（不是 bug）。
  另发现一个贯穿性根因：**`chart_stack.py` / `main_window.py` / `editor.py` 在本分支上被结构性污染（同名方法重复定义、最后一个生效、部分缩进错位/空桩）**，它直接造成了 #1 与 #4。

---

## 速览表

| # | 现象 | 真实? | 涉及文件（状态） | 根因一句话 |
|---|------|------|------------------|-----------|
| 1 | 图片编辑器：拖动窗口大小，图片不等比自适应 | ✅ 是 | `markup/editor.py`（局部污染） | `showEvent`/`resizeEvent` 缩进错位成局部函数，没覆盖 Qt，resize 永不触发 `fit_to_window` |
| 2 | 时域纵轴显示 ×100 / ×1e4 倍率 | ✅ 是（subplot/single） | `ui/pg_canvases.py`（干净） | pyqtgraph 默认 `enableAutoSIPrefix=True`，只有 overlay 模式被禁用 |
| 3 | 双 cursor 区域内最大/最小红绿点高亮 | ⚪ 未实现（非 bug） | `ui/pg_canvases.py`（干净） | 功能没做；可加，基本不卡 |
| 4 | 复制图片不含 cursor 统计文本 | ✅ 是 | `ui/chart_stack.py`（严重污染） | 复制/抓图触发链的"生效定义"被污染断开，带 pill 合成的复制路径没被走到 |
| 5 | 颜色/线宽下拉菜单圆角背后露方形 | ✅ 是 | `markup/editor.py` + `ui_kit/style.qss` | QMenu 缺 `Qt.WA_TranslucentBackground`，矩形底色从圆角外露出 |
| ★ | 三个 UI 文件结构性污染 | ✅ 是 | `chart_stack.py`/`main_window.py`/`editor.py` | 同名方法被反复追加、Python 取最后一个；本分支引入（main 基本干净） |

---

## ★ 贯穿性根因：UI 文件结构性污染

证据（行数 / 重复定义统计，均为脚本统计后单值读出，可信）：

| 文件 | 本分支行数 | main 行数 | 重复定义的方法名数 | 单方法最多重复 |
|------|-----------|-----------|-------------------|---------------|
| `ui/chart_stack.py` | **8327** | 2557 | **130** | `__init__` × **64** |
| `ui/main_window.py` | 4416 | — | 109 | 37 |
| `markup/editor.py` | 1108 | — | 14 | 4（`showEvent`/`resizeEvent`/`__init__` 各 4） |
| `ui/pg_canvases.py` | 4030 | — | **0**（干净） | 1 |

- main 分支上 `chart_stack.py` 只有 11 个"重名"、最多 5 个——那是文件里有多个类、各自带 `__init__`/`paintEvent` 的**正常现象**。本分支 130/64 是异常污染。
- 特征：同名方法被**反复 append**（有的最后一份是空 `pass` 桩、有的缩进错成局部函数），像某个自动改写/合并工具在**追加重新生成的方法体而不是替换**。
- 影响机制：Python 解析类体时**后定义覆盖先定义**，所以"生效行为 = 最后一个定义"。当最后一个定义恰好是干净版 → 功能正常；当最后一个是空桩/被打乱版 → 功能莫名其妙坏掉。这正是 #1、#4 表现为"偶发性损坏"的来源。
- 风险：污染未清理前，直接在 `chart_stack.py` 上做定点 patch 风险高，且 #4 难保证修干净。

---

## #1 图片编辑器不随窗口等比自适应

- **现象**：复制后打开图片编辑器，进入后拖动编辑器窗口边缘改变大小，里面的图片不跟着等比缩放（不 auto-fit）。
- **是否真实**：✅ 真实存在。
- **根因**：`markup/editor.py` 中 `MarkupEditor` 的 `showEvent` / `resizeEvent` 被写在**缩进 8 格**（即嵌套在 `__init__`/某方法体内，约 L546 / L552 / L557 等），成了**局部函数**，并没有覆盖 `QWidget` 的同名虚函数。于是窗口 resize 时 Qt 调用的是默认实现，**永远不会触发 `fit_to_window`**（`self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)`）。`fit_to_window` 本身在类方法级（缩进 4）是对的，只是没人在 resize 时调它。
- **附加**：`showEvent`/`resizeEvent` 在该文件各被重复定义 ~4 次（结构性污染的局部表现）。
- **更正**：先前子 agent 把它判为"`_auto_fit` 闩锁导致的设计限制"，那是因为它默认这两个是正常类方法、没注意到缩进错位。实际更根本的是这两个方法**根本没生效**。

## #2 时域纵轴显示 ×100 / ×1e4 倍率

- **现象**：时域绘图 Y 轴自动加 SI 倍率芯片（×100、×1e4 等），不直接显示真实数值。
- **是否真实**：✅ 真实存在于 **subplot / single 模式**；overlay 模式已正确禁用。
- **根因**：pyqtgraph `AxisItem` 默认 `enableAutoSIPrefix=True`。全仓**只有一处**禁用调用：`ui/pg_canvases.py:1563` `axis.enableAutoSIPrefix(False)`，且位于 overlay-only 的 `_configure_overlay_axis_geometry()`，只在 `plot_channels()` 的 overlay 分支被调用。subplot / single 模式建的左轴**从未禁用**。
- **证据**：全仓 grep `enableAutoSIPrefix` 仅 1 个调用点（1563）；`pg_canvases.py` 文件干净（无重复定义）。
- **修复落点（仅指出）**：在建轴处（如 `_add_plot_item` 对 left/right/bottom 轴）统一 `enableAutoSIPrefix(False)`，覆盖所有模式。

## #3 双 cursor 区域内最大/最小红绿点高亮

- **现象**：希望双 cursor 触发时，在两线之间区域内，用红点标最大、绿点标最小，提示计算位置。
- **是否真实**：⚪ 这是**尚未实现的功能诉求，不是已存在的 bug**。当前代码无任何 `ScatterPlotItem` / 高亮标记。
- **卡顿评估**：**风险低**。
  - cursor 是**点击放置**（`_handle_cursor_mouse_press`）时触发统计重算，不是连续拖拽每帧重算；
  - min/max 已在 `_emit_dual_cursor_html` 内算好，再加 `argmin`/`argmax` 只是 O(n) 单次扫描；
  - 数据量受 `MAX_PTS ≈ 8000` 限制，pyqtgraph 画几颗点是毫秒级。
- **注意点**：用一个**常驻 `ScatterPlotItem` + `setData()` 更新**（别每次 add/remove）；若以后把 cursor 改成可拖拽并实时重算，给重算/重绘加节流即可。
- **落点**：`pg_canvases.py` 的 `_emit_dual_cursor_html`（干净文件）算完 min/max 后顺便取 `argmin`/`argmax` 的 `(t, value)` 并 setData。

## #4 复制图片不含 cursor 模式计算内容

- **现象**：cursor 模式下复制图片，min/max/均值/差值等统计文本没被一并复制进去。
- **是否真实**：✅ 真实存在。
- **链路**：
  1. 统计文本不画在 plot 画布内，而在独立浮层 `CursorPill`（`QFrame`，canvas 的兄弟 widget，浮在画布之上）。
  2. 复制 = `chart_stack._copy_card_image` 先 grab 画布，再**仅当 `_pill.isVisible()`** 把 pill 合成到截图上 → `image_captured` → `main_window._publish_copied_pixmap` 原样写剪贴板/喂缩略图编辑器。
  3. `main_window` 这端**干净**（200–314 行读取确认）；`_copy_card_image` 里的合成代码本身**也在**。
- **根因**：`chart_stack.py` 严重污染，导致复制/抓图链路上"生效（最后一个）定义"不可靠——探测显示**生效的 `_request_capture` 是空桩、`_capture_active_card` 的生效定义里不再调用 `_copy_card_image`**。也就是真正触发"带 pill 合成的复制"那条路被污染断开了，统计文本进不了剪贴板。
- **两处更正**：
  - 我中途怀疑"`_on_dual_cursor_info` 把 pill 关掉了"——核实后那是终端显示假象；生效的 `_on_dual_cursor_info`（L1480–L1484）是干净的，会 `setVisible(True)`，pill 本身会显示。
  - 子 agent 的"已解决"结论也要更正：它读到的是某个较早的干净副本定义，不是 Python 实际生效的最后一个定义。
- **不确定度声明**：因文件污染严重，精确"断在哪一行"会随重复定义漂移；**可靠结论是"复制链路在被污染的 `chart_stack.py` 上不可靠，根因是文件损坏"**。要 100% 锁定机制，需要先把 `chart_stack.py` 去污染。

## #5 下拉二级菜单圆角背后露方形

- **现象**：颜色/线宽弹出菜单（截图那排彩色圆点 + 线宽样例的浮层）四角，圆角外露出方形底色。
- **是否真实**：✅ 真实存在。
- **根因**：`markup/editor.py`（约 L746）创建的这个 `QMenu` 没有设 `Qt.WA_TranslucentBackground`。QSS（`ui_kit/style.qss` 约 1175–1194 行 `QMenu { … border-radius:12px; background-color:rgba(255,255,255,238); }`）给了圆角，但**没有透明背景时，widget 的矩形不透明底色会在圆角外四角露出来** → "圆角背后有方形"。
- **对照证据**：`ui/pg_canvases.py:345` 的 `pgContextMenu` 设了 `setAttribute(Qt.WA_TranslucentBackground, True)`（对应 QSS `#pgContextMenu`，约 1207–1215），所以它没有这个问题。
- **结论**：**正确做法仓库里已有，只是新菜单没套用**——与你说的"已作为 lessons learn 过、codex 没遵守"一致。

---

## 修复优先级建议（仅建议，未执行）

1. 先处理 **★ 结构性污染**（`chart_stack.py` 优先，其次 `editor.py`/`main_window.py`）：把每个方法去重收敛到正确版本、修正缩进。这是 #1、#4 能干净修复的前提。
2. #2、#5：根因清晰且在干净/可控范围，去污染后定点修。
3. #1：去污染后，把 `showEvent`/`resizeEvent` 落成真正的类方法并在 resize 时调用等比 `fit_to_window`。
4. #3：作为新功能在 `_emit_dual_cursor_html` 加常驻 ScatterPlotItem。
