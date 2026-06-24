# 操作速查面板（Quick-Reference Panel）设计

**日期**：2026-06-25
**状态**：设计已确认（HTML 方案 + pin 约束），待实现
**改动面**：新增 `mf4_analyzer/ui/quickref.py`（操作目录）+ `QuickRefPanel` widget
+ 触发/钉住 wiring + 样式；`tests/ui/test_quickref.py` + 真机截图验证

## 背景 / 问题

软件操作复杂、陌生人无从下手。现有 4 套帮助途径都**被动**：图文手册要开浏览器
且入口藏、滚动提示条一次一条且需先加载数据才出、按钮 tooltip 要逐个悬停、右键
菜单本身就藏。缺一个 **app 内随时唤出、一屏看全所有操作**的入口。

## 目标

按 `?` 唤出一个**美观的「操作速查」面板**，分区列全所有手势 / 快捷键 / 功能，
在 app 内、一览全貌。视觉与内容以已确认的 HTML 方案为准
（`scratchpad/操作速查-方案.html`，已发用户确认「就这样」）。

## ★ 关键约束：可 pin、不阻碍操作

- 面板**非模态**、**不压暗背景**；打开时主窗口**照常可操作**（点图、拖通道、
  缩放都不被挡）。
- **可钉住（pin）**：pin 后常驻置顶、不随失焦 / 点外自动关；未 pin 时是轻量
  「瞥一眼」，`Esc` / 点外即收。
- 可**拖动**（拖标题栏）重新摆放，避免挡住正在看的区域。
- ⚠️ HTML 方案里的「压暗背景」**只是 mockup 凸显效果，实现时去掉**。

## 形态与行为

- 触发：`?` 快捷键 + 一个可见入口按钮（状态栏，挨着现有「软件说明」📖）。
- 浮起卡 look（白卡 + 柔影 + 圆角），但作为**非模态浮窗**叠在 app 上
  （`Qt.Tool`；pin 时加 `WindowStaysOnTopHint` 或等效，保持主窗可操作）。
- 头部：标题 + 搜索框（过滤）+ pin 切换 + 关闭。

## 视觉

- 走现有 surface-UI token（托盘 `#f2f4f7`、白浮卡、`#5b6472` 灰、克制蓝）。
  **实现时读真实 QSS / 主题取准确色值与字体**，不照抄 mockup 近似值。
- ⚠️ 圆角 / 透明：**别用 `WA_TranslucentBackground` 直接套**（会让本体 QSS 失效，
  见 CLAUDE.md gotcha）。圆角 + 阴影用 `paintEvent` 或内部子 widget 兜底。
- 键帽（灰）vs 鼠标手势（蓝胶囊）双样式区分（同 mockup）。

## 内容目录（= 这次的「扩充」）

结构化目录 `quickref.py`，11 组（同 mockup）：开始/文件、四个分析模式（带一句
用途）、图表手势、快捷键、通道树、游标、谱图、标注、预设、导出/复制、右键菜单。

- 键盘行**复用** `hints.NAV_SHORTCUTS` / `TIME_CARD_SHORTCUTS`（单一事实源，改
  快捷键不用两处维护）。
- 共轴挂「即将」徽标（对应 `coaxis.* ship="later"`）；阶次写 **EPS 电机转速**。
- 数据结构：`group{title, rows[]}`，`row{desc, sub?, keys[]|gesture?, soon?}`。

## 与现有面的关系

- 滚动提示条 footer = 轮播子集（渐进发现）；速查面板 = 一览全集（主动查）。
- 底部「想深入 → 各模式『? 使用说明』」串到现有 HTML 手册。
- `/update-hints` 命令**后续扩展**：同时核对 / 维护 quickref 目录。

## 实现拆解

1. `quickref.py`：目录数据 + 取数 helper（复用 shortcut 注册表）。TDD：结构完整性、
   键盘行与 `hints` 注册表一致、「即将」项标记、无空组。
2. `QuickRefPanel(QWidget)`：非模态浮窗；头部（标题/搜索/pin/关闭）；body 网格分组卡；
   `paintEvent` 圆角 + 阴影；标题栏拖动；搜索实时过滤。
3. wiring：`?` `QShortcut` + 状态栏入口按钮；pin 切置顶；`Esc` / 点外（未 pin）收起。
4. 样式：读真实 surface QSS，匹配 token；键帽 vs 手势双样式。
5. 验证：**真机截图**对照 mockup（复用 `tools/` help 面板截图脚本思路）。

## 验证（真机优先，遵 CLAUDE.md）

- 截图真实 PyQt 渲染，与 `操作速查-方案.html` 比对观感。
- 确认：非模态时主窗仍可操作、pin 生效、圆角 / 阴影正常（**非灰底**）、macOS
  原生渲染正确。
- **不靠「属性设上了 + 单测过」判定**。

## 涉及文件

- `mf4_analyzer/ui/quickref.py`（新）
- `QuickRefPanel` widget（新）
- 触发 / 入口按钮 wiring（status bar / window）
- `tests/ui/test_quickref.py`（新）
- 本 spec
