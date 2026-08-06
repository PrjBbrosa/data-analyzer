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
改由 orchestrator 做两侧自动化渲染对比，可视面清单见最终报告。
