# 分析 View 来源隔离 · Codex Review 修复实施计划

- 日期：2026-08-10
- 状态：可执行
- 依据审查：
  [`2026-08-10-grok-analysis-view-source-isolation-implementation-review.md`](../reviews/2026-08-10-grok-analysis-view-source-isolation-implementation-review.md)
- 产品 Spec：
  [`2026-08-10-analysis-view-source-isolation-pilot-spec.md`](../specs/2026-08-10-analysis-view-source-isolation-pilot-spec.md)
- 原实施 Plan：
  [`2026-08-10-analysis-view-source-isolation-pilot-implementation.md`](../plans/2026-08-10-analysis-view-source-isolation-pilot-implementation.md)
- 基线分支：`codex/analysis-view-source-isolation-pilot` @ `a08afe3e`

## 1. 审查结论采纳

审查总体判断 **合理，采纳为 NO-GO / NEEDS REWORK**。核心产品模型（全局文件仓库 +
每 View 独立 attachment + Pane 来源）保持不变；下列问题属真实实现缺口，不是误报：

| ID | 严重度 | 问题 | 核实 |
| --- | --- | --- | --- |
| F1 | P1 | 局部 detach / 删通道后分析画布 stale | `_detach_files_from_active_analysis_view` 只投影不 render |
| F2 | P1 | 进 FFT 跳过 `apply_params` 后又 `capture` live→state | `_on_mode_changed` + `_enter_fft_mode` |
| F3 | P1 | 依赖索引漏 exact-X / overlay | `collect_source_uses` 仅 attachment/checked |
| F4 | P2 | analysis_candidates 仍可点 checkbox +「显示」标题 | `set_projection_role` 未改 header/flags |
| F5 | P2 | 物理文件多 logical source 关闭非原子 | `_request_close_group` 逐 fid `_close` |
| F6 | 门禁 | FRF Inspector 旧文案断言；Task 10 / full suite 未闭环 | `test_inspector.py:283` |

本次修复范围：**F1–F5 + F6 文案测试**。Task 10（50 次矩阵 / 性能 / macOS 前台）与
Batch 全量归因另立 gate，不在本 plan 声称完成 Stage 1。

## 2. 修复顺序（与审查 §6 一致）

1. **F2** — 恢复 target state → live 完整 apply，再决定是否复用画布
2. **F1** — detach / 通道删除后对当前 section 做 cache 投影或清图
3. **F3** — 依赖索引与 cleanup 共享 persisted-refs 合同（含 exact X、overlay）
4. **F4** — 左栏三种 role 的 header / flags / 交互外观
5. **F5** — 物理 group close 一次依赖摘要、全有或全无
6. **F6** — 同步 FRF Inspector 测试；加强 mode-switch 双断言

## 3. Task A — FFT 模式进入顺序（F2）

### 改动

- `window.py::_on_mode_changed('fft')`：调用
  `_apply_active_analysis_context(mode, render=False, apply_params=True)`
  （**必须** apply params/sources/range；可跳过立即 render）。
- `window.py::_enter_fft_mode`：
  - **禁止**在 apply 之前用 live Inspector 覆盖目标 View params；
  - 允许在 attachments/sources 已 apply 后，仅 capture **navigator 勾选**到当前 FFT
    Pane（若产品仍要“进入时同步勾选”），但不得 `capture_params`；
  - 或更干净：完全不再 capture params；sources 以已 apply 的 state 为准，勾选变化只走
    `_ch_changed`。
- 推荐干净合同：`_enter_fft_mode` 不再调用 `_capture_active_analysis_view`；只基于已
  apply 的 state 算 signature / 缓存渲染 / preview。

### 测试

- 强化 `test_mode_switch_applies_target_active_view_before_capture`：
  - live Inspector `nfft` 设为与 state 不同；
  - 进入 FFT 后 live 与 state 均等于目标 View 的 params；
  - state serialization 中 `nfft` 不被 live 覆盖。
- 恢复真正的自动进入路径（toolbar mode 切换），不手动绕过 `_enter_fft_mode` 事件链
  （可保留 `qtbot.wait` 等 timer）。

## 4. Task B — detach / 删通道后画布一致（F1）

### 改动

- `_detach_files_from_active_analysis_view`：mutation + 投影后，若当前 mode == section，
  调用 `_render_analysis_view_from_cache(section, state)`（空来源路径会清图）。
- 通道删除确认清理路径：在清完 analysis refs 后，若当前 mode 是分析 section，同样
  re-render/clear 当前 View；**不**对局部/已局部清理的 fid 再做多余全局 invalidate
  （全局删除仍走既有 invalidate）。
- 仍禁止局部 detach 调用 `_invalidate_all_analysis_caches_for_fid`。

### 测试

- FFT/时频/FRF/阶次：有结果 → detach 来源文件 → `has_result() is False`（或等价空画布）。
- sibling View / 其他 section state byte-equivalent 仍保持。

## 5. Task C — 依赖索引补全（F3）

### 改动

- `analysis_source_scope.collect_source_uses` / `collect_channel_uses` 增加：
  - `role="x_axis"`：`ViewState.axis_opts` 中 `EXACT_SOURCE` 的 `source_fid`[/channel]
  - `role="overlay_primary"`：`overlay_primary` 命中
  - （可选防御）`frf_source_signature` 内 input/output fid
- 摘要文案计入这些角色。
- 纯单测：`attached=[]/checked=[]` 但 exact X 指向 f1 → uses 非空；关闭默认取消。

## 6. Task D — 左栏投影语义（F4）

### 改动

- `set_projection_role`：
  - `time`：列标题保持「显示」；checkbox + eye
  - `fft_sources`：第三列标题改为「来源」；checkbox 可选；无 eye
  - `analysis_candidates`：第三列标题改为「移出」或隐藏无意义勾选列语义；
    **清除** channel 的 `ItemIsUserCheckable`，避免瞬时勾选反馈
- 有 focused widget 断言（header text + flags），不只断言 state。

## 7. Task E — 物理 group close 原子性（F5）

### 产品决策（本轮采用）

> 文件区物理卡关闭 = 同组全部 logical sources 一次依赖汇总，默认取消；确认后全部关闭。
> 不允许一次物理关闭产生部分成功。

### 改动

- `FileNavigator` 增加 group-close 信号（或复用现有并传 fid 列表）。
- `_close_group(fids)`：聚合 `collect_source_uses` → 一次确认 → 确认后对每个 fid
  `force=True` 走既有清理链。
- 单测：两 logical sources 同组，依赖在其一；取消则两者都在；确认则两者皆关。

## 8. Task F — 文案/测试收口（F6 窄修）

- `tests/ui/test_inspector.py`：断言「来源不可用」。
- 不在本轮声称 A17/A18 PASS。

## 9. 验证命令

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_analysis_source_scope.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_frf_main_window.py \
  tests/ui/test_inspector.py \
  tests/ui/test_main_window_smoke.py \
  tests/ui/test_main_window_state_ownership.py -q --tb=line
```

边界：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_packaging_imports.py -q
```

## 10. 明确非目标

- 不实现 Stage 2 unresolved/relink。
- 不在本 plan 内完成 Task 10 前台/性能矩阵（另开验收）。
- 不把范围外 Batch teardown 红项改成 xfail 冒充全绿；需单独 baseline。
- 不扩大 `test_main_window_state_ownership` 白名单。

## 11. Definition of Done（本修复轮）

- F1–F5 有失败→修复→绿测闭环。
- F2 的 mode-switch 测试同时断言 state 与 live params。
- F1 测试断言 canvas `has_result` / 空图，不只 state。
- F3 测试覆盖 exact-X 默认取消。
- F5 同组多 fid 一次确认。
- 审查文档中的三条 P1 在 focused 证据下关闭。
