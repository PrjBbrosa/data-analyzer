# 批处理整面板拖放导入 · 设计规格

- **状态**：已实现（2026-08-10；方案 A：共享 `ui/drop_paths.py`）
- **日期**：2026-08-10
- **组件**：`BatchSheet`（整对话框为 drop zone）+ 可选共享 MIME/扩展名过滤
- **参照实现**：`mf4_analyzer/ui/main_window/_drop_import_mixin.py`
- **执行计划**：`docs/analyzer/plans/2026-08-10-batch-drop-import-implementation.md`

---

## 1. 背景

主窗口已支持把本地数据文件拖进 TraceLab：`DropImportMixin` 在整窗
`acceptDrops`，过滤后走 `ProjectIOMixin._open_paths` 全量加载进会话。
批处理对话框（`BatchSheet`）今天只有：

| 入口 | 行为 |
| --- | --- |
| `+ 已加载` | 从主窗 `FileData` 挂行，跳过 probe |
| `+ 从磁盘…` | `QFileDialog` → `FileListWidget.add_disk_path` → 异步 probe |

用户期望与主窗一致：打开批处理面板后，把文件拖到**整个批处理对话框**即可加入
数据文件列表。当前批处理包内无任何 `setAcceptDrops` / `dragEnter` / `dropEvent`。

### 1.1 为什么现在做

- 主窗拖放已稳定（`tests/ui/test_drop_import.py` + lesson
  `docs/lessons-learned/pyqt-drag-event-mimedata-lifetime.md`）。
- 批处理磁盘入口 `add_disk_path` 已处理 pending → probe → 多 `LoadedSource` 拆分、
  重复路径静默跳过、unavailable 行。**业务 sink 已存在**，缺的是 DnD 接线。
- 产品上「打开批处理就能拖文件」是高频操作；强制走文件对话框增加摩擦。

### 1.2 明确非目标（本次不做）

- **不**把 drop 路由到主窗 `_open_paths` / `_load_one`（会污染会话、同步全量 load、
  可能弹出 `.tlproj` 替换确认）。
- **不**支持拖入 `.tlproj` 项目文件。
- **不**递归扫描目录；目录 URL 一律忽略（与主窗一致）。
- **不**改变「已加载」菜单语义；拖入的一律当**磁盘路径**走 probe。
- **不**在 `FileListWidget` 行内单独开 drop（整 `BatchSheet` 足够；子控件未开
  `acceptDrops` 时 Qt 会把事件交给祖先）。
- **不**做文件夹批量导入、网络 URL、剪贴板粘贴。

---

## 2. 范围

### 2.1 本次要做

1. `BatchSheet` 整对话框 `setAcceptDrops(True)`，实现 enter / move / leave / drop。
2. 接受条件：本地文件且后缀 ∈ `DEFAULT_SOURCE_ADAPTER_REGISTRY.supported_extensions`
   （与「从磁盘…」对话框同源，**不含** `.tlproj`）。
3. `drop` 后对每个合法路径调用既有 `FileListWidget.add_disk_path`（顺序与对话框一致）。
4. 拖入时显示半透明遮罩（复用/移植 `_DropOverlay`），文案区分主窗：
   **「松手添加到批处理」**。
5. 运行中（`self._running` / `lock_editing` 后输入区禁用）拒绝 drop。
6. 有被跳过的 URL（目录、不支持扩展名、空路径）时 toast：
   `忽略 N 个不支持的文件`（kind=`warning`），走 `BatchSheet._toast`。
7. 聚焦 pytest：合成 `QDragEnterEvent` / `QDropEvent`（必须 `_mime_ref` 保活）。
8. **可选但推荐**：把 MIME → 路径过滤抽成 UI 中立小 helper，主窗 mixin 与批处理共用；
   主窗仍在过滤结果上并入 `.tlproj` 再交给 `_open_paths`。

### 2.2 本次不做

见 §1.2。亦不改 probe 状态机、preset 序列化、hints/quickref（除非交互文案需要
一条发现性提示——默认可在落地后由 `/update-hints` 补，**本规格不强制**）。

---

## 3. 交互契约

### 3.1 Drop 目标

- **唯一 drop zone**：`BatchSheet` 对话框客户区（含工具栏、三列、页脚）。
- 用户把文件拖到面板任意位置（含输出列、空白）都应可 accept；松手后文件进入
  **输入列**的文件列表，与点「从磁盘…」等价。

### 3.2 Accept / Ignore

| 条件 | dragEnter / dragMove | drop |
| --- | --- | --- |
| 至少一个本地文件且后缀受支持，且未在运行中 | accept + 显示遮罩 | 过滤后 `add_disk_path` |
| 仅有目录 / 仅有不支持扩展名 / 无 URL | ignore | ignore |
| `self._running is True`（含 preview 不强制；**run 锁定后必拒**） | ignore，不显示遮罩 | ignore |
| 混有合法与非法 | accept（因有合法） | 只加合法；toast 跳过数 |

### 3.3 与「从磁盘…」的等价性

对每个 accepted path `P`：

```
batch_sheet._input_panel._file_list.add_disk_path(P)
```

必须与对话框多选后的循环调用产生**相同**状态机行为：

- 重复 canonical path → 静默 return（不 toast、不第二行）
- 支持格式 → `STATE_PATH_PENDING` → 异步 probe → loaded / failed / 多源拆分
- unavailable（如缺 DBC context 的 BLF）→ 可见 unavailable 行 + reason

**禁止**在 drop 路径上绕开 `add_disk_path` 手写第二套 probe。

### 3.4 遮罩

- 父控件：`BatchSheet` 自身（或对话框根布局宿主），几何 = 对话框 `rect()`，
  `raise_()` 盖住内容。
- `WA_TransparentForMouseEvents` + 半透明蓝底 + 虚线圆角框（对齐主窗 overlay）。
- 文案：**「松手添加到批处理」**（主窗仍为「松手导入文件」）。
- `dragLeave` / `drop` 后立即隐藏。

### 3.5 Toast

| 场景 | 文案 | kind |
| --- | --- | --- |
| drop 中有 ≥1 个 URL 被过滤掉 | `忽略 N 个不支持的文件` | warning |
| 全部合法、仅有重复跳过 | **不** toast（保持 `add_disk_path` 静默语义） | — |

---

## 4. 架构与复用

### 4.1 数据流（正确）

```
OS drop → BatchSheet.dropEvent
       → filter local files by registry.supported_extensions
       → for path in paths: FileListWidget.add_disk_path(path)
       → existing probe / multi-source expansion
```

### 4.2 数据流（禁止）

```
OS drop → MainWindow._open_paths / _load_one   ❌
OS drop → 手写 QThreadPool probe 旁路          ❌
```

### 4.3 共享过滤（推荐形态）

新建薄模块，例如：

`mf4_analyzer/ui/drop_paths.py`（或 `ui_kit` 下同等位置——**不得**让
`ui_kit` import `ui` / `acquisition_ui`，故优先放 `ui/`）：

```python
def iter_local_file_urls(mime) -> list[str]: ...
def filter_existing_files(paths, *, suffixes: set[str]) -> list[str]: ...
```

- 主窗：`suffixes = registry_exts | {".tlproj"}`，再 `_open_paths`
- 批处理：`suffixes = set(registry.supported_extensions)`，再 `add_disk_path`

`_DropOverlay` 可：

- **A**：抽到共享模块，构造时传入文案；或
- **B**：批处理内复制一小段 paint（接受轻微重复，改动面更小）

本规格允许 A 或 B；执行计划默认走 **A（文案参数化）**，若抽公共件触及主窗测试面过宽可降为 B。

### 4.4 模态与主窗双 drop 目标

`BatchSheet` 是 `setModal(True)` 的 `QDialog`。打开时主窗通常收不到 drag。
仍要求：批处理自己 `acceptDrops`，**不**依赖主窗转发。关闭对话框后主窗拖放行为不变。

---

## 5. 错误与边界

| 输入 | 行为 |
| --- | --- |
| 空 `QMimeData` / 无 urls | ignore |
| 远程 URL（无 local file） | 忽略该 URL |
| 路径存在但是目录 | 忽略 |
| 路径不存在 | 忽略（与主窗 `_dropped_paths` 的 `is_file()` 一致） |
| 后缀大小写 | 一律 `.lower()` 比较 |
| 运行中 drop | ignore，无遮罩 |
| 关闭对话框过程中 | 无额外要求；标准 Qt 销毁即可 |

编程错误（例如 `add_disk_path` 抛意外）**不得**用宽泛 `except Exception: pass`
吞掉；沿用现有 `add_disk_path` 内部对 unsupported 的可见处理。

---

## 6. 测试契约

新文件建议：`tests/ui/test_batch_drop_import.py`（或并入既有 batch sheet 测试模块）。
合成事件必须 `event._mime_ref = mime`（见 lessons）。

最低用例：

1. `BatchSheet.acceptDrops() is True`
2. 支持后缀（如 `.csv` / `.mf4`）`dragEnter` → accepted + overlay 可见
3. 仅目录 / 仅 `.txt` → ignored + 无 overlay
4. `.tlproj` → **ignored**（与主窗差异的硬回归）
5. `drop` 多个合法路径 → 对 `_file_list.add_disk_path` 的调用序列等于路径列表
   （monkeypatch 捕获；或断言 list 行数 / paths）
6. `drop` 合法+非法混搭 → 只加合法 + toast 含「忽略」
7. `_running = True` 时 enter/drop → ignored
8. 重复 path drop 两次 → 仍只有一行（沿用 `add_disk_path` 去重）

主窗 `tests/ui/test_drop_import.py`：若抽了共享 helper，既有用例须保持全绿；
勿放宽主窗对 `.tlproj` 的接受。

---

## 7. 验收标准

- [ ] 批处理对话框打开后，拖入受支持数据文件，文件列表出现与「从磁盘…」相同的 pending/loaded 行为
- [ ] 拖入过程有「松手添加到批处理」遮罩；离开或放下后消失
- [ ] 不支持项被忽略并 toast；目录不递归
- [ ] 不接受 `.tlproj`；不调用 `_open_paths`
- [ ] 运行中无法通过拖放添加文件
- [ ] 聚焦测试全绿；主窗拖放回归全绿
- [ ] 不引入 `ui_kit → ui` 反向依赖；不把实现塞进 `batch_render` / `signal/` 等中立层

---

## 8. 工作量与风险

| 项 | 估计 |
| --- | --- |
| 规模 | **S**（只接 `BatchSheet` + 测试）；抽共享 helper 仍为 **S–M** |
| 主风险 | 合成 DnD 事件 MIME 生命周期；运行中误 accept；误接 `_open_paths` |
| 非风险 | probe / 多源拆分（已有路径） |

---

## 9. 文档扇出

- 本规格 + 执行计划（本次必交）。
- **不**因本功能单独升 `APP_VERSION`（小交互增强，跟进下一次常规版本说明即可）。
- 用户指南 / help：非必须；若本迭代顺手，可在批处理「数据文件」小节加一句
  「可将文件拖入批处理面板」。
