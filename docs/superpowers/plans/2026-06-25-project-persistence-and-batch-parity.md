# 实现计划：项目滤波持久化 + 批处理全面板对齐

- 日期：2026-06-25
- 设计：`docs/superpowers/specs/2026-06-25-project-persistence-and-batch-parity-design.md`
- 方法：TDD（先红后绿）；UI 改动须验真渲染；每个任务自带回归测试
- 专家路由（CLAUDE.md squad）：`signal-processing-expert`(SP) · `pyqt-ui-engineer`(UI) · `refactor-architect`(RA)

> 基线：跑前先记全量 pytest 基线（全量套有 ~10 个计时 flaky，见 `project-fullsuite-baseline-flaky-tests`），用 git-stash 同环境对比判回归。

---

## 阶段一：滤波持久化（项目级全局）

### T1 — FilterSpec 序列化 + 项目 schema v2 + 迁移〔SP 或 RA〕
- **改**：
  - `signal/filters.py`：`FilterSpec.to_dict()/from_dict()`（含字段缺省兜底；band 双截止）。
  - `ui/project_io.py`：`ProjectDocument` 加 `filter: dict | None = None`；`save_project_to_json` payload 加 `"filter"`；`SCHEMA_VERSION=2`；`load_project_from_json` 接受 `version∈{1,2}`，v1 迁移为 `filter=None`，未知高版本仍拒绝。
- **测**（先写）：
  - `to_dict/from_dict` 四种 kind 往返。
  - 加载 v1 旧 fixture（无 filter）→ `filter is None`、不抛。
  - 加载 v2（含 filter）→ 还原等值。
- **交付字段**：`tests_before/after`、`files_changed`。
- **依赖**：无。

### T2 — save/open 接线 + 时域重绘 + 缓存键〔UI〕
- **改**：
  - `_project_io_mixin.py:save_project`：从 `inspector.filter_panel` 读 `enabled/spec/show_*` → `doc.filter`。
  - `_project_io_mixin.py:open_project`：读 `doc.filter` → 依次 `set_kind/set_cutoff/set_band/set_order/set_enabled` + 显示开关；恢复后若时域模式触发重绘；恢复路径经 `nyquist_guard` 钳制越界 cutoff。
  - `window.py` 时域绘制缓存键纳入 `FilterSpec+enabled`（核对 `_plot_time_on_canvas` 现有键，缺则补）。
- **测**（先写）：
  - 端到端往返：设滤波（启用+band+自定义截止+关 show_original）→ save → 新建窗口 open → 断言 `filter_spec()` 全等 + 开关；用 `pytest-qt`。
  - 恢复后重绘命中新缓存（不显示未滤波旧曲线）。
  - 越界 cutoff（新数据 nyquist 更低）恢复后被钳制、不报错。
- **依赖**：`depends_on: [T1]`。
- **验真**：截图确认恢复后时域图出现滤波叠加曲线。

---

## 阶段二：批处理全面板对齐（含 A 计权 · 核心，无算法风险）

### T3 — 参数透传（止血「填入/导入」丢参数）〔UI 或 RA〕
- **改**：`ui/drawers/batch/sheet.py`
  - `BatchSheet` 加 `self._passthrough_params`；`apply_preset` 记录非（可见字段∪轴∪rpm）的 key；切方法时按方法白名单清理无关 key。
  - `get_preset()` 合并顺序：`{**_passthrough_params, **form_params, **axis_params, **rpm_params}`（+ time_range），表单/轴/rpm 覆盖 passthrough。
- **测**（先写）：
  - FFT「填入当前」weighting=A → `get_preset().params['weighting']=='A'`。
  - 覆盖序：对话框改 window 后 window 取表单值、weighting 仍保 A。
  - mock `BatchRunner._compute_fft_dataframe` 断言收到 `weighting='A'`（端到端透传）。
- **依赖**：无（与 T1/T2 并行）。

### T4 — 暴露 weighting 下拉（三方法）〔UI〕
- **改**：`ui/drawers/batch/method_buttons.py`
  - `_METHOD_FIELDS` 三方法加 `"weighting"`；`DynamicParamForm` 加「计权」`QComboBox`；`get_params/apply_params` 加分支。
  - 取值集合**以主面板 `combo_weighting` 为准**（实现时读主面板 items，勿硬编码漂移）。
- **测**（先写）：weighting 下拉往返（三方法）；可见字段集随方法切换正确。
- **依赖**：`depends_on: [T3]`（weighting 成为可见字段后从 passthrough 转交表单，避免逻辑打架）。
- **验真**：批处理对话框三方法下都能看到并选「计权」。

### T5 — fft_time 的「从当前填入」分支〔UI〕
- **改**：`window.py:_build_current_batch_preset` 加 `mode=='fft_time'` 分支（单信号 `fft_time_ctx.current_signal()` + `get_params()` + fs + time_range → `from_current_single(method='fft_time')`）。
- **测**（先写）：fft_time 模式 `_build_current_batch_preset()` 非 None、信号/参数正确；空信号返回 None；与 `open_batch` 失效检测兼容。
- **依赖**：无（可与 T3 并行；建议 T3 先合以便端到端验证透传含 fft_time 的 weighting）。

### T6 — preset JSON weighting 回归测试〔UI/SP〕
- **改**：仅加测试（`batch_preset_io` 已整存 params）。
- **测**：构造含 weighting 的 preset → save→load → weighting 不丢；顺带覆盖三方法。
- **依赖**：无。

---

## 阶段三（可选 · 需用户单独 green-light）：完全数值对齐

> 仅当要求「批处理结果与屏幕单次像素级等同」时启动；动 signal 核心，必须 TDD。

### T7 — FFT dB 出图〔SP〕
- `batch.py:_build_export_scene` 的 `kind=='fft'` 支持 `amplitude_mode/db_reference`（现恒线性）。
- 测：dB 模式出图数据轴与主面板一致。

### T8 — FFT Welch 平均〔SP〕
- `batch.py:_compute_fft_dataframe` 支持 `overlap/avg_mode/avg_overlap`（现单块）。
- 测：与主面板 `FFTAnalyzer` 在相同 Welch 参数下逐点一致。

---

## 依赖图
```
T1 ──▶ T2                      (阶段一，可与阶段二并行)
T3 ──▶ T4
T3 ──▶（端到端验证）
T5                              (独立)
T6                              (独立)
T7, T8                          (阶段三，门控，依赖阶段二完成)
```

## 完成判据
- 阶段一：滤波端到端往返通过 + 验真截图。
- 阶段二：weighting 三方法端到端透传 + fft_time 填入可用 + 对话框可选计权 + 全量套无新增失败（排除已知 flaky）。
- 阶段三：（若启）批处理 FFT 数值与主面板逐点一致。

## 风险与回滚
- schema v2：保留 v1 迁移，旧项目可读；新文件被旧 app 读会被版本拒绝（可接受）。
- passthrough 切方法泄漏：用方法白名单过滤，配单测守。
- UI 变更：以 spec 为评审依据，落地 `pyqt-ui-engineer` 验真渲染（勿凭「属性设上+单测过」判定）。
