# 批处理时域布局与横坐标 Implementation Plan v3

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Every production change follows `superpowers:test-driven-development`; each test must be observed failing for the intended reason before implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为批处理时域导出增加每信号、同文件多通道、同通道多文件三种出图分组，支持叠加/分屏和时间/指定通道横坐标，同时保持旧 preset、默认任务身份、输出路径和恢复契约兼容。

**Architecture:** 默认 `render_group_by=none` 继续使用现有 task 级单次 reservation + `atomic_write_set`，只是把时域图片载荷适配成新的 `BatchTimeFigureSpec`。显式分组使用两阶段执行：运行开始先探测 renderer；随后按 source-major 计算并发布 task 数据、把最小曲线载荷写入临时 spool；最后逐组读取载荷并单独原子发布组图片。组图片在 schema v1 manifest 中拥有可选、可增量 journal 的独立状态，resume/retry 同时校验成员 task、源文件 facts 和图片 checksum。

**Tech Stack:** Python 3、NumPy、pandas、Matplotlib OO/Agg、PyQt5、pytest、现有 batch output/manifest 原子写入设施。

## Global Constraints

- 产品代码基线为 `6cf1360`；计划文档提交可在该基线上新增一个 docs-only commit。
- `method != "time"` 时五个新参数必须由 `normalize_batch_params` 移除；FFT、FFT-time、order-time 的 recipe fingerprint、task id、stem 和行为不得变化。
- 五个默认值只在运行期解析，绝不物化进 normalized params：`none`、`overlay`、`time`、`""`、`zero`。
- 默认兼容门禁是规范化语义等价，不声称跨运行 JSON 或图片逐字节相同；run id、时间戳、checksum 本来就会变化。
- 默认模式不得出现 `render_groups`、`image_count` 或 `x_channel_aligned`；`derive_summary()` 的返回结构保持不变。
- 任何请求 image 的运行都必须在第一次 `reserve_output_paths` 之前调用现有 `_probe_image_backend()`；只有 probe 的 `ImportError`/`ModuleNotFoundError` 可以把 data+image 降级为 data-only。
- probe 之后发生的 render/write 错误仍属于原子事务失败，不得降级或吞掉。
- `render_group_by=none` 保留 task stem、一次 reservation、一次 `atomic_write_set` 和 task 级 image manifest；显式 `source/channel` 分组才拥有 group stem 和 `render_groups`。
- 显式分组即使只有一个成员，也按“task data + group image”两个发布单元执行；不伪造跨 stem 的原子事务。
- 单组成员上限 32，subplot 活跃 panel 上限 8，单组保留曲线字节上限 128 MiB，全运行 spool 上限 2 GiB；阈值必须在追加载荷前检查且可 monkeypatch。
- 新 UI 只允许选择所有已加载 source 共同具备的 X 通道；partial 通道显示但禁用。导入的无效选择要清空并产生 `x_channel` preflight issue。
- X 通道单位必须在所有参与 source 中一致；UI 预检和 renderer 都要 fail closed，不能取第一个 source 的单位冒充全组单位。
- 两种 Y 单位使用左右轴；第三种单位报错。两种 Y 单位同时配置手动 Y 范围时明确报错，不能把同一数值范围无提示套到不同物理单位。
- 旧 DataFrame 时域 renderer 作为兼容入口保留；BatchRunner 的时域图片从 Task 4 起统一走 spec。
- 不修改 `CLAUDE.md` 或 `.claude/`；不顺手修计划外既有测试失败。

---

## Fixed Design Contracts

### Recipe and UI defaults

```python
TIME_RENDER_DEFAULTS = {
    "render_group_by": "none",
    "render_layout": "overlay",
    "x_source": "time",
    "x_channel": "",
    "x_origin": "zero",
}
```

`normalize_batch_params()` 将这五个字段列入 `METHOD_PARAM_FIELDS["time"]`，并删除值等于上表默认值的字段；其他 method 因 known-but-incompatible 规则删除全部五个字段。UI getter 也只返回语义偏离默认值的键，所以“用户改回默认值”、旧 preset、导入/导出走同一规范化结果。

### Rendering payload

```python
@dataclass(frozen=True)
class BatchSeries:
    x: np.ndarray
    y: np.ndarray
    label: str
    unit: str = ""
    x_unit: str = "s"
    linestyle: str = "-"      # only "-" or "--"
    panel: int = 0


@dataclass(frozen=True)
class BatchTimeFigureSpec:
    series: tuple[BatchSeries, ...]
    layout: str = "overlay"   # overlay | subplot
    x_source: str = "time"    # time | channel
    x_origin: str = "zero"    # only applies to time
    x_label: str = "Time (s)"
    panel_titles: tuple[str, ...] = ()
```

`BatchSeries.__post_init__` 要求一维、x/y 等长、panel 为非负 int、linestyle 合法；允许成对空数组。空 series 不参与单位、范围、legend；全空 spec 渲染一个有标签的空轴。subplot 按非空 series 的 panel 创建连续 active panels；全空时创建一个 panel。`x_source=channel` 强制 absolute，不执行归零。

### Group state

仅当 `method=time`、显式分组且 requested image 时写 `render_groups`。组状态为：

`pending -> running -> done | partial | failed | blocked | cancelled | degraded | skipped`

- `done`：所有预期成员都产生可画 payload，图片发布且 checksum 完整；task data 的 skipped/failed 状态独立记录，不改变图片是否包含完整曲线集合。
- `partial`：至少一个成员失败、至少一个成功并发布了部分组图；不得作为完整 resume 命中。
- `failed`：没有可画成员，或 render/publish 失败。
- `blocked`：成员数/panel/字节/spool 护栏拒绝图片；task data 仍可成功。
- `degraded`：renderer probe 不可用且 data 仍可输出；不 reserve 组图片。
- `cancelled`：取消发生在组图完成前。
- `skipped`：显式 `skip` 冲突策略使现存组图未被本次运行证明有效。

每次组状态变化都通过 recorder upsert 后原子重写 `.partial.json`。

### Grouped resume matrix

`data_valid` 按每个 task 分别计算；`image_valid` 只有在 group status=`done`、成员 task id 集合完全一致、每个 source identity/size/mtime_ns 一致、无 degraded reason、图片 checksum/format 完整时为真。

| data | image | 动作 |
|---|---|---|
| 全部 valid | valid | 所有 task resumed；组图复用；不加载 source |
| 部分 invalid | valid | 只重写 invalid task data；图片复用 |
| 全部 valid | invalid | 重算全部 render payload；只发布组图；所有 data bytes/mtime 不变 |
| 部分 invalid | invalid | invalid task 写 data；全部成功成员重算 payload；发布组图 |

任一成员 source stat 改变都会令该成员 data 和整组 image 失效。旧 degraded task 不可 resume。retry-failed 扩展到失败/partial/blocked/cancelled group，但成功成员只提供 payload，已验证 data 不重写。

---

### Task 1: Time Figure Spec Renderer

**Files:**
- Modify: `mf4_analyzer/batch_render.py`
- Test: `tests/test_batch_renderer.py`

**Interfaces:**
- Produces: `BatchSeries`, `BatchTimeFigureSpec`, `warnings_out` keyword on `render_batch_image`, `_build_batch_figure`, `_build_batch_figure_in_context`.
- Preserves: legacy `("time", DataFrame)` behavior and public renderer `Path` return.

- [ ] **Step 1: Add failing renderer-contract tests**

Add tests named:

```python
test_time_spec_overlay_has_no_phantom_axis
test_time_spec_channel_x_uses_requested_label_without_zeroing
test_time_spec_normalizes_each_time_series_and_keeps_union
test_time_spec_mixed_x_units_fail_closed
test_time_spec_two_y_units_use_one_combined_legend
test_time_spec_three_y_units_fail_closed
test_time_spec_dual_y_rejects_manual_y_limits
test_time_spec_subplot_uses_only_active_panels_and_bottom_x_label
test_time_spec_original_and_filtered_linestyles_are_distinct
test_time_spec_all_empty_renders_one_blank_labeled_axis
test_time_spec_context_renders_group_member_coverage
test_invalid_cmap_falls_back_and_appends_warning
```

Assert exact axes counts, x data, xlabel, xlim union, left/right ylabel, legend labels and `-`/`--`. The channel-X test must start at a nonzero value and prove it remains nonzero. The all-empty test must prove no `min/max` exception occurs.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/test_batch_renderer.py -q
```

Expected: the new imports/tests fail because the spec types and behavior do not exist; existing tests remain at their recorded baseline.

- [ ] **Step 3: Implement the spec path before `add_subplot(111)`**

Insert the `kind == "time" and isinstance(data, BatchTimeFigureSpec)` dispatch before the unconditional axis creation. Implement validation, empty filtering, first-appearance unit assignment, exact X union, combined legend and active-panel subplot assembly. Apply `spec.x_label` to overlay or the bottom primary subplot axis; clear labels/tick text above it.

For dual Y, reject valid manual `y_min/y_max` when `y_auto` is false. Apply manual X only on the primary/shared axis after autoscale union. Use `_linear_amplitude_label` for both Y axes. Teach `_effective_fact_items` to render a supplied `members="N/M"` fact. When sparse input panel ids are compressed, use `panel_titles[original_panel_id]` when that index exists.

- [ ] **Step 4: Implement warning sink and cmap fallback**

Add `warnings_out: list[str] | None = None` through the renderer call chain. `_render_heatmap` resolves `params.get("cmap", "turbo")` with `matplotlib.colormaps`; invalid names append exactly one warning and use `turbo`. Do not change any renderer return type.

- [ ] **Step 5: Run renderer tests GREEN and commit**

```powershell
python -m pytest tests/test_batch_renderer.py tests/test_db_conversion_convergence.py -q
git diff --check
git add mf4_analyzer/batch_render.py tests/test_batch_renderer.py
git commit -m "Add grouped time-domain figure spec"
```

---

### Task 2: Aligned X-Channel Preprocessing

**Files:**
- Modify: `mf4_analyzer/batch_preprocess.py`
- Test: `tests/test_batch_preprocess.py`

**Interfaces:**
- Produces: `preprocess_batch_signal(..., *, rpm=None, x_values=None)` and `BatchPreprocessResult.x_values`.
- Compatibility: `effective["x_channel_aligned"]` exists only when `x_values` is supplied.

- [ ] **Step 1: Add failing alignment tests**

```python
test_x_values_follow_time_range_and_joint_finite_mask
test_x_values_follow_regularization_and_downsampling
test_x_values_do_not_receive_target_gain_mean_or_user_filter
test_x_values_length_mismatch_fails_before_preprocessing
test_default_preprocess_effective_facts_do_not_gain_x_key
```

The downsample expectation must be derived from literal input/output coordinates, not by calling the helper under test.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_batch_preprocess.py -q
```

- [ ] **Step 3: Thread X through every alignment helper**

Use these exact signatures and return ordering:

```python
def _regularize_for_antialias(time, signal, rpm, x_values, fs):
    return time, signal, rpm, x_values, regularized

def _anti_aliased_downsample(signal, time, fs, target_fs, rpm, x_values):
    return signal, time, rpm, x_values, facts, warnings
```

Treat X like RPM during time mask, joint finite mask, regularization, its own anti-alias filtering and interpolation. Never apply target scale/offset, mean removal or final user filter to X.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_preprocess.py -q
git diff --check
git add mf4_analyzer/batch_preprocess.py tests/test_batch_preprocess.py
git commit -m "Align batch X channels with target preprocessing"
```

---

### Task 3: Time-Only Recipe, Group Identity and Truthful Preview

**Files:**
- Modify: `mf4_analyzer/batch_recipe.py`
- Modify: `mf4_analyzer/batch_validation.py`
- Modify: `mf4_analyzer/batch_output.py`
- Create: `mf4_analyzer/batch_grouping.py`
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_recipe.py`
- Test: `tests/test_batch_validation.py`
- Test: `tests/test_batch_output.py`
- Test: `tests/test_batch_runner.py`

**Interfaces:**
- Produces: `TIME_RENDER_DEFAULTS`, `RenderTask`, `RenderGroup`, `group_render_tasks`, `GroupOutputIdentity`, `build_group_output_identity`.
- Produces: group-aware `BatchRunner.preview_outputs()` without loading unresolved sources.

```python
@dataclass(frozen=True)
class RenderTask:
    source_key: object
    channel: str
    identity: TaskOutputIdentity

@dataclass(frozen=True)
class RenderGroup:
    identity: GroupOutputIdentity
    group_by: str
    group_key: str
    layout: str
    members: tuple[RenderTask, ...]

def group_render_tasks(
    tasks: Sequence[RenderTask], params: Mapping[str, Any]
) -> tuple[RenderGroup, ...]: ...

@dataclass(frozen=True)
class GroupOutputIdentity:
    group_id: str
    stem: str
    members: tuple[tuple[str, str, str], ...]

def build_group_output_identity(
    members: Sequence[tuple[str, str, str]], *,
    method: str, params: Mapping[str, Any], group_by: str,
) -> GroupOutputIdentity: ...
```

Extend preview with integer fields `group_count`, `data_artifact_count`, `image_artifact_count`, `data_conflict_count`, and `image_conflict_count`; keep all existing fields and return type.

- [ ] **Step 1: Add failing recipe and identity tests**

Cover:

```python
test_time_render_defaults_are_removed_from_normalized_params
test_time_render_nondefaults_change_fingerprint
test_time_render_fields_are_removed_from_every_non_time_method
test_channel_x_requires_nonempty_channel
test_group_identity_changes_when_one_member_source_changes
test_group_identity_is_member_order_independent
```

Also assert imported `render_layout=subplot` is normalized away when effective group-by is `none`, `x_channel` is normalized away unless effective `x_source=channel`, and `x_origin` is normalized away when effective X source is channel.

- [ ] **Step 2: Add failing preview tests**

For 2 sources × 2 channels assert:

- none + data/image = 4 data + 4 image;
- source grouping = 4 data + 2 image;
- channel grouping = 4 data + 2 image;
- data-only = 4 data + 0 image and no render groups;
- group image conflicts use group stems; data conflicts use task stems;
- unresolved sources are not passed to the full loader.

Retain `BatchOutputPreview.task_count`, `artifact_count`, `conflict_count`; add `group_count`, `data_artifact_count`, `image_artifact_count`, `data_conflict_count`, `image_conflict_count`. Default-mode aggregate conflict semantics stay task-set compatible; grouped aggregate is the sum of conflicting task data sets plus group image paths.

- [ ] **Step 3: Verify RED**

```powershell
python -m pytest tests/test_batch_recipe.py tests/test_batch_validation.py tests/test_batch_output.py tests/test_batch_runner.py -q
```

- [ ] **Step 4: Implement pure planning primitives**

`RenderTask` contains source key, channel and task identity. `RenderGroup` contains `group_id`, stem, group key, ordered member task ids and layout. `group_render_tasks()` returns task-singletons for `none`, source groups ordered by source then channel, or channel groups ordered by channel then source. The group fingerprint input is the sorted full `(source_identity, group_identity, channel)` sequence.

Do not add the new fields to `COMMON_PARAM_FIELDS`; add them only to `METHOD_PARAM_FIELDS["time"]` and `KNOWN_PARAM_FIELDS`. Normalize inactive/default fields out before fingerprinting.

- [ ] **Step 5: Make preview consume the same grouping plan**

Build task/group identities from known metadata or unresolved `SimpleNamespace` exactly as current task preview does. Preview must never probe the renderer, reserve paths or load files.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_recipe.py tests/test_batch_validation.py tests/test_batch_output.py tests/test_batch_runner.py -q
git diff --check
git add mf4_analyzer/batch_recipe.py mf4_analyzer/batch_validation.py mf4_analyzer/batch_output.py mf4_analyzer/batch_grouping.py mf4_analyzer/batch.py tests/test_batch_recipe.py tests/test_batch_validation.py tests/test_batch_output.py tests/test_batch_runner.py
git commit -m "Plan time render groups and preview outputs"
```

---

### Task 4: Bounded Series Spool and Default Spec Adapter

**Files:**
- Create: `mf4_analyzer/batch_series_spool.py`
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`
- Test: `tests/test_batch_series_spool.py`

**Interfaces:**
- Produces: `BatchSeriesSpool`, `SpooledSeriesRef`, `_build_time_series`, `_build_time_figure_spec`.
- Consumes: Task 1 spec and Task 2 aligned X result.

```python
@dataclass(frozen=True)
class SpooledSeriesRef:
    x_path: Path
    y_path: Path
    label: str
    unit: str
    x_unit: str
    linestyle: str
    panel: int
    nbytes: int

class BatchSeriesSpool:
    def append(
        self, group_id: str, task_id: str,
        series: Sequence[BatchSeries],
    ) -> tuple[SpooledSeriesRef, ...]: ...
    def load(
        self, refs: Sequence[SpooledSeriesRef],
    ) -> tuple[BatchSeries, ...]: ...
    def close(self) -> None: ...

def _build_time_series(
    self, *, fd, signal_name: str,
    preprocessed: BatchPreprocessResult,
    source_label: str, params: Mapping[str, Any], panel: int,
) -> tuple[BatchSeries, ...]: ...

def _build_time_figure_spec(
    self, series: Sequence[BatchSeries], *,
    params: Mapping[str, Any], x_label: str,
    panel_titles: Sequence[str] = (),
) -> BatchTimeFigureSpec: ...
```

- [ ] **Step 1: Add failing spool and adapter tests**

Tests must cover round-trip metadata/arrays, cleanup after success/exception, mmap loading, append-before-write byte rejection, all-run spool limit, original/filtered linestyle, channel X label/unit, missing X channel task failure, and default single-task spec contents.

Use constants:

```python
_MAX_GROUP_MEMBERS = 32
_MAX_SUBPLOT_PANELS = 8
_MAX_GROUP_PAYLOAD_BYTES = 128 * 1024 * 1024
_MAX_SPOOL_BYTES = 2 * 1024 * 1024 * 1024
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_batch_series_spool.py tests/test_batch_runner.py -q
```

- [ ] **Step 3: Implement spool with a private temporary directory**

Store each x/y array as `.npy`, metadata in immutable Python records, and load with `np.load(..., mmap_mode="r")`. Track bytes from array `nbytes` before writing. `close()` removes only the exact temporary directory created by the spool; context-manager cleanup must run on cancel and exceptions.

- [ ] **Step 4: Implement one canonical time-series adapter**

For `x_source=time`, use preprocessed time and `x_unit="s"`; `x_origin` comes from params. For `x_source=channel`, require the channel in `fd.data`, pass raw values to Task 2 preprocessing, use aligned X, force `x_origin="absolute"`, and build label as `f"{channel} ({unit})"` when unit is nonempty, otherwise channel.

Original line uses `linestyle="-"`; filtered line uses `"--"`. Labels include source/channel plus `original` or `filtered` only when both exist. Group subplot panels are contiguous in member order.

- [ ] **Step 5: Route default time images through spec without changing publication**

Keep default `_run_one` probe/reservation/`atomic_write_set` order. Replace only its time image payload with a one-task spec. Keep non-time payloads unchanged. `_write_image(..., warnings_out=None)` continues returning the existing path/result; caller-owned attempt warnings are discarded on `OutputPublishRace` retry and merged only after successful publication.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_series_spool.py tests/test_batch_runner.py tests/test_batch_renderer.py tests/test_db_conversion_convergence.py -q
git diff --check
git add mf4_analyzer/batch_series_spool.py mf4_analyzer/batch.py tests/test_batch_series_spool.py tests/test_batch_runner.py
git commit -m "Adapt time exports to bounded figure series"
```

---

### Task 5: Crash-Safe Render Group Manifest and Recovery Helpers

**Files:**
- Modify: `mf4_analyzer/batch_manifest.py`
- Test: `tests/test_batch_manifest.py`

**Interfaces:**
- Produces: `BatchManifestRecorder.upsert_task`, `upsert_render_group`, `find_resumable_group`, `RetryScope`.
- Preserves: `SCHEMA_VERSION == 1`, `derive_summary()` shape and old-manifest loading.

```python
@dataclass(frozen=True)
class GroupMemberResumeFact:
    task_id: str
    source: Mapping[str, Any]

@dataclass(frozen=True)
class RetryScope:
    task_keys: frozenset[tuple[object, str, str]]
    group_ids: frozenset[str]

def find_resumable_group(
    manifest: Mapping[str, Any], *, recipe_fingerprint: str,
    group_id: str, members: Sequence[GroupMemberResumeFact],
    image_format: str, cancel_token=None,
) -> Mapping[str, Any] | None: ...
```

- [ ] **Step 1: Add failing manifest tests**

```python
test_default_manifest_has_no_render_groups_and_unchanged_summary_shape
test_group_upsert_is_visible_in_partial_journal_immediately
test_group_upsert_replaces_instead_of_duplicating
test_old_manifest_without_render_groups_still_loads
test_resumable_group_requires_done_status_and_complete_members
test_resumable_group_rejects_changed_member_source_stat
test_resumable_group_rejects_bad_image_checksum
test_partial_and_degraded_groups_are_not_resumable
test_retry_scope_includes_failed_group_and_all_member_task_keys
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_batch_manifest.py -q
```

- [ ] **Step 3: Extend recorder and validation**

Use task id and group id keyed ordered mappings internally. `record()` remains a compatibility alias to `upsert_task()`. Every upsert atomically rewrites the partial journal. Final and partial manifests include `render_groups` only when at least one group was registered; do not add `image_count` anywhere.

Each group entry contains:

```python
{
    "group_id": str,
    "stem": str,
    "group_by": "source" | "channel",
    "layout": "overlay" | "subplot",
    "members": [{"task_id": str, "source": source_file_facts_dict}],
    "requested_outputs": {"image": str},
    "effective_outputs": {"image": str} | {},
    "degraded_reason": str,
    "status": str,
    "message": str,
    "warnings": list[str],
    "artifact": image_artifact_facts | None,
}
```

- [ ] **Step 4: Implement source-safe resume and retry helpers**

`find_resumable_group` compares recipe id, group id, exact ordered member task ids, each source identity/size/mtime_ns, group status and image artifact checksum. `RetryScope` exposes `task_keys` and `group_ids`; failed task membership expands to its whole group for rendering but does not declare healthy data writable.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_manifest.py -q
git diff --check
git add mf4_analyzer/batch_manifest.py tests/test_batch_manifest.py
git commit -m "Journal batch render groups and recovery facts"
```

---

### Task 6: Grouped Batch Execution and Outcome State

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes: Tasks 3–5 grouping, spool and manifest helpers.
- Produces: fresh-run group execution with task-data and group-image ownership.

```python
@dataclass(frozen=True)
class EffectiveOutputPlan:
    requested: Mapping[str, str]
    effective: Mapping[str, str]
    render_backend_types: tuple[type, type] | None
    degraded_reason: str

@dataclass
class TaskComputeResult:
    item: BatchItemResult
    series_refs: tuple[SpooledSeriesRef, ...] = ()
    render_error: str = ""

@dataclass
class RenderGroupResult:
    group_id: str
    status: str
    image_path: str | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    artifact: dict[str, Any] | None = None

def _resolve_effective_outputs(self, outputs) -> EffectiveOutputPlan: ...
def _compute_group_task(
    self, preset: AnalysisPreset, source_key: object, fd,
    signal_name: str, output_dir: Path,
    spool: BatchSeriesSpool, group: RenderGroup, *,
    data_write_eligible: bool,
    payload_required: bool, effective: EffectiveOutputPlan,
    cancel_token=None,
) -> TaskComputeResult: ...
def _render_group(
    self, group: RenderGroup,
    results: Sequence[TaskComputeResult], preset: AnalysisPreset,
    output_dir: Path, spool: BatchSeriesSpool, *,
    effective: EffectiveOutputPlan, recorder=None,
    cancel_token=None,
) -> RenderGroupResult: ...
```

- [ ] **Step 1: Add failing probe/order and publication tests**

Add tests proving:

- renderer probe occurs once before the first reservation in grouped mode;
- backend missing + data/image produces task data, degraded groups and no image reservations;
- backend missing + image-only fails members/groups before compute/reservation;
- default none still performs one task reservation and one atomic data+image publication;
- explicit source/channel singleton uses task data stem plus distinct group image stem;
- group image failure leaves successful CSV untouched and journaled task status done;
- writer-time import/render errors roll back the image transaction and do not degrade.

- [ ] **Step 2: Add failing group outcome and guard tests**

Cover source/channel outputs, partial/all-failed groups, member=33, subplot panel=9, 128 MiB threshold before spool write, 2 GiB all-run threshold, cancel cleanup, warnings mirrored to successful members, and data-only producing no group journal entries.

- [ ] **Step 3: Add a failing source-major load-count test**

For 4 physical sources × 2 selected channels with `group_by=channel`, assert each physical source is loaded once in a fresh run. The assertion must observe the real loader boundary; do not assert an internal cache constant.

- [ ] **Step 4: Verify RED**

```powershell
python -m pytest tests/test_batch_runner.py -q
```

- [ ] **Step 5: Implement run-level effective output planning**

After validation/task grouping but before recorder output reservations, probe once when image requested. Pass one immutable effective-output decision into every task/group path; no nested probe is allowed. Default none may call the existing `_run_one` with the already-probed backend types.

- [ ] **Step 6: Implement source-major compute and group render**

For explicit groups, iterate physical sources once, compute task data and series payload, publish only eligible data, spool only groups that need rendering, then evict the physical file. After compute, iterate groups deterministically, load one group via mmap, render/publish one image, update member warnings and journal state, then release mappings before the next group.

If a group crosses its 128 MiB guard, mark that group blocked and stop spooling it while continuing task data. If the 2 GiB run guard is reached, mark every image group that still requires additional spool data blocked; continue data exports without writing more spool files. Partial groups render only successful members with effective fact `members="N/M"`.

- [ ] **Step 7: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_runner.py tests/test_batch_manifest.py tests/test_batch_output.py tests/test_batch_renderer.py tests/test_batch_preprocess.py -q
git diff --check
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "Execute grouped time-domain exports"
```

---

### Task 7: Grouped Resume, Retry and Conflict Policies

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes: Task 5 recovery helpers and Task 6 grouped execution.
- Produces: `data_write_eligible`, `payload_required`, `image_write_required` decisions for resume/retry.

```python
@dataclass(frozen=True)
class GroupRecoveryDecision:
    data_write_task_ids: frozenset[str]
    payload_task_ids: frozenset[str]
    image_write_required: bool
    reusable_group: Mapping[str, Any] | None

def _plan_group_recovery(
    self, group: RenderGroup, *, resume_manifest=None,
    retry_scope: RetryScope | None = None,
) -> GroupRecoveryDecision: ...
```

- [ ] **Step 1: Add failing resume matrix tests**

Implement one behavior test for each Fixed Design Contract matrix row. Each test records CSV/image bytes and mtimes before resume, then asserts only the eligible artifact changes.

- [ ] **Step 2: Add failing invalidation and retry tests**

Cover:

- changing one member mtime/size invalidates that task data and the whole group image;
- valid member CSV bytes and mtime remain unchanged while a missing group image is regenerated;
- retrying one failed member re-renders the whole group but leaves healthy CSV bytes/mtime unchanged;
- failed/partial/blocked/cancelled group ids enter retry scope even when member task status is done;
- partial and degraded group images never count as complete resume hits.

- [ ] **Step 3: Add failing conflict-policy tests**

Exercise `error`, `skip`, `overwrite` and `auto_number` independently for task data and group-image publication.

- A task-data `error` marks that task failed; when image is requested its source is still computed for a render payload, but its data writer is absent. Data-only stops that task before analysis.
- A task-data `skip` records task status skipped and no verified data artifact; when image is requested the computed payload may still contribute to the group.
- Task-data `overwrite` and `auto_number` publish normally and record the actual path.
- Group status coverage counts successfully computed render payloads, not data publication status. A complete line set plus a published image may therefore be group `done` while one task data artifact is skipped; task status remains authoritative for data resume.
- A group-image `skip` records group status skipped and never claims the existing image as verified provenance; overwrite replaces the exact group path; auto-number records the final reserved path.
- A group-image `error` happens after any eligible task data publication, preserves that data, and records group failed. There is deliberately no cross-transaction rollback.

- [ ] **Step 4: Verify RED**

```powershell
python -m pytest tests/test_batch_runner.py tests/test_batch_manifest.py -q
```

- [ ] **Step 5: Implement decisions before loading any source**

Build `data_write_eligible`, `payload_required` and `image_write_required` sets from manifest facts. Never infer data writability from payload requirement. Resume and retry use exact prior artifact/source facts rather than treating an existing filename as provenance. Expand retry to whole-group payload requirements only after determining healthy data eligibility.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest tests/test_batch_runner.py tests/test_batch_manifest.py tests/test_batch_output.py -q
git diff --check
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "Recover grouped time-domain exports safely"
```

---

### Task 8: Time UI Controls and Preset Compatibility

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- Modify: `mf4_analyzer/analysis_presets.py`
- Test: `tests/ui/test_batch_method_buttons.py`
- Test: `tests/test_analysis_presets.py`

**Interfaces:**
- Produces: five time controls, `DynamicParamForm.set_x_channel_candidates`, whole preset host hiding.
- Preserves: old `time_preprocess` in `BatchSheet._base_params`; form accepts and ignores it.

```python
def set_x_channel_candidates(
    self, common: Sequence[str], partial: Mapping[str, str]
) -> None: ...
```

- [ ] **Step 1: Capture the pre-UI-change baseline in the SDD report**

Run these exact existing cases before editing any UI production or test file:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_batch_input_panel.py::test_disk_add_triggers_probe tests/ui/test_batch_input_panel.py::test_limited_source_row_exposes_reason_and_never_runs_probe tests/ui/test_batch_input_panel.py::test_probe_failure_sets_probe_failed tests/ui/test_batch_input_panel.py::test_path_pending_to_loaded_transition tests/ui/test_batch_method_buttons.py::test_method_button_labels_fit_narrow_batch_column_with_production_qss tests/ui/test_batch_smoke.py::test_sheet_opens_artifact_location_only_after_explicit_row_activation -q
```

Write the six individual outcomes and command output into the task report; Tasks 8–10 compare against this evidence.

- [ ] **Step 2: Add failing UI tests**

Cover exact visible time field set, default getter `{}`, nondefault sparse serialization, user changing back to defaults, inactive layout/origin omission, apply/get round-trip, old `time_preprocess` acceptance, common/partial candidate behavior, and time/FFT preset host visibility.

- [ ] **Step 3: Verify RED**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_batch_method_buttons.py tests/test_analysis_presets.py -q
```

- [ ] **Step 4: Replace the six old widgets with five controls**

Use combos for grouping, layout, X source, X channel and time origin. Serialize exactly as Fixed Design Contracts specifies. Run all visibility/enabled synchronizers at the end of `_render_for()` for init-sync. Use `_set_form_row_visible` for X channel and time-origin rows.

Partial X items carry the existing availability suffix and are disabled through their item model flags. If an applied/pending selection is not common after universe refresh, clear it, retain a validation message, and emit `paramsChanged` once.

- [ ] **Step 5: Wrap and hide the complete preset section**

Create `self._preset_host` containing both title and radio row. For time, hide host and return before `list_builtin_presets`. Remove time built-ins from `analysis_presets` only; do not remove batch method support.

- [ ] **Step 6: Run GREEN and commit**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_batch_method_buttons.py tests/test_analysis_presets.py -q
git diff --check
git add mf4_analyzer/ui/drawers/batch/method_buttons.py mf4_analyzer/ui/drawers/batch/analysis_panel.py mf4_analyzer/analysis_presets.py tests/ui/test_batch_method_buttons.py tests/test_analysis_presets.py
git commit -m "Add sparse time layout controls to batch UI"
```

---

### Task 9: X-Channel UI Dataflow, Units and 288 px Geometry

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/task_list.py`
- Test: `tests/ui/test_batch_input_panel.py`
- Test: `tests/ui/test_batch_output_panel.py`
- Test: `tests/ui/test_batch_smoke.py`
- Test: `tests/ui/test_batch_toolbar.py`
- Test: `tests/ui/test_batch_task_list.py`

**Interfaces:**
- Produces: `InputPanel.channelUniverseChanged(tuple, dict)`, `OutputPanel.set_x_axis_context(label, unit)`, Sheet synchronization/preflight.

```python
channelUniverseChanged = pyqtSignal(tuple, dict)

def set_x_axis_context(self, *, label: str, unit: str = "") -> None: ...

def apply_dry_run(
    self, tasks: Sequence[tuple[str, str, str]],
    outputs_per_task: int, *, artifact_count: int | None = None,
) -> None: ...
```

- [ ] **Step 1: Add failing signal and preflight tests**

Prove universe signal emits exact common/partial payload, Sheet updates candidates, stale selection clears, missing X is a preflight issue, and mixed source units are a preflight issue. Use real loaded row metadata rather than a mock widget.

- [ ] **Step 2: Add failing output-label, task-count and narrow-layout tests**

Prove time displays `Time (s)`, channel displays `channel (unit)`, mixed units never display a guessed first-source unit, presentation sync does not emit output `changed`, and the time form at 288 px under production QSS has no horizontal scrollbar/overflow. Include a long X channel name and toggle all dependent rows twice to expose stale geometry. For 2 sources × 2 channels, assert the visible task-list summary reports 8 outputs for none and 6 outputs for source/channel grouping while retaining four task rows.

- [ ] **Step 3: Verify RED against the Task 8 baseline**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_output_panel.py tests/ui/test_batch_smoke.py tests/ui/test_batch_toolbar.py tests/ui/test_batch_task_list.py -q
```

Only failures not present in the Task 8 report block this task.

- [ ] **Step 4: Wire common/partial candidates and unit aggregation**

Emit after `_refresh_signal_universe`. Sheet resolves units for the selected X across every loaded row using `channel_metadata[ch]["unit"]`, falling back to `row.units[ch]`. Zero/one unique units updates OutputPanel; more than one adds `ValidationIssue("x_channel", "mixed_x_units", ...)` and clears the display unit.

Call the X-axis context synchronizer on method changes, params changes and universe changes. `set_x_axis_context` updates presentation only and does not emit a recipe/output change.

Change `TaskListWidget.apply_dry_run` to accept `artifact_count: int | None = None`; when supplied, the idle summary uses that exact count instead of `len(tasks) * outputs_per_task`. In `_on_run_clicked`, build runner and preset before applying the dry run, call `runner.preview_outputs(preset, output_dir)`, and pass `preview.artifact_count`. The task rows remain per task; only the visible output count becomes group-aware.

- [ ] **Step 5: Run GREEN and commit**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_output_panel.py tests/ui/test_batch_smoke.py tests/ui/test_batch_toolbar.py tests/ui/test_batch_task_list.py -q
git diff --check
git add mf4_analyzer/ui/drawers/batch/input_panel.py mf4_analyzer/ui/drawers/batch/sheet.py mf4_analyzer/ui/drawers/batch/output_panel.py mf4_analyzer/ui/drawers/batch/task_list.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_output_panel.py tests/ui/test_batch_smoke.py tests/ui/test_batch_toolbar.py tests/ui/test_batch_task_list.py
git commit -m "Wire batch X-channel context through the UI"
```

---

### Task 10: Frozen/Packaging Coverage and Final Regression Gates

**Files:**
- Create: `mf4_analyzer/batch_time_group_acceptance.py`
- Modify: `mf4_analyzer/batch_render_smoke.py`
- Test: `tests/test_batch_time_group_acceptance.py`
- Test: `tests/test_frozen_batch_render_smoke.py`

**Interfaces:**
- Produces: `batch_time_group_acceptance.run(output_directory: Path, result_json: Path) -> int` and module CLI `--output-dir/--result-json`.
- Verifies: frozen renderer imports/spec path, real core-runner grouped outputs, deleted-image resume, legacy compatibility and Windows UI geometry.

- [ ] **Step 1: Add a failing frozen smoke assertion for the spec path**

The smoke artifact must render a `BatchTimeFigureSpec` through the same public `render_batch_image` entry point used by frozen acceptance. Assert the image exists, is nonempty and has expected dimensions; do not grep source text.

- [ ] **Step 2: Verify RED, implement minimal smoke update and run GREEN**

```powershell
python -m pytest tests/test_frozen_batch_render_smoke.py -q
```

Do not change the frozen executable's existing three-MF4/one-channel CLI contract. Frozen acceptance only proves the public spec renderer is bundled and callable.

- [ ] **Step 3: Add a failing end-to-end group acceptance test**

The new acceptance module creates two on-disk CSV-backed `FileData` inputs with `time`, `speed`, and `accel`, runs `none`, `source`, and `channel` into separate directories, and asserts exact data/image/group counts plus manifest member linkage. It then deletes one channel-group image, resumes from that manifest with `resume_policy="manifest"`, and asserts the image is recreated while every verified CSV byte sequence and mtime is unchanged. It writes a JSON result with `status`, per-mode counts, resume facts and generated paths.

- [ ] **Step 4: Verify RED, implement the harness and run GREEN**

```powershell
python -m pytest tests/test_batch_time_group_acceptance.py -q
python -m mf4_analyzer.batch_time_group_acceptance --output-dir .state/acceptance/batch-time-groups --result-json .state/acceptance/batch-time-groups.json
```

- [ ] **Step 5: Run focused feature gate**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_batch_renderer.py tests/test_batch_preprocess.py tests/test_batch_recipe.py tests/test_batch_validation.py tests/test_batch_output.py tests/test_batch_manifest.py tests/test_batch_series_spool.py tests/test_batch_runner.py tests/test_batch_time_group_acceptance.py tests/test_analysis_presets.py tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_output_panel.py tests/ui/test_batch_smoke.py tests/ui/test_batch_toolbar.py tests/ui/test_batch_task_list.py -q
```

- [ ] **Step 6: Run repository regression partitions**

```powershell
python -m pytest tests/ -q --ignore=tests/ui --ignore=tests/acquisition_ui --ignore=tests/test_importer_runtime_smoke.py --ignore=tests/test_tdms_loader.py
python -m pytest tests/acquisition_ui -q
```

Run UI tests per file so the two known QMessageBox access-violation files cannot hide other results. Compare with the baseline captured before Task 8 and require zero new failures.

- [ ] **Step 7: Build both Windows packages with frozen spec smoke**

Run the exact commands below. Do not add `-SkipInstall`; each script owns its environment and invokes `tools/verify_frozen_batch_render.py` against the built executable.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1 -AppName TraceLabBatchV3Full -Console -KeepPrevious
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_folder_lite.ps1 -AppName TraceLabBatchV3Lite -Console -KeepPrevious
```

Require both commands to exit 0, both executables to exist, and both smoke JSON files to report success:

```text
dist/TraceLabBatchV3Full/TraceLabBatchV3Full.exe
dist/TraceLabBatchV3Lite/TraceLabBatchV3Lite.exe
.state/build-evidence/TraceLabBatchV3Full-batch-render-smoke.json
.state/build-evidence/TraceLabBatchV3Lite-batch-render-smoke.json
```

Then re-run the exact `batch_time_group_acceptance` CLI from Step 4 and inspect its JSON result.

- [ ] **Step 8: Run lessons and diff gates, then commit**

```powershell
python scripts/lessons/check.py
git diff --check
git status --short
git add mf4_analyzer/batch_time_group_acceptance.py mf4_analyzer/batch_render_smoke.py tests/test_batch_time_group_acceptance.py tests/test_frozen_batch_render_smoke.py
git commit -m "Cover grouped time exports in frozen acceptance"
```

Stage only files actually changed by this task; do not add unrelated untracked documents.

---

## Plan Self-Review Checklist

- [ ] Every new parameter has one normalization owner, one runtime default owner and a time-only gate.
- [ ] Default params, task identity, task stem and manifest schema/shape compatibility have behavior tests; no test compares volatile whole-manifest bytes.
- [ ] Renderer probe occurs before every reservation on every image path.
- [ ] Default task publication and explicit group publication are separate, non-contradictory contracts.
- [ ] Group journal state is persisted during the run, not only at finalization.
- [ ] Resume validates every member source stat; retry cannot rewrite healthy data.
- [ ] Preview counts the same group plan the runner executes.
- [ ] OutputPanel preview and TaskList dry-run summary both consume the group-aware artifact count.
- [ ] Memory constraints are byte-based and checked before spool append.
- [ ] X alignment covers time mask, finite mask, regularization and downsampling.
- [ ] X label reaches the rendered bottom axis and OutputPanel.
- [ ] Empty series, mixed X units, third Y unit and dual-Y manual limits have explicit outcomes.
- [ ] UI default serialization, preset pass-through, whole-row hiding and 288 px geometry are tested.
- [ ] No placeholder, stale revision directive or cross-stem singleton atomicity requirement remains.

## Commit Order

Tasks 1 through 10 commit serially. A task is complete only after its implementer report, task-scoped spec/quality review, and any fix-loop re-review are clean. After Task 10, run one whole-branch review from the plan commit to `HEAD`, one fix wave if needed, then use `superpowers:finishing-a-development-branch`.
