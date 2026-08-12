# 批处理 BLF 复用单文件 DBC 弹窗 · 执行计划

- **状态**：已完成（聚焦门禁绿）
- **日期**：2026-08-10
- **规格**：`docs/analyzer/specs/2026-08-10-batch-blf-dbc-context-reuse-spec.md`
- **主改**：`_project_io_mixin.py`（薄门面）、`sheet.py`、`input_panel.py`、新测试

---

## T0 · 基线

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_batch_input_panel.py \
  tests/ui/test_batch_drop_import.py \
  tests/test_source_adapters.py \
  tests/ui/test_blf_open.py \
  -q --tb=no
```

## T1 · ProjectIOMixin 门面

```python
def resolve_blf_dbc_paths_for_batch(self, paths) -> list[str] | None:
    """Reuse single-file BLF/DBC tip+picker for BatchSheet disk intake."""
```

按 spec §2.1 / §3.4 分支。不新造对话框。

## T2 · InputPanel context 同步 + disk handler

- `FileListWidget.set_source_context` / `InputPanel.set_source_context`
- `InputPanel.set_disk_paths_handler(cb)`；`_open_disk_dialog` 优先走 cb

## T3 · BatchSheet 编排

- `_add_disk_paths_with_blf_context(paths)`
- `_ensure_blf_dbc_context(paths) -> bool`
- dropEvent / disk handler / `apply_sources`·`apply_files` 中纯磁盘 BLF 走编排

## T4 · 测试 + 门禁

新 `tests/ui/test_batch_blf_dbc_context.py`；跑 T0 集合 + 新文件 + `test_import_boundaries.py`。
