# 批处理「目标信号」选择器改造 · 方案 A 设计规格

- **状态**：待实现
- **日期**：2026-08-02
- **组件**：`mf4_analyzer/ui/drawers/batch/signal_picker.py::SignalPickerPopup`
- **交互原型（本规格的视觉基准）**：
  `docs/analyzer/ui-prototypes/batch-signal-picker-options.html` → 卡片「A · 摘要行 + 弹层内搜索」
- **执行计划**：`docs/analyzer/plans/2026-08-02-batch-signal-picker-option-a-plan.md`

> 原型即规格。凡本文与原型冲突处，以原型的**交互行为**为准；尺寸/颜色以本文
> 第 4 节的参数表为准（表中数值已从原型 CSS 提取并标注 Qt 可移植性）。

---

## 1. 背景

当前控件把三个职责压在同一行 38px 里：已选摘要（chips + `+N`）、搜索输入
（内联 `QLineEdit`）、展开按钮。由此产生五个已确认症状：

| 编号 | 症状 | 根因位置 |
| --- | --- | --- |
| 01 | 箭头是字符 `"⌄"`/`"⌃"` 压在 26×28 蓝色实底方块上，渲染粗糙 | `signal_picker.py:177-186` |
| 02 | `#fff` 底 + 1px `#cbd5e1` 边落在浅色面板上，静止态看不出可点 | `signal_picker.py:130-134` |
| 03 | 选中后 chip / `+N` / 光标 / placeholder 四种元素抢一行，placeholder「继续搜索…」被压成两字 | `signal_picker.py:459-463` |
| 04 | 一开始搜索即 `visible_count = 0` 隐藏全部 chips，清空后恢复，输入框左边界来回位移（原型实测 339px） | `signal_picker.py:434-442` |
| 05 | 弹层需靠「直接在上方原通道框输入」一句话解释自己；弹层宽度 `max(280, 触发器宽)`，长名在列表内同样被切 | `signal_picker.py:206-212`、`:278` |

**方案 A 的核心**：把搜索职责从收起态移进弹层。收起态只做一件事——显示选了什么。

---

## 2. 范围

### 2.1 本次要做

- `SignalPickerPopup` 收起态改为**只读摘要行**（不可输入）。
- 搜索框移入弹层顶部，弹层打开时自动聚焦。
- 弹层新增底部操作条：`已选 N · 匹配 M` ｜ `全选 M 条` · `清空`。
- 箭头改用绘制图标（`Icons.chevron_down()`），去掉蓝色实底。
- 收起态底色改为比面板略深的凹陷灰，聚焦/展开时转白 + 蓝边。
- 摘要文本改用 `Qt.ElideMiddle`。
- 弹层最小宽度 280 → 420。
- 删除弹层内的 `_search_hint`（「直接在上方原通道框输入」）。
- RPM 行（`single_select=True`）同步适用。

### 2.2 本次不做

- 不改 `SignalPickerPopup` 的对外接口语义（见第 5 节契约）。
- 不改 `QComboBox` / `QSpinBox` 的既有箭头（`style.qss` 注释记录了「`QComboBox::drop-down` 保留不动」的既有约束）。
- 不实现原型里的方案 B / C。方案 C 的「在面板中选择」入口留待后续，本次不预埋按钮。
- 不改批处理的数据流、preset 序列化、`BatchSheet` 侧的任何逻辑。
- 不把 picker 的内联样式迁进 `style.qss`（保持现状的内联 `setStyleSheet`，以控制改动面）。

---

## 3. 交互契约

### 3.1 状态机

```
        ┌──────────── 收起（只读摘要） ────────────┐
        │  点击触发器任意位置 / 点击箭头 / Space·Enter
        ↓                                          │
   展开（弹层可见，搜索框已聚焦）                    │
        │  Esc · 点击弹层外 · 再次点击箭头 ─────────┘
```

- **收起态不接受文本输入**。触发器是按钮语义，不是输入框。
- **展开即聚焦搜索框**，用户点开后可直接打字，无需第二次点击。这是方案 A
  「多一个输入框」不产生额外操作成本的前提，**必须实现**。
- 勾选/取消勾选**即时生效**（沿用现状），不需要「确认」动作。
- 勾选后**弹层保持打开**，焦点**留在搜索框**，可连续勾选。
- `Esc` 关闭弹层并把焦点交还触发器。

### 3.2 搜索行为

- 搜索仅过滤弹层列表，**不影响收起态摘要的内容与几何**。这是症状 04 的验收点。
- 关闭弹层时清空搜索词（下次打开是干净的全列表）。
- 无匹配时列表区显示「无匹配信号」占位文本，底部操作条的 `全选` 置灰。

### 3.3 底部操作条

| 元素 | 文案 | 行为 | 禁用条件 |
| --- | --- | --- | --- |
| 左侧统计 | `已选 N · 匹配 M` | 只读 | — |
| 全选 | `全选 M 条` | 把当前**筛选结果**并入已选（不清除已选的其他项） | `M == 0` |
| 清空 | `清空` | 清空全部已选 | `N == 0` |

- `全选` 只对**可选**项生效：`partially_available` 且 `selectable=False` 的项跳过。
- 单选模式（RPM）下**隐藏**「全选」，只保留统计与「清空」——全选在单选下无意义。

### 3.4 摘要显示规则

| 已选数 | 摘要区 | 徽章 |
| --- | --- | --- |
| 0 | 占位符「选择信号…」（灰） | 隐藏 |
| 1 | 该信号名，`ElideMiddle` | 隐藏 |
| N ≥ 2 | 第一个信号名，`ElideMiddle` | `+{N-1}` |

- 触发器 `toolTip` 为全部已选信号名，每行一个。
- **收起态不提供逐条删除**。移除信号在弹层内取消勾选完成。这是方案 A 消除
  症状 03 的必要条件：一旦摘要区放回 `×` 按钮，就退回多职责抢一行。

### 3.5 键盘

| 按键 | 收起态 | 展开态 |
| --- | --- | --- |
| `Space` / `Enter` | 展开 | — |
| `Esc` | — | 关闭并聚焦触发器 |
| 可打印字符 | 无响应 | 由搜索框接收（焦点本就在它上面） |
| `Tab` | 移到下一控件 | 在搜索框 → 列表 → 操作条间移动 |

现状 `eventFilter` 里把弹层收到的按键转发进 `_search` 的那套 hack
（`signal_picker.py:509-518`）随搜索框进入弹层而**删除**——搜索框自己就有焦点。

---

## 4. 视觉规格

数值提取自原型 CSS。「Qt」列标注可移植性：✅ 直接可写 QSS，⚠️ 需代码实现，
❌ QSS 不支持、需替代方案。

### 4.1 收起态触发器

| 属性 | 值 | Qt | 备注 |
| --- | --- | --- | --- |
| 高度 | 38px | ✅ | 沿用 `_DISPLAY_HEIGHT`，不变 |
| 圆角 | 7px | ✅ | 不变 |
| 静止背景 | `#eef2f7` | ✅ | **变更**（原 `#fff`）→ 症状 02 |
| 静止边框 | 1px `#ccd6e2` | ✅ | 原 `#cbd5e1` |
| hover 背景 / 边框 | `#e8edf4` / `#b3c1d1` | ✅ | **新增** |
| 展开·聚焦背景 | `#fff` | ✅ | 与静止态形成明确状态差 |
| 展开·聚焦边框 | 1px `#1769e0` | ✅ | |
| 聚焦外发光 | `0 0 0 3px rgba(23,105,224,.13)` | ❌ | **QSS 无 `box-shadow`**。替代：聚焦时边框加粗到 2px 并把内边距补 1px 以免控件跳动。**不要**用 `QGraphicsDropShadowEffect`（它会让子控件走软件合成路径，在本项目的浮层里已有前科） |
| 内边距 | 左 8px · 右 4px | ✅ | `setContentsMargins(8, 0, 4, 0)` |
| 子元素间距 | 6px | ✅ | |

### 4.2 摘要文本与徽章

| 属性 | 值 | Qt | 备注 |
| --- | --- | --- | --- |
| 摘要字体 | 等宽 **12px** | ✅ | `font-family:"SF Mono","Menlo",monospace`——与同目录 `pipeline_strip.py:46` 及 `style.qss` 既有三处一致。信号名是代码标识符，等宽能让 `_xds16`/`_gdf32` 后缀对齐。**必须用整数 px**：原型的 `11.5px` 在 Qt 里会被整条丢弃（实测 `font-size:11.5px` → `pointSize=12, pixelSize=-1`，即回落默认 12pt 而非 12px）；`11.5pt` 虽能解析，但在 Windows 96dpi 下会变成 15.3px |
| 摘要颜色 | `#172033` | ✅ | |
| 摘要省略 | 中间省略 | ⚠️ | `QFontMetrics.elidedText(name, Qt.ElideMiddle, budget)`，在 `resizeEvent` 里重算 |
| 占位符文案 / 色 | 「选择信号…」/ `#98a3b1` | ✅ | |
| 徽章文案 | `+{N-1}` | ⚠️ | |
| 徽章 背景/边/字 | `#eef4ff` / `#d4e3f8` / `#234d78` | ✅ | 沿用现 `_overflow_label` 配色 |
| 徽章 圆角 / 内边距 | 6px / 3px 7px | ✅ | |

### 4.3 箭头

| 属性 | 值 | Qt | 备注 |
| --- | --- | --- | --- |
| 尺寸 | 26×28 | ✅ | 不变 |
| 字形 | chevron（线条 V 形） | ⚠️ | **新增 `Icons.chevron_down()`**，见 4.6 |
| 静止背景 | `transparent` | ✅ | **变更**（原 `#eef4ff` 实底）→ 症状 01 |
| hover 背景 | `#eef2f7` | ✅ | |
| 颜色 静止 / hover | `#7b8798` / `#354254` | ⚠️ | 两个颜色 → 两个 QIcon，在 `enterEvent`/`leaveEvent` 切换；或用 `QIcon` 的 `Active` 模式 |
| 展开态 | 图标翻转 180° | ⚠️ | 提供 `Icons.chevron_up()`，或对同一 pixmap 做 `transformed(QTransform().rotate(180))` |
| 圆角 | 6px | ✅ | |

### 4.4 弹层

| 属性 | 值 | Qt | 备注 |
| --- | --- | --- | --- |
| 最小宽度 | 420px | ✅ | **变更**（原 280）→ 症状 05 |
| 实际宽度 | `max(420, 触发器宽)` | ✅ | |
| 屏幕边缘 | 空间不足时向左对齐，不得溢出屏幕 | ⚠️ | `Qt.Popup` 有部分自动行为，仍需显式钳制（原型 `clampPop` 的等价逻辑） |
| 圆角 / 边框 | 9px / 1px `#cbd5e1` | ✅ | 原 8px |
| 内边距 | 6px | ✅ | |
| 列表最大高度 | 按可用屏幕空间计算，下限 96px | ⚠️ | 原型 `fitList` 的等价逻辑；不要写死像素 |
| 圆角外壳 | 保持 `apply_popup_shell` + `WA_TranslucentBackground` + `WA_StyledBackground` | ✅ | **不得改动**，`test_picker_popup_rounded_corners_have_no_square_frame` 守着这条 |

### 4.5 弹层内搜索框与列表

| 元素 | 属性 | 值 | Qt |
| --- | --- | --- | --- |
| 搜索框 | 高 / 圆角 | 32px / 7px | ✅ |
| | 外边距 | 上下 8/6，左右 8 | ✅ |
| | 背景 静止 / 聚焦 | `#f7f9fc` / `#fff` | ✅ |
| | 边框 静止 / 聚焦 | `#d3dbe5` / `#1769e0` | ✅ |
| | 占位符 | 「搜索信号…」 | ✅ |
| | 放大镜图标 | 左侧 13px，`#8b95a3` | ⚠️ 可选，`QLineEdit.addAction` |
| 列表项 | 内边距 / 圆角 | 5px 7px / 5px | ✅ |
| | 字体 | 等宽 **12px**（整数 px，理由同 4.2） | ✅ |
| | hover / 选中背景 | `#f2f6fb` / `#eef4ff` | ✅ |
| | 省略 | **不做省略** | — | 420px 宽下 46 字符可完整显示；更长者靠横向滚动 + `toolTip` 全名 |
| 空态 | 文案 / 色 | 「无匹配信号」/ `#8b95a3` | ✅ |
| 底部条 | 背景 / 上边框 | `#fafbfd` / 1px `#edf1f6` | ✅ |
| | 内边距 / 字号 | 7px 10px / **12px**（整数 px，理由同 4.2） | ✅ |
| | 链接按钮色 | `#1769e0`，hover 底 `#eef4ff`，禁用 `#a8b2bf` | ✅ |

### 4.6 新增图标

在 `mf4_analyzer/ui_kit/icons.py` 的 `Icons` 类中新增：

```python
@classmethod
def chevron_down(cls, color=None): ...
@classmethod
def chevron_up(cls, color=None): ...
```

- 走现有 `_line_icon(draw, color)` 路径（20×20 逻辑画布、2x DPR、`Antialiasing`）。
- **不要**走 `ensure_icon_cache()` / `{{ICON_*}}` QSS 占位符那条路：那套机制是为
  **QSS subcontrol**（`QComboBox::down-arrow`）准备的，lesson
  `pyqt-ui/2026-04-28-qss-subcontrol-needs-explicit-arrow-glyph.md` 的约束只适用于
  subcontrol。这里的箭头是一个真实的 `QPushButton`，`setIcon()` 即可，不需要
  qtawesome 依赖、PNG 缓存和路径正斜杠处理。
- 描边宽度对齐现有线性图标（`_pen(color, 1.7)`），V 形开口向下，两笔一折。

**已知不一致（需知悉）**：本控件将使用 chevron（线条），而同一面板内的
`QComboBox` 仍是 `mdi6.menu-down`（实心三角）。这是本次刻意接受的取舍——
原型用的是 chevron 且已获认可，而 `style.qss` 记录了 `QComboBox::drop-down`
保留不动的既有约束。若后续希望全局统一，应作为独立的样式统一任务处理。

---

## 5. 对外契约

### 5.1 保持不变（外部调用者依赖，签名与语义均不得变）

被 `input_panel.py` / `sheet.py` / 测试直接调用：

```python
set_selected(signals: Iterable[str]) -> None
selected() -> tuple[str, ...]
selectionChanged: pyqtSignal(tuple)
set_available(signals: Iterable[str]) -> None
set_partially_available(mapping, *, selectable: bool = False) -> None
show_popup() / hide_popup() / is_popup_visible() -> bool
visible_items() -> list[str]
is_disabled(signal: str) -> bool
label_for(signal: str) -> str
set_search_text(text: str) -> None      # 语义微调：写入弹层内搜索框
sizeHint() / minimumSizeHint()          # 仍返回 38 高、与已选数无关
SignalPickerPopup(..., single_select: bool = False)
```

`set_partially_available` 的「选中项在变为不可用时保留在 `_selected` 且不误发信号」
这一行为由 `test_set_partially_available_keeps_selection_marked_unavailable`
（ultrareview bug_002 的回归）守着，**必须原样保留**。

### 5.2 内部结构变更

| 现状 | 改造后 | 影响 |
| --- | --- | --- |
| `_display_frame`（`_ClickableFrame`） | `_trigger`（按钮语义） | 测试引用需更新；建议保留 `_display_frame` 作为别名属性以缩小改动面 |
| `_search` 在 `_display_frame` 内 | `_search` 在 `_popup` 内 | **语义反转**，见 6.1 |
| `_chip_host` / `_chip_layout` | 移除 | |
| `_overflow_label` | 保留属性名，语义变为「+N 徽章」 | 文本仍是 `+{N-1}`，见 6.1 的巧合说明 |
| `_search_hint` | **移除** | 症状 05 |
| `_arrow_button.setText("⌄")` | `setIcon(Icons.chevron_down())`，`text()` 为空 | |
| `SignalChip` 类 | picker 不再实例化 | 处置见 5.3 |

### 5.3 `SignalChip` 的处置

方案 A 下 `SignalChip` 在 `SignalPickerPopup` 中不再被使用。当前它还被
`tools/render_batch_input_output_polish.py` 与两条单元测试引用。

**决定：连同其测试与工具引用一并删除。** 理由：留着一个无人实例化的
widget 类等于死代码，而它的存在会诱导后续改动把 chips 塞回收起态——那正是
症状 03 的来源。删除范围见执行计划第 4 步。

---

## 6. 测试影响

### 6.1 必须改写（语义已反转或概念已消失）

| 测试 | 位置 | 处理 |
| --- | --- | --- |
| `test_picker_search_lives_in_original_field_not_popup` | `tests/ui/test_batch_signal_picker.py:21` | **反转**并改名为 `test_picker_search_lives_in_popup_not_trigger`：断言 `_popup.isAncestorOf(_search)` 为真、触发器内无 `QLineEdit` |
| `test_focus_to_inline_search_keeps_popup_open` | `:66` | 重写：搜索框已在弹层内，改为断言「弹层打开后 `_search` 自动获得焦点」 |
| `test_picker_display_summarizes_selected_items_that_do_not_fit` | `:125` | 改为断言摘要文本非空 + `_overflow_label.text() == f"+{len(names)-1}"` + tooltip 含全部名字，不再引用 `SignalChip` |
| `test_picker_display_stays_single_line_and_inside_narrow_host` | `:145` | 保留「单行 + 子元素不越界」意图，把子元素集合换成 `摘要 / 徽章 / 箭头`（去掉 `SignalChip` 与 `_search`） |
| `test_picker_active_search_uses_original_field_width` | `:178` | **删除**：「搜索占用原字段宽度」这个概念随方案 A 消失。以 6.3 的新回归测试取代 |
| `test_picker_display_chip_remove_unselects_signal` | `:202` | 改写为「在弹层内取消勾选可移除信号」 |
| `test_signal_chip_emits_remove_signal` | `:104` | **删除**（随 `SignalChip`） |
| `test_signal_chip_label_truncates_long_name` | `:115` | **删除**（随 `SignalChip`） |
| `test_picker_display_clicking_empty_area_opens_popup` | `:218` | 更新控件引用（`_display_frame` → `_trigger`），行为不变 |

### 6.2 预期原样通过（勿改，用作行为守卫）

- `test_picker_emits_selection_on_check`、`test_picker_search_filters_list`、
  `test_picker_marks_partial_signals_grey`、`test_picker_popup_collapses_on_escape`、
  `test_picker_popup_collapses_on_focus_out`、
  `test_set_partially_available_keeps_selection_marked_unavailable`、
  `test_picker_single_select_*`、`test_picker_popup_rounded_corners_have_no_square_frame`
- `tests/ui/test_batch_smoke.py:197`（`_overflow_label.text() == "+3"`）：
  现状是「4 选 / 窄宽下可见 1 chip → +3」，方案 A 是「4 选 / 摘要显示 1 个 → +3」，
  **数值巧合一致**，预期无需修改。实现后须确认这一点，若不一致按 6.1 的口径改。
- `tests/ui/test_batch_input_panel.py` 中所有 `set_selected` 调用：走的是公开接口，
  不受影响。

### 6.3 新增测试（每条对应一个症状）

| 新测试 | 守的症状 |
| --- | --- |
| `test_picker_arrow_uses_drawn_icon_not_text_glyph`：`_arrow_button.text() == ""` 且 `not icon().isNull()` | 01 |
| `test_picker_trigger_has_sunken_resting_background`：静止态样式含 `#eef2f7`，展开态含 `#fff` | 02 |
| `test_picker_trigger_geometry_is_stable_across_search`：记录摘要/徽章/箭头的 `geometry()`，`set_search_text("xxx")` 后再取，**逐一相等** | 03 / 04 |
| `test_picker_popup_is_at_least_420_wide` | 05 |
| `test_picker_summary_elides_in_middle`：长名摘要同时包含原名的头片段与尾片段（如 `_xds16`） | 05 |
| `test_picker_popup_select_all_adds_filtered_matches`：筛选后点全选，已选为筛选结果的并集 | 批量选择 |
| `test_picker_popup_select_all_skips_disabled_partials` | 3.3 约束 |
| `test_picker_single_select_hides_select_all` | 3.3 约束 |

### 6.4 工具

`tools/render_batch_input_output_polish.py::_save_picker_proofs` 引用了
`SignalChip` / `_chip_host` / `_search` / `_arrow_button`，须同步更新为新结构，
否则渲染证据脚本会直接报错。

---

## 7. 验收标准

功能性：

1. 五个症状逐条消除，由 6.3 的新测试覆盖。
2. `pytest tests/ui/test_batch_signal_picker.py tests/ui/test_batch_input_panel.py
   tests/ui/test_batch_smoke.py` 全绿（相对改动前基线无新增失败）。
3. 全量套件相对基线无新增失败（`main` 上 `tests/ui/test_split_*` 已知红，不计入）。

视觉（**必须真机验证**，`offscreen` 不作为视觉验收依据）：

4. macOS 原生平台启动 GUI，批处理抽屉截图与原型卡片 A 逐项对标，核对清单见
   执行计划第 7 步。
5. 收起态在静止、hover、展开三态下均能看出是可点区域（症状 02 的主观验收点）。

---

## 8. 未决与后续

- **箭头字形不一致**（chevron vs `QComboBox` 的实心三角）：本次接受，见 4.6。
- **方案 C 入口**：本次不预埋。若后续通道数继续增长（当前单来源已 24 条、
  名字普遍 30–46 字符），在弹层底部条右侧加「在面板中选择」是自然的下一步，
  届时 A 的数据层可原样复用。
- **Windows 等宽回退**：`"SF Mono"` / `"Menlo"` 均为 macOS 字体，Windows 上会落到
  `monospace` 的系统默认（通常 Courier New，字宽偏大）。这是项目既有惯例的固有行为，
  本次沿用、不单独处理；若 Windows 端摘要出现明显溢出，作为独立问题处理。
