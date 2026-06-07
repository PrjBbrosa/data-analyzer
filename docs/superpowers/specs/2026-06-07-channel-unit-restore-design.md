# 通道单位全部丢失 — 根因与修复设计

日期：2026-06-07
分支：docs/timedomain-view-tabs-plan
状态：根因已用真机数据确认，方案待实现（用户要求先出 spec/plan，尚未改代码）
关联实现计划：`docs/superpowers/plans/2026-06-07-channel-unit-restore.md`

## 背景

用户在时域视图（pyqtgraph 后端 `TimeDomainCanvasPG`，叠加模式）反馈：**所有通道的 Y 轴
都没有单位了**（s / Nm / N / rpm / deg / deg·s⁻¹ 全部消失），并明确「以前是有的」。要求
跨绘图链路详细 review，先分析不要改。

复现文件：`testdoc/tiaonorth.MF4`（MDF 4.10，25 通道，100 Hz，208.66 s）。
运行环境：项目 `.venv`，`asammdf 8.8.16`，`pyqtgraph 0.14.0`，PyQt5。

> 注意：`testdoc/` **未入库**（`git ls-files testdoc/` 为空），不能作为测试 fixture 依赖。

## 单位的完整数据流（各模块职责）

```
MF4 文件 (CCblock 里存单位)
  └─ io/loader.py:113/124   units[ch] = str(getattr(sig,'unit','') or '')   ← 源头读取
       └─ io/file_data.py:24   fd.channel_units = units                     ← 数据模型
            └─ ui/main_window.py:1593   unit = fd.channel_units.get(ch,'')   ← 取用
                 └─ data tuple 第5位 (name,True,x,sig,color,unit,fid):1604
                      └─ ui/pg_canvases.py  plot_channels → _bind_channel    ← 渲染
```

源头 → 数据模型 → 取用 三段逐行核对均完好；问题出在**首尾两端**：① `loader` 读单位的
方式（主因）；② `pg_canvases` 分屏标签渲染（连带潜伏 bug）。

## 复现与证据（已用 .venv 运行时证据确认）

对 `testdoc/tiaonorth.MF4` 用三种方式读同一扭矩通道 `Rte_PA_mAtMotorTorque_xds16`：

| 读取路径 | 结果 |
|---|---|
| `mdf.get(group,index).unit`（即 loader 现读的 `sig.unit`） | `''` |
| `channel.unit`（通道块自身 unit 字段） | `''` |
| **`channel.conversion.unit`（CCblock 转换块）** | **`'Nm'`** ✅ |
| `sig.conversion`（Signal 上的 conversion 属性） | **`None`**（不可用） |

全通道扫描 `conversion.unit`，**单位一个不少全在 CCblock 里**：

```
 s          t / t[1:0] / t[2:0] / t[3:0]
 Nm         12 个扭矩通道（*MotorTorque* / *TorsionBar* / TLC / FricComp / InCo / SteerCtrl ...）
 deg        Rte_RackPosCorrPlausi_wSteeringAngle_xds16
 deg/sec    Rte_RotationSpeedCalculation_vSteeringAngleSpeed_xds16
 km/h/10ms  Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16
```

- 现状（`sig.unit` 路径）：**0 / 24** 个通道有单位。
- 加 `conversion.unit` 回退后：**18 / 26** 个通道有单位；剩余 8 个（Comment、cPCBTemp、
  cMcuTemp、cNtcTemp 等）在文件任何层都无单位，属文件自身缺失，非本 bug。

## 已证伪的错误假设

- ❌ **「叠加模式的标签代码丢了单位」**——错。`_bind_channel` 叠加分支
  `pg_canvases.py:2085` 调 `_overlay_axis_label`（`2103-2108`）会拼 ` (unit)`；
  `_refresh_overlay_axis_labels:2189` 用 `channel_data[name][3]==unit` 重建，也正确。
  叠加路径**无 bug**，单位为空纯粹是因为 `loader` 给的 unit 是空串。
  （本假设最初基于「读代码」得出，被用户截图 + 真机数据直接推翻——教训：单位/视觉问题
  必须验真机，见 lessons `feedback-verify-ui-visually`。）
- ❌ **「通道名 key 不匹配导致 `channel_units.get(ch)` 取空」**——错。`loader.py:112-113`
  里 `sigs[ch_name]` 与 `units[ch_name]` 用同一 `ch_name`，`data` 列名亦同源；headless
  实测取到的 unit 确实是 `''`，不是 KeyError 落空。
- ❌ **「文件本来就没单位 / 用户记错」**——错。`conversion.unit` 扫描证明单位实际存在。

## 真正根因

### 主因（IO 层，影响全部显示模式）

`io/loader.py:113` 与 `:124` 只读 `str(getattr(sig, 'unit', '') or '')`。
**asammdf 8.x 行为变化**：当通道块自身 unit 为空、单位仅定义在转换块（CCblock）上时，
`mdf.get().unit` **不再回退到 `conversion.unit`**；早期 asammdf 会把 CCblock 单位带进
`Signal.unit`。Vector 导出的 MF4 普遍把物理单位（Nm/deg/s/...）放在线性转换块上，于是
`loader` 读到的全是空串 → `fd.channel_units` 全空 → **叠加/分屏/单通道三种模式、所有通道
都没单位**，与「全没了」完全吻合。这是一个真·回归，根因在 loader，与绘图模块无关。

注意 `sig.conversion` 在 8.8.16 上返回 `None`（已实测），单位只能经
`mdf.groups[g].channels[i].conversion.unit` 取到。`loader` 两条读取路径（`107-116` 主路径、
`118-129` 兼容路径）都在同一循环内、`(group_idx, ch_idx)` 均在作用域，可统一用 group/index 解析。

### 连带潜伏 bug（UI 层，仅分屏模式）

即使主因修好，**分屏(分)模式仍不显示单位**。`pg_canvases.py:1596-1599` 构建
`_subplot_label_specs` 时取的是 `vis[i][3]`（=color），**漏取 `vis[i][4]`（=unit）**，
元组退化为 `(handle, name, color)`。随后 `_recheck_subplot_label_placement`（`5172`）在
`_bind_channel` 之后重写左轴标签：
- 外侧分支 `:5234` `ax_item.setLabel(text=str(name))` —— 纯名字，覆盖了带单位的标签；
- 内侧分支 `:5194-5197` `label_text` 同样只用 name。

`git blame` 确认这两处出自 `55d8a93e (2026-05-28) feat(ui): migrate TimeDomain chart to
pyqtgraph renderer`——迁移时漏移植了 matplotlib 旧实现里的单位 chip（`canvases.py:738-748`
经 `_set_series_ylabel(..., unit=unit)` 绘制）。病根是**子图标签格式化有「两个真相源」**
（`_bind_channel` 一套、`_recheck_subplot_label_placement` 一套），极易再次分叉。

## 影响范围（逐路径核对）

| 模式 | 修主因前 | 仅修主因后 | 主因+连带都修后 |
|---|---|---|---|
| 单通道 | ❌ 无单位 | ✅ 有 | ✅ 有 |
| 叠加 overlay | ❌ 无单位 | ✅ 有 | ✅ 有 |
| 分屏 subplot | ❌ 无单位 | ❌ 仍无（连带 bug） | ✅ 有 |

附：游标读数（`pg_canvases.py:4973`）、统计条（`main_window.py:1605`）、导出
（`pg_canvases.py:3813`）里的 unit 取自 `channel_data`，主因修好后**自动恢复**，无需单独改。
分屏底部 X 轴 `Time (s)` 走独立路径（`main_window.py:1614` 硬编码），不受影响。

## 方案

### 方案 ①（主因 / 必修）：`loader` 单位 conversion 回退

新增模块级 helper `_resolve_channel_unit(mdf, sig, group_idx, ch_idx)`，解析顺序
`Signal.unit` → `channel.conversion.unit` → `channel.unit`，空则 `''`。`loader.py:113`、
`:124` 两处改为调用它。`load_csv` / `load_excel`（`:160` / `:168` 返回 `{}`）无 CCblock
概念，**不在 scope**。

### 方案 ②（连带 / 同批修）：分屏标签携带并渲染单位

1. `_subplot_label_specs`（`1596-1599`）改为四元组 `(handle, name, color, unit)`，取
   `vis[i][4]`。
2. 同步两处解包：`_subplot_ylabels_need_inside_labels:5092`、
   `_recheck_subplot_label_placement:5184` 改四元组。
3. 抽模块级 helper `_subplot_ylabel_text(name, unit)`（= `_compact_axis_label(name,unit,20)`
   + ` (unit)`），让 `_bind_channel` 子图分支（`2087-2088`）与 `_recheck` 外侧分支
   （`5234`）**共用同一真相源**；内侧分支（`5194-5197`）把 ` (unit)` 追加到 rest/name 行。

### 不做（YAGNI）

- 不动 `_overlay_axis_label`（叠加已正确）。
- 不重构 asammdf 读取主流程、不升/降 asammdf 版本（回退方案对各版本都健壮）。
- 不为「8 个文件本身无单位的通道」编造单位。

## 测试

- IO（`tests/test_mf4_loader.py` + `tests/_helpers/mf4_factory.py` 新增
  `write_conversion_unit_mf4`）：合成「unit 只在 CCblock」的 MDF（`Signal(unit='',
  conversion={'a':1.0,'b':0.0,'unit':'Nm'})`，已实测可复现 `sig.unit=='' /
  conversion.unit=='Nm'`），断言 `DataLoader.load_mf4` 解析出 `'Nm'`；并保留「unit 在通道块
  时仍优先」的回归断言。
- UI（`tests/ui/test_pg_timedomain_canvas.py`）：分屏外侧标签 `handle.get_ylabel()` 含单位；
  分屏内侧标签（长前缀名触发 inside）`canvas._inside_label_items[i].toPlainText()` 含单位。

## 验收

- `pytest tests/test_mf4_loader.py tests/ui/test_pg_timedomain_canvas.py` 全绿。
- **真机验证**（本次教训，必须）：加载 `testdoc/tiaonorth.MF4`，叠加与分屏两模式各截图，
  确认扭矩通道显示 `(Nm)`、转角 `(deg)`、角速度 `(deg/sec)`、时间轴 `s`。不得只凭单测过 +
  「属性已设」下「修好」结论。
