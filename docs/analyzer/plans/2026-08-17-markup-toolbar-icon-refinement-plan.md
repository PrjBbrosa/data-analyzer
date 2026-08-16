# 标注编辑器工具栏图标精致化

状态：提案，尚未改产品代码  
输入：2026-08-17 用户反馈——复制图片后进入「图片标注」的按钮 UI 偏 low；图标做成**标准矩形**；提升精致感；可用图库；方案需匹配当前软件。  
交互稿：[2026-08-17-markup-toolbar-icon-options.html](../ui-prototypes/2026-08-17-markup-toolbar-icon-options.html)

## 1. 决策与边界

### 1.1 改什么

只改复制图表 → 右下角缩略图 → 点进 `MarkupEditor` 之后那条顶栏的**视觉语言**：

- 工具按钮外形：统一标准矩形（等宽等高），不要圆标、不要 76×44 与 44×44 混高。
- 图标：继续走现有 `qtawesome` 图库，不引入新包、不手绘 PNG。
- 选中态：从整块实心蓝 + 白字，改成 Precision Light 的浅洗 + 蓝描边 + 蓝字形。
- 关闭钮：与工具同尺寸矩形；危险色只在 hover，不要常驻粉底。

不改：工具集合、快捷键、撤销栈、样式弹出层的功能、完成复制 / 保存的语义、3 秒缩略图合同。

### 1.2 为什么现在看起来 low

现状在 `mf4_analyzer/ui/markup/toolbar.py` + `editor.py::_TOOL_ICONS`：

| 点 | 现状 | 问题 |
| --- | --- | --- |
| 外形 | 44×44、`border-radius: 6px` | 比图表工具栏、菜单行都大一号，像独立玩具条 |
| 选中 | `#1769e0` 实心填满 | 对比度靠白字形硬撑，和软件其它 checked 浅洗不一致 |
| 序号 | `ph.number-circle-one` | 圆标，破坏「标准矩形」 |
| 样式钮 | 76×44 | 同一条栏里出现第二种矩形 |
| 关闭 | 粉底红框 44×44 | 常驻告警色，比工具还抢眼 |
| 样式表 | 写在 widget 内联 QSS | 与 `style.qss` / `#chartToolbar` 脱节；状态规则里的 `border:` 简写也踩 QSS 棘轮风险 |
| 图库混用 | Phosphor 字形 + 自绘色板/线宽 | 视觉重量不齐 |

### 1.3 匹配当前软件的视觉合同

这条编辑器走的是**分析区 Precision Light**（`#1769e0` / `#dfe5ee` / `#eaf2ff`），不是 UltraView 钛青绿。对标对象：

- 图表工具栏 `QWidget#chartToolbar QToolButton#chartTickDensityButton`：白底、`#b7c8dc` 发丝边、7px 圆角、hover `#e8f1ff` / `#0b7af3`
- 全局 `[role="tool"]`：让 `setFixedSize` 真正生效（`min-width/min-height: 0`）
- 右键菜单 / 卡片动作：矩形图标按钮，glyph 居中，不靠 emoji、不靠渐变

推荐尺寸（方案 A，见 HTML）：**36×36 矩形、圆角 7px、字形 18px**。比现在的 44 更贴图表栏，仍大于 28px View 轨，点选工具够用。

### 1.4 图库

继续 `qtawesome`，**不新加依赖**。

- 默认（方案 A）：保留 Phosphor Regular，只换掉圆标。
- 备选（方案 B）：改用产品里 UltraView 已在用的 Font Awesome 5（`fa5s.*`），字形更「方」、墨水更足。
- 序号禁止 `ph.number-circle-one` / `fa5s.circle`。改为 `ph.list-numbers` 或 `fa5s.list-ol`；若仍不够「1 号标注」，用 `Icons.py` 画一个 **圆角方块里的 1**，外形仍是矩形。

推荐映射（方案 A）：

```text
select  ph.cursor
crop    ph.crop
arrow   ph.arrow-up-right
line    ph.line-segment
rect    ph.rectangle
pen     ph.pencil-simple
text    ph.text-t
number  ph.list-numbers          # 替换 circle
close   ph.x
undo    ph.arrow-counter-clockwise
redo    ph.arrow-clockwise
```

## 2. 方案（先选再做）

交互稿里四条栏可点选对比。落地只做用户点名的那一套，不并行三套。

| 方案 | 外形 | 图库 | 选中 | 适合 |
| --- | --- | --- | --- | --- |
| **0 现状** | 44 方 + 76 宽 | Phosphor + 圆序号 | 实心蓝 | 对照用 |
| **A 精密矩形（推荐）** | 一律 36 高；工具 36×36；样式 52×36 | Phosphor | 浅洗 + 蓝边 | 改动小，和标注蓝一致 |
| **B 图表孪生** | 32×32，7px，`#b7c8dc` | FA5 | 同图表栏 | 和时域工具栏一家 |
| **C 一体岛** | 工具挤进一条胶囊，内部方格无独立外框 | Phosphor | 岛内浅洗 | 更「应用」，QSS 稍重 |

关闭 / 撤销 / 重做与工具**同高同宽**。保存、完成复制继续做右侧文字主按钮，不改成图标——那是提交动作，不是工具。

复制后右下角 `CopyThumbnail` 的文字 `"×"` 关闭钮，作为**同一次视觉语言扫尾**（可选 Task 3）：改成 28×28 矩形 `ph.x`，QSS 收到 `#copyThumbnail`。不改 3 秒倒计时、悬停暂停、点击打开编辑器。

## 3. 实施任务

确认方案后再动代码。默认按 A 估。

### Task 1 · 把工具栏 QSS 收到 `style.qss`

**Files:** `mf4_analyzer/ui_kit/style.qss`、`mf4_analyzer/ui/markup/toolbar.py`

- `#markupEditorToolbar QToolButton` 写完整属性：`background-color` / `border-width` / `border-style` / `border-color` / `border-radius`，**禁止状态规则用 `border:` 简写**（`tests/ui_kit/test_qss_border_shorthand.py`）。
- 按钮设 `role="tool"`，让全局 min-height 不再把 `setFixedSize` 撑破。
- `compact_tool_button_qss()` 删掉或收成空；关闭钮不再单独一份粉红 QSS，hover 用 `#markupCloseButton:hover`。
- 新连接继续 bound method，不新增 `.connect(lambda`。

Owner：`tests/ui_kit/test_qss_border_shorthand.py`

### Task 2 · 矩形尺寸 + 图库映射

**Files:** `toolbar.py`、`editor.py`（`_TOOL_ICONS` / `_tool_icon`）

- 工具 / 关闭 / 撤销 / 重做：`setFixedSize(36, 36)`，`setIconSize(18, 18)`。
- 样式触发：高度 36，宽度约 52，内部仍是色块 + 线宽 pip。
- `_TOOL_ICONS["number"]` 改为矩形字形；选中色用 `#1769e0` 字形而不是白字。
- 更新 `tests/ui/test_markup_toolbar_wiring.py` 里钉死的 44px 几何（那是刻意 hit-target，改尺寸必须改断言，不要删这条断言）。

Owner：`tests/ui/test_markup_toolbar_wiring.py`、`tests/ui/test_color_swatch_hidpi.py`

### Task 3 ·（可选）CopyThumbnail 关闭钮同款矩形

**Files:** `mf4_analyzer/ui/markup/thumbnail.py`

- `"×"` 文字按钮 → `QToolButton` + `qta.icon("ph.x")`，28×28，7px 圆角。
- 样式进 `#copyThumbnail`，不要继续内联一整段。

Owner：`tests/ui/test_copy_thumbnail.py`

### Task 4 · 发现性文案（仅当可见标签变化时）

图标 tooltip 文案若不变，hints / quickref / help **不必**改。若方案 B 把「序号」理解成列表、或关闭钮从粉红块变成普通方钮，补一句操作速查即可。

## 4. 验证

聚焦，不跑全量。

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_markup_toolbar_wiring.py \
  tests/ui/test_color_swatch_hidpi.py \
  tests/ui/test_copy_thumbnail.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py \
  -q
```

真机 Cocoa：复制一张时域图 → 点缩略图进标注 → 核对矩形对齐、hover/checked、序号不是圆、关闭钮不常驻粉。offscreen 不能当视觉验收。

## 5. 不做

- 不换标注工具集、不改快捷键、不改完成复制流程。
- 不把这条栏改成 UltraView 钛青绿。
- 不引入第二套 icon 字体包；FA5 仅在用户选 B 时启用（qtawesome 已带）。
- 不把保存 / 完成复制收成纯图标。
- 不把 5 月底那份 `2026-05-31-markup-toolbar-options.html` 当现行合同——那是重构前的稿，尺寸和选中态都已过期。
