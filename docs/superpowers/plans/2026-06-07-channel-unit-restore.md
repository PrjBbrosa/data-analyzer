# 通道单位恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让时域图各通道重新显示物理单位（Nm / deg / s / deg·sec⁻¹ ...）：① 修 `loader` 让其从 MF4 转换块(CCblock)回退读取单位（主因，影响所有显示模式）；② 修 `pg_canvases` 分屏标签携带并渲染单位（连带潜伏 bug，仅分屏）。

**Architecture:** 两处独立改动。① IO 层：新增 `_resolve_channel_unit` helper，解析顺序 `Signal.unit → channel.conversion.unit → channel.unit`，`load_mf4` 两条读取路径都调用它。② UI 层：`_subplot_label_specs` 由三元组升四元组带上 unit，抽 `_subplot_ylabel_text(name, unit)` 单一真相源，`_bind_channel` 与 `_recheck_subplot_label_placement` 共用。

**Tech Stack:** Python 3.12、asammdf 8.8.16、pandas、PyQt5、pyqtgraph 0.14、pytest（offscreen Qt，`tests/ui/conftest.py` 的 `qapp` 会话 fixture）。

参照设计：`docs/superpowers/specs/2026-06-07-channel-unit-restore-design.md`。

---

## File Structure

- `mf4_analyzer/io/loader.py` — 主因。新增模块级 `_resolve_channel_unit`（紧邻 `unique_mdf_channel_locations`，`loader.py:89` 后）；`load_mf4` 的 `:113`、`:124` 改调用它。
- `mf4_analyzer/ui/pg_canvases.py` — 连带。新增模块级 `_subplot_ylabel_text`（紧邻 `_view_state_channel_key`，`~156`）；改 `_subplot_label_specs` 构建（`1596-1599`）、`_bind_channel` 子图分支（`2086-2089`）、`_recheck_subplot_label_placement`（`5184` 起两分支）、`_subplot_ylabels_need_inside_labels` 解包（`5092`）。
- `tests/_helpers/mf4_factory.py` — 新增 `write_conversion_unit_mf4`：单位只在 CCblock 的合成 MDF。
- `tests/test_mf4_loader.py` — 追加 conversion 回退测试 + 通道块单位仍优先的回归断言。
- `tests/ui/test_pg_timedomain_canvas.py` — 追加分屏外侧/内侧标签含单位断言。

约定（参照现有测试）：canvas 由 `_pg_canvas(qapp)` 构造（`test_pg_timedomain_canvas.py:535`）；`plot_channels` 行元组为 7 元素 `(name, visible, t, sig, color, unit, data_id)`；分屏用 `mode="subplot"`。合成 MDF 走 `tests/_helpers/mf4_factory.py`（`testdoc/` 未入库，不可依赖）。

---

## Task 1: loader 从 conversion 块回退读取单位

**Files:**
- Modify: `tests/_helpers/mf4_factory.py`（新增 builder）
- Modify: `tests/test_mf4_loader.py`（新增 2 个测试）
- Modify: `mf4_analyzer/io/loader.py:89` 后（新增 helper）+ `:113` + `:124`

- [ ] **Step 1: 写失败测试（含合成 MDF builder）**

在 `tests/_helpers/mf4_factory.py` 末尾追加（与现有 `write_single_channel_mf4` 同风格）：

```python
def write_conversion_unit_mf4(
    path: Path,
    *,
    name: str = "trq",
    unit: str = "Nm",
    timestamps: Sequence[float] | np.ndarray = (0.0, 0.01, 0.02, 0.03),
    samples: Sequence[float] | np.ndarray = (1.0, 2.0, 3.0, 4.0),
) -> Path:
    """Write a channel whose unit lives ONLY on the (linear) conversion block.

    Reproduces the Vector-export shape where ``Signal.unit`` reads back empty
    but ``channel.conversion.unit`` carries the physical unit (verified on
    asammdf 8.8.16). Guards DataLoader's conversion-unit fallback.
    """
    t = np.asarray(timestamps, dtype=float)
    y = np.asarray(samples, dtype=float)
    # CC_LIN identity (a=1, b=0); the unit rides on the CCblock, channel unit empty.
    conversion = {"a": 1.0, "b": 0.0, "unit": unit}
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit="", conversion=conversion)])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path
```

在 `tests/test_mf4_loader.py` 顶部 import 行追加 `write_conversion_unit_mf4, write_single_channel_mf4`，并在文件末尾追加：

```python
def test_load_mf4_reads_unit_from_conversion_block(tmp_path):
    mf4 = write_conversion_unit_mf4(tmp_path / "conv_unit.mf4", name="trq", unit="Nm")

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert units["trq"] == "Nm"
    assert df["trq"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])


def test_load_mf4_prefers_channel_unit_over_conversion(tmp_path):
    # write_single_channel_mf4 stores the unit on the channel block (Signal.unit).
    mf4 = write_single_channel_mf4(tmp_path / "chan_unit.mf4", name="v", unit="V")

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert units["v"] == "V"
```

`tests/test_mf4_loader.py` 现有 import 行为 `from tests._helpers.mf4_factory import write_source_path_mf4`，改成：

```python
from tests._helpers.mf4_factory import (
    write_conversion_unit_mf4,
    write_single_channel_mf4,
    write_source_path_mf4,
)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./.venv/bin/python -m pytest tests/test_mf4_loader.py::test_load_mf4_reads_unit_from_conversion_block -v`
Expected: FAIL — `assert '' == 'Nm'`（loader 当前只读 `sig.unit`，为空串）。

- [ ] **Step 3: 实现 conversion 回退**

在 `mf4_analyzer/io/loader.py` 的 `unique_mdf_channel_locations` 定义之后（`:89` 空行后）新增模块级函数：

```python
def _resolve_channel_unit(mdf, sig, group_idx, ch_idx):
    """Channel unit with conversion-block fallback.

    asammdf 8.x returns an empty ``Signal.unit`` when a channel's unit is
    defined only on its conversion block (CCblock) and the channel block's
    own unit field is empty — the common Vector-export case where physical
    units (Nm, deg, s, ...) live on the linear conversion. Earlier asammdf
    releases surfaced the conversion unit through ``Signal.unit``, so reading
    ``sig.unit`` alone silently dropped every unit (regression confirmed
    2026-06-07 on tiaonorth.MF4: 0/24 via ``sig.unit``, 18/26 via this
    fallback).

    Resolution order: ``Signal.unit`` -> ``channel.conversion.unit`` ->
    ``channel.unit``. ``sig.conversion`` is NOT consulted: asammdf 8.8.16
    leaves it ``None`` on the returned Signal for these files.
    """
    unit = str(getattr(sig, 'unit', '') or '')
    if unit:
        return unit
    try:
        channel = mdf.groups[group_idx].channels[ch_idx]
    except Exception:
        return ''
    conversion = getattr(channel, 'conversion', None)
    conv_unit = (
        str(getattr(conversion, 'unit', '') or '')
        if conversion is not None
        else ''
    )
    if conv_unit:
        return conv_unit
    return str(getattr(channel, 'unit', '') or '')
```

把 `load_mf4` 内两处读取改为调用它。`mf4_analyzer/io/loader.py:113`：

```python
                    units[ch_name] = _resolve_channel_unit(mdf, sig, group_idx, ch_idx)
```

`mf4_analyzer/io/loader.py:124`（兼容路径，`group_idx`/`ch_idx` 同在循环作用域内）：

```python
                        units[ch_name] = _resolve_channel_unit(mdf, sig, group_idx, ch_idx)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `./.venv/bin/python -m pytest tests/test_mf4_loader.py -v`
Expected: PASS（含原有 3 个去重测试 + 新 2 个单位测试，共 5 个）。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/io/loader.py tests/test_mf4_loader.py tests/_helpers/mf4_factory.py
git commit -m "fix(io): resolve channel unit from MF4 conversion block (asammdf 8.x fallback)"
```

---

## Task 2: 分屏标签携带并渲染单位

**Files:**
- Modify: `tests/ui/test_pg_timedomain_canvas.py`（新增 2 个测试）
- Modify: `mf4_analyzer/ui/pg_canvases.py`（新增 helper + 4 处改动）

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_pg_timedomain_canvas.py` 末尾追加（`_pg_canvas` 已在本文件 `:535` 定义；`numpy as np` 已导入）：

```python
class TestTimeDomainCanvasPGSubplotUnits:
    """分屏模式 Y 轴标签必须带物理单位（回归：55d8a93e 迁移 pyqtgraph 时丢失）。"""

    def _rows(self, names_units):
        t = np.linspace(0.0, 1.0, 64)
        sig = np.sin(t * 6.28)
        colors = ["#1769e0", "#e07b39", "#2bb673", "#c0392b"]
        return [
            (name, True, t, sig, colors[i % len(colors)], unit, "fid-1")
            for i, (name, unit) in enumerate(names_units)
        ]

    def test_subplot_outside_label_includes_unit(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 420)
        canvas.show()
        qapp.processEvents()
        # 短名 + 宽画布 → 走外侧 AxisItem 标签分支。
        canvas.plot_channels(self._rows([("a", "Nm"), ("b", "deg")]), mode="subplot")
        qapp.processEvents()

        labels = [h.get_ylabel() for h in canvas.axes_list]
        assert any("Nm" in lbl for lbl in labels), labels
        assert any("deg" in lbl for lbl in labels), labels

    def test_subplot_inside_label_includes_unit(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.resize(900, 420)
        canvas.show()
        qapp.processEvents()
        # 长前缀名（以 "[" 开头）→ 强制走内侧 TextItem 标签分支。
        rows = self._rows([
            ("[tiaonorth] Rte_PA_mAtMotorTorque_xds16", "Nm"),
            ("[tiaonorth] Rte_RackPosCorrPlausi_wSteeringAngle_xds16", "deg"),
        ])
        canvas.plot_channels(rows, mode="subplot")
        qapp.processEvents()

        texts = [it.toPlainText() for it in canvas._inside_label_items]
        assert texts, "expected inside-label TextItems for long prefixed names"
        assert any("Nm" in s for s in texts), texts
        assert any("deg" in s for s in texts), texts
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./.venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotUnits -v`
Expected: FAIL — 外侧标签为纯名字 `"a"`（无 `Nm`）、内侧 TextItem 为 `"● [tiaonorth]\nRte_PA_..."`（无 `Nm`），因 `_recheck_subplot_label_placement` 用 name-only 覆盖。

- [ ] **Step 3: 实现单位携带 + 单一真相源**

(3a) 在 `mf4_analyzer/ui/pg_canvases.py` 模块级、`_view_state_channel_key`（`~156`）之前新增：

```python
def _subplot_ylabel_text(name, unit):
    """Subplot left-axis label: compact channel name + ``(unit)`` suffix.

    Single source of truth shared by ``TimeDomainCanvasPG._bind_channel``
    (initial set) and ``_recheck_subplot_label_placement`` (placement
    re-pass) so the unit suffix can never silently diverge between the two
    passes again — the divergence that dropped every subplot unit after the
    pyqtgraph migration (55d8a93e).
    """
    compact = _compact_axis_label(name, unit, max_chars=20)
    return f"{compact}" + (f" ({unit})" if unit else "")
```

(3b) `_subplot_label_specs` 构建携带 unit。`mf4_analyzer/ui/pg_canvases.py:1595-1599` 当前：

```python
            # vis[i] is (name, t, sig, color, unit, data_id); color at idx 3.
            self._subplot_label_specs = [
                (self.axes_list[i], vis[i][0], vis[i][3])
                for i in range(len(vis))
            ]
```

改为：

```python
            # vis[i] is (name, t, sig, color, unit, data_id); color idx3, unit idx4.
            self._subplot_label_specs = [
                (self.axes_list[i], vis[i][0], vis[i][3], vis[i][4])
                for i in range(len(vis))
            ]
```

(3c) `_bind_channel` 子图分支共用 helper。`mf4_analyzer/ui/pg_canvases.py:2086-2089` 当前：

```python
            else:
                compact = _compact_axis_label(name, unit, max_chars=20)
                label = f"{compact}" + (f" ({unit})" if unit else "")
            axis_handle.set_ylabel(label)
```

改为：

```python
            else:
                label = _subplot_ylabel_text(name, unit)
            axis_handle.set_ylabel(label)
```

(3d) `_subplot_ylabels_need_inside_labels` 解包升四元组。`mf4_analyzer/ui/pg_canvases.py:5092` 当前：

```python
        for _handle, name, _color in self._subplot_label_specs:
```

改为：

```python
        for _handle, name, _color, _unit in self._subplot_label_specs:
```

(3e) `_recheck_subplot_label_placement` 两分支渲染单位。`mf4_analyzer/ui/pg_canvases.py:5184` 当前 `for handle, name, color in self._subplot_label_specs:` 改为：

```python
        for handle, name, color, unit in self._subplot_label_specs:
```

内侧分支 `mf4_analyzer/ui/pg_canvases.py:5194-5195` 当前：

```python
                prefix, rest = _split_prefixed_label(str(name))
                label_text = f"{prefix}\n{rest}" if prefix is not None else str(name)
```

改为：

```python
                prefix, rest = _split_prefixed_label(str(name))
                unit_suffix = f" ({unit})" if unit else ""
                if prefix is not None:
                    label_text = f"{prefix}\n{rest}{unit_suffix}"
                else:
                    label_text = f"{str(name)}{unit_suffix}"
```

外侧分支 `mf4_analyzer/ui/pg_canvases.py:5234` 当前 `ax_item.setLabel(text=str(name))` 改为：

```python
                        ax_item.setLabel(text=_subplot_ylabel_text(name, unit))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `./.venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -v`
Expected: PASS（新增 2 个 + 原有用例全绿；确认四元组改动未破坏既有分屏标签/放置测试）。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(ui): keep channel unit on subplot Y labels (carry unit through label specs)"
```

---

## Task 3: 真机视觉验证（手动，非自动）

**Files:** 无（仅运行 + 截图）

- [ ] **Step 1: 启动应用加载真实文件**

Run: `./.venv/bin/python -m mf4_analyzer`（或项目既有启动入口），加载 `testdoc/tiaonorth.MF4`。

- [ ] **Step 2: 叠加模式截图核验**

勾选若干扭矩/转角通道，切「叠」模式，截图。
Expected: 各 Y 轴标签显示 `... (Nm)` / `... (deg)` / `... (deg/sec)`；时间轴 `Time (s)`。

- [ ] **Step 3: 分屏模式截图核验**

切「分」模式，截图。
Expected: 每行 Y 轴（外侧或内侧标签）均带对应单位；与叠加模式单位一致。

- [ ] **Step 4: 记录结论**

把两张截图与「修复前无单位」对比写入验证说明。**不得仅凭单测通过下结论**（lessons `feedback-verify-ui-visually`）。若任一模式仍缺单位，回到对应 Task 重新定位，不要叠加新猜测。

---

## Self-Review

- **Spec coverage：** 方案①→Task 1；方案②（specs 四元组 / helper / 两分支）→Task 2 的 3b-3e；测试→Task 1 Step1 + Task 2 Step1；验收真机→Task 3。游标/统计/导出单位随主因自动恢复（spec 已述），无需独立 task。
- **Placeholder scan：** 每个 code step 均为完整可粘贴代码；命令含预期输出；无 TBD/“类似上文”。
- **Type consistency：** `_subplot_label_specs` 四元组 `(handle, name, color, unit)` 在构建（3b）、`_subplot_ylabels_need_inside_labels` 解包（3d）、`_recheck_subplot_label_placement` 解包（3e）三处一致；`_subplot_ylabel_text(name, unit)` 签名在 3a 定义、3c/3e 调用一致；`_resolve_channel_unit(mdf, sig, group_idx, ch_idx)` 在 Task1 Step3 定义并于 `:113`/`:124` 同签名调用。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-07-channel-unit-restore.md`. Two execution options:

1. **Subagent-Driven (recommended)** — 每个 Task 派新 subagent，Task 间双阶段 review，迭代快。
2. **Inline Execution** — 本会话内按 executing-plans 批量执行 + checkpoint。

二选一即可开工。
