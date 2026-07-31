# Test Coupling Classification Study

**日期：** 2026-07-30

**基线：** `b5d7956eb8c80c7981d174ed92575e876d171c2b`

**范围：** 只读研究；未修改源码或测试，未安装或运行 coverage。

## 1. 结论

1. **值得补行为级契约测试，但它只能补强、不能取代白盒层。** C 类“可迁移到公开行为”分层加权估计为 **74.3%**，95% 区间 **67.6%–81.0%**。
2. **不应全局禁止私有属性断言。** S1 中 B 类“有意白盒不变量”占 **53.3%**，覆盖性能状态机、对象复用、缓存和 debounce 生命周期。
3. **没有证据证明 `canvas.py` 是被测试阻止才无法拆分。** S1+S2 的 A 类“脆弱实现细节”估计仅 **3.6%**，95% 上界 **8.2%**。
4. **裸 `_refresh` 与 `_refresh_pending/_refresh_timer` 不能混为一谈。** 裸 `canvas._refresh` 只有一条断言，判 A；其余 17 条锁定活跃的 flush、timer 和 generation 行为。
5. 若引入 `@pytest.mark.whitebox`，只应标记 B 类，并要求写明为什么没有合理的公开等价断言；不能给所有私有访问批量加 marker。

## 2. 权威分类口径

- **A · Implementation-detail coupling：** 锁定死状态、对象别名、冗余常量、内部布局或 setup 前提；纯移动、重命名或等价重组会使其失败，但用户行为可能不变。
- **B · Intentional white-box invariant：** 性能状态机、缓存键、对象复用、生命周期或数值/渲染内部不变量；没有成本合理的公开等价断言，破坏时应明确失败。
- **C · Migratable：** 当前通过私有成员断言，但可合理迁移到真实 UI 事件、公开信号/返回值、渲染结果或用户可见状态。

每条样本只分配一个标签。

## 3. 总体、分层与种子

总体命令：

```bash
grep -rn "assert [a-z_]*\._[a-z_]*" tests --include="*.py" | wc -l
```

基线结果：`1,232`。

| 层 | 定义 | 总体 N | 样本 n |
|---|---|---:|---:|
| S1 | `tests/ui/test_pg_timedomain_canvas.py` | 220 | 30 |
| S2 | 其余文件名含 `pg`/`canvas` 的 UI 测试及明确 canvas 邻接文件 | 258 | 30 |
| S3 | `tests/ui/test_chart_stack*.py` | 93 | 30 |
| S4 | 扣除 S1–S3 后其余 `tests/ui/` | 489 | 30 |
| S5 | `tests/ui/` 之外 | 172 | 30 |
| **合计** |  | **1,232** | **150** |

S2 补充集合：

```text
test_axis_interaction.py
test_envelope.py
test_high_variation_envelope.py
test_timedomain_canvas_contract.py
test_xlim_refresh.py
```

**固定种子：** `20260730`

**样本 manifest SHA-256：** `bd5e10c760d5c42b36b8198a165cbd6aae26761727becc01fa92af8822d3c162`

## 4. 可重复抽样脚本

脚本直接读取基线 Git 对象，不受并行工作树变化影响。一个 RNG 按 S1→S5 连续抽样，每层取 `min(30, N)` 条。

```bash
.venv/bin/python - <<'PY'
from pathlib import PurePosixPath
from collections import Counter
import hashlib
import random
import re
import subprocess

SHA = "b5d7956eb8c80c7981d174ed92575e876d171c2b"
SEED = 20260730
PAT = re.compile(r"assert [a-z_]*\._[a-z_]*")
ATTR = re.compile(r"assert\s+[a-z_]*\.(_[A-Za-z0-9_]*)")
EXPLICIT_S2 = {
    "test_axis_interaction.py",
    "test_envelope.py",
    "test_high_variation_envelope.py",
    "test_timedomain_canvas_contract.py",
    "test_xlim_refresh.py",
}

def git(*args):
    return subprocess.check_output(["git", *args], text=True)

def stratum(path):
    p = PurePosixPath(path)
    name = p.name
    if path == "tests/ui/test_pg_timedomain_canvas.py":
        return "S1"
    if path.startswith("tests/ui/") and name.startswith("test_chart_stack"):
        return "S3"
    if (
        path.startswith("tests/ui/")
        and ("pg" in name or "canvas" in name or name in EXPLICIT_S2)
    ):
        return "S2"
    if path.startswith("tests/ui/"):
        return "S4"
    return "S5"

rows = []
paths = git("ls-tree", "-r", "--name-only", SHA, "tests").splitlines()
for path in sorted(p for p in paths if p.endswith(".py")):
    for line_no, line in enumerate(git("show", f"{SHA}:{path}").splitlines(), 1):
        if PAT.search(line):
            match = ATTR.search(line)
            attr = match.group(1) if match else "<multiline>"
            rows.append((stratum(path), path, line_no, attr, line.strip()))

rng = random.Random(SEED)
sample = []
for layer in ("S1", "S2", "S3", "S4", "S5"):
    population = [row for row in rows if row[0] == layer]
    picked = rng.sample(population, min(30, len(population)))
    sample.extend(sorted(picked, key=lambda row: (row[1], row[2])))

manifest = "\n".join("\t".join(map(str, row)) for row in sample) + "\n"
print("population:", len(rows))
print("strata:", Counter(row[0] for row in rows))
print("sample:", len(sample))
print("manifest_sha256:", hashlib.sha256(manifest.encode()).hexdigest())
print(manifest, end="")
PY
```

期望摘要：

```text
population: 1232
strata: S1=220, S2=258, S3=93, S4=489, S5=172
sample: 150
manifest_sha256: bd5e10c760d5c42b36b8198a165cbd6aae26761727becc01fa92af8822d3c162
```

## 5. 分类结果

每层比例使用 95% Wilson score interval。总体估计按各层总体数量加权，并使用有限总体修正的近似区间。

| 层 | A 实现细节 | B 有意白盒 | C 可迁移 |
|---|---:|---:|---:|
| S1 | 0/30 = 0.0% `[0.0, 11.4]` | 16/30 = 53.3% `[36.1, 69.8]` | 14/30 = 46.7% `[30.2, 63.9]` |
| S2 | 2/30 = 6.7% `[1.8, 21.3]` | 3/30 = 10.0% `[3.5, 25.6]` | 25/30 = 83.3% `[66.4, 92.7]` |
| S3 | 4/30 = 13.3% `[5.3, 29.7]` | 3/30 = 10.0% `[3.5, 25.6]` | 23/30 = 76.7% `[59.1, 88.2]` |
| S4 | 3/30 = 10.0% `[3.5, 25.6]` | 1/30 = 3.3% `[0.6, 16.7]` | 26/30 = 86.7% `[70.3, 94.7]` |
| S5 | 0/30 = 0.0% `[0.0, 11.4]` | 12/30 = 40.0% `[24.6, 57.7]` | 18/30 = 60.0% `[42.3, 75.4]` |
| **分层加权** | **6.4% `[1.7, 11.0]`** | **19.3% `[14.2, 24.3]`** | **74.3% `[67.6, 81.0]`** |

Canvas 邻接面 S1+S2：

| 范围 | A | B | C |
|---|---:|---:|---:|
| S1+S2 | 3.6% `[0.0, 8.2]` | 29.9% `[20.4, 39.5]` | 66.5% `[56.1, 76.8]` |

## 6. 25% 决策规则

25% 定义为“足以支持一次有成本测试架构动作”的材料性阈值：

- 95% 区间下界高于 25%：强证据，执行相应动作。
- 点估计超过 25%，但区间跨过 25%：局部信号，不制定仓库级规则。
- 95% 区间上界低于 25%：拒绝该动作的当前因果前提。
- 按目标 surface 判断，不能用普通 widget 样本淹没 canvas/perf 状态机。

应用结果：

1. **建立公开行为契约：是。** C 类在五层的区间下界都高于 25%。
2. **全面禁止私有断言：否。** S1 的 B 类下界为 36.1%，明确高于 25%。
3. **认为 canvas 拆分被测试阻止：否。** Canvas 邻接 A 类上界仅 8.2%。
4. **whitebox marker：窄用。** 只标 B，并要求机制理由；C 应迁移，A 应删除或重写。

## 7. `_refresh` 定向普查

```bash
grep -rn "assert [a-z_]*\._[a-z_]*" tests --include="*.py" \
  | rg "\._refresh\b|\._refresh_"
```

共 18 行：

- 裸 `canvas._refresh`：1 行，`tests/ui/test_pg_timedomain_canvas.py:1538`，判 **A**。
- `_refresh_pending/_refresh_timer`：17 行，多数属于 **B** 或 **C**。

`:1538` 先人为写 `canvas._refresh = False`，调用 `reset_cursor_state()`，再断言它变为 True；生产代码没有读取该 flag，删除赋值不改变游标行为。

其余断言锁定导出 flush、programmatic range settle、stale generation、split timer 隔离和 perf benchmark 完成状态。它们与 `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md` 的机制一致，不能因共享 `_refresh` 前缀一起删除。

## 8. 代表性证据

### A · Implementation-detail coupling

- 裸 `canvas._refresh`：死 flag，无生产读取。
- `test_pg_heatmap_canvas.py:826`：只锁定 setup 点在内部 scene rect。
- `test_pg_heatmap_canvas.py:2082`：只为强制移除 layout item 证明 `_cbar` 当前存在。
- `test_chart_stack.py:462`：锁定内部 margin，尽管已有最终几何断言。
- `test_chart_stack.py:2113/2125`：锁定内部按钮名称。
- `test_chart_stack.py:2463`：锁定 `_fft_time_card` 与 `_cards[0]` 的对象别名。
- `test_auto_color_span.py:22`：输出已验证后又重复锁定常量。
- `test_main_window_smoke.py:4064`：只证明 provider 对象存在，后续结果已证明接线。
- `test_split_container.py:27`：锁定 splitter count，公开 secondary canvas 已证明两 pane。

### B · Intentional white-box invariant

- `test_pg_timedomain_canvas.py:779`：窄 Y wall guard 必须跨 cache hit 保持。
- `test_pg_timedomain_canvas.py:4638`：导出不得污染 idle-AA hysteresis。
- `test_pg_timedomain_canvas.py:4816/4837`：coarse refresh 的延迟与 pending xlim 状态机。
- `test_pg_timedomain_canvas.py:5292–5403`：selection-delta 必须复用 PlotDataItem/ViewBox。
- `test_pg_heatmap_canvas.py:1343`：色阶窗口不得裁剪原矩阵。
- `test_chart_stack.py:2862–2873`：提示 timer 的 single-shot/dwell 机制。
- `test_timedomain_hotpath_perf.py:146`：resize burst 必须收口到 settle timer。
- `test_state_machine.py:521`：连接 timeout 后必须清 attempt timestamp。

相关 lessons：

- `docs/lessons-learned/pyqt-ui/2026-06-23-y-overflow-wall-guard-needs-y-in-range-key-and-cache-hit-state.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`
- `docs/lessons-learned/pyqt-ui/2026-06-27-hint-ship-flip-test-blast-radius.md`

### C · Migratable

- 私有 wheel handler → 真实 `QWheelEvent`、range 和 settle 信号。
- 私有 axis label → 公开 axis adapter 或渲染标题。
- `_img/_cbar.levels` → 公开 clim/colorbar 范围。
- `_remarks[*].flags` → 真实拖动注释。
- 私有 toolbar button → child lookup/accessibility 和真实点击。
- 私有 spinbox 值 → preset roundtrip 或公开表单查询。
- 私有 channel-config 方法 → 保存动作、store 结果和信号。
- `_ifdata_xcp` → readiness、backend gate、状态 chip 和连接结果。

## 9. 三项建议

### 9.1 是否建立行为级契约层？

**是，但不能成为重构时唯一必须绿的层。**

优先为 chart/widget、axis labels、toolbar、preset、主窗口 workflow 和 acquisition readiness 补公开查询/事件测试；保留 B 类性能、缓存、generation 和生命周期测试。

### 9.2 是否禁止新测试访问私有属性？

**否。**

- 能以公开事件、信号或输出验证时，不新增 C 类私有断言。
- B 类必须附机制理由，并可用 `@pytest.mark.whitebox`。
- A 类不允许新增。
- 不批量给现有 1,232 行加 marker。

### 9.3 `canvas.py` 是否被测试阻塞？

**否，当前数据不支持该因果判断。**

拆分需要保留 B 类状态机、为 C 类提供 façade/test adapter、清理少量 A 类，并审计 monkeypatch、source inspection 和旧导入锚点。这是兼容迁移工作，不是无法拆分的证明。

## 10. 限制

- 每层只有 30 条；S3/S4 的 A 类区间上界仍略过 25%，针对这些模块拆分时应扩大样本。
- 单一分类者对“公开替代成本是否合理”有主观判断。
- 正则不覆盖 `getattr`、fixture 间接访问、monkeypatch 或 source inspection。
- `self._helper()` 会产生少量假阳性。
- 分类比例不能证明历史上曾有 refactor 因测试而放弃。
- Coverage 未安装；计划禁止未经批准新增依赖。

## 附录 A：150 条样本

### S1

| 位置 | 属性 | 类 | 理由 |
|---|---|:---:|---|
| `tests/ui/test_pg_timedomain_canvas.py:521` | `_overlay_mode` | C | `effective_pixel_width` 和 plot mode 可替代。 |
| `:761` | `_y_overflow_wall_active` | C | displayed-point 数已证明未限流。 |
| `:779` | `_y_overflow_wall_active` | B | wall guard 与 AA gate 不变量。 |
| `:3166` | `_overlay_axes.selected_channel` | C | RectMode、selection 信号和橡皮框可观察。 |
| `:3167` | `_overlay_axes.dragging` | C | 可由真实 press 后是否进入 drag 验证。 |
| `:3621` | `_handle_cursor_mouse_move` | C | 可发真实 move 并断言 `cursor_info`。 |
| `:4638` | `_quality.density_allowed` | B | 导出不得污染 idle-AA hysteresis。 |
| `:4816` | `_remaining_coarse_refresh_ms` | B | 10 Hz 限流向上取整。 |
| `:4837` | `_pending_coarse_xlim` | B | 早到 timeout 必须保留 xlim。 |
| `:4941` | `_handle_wheel_dispatch` | C | 可用真实 wheel event 替代。 |
| `:5181` | `_interaction_generation` | B | split generation 必须隔离。 |
| `:5292` | `_channel_lines` | B | 必须复用 line identity。 |
| `:5293` | `_x_master_handle` | B | master ViewBox 不得重建。 |
| `:5403` | `_channel_lines` | B | append 必须复用 PlotDataItem。 |
| `:5548` | `_channel_lines` | B | hidden warm path 必须复用 ViewBox。 |
| `:6550` | `_quality.aa_on` | B | idle-AA 初始状态机。 |
| `:6631` | `_refresh_pending` | C | pixmap、setData 和 displayed range 可证明 flush。 |
| `:6660` | `_quality.aa_on` | C | curve AA opts 可替代。 |
| `:6685` | `_quality.aa_on` | B | overlay drag 时禁止 AA。 |
| `:6715` | `_quality.timer` | B | build 后必须重臂 timer。 |
| `:6726` | `_quality.aa_on` | C | curve AA/cache mode 可替代。 |
| `:6730` | `_quality.aa_on` | C | curve opts 与 timer 可替代。 |
| `:6766` | `_handle_wheel_dispatch` | C | 真实 Shift-wheel 可替代。 |
| `:6770` | `_quality.timer` | B | Y-wheel 后必须重臂 timer。 |
| `:7004` | `_AA_OVERLAY_SEGMENT_ON` | B | hysteresis 防逐帧抖动。 |
| `:7040` | `_quality.density_allowed` | B | unreadable data 必须 fail closed。 |
| `:7120` | `_quality.aa_on` | C | DeviceCoordinateCache 与 AA opts 可替代。 |
| `:7193` | `_quality.aa_on` | C | NoCache 与 curve opts 可替代。 |
| `:8277` | `self._companion_pen_style` | B | 正则假阳性；实际锁定 dash style。 |
| `:8456` | `_load_custom_action` | C | 菜单和 QSettings roundtrip 可替代。 |

### S2

| 位置 | 属性 | 类 | 理由 |
|---|---|:---:|---|
| `tests/ui/test_pg_dense_raster.py:527` | `_refresh_pending` | C | pixmap cacheKey/data rect 可证明 flush。 |
| `tests/ui/test_pg_heatmap_canvas.py:237` | `_plot.titleLabel` | C | 实际布局可验证无标题行。 |
| `:238` | `axis.autoSIPrefix` | C | 实际刻度和标题可替代。 |
| `:277` | `axis.labelText` | C | 用户可见轴标题。 |
| `:492` | `_img.levels` | C | 公开 clim/渲染可替代。 |
| `:493` | `_cbar.levels` | C | colorbar 显示范围可替代。 |
| `:781` | `_remarks.text.flags` | C | 真实拖动注释可替代。 |
| `:826` | `_plot.sceneBoundingRect` | A | 只是 setup 前提。 |
| `:1036` | `_cbar` | C | reset 后无 colorbar 可观察。 |
| `:1343` | `_matrix_disp` | B | 原矩阵不得被色阶裁剪。 |
| `:1632` | `_slice_aa_on` | B | marker drag AA 状态机。 |
| `:1906` | `_slice_marker.angle` | C | 用户可见 marker 朝向。 |
| `:1907` | `axis.labelText` | C | 用户可见轴标题。 |
| `:2082` | `_cbar` | A | 仅为强删 layout item 的 setup。 |
| `:2143` | `_plot.isVisible` | C | collapse 后主图可见。 |
| `:2210` | `_bottom_collapsed` | C | 可见性和高度可替代。 |
| `:2212` | `_slice_plot.maximumHeight` | C | 实际 UI 高度。 |
| `:2355` | `_bottom_split_h` | C | 可真实拖 divider 量测。 |
| `:2720` | `_slice_curve/_slice_plot` | C | reset 后继续使用可证明存活。 |
| `:2881` | `_value_at` | C | hover/click readout 可替代。 |
| `tests/ui/test_pg_line_canvas.py:294` | `_time_overlay_axes` | C | axis tree 和字体可观察。 |
| `:811` | `_aa_on` | B | 交互降 AA 状态机。 |
| `:916` | `axis.labelText` | C | 用户可见轴标题。 |
| `:918` | `axis.labelText` | C | 用户可见轴标题。 |
| `:926` | `rightAxis` | C | 用户可见右框线。 |
| `:1136` | `maximumHeight` | C | 实际布局高度。 |
| `:1220` | `maximumHeight` | C | 恢复默认高度。 |
| `:1234` | `_bottom_split_h` | C | 可真实拖 divider 量测。 |
| `:1558` | `_remarks.dot.brush` | C | 用户可见注释颜色。 |
| `:1773` | `AxisItem._tickDensity` | C | 应改断言实际 tick 数。 |

### S3

| 位置 | 属性 | 类 | 理由 |
|---|---|:---:|---|
| `tests/ui/test_chart_stack.py:112` | `_time_toolbar.mode` | C | 真实 toolbar 广播可替代。 |
| `:140` | `axis.labelText` | C | 用户可见轴标题。 |
| `:210` | `_toggle_btn.text` | C | 用户可见文案。 |
| `:211` | `_toggle_btn.toolTip` | C | 用户可见 tooltip。 |
| `:222` | `_toggle_btn.text` | C | 用户可见恢复文案。 |
| `:462` | `_primary.contentsMargins` | A | 已有最终几何断言。 |
| `:557` | `_pill.x` | C | 最终位置可量测。 |
| `:611` | `_pill...property` | C | mini 状态可公开观察。 |
| `:668` | `_annotation_btn` | C | child lookup/accessibility 可替代。 |
| `:672` | `_annotation_btn.objectName` | C | 可从公开 child tree 查询。 |
| `:673` | `_annotation_btn.text` | C | icon-only 行为。 |
| `:678` | `_clear_annotation_btn.toolTip` | C | 用户可见 tooltip。 |
| `:1396` | `_quality_indicator.property` | C | 状态信号和渲染可替代。 |
| `:1437` | `_quality_indicator_position_pending` | B | 失败后必须清 debounce pending。 |
| `:2113` | `_options_btn.objectName` | A | 纯内部名称。 |
| `:2115` | `_options_btn.autoRaise` | C | 用户可见 toolbar 样式。 |
| `:2125` | `_tick_density_btn.objectName` | A | 纯内部名称。 |
| `:2126` | `_tick_density_btn.text` | C | icon-only 行为。 |
| `:2139` | `_reset_btn.text` | C | 用户可见 reset 文案。 |
| `:2153` | `_copy_btn.width` | C | 用户可见按钮几何。 |
| `:2204` | `_tick_density_btn.toolTip` | C | 用户可见密度提示。 |
| `:2463` | `_fft_time_card` | A | 锁定内部对象别名。 |
| `:2635` | `_hint_context.full_text` | C | 用户提示文案。 |
| `:2652` | `_hint_context.full_text` | C | 用户提示文案。 |
| `:2840` | `_hint_context.full_text` | C | 用户提示文案。 |
| `:2842` | `_hint_context.full_text` | C | 用户提示轮换。 |
| `:2862` | `_hint_rotation_timer` | B | variable dwell 必须 single-shot。 |
| `:2873` | `_hint_rotation_timer.interval` | B | dwell timing 状态机。 |
| `:2945` | `_hint_context.full_text` | C | 用户提示文案。 |
| `:2969` | `_hint_bar.isVisible` | C | 用户可见 footer。 |

### S4

| 位置 | 属性 | 类 | 理由 |
|---|---|:---:|---|
| `tests/ui/test_analysis_multiview_integration.py:208` | `_empty_hint_item` | C | 用户可见空态提示。 |
| `tests/ui/test_auto_color_span.py:22` | `_AUTO_SPAN_DB` | A | 输出已验证，常量断言冗余。 |
| `tests/ui/test_batch_input_panel.py:129` | `_rows` | C | 可由公开 source rows 查询。 |
| `:533` | `_rpm_row_host` | C | method 切换后的可见性。 |
| `tests/ui/test_batch_output_panel.py:388` | `_spin_image_width` | C | 表单/preset roundtrip 可替代。 |
| `:389` | `_spin_image_height` | C | 表单/preset roundtrip 可替代。 |
| `tests/ui/test_batch_smoke.py:447` | `_body.isVisible` | C | 用户可见 task-list body。 |
| `tests/ui/test_blf_open.py:71` | `_prompt_blf_dbc` | C | 真实 open action 可替代。 |
| `tests/ui/test_file_navigator.py:261` | `_btn_kebab.maximumWidth` | C | 用户可见按钮几何。 |
| `tests/ui/test_inspector.py:1098` | `_collapser_body.isHidden` | C | 默认展开行为。 |
| `:1102` | `_collapser_body.isVisible` | C | 用户可见性。 |
| `:2203` | `_load_btns[4].text` | C | 用户可见 preset 文案。 |
| `:4439` | `_order_nfft_preview` | C | preview label/result 可替代。 |
| `:4567` | `_load_btns[1].property` | C | 用户可见 applied 样式。 |
| `tests/ui/test_main_window_smoke.py:4064` | `_auto_nfft_provider` | A | 后续结果已证明接线。 |
| `tests/ui/test_markup_editor.py:113` | `_background_item.pixmap` | C | crop/export 与 scene rect 可替代。 |
| `:127` | `_background_item.pixmap` | C | undo/export 可替代。 |
| `:211` | `_view.transform` | C | 初始 fit 可公开观察。 |
| `tests/ui/test_slice_amp_floor_guard.py:58` | `_slice_amp_bounds` | C | degenerate slice fallback 可替代。 |
| `tests/ui/test_split_container.py:27` | `_time_split.count` | A | public secondary canvas 已证明两 pane。 |
| `tests/ui/test_split_per_pane_controls.py:154` | `_time_card.plot_mode` | C | 公开 per-canvas mode 可替代。 |
| `:286` | `_secondary_card.cursor_mode` | C | 公开 per-pane mode 可替代。 |
| `:368` | `_pill_secondary.has_detail` | C | 用户可见 pill 内容。 |
| `tests/ui/test_time_filter_overlay.py:146` | `_channel_lines...isVisible` | C | checkbox 后曲线/render 可替代。 |
| `tests/ui/test_timedomain_hotpath_perf.py:146` | `_resize_settle_timer` | B | resize burst 必须唯一 settle。 |
| `tests/ui/test_view_channel_scope.py:307` | `_save_current_channel_config` | C | 保存动作、store 和信号可替代。 |
| `:377` | `_apply_selected_channel_config` | C | 状态、信号和 UI action 可替代。 |
| `tests/ui/test_view_tabbar.py:190` | `_split_clear.isVisible` | C | 用户可见取消按钮。 |
| `:224` | `_split_clear.isVisible` | C | split 更新后的可见行为。 |
| `:720` | `_split_clear.isVisible` | C | 窄宽度下 action 可见。 |

### S5

| 位置 | 属性 | 类 | 理由 |
|---|---|:---:|---|
| `tests/acquisition_ui/test_capture_session.py:37` | `_begin_capture_session` | C | 公开 capture action 可替代。 |
| `tests/acquisition_ui/test_config_path_persistence.py:65` | `_transport_config` | C | settings/chip/roundtrip 可替代。 |
| `:68` | `_transport_config.bitrate` | C | 公开 transport settings 可替代。 |
| `:132` | `_transport_config` | C | corrupt config 后 UI/default 可替代。 |
| `tests/acquisition_ui/test_demo_smoke.py:50` | `_target_fps` | B | watermark→FPS 性能状态机。 |
| `:78` | `_review_modal` | C | 可查询顶层 modal。 |
| `tests/acquisition_ui/test_left_pane.py:133` | `_list.count` | C | 用户可见搜索结果。 |
| `tests/acquisition_ui/test_live_cards.py:345` | `_spark._sample_state` | C | `card.sample_state()` 已提供等价。 |
| `:732` | `_spark.y_ticks_visible` | C | 可渲染验证。 |
| `:750` | `_spark.y_ticks_visible` | C | 可渲染验证。 |
| `:751` | `_spark.sample_count` | C | 公开 buffer/card 状态可替代。 |
| `tests/acquisition_ui/test_pick_a2l_populates_left_pane.py:204` | `_a2l_name` | C | A2L chip/title 可替代。 |
| `tests/acquisition_ui/test_pick_a2l_warnings.py:166` | `_ifdata_xcp` | C | warning/backend gate/status 可替代。 |
| `:205` | `_ifdata_xcp` | C | readiness/backend gate 可替代。 |
| `:253` | `_ifdata_xcp` | C | warning/readiness 可替代。 |
| `tests/acquisition_ui/test_record_backend_swap.py:281` | `_connection_attempt_started` | B | 失败前置不得留下假 attempt。 |
| `:282` | `_stream_start_ts` | B | 失败连接不得留下 stream 状态。 |
| `:560` | `_owns_vector_backend` | B | owned backend 清理责任。 |
| `:595` | `_transport_config` | C | 公开 transport setting 可替代。 |
| `:599` | `_connection_attempt_started` | B | transport change 后必须清生命周期。 |
| `:600` | `_first_frame_ts` | B | disconnect 必须清首帧状态。 |
| `:622` | `_owns_vector_backend` | B | unchanged transport 保留 ownership。 |
| `:658` | `_connection_attempt_started` | B | A2L change 后必须清 attempt。 |
| `:688` | `_left_pane._frozen` | C | enabled 状态和选择拒绝可替代。 |
| `:692` | `_left_pane.current_selection` | C | 用户选择未变化。 |
| `tests/acquisition_ui/test_state_machine.py:268` | `_connection_attempt_started` | B | bad DTO teardown 后清 attempt。 |
| `:521` | `_connection_attempt_started` | B | timeout 后清 attempt。 |
| `:585` | `_connection_attempt_started` | B | deadline 前 attempt 继续存活。 |
| `tests/perf/test_timedomain_pan_perf.py:251` | `_refresh_pending` | B | benchmark 结束必须完成 refresh。 |
| `tests/test_vector_xcp_backend.py:172` | `_run_pyxcp_import_probe` | C | 公开 import-readiness 流程可替代。 |
