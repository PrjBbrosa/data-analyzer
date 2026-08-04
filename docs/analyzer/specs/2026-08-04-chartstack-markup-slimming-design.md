# ChartStack 与标注编辑器瘦身 · 设计(包 D)

- 日期:2026-08-04
- 基线:`main` @ `e385ce5a`(v7.9.3 + 通道表达式功能)。**本文所有行号以此 commit 为准。**
  (由 `6236a5fe` 更新;间隔仅一次 feature 提交 `6bda7ccb`,未触碰 chart_stack/markup,行号不变。)
- 来源:2026-08-04 全仓复杂度评审(杂项大文件分诊 + pg_canvas 探查)。
- 实施计划:[2026-08-04-chartstack-markup-slimming-implementation.md](../plans/2026-08-04-chartstack-markup-slimming-implementation.md)
- 前置:无(独立于包 A/B/C/E,可并行)。两个目标互相独立,可只做其一。

## 问题与收益

**目标 1 · `ui/chart_stack/stack.py`(1306 行,单类 `ChartStack` 83 个方法):**
游标 pill 的 HTML 文本格式化与定位约 270 行(:1032-1305)住在中心面板协调器里
(文件头 `from html import escape` + `import re` 是明确信号),而同目录**已有
`cursor_pill.py`**——归属本来就该在那。格式化函数是纯文本处理,搬出后可获得
无 Qt 的直接单测(当前只能通过整窗测试间接覆盖)。

**目标 2 · `ui/markup/editor.py`(1416 行,单类 `MarkupEditor` 85 个方法,注释率
仅 2.4%):** 同包已有 `commands.py` / `items.py` / `view.py` 分层却未被遵守。
三块可独立搬出:序列化(与 QWidget 无关)、工具栏构建、手柄拖拽几何。

## 已核实锚点

**stack.py pill 区(:1032-1305,方法清单 2026-08-04 grep 实测):**

- 纯格式化候选:`_format_cursor_info_for_pill`(:1089)、
  `_format_single_cursor_variants_for_pill`(:1100)、`_mini_single_cursor_part`(:1131)、
  `_plain_single_cursor_tooltip_line`(:1152)、`_single_cursor_channel_color`(:1164)、
  `_strip_html`(:1183)。
- 定位与快照(**本包第一阶段不动**):`_reposition_pill`(:1212)、
  `_reposition_one_pill`(:1234)、`cursor_pill_snapshot`(:1268)、
  `restore_cursor_pill_snapshot`(:1287)等。

**editor.py:** 图元工厂 :179-330;`_build_toolbar`(:394-549,156 行);
`_build_style_panel`(:701-771);手柄几何带 :901-1096;
`_serialize_item`(:1163-1210)/`_deserialize_item`(:1212-1268);
图标生成 :1282-1324;`keyPressEvent`(:1325-1416,本包不动)。

## 设计决策

**D-D1 · pill 格式化 → 并入 `chart_stack/cursor_pill.py`(必做)**

六个格式化方法降级为 `cursor_pill.py` 的模块级纯函数(显式收参数)。
实施前必查:`_single_cursor_channel_color` 等若读 `self`(如通道颜色查询),
把所依赖的数据变成参数,`ChartStack` 侧保留一行委托。`ChartStack` 的方法名与
签名全部保留(薄委托),外部与测试零改动。

**新增测试** `tests/ui/test_cursor_pill_formatting.py`:用**从现有测试与真实
canvas 输出采集的**代表性游标 HTML 字符串(单游标单通道 / 单游标多通道 /
双游标)断言:mini 与 plain 两种变体的输出结构、HTML 剥离正确性、异常输入
(空串/裸文本/嵌套标签)不抛异常。期望值先实测再固化。

**D-D2 · pill 定位与快照 → `CursorPillController`(可选,有闸门)**

D-D1 验收通过后才可做:`_reposition_*` / snapshot / `_on_*_cursor_*` 回调收拢为
`cursor_pill.py` 里的控制器类,`ChartStack` 持有实例。闸门:D-D1 全绿 +
`cursor_pill_snapshot` 的既有测试逐字保持。做不完就停在 D-D1,不算失败。

**D-D3 · 标注序列化 → `markup/serialization.py`(必做)**

`_serialize_item` / `_deserialize_item` 移为模块级函数。**先写往返测试再搬**:
新增 `tests/ui/test_markup_serialization.py`——对每种图元
(rect/line/arrow/path/text/number,以 :179-330 工厂为准)构造 → 序列化 →
反序列化 → 断言几何与样式字段逐项相等;再加「旧格式载荷向后兼容」用例
(从基线实现导出的 payload 常量固化进测试,防止格式漂移破坏已保存的标注)。

**D-D4 · 工具栏构建 → `markup/toolbar.py`(必做)**

`_build_toolbar` / `_build_style_panel` / 图标生成函数移出,editor 传回调。
**接线特征测试先行**:新增用例快照工具栏的按钮清单(objectName/文本/是否
checkable/初始选中态),基线跑绿后再搬,搬后原样绿。

**D-D5 · 手柄几何 → `markup/handles.py`(可选,有闸门)**

:901-1096 的命中/拖拽几何。闸门:D-D3/D-D4 完成且全量绿。纯几何函数
(命中判定、矩形缩放计算)提出时补直接单测;与 QGraphicsItem 强耦合的部分
留在 editor,不硬拆。

## 非目标

- `keyPressEvent`(92 行)不动;`ChartStack` 的焦点管理(:364-602)不动
  (留待后续独立立项);`ChannelEditorDialog.__init__` 不在本包(包 A 已排除)。
- 不改任何用户可见行为、文案、快捷键;完成后 `/update-hints` 无需运行。

## 验收准则

1. `tests/ui/test_chart_stack.py`(2973 行)、`test_markup_editor.py`(1180 行)、
   `test_copy_thumbnail.py`、`test_chart_stack_stats_visibility.py` 失败集与基线一致;
   三个新增测试文件全绿。
2. `ChartStack` 方法数下降(D-D1 后格式化逻辑不在 stack.py);
   `editor.py` 减少 ≥ 350 行(D-D3+D-D4)。
3. 序列化向后兼容用例通过(旧 payload 常量能被新代码正确还原)。
4. **真机验收:** 时域图上放单游标与双游标,核对 pill 内容与位置随缩放/分屏正确;
   打开标注编辑器,工具栏外观与基线截图一致,画一个矩形+文字,保存→重开→还原正确。
