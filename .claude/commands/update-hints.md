---
description: 核对最近 UI 改动，维护两个发现性面——滚动提示 footer + 操作速查面板（项目内命令）
---

# /update-hints — 维护「滚动提示 + 操作速查面板」

任务：核对自上次以来的 UI 交互改动，让两个**发现性面**都跟上——找出「缺 / 过期 /
在途未登记」的操作，起草并（经用户确认后）写回。

设计依据：
- `docs/superpowers/specs/2026-06-25-update-hints-command-design.md`（命令本身）
- `docs/superpowers/specs/2026-06-25-operations-quickref-panel-design.md`（速查面板）

## 两个面 + 各自门槛

| 面 | 文件 | 收什么 | 约束 |
|----|------|--------|------|
| **A. 滚动提示 footer** | `mf4_analyzer/ui/hints.py` | **只非自明交互**（看不出来、想破头也不知道）：修饰键手势、右键菜单、框选/拖拽/双击、点击取样 | 文案 **≤18 全宽**；按 mode 门控轮播；渐进发现 |
| **B. 操作速查面板** | `mf4_analyzer/ui/quickref.py` | **全操作目录**：A 的全部 **＋** 自明项（文件格式、四个模式用途、普通按钮/菜单、导出…） | 无宽度硬限（但简洁）；按区域分组；主动查·一览 |

- 一条操作可能**只进 A**、**只进 B**、或**两者都进**（如「框选缩放」既是 footer 提示
  也在面板的「图表手势」组）。
- **共享纪律**：快捷键文案两面都**复用** `hints.shortcut_tooltip(key)`（改快捷键只动
  `hints` 注册表，两面自动跟）；在途功能 A 用 `ship="later"`、B 用 `soon=True`，落地时
  一起翻正。

## 单一事实源

- 滚动提示：`mf4_analyzer/ui/hints.py`（`_HINTS` 四 surface + `_FLASH_TIPS`）；系统设计
  `docs/superpowers/specs/2026-06-01-chart-hint-system-design.md`；测试 `tests/ui/test_hints.py`。
- 操作速查：`mf4_analyzer/ui/quickref.py`（`QUICKREF` = `QuickGroup` 列表，`QuickGroup{title,
  rows, note, wide}`、`QuickRow{desc, sub, keys, gesture, soon, accent}`）；测试
  `tests/ui/test_quickref.py`（+ 控件 `quickref_panel.py` 测试 `test_quickref_panel.py`）。

## 流程

1. **定范围**：`git log --oneline -30`，并扫 `docs/superpowers/specs/` 与
   `docs/superpowers/plans/` 里新/改的设计文档。**全量核对**，不依赖标记文件。
2. **枚举操作点**（grep，read-only）：
   - 非自明交互（→ 面 A 也进 B）：`event.modifiers()`、`AltModifier`、`ControlModifier`、
     `ShiftModifier`、`_on_context_menu`、`addAction(`、`RectMode`、`框选`、
     `mouseDoubleClick`、点击取样（`pick`/`选为`/`切片`）。
   - 自明但该上墙的（→ 仅面 B）：工具栏/卡片按钮、文件格式（`DATA_FILE_GLOB`）、分析模式、
     导出/预设入口、`setToolTip(` 覆盖的控件。
3. **比对**：每个操作点，看 `_HINTS`/`_FLASH_TIPS`（A）和 `QUICKREF`（B）是否已有对应
   **交互**（按行为比，不只看 id）。
4. **分类**（标明涉及哪个面）：缺失 / 过期（文案与现行为不符）/ 在途（spec 有、功能未落地）。
5. **起草**（守约定）：
   - **面 A（hints.py）**：选 surface（`persistent`/`discovery`+`retire_on`/`context`+mode 门控
     /`anchor`）；文案 **≤ `HINT_MAX_WIDTH`(18 全宽)**，逐条用 `hints.hint_display_width` 验；
     在途用 `ship="later"`。
   - **面 B（quickref.py）**：归到对的 `QuickGroup`；键盘走 `keys=(...)` 用 `shortcut_tooltip`
     取值（别硬编码），鼠标手势走 `gesture=`（蓝胶囊）；在途 `soon=True`（「即将」徽标）；
     模式行带一句 `sub` 用途。
   - **通用**：用户分析 **EPS（电动助力转向）**，阶次 base = 电机转速，示例信号用 EPS 名
     （方向盘扭矩/电机转速/电机扭矩），别用 engine；Mac/Win 修饰键并列写 `Option/Alt`。
6. **报候选给用户**：按面分列 `[面 A/B][分类] 标识 · 门控/分组 · 文案 · 理由`，等确认 / 改文案。
7. **写回**：`hints.py`（+ 不变量动了同步 `test_hints.py`）；`quickref.py`（+ 同步
   `test_quickref.py`）。优先**改现有条目**而非加重复。
8. **验证**：`pytest tests/ui/test_hints.py tests/ui/test_quickref.py`（必须全绿，尤其
   hints 宽度预算）。UI 若涉及面板渲染改动，按 CLAUDE.md **真机截图**核对。
9. **汇报**：按面列实际改动 + 测试结果 + 仍 `ship="later"`/`soon=True` 待落地的项。

## 注意

- 两面**保持一致**：同一操作的快捷键/措辞别两处打架（快捷键统一从 `shortcut_tooltip` 取）。
- 别动测量算法 / 非提示代码；只碰这两份注册表 + 其测试（+ 必要的面板控件）。
- 项目在 `~/Downloads` 时 Bash 可能 EPERM（macOS TCC）—— 测试若被挡，请用户用
  `! pytest tests/ui/test_hints.py tests/ui/test_quickref.py` 或给终端授 Full Disk Access。
