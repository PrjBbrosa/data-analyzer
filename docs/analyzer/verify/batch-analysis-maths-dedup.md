# 批处理渲染器 ↔ 中立层：分析数学去重审计

- 基线：`main` @ `6b0a3123`（`fix/render-parity-contract` 合入后，parity 基线可信）。
- 分支：`refactor/batch-render-share-analysis-maths`。
- 对象：`mf4_analyzer/qt_analysis_shared.py`（中立层）与
  `mf4_analyzer/batch_render_qt/_builder.py`（批处理渲染器）之间的三个重复符号。
- 背景：包 B 建中立层时把 GUI 侧的实现搬了过去（`ui/pg_canvas/analysis_axes.py`
  现在只是再导出），但 `_builder.py` 保留了自己手抄的一份，理由写在
  `_builder.py:344-347` 的 `Copied — not imported` 注释里：**批处理渲染器不许
  import `mf4_analyzer.ui`**。中立层的存在正是为了解掉这个理由——它不依赖
  `ui`，`tests/test_batch_render_import_boundary.py` 用子进程守着。

## 审计方法

不靠肉眼比对。`scratchpad/audit_diff.py`（临时脚本，未入库）做两件事：

1. **AST 归一化 diff**——剥掉 docstring、把局部变量/参数 alpha-rename 成位置槽
   （`v0`、`v1`…），再 `ast.unparse` 比对。这样「只改了变量名」的伪差异会被消掉，
   剩下的才是真差异。
2. **差分模糊测试**——同一批输入喂给两侧实现，逐一比对返回值。用例含 14 个手工
   边界（空数组、全 NaN、单值、平坦、±inf、dB 地板 `20*log10(tiny)` ≈ -6153、
   恰好 -200.0 的边界 bin、刚过界的 -200.0001、`1e300` 溢出、`-0.0` vs `0.0`）
   加 4000 条随机数组（长度 0-40，随机掺入死 bin/非有限值），外加 list/tuple/
   int32 等非 ndarray 入参。

## 审计表

| 符号 | 中立层 | `_builder.py` | 实测差异 | 结论 |
| --- | --- | --- | --- | --- |
| `_SLICE_MAX_SPAN_DB` | `:104` | `:348` | 值都是 `200.0`、都是 `float`；**唯一差异是中立层带 `: float` 注解**，`_builder` 裸赋值 | (a) 无意漂移 → 统一到中立层 |
| `_slice_amp_bounds` | `:107-127` | `:351-371` | AST 归一化后**完全相同**；4018 条差分用例 **0 mismatch**。原始文本差异仅为局部变量名（`arr`/`hi`/`lo` ↔ `array`/`high`/`low`）与 docstring 措辞 | (a) 无意漂移 → 统一到中立层 |
| `_SmoothImageItem` | `:130-153`（24 行） | `:674-691`（18 行） | 见下表逐成员拆解 | (a) 无意漂移 → 统一到中立层 |

### `_SmoothImageItem` 逐成员

| 成员 | 比对结果 |
| --- | --- |
| 基类 | 两侧都是 `pg.ImageItem` |
| `__init__` | **逐字节相同** |
| `paint` | AST 归一化后相同（`testRenderHint` → `setRenderHint` → `try/finally` 还原，逻辑与顺序一致） |
| `smooth_transform_enabled` | **中立层独有**，`_builder` 没有。纯增量访问器 |
| `set_smooth_transform` | **唯一实质差异**，见下 |

`set_smooth_transform` 的 diff（归一化后）：

```diff
 def set_smooth_transform(self, enabled: bool) -> None:
-    enabled = bool(enabled)                      # 中立层：幂等早退
-    if self._smooth_transform == enabled:
-        return
-    self._smooth_transform = enabled
+    self._smooth_transform = bool(enabled)       # _builder：无条件
     self.update()
```

**判定：无意漂移，中立层是严格超集，不需要参数/子类吸收。** 理由三条：

1. **两侧最终状态完全一致**。`_smooth_transform` 被赋成同一个 `bool(enabled)`，
   差别只在「值没变时要不要多调一次 `update()`」。`QGraphicsItem.update()` 只是
   排一次重绘，不改变任何要画的内容。
2. **批处理的调用点只调一次，且在入场景之前**。`_builder.py:1997-2001`：
   `_SmoothImageItem(axisOrder="row-major")` 构造后立刻 `set_smooth_transform(...)`，
   之后才 `setImage`（`:2002`）、`setRect`（`:2003`）、`plot.addItem`（`:2004`）。
   所以差异只可能出现在 `interp` 非平滑（`enabled=False`）这一支：中立层因为
   初值就是 `False` 会早退、少一次 `update()`；而那一刻 item 既没有图像也不在
   场景里，`update()` 是空转，随后的 `setImage` 自己会触发重绘。**渲染输出零影响**，
   parity 14/14 + 84/84 是这条判定的实证防线。
3. **`smooth_transform_enabled` 是纯增量**。`_builder` 从不调用它（全仓库搜索：
   只有 `ui/pg_canvas/heatmap_canvas.py`、`tests/ui/` 与 spike 脚本调），多一个
   访问器不会改变批处理行为，反而让批处理侧也可断言。

### 无法判定的差异：**0 处**

任务给的停止阈值是「无法判定 > 2 处」。实测 0 处——三个符号全部是无意漂移，
中立层侧在每一处都是超集或等价。**不触发停止条件，进入阶段 2。**
也没有任何一处需要用参数/子类承接的真实行为分叉。

## 顺带发现：相邻的第四组重复（**本次不动，留作后续**）

`_builder.py` 还有一组与中立层同源的绝对 dB 自动色窗常量/函数：

| 中立层 | `_builder.py` | 空输入行为 |
| --- | --- | --- |
| `_AUTO_SPAN_DB = 30.0` (`:54`) | `_AUTO_SPAN_DB = 30.0` (`:62`) | — |
| `_AUTO_CEILING_PCT = 99.0` (`:65`) | `_AUTO_CEILING_PERCENTILE = 99.0` (`:63`) | 名字不同、值相同 |
| `_auto_db_window` (`:85`) | `_auto_db_color_limits` (`:128`) | **实测有真实差异** |

正常数据两侧输出逐位相同（实测 `linspace(-90,-10,500)` → 两侧同为
`(-40.80000000000001, -10.800000000000011)`）；但**空/全 NaN 输入不同**：
中立层退回 `_finite_data_bounds` 得 `(-29.0, 1.0)`，`_builder` 退回
`_EMPTY_DB_LEVEL` 得 `(-230.0, -200.0)`。批处理侧那个 -200 dB 空态基线是它自己
`_EMPTY_DB_LEVEL` 语义的一部分（另有 `_DISPLAY_DEAD_SPAN_DB` 与之配套）。

这是**任务范围外的第四组**（任务只点名三个符号），且它带真实行为差异，需要单独
决定空态语义归谁。**本次不合并**，按「保留分叉 + 记录理由好过合出 bug」的纪律留档。

## 阶段 2 的落地方式

`_builder.py` 删除三份本地副本，改从中立层导入：

```python
from mf4_analyzer.qt_analysis_shared import (
    _SLICE_MAX_SPAN_DB,
    _SmoothImageItem,
    _slice_amp_bounds,
)
```

- 中立层**函数体一行未动**，也没有新增参数——审计结论是不需要。GUI 侧因此逐字不变。
- 调用点签名不变（`_slice_amp_bounds(stacked)`、`_SmoothImageItem(axisOrder=...)`
  + `set_smooth_transform(...)`），`_builder.py` 其余代码无须改动。
- 导入边界靠 `tests/test_batch_render_import_boundary.py` 的子进程断言守住：
  中立层不得拉起 `mf4_analyzer.ui`。

## 阶段 3 验证（实测结果）

| 项目 | 结果 |
| --- | --- |
| `tools/verify_batch_qt_render_parity.py` | **14/14 PASS**（0 failed） |
| 同上 `--full-matrix` | parity **14/14 PASS** + integration matrix **84/84 PASS**，`status: PASS` |
| `tests/test_batch_render_import_boundary.py` | 4 passed —— 中立层未拉起 `mf4_analyzer.ui` |
| 画布用例（`test_pg_heatmap_canvas` / `test_slice_panel` / `test_slice_amp_floor_guard` / `test_analysis_axes`） | 253 passed |
| `-k batch`（`--ignore=tests/acquisition_ui`） | 1232 passed / 1 failed —— 唯一那条是 CLAUDE.md 既有红 #1 `test_sheet_preview_and_result_share_channel_metadata_reference`，失败集未变 |

### 零像素变化的硬证据

没有靠「断言过了」判定渲染没变，而是**两棵树各跑一次、逐文件哈希**：改动前的树
（`git stash` 掉本次改动）与改动后的树，各自 `--full-matrix` 渲染到独立的 scratch
目录，再比 sha256。

```
PNG artifacts compared: 60
  byte-identical : 60
  differing      : 0
evidence.json（剔除 generated_at / commit_sha / source_state_sha256 / path）: identical
  before: cases 14  matrix 84   status PASS
  after : cases 14  matrix 84   status PASS
```

60/60 逐字节相同 —— 这次去重**一个像素都没动**。

（注：`docs/superpowers/verify/batch-qt-render/` 下入库的 evidence 产物**本次未更新**。
校验一律输出到 scratch 目录，避免给一个不改像素的重构塞进 60 个二进制文件的环境性
churn；入库那份与本机重新生成的产物本就有环境差，重新生成反而会污染上面的对照。）

### 变异测试：证明两侧真的共用同一份实现

只改**中立层** `_slice_amp_bounds` 的函数体（不动常量，这样测的是「函数是否共用」
而不只是「常量是否共用」）：

```diff
-    real = finite[finite >= hi - _SLICE_MAX_SPAN_DB]
+    real = finite[finite >= hi - 20.0]      # 变异
```

一处改动，**两侧同时变红**：

| 侧 | 变异前 | 变异后 |
| --- | --- | --- |
| GUI | 91 passed | **4 failed** / 87 passed：`test_slice_amp_bounds_keeps_a_bin_exactly_at_the_span_limit`、`test_slice_amp_bounds_drops_a_bin_just_past_the_span_limit`、`test_slice_amp_bounds_excludes_db_floor_outlier`、`test_slice_amp_bounds_keeps_real_low_data` |
| 批处理 | 59 passed | **2 failed** / 57 passed：`test_slice_amplitude_axis_ends_on_whole_nice_steps`（视图下沿 `-36.0` → `-22.0`）、`test_slice_amplitude_axis_ignores_the_dc_dead_zone` |

批处理侧的 `-36.0 → -22.0` 是最直接的证据：那条断言读的是
`scene.slice_plot.vb.viewRange()[1]`，值确实跟着中立层的函数体走了。已还原，还原后
150 passed，`git status` 干净。

### 顺带测出来的一件事：parity 抓不到这类改动

变异还在的时候跑 parity，结果**仍是 14/14 PASS**。这不是 bug，是它的定义域：
parity 比的是**批处理侧 vs GUI 参照侧**，而共用实现被改时两侧一起动，差值不变。

结论要记住：**parity 守的是「两侧不许分叉」，`tests/ui/` + `tests/test_batch_render_qt_heatmap.py`
的单测守的才是「绝对行为不许变」。** 去重之后这条分工更重要了——以前两份副本各自
锚住自己的绝对行为，现在只剩一份，绝对行为全靠单测钉住。
