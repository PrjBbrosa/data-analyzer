# 设计方案：项目入口 + 工具栏重组 + 导出搬家

- **日期**：2026-06-09
- **状态**：已评审（含原生 mock 对齐），待写实现计划
- **涉及版本**：TraceLab v6.5
- **前置**：底层 `project_io` 与 `MainWindow.save_project()/open_project()` 已实现（见 `2026-06-09-project-io-and-toolbar-branding-design.md` + 已落地 commit）。本方案给它们接 UI，并顺带重组工具栏左簇。

---

## 1. 背景与目标

底层项目读写已就位但**无 UI 入口**。本轮加入口，并按用户拍板重组：

- 蓝色「添加文件」**一分为二** → 「打开」+「保存项目」。
- 「打开」**统一开文件/项目**：按所选文件扩展名自动分流。
- 「导出」**移出工具栏**，搬进「通道编辑」抽屉做一个新 section（逻辑：先选文件 → 再导出）。

净效果：工具栏左簇仍是 4 个按钮 `[打开][保存项目][批处理][Cockpit]`（与现状 `[添加文件][导出][批处理][Cockpit]` 数量持平，不更挤）。

---

## 2. 工作线 C — 工具栏：打开 / 保存项目

### 2.1 「打开」（统一入口，蓝色 primary）
`btn_add` 文案改「打开」、信号 `file_add_requested` → 重命名 `open_requested`，连到**新** handler `MainWindow.open_files_or_project()`。
对话框 filter 增加 `*.tlproj`。选中后按扩展名分流：

| 选中内容 | 行为 |
|---|---|
| 只有数据文件（.mf4/.csv/.xlsx/.xls） | 逐个 `_load_one`（**追加**，现状不变） |
| 恰好 1 个 `.tlproj`，无数据文件 | `open_project`（**替换**；若 `self.files` 非空先弹确认） |
| 1 个 `.tlproj` + 若干数据文件 | 先 `open_project`，再把数据文件逐个 `_load_one` 追加 |
| ≥2 个 `.tlproj` | 拒绝 + 提示「一次只能打开一个项目」 |

**替换护栏**：项目无脏标记，故规则用「`self.files` 非空 → 确认弹窗『打开项目将关闭当前 N 个文件，是否继续？』」，取消则中止。

`load_files()` **保留原样**（纯加数据，`test_main_window_smoke` 与 Cockpit handoff 仍依赖）。

### 2.2 「保存项目」（新按钮，次级）
新增 `btn_save_project`「保存项目」+ 信号 `save_project_requested` → handler `MainWindow.save_project_via_dialog()`。
**当前项目路径跟踪** `self._project_path`：
- `open_project(path)` / `save_project(path)` 末尾置 `self._project_path = path`；`__init__` 初始化为 `None`。
- `save_project_via_dialog()`：`_project_path` 已存在 → 直接覆盖；否则弹 `getSaveFileName(... "*.tlproj")` 另存为，再 `save_project(path)`。

### 2.3 移除「导出」按钮
删除 `btn_export` 与 `export_requested` 信号；`set_enabled_for_mode` 不再 gate `btn_export`，改为 gate `btn_save_project`（`has_file` 才可保存）。
连带更新 `tests/ui/test_toolbar.py:24/28/44`（现断言 `btn_export`，改为 `btn_save_project`/`btn_add`）。

---

## 3. 工作线 D — 导出搬进「通道编辑」

### 3.1 新 section 位置与样式
在 `ChannelEditorDialog`（`ui/dialogs.py`）的滚动体 `bl` 里，**插在 `g2`（双通道运算, line 169 后）与 `g3`（删除, line 186 前）之间**，新增 `QGroupBox("导出")`，样式与其它 section 对齐（按钮用 `objectName("channelCreateBtn") + property("role","create")` 或 primary）。**不加额外取消/应用**（对话框已有自己的「取消/确定」页脚，保留不动）。

section 内容（参照已对齐的 mock）：
- 一个 **checkable 通道列表**（`QListWidget`，每项 `ItemIsUserCheckable`）——导出用**自己的勾选**，与「删除」区的多选高亮互不干扰。在 `_populate_channels()` 里随当前文件刷新（清空 + 按 `fd.get_signal_channels()` 加项，默认勾选）。
- `QCheckBox("包含时间列")`（默认勾）。
- `QCheckBox("仅导出选定时间范围")`（读主窗时间范围）。
- `QPushButton("导出 Excel")`。

### 3.2 信号与执行边界
对话框只收集选择，不直接落盘。新增信号
`export_requested = pyqtSignal(str, list, bool, bool)` → `(fid, channels, include_time, use_range)`，点「导出 Excel」时 emit（无勾选则提示并不 emit）。
`ChannelEditorDrawer` 像 `applied` 一样**再 emit** 该信号；`MainWindow` 在抽屉创建处（`main_window.py:1782-1787`）连到新 handler。

`MainWindow._do_export_excel(fid, channels, include_time, use_range)`（由现 `export_excel` 体抽出）：读 `self.files[fid]`，按 `include_time` 加 Time 列、按 `use_range` 用 `inspector.top.range_values()` 过滤，`getSaveFileName` → `df.to_excel(engine='openpyxl')`，toast + statusBar。
旧 `export_excel`（开 `ExportSheet` 那条路径）**移除**；`ExportSheet`/`ExportDialog` 文件保留不动（本轮不删，避免牵连）。

---

## 4. 代码锚点速查
| 关注点 | 位置 |
|---|---|
| 工具栏按钮/信号/`set_enabled_for_mode` | `ui/toolbar.py`（btn 创建 ~28-37，left 簇 ~58-64，wire ~128-137，set_enabled ~154-157）|
| 打开/导出 连线 | `ui/main_window.py:337`（file_add_requested→load_files）、`:338`（export_requested→export_excel）|
| 现 `load_files` | `ui/main_window.py:1291` |
| 现导出体 | `ui/main_window.py:1843-1874` |
| 编辑抽屉打开 + applied | `ui/main_window.py:1782-1787` |
| 对话框 section 顺序 | `ui/dialogs.py`：单通道 134 / 双通道 169 / 删除 186 / footer 192-209 |
| 通道填充 | `ui/dialogs.py:272 _populate_channels`（list_rm 模式在 289-291）|

---

## 5. 测试要点
- 打开分流：monkeypatch `getOpenFileNames`，四种组合各一例（追加 / 替换 / 项目+文件 / ≥2 项目拒绝），替换护栏确认。
- 保存：首存（无 `_project_path`→另存为）与覆盖（有路径）两条；`open_project` 后 `_project_path` 已置。
- 工具栏：`btn_add` 文案「打开」、存在 `btn_save_project`、不存在 `btn_export`；更新旧 `test_toolbar.py` 三处断言。
- 导出 section：构造 `ChannelEditorDialog`（合成 files），断言 section 存在、勾选后点按钮 emit `export_requested(fid, channels, True, False)`；`_do_export_excel` 写出临时 xlsx 并校验行列。
- 全量 UI 回归（`tests/ui/`）须全绿。

---

## 6. 不在本轮范围
- 真·拖拽导入（用户已确认不做）。
- 项目脏标记 / 关窗未保存提醒（替换护栏先用「非空即确认」兜底）。
- 删除 `ExportSheet`/`ExportDialog` 旧文件（仅停用）。
- 「另存为」独立按钮（保存按钮内含首存=另存为逻辑即可）。

## 7. 实现分工提示（写计划参考）
全部属 `pyqt-ui-engineer`（工具栏 / 对话框 / 信号接线 / 文件对话框）。无数值算法改动。
