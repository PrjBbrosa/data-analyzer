# 文件窗口拖动导入（Drag & Drop Import）— 设计

**日期：** 2026-06-27
**状态：** 已通过 brainstorming，待 user 复核 → writing-plans

## 1. 目标与范围

让用户把文件从 Finder / 资源管理器**拖入应用即可导入**，行为与现有「打开」菜单
完全一致，不新造任何业务语义（"按正常软件逻辑使用，不脑补"）。

- **接收区**：整个主窗口（拖到工具栏 / 文件列表 / 图表区 / 检查器任意位置都能放下）。
- **视觉反馈**：拖入时整窗叠一层半透明高亮遮罩 + 居中提示文字，离开/放下后消失。
- **复用现有分发**：拖入的路径走和「打开」菜单**同一条**分发逻辑，免费支持
  mf4/mdf · blf（含 DBC 交互）· csv · xlsx/xls · hdf（多组）· 音视频 · .tlproj。

非目标：拖动导出、应用内拖动重排、拖入 URL/文本、拖入文件夹递归扫描。

## 2. 现状（仓库事实）

- **「文件窗口」= `FileNavigator(QWidget)`** — `mf4_analyzer/ui/file_navigator.py:157`，
  左侧面板（文件列表 + 通道树）。
- **主窗口 `MainWindow(QMainWindow)`** — `mf4_analyzer/ui/main_window/window.py:63`，
  多 Mixin 继承（`AnalysisMixin, FFTMixin, OrderMixin, FFTTimeMixin,
  ProjectIOMixin, ViewMixin, QMainWindow`）。`__init__` 在 `window.py:121` 调
  `self._init_ui()`、`window.py:122` 调 `self._connect()`。中央控件 `cw`
  （objectName `centralTray`）在 `_init_ui` 内 `setCentralWidget(cw)`
  （`window.py:135-136`）。
- **导入入口** — `ProjectIOMixin`（`_project_io_mixin.py`）：
  - `open_files_or_project()` `:44` — 「打开」菜单 handler，`QFileDialog` 取 `fps`
    后做分发：数据文件追加 · 单个 `.tlproj` 替换（先确认）· 项目+文件先开项目再
    追加 · ≥2 项目拒绝。
  - `_load_one(fp, *, blf_dbc_paths=None)` `:182` — 核心导入，按扩展名分发到
    `DataLoader.load_*()`，注册数据并刷新 UI。本设计**一行不动**。
- **支持扩展名**（`_project_io_mixin.py:13-14`）：
  `*.mf4 *.mdf *.blf *.csv *.xlsx *.xls *.hdf` + 音视频
  `*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac`，外加项目 `*.tlproj`。
- **拖放代码现状**：全仓库 0 处 `dragEnterEvent/dropEvent/setAcceptDrops/mimeData`，
  从零实现。
- **铁律（CLAUDE.md + memory）**：① UI/视觉必须**真机渲染验真**（截图/objc），不靠
  "属性设上了 + 单测过"；② 嵌入浮层 / 自定义 QWidget 用 `WA_TranslucentBackground`
  会让本体 QSS 失效 → 背景必须 `paintEvent` 自绘或内部子 widget 兜底。

## 3. 架构

### 3.1 `DropImportMixin` — 新文件 `mf4_analyzer/ui/main_window/_drop_import_mixin.py`

`window.py` 已 127K，不再扩。新建 Mixin，加入 `MainWindow` 继承链，**放在
`QMainWindow` 之前**（让其事件重写在 MRO 中优先）。`window.py` 仅两处改动：

1. 继承列表加 `DropImportMixin`（`window.py:63-65`）。
2. `__init__` 在 `self._init_ui()` 之后加一行 `self._init_drop_import()`
   （此时 `centralWidget()` 已存在，遮罩可挂载）。

Mixin 职责：

```text
_init_drop_import()      # setAcceptDrops(True)；惰性持有 self._drop_overlay=None
dragEnterEvent(e)        # 有 URL 且 ≥1 受支持本地文件 → 显示遮罩 + acceptProposedAction()；否则 ignore()
dragMoveEvent(e)         # 同 dragEnter 的接受判定（保持放下状态）
dragLeaveEvent(e)        # 隐藏遮罩
dropEvent(e)             # 隐藏遮罩；抽取路径 → 过滤 → self._open_paths(paths)；acceptProposedAction()
_dropped_paths(mime)     # mime.urls() → toLocalFile()；保留「存在的文件 且 扩展名受支持」
_has_supported_urls(mime)# dragEnter 判定用；任一受支持即 True
```

- **受支持判定**：扩展名 ∈ 数据扩展名集合 ∪ `{.tlproj}`。集合从
  `_project_io_mixin` 的 `DATA_FILE_GLOB` 解析或单列常量，**单一来源**避免和对话框
  过滤器漂移。
- **不支持 / 目录 / 不存在**：从 `paths` 滤掉；若有被滤掉的，`dropEvent` 末尾
  `toast` 一条「忽略 N 个不支持的文件」，不静默吞。
- 若过滤后 `paths` 为空：不调用 `_open_paths`，只 toast。

### 3.2 `_open_paths(paths)` — 抽取自 `open_files_or_project`

把 `open_files_or_project()` 中**取到 `fps` 之后**的分发体原样抽成
`ProjectIOMixin._open_paths(paths)`。改造后：

```python
def open_files_or_project(self):
    fps, _ = _QFileDialog.getOpenFileNames(self, "打开", "", PROJECT_OR_DATA_FILTER)
    if not fps:
        return
    self._open_paths(fps)

def _open_paths(self, paths):
    # 原 open_files_or_project 的 projects/data_files 拆分 + 替换确认 + 分发，整体搬入
    ...
```

`dropEvent` 与菜单**调用同一个 `_open_paths`**，行为零分叉：拖入单个 `.tlproj`
照样弹替换确认、拖入 ≥2 项目照样拒绝、拖入 blf 照样走 DBC 交互。

### 3.3 `_DropOverlay(QWidget)` — 整窗高亮遮罩

定义在 `_drop_import_mixin.py`（或同包小文件）。父挂 `self.centralWidget()`，覆盖
其全部矩形。

- `setAttribute(WA_TransparentForMouseEvents, True)` — 遮罩**不拦截**拖放事件，
  事件照常冒泡到 `MainWindow.dropEvent`。
- `setAttribute(WA_TranslucentBackground, True)` + **`paintEvent` 自绘**：半透明
  高亮填充（如品牌强调色 ~12% alpha）+ 内描边虚线/实线 + 居中文字「松手导入文件」。
  **不用 QSS background**（铁律②：`WA_TranslucentBackground` 让 QSS 背景失效）。
- 显示前 `setGeometry(centralWidget().rect())` 贴合当前尺寸再 `raise_()`/`show()`；
  `dragLeaveEvent`/`dropEvent` `hide()`。遮罩仅在拖拽期存在，无需常驻 resize 跟随。

## 4. 边界与风险

- **子控件吞 drop**：左侧通道树 `MultiFileChannelWidget` 若开了自身 `acceptDrops`
  （拖动重排），会截走落在其上的 drop。**实现期必查**：若开着，要么放行 URL 类型
  下沉、要么接受「树区域不接 drop、窗口其余区域兜底」。计划中列为显式核查项。
- **macOS 真机渲染**（铁律①）：遮罩外观（半透明色、文字清晰度、是否盖住工具栏/
  圆角面板边缘）必须截图 / 真机验真，单测不算数。计划中单列强制手工验证步骤。
- **`processEvents` 重入**：`_load_one` 内有 `QApplication.processEvents()`；drop 在
  事件循环中触发同步加载属既有模式（菜单也同步加载），保持一致，不额外加线程。

## 5. 测试（pytest-qt，`tests/ui/`）

构造 `QMimeData` 挂 `QUrl.fromLocalFile(...)` + `QDragEnterEvent`/`QDropEvent`
投递到窗口，断言：

1. 受支持文件 drop → `_open_paths` 被调用，且收到过滤后的正确路径（mock/spy
   `_open_paths` 或 `_load_one`）。
2. 不支持扩展名 / 目录 / 不存在路径 → 被过滤，不进入 `_open_paths`。
3. `dragEnter`（含受支持 URL）→ `_drop_overlay.isVisible()` 为真；`dragLeave` /
   `drop` 后为假。
4. `dragEnter`（无受支持 URL，如纯文本/仅 .txt）→ 不接受、遮罩不显示。
5. `.tlproj` 经 drop → 走项目分支（与 `open_files_or_project` 一致，复用既有断言
   思路）。
6. 回归：`open_files_or_project` 抽取 `_open_paths` 后行为不变（现有 smoke/IO 测试
   全绿）。

真机渲染单测覆盖不到 → 见 §4 手工验证。

## 6. 可发现性（可选 follow-up，不绑本 spec）

拖入导入较自明；项目有 `/update-hints` 维护的操作速查面板。是否加一条「拖入文件
即可导入」留作实现完成后的可选 follow-up，由 user 定夺。

## 7. 改动清单

- 新增 `mf4_analyzer/ui/main_window/_drop_import_mixin.py`（`DropImportMixin` +
  `_DropOverlay`）。
- 改 `mf4_analyzer/ui/main_window/window.py`：继承列表加 `DropImportMixin`；
  `__init__` 加 `self._init_drop_import()`。
- 改 `mf4_analyzer/ui/main_window/_project_io_mixin.py`：抽 `_open_paths(paths)`，
  `open_files_or_project` 改为调用它。
- 新增 `tests/ui/test_drop_import.py`。
- `_load_one` 本体不动。
