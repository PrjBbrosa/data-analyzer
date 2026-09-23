# MF4 共享时间轴导入 Follow-up Plan

> 执行方式：后续获得实施授权后，使用 `superpowers:executing-plans` 按任务顺序执行；本文件的创建不代表已授权修改产品代码。任务共享 loader 合同，由同一执行者串行完成，不要求多 agent。

日期：2026-09-23

状态：已实施（2026-09-23）。自动测试与 `test1.mf4` 本机加载已核对；前台 Windows toast 截图未执行，该项为未验证。不宣称原生多时基无损导入。

核对基线：`90289a3a`（`fix(io): keep MF4 channels when timestamps are not strictly increasing`）。

**目标：** 保住原修复恢复的 MF4 数值通道，消除错误时间合并，并让共享轴造成的数据处理和覆盖限制可见。

**架构：** 时间整理、对齐策略和结构化诊断仍由 `mf4_analyzer/io/loader.py` 拥有；adapter 透传诊断并复用时间主通道判定；GUI 使用已有导入提示入口。保留三元组返回值和单个公共 `Time` 的兼容合同，不扩展为多时基存储架构。

**技术：** Python、NumPy、pandas、asammdf、现有 PyQt 导入提示及 pytest。

**依据：** [原计划](2026-09-23-mf4-shared-axis-alignment-plan.md)及本次 review 的四个反例。实施本 follow-up 时，下述合同取代原计划中“回退自动排序”“单点无条件共用一行”“共享轴无诊断”和“只修改 adapter 元数据透传”的约定；不回写原计划的历史根因。

## 1. 已知证据与范围选择

| Review 项 | 已观察到的结果 | 本轮处理 |
| --- | --- | --- |
| R1 时间回退 | `t=[0,1,2,0,1,2]` 排序去重后只剩后一段的值 | 检测到回退就明确跳过，不猜测时钟重置或乱序 |
| R2 覆盖范围 | 点数更多的通道覆盖 0–1 s，另一通道覆盖 0–10 s；输出只到 1 s，无诊断 | 保留共享轴，报告裁出范围、重采样及端点填充；完全无重叠通道不生成常数曲线 |
| R3 探测不一致 | 多组文件 probe 含 `time [1:0]`，load 不含 | probe/load 共用按 MDF 类型判定的时间主通道过滤 |
| R4 单点错时 | A 仅在 0 s 有值、B 仅在 10 s 有值，结果合并到 0 s | 单点只有时间完全一致才允许合并；全单点异时文件明确失败 |

真实样本 `C:\Users\hang\Downloads\test1.mf4` 的第 3 组有 5 个 ECU 信号，各 181299 点、两处重复时间戳；原修复能恢复这 5 个通道。该文件只作为可选本机 smoke，不入库、不成为必要测试依赖。上轮 43 项测试通过是历史证据，不是本计划完成证明。

本轮采用**保守修复加诊断**。两个更大方案——取全部时间戳并集、按原生时基拆分 `LoadedSource`——均可能改变采样语义、分析输入和项目身份，暂不实施。因此本计划完成后仍不能宣称“所有原始采样点无损导入”；R2 的验收是限制可见、无重叠不造曲线，不是消除共享轴本身的信息损失。

## 2. 全局约束与目标合同

### 2.1 时间与样本整理

1. 只接受一维实数整数/浮点样本和一维时间轴；输出沿用 float64。字符串、结构化值、多维值、复数不隐式压平或丢虚部，分别记录 `non-numeric` / `non-1d`。不顺带改变其他格式。
2. 先检查形状和等长，再处理数值；长度不符记为 `length-mismatch`。空数组记为 `empty`。不使用截断或 `reshape(-1)` 掩盖坏形状。
3. 非有限时间戳与其对应样本一起移除，统计移除数量；所有时间均不可用则记为 `unusable-time`。样本的 NaN/Inf 保留，不替换为 0，不凭空补有效值。
4. 在剩余时间序列上检查相邻差：只要有 `< 0`，就记为 `time-regression`，不排序、不拼接、不推断“只是轻微回退”。同一组里其余有效通道仍可加载。
5. 无回退时，对完全相等的重复时间戳保留最后一点，保持时间与样本成对；统计被合并的点数。无近似相等容差，不吸收真实的细小时间差。
6. 现有 `prepare_shared_time_series(timestamps, samples)` 保留 `(t, y) | None` 接口；通过同一私有实现取得诊断，不复制整理算法。它对回退返回 `None`，旧的“回退可排序”测试需按新合同改写。

### 2.2 公共轴与单点

1. 从成功整理的通道中按有效点数选最长轴；平手沿用物理通道遍历顺序。诊断记录被选中的物理位置。公共轴只来自实际时间戳，不推算采样率，不生成虚构时间点。
2. 多点通道只有时间轴完全一致才拷贝，否则线性插值。部分重叠仍保留原来的端点保持，但必须记录并提示其使用范围；NaN 样本仍按现有插值行为传播。
3. 对每条已整理的多点通道，计算其原范围与公共轴范围，以及落在公共轴范围之外的输入点数；计算公共轴落在该通道范围之外、需端点填充的输出点数。边界严格比较，不用任意 epsilon 隐藏短尾裁出。
4. 若两者时间区间完全无重叠，记为 `no-time-overlap` 并跳过；禁止产生整段端点常数。区间仅在端点相接仍属重叠，照常记录填充诊断。
5. 公共轴为多点时，单点通道统一记为 `single-sample`，不广播。若所有可用通道均为单点且时间完全一致，保留一行；若时间不同，则整次加载抛出明确的 `ValueError`，说明“单点通道时间不一致，无法在当前共享时间轴下合并”，不返回部分错位结果。
6. 全部通道跳过时，错误消息携带汇总原因及有限数量的通道名，完整明细记入日志；不得仅返回 `No valid numeric data` 而丢失此次诊断。

### 2.3 诊断合同

继续使用 `DataFrame.attrs["source_metadata"]`，保留 `source_kind="mdf"` 和 `skipped_channels=[{"name": ..., "reason": ...}]`。新增 `mf4_alignment` 和已有 UI 能消费的 `warnings: list[str]`；不得自造 `source_warnings` 键。

`mf4_alignment` 结构如下。它是来源处理事实，不是 preset 参数；不包含数组、Qt 对象或运行缓存。物理身份用 `(group, index)`，显示名称只是展示字段。

```python
{
    "policy": "shared-longest-axis-v1",
    "reference_occurrence": [2, 1],
    "output_range": [0.0, 1.0],
    "channels": [
        {
            "name": "slow",
            "physical_occurrence": [3, 1],
            "input_count": 3,
            "prepared_count": 3,
            "nonfinite_time_removed": 0,
            "duplicate_time_removed": 0,
            "time_regression_count": 0,
            "input_range": [0.0, 10.0],  # 有限时间的 min/max；无有限时间用 None
            "outside_reference_count": 2,
            "endpoint_fill_count": 0,
            "alignment": "linear",  # identity / linear / skipped
            "skip_reason": None,
        },
    ],
}
```

未进入数值对齐阶段的 unreadable/non-numeric 等通道仍记录在 `skipped_channels`；无需为其伪造采样统计。`channels` 是进入整理阶段的记录列表，不用显示名作身份字典键。被跳过条目的对齐统计不可计算时用 `None`，不谎报为 0。

`warnings` 按文件汇总成最多三条：时间整理、覆盖/重采样、无法对齐的跳过原因。每条最多展示 3 个通道名，其余显示数量；完整数据留在结构化明细中。涵盖以下事实，而不逐通道弹 toast：

- 重复时间戳保留最后值；移除了多少非有限时间点。
- 已按公共轴重采样；有多少通道的部分时间范围未保留，有多少通道使用端点填充；明确端点填充部分不是原始测量。
- 时间回退、单点或完全无重叠导致的跳过；说明具体原因，避免只有“未导入”名单。

### 2.4 读取与探测边界

- 保留物理通道定位；不能在读取失败后按显示名称重试而读到同名的另一条通道。保留已有 `MDF` monkeypatch seam。
- 仅将已识别的文件/解析异常（如 `OSError`、asammdf 的 `MdfException`）转为 `unreadable`；其他异常传播。异常类型按需导入，不把 asammdf 拉入空启动导入闭包。不以整个 `RuntimeError` 类代表解析错误。
- probe 仍只读元数据；时间主通道按 channel type / sync type 判定，兼容 MDF 2/3 与 4。真实信号恰好叫 `t` 或 `time` 不可仅凭名字删掉。
- 不要求 metadata probe 预判样本回退、全 NaN 或长度错误；它不能为了与 load 完全同表而读取全部样本。本轮一致性指可由元数据确定的时间主通道过滤及身份稳定。
- 保持 `SourceUnavailableError` 的 preview 边界、后续实际 load 重试、`source_id`、`group_id` 和 `_RunReporter` 所有权；不改 Batch orchestration、preset、worker 生命周期。

## 3. Review Focus 与任务归属

| 容易遗漏的输入 | 预期 | Owner |
| --- | --- | --- |
| 回退与重复同时出现，或非有限时间清理后仍回退 | 不排序覆盖；明确跳过 | Task 1 |
| 密集短记录、稀疏长记录及完全异时段 | 裁出/填充可见；无重叠不造常数曲线 | Task 2 |
| 全单点同时间/异时间及混合多点 | 同时间合并、异时间失败、混合单点跳过 | Task 2 |
| 多组 master 重名及名为 time 的真实信号 | 按类型过滤，保留物理身份 | Task 3 |
| 一个文件多种告警、全通道失败 | GUI 真实导入可见且有界，不误报成功 | Task 4 |

## 4. 实施任务

### Task 1：时间整理与读取错误边界（R1）

**修改：** `mf4_analyzer/io/loader.py`。

**测试：** `tests/test_mf4_loader.py`，必要时扩展 `tests/_helpers/mf4_factory.py`。

**接口：** 新增私有 `_prepare_mdf_time_series(timestamps, samples)`，返回 `(prepared, facts)`，`prepared` 为 `(t, y) | None`，`facts` 包含 §2.3 的整理计数及 `skip_reason`。现有公开 helper 包装该函数并只返回 `prepared`；`load_mf4` 消费完整结果并附加物理位置。

- [ ] 先替换旧的回退排序测试，补下面的失败断言；用假 MDF 通道对象测试 asammdf 无法写出的坏长度/坏形状，真实可写边界使用仓内合成 factory。

```python
def test_prepare_shared_time_series_rejects_clock_reset():
    result = prepare_shared_time_series(
        [0, 1, 2, 0, 1, 2], [10, 11, 12, 20, 21, 22]
    )
    assert result is None
```

- [ ] 参数化覆盖相邻重复的 int16/float32/float64、最后值为 NaN、空、全非有限时间、非有限时间成对删除、长度不符、二维和复数。无回退重复案例仍断言正确数值及删除计数。
- [ ] 用至少一条有效通道加一条回退通道验证 `time-regression`，且有效通道数值不变。全回退文件断言可操作错误。
- [ ] 加入读取异常测试：指定物理位置抛 `MdfException` 时不得读取另一同名通道；普通 `ValueError` / `RuntimeError` 必须传播，成功或失败都关闭 MDF。
- [ ] 运行新增 owner 测试确认失败原因，再实现 §2.1 和窄异常边界。保留公开返回接口，不另建通用 DSP 模块。
- [ ] 跑 `tests/test_mf4_loader.py`；边界跑 `tests/test_startup_import_boundary.py` 和 `tests/test_native_import_boundaries.py`，确认未引入 eager parser/native imports。

### Task 2：共享轴覆盖诊断与单点规则（R2、R4）

**修改：** `mf4_analyzer/io/loader.py`。

**测试：** `tests/test_mf4_loader.py`、`tests/test_source_adapters.py`。

**依赖与接口：** 消费 Task 1 的 `(prepared, facts)`；产出 §2.3 的来源 metadata，保留 `(DataFrame, channels, units)`。

- [ ] 添加以下合成用例，先断言当前缺少诊断而失败；断言具体范围与点数，不只断言 metadata 键存在。

```python
def test_load_mf4_reports_reference_range_loss(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "coverage.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, .25, .5, .75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
    ])
    frame, channels, _ = DataLoader.load_mf4(str(path))
    meta = frame.attrs["source_metadata"]
    assert frame["Time"].tolist() == [0, .25, .5, .75, 1]
    assert "slow" in channels
    item = next(x for x in meta["mf4_alignment"]["channels"]
                if x["physical_occurrence"] == [1, 1])
    assert item["input_range"] == [0, 10]
    assert item["outside_reference_count"] == 2
    assert item["alignment"] == "linear"
    assert meta["warnings"]
```

- [ ] 补充部分重叠的端点填充数量与数值、完全无重叠跳过、仅端点相接、参考轴平手稳定、相同点数不同时间正确插值、完全同轴直接拷贝且无伪告警。
- [ ] 补充单点 A@0/B@0 保留一行，A@0/B@10 明确 `ValueError`，单点混合多点记 `single-sample`。沿用 factory 生成独立 channel group。
- [ ] 实现 §2.2 和结构化 metadata；对重采样、删点、裁出、填充生成事实诊断，不把处理后的输出当原始无损数据。
- [ ] 用 `adapter.load_sources` 检查 `LoadedSource.metadata` 与 `file_data.source_metadata` 均保留关键诊断；确认诊断中无数组/对象。继续沿用 adapter 三元组 attrs 读取，不改变五元组优先级。
- [ ] 跑 `tests/test_mf4_loader.py tests/test_source_adapters.py`。此任务不修改 Batch runner，无需触发 reporter 或全量 Batch 测试。

### Task 3：元数据 probe 与 load 统一时间主通道判定（R3）

**修改：** `mf4_analyzer/io/source_adapters.py`，必要时调整 `loader.py` 中共享判定的调用方式。

**测试：** `tests/test_source_adapters.py`、`tests/test_mf4_loader.py`。

**接口：** `_mdf_channel_facts(mdf)` 复用现有 `_is_mdf_time_master(channel, version)`；不复制常量判定，不新增第三方顶层导入。

- [ ] 先用两个普通数值 channel group 写入 MF4，捕获当前 `time [1:0]` 泄漏：

```python
def test_mdf_probe_filters_all_group_time_masters(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "two-groups.mf4", [
        [("a", [1, 2], [0, 1])], [("b", [3, 4], [0, 1])],
    ])
    adapter = SourceAdapterRegistry.default().adapter_for(str(path))
    descriptor = adapter.probe_sources(str(path))[0]
    assert set(descriptor.channel_names) == {"a", "b"}
    assert descriptor.source_id == adapter.load_sources(str(path))[0].source_id
```

- [ ] fake metadata 覆盖 MDF 2/3 time master、MDF 4 master/virtual master、非 time sync master、名为 `t`/`time` 的普通 signal。断言 `_mdf_channel_facts` 不按名字误删；非 time master 是否能数值加载仍由现有格式能力决定。
- [ ] 将 MDF 的样本读取入口替换为会失败的 spy，证明 probe 没有调用它。保留缺失文件翻译 `SourceUnavailableError`、编程错误传播的现有测试。
- [ ] 实施类型过滤并跑 `tests/test_source_adapters.py tests/test_mf4_loader.py`；未修改的 startup/native 边界若 Task 1 已通过且 import seam 未变，不重复跑。

### Task 4：真实 GUI 导入路径和用户说明

**修改：** `mf4_analyzer/ui/main_window/_project_io_mixin.py`（仅在已有 metadata/toast 传递不足时）、`mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`。

**新增测试：** `tests/ui/test_mf4_import_flow.py`。

**复用测试：** `tests/ui/test_project_session.py` 的 source warnings 去重案例。

**接口：** 继续由 `_load_one` 把 `source_metadata` 交给 `_register_file_data`，并调用 `_toast_io_load_diagnostics`；使用现有 `warnings` 消费路径，不新增 MainWindow 状态或提示框架。

- [ ] 新测试使用真实合成 MF4、真实 `MainWindow._load_one`，注册窗口到 `qtbot` 管理其生命周期；只捕获 toast 输出，不 mock loader 或 adapter。

```python
# 以下放入持有 qapp / qtbot / tmp_path 的 test_load_mf4_warns_on_alignment 中。
mw = MainWindow()
qtbot.addWidget(mw)
notices = []
def capture_notice(message, level="info"):
    notices.append((message, level))
monkeypatch.setattr(mw, "toast", capture_notice)
mw._load_one(str(path))  # path 用 Task 2 的 coverage fixture 生成
assert any(level == "warning" and "时间范围" in message
           for message, level in notices)
```

- [ ] GUI 用例覆盖重复时间恢复成功并提示处理事实、部分覆盖限制、回退通道原因、全单点异时文件的错误路径。错误路径不得新增成功文件或显示“已加载”；预先捕获应用错误显示出口，避免阻塞式对话框。
- [ ] 多通道输入验证摘要最多三条 alignment warning、重复 metadata 不重复发同条告警；保留现有 skipped 名单行为，不改变其他格式的提示。
- [ ] 同步 hints/quickref 的 MF4 导入说明：共享轴重采样、重复时间保留最后值、回退拒绝、范围与填充提示。无新控件、无新偏好项，不改产品版本。
- [ ] 跑新增 UI owner 文件及现有 warning 去重测试；若 mixin 有改动，再跑 state ownership 与 UI import boundary。
- [ ] 用运行中的 Windows 应用打开合成覆盖用例，检查实际 toast 文本、长名称布局、错误后的文件列表。截图放 `.state/`；offscreen 测试不可代替此项，未执行则明确标为未验证。

### Task 5：验收与范围复核

- [ ] 按 §3 表逐项核对已实施合同与测试。原“回退可排序”测试已被新合同替换，不保留互相矛盾的断言。
- [ ] 复用各任务在稳定代码上的通过结果；只因后续相关改动或失败重跑对应门禁，记录原因。没有全量测试 gate，也不运行整个 `tests/ui`。
- [ ] 本机若存在 `test1.mf4`，做一次可选 smoke：恢复 Msteer 与 5 个 ECU 信号、两个空配置通道记 `empty`、master 不出现、重复整理可见、覆盖/填充事实与原时间范围一致。缺文件应 skip；不捏造该文件上的完成证据。
- [ ] 最终报告区分：通道恢复、保守拒绝、共享轴限制、自动测试、前台 UI。不能把本计划表述为原生多时基无损导入。
- [ ] 检查 `git diff --check`、修改范围与 lessons 状态；只提交实施者自己的授权改动，不纳入其他会话变更。

## 5. 门禁执行方式

Windows 项目运行时示例（每条命令在对应任务完成时执行，不把下面当作最终全量重跑清单）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = '.'
& .venv/Scripts/python.exe -m pytest tests/test_mf4_loader.py tests/test_source_adapters.py -q
& .venv/Scripts/python.exe -m pytest tests/test_startup_import_boundary.py tests/test_native_import_boundaries.py -q
& .venv/Scripts/python.exe -m pytest tests/ui/test_mf4_import_flow.py tests/ui/test_project_session.py::test_toast_io_load_diagnostics_surfaces_and_dedupes_source_warnings -q
# 仅 Task 4 修改 mixin 时追加：
& .venv/Scripts/python.exe -m pytest tests/ui/test_main_window_state_ownership.py tests/ui/test_import_boundaries.py -q
git diff --check
```

Linux/macOS 等价使用 `.venv/bin/python`，Qt 自动测试设置 `QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。前台验证使用正常 Windows 平台，不携带 offscreen 环境变量。临时证据统一放 `.state/`。

本次**计划文件写作**只检查引用、合同一致性、scope 与 whitespace；未修改运行行为，不需要重跑上述 runtime gate。新增测试名称与 metadata 合同均为待实施内容，不代表现在已存在或已通过。
