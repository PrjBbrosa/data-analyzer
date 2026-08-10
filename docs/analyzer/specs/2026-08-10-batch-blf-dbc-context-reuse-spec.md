# 批处理 BLF 复用单文件 DBC 弹窗 · 设计规格

- **状态**：已实现（2026-08-10）
- **日期**：2026-08-10
- **组件**：`BatchSheet` 磁盘/拖放进件 + `ProjectIOMixin` 既有 BLF/DBC 提示与选择路径
- **执行计划**：`docs/analyzer/plans/2026-08-10-batch-blf-dbc-context-reuse-implementation.md`

---

## 1. 背景

主窗打开 / 拖入 `.blf` 已有完整链路：自动候选提示 → 确认/手选 DBC → 不匹配重试 →
`DataLoader.load_blf(..., dbc_paths=…)`。批处理磁盘进件虽已把 `.blf` 列入
`supported_extensions`，但 `source_context` 默认为空，adapter 要求
`dbc_paths`，于是行直接 `unavailable`（「BLF 需要 DBC 解码上下文…」），**从不 probe**。

用户期望：批处理加载与单文件加载**共用同一套弹窗和提示路径**，不要在批处理里再造一版
DBC UI。

### 1.1 为什么现在做

- 解码与 probe 能力已在 `SourceAdapter(key="blf")` / `DataLoader` 就绪。
- `BatchSheet._source_context` → `InputPanel` → `BatchRunner` 的上下文管道已存在，只缺写入。
- 「+ 已加载」对主窗已解码的 BLF 可用，磁盘/拖放路径是缺口。

### 1.2 非目标

- **不**在 `BatchSheet` / `InputPanel` 内复制 `QMessageBox` / `QFileDialog` 文案或候选逻辑。
- **不**把 raw CAN 帧当作批处理信号来源（与单文件 UI、adapter 一致）。
- **不**在本轮做「每个磁盘 BLF 行独立 DBC」的 runner 改造（仍是 sheet 级一份
  `source_context["dbc_paths"]`）。
- **不**把 DBC 写入 recipe/preset JSON（会话上下文；重开方案若只有 `source_paths` 再提示）。
- **不**升版本号 / 改 help（小接线增强，跟下次常规说明即可）。

---

## 2. 范围

### 2.1 要做

1. 在 `ProjectIOMixin` 增加**薄公开门面**，只编排既有私有方法：
   - 1 个 BLF → `_resolve_blf_dbc_paths`（与单文件打开同一提示/候选/手选/重试）
   - ≥2 个 BLF → `_ask_blf_batch_dbc_action`；`batch` → `_choose_blf_dbc_with_retry(首文件)`；
     `individual` → 对**第一个** BLF 走 `_resolve_blf_dbc_paths`（sheet 共用一套 DBC）；
     取消 → `None`
2. `BatchSheet` 在磁盘多选、拖放、以及会调用 `add_disk_path` 的恢复路径上，对新增
   `.blf` **先**解析 DBC 写入 `_source_context`，再 `add_disk_paths`。
3. `InputPanel` / `FileListWidget` 支持更新 `source_context`（probe 与 availability 同源）。
4. 取消 DBC 时：不加入任何本次待加的 `.blf`；同批非 BLF 文件仍可加入；toast 说明已取消。
5. 聚焦测试：mock 门面 / mixin 方法，断言 context 写入与 `add_disk_path` 在 ready 后 probe。

### 2.2 不做

见 §1.2。不改 `blf_dbc_candidates.py` 纯函数、不改 loader 解码语义。

---

## 3. 交互契约

### 3.1 触发点

| 入口 | 行为 |
| --- | --- |
| `+ 从磁盘…` 多选含 `.blf` | 先 DBC 门面，再 `add_disk_paths` |
| 整面板拖放含 `.blf` | 同上 |
| `apply_sources` / `apply_files` 仅磁盘 `.blf` 路径 | 同上（无主窗 FileData） |
| `+ 已加载`（主窗已解码 BLF） | **不**弹 DBC（现状保留） |

### 3.2 已有 context

若 `_source_context` 已有非空 `dbc_paths`，本次新增 BLF **不再弹窗**，直接 probe；
不匹配的文件走既有 `probe_failed` / 错误行，不静默吞掉。

### 3.3 取消

门面返回 `None` → 本次路径列表中的 `.blf` 全部跳过；toast：
`已取消 BLF 的 DBC 选择`（kind=`info`）。同批其它扩展名照常添加。

### 3.4 多文件「逐个选择」

主窗 `individual` 会对每个 BLF 单独 `_load_one`（各自 FileData 自带 DBC）。
批处理 sheet 只有一份 `source_context`，本轮约定：`individual` 用**第一个** BLF 的
`_resolve_blf_dbc_paths` 结果作为整表上下文，随后所有待加 BLF 共用。规格写清，避免
误以为已支持混总线多 DBC。

---

## 4. 架构

### 4.1 数据流（正确）

```
磁盘/拖放 paths
  → BatchSheet 筛出待加 .blf
  → parent.resolve_blf_dbc_paths_for_batch(blf_paths)   # ProjectIOMixin 门面
        → 既有 _resolve_blf_dbc_paths / _ask_blf_batch_dbc_action / …
  → sheet._source_context["dbc_paths"] = resolved
  → InputPanel.set_source_context(...)
  → FileListWidget.add_disk_path → availability ready → probe_blf_dbc
  → Run: BatchRunner(..., source_context=sheet._source_context)
        → load_sources(..., context) → load_blf(dbc_paths=…)
```

### 4.2 禁止

```
BatchSheet 内新建 QFileDialog「选 DBC」     ❌
跳过 DBC 把 raw CAN 当通道                 ❌
只改 probe、Run 时仍空 context             ❌
```

### 4.3 无 MainWindow parent

测试/`parent is None`：无门面时，对 `.blf` toast 说明无法选择 DBC 并跳过；非 BLF 不受影响。
不在无 parent 时假装 ready。

---

## 5. 测试契约

新建或扩展：`tests/ui/test_batch_blf_dbc_context.py`（名称可微调）。

最低用例：

1. 单 BLF + mock `resolve_blf_dbc_paths_for_batch` → context 含 dbc → 行进入 probe/loaded（非 unavailable）
2. 取消门面 → BLF 不入列；同批 `.csv` 仍入列
3. 已有 context 时再次加 BLF → **不再**调用门面
4. drop / `add_disk_paths` 都走同一 `_add_disk_paths_with_blf_context` 编排
5. `BatchRunner` 构造拿到的 `source_context` 含同一 `dbc_paths`（可用 sheet._make_runner 断言）

既有：`test_limited_source_row_exposes_reason_and_never_runs_probe`、
`test_blf_without_dbc_context_is_limited…` 保持语义（空 context 仍 limited）。

---

## 6. 验收

- [ ] 批处理「从磁盘」或拖入 `.blf`，出现与主窗同类的 DBC 提示/选择；选完后文件可 probe
- [ ] 取消则不加入该批 BLF
- [ ] Run/Preview 能 `load_blf` 成功（同源 context）
- [ ] 无第二套 DBC 对话框实现
- [ ] 聚焦测试全绿；`test_import_boundaries` 仍绿

---

## 7. 工作量

| 项 | 估计 |
| --- | --- |
| 规模 | **S–M**（门面 + sheet 编排 + context 同步 + 测试） |
| 主风险 | 多 BLF individual 语义与主窗不完全同构（已在 §3.4 写明） |
| 非风险 | 解码本身、已加载路径 |
