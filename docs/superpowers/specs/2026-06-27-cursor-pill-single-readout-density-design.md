# 单游标读数面板密度与折叠态优化设计

## 背景

用户反馈来自单游标读数面板截图：

- 展开态每个通道读数之间的垂直间距太大，7 条通道已经占据很高一块区域。
- 右上角 `-` / `+` 按钮视觉几乎一样，只靠字形表示状态，用户难以一眼判断当前是展开还是收起。
- 用户希望 `-` 收起后只显示数值，并用通道颜色区分，不再显示完整通道名。

当前代码锚点：

- `mf4_analyzer/ui/chart_stack/stack.py:1047` 的 `_format_cursor_info_for_pill(...)` 把单游标 HTML 拆成 `primary` 和 detail table。
- `mf4_analyzer/ui/chart_stack/stack.py:1058` 对第二行开始使用 `padding-top:6px`，加上 `CursorPill` 自身 layout 间距，造成截图里的高行距。
- `mf4_analyzer/ui/chart_stack/cursor_pill.py:38` 使用 `QVBoxLayout`，margin 是 `10, 7, 22, 8`，spacing 是 `4`。
- `mf4_analyzer/ui/chart_stack/cursor_pill.py:146` 的 `_toggle_mode()` 只切换 `_mode` 和按钮文字 `+` / `-`。
- `mf4_analyzer/ui/chart_stack/cursor_pill.py:152` 的 `set_dual_rows(...)` 让 mini/full 模式目前主要服务双游标统计，单游标 detail 还没有对应的 mini detail。
- `mf4_analyzer/ui/plot_helpers.py:65` 的 `_format_single_cursor_channel_html(...)` 已经把单游标通道数值放进 `<b>...</b>`，颜色放在外层 span；这可以作为 mini 视图的数据源，不需要重新计算游标值。

这份 spec 只定义时域单游标读数 pill 的显示优化，不改变游标计算、插值、可见通道过滤、分屏路由、截图合成或复制逻辑。

## 目标

1. 单游标展开态显著减少行距，在同样高度里容纳更多通道读数。
2. `-` / `+` 状态有明确视觉差异、明确 tooltip 和可测试的 Qt property。
3. 单游标收起态保留顶部时间行，只显示每个通道的彩色数值和单位，不显示通道名。
4. 收起态仍能追溯通道身份：通道名进入 detail 的 tooltip。
5. 分屏下主/副 pane 仍各用自己的 `CursorPill`，互不覆盖。
6. 继续保持 pill 圆角透明像素与复制图片合成路径稳定。

## 非目标

- 不改 `CursorController._emit_single_cursor_html(...)` 的插值和 HTML emission contract。
- 不改 `plot_helpers._format_single_cursor_channel_html(...)` 的完整通道名输出契约。
- 不新增图例、表格面板、悬浮侧栏或右侧 Inspector 控件。
- 不把收起态做成通道选择器；它只是一个更紧凑的读数视图。
- 不让 FFT / FFT vs Time / Order 热力图 hover pill 重新显示；当前只在 TimeDomain 显示 cursor pill 的限制保持不变。

## 用户体验契约

### 展开态

展开态是默认状态，按钮显示 `-`。

显示内容：

- 第一行：时间，例如 `t=35.0358s`。
- 明细行：每个可见通道一行，保留 `[file]` 前缀、完整通道名、数值和单位。
- 通道名和值继续使用该通道颜色，文件前缀继续使用灰蓝色。

密度要求：

- 明细行之间使用紧凑间距，第二行开始的 `padding-top` 从当前 `6px` 降到 `2px`。
- 明细行 `line-height` 从当前 `1.35` 降到约 `1.15`。
- detail table 的 `padding-bottom` 不再额外撑开高度。
- `CursorPill` layout spacing 从 `4` 降低到 `2`；外边距保持足够触控和圆角留白，不做激进压缩。

### 收起态

收起态按钮显示 `+`。

显示内容：

- 第一行仍显示时间。
- 明细区只显示一列紧凑彩色数值，每行包含：
  - 一个小色点或短色条，颜色等于通道颜色。
  - 数值和单位，例如 `0 Nm`、`-0.0498 Nm`、`395.5 deg`。
- 收起态不显示 `[file]`、通道名、`=`。
- detail tooltip 包含完整通道名和数值，每行一条，便于需要时确认身份。

视觉判断：

- 收起态不应因为只显示数值而显得“信息丢失不可恢复”。`+` 的 tooltip 必须说明可以展开通道名。
- 颜色是主区分方式，色点/色条是辅助区分方式；不要只把数值文字染色后完全没有图形锚点。

### Toggle 状态

按钮行为：

- full 状态：文字 `-`，tooltip `收起为数值`，视觉为中性灰。
- mini 状态：文字 `+`，tooltip `展开通道名`，视觉更明显，使用蓝色填充或蓝色边框。
- 按钮有动态 property，例如 `cursorPillMode="full"` / `"mini"`，用于 QSS 和测试。

按钮位置：

- 仍固定在 pill 右上角。
- 因收起态 pill 更窄，按钮仍保持 16x16，不能挤压第一行时间文本。

### 分屏行为

分屏时：

- 主 pane 的单游标读数只进入主 `_pill`。
- 副 pane 的单游标读数只进入 `_pill_secondary`。
- 主/副 pill 的 full/mini mode 可以各自独立。
- 修改不改变 `ChartStack._pill_for_canvas(...)` 路由。

## 技术设计

### 单游标 detail variants

保留 `_format_cursor_info_for_pill(text, mode)` 的兼容返回值 `(primary, detail)`，供已有测试和外部调用继续使用。

新增内部 helper，例如 `_format_single_cursor_variants_for_pill(text)`，返回：

```python
primary, full_detail, mini_detail, tooltip
```

规则：

- `primary` 是原第一个 HTML part。
- `full_detail` 是紧凑版 full table。
- `mini_detail` 是只显示色点和值的 mini table。
- `tooltip` 是纯文本多行，每行包含通道名和值。

解析策略：

- 继续用 `_CURSOR_HTML_SEP` 拆分原 HTML。
- 对每个通道 part：
  - 从 `style="color:..."` 中取通道色；没有取到则用 `#111827`。
  - 从 `<b>...</b>` 中取数值+单位；没有取到则从 `=` 后面的纯文本兜底。
  - 用去标签后的纯文本生成 tooltip；保留完整通道名。
- 解析失败时不丢行：mini 兜底显示去标签后的整行纯文本，但仍不应崩溃。

### CursorPill 状态

`CursorPill` 增加单游标 detail variant 状态：

- `_single_full_detail`
- `_single_mini_detail`
- `_single_tooltip`

新增方法：

- `set_single_detail_html(full_html, mini_html, tooltip="")`

刷新逻辑：

- 如果 `_dual_rows` 非空，保持现有双游标 full/mini 逻辑。
- 否则如果有 `_single_full_detail`，根据 `_mode` 显示 full 或 mini。
- 否则使用普通 `set_detail_html(...)` 的 raw detail。

清理逻辑：

- `clear()` 清空 single variants、dual rows、detail tooltip 和可见状态。
- `set_detail_html("")` 也清空 tooltip，避免上一条 tooltip 残留。

### QSS

`QPushButton#cursorPillToggle` 保留 16x16 尺寸。

新增动态属性样式：

- `QPushButton#cursorPillToggle[cursorPillMode="full"]`：中性灰。
- `QPushButton#cursorPillToggle[cursorPillMode="mini"]`：蓝色边框或蓝色填充，清晰区别于 full。

切换 property 后调用 `unpolish/polish` 或等价刷新，确保 Qt 动态属性样式立即生效。

## 验收标准

### 字符串契约

- 单游标 full detail 不再包含 `padding-top:6px`。
- 单游标 full detail 包含 `padding-top:2px` 和紧凑 `line-height`。
- 单游标 mini detail 包含原数值和单位。
- 单游标 mini detail 不包含通道名、不包含 `[file]` 前缀、不包含 `=`。
- detail tooltip 包含完整通道名和数值。

### Widget 契约

- `CursorPill` 初始 full：按钮文字是 `-`，tooltip 是 `收起为数值`，property 是 `full`。
- 切换到 mini：按钮文字是 `+`，tooltip 是 `展开通道名`，property 是 `mini`。
- 再次切换回 full：状态恢复。
- `clear()` 后 tooltip 不残留。

### 回归契约

- `tests/ui/test_chart_stack.py::test_cursor_pill_renders_transparent_rounded_corners` 继续通过。
- `tests/ui/test_split_per_pane_controls.py` 相关 per-pane cursor pill 测试继续通过。
- `tests/ui/test_pg_timedomain_canvas.py` 中单游标 HTML emission 测试不需要改动，因为 canvas emission contract 不变。

### 人工验证

在真实 TraceLab 窗口中打开包含 6 条以上通道的时域图：

- 单游标展开态可见行数明显增加，行距不再像截图那样松散。
- 点击 `-` 后按钮变成更明显的 `+` 状态，面板只显示时间和值。
- 点击 `+` 后恢复完整通道名。
- hover tooltip 能确认收起态每个数值对应的通道。

