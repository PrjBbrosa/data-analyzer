# 分析结果缓存 View 绑定常驻（Pinning）实施计划

- 日期：2026-08-11
- 状态：已实施
- 对应 spec：
  [`2026-08-11-analysis-cache-view-pinning-spec.md`](../specs/2026-08-11-analysis-cache-view-pinning-spec.md)
- 任务顺序即依赖顺序；Task 1–2 是地基，3–5 可在 2 之后并行，6 收口，7 独立。
- 每个 Task 自带看守测试；先跑对应子目录，收尾按两条命令跑全量
  （主体 `--ignore=tests/acquisition_ui` + 该目录单独跑）。

## 实测记录

- Task 0 基线（实施前）：`test_task4_cache_invalidation` /
  `test_nonuniform_fft_full_flow` / `test_compute_progress_integration` /
  `test_cache_key_dataclass_binding` → **51 passed**。
- 实施后聚焦（含新增 pinning/residency、coordinator、state-ownership、
  FRF/multiview、quickref）：**239 passed**。
- Review 复核（Task 8 全量收尾）：主体一条命令在当前 HEAD 被一个**既有**的
  通道树 delegate paint 交错 segfault 阻断（干净 HEAD worktree A/B 复现，
  与本实施无关）；分段口径下全部通过（非 ui 2263 + ui 两半 851/2904 +
  acquisition_ui 355），仅有的 2 个 failed 均归因为既有红 / 并行会话在途
  污染。定性、崩溃栈、临时验证口径与后续修复建议见
  [`../reviews/2026-08-11-channel-tree-paint-segfault-triage.md`](../reviews/2026-08-11-channel-tree-paint-segfault-triage.md)。

## Task 0 — 基线记录

动手前记录当前失败数（CLAUDE.md 纪律）。相关子集：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_task4_cache_invalidation.py \
  tests/ui/test_nonuniform_fft_full_flow.py \
  tests/ui/test_compute_progress_integration.py \
  tests/test_cache_key_dataclass_binding.py -q
```

预期与 2026-08-11 全量基线一致（两边全绿）。这四个文件是现有缓存契约的
持有者，后续每个 Task 结束都要求它们保持绿。

## Task 1 — `AnalysisResultCache` 淘汰规则（纯逻辑，不碰 UI）

**改动**：`mf4_analyzer/ui/analysis_cache.py`

- 构造签名加可选 keyword-only `pinned_provider=None`（返回键集合的可调用）。
- `put` 淘汰循环按 spec §3 改写：只淘汰无主条目，容量语义 = 无主条数上限。
  provider 每次淘汰循环调用一次（不缓存结果——pin 簿在两次 put 之间会变）。
- `FrfAnalysisResultCache` 不需要额外改动（继承 `put`）。
- docstring 更新容量语义（文件头「capacity 12」的注释一并改）。

**看守**：新增 `tests/ui/test_analysis_cache_pinning.py`（或并入
`test_task4_cache_invalidation.py` 同目录新文件）：

- pinned 条目在 2×capacity 的 put 风暴后仍在；无主条目按插入序淘汰。
- `pinned_provider=None` 时与现状逐字节一致（容量、淘汰序、`get` 触发的
  move_to_end）——这是所有既有用例的兼容面。
- `invalidate_fid` / `clear` 无视 pin 照删（spec §3：pin 是留存策略不是正确性屏障）。
- `FrfCacheKey` 进 pin 集合的可哈希路径。

## Task 2 — window 侧 pin 簿 + put 单点 helper

**改动**：`mf4_analyzer/ui/main_window/window.py` + `_analysis_mixin.py`

- `window.__init__` 建 `self._analysis_pins: dict[(section, view_id, pane_idx), set]`，
  四个 cache 构造时注入闭包 provider（对该 section 取并集）。
  注意状态所有权棘轮（`test_main_window_state_ownership.py`）：`_analysis_pins`
  只在一个文件赋值——建在 `window.py`，mixin 只调方法不裸写属性；若需 holder，
  进 `_state_holders.py` 的既有 dataclass 模式。
- 新增单点 helper（归属 `_analysis_mixin.py`，与其余缓存编排同居）：
  `_store_analysis_result(section, view_id, pane_idx, key, result)` = put + pin 追加；
  以及 `_replace_analysis_pane_pins(section, view_id, pane_idx, keys)`（Task 4 用）、
  `_drop_analysis_view_pins(section, view_id)`（Task 5 用）。
- 同步站点改道：`_fft_mixin.py:281`（active view state 在作用域内）与
  `_order_mixin.py:351`（缓存命中回写，经 helper 顺带记 pin）。

**看守**：

- AST 测试（放同一新测试文件）：扫 `mf4_analyzer/`，对
  `analysis_caches`（及 coordinator 持有的 `_cache`）的 `.put(` 调用只允许出现在
  helper 定义内。写法参照 `tests/test_batch_run_reporter.py` 的
  reporter-stays-private 范式。
- 单测：helper 落盘后 provider 立即含该键；同一 (view, pane) 追加不重复。

## Task 3 — 异步站点：ctx 带 view_id，coordinator 改注入 store 回调

**改动**：

- `_order_mixin.py` dispatch 处：ctx 写入 `view_id`（dispatch 时刻的 active，
  `pane_idx` 已有）；`_on_order_job_finished`（`:688`）改调 helper，身份取自 ctx，
  **禁止**读回调时的 active。
- `fft_time_coordinator.py` / `frf_coordinator.py`：构造参数从裸 cache 改为
  （或额外加）window 注入的 store 回调；`_on_job_finished` 经回调落盘。
  候选 dict 在 `_fft_time_mixin.py` / FRF dispatch 构建处加 `view_id`；
  `_build_context` 的 `dict(candidate)` 原样携带，`_apply_factory_updates`
  不触碰该字段。coordinator 自身的 `_cache.get` 读路径不变。
- `window.py:160-168` 的构造点同步改签名。

**看守**：spec §8.4 的异步身份用例——dispatch 后立即切 View，等回调落盘，断言
pin 记在 dispatch 时的 view_id 下（`tests/ui/test_compute_progress_integration.py`
已有完整的假 job 基建可复用）。coordinator 现有单测（若有构造签名断言）同步更新。

## Task 4 — 渲染查键点：按 pane 整体替换 pin 集合

**改动**：

- `_render_analysis_view_from_cache`（`_analysis_mixin.py:687`）：fft 分支收集
  pane 内全部键、heatmap 分支收集单键后，调 `_replace_analysis_pane_pins`。
  未命中的键也记（绑定意图，spec §4）。注意 pane 数少于 `state.panes` 时
  （单/双 pane 对齐后）只替换实际枚举过的 pane，未枚举的 pane 集合清空。
- `_render_frf_view_from_cache`（`_frf_mixin.py:629`）：同样处理 FRF 键。

**看守**：单测——先在 View A pane 0 落盘两组参数的结果（模拟调参迭代），切走
再切回 A，断言 pin 集合只剩当前键，旧参数结果回到无主队列并可被 put 风暴淘汰
（spec §4 自清洁性质）。

## Task 5 — pin 生命周期接线

**改动**（全部走 Task 2 的方法，不散写字典操作）：

- 删除 View：分析区删除 intent 处理器（`_on_analysis_view_delete` 一族）在
  `mgr.delete_view` 前调 `_drop_analysis_view_pins(section, view_id)`。
- `window.py:2452` 的 `analysis_caches['fft_time'].clear()` 站点：同步清该
  section 的 pin 条目（helper：`_clear_analysis_section_pins(section)`）。
- `invalidate_fid`：**不**剪 pin（spec §5 明确决定，死键无害、渲染替换自清）；
  在 helper docstring 里写明这是决定不是遗漏。

**看守**：删 View 后其结果可被淘汰；复制 View 后两个 view_id 并集引用同一条目、
删其一另一个仍 pin 住。

## Task 6 — 集成守卫（产品承诺的常驻护栏）

新增 `tests/ui/test_analysis_view_cache_residency.py`，spec §7 前三行各一条：

1. **轮巡零 miss**：一个 heatmap 分区建 12 View（单 pane）各落盘一个假结果，
   任意顺序切换两圈，断言 `_render_analysis_view_from_cache` 全程不出空态提示
   （可 spy `_show_analysis_empty_hint`）。
2. **双 pane 超容量**：12 View × 2 pane = 24 绑定（容量 12），同样零 miss。
3. **调参风暴**：停在 View 1 连续 20 次不同参数落盘，断言其余 11 个 View 的
   绑定键仍在 `_store`。

用假结果对象（轻量 dict/dataclass）经 helper 落盘即可，不跑真实 DSP；重点是
淘汰语义不是数值。测试标注这是 spec §7 的机械看守：红了修代码，不放宽。

## Task 7 — 附带小修：View 快捷键对齐 12（独立，可先行）

- `_view_mixin.py:182` `range(6)` → `range(9)`（Alt+1..9；10–12 号走标签栏，
  spec §9 已定）。
- `tests/ui/` 现有快捷键用例同步（若有断言只装 6 个）。
- 跑 `/update-hints` 核对：hints/quickref 目前无 Alt 文案；若速查面板该补
  「Alt+1..9 切换当前分区 View」，按该命令的流程走。

## Task 8 — 收尾验证

1. Task 0 的四个契约文件 + 新增测试全绿。
2. 全量两条命令跑法，对照 Task 0 基线，失败数不增。
3. 真机冒烟（非 offscreen）：加载 `testdoc/` 样本，时频分区建 3-4 个 View 各算
   一次，轮巡确认无「点击计算」空态；Activity Monitor 看 RSS 与预期量级相符
   （spec §6）。不涉及 paint 性能，无需跑 ink/交互基准。
4. 提交按 Task 分粒度；spec 状态行改「已实施」，本文件补实测记录。
