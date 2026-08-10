# FRF 非均匀真实时间轴 — 自动恢复实施计划

日期：2026-08-10

状态：**实施中（自动重建，无弹窗选 Fs）**

规格：`docs/analyzer/specs/2026-08-10-frf-nonuniform-time-axis-recovery-spec.md`

## 1. 任务

### Task 1 — GUI：选中范围不均匀时自动 `rebuild_time_axis`

- `_frf_prepare_pair_samples`：mask 后若不均匀 → 对该 fid 自动重建一次 → 重跑 prepare（帽=1）
- toast + statusBar（spec D3）
- 更新/改写原「选中范围内抖动应 raise」测试为「自动重建后可构建 candidate」

### Task 2 — Batch：`prepare_frf_task` 本地均匀化 + warning

- 抖动超限：`time/fs` 换为 `arange/suggested`；`PreparedBatchFrf.warnings` 记录
- `batch.py` 合并 `prepared.warnings`
- 更新原 expect-raise 的 Batch 测试

### Task 3 — 帮助一句 + 原 FRF spec 交叉引用已存在则同步「自动」措辞

### Task 4 — 回归

`pytest tests/ui/test_frf_main_window.py tests/test_batch_frf_export.py tests/test_frf.py -q`

## 2. 完成记录

| 项 | 记录 |
| --- | --- |
| 自动化 | `tests/test_batch_frf_export.py` + 关键 UI 自动重建用例通过；`tests/test_frf.py` 全绿 |
| DaXiaoQiu | Batch `prepare_frf_task` 自动重建后可 `compute_prepared_frf` |
| 行为 | GUI/Batch 均自动按建议 Fs 重建，无弹窗选 Fs |
