# 批处理「目标信号」选择器改造 · 方案 A 执行计划

- **状态**：待执行
- **日期**：2026-08-02
- **设计规格**：`docs/analyzer/specs/2026-08-02-batch-signal-picker-option-a-spec.md`
- **视觉基准**：`docs/analyzer/ui-prototypes/batch-signal-picker-options.html` → 卡片「A」
- **主改文件**：`mf4_analyzer/ui/drawers/batch/signal_picker.py`

改动面小而集中：一个组件文件 + 一个图标方法 + 一批测试 + 一个渲染工具。
`BatchSheet` / `input_panel` / preset 序列化 **均不需要改**（对外接口不变）。

---

## 第 0 步 · 取基线（动手前必做）

CLAUDE.md 记录：`main` 上 `tests/ui/` 已有一批红灯（主要是 `test_split_*`，
`canvas_time.get_visible_xlim()` 返回 `None`，offscreen 与原生平台都复现）。
**先记下失败数与用例名**，否则无法区分既有失败与本次引入的失败。

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -q 2>&1 | tail -30
```

把 `failed` 计数与用例名记进 `docs/analyzer/verify/`（或本计划末尾的「基线记录」）。
同时单独跑一次本次直接相关的三个文件，确认它们**改动前全绿**：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_batch_signal_picker.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_smoke.py -q
```

> 全量套件约 4600 条、近 20 分钟，不要在迭代过程中反复跑；收尾再跑一次全量。

---

## 第 1 步 · 新增 chevron 图标

**文件**：`mf4_analyzer/ui_kit/icons.py`

在 `Icons` 类中加两个 classmethod，走现有 `_line_icon(draw, color)` 路径
（20×20 逻辑画布、2x DPR、抗锯齿已由 `_canvas` 处理）：

```python
@classmethod
def chevron_down(cls, color=None): ...   # V 形开口向下，两笔一折
@classmethod
def chevron_up(cls, color=None): ...
```

- 描边宽度对齐现有线性图标（`_pen(color, 1.7)`），`RoundCap` / `RoundJoin` 由 `_pen` 提供。
- 默认色取 spec 4.3 的 `#7b8798`，hover 色 `#354254` 由调用方传入。
- **不要**动 `_ARROW_SPECS` / `ensure_icon_cache()` / `{{ICON_*}}` 那套——那是给
  QSS subcontrol 用的，本控件的箭头是真实 `QPushButton`，`setIcon()` 即可
  （理由见 spec 4.6）。

**验证**：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -c "
from PyQt5.QtWidgets import QApplication; app=QApplication([])
from mf4_analyzer.ui_kit.icons import Icons
for n in ('chevron_down','chevron_up'):
    ic=getattr(Icons,n)(); assert not ic.isNull(), n
    print(n, ic.availableSizes())
"
```

---

## 第 2 步 · 重建收起态为只读摘要行

**文件**：`signal_picker.py`

拆掉 `_display_frame` 里的 chips + 内联搜索，替换为：

```
_trigger (按钮语义, 38px 高)
├── _summary_label   QLabel, 等宽, ElideMiddle
├── _overflow_label  QLabel, "+N" 徽章（保留属性名）
└── _arrow_button    QPushButton, setIcon(chevron)
```

要点：

- `_trigger` 需可键盘聚焦（`Qt.StrongFocus`）并响应 `Space`/`Enter` 展开。
  沿用 `_ClickableFrame` + 手动键盘处理，或换 `QPushButton` 承载子布局——
  两条路都可以，**保留 `_display_frame` 作为指向 `_trigger` 的别名属性**，
  可让 `test_picker_display_clicking_empty_area_opens_popup` 等测试少改。
- 摘要文本按 spec 3.4 的三档规则渲染；`ElideMiddle` 的宽度预算在
  `resizeEvent` 里重算（沿用现有 `resizeEvent` → `_refresh_display` 的结构）。
- 触发器 `toolTip` = 全部已选名，每行一个。
- 样式按 spec 4.1/4.2，静止 `#eef2f7`、hover `#e8edf4`、展开·聚焦 `#fff` + 蓝边。
  聚焦外发光在 QSS 不可用，**改为边框 1px→2px 并把内边距补 1px**，避免控件跳动。
- 删除 `_chip_host` / `_chip_layout` / `_clear_chips()` / `_on_chip_remove_requested()`。

**本步的自检**：`sizeHint()` 仍返回 `QSize(220, 38)`，且与已选数无关
（`test_batch_smoke.py` 的核心契约）。

---

## 第 3 步 · 把搜索搬进弹层 + 底部操作条

**文件**：`signal_picker.py`

弹层结构：

```
_popup (QFrame, Qt.Popup, 最小宽 420)
├── _search        QLineEdit  ← 从 _display_frame 移入
├── _list          QListWidget
└── _foot          已选 N · 匹配 M ｜ 全选 M 条 · 清空
```

要点：

- **删除 `_search_hint`**（「直接在上方原通道框输入」）——症状 05。
- `show_popup()` 里在弹层显示后 `_search.setFocus()`，并 `selectAll()`。
  这是方案 A 成立的前提（spec 3.1），**不可省略**。
- `hide_popup()` 里清空搜索词（spec 3.2）。
- 删除 `eventFilter` 中把弹层按键转发进 `_search` 的分支
  （现 `signal_picker.py:509-518` 的 `Key_Backspace` / `event.text().isprintable()`），
  搜索框自己就有焦点了。**保留** `Key_Escape` 分支与 `FocusOut` 关闭逻辑。
- 弹层宽度 `max(420, 触发器宽)`，并对屏幕右缘做钳制（等价于原型的 `clampPop`）。
- 列表最大高度按可用屏幕空间算、下限 96px（等价于原型的 `fitList`），
  **不要写死像素**。
- 底部条按 spec 3.3：`全选` 只并入**可选**项（跳过 `selectable=False` 的 partial）；
  单选模式隐藏 `全选`。

**风险点**：`_popup` 的圆角外壳（`apply_popup_shell` + `WA_TranslucentBackground`
+ `WA_StyledBackground` + `NoFrame`）**不得改动**，
`test_picker_popup_rounded_corners_have_no_square_frame` 守着这条。往弹层里加
子控件时注意 CLAUDE.md 的踩坑记录：`WA_TranslucentBackground` 会让本体 QSS 失效，
新加的搜索框/底部条若背景不显示，需靠内部子 widget 兜底而非改外壳属性。

---

## 第 4 步 · 删除 `SignalChip`

按 spec 5.3，连同引用一并删除：

| 位置 | 动作 |
| --- | --- |
| `signal_picker.py` | 删 `SignalChip` 类 |
| `tests/ui/test_batch_signal_picker.py:104` | 删 `test_signal_chip_emits_remove_signal` |
| `tests/ui/test_batch_signal_picker.py:115` | 删 `test_signal_chip_label_truncates_long_name` |
| `tools/render_batch_input_output_polish.py:36-37` | 去掉 `SignalChip` 导入 |
| `tools/render_batch_input_output_polish.py::_save_picker_proofs` | 改用新结构（见第 6 步） |

**先全仓搜一遍确认没有遗漏**：

```bash
grep -rn "SignalChip\|_chip_host\|_chip_layout" --include="*.py" .
```

---

## 第 5 步 · 更新与新增测试

**文件**：`tests/ui/test_batch_signal_picker.py`

按 spec 6.1 逐条改写（反转 2 条、重写 3 条、删除 3 条、更新引用 1 条），
按 spec 6.3 新增 8 条。新增测试与症状一一对应，其中这三条是核心回归：

- `test_picker_trigger_geometry_is_stable_across_search` —— **症状 04 的守门测试**。
  记录 `_summary_label` / `_overflow_label` / `_arrow_button` 的 `geometry()`，
  `set_search_text("xxx")` 后再取，逐一相等。原型实测现状会位移 339px，
  改造后必须为 0。
- `test_picker_arrow_uses_drawn_icon_not_text_glyph` —— 症状 01。
- `test_picker_popup_is_at_least_420_wide` —— 症状 05。

**跑**：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_batch_signal_picker.py -q
```

随后确认 spec 6.2 列出的「预期原样通过」那批**确实没动就绿**，特别是
`tests/ui/test_batch_smoke.py:197` 的 `_overflow_label.text() == "+3"`
（预期数值巧合一致；若不一致，按 spec 6.1 的口径改这一条并在计划里记录）。

---

## 第 6 步 · 更新渲染证据工具

**文件**：`tools/render_batch_input_output_polish.py::_save_picker_proofs`

现引用 `SignalChip` / `_chip_host` / `_search` / `_arrow_button` 做越界断言。
改为对新结构断言：`_summary_label` / `_overflow_label` / `_arrow_button` 均不越出
`_trigger` 右边界，`picker.height() == 38`，`_overflow_label.text() == "+19"`。

顺带产出改造后的收起态与展开态 PNG，供第 7 步对标使用。

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python tools/render_batch_input_output_polish.py
```

> 这一步的产物是**排版草稿**，不是视觉验收依据（CLAUDE.md：offscreen 只能当草稿）。

---

## 第 7 步 · 与 HTML 原型对标（视觉验收）

**必须在 macOS 原生平台跑真实 GUI**，不能用 offscreen 交差。

1. 启动应用，打开批处理抽屉，加载一个含长通道名的来源（EPS 数据即可）。

   ```bash
   .venv/bin/python "MF4 Data Analyzer V1.py"
   ```

2. 截三张图：**空态**、**选中 1 个**、**选中 4 个且弹层展开**。
3. 打开原型页对应卡片 A，同样三态截图。
4. 按下表逐项核对；每项记「一致 / 有差异（附数值）」：

| # | 对标项 | 判据 |
| --- | --- | --- |
| 1 | 控件高度 | 38px |
| 2 | 圆角 | 触发器 7px、弹层 9px |
| 3 | 静止底色 | 触发器明显浅于白、深于面板底（`#eef2f7`） |
| 4 | 三态可辨 | 静止 / hover / 展开 三种背景肉眼可区分 |
| 5 | 箭头 | 线条 chevron，无蓝色实底方块，展开时翻转 |
| 6 | 摘要省略 | **中间省略**，头尾片段同时可见（`Rte_ActRetPlausi_m…MotorTorque_xds16`） |
| 7 | 徽章 | `+N` 淡蓝底，位于摘要与箭头之间 |
| 8 | 无输入光标 | 收起态点击不出现文本光标 |
| 9 | 弹层宽度 | ≥ 420px，且宽于触发器时不超出屏幕 |
| 10 | 自动聚焦 | 点开后直接打字即可筛选，无需二次点击 |
| 11 | 搜索零位移 | 输入再删除关键字，**弹层内搜索框与收起态摘要均不移动** |
| 12 | 底部条 | `已选 N · 匹配 M` ｜ `全选 M 条` · `清空`，禁用态置灰 |
| 13 | 无提示语 | 弹层内不再有「直接在上方原通道框输入」 |
| 14 | 列表长名 | 46 字符信号名在 420px 宽下完整可读 |
| 15 | 圆角无方框 | 弹层四角外无残留方形边框（回归 `apply_popup_shell`） |

5. 把三张真机截图与核对表存入 `docs/analyzer/verify/`，并在本计划末尾登记结论。

**第 11 项是本次改造的核心验收点**——它是用户最初报告的症状。

---

## 第 8 步 · 收尾

1. RPM 行（`single_select=True`）单独走一遍：单选替换、无「全选」、
   选中后摘要正确。
2. 全量套件与第 0 步基线比对：

   ```bash
   TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest 2>&1 | tail -30
   ```

   **判据**：失败集合 ⊆ 基线失败集合（不新增）。
3. 交互有增删改 → 按 CLAUDE.md 跑项目内命令 `/update-hints`，同步
   `ui/hints.py` 与 `ui/quickref.py`。本次收起态由「可输入」变「只读」、
   新增「全选/清空」，**属于需要同步的交互变更**。
4. 版本号若需更新，只改 `mf4_analyzer/app_meta.py::APP_VERSION`，别处不硬编码。

---

## 风险与回滚

| 风险 | 应对 |
| --- | --- |
| 弹层加子控件后背景不显示（`WA_TranslucentBackground` 让本体 QSS 失效） | CLAUDE.md 已记录：靠内部子 widget 或 `paintEvent` 兜底，**不要**改外壳属性，否则圆角回归测试会红 |
| `_trigger` 键盘可达性回退 | 第 5 步新增测试覆盖 `Space`/`Enter` 展开 |
| `test_batch_smoke.py` 的 `+3` 断言未如预期巧合一致 | 按 spec 6.1 口径改这一条，并在本计划登记 |
| 真机与 offscreen 渲染不一致 | 视觉验收只认第 7 步的真机截图 |

**回滚**：改动集中在 `signal_picker.py` 一个文件 + `icons.py` 的两个新增方法，
`git revert` 单个提交即可完全回退；对外接口未变，不会波及 preset 与 `BatchSheet`。

---

## 基线记录（第 0 步产出）

```
日期：2026-08-02
命令：TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -q
tests/ui 结果：60 failed, 2682 passed, 1 deselected（635s）
三个直接相关文件（test_batch_signal_picker / test_batch_input_panel /
test_batch_smoke）：105 passed，改动前全绿
```

失败用例名（60 条，全部为 main 上既有红灯）：

| 文件 | 条数 | 用例 |
| --- | --- | --- |
| `test_split_per_pane_controls.py` | 24 | 全部 |
| `test_split_focus_routing.py` | 18 | 全部 |
| `test_split_routing.py` | 6 | `test_directional_merge_only_host_splits`、`test_split_render_does_not_pollute_active_view_ui`、`test_split_render_preserves_active_cursor_pill`、`test_secondary_pane_keeps_its_own_plot_mode_across_switches`、`test_split_none_exits`、`test_switch_to_cursor_off_view_clears_pill` |
| `test_channel_widget_setters.py` | 3 | `test_file_navigator_delegates_channel_state`、`test_set_checked_channels_roundtrip`、`test_set_hidden_channels_keeps_only_checked_known_channels` |
| `test_head_hdf_rail.py` | 3 | `test_channel_tree_check_raster_selects_all_channels`、`test_flat_get_checked_channels_works`、`test_get_checked_channels_returns_fid_ch_color` |
| `test_main_window_smoke.py` | 2 | `test_entering_fft_mode_resolves_auto_db_reference_for_checked_channel`、`test_fft_checked_channel_change_refreshes_auto_db_reference` |
| `test_pg_dense_raster.py` | 2 | `test_dense_raster_is_transform_only_until_100ms_settle`、`test_dense_raster_visibility_color_and_revision_invalidate` |
| `test_chart_stack.py` | 1 | `test_time_toolbar_has_no_loc_label_to_jostle_right_controls` |
| `test_db_reference_controls.py` | 1 | `test_dialog_layout_insets_toggle_content_and_bounds_compact_columns` |
| `test_hints.py` | 1 | `test_axis_group_menu_open_retires_coaxis_merge_discovery` |

## 改动后比对（第 8 步产出）

```
命令：TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q
全量结果：62 failed, 4591 passed, 9 skipped, 3 deselected（753s）
tests/ui 失败集合 == 第 0 步基线的 60 条，逐条相同（无新增、无消失）
另外 2 条在 tests/ui 之外：
  tests/acquisition_ui/test_review_handoff.py::test_analyzer_load_file_delegates_to_load_one
  tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence
  —— 已在干净 checkout 上单独复跑确认同样失败，属 main 既有红灯
三个直接相关文件：113 passed（基线 105 + 本次新增 8 条）
```

## 验收记录（第 7 步产出）

**部分执行。** 用户在真机上验收，报告了四个 offscreen 未能发现的问题，
全部已修（`b48c943`、`bf4a5f9`），随后确认弹层背景已不透明。

| 项 | 结论 |
| --- | --- |
| 弹层背景不透明 | ✅ **用户真机确认**。这是唯一无法用 offscreen 验证的一项——`grab()` 会把透明区域合成掉，正是它当初漏掉这个 bug 的原因 |
| 其余 14 项 | 未逐项核对 |

真机验收暴露、offscreen 全绿却看不出的四个问题：

1. 弹层背景透明，列表区透出后面的面板 —— `apply_popup_shell` 的
   `WA_TranslucentBackground` 让外壳自身 QSS 背景失效（CLAUDE.md 已记载此坑），
   改由内部 `_surface` 承载白底与圆角
2. 弹层高度吃掉大半屏（25 条通道要 554px）—— 加 `_LIST_MAX_ROWS = 9`
3. 弹出方向时上时下 —— 与 2 同源：高度随筛选变化，翻转判据跟着变。
   改为每次打开测量一次并锁定
4. 行距过宽 —— 列表项垂直 padding 5px → 2px

随后 offscreen 排版复核又发现最后一行被底部条切掉半行（长通道名触发横向
滚动条，吃掉 viewport 底部），改为关闭横向滚动 + 列表项中间省略。

**教训**：几何数值（高度、位置、整除关系）offscreen 可信；
**颜色与合成**（透明、叠加、阴影）offscreen 不可信，必须真机。
本次四个问题里有三个是几何、一个是合成，而恰恰是合成那个最严重。
