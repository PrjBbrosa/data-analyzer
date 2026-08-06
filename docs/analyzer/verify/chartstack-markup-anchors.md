# 包 D 锚点核验与纯度审计

- 日期：2026-08-06
- 分支：`refactor/chartstack-markup-slimming`，起点 `main` @ `ab19622f`
- 设计：[2026-08-04-chartstack-markup-slimming-design.md](../specs/2026-08-04-chartstack-markup-slimming-design.md)

## 1. 锚点核验（spec 基线 `e385ce5a` → 当前 `ab19622f`）

spec 行号以 `e385ce5a` 为准。包 A/B/E 合入后**两个主战场文件均未被触碰**，
行号逐条复核**全部一致**：

| 文件 | 符号 | spec 行号 | 实测行号 | 结论 |
|---|---|---|---|---|
| stack.py | `_format_cursor_info_for_pill` | 1089 | 1089 | ✅ |
| stack.py | `_format_single_cursor_variants_for_pill` | 1100 | 1100 | ✅ |
| stack.py | `_mini_single_cursor_part` | 1131 | 1131 | ✅ |
| stack.py | `_plain_single_cursor_tooltip_line` | 1152 | 1152 | ✅ |
| stack.py | `_single_cursor_channel_color` | 1164 | 1164 | ✅ |
| stack.py | `_strip_html` | 1183 | 1183 | ✅ |
| stack.py | `_reposition_pill` / `_reposition_one_pill` | 1212 / 1234 | 1212 / 1234 | ✅ |
| stack.py | `cursor_pill_snapshot` / `restore_cursor_pill_snapshot` | 1268 / 1287 | 1268 / 1287 | ✅ |
| editor.py | `_build_toolbar` | 394 | 394 | ✅ |
| editor.py | `_build_style_panel` | 701 | 701 | ✅ |
| editor.py | 手柄几何带 | 901-1096 | 901-1096 | ✅ |
| editor.py | `_serialize_item` / `_deserialize_item` | 1163 / 1212 | 1163 / 1212 | ✅ |
| editor.py | 图标生成 | 1282-1324 | 1282-1324 | ✅ |
| editor.py | `keyPressEvent`（不动） | 1325 | 1325 | ✅ |

文件规模：`stack.py` 1306 行 · `editor.py` 1416 行 · `cursor_pill.py` 341 行。

## 2. `cursor_pill.py` 现有内容（并入前的命名占用）

- 常量：`_CURSOR_PILL_RADIUS` `_CURSOR_PILL_BG` `_CURSOR_PILL_BORDER`
  `_TOGGLE_EDGE_GAP` `_TOGGLE_FIRST_LINE_RESERVE` `_CURSOR_HTML_SEP`
- 类：`CursorPill`（widget，含 `snapshot` / `restore_snapshot` / `_refresh_detail`）、
  `_QualityStatusIndicator`
- 导入：`._helpers._format_mini_html`；`..plot_helpers._format_dual_html`（函数内延迟导入）

**无命名冲突**：待并入的六个格式化函数名与四个正则常量在本模块均未占用。

## 3. 纯度审计（六个格式化方法逐个 grep 方法体的 `self.`）

| 方法 | `self.` 依赖 | 传递依赖（模块级/类级名字） | 分类 | 搬迁方案 |
|---|---|---|---|---|
| `_format_cursor_info_for_pill(text, mode=None)` | `self.cursor_mode()`（**活状态读取**）、`self._format_single_cursor_variants_for_pill` | `_CURSOR_HTML_SEP` | **不纯**（默认值要查实例状态） | 模块函数签名改为**必填** `mode`；`cursor_mode()` 缺省解析留在 `ChartStack` 薄委托里 |
| `_format_single_cursor_variants_for_pill(text)` | 仅同组两个兄弟方法 | `_CURSOR_HTML_SEP` | 纯 | 直接模块函数 |
| `_mini_single_cursor_part(part, top_pad)` | `_single_cursor_channel_color`、`_strip_html`（兄弟）、`self._BOLD_VALUE_RE`（类常量） | `escape`（html）、`_BOLD_VALUE_RE` | 纯 | 直接模块函数；常量升为模块级 |
| `_plain_single_cursor_tooltip_line(part)` | `_strip_html`（兄弟） | `re` | 纯 | 直接模块函数 |
| `_single_cursor_channel_color(part)` | `self._COLOR_RE`、`self._BOLD_VALUE_RE`、`self._CURSOR_PREFIX_COLORS`（均类常量） | 同左三个常量 | 纯 | 直接模块函数；常量升为模块级 |
| `_strip_html(value)` | `self._TAG_RE`（类常量） | `unescape`（html）、`_TAG_RE` | 纯 | 直接模块函数；常量升为模块级 |

**结论：六个方法里五个纯，一个（`_format_cursor_info_for_pill`）仅在「默认参数解析」
一处不纯**，把 `mode` 提为显式参数即可，其余逻辑不含状态读取。没有一处需要
通道颜色查询（spec 对 `_single_cursor_channel_color` 的预判偏保守：它只从
HTML 文本里正则提取颜色，不查实例）。

### 3.1 传递依赖清单（一并搬迁）

grep 生成的移动清单看不见传递依赖，故逐条列出方法体引用的模块级/类级名字：

- `ChartStack._COLOR_RE` = `re.compile(r'color:\s*([^;"\']+)')`（stack.py:36）
- `ChartStack._BOLD_VALUE_RE` = `re.compile(r'<b[^>]*>(.*?)</b>', re.S)`（stack.py:37）
- `ChartStack._TAG_RE` = `re.compile(r'<[^>]+>')`（stack.py:38）
- `ChartStack._CURSOR_PREFIX_COLORS` = `{"#64748b"}`（stack.py:39）
- 模块导入 `import re` / `from html import escape` / `from html import unescape`
  （stack.py:2-4）

**实测：这三个导入在 stack.py 里除 pill 格式化区外零使用**
（`grep -n "\bre\.\|escape("` 命中行全部落在 :36-38 与 :1141/:1154/:1158/:1160/:1184），
搬走后三行 import 一并删除——与 spec「文件头 import 是明确信号」的判断一致。

### 3.2 monkeypatch 风险审计（「再导出复制绑定不复制作用域」）

包 A 踩过的坑：方法体读的模块级名字若被测试 monkeypatch，搬家会让 patch 失效。
逐个核查四个常量与三个导入：

- `grep -rn "_BOLD_VALUE_RE\|_COLOR_RE\|_CURSOR_PREFIX_COLORS\|_TAG_RE" mf4_analyzer/ tests/ scripts/ tools/`
  → **命中全部在 `stack.py` 内部**，仓库无外部引用、无 monkeypatch。
- `tests/ui/test_chart_stack.py` 的 13 处 `monkeypatch.setattr` 无一指向 stack 模块全局
  或 `escape` / `unescape` / `re`（目标是 `QMenu.popup`、`QPainter.drawPixmap`、
  `cs._grab_pill_scaled`、`toolbar_mod.QMessageBox`、`hints.rotation_hints` 等）。

**结论：无 monkeypatch 冲突，可以直接搬。**

## 4. 测试语料（Task 1 复用）

`tests/ui/test_chart_stack.py` 既有 pill 用例与真实 EPS 语料：

- `:227 test_single_cursor_pill_uses_vertical_channel_readout` — 单游标三段，
  含 `[tiadodamping] Rte_=<b>424.2</b>`
- `:256 test_single_cursor_pill_builds_mini_value_only_detail` — 带 `[taiyaok]` 前缀色段
  （`#64748b`）+ `Rte_ESChkPlausi_mESMotorTorque_xds16=<b>0 Nm</b>`，
  校验 mini 只留值、tooltip 留 `name=value`
- `:291 test_single_cursor_pill_mini_detail_reescapes_html_entities` — `1 &lt;A&gt;&amp;` 转义往返
- `:313 test_single_cursor_pill_toggle_shows_value_only_mini_detail` — toggle 后 mini
- `:588 test_cursor_pill_snapshot_restore_preserves_single_mini_variants`
- `:1473 test_cursor_pill_formats_single_cursor_details_for_mode` — `_format_cursor_info_for_pill` 直调

注意：多处用例直接调用 `cs._strip_html(...)` / `cs._format_single_cursor_variants_for_pill(...)`,
**薄委托必须保留同名同签名**。

## 5. 基线

命令（Task 0 Step 5，在当前 `main` @ `ab19622f` 上重采）：

```
PYTEST tests/ui/test_chart_stack.py tests/ui/test_markup_editor.py \
       tests/ui/test_copy_thumbnail.py tests/ui/test_chart_stack_stats_visibility.py -q
```

结果：**189 passed，0 failed**（存 `chartstack-markup-baseline.txt`）。
本包四个目标文件的基线全绿——CLAUDE.md 记录的两条既有红
（`test_batch_runner_thread.py` / `test_hint_nudges.py`）不在本集合内。

真机基线截图：本次执行按编排要求**跳过**（不启动 GUI，不用 offscreen 冒充视觉验收）；
改由 orchestrator 做两侧自动化渲染对比，可视面清单见下节。

## 6. 收尾结果（2026-08-06）

### 6.1 任务完成情况

| 任务 | 状态 | 说明 |
|---|---|---|
| Task 0 | ✅ | 锚点全对，基线 189 passed |
| D1 pill 格式化 | ✅ | 六个函数并入 `cursor_pill.py` |
| D2 pill 定位控制器 | ⏭️ **跳过** | 见 6.2 |
| D3 序列化 | ✅ | `markup/serialization.py` |
| D4 工具栏 | ✅（部分） | 图标生成留在 editor，见 6.3 |
| D5 手柄几何 | ✅ | `markup/handles.py` |

### 6.2 D2 跳过理由（闸门开着，但收益不成立）

D1 全绿，闸门形式上满足。跳过是基于耦合实测：

- `CursorPillController` 需要的状态里，`_secondary_card` 在 stack.py 有 **76 处**引用、
  `_time_card` **41 处**；两者由分屏逻辑（`enter_split` / `exit_split`，:605/:639）
  创建销毁，`_pill_secondary` 本身也在分屏入口里 new 出来。
- 控制器拿不到这些状态的所有权，只能持 ChartStack 反向引用逐个 `self._stack.<x>` 转发
  ——那是**位移，不是接缝**：多一层间接，分屏与 pill 的交互反而更难读。
- 且计划为 D2 规定的验证手段是真机核对 pill 随缩放/分屏/切 View 的位置行为，本次执行
  按编排要求跳过真机，offscreen 替代不了（CLAUDE.md 首条 Gotcha）。

计划原文允许「闸门不满足就跳过，不算失败」；此处是闸门满足但收益不成立，同样停在 D1。

### 6.3 D4 偏离：图标生成未移出

spec D-D4 列了「图标生成(:1282-1324)」一并移入 `toolbar.py`。**实测不能移**：

`tests/ui/test_color_swatch_hidpi.py:57-66` 用
`monkeypatch.setattr(editor_mod, "icon_device_pixel_ratio", lambda: 2.0)`
伪造 2x 屏，再调 `MarkupEditor._icon_canvas`。`_icon_canvas` 从 **editor 模块的全局**
解析这个名字；把画图函数搬到 `toolbar.py` 后，它读的是 toolbar 的全局，
patch 落空 → 该用例实测转红（`assert (18,18) == (36,36)`）。

这正是「再导出复制绑定不复制作用域」。按纪律**不改既有测试去迁就重构**，
四个画图函数留在 `MarkupEditor`，`build_style_panel` 回调 `editor._color_icon` /
`editor._width_icon`。两侧都留了注释说明原因，防止后人「顺手补完」。

代价：editor.py 少减约 43 行（见 6.4）。

### 6.4 行数与方法数

| 文件 | 前 | 后 | 差 |
|---|---|---|---|
| `chart_stack/stack.py` | 1306 | 1233 | −73 |
| `chart_stack/cursor_pill.py` | 341 | 486 | +145 |
| `markup/editor.py` | 1416 | 1014 | **−402** |
| `markup/serialization.py` | — | 176 | 新增 |
| `markup/toolbar.py` | — | 320 | 新增 |
| `markup/handles.py` | — | 136 | 新增 |

- spec 验收 #2 要求 editor.py（D3+D4）减 ≥350：D3+D4 合计 **−335**，
  差在 6.3 留下的图标块；把 D5 计入后总减 **−402**。
- spec 验收 #2 还要求「ChartStack 方法数下降」：**未达成，仍是 83**。
  与同一份 spec「`ChartStack` 的方法名与签名全部保留（薄委托），外部与测试零改动」
  直接冲突——保留薄委托就必然保留方法数。按后者执行（测试确实直接调
  `cs._strip_html` 等）。该条的真实意图「格式化逻辑不在 stack.py」已达成。
  `MarkupEditor` 同理仍是 85。

### 6.5 失败集对比（Task 0 Step 5 同一命令）

**189 passed，0 failed —— 与基线逐条一致，差异为空。**

全量套件（`--ignore=tests/acquisition_ui`，见下）两侧同为 **5 failed / 4974 passed**，
失败集完全相同：

1. `tests/ui/test_batch_runner_thread.py::test_sheet_preview_and_result_share_channel_metadata_reference`（CLAUDE.md 已记）
2. `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_and_custom_action`（CLAUDE.md 已记）
3. `tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence`
4. `tests/test_batch_renderer.py::test_facade_exports_only_supported_qt_renderer_contract`
5. `tests/test_gen_help_screenshots.py::test_import_screenshot_uses_real_checked_in_samples`

**3-5 是既有红但 CLAUDE.md 未记**（在 `ab19622f` 上逐条复现）。

另：全量套件在 `tests/acquisition_ui/` 段 **段错误崩溃**（pyqtgraph `LabelItem.resizeEvent`
访问已析构的 `QGraphicsTextItem`），`ab19622f` 上同点同样崩溃——既有问题，与本包无关，
故全量对比一律加 `--ignore=tests/acquisition_ui`。

### 6.6 改动触碰的可视面（供 orchestrator 扩充自动化对比场景）

真机验收本次跳过，以下是本包改动可能影响的渲染面：

**A. 游标 pill（D1）** — 格式化输出逐字未改，但整条 HTML 生成路径换了实现位置：
1. 时域单游标 · 单通道：primary 行 `t=…s` + 一行明细
2. 时域单游标 · 多通道：明细表首行无 top padding、后续行 2px
3. mini 模式（点 pill 右上角 `−`/`+`）：只剩色点 + 数值，等宽字体，通道名进 tooltip
4. 色点取通道色而非 `[文件名]` 前缀的灰 `#64748b`
5. 含 HTML 实体的通道值（`&lt;` 等）在 mini 里保持转义、tooltip 里还原
6. 双游标：整串原样进 primary，不拆表
7. pill 定位/拖拽/快照 —— **代码未动**（D2 跳过），可作对照组

**B. 标注编辑器工具栏（D4）** — 构造代码整体搬家，按钮清单与接线由特征测试锁定：
1. 工具栏三段：左 关闭 / 中 样式+8 工具+撤销+重做 / 右 保存+完成复制
2. 8 个工具按钮 44×44、选中态蓝底白字形
3. 样式弹窗：6 色 + 4 线宽，圆角面板 + 透明菜单外壳（macOS 方角回归的高危面）
4. 样式按钮上的复合图标（色点 + 线宽横线）
5. hi-DPI 下图标清晰度 —— 画图函数**未移动**（见 6.3）

**C. 标注序列化（D3）** — 无直接视觉面，行为面是**编辑器内复制/粘贴**：
1. 六种图元各自 复制 → 粘贴，偏移 (12,12)，几何与样式还原
2. 序号徽标的圆/标签/缩放还原
3. 粘贴后编辑器当前颜色/线宽不被 payload 污染

**D. 手柄几何（D5）**：
1. 拖矩形四角/四边中点改尺寸；拖过对边翻转而非负宽
2. 裁剪框八手柄
3. 文字/画笔路径左上角锚定缩放；序号徽标中心锚定缩放
4. 缩放下限 0.25（拖到锚点上不会缩没）
5. 缩放视图下手柄命中半径（14px 屏幕空间）
