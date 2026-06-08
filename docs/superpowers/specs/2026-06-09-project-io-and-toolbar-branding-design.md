# 设计方案：项目保存/加载（底层）+ 工具栏品牌化改版

- **日期**：2026-06-09
- **状态**：已评审，待写实现计划
- **涉及版本**：TraceLab v6.5
- **来源**：用户口头需求 + 可视化伴侣 mockup 对齐（`.superpowers/brainstorm/60093-1780927006/`）

---

## 1. 背景与目标

本次包含两条**相互独立**的工作线，捆在一起是因为同属一批 v6.5 体验改进：

- **工作线 A — 项目保存/加载（本轮只做底层）**：把「当前打开的文件 + 各 View 的内容」存成可复现的项目文件，下次能恢复现场。
- **工作线 B — 工具栏品牌化改版**：Cockpit 按钮迁移；原 Cockpit 位置放 BOSCH Logo；新增「更新」入口（图标，跳转飞书发布页）。

两条线没有共享代码，可独立实现、独立验收。

---

## 2. 范围

**本轮做：**
- A：序列化底层（`project_io` 模块）+ `MainWindow.save_project()/open_project()` 方法，可被代码/单测调用。
- B：Cockpit 迁移 + Logo + 底部状态栏更新图标，全部接线可用。

**本轮明确不做（用户决定延后）：**
- A 的 **UI 入口**（菜单项/按钮/快捷键）——入口位置用户尚未想好，先把底层打磨稳。`save_project()/open_project()` 先不接任何可见入口，仅留方法 + 单测。

---

## 3. 工作线 A — 项目保存/加载（底层）

### 3.1 关键决策
- **只存引用**：项目文件只记录原文件路径 + 每文件的手改设置（`fs`、时间轴来源等）+ 全部 View 状态。加载时重新读原文件。
- **手动文档模型**：显式 `save_project(path)` / `open_project(path)`，文件类型 `.tlproj`（JSON，带版本号）。不做自动会话恢复。

### 3.2 文件格式 `.tlproj`
```jsonc
{
  "format": "tracelab-project",
  "version": 1,
  "active_file": "f0",                 // 当前活跃文件 fid，可为 null
  "current_mode": "time",              // time | fft | fft_time | order
  "files": [
    {
      "fid": "f0",
      "path_abs": "/abs/path/a.mf4",
      "path_rel": "data/a.mf4",        // 相对 .tlproj 的路径，便于整包搬移
      "fs": 1000.0,
      "time_source": "auto",           // auto | column | generated | manual
      "time_column": null              // time_source==column 时的列名，否则 null
    }
  ],
  "views": [ /* 原样复用 ViewState.to_dict() 产物 */ ],
  "view_manager": { "active": 0, "split_pairs": { "0": 1 } }
}
```

要点：
- `views[]` **直接复用** `ui/view_state.py` 既有的 `ViewState.to_dict()/from_dict()`（含 ChannelKey、colors、xlim/ylims 的 JSON 编解码），不重造。
- `fid` 必须按原顺序写回，且 `open_project` 重建时沿用相同 fid，否则 view 里 `(fid, ch)` 引用对不上。

### 3.3 新模块 `mf4_analyzer/project_io.py`
仿现有 `mf4_analyzer/batch_preset_io.py`（`SCHEMA_VERSION` + `save_*_to_json` / `load_*_from_json`），纯序列化、无 Qt 依赖、可单测：

```python
SCHEMA_VERSION = 1

@dataclass
class ProjectFileRef:
    fid: str
    path_abs: str
    path_rel: str | None
    fs: float
    time_source: str
    time_column: str | None = None

@dataclass
class ProjectDocument:
    active_file: str | None
    current_mode: str
    files: list[ProjectFileRef]
    views: list[dict]                  # ViewState.to_dict() 原样
    view_manager: dict                 # {"active": int, "split_pairs": {...}}

def save_project_to_json(doc: ProjectDocument, path: Path) -> None: ...
def load_project_from_json(path: Path) -> ProjectDocument: ...   # 版本不符抛明确异常
def resolve_file_path(ref: ProjectFileRef, project_path: Path) -> Path | None:
    """先按 path_rel 相对 project 找，再退 path_abs；都不存在返回 None。"""
```

### 3.4 `MainWindow` 两个方法（`ui/main_window.py`）
- `save_project(path)`：
  1. 先把**当前活跃 View 的实时状态**回灌到对应 `ViewState`（复用 `ui/view_bridge.py` 的 `capture_view`/`capture_*` 系列），避免活跃 view 的 canvas 范围未同步。
  2. 从 `self.files`（OrderedDict，`io/file_data.py`）取每文件的 `filepath/fs/_time_source` 拼 `ProjectFileRef`，计算相对 `path` 的 `path_rel`。
  3. 收集 `view_manager.views`（`to_dict()`）、`active`、`_split_pairs`、`_active`、当前 mode → `ProjectDocument` → `save_project_to_json`。
- `open_project(path)`：
  1. `load_project_from_json` → 逐个 `resolve_file_path`。
  2. 对找得到的文件复用现有加载流程（`_load_one`，line ~1299），**沿用文件里记录的 fid**；恢复 `fs/time_source`。
  3. `ViewState.from_dict` 重建 views 灌进 `view_manager`，恢复 `split_pairs/active`；引用到缺失文件的通道自动忽略。
  4. 切到 `active_file` 与 `current_mode`，`apply_view` 刷新活跃 view。

### 3.5 缺文件处理（v1）
- 解析顺序：`path_rel`（相对 .tlproj）优先 → `path_abs` 兜底。
- 找不到的文件：**收集后统一弹窗**「以下文件找不到，将跳过：…」，能加载的照常加载，相关通道在 view 里忽略。
- 「重新定位/relocate」留后续，不在本轮。

### 3.6 测试（`tests/`，pytest）
- `project_io` 往返：构造 `ProjectDocument` → save → load → 字段逐一相等。
- 版本不符：`version: 999` → 抛明确异常。
- `resolve_file_path`：相对优先、绝对兜底、都缺返回 None 三种分支。
- `MainWindow.save_project/open_project` 往返（用 Qt 测试夹具 + 临时 mf4/csv）：打开文件 + 建几个 view + 改 fs/range → save → 新窗口 open → files/views/active/mode 一致。
- 缺文件加载：删掉一个被引用文件 → open 不崩、弹警告、其余正常。

---

## 4. 工作线 B — 工具栏品牌化改版

### 4.1 Cockpit 迁移（`mf4_analyzer/ui/toolbar.py`）
- 现状：`btn_acquisition_cockpit`（line ~35-37 定义）在右段 `right` 布局（`right.addWidget`, line ~93）。
- 改为：从右段移到左段 `left` 布局「批处理」（`btn_batch`, line ~61）之后。
- 信号 `acquisition_cockpit_requested`（line 19）、连接（line ~132）、handler `MainWindow.open_acquisition_cockpit`（line ~1281）**全部不变**。
- 图标尺寸同步循环（line ~49-53）保持包含该按钮。

### 4.2 BOSCH Logo（占原 Cockpit 的右上带）
- **资源**：用裁掉白边的**完整版** BOSCH 标识（圆标 + BOSCH + 中文公司名），新增 `assets/branding/bosch_hasco_logo.png`；并备一张**透明底**版本 `bosch_hasco_logo_alpha.png` 兜底（工具栏非纯白时防露白块）。
  - 原图 2000×500，裁白边后约 1860×171（≈10.9:1）。
- **打包**：`tools/build_windows_folder.ps1` 仿现有 `assets\icons` 那行（line ~105/154），加一行
  `--add-data "<RepoRoot>\assets\branding;assets\branding"`。
- **控件**：右段 `right` 布局放一个 `QLabel`，`setPixmap` 缩放到**宽 190px**（高按比例 ≈18px），右对齐，所在容器宽 ≈215px（≈Inspector 列宽）留呼吸感。中文全称放进 `tooltip`（后续可挪「关于」弹窗）。
- 透明底优先加载 alpha 版；工具栏背景为纯白时两者视觉等价。

### 4.3 更新图标（底部状态栏右角，`mf4_analyzer/ui/hints.py`）
- 底部提示栏由 `ui/hints.py` 构建（"Ctrl + 滚轮 缩放 X" 等 chip）。在该栏**最右端**追加：
  - 一个 `QToolButton`：**云下载图标、无文字**，`toolTip="检查更新"`，`cursor=PointingHand`。
  - 紧邻一个小号 `QLabel` 显示版本号 `v6.5`（灰色）。
- 图标：自绘 SVG/QPainter 风格的「云 + 向下箭头」，挂进 `ui_kit/icons.py`（`Icons.cloud_download()`），与现有编程式图标体系一致。
- 行为：点击 → `QDesktopServices.openUrl(QUrl(RELEASE_URL))`（模式同 `acquisition_ui/history_tab.py:479`）。
- **`RELEASE_URL`**：飞书发布页
  `https://jcnubq178nzc.feishu.cn/wiki/LkfAwEotfiSO6GktmPvcYPRznhd`
  做成单一易改常量（建议 `mf4_analyzer/app_meta.py` 里 `RELEASE_URL` + `APP_VERSION`，版本号也从这里取，避免散落）。

### 4.4 验证（B 全是视觉/原生渲染，必须看真实结果）
- 真机/截图核对：Cockpit 在「批处理」右侧；Logo 在右上带、宽度略窄于 Inspector、不糊不溢出、无白底色块；底部右角云下载图标 + 版本号；点击图标确实拉起浏览器打开飞书链接。
- 嵌入的 Logo 容器与更新按钮容器若是自定义 QWidget，背景必须透明（QSS transparent + `WA_TranslucentBackground`），不留默认灰底。

---

## 5. 待办 / 占位
- A 的 UI 入口（菜单/按钮/快捷键）——延后，待用户定位置。
- BOSCH 透明底 PNG 由白底原图生成（near-white→透明，注意别吃掉银色圆标）。

## 6. 不在本轮范围
- 项目文件「内嵌数据 / 打包副本」模式（本轮只做「只存引用」）。
- 更新的「版本比对 / 自动检测 / 角标提醒」（本轮只做纯链接跳转）。
- A 的缺文件「重新定位」。

---

## 7. 实现分工提示（供写计划时参考）
- 工作线 B 属 `pyqt-ui-engineer`（工具栏/状态栏/图标/资源）。
- 工作线 A 的 `project_io.py` 为纯序列化；`MainWindow` 接线偏 UI 集成。两线可并行。
