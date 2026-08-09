# 批处理整面板拖放导入 · 执行计划

- **状态**：已完成（2026-08-10；门禁 152 passed）
- **日期**：2026-08-10
- **设计规格**：`docs/analyzer/specs/2026-08-10-batch-drop-import-spec.md`
- **参照**：`mf4_analyzer/ui/main_window/_drop_import_mixin.py`、
  `tests/ui/test_drop_import.py`、
  `docs/lessons-learned/pyqt-drag-event-mimedata-lifetime.md`
- **主改文件**：`mf4_analyzer/ui/drawers/batch/sheet.py`；可选
  `mf4_analyzer/ui/drop_paths.py` + `_drop_import_mixin.py`

改动面小：接线 + 过滤复用 + 聚焦测试。业务 sink（`FileListWidget.add_disk_path`）
**禁止重写**。

---

## 第 0 步 · 取基线（动手前必做）

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_drop_import.py tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_input_panel.py -q --tb=no
```

记下 pass/fail。后续只拿「本次新增/改动」相关失败算自己的账。

---

## 第 1 步 · 抽出共享路径过滤（推荐，可与第 2 步同 PR）

**新建** `mf4_analyzer/ui/drop_paths.py`（注意：放在 `ui/`，不要放进 `ui_kit/`，
避免任何新的跨层诱惑；本文件只依赖 `pathlib` + Qt `QMimeData`/`QUrl`）。

```python
def iter_local_paths(mime) -> list[str]:
    """Return local filesystem paths from mime URLs (may include dirs)."""

def filter_drop_files(paths, *, suffixes: set[str]) -> list[str]:
    """Keep existing files whose suffix.lower() is in suffixes."""
```

**改** `_drop_import_mixin.py`：

- `SUPPORTED_DROP_EXTS` 仍可由 `DATA_FILE_GLOB` ∪ `{.tlproj}` 构成。
- `_has_supported_urls` / `_dropped_paths` 改为调用共享函数。
- `_DropOverlay`：给 `__init__` 增加可选 `message: str = "松手导入文件"`，
  `paintEvent` 画传入文案。为减少循环依赖，可将 `_DropOverlay` 一并挪到
  `drop_paths.py`（或 `ui/drop_overlay.py`）；若移动，更新 mixin 导入与
  `test_drop_import.py` 中若有直接引用。

**验证**：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_drop_import.py -q
```

必须全绿。若抽公共件导致导入边界变复杂，允许降级：本步取消，第 2 步在
`sheet.py` 内联过滤 + 复制 overlay（spec §4.3 方案 B）。

---

## 第 2 步 · BatchSheet 接线

**文件**：`mf4_analyzer/ui/drawers/batch/sheet.py`

在 `__init__` 布局与信号连接完成后（与其它 `_init_*` 对称的位置）调用：

```python
self._init_drop_import()
```

实现（可作 `BatchSheet` 方法，不必新建 mixin，除非文件已过长需对称抽取）：

1. `self.setAcceptDrops(True)`
2. `self._drop_overlay = None`（懒创建）
3. `dragEnterEvent` / `dragMoveEvent`：
   - 若 `self._running`: `event.ignore()`；return
   - 若存在至少一个合法数据文件 URL：`acceptProposedAction()` + show overlay
   - 否则 ignore
4. `dragLeaveEvent`：hide overlay；`super().dragLeaveEvent(event)`
5. `dropEvent`：
   - hide overlay
   - 若 running：ignore；return
   - `paths = filter_drop_files(..., suffixes=set(self._source_registry.supported_extensions))`
   - `total` = 本地 URL 数（与主窗一致，用于 skipped 计数）
   - 对每个 path：`self._input_panel._file_list.add_disk_path(path)`
     （若 `InputPanel` 已有薄封装 `add_disk_paths` / 公开 API，优先用公开面；
     **不要**为了「封装」再写第二套 probe）
   - 有 paths 则 accept；否则 ignore
   - `skipped = total - len(paths)`；`skipped > 0` 时
     `self._toast(f"忽略 {skipped} 个不支持的文件", kind="warning")`

扩展名集合：

```python
suffixes = {ext.lower() for ext in self._source_registry.supported_extensions}
# supported_extensions 已带点号（如 ".mf4"）；确认后统一 lower
```

**禁止**：

- `self.parent()._open_paths(...)` 或任何主窗 load 路径
- 接受 `.tlproj`
- 宽泛 `except Exception: pass`

遮罩父控件用 `self`（对话框），`setGeometry(self.rect())`；可在
`resizeEvent` 里若 overlay 可见则同步几何（主窗挂在 centralWidget，批处理更简单；
若缺省也能 cover，可省略 resize 同步，但建议加一行）。

**可选薄封装**（非必须）：`InputPanel.add_disk_paths(paths)` 循环调用
`self._file_list.add_disk_path`，让 sheet 不触及 `_file_list` 私有属性。

---

## 第 3 步 · 测试

**新建** `tests/ui/test_batch_drop_import.py`。

复用 `test_drop_import.py` 的 `_mime` / `_enter` / `_drop` 模式（含 `_mime_ref`）。
构造 `BatchSheet` 时必须注入隔离 `prefs_store`（见 `BatchSheet.__init__` docstring），
并提供最小 `files={}` / parent。参考既有 `tests/ui/test_batch_*.py` 的 sheet 夹具。

用例清单对齐 spec §6。对 `add_disk_path` 的断言优先 monkeypatch：

```python
calls = []
monkeypatch.setattr(sheet._input_panel._file_list, "add_disk_path",
                    lambda p: calls.append(p))
```

这样不依赖真实 probe / 样本文件内容（只需 `tmp_path` 下 `is_file()` 为真的空文件）。

运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_batch_drop_import.py tests/ui/test_drop_import.py -q
```

---

## 第 4 步 · 收尾门禁

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_batch_drop_import.py \
  tests/ui/test_drop_import.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_import_boundaries.py \
  -q
```

若改了 `ui/` 新模块的导入方向，确认 `test_import_boundaries.py` 仍绿。

**不做**：全量 5600 除非用户要求；真机 Cocoa 拖放目测可作为人工验收，不阻塞合并。

---

## 任务拆分（给执行 agent）

| Task | 内容 | 完成定义 |
| --- | --- | --- |
| T0 | 跑基线，记录结果 | 命令输出保留在回复或 `.state/` |
| T1 | 共享 `drop_paths`（或记录降级为 B） | `test_drop_import` 全绿 |
| T2 | `BatchSheet` acceptDrops + overlay + drop→`add_disk_path` | 手工逻辑就位 |
| T3 | `test_batch_drop_import.py` 覆盖 spec §6 | 新测试全绿 |
| T4 | 门禁命令 + 简短实现说明 | 回复含验证命令与结果 |

---

## 非目标再确认

- 不升版本号、不改 help/user-guide（除非顺手一句）。
- 不改 `FileListWidget` 状态机。
- 不实现目录递归。
- 不把 drop 接到「已加载」语义。

---

## 基线记录（执行时填写）

```
日期：2026-08-10
T0 基线：137 passed（test_drop_import + test_batch_smoke + test_batch_input_panel）
T4 门禁：152 passed（含 test_batch_drop_import + test_import_boundaries）
方案：A（共享 drop_paths + 参数化 DropOverlay）
```
