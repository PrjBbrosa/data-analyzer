# 近期提交与 BLF / DBC / 通道 UI 工作审查报告

日期：2026-07-23
审查方式：代码与提交审查、当前工作树审查、专项 pytest、真实 BLF/DBC 只读计时、Qt 离屏渲染复核
结论：**NEEDS REVISION（方向正确，核心功能大体到位，但尚不能判定完成或直接合并）**

## 1. 执行摘要

本轮工作已经把用户反馈中的主要交互和性能问题覆盖到了：

- 多个 BLF 在同一次导入动作中可以统一选择 DBC，下一次导入会重新确认；
- BLF 原始帧在“候选校验 → 正式解码”之间复用，避免同一文件重复读取；
- DBC 不匹配时不会静默套用错误数据库；
- 文件加载和时间域绘图都接入了底部确定型进度显示；
- CRC/滚动计数器类高变化信号增加了几何型 envelope 上限，原始数据不被改写；
- 通道树选中行的勾选框、色标、点数和眼睛列已固定锚点；
- 通道配置栏的保存/选择/应用高度统一，按钮宽度收窄；
- 批量 DBC 弹窗按钮文字已通过离屏渲染确认不截断。

但目前仍有两个发布级问题：

1. 自动匹配 DBC 仍会在 GUI 主线程对所有历史候选逐帧扫描；候选最多 20 组，而且同一 DBC 集合仅因路径顺序不同就会重复扫描。真实 27 MB BLF 上，单次强匹配校验约 1.41 秒，因此“DBC 选择框弹出前卡住”仍然存在并会随历史候选线性放大。
2. 更宽的通道树回归集仍有 12 个失败。11 个是 View 附加语义落地后旧测试未同步，另 1 个是 macOS/PyQt 下不可靠的 `QMessageBox.windowTitle()` 断言。专项新用例通过不能替代这组回归失败。

因此建议先完成“DBC 候选限流/去重 + 回归测试契约修复”，再把当前工作树按主题拆分提交。

## 2. 审查范围与基线

### 2.1 已提交工作

当前分支为 `main`，`HEAD` 与 `origin/main` 同步在：

- `014513b6 feat(ui): manage saved channel configurations`

本次重点审查的提交链为 `84376e91..014513b6`，共 13 个提交，主要包括：

- View 文件附加状态持久化、按聚焦 View 投影通道树；
- 文件拖入/自动加入当前 View；
- 可复用通道配置的保存、应用、管理；
- View 删除及标注清除的破坏性确认；
- 自动加入说明、帮助分页和配置管理 UI。

该提交链相对 `2fd964be` 共涉及 35 个文件，约 `4631 insertions / 90 deletions`。最新提交 `014513b6` 单独涉及 11 个文件，约 `916 insertions / 88 deletions`。

### 2.2 尚未提交的工作

当前工作树不是干净状态：18 个已跟踪文件被修改，另有 7 个未跟踪文件。已跟踪 diff 约为 `1251 insertions / 106 deletions`，同时包含：

- BLF 读取、DBC 候选与批量导入；
- 文件加载与绘图进度；
- CRC 类高变化 envelope；
- 通道树 delegate 与配置栏尺寸；
- 共轴双游标极值标记；
- QMessageBox 按钮宽度；
- 多组测试和 lessons 文档。

这些变更尚未形成一个可独立回滚、可清晰归因的提交边界。

## 3. Findings（按严重度排序）

### [P1] DBC 自动候选仍是 `候选数 × 全部帧数` 的 GUI 主线程扫描

证据：

- 历史候选上限为 20 组：`mf4_analyzer/ui/main_window/_project_io_mixin.py:33-34`。
- 候选身份直接使用路径顺序，未按集合去重：`mf4_analyzer/ui/main_window/_project_io_mixin.py:517-518`。
- 最近历史全部加入候选，之后再加入附近 DBC：`mf4_analyzer/ui/main_window/_project_io_mixin.py:578-602`。
- 每个候选都对已经读取的全部帧调用一次 probe：`mf4_analyzer/ui/main_window/_project_io_mixin.py:604-640`。
- 多候选对话框只保留候选发现顺序，默认选中第 1 项，没有按 strong/weak 或解码覆盖率排序：`mf4_analyzer/ui/main_window/_project_io_mixin.py:688-695`、`974-996`。

当前机器的只读检查发现 3 组有效历史候选，其中两组分别是：

- `T1TP_2503.DBC + TestRunOutput(1).dbc`
- `TestRunOutput(1).dbc + T1TP_2503.DBC`

它们是同一集合的不同排列，却会重复做完整扫描。

真实数据计时（当前 `.venv`，`0kph_50-6.blf`，27,988,880 bytes，611,013 帧）：

| 阶段 | 结果 | 耗时 |
|---|---:|---:|
| 读取 BLF | 611,013 帧 | 1.414 s |
| `T1TP_2503.DBC` probe | strong，567,387 帧，177 信号 | 1.409 s |
| `T1TP_2503.DBC` decode | 53,935 行，177 通道 | 2.168 s |
| `TestRunOutput(1).dbc` probe | weak，43,626 帧，3 信号 | 0.148 s |

用户影响：确认 DBC 的窗口要等所有候选扫描完才出现；历史候选越多越卡。即使复用了 BLF 帧，也只消除了重复磁盘读取，没有消除重复逐帧解码校验。

建议：

1. 候选身份按“规范化路径集合”去重，显示顺序与集合身份分离；
2. 自动 probe 只检查最近 3–5 组，附近 DBC 先用 CAN ID 交集做低成本预筛；
3. 找到高覆盖 strong 候选后允许提前停止，其他候选改为用户主动展开后再校验；
4. 候选按覆盖率/strong 优先排序，不让 weak 历史项成为默认值；
5. 长 probe 移出 GUI 主线程或至少支持取消。

### [P1] 通道树回归集仍有 12 个失败，当前状态不能按“全绿”交付

命令：

```text
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_channel_widget.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_timedomain_hotpath_perf.py
```

结果：

```text
12 failed, 381 passed, 1 deselected in 12.93s
```

其中 11 个失败的共同原因是：产品代码已要求文件先附加到当前 View，旧 `test_channel_widget.py` 仍只调用 `add_file()`。产品代码会隐藏未附加文件、禁用通道操作，并且只恢复附加文件的勾选状态：

- `mf4_analyzer/ui/widgets/__init__.py:647-660`
- `mf4_analyzer/ui/widgets/__init__.py:716-727`
- `mf4_analyzer/ui/widgets/__init__.py:1213-1223`
- `mf4_analyzer/ui/widgets/__init__.py:1354-1389`

另 1 个失败是 `tests/ui/test_channel_widget.py:453-478` 在 macOS/PyQt 上、消息框真正 show 之前断言 `windowTitle()`；本机直接构造 `QMessageBox` 也返回空标题，因此该测试不是稳定的跨平台证据。

判断：这 12 个失败不等价于 12 个产品逻辑 bug，但它们证明提交链没有同步关闭旧测试契约。应把相关 widget 测试统一改为显式 `set_attached_file_ids()`，并将消息框标题改成 show 后验证或验证创建逻辑，不应简单删除断言。

### [P2] BLF 进度仍有两个“不符合实际工作量”的断点

第一处是无 DBC 的原始 BLF：

- `_raw_blf_channels()` 拆 payload byte 并组装共享时间轴，但没有接收/转发 progress callback：`mf4_analyzer/io/loader.py:430-456`。
- `load_blf_frames(..., dbc_paths=None)` 直接进入该无进度分支：`mf4_analyzer/io/loader.py:486-503`。
- `load_blf()` 把读取阶段固定映射为 0–40%，后续映射为 40–100%：`mf4_analyzer/io/loader.py:648-679`。

结果是原始 BLF 会在读取完成后停在约 40%，待 byte 通道组装结束后突然完成。

第二处是单 BLF 的 DBC 自动候选：所有候选 probe 被压缩在文件进度的 45–55% 区间：`mf4_analyzer/ui/main_window/_project_io_mixin.py:388-395`。真实数据上单次 strong probe 与读取阶段耗时近似，但 UI 权重分别是 10% 与 40%；有多个候选时偏差会进一步放大。

建议按实际阶段建立动态总工作量：读取 bytes + `候选数 × frames` + decode frames + assemble signals。若格式库无法提供细粒度回调，应明确显示“不确定阶段”，不要用固定百分比假装精确。

### [P2] 混合格式的一次导入会改变用户给出的文件顺序

当一次动作里有至少两个 BLF 时，代码先抽出并批量处理全部 BLF，再遍历加载非 BLF：`mf4_analyzer/ui/main_window/_project_io_mixin.py:150-183`。

例如输入顺序为 `CSV-A, BLF-B, CSV-C, BLF-D`，实际登记顺序会变成 `BLF-B, BLF-D, CSV-A, CSV-C`。这会影响左侧文件列表顺序和后续依赖插入顺序的操作。现有 `tests/ui/test_blf_batch_import.py` 只覆盖纯 BLF 批次，没有覆盖混合格式顺序。

同一段代码还用 `{str(path): index}` 记录 BLF 位置：`mf4_analyzer/ui/main_window/_project_io_mixin.py:150-165`。如果一次输入包含重复路径，进度只会映射到最后一次出现的位置。文件选择器通常不会制造重复项，但拖放/程序调用仍可触发。

建议将一次用户动作表示为有序任务列表；BLF 只共享“本次 DBC 策略”，不应通过先重排全部 BLF 才实现批量策略。

### [P2] 批量 DBC 不匹配弹窗的“剩余数量”在最后一个文件会显示错误

调用处传入的是“当前文件之后的数量”：

- `len(paths) - index - 1`：`mf4_analyzer/ui/main_window/_project_io_mixin.py:823-825`

弹窗文案却写成：

- `当前及后续 {remaining_count} 个 BLF`：`mf4_analyzer/ui/main_window/_project_io_mixin.py:879-882`

因此在最后一个文件不匹配时会显示“当前及后续 0 个 BLF”，与实际仍需处理当前文件矛盾。

建议改为“为当前文件重选，并应用到后续 N 个 BLF”；当 `N == 0` 时只显示“为当前文件重选”。

### [P3] 通道配置管理器的显式空选择无法清除现有选择

`ChannelConfigManagerDialog.set_configs()` 使用：

```python
self._selected_ids = (requested or self._selected_ids) & valid
```

见 `mf4_analyzer/ui/widgets/channel_config_manager.py:219-229`。

这会把“调用者明确传入空集合”与“调用者没有提供新选择”混为一谈。当前主调用链在删除后通常因 `valid` 集合变化而被动清掉已删除项，因此暂未形成明显用户故障，但 API 语义有陷阱，且没有覆盖“显式清空但配置仍有效”的测试。

建议用 `selected_ids=None` 表示保留选择，空 iterable 表示明确清空。

## 4. 已确认到位的部分

### 4.1 DBC 作用域与错误处理

- 本次批量使用的 `dbc_paths` 是 `_load_blf_batch()` 的局部变量，不会跨下一次导入动作继承：`mf4_analyzer/ui/main_window/_project_io_mixin.py:716-759`。
- 每个 BLF 只持有一份当前文件 frames；校验通过后把相同 frames 交给 decode：`mf4_analyzer/ui/main_window/_project_io_mixin.py:763-810`。
- 不匹配时提供重选、跳过、停止，不会用错误 DBC 静默登记数据：`mf4_analyzer/ui/main_window/_project_io_mixin.py:823-842`。
- 正式登记的数据会记录 `source_kind=blf` 和 `dbc_paths`：`mf4_analyzer/ui/main_window/_project_io_mixin.py:409-417`。

### 4.2 CRC 类通道卡顿修复

- 检测依据是实际 envelope 的高变化几何，不依赖通道名或 BLF 文件类型：`mf4_analyzer/ui/pg_canvas/renderer.py:131-186`。
- 首帧 bind 和后续 viewport refresh 都应用同一类上限：`mf4_analyzer/ui/pg_canvas/overlay_axes.py:298-337`、`mf4_analyzer/ui/pg_canvas/renderer.py:554-582`。
- 回归用例确认显示 envelope 被限制，而 `channel_data` 仍引用原始 5,727 点数组：`tests/ui/test_high_variation_envelope.py:29-58`。

残余风险：当前阈值主要由合成随机 byte、smooth sine 和一张真实 BLF 离屏图证明；尚没有对“高噪声但需要观察单样本跳变的物理信号”建立视觉误差/SLA 测试。它不是当前 blocker，但后续应补一组真实信号对照和选择到首帧的耗时阈值。

### 4.3 通道树与配置栏 UI

离屏渲染已确认：

- 选中行与普通行的 checkbox、swatch、文字、Pts、眼睛使用固定列锚点；
- 保存、选择框、应用三者高度一致；
- 保存/应用宽度收窄为 64 px，中间选择框获得剩余空间；
- 批量 DBC 三个按钮文字完整显示。

对应回归覆盖：

- `tests/ui/test_file_navigator.py:163-220`
- `tests/ui/test_channel_config_bar.py:123-166`
- `tests/ui/test_blf_batch_import.py:103-156`

证据级别说明：上述是 Qt 离屏截图和几何断言，不是本轮在用户当前桌面上重新点击的 live-app 证据。

### 4.4 绘图进度

- 底部组件现在显示百分比：`mf4_analyzer/ui/compute_progress.py:30-64`。
- 时间域绘图拆成准备、构建、应用三个区间，并用样本数推进准备/绑定阶段：`mf4_analyzer/ui/main_window/window.py:2518-2574`、`2650-2775`。
- 进度刷新只同步 repaint 小组件，没有在绘图中反复 drain 全部 Qt 事件：`mf4_analyzer/ui/main_window/window.py:387-406`。
- canvas bind 阶段按每条 trace 的样本量推进：`mf4_analyzer/ui/pg_canvas/canvas.py:533-652`。

这已经明显优于原来“固定在一半然后结束”的装饰性进度，但阶段权重仍是经验值，不能据此宣称达到严格 ETA 精度。

## 5. 测试与证据汇总

### 5.1 通过

BLF、DBC、配置管理、进度和 CRC 专项：

```text
86 passed in 23.06s
```

包含：

- `tests/test_blf_loader.py`
- `tests/ui/test_blf_open.py`
- `tests/ui/test_blf_batch_import.py`
- `tests/ui/test_compute_progress.py`
- `tests/ui/test_compute_progress_integration.py`
- `tests/ui/test_high_variation_envelope.py`
- `tests/ui/test_channel_config_bar.py`
- `tests/ui/test_channel_config_manager.py`
- `tests/ui/test_view_channel_scope.py`

更宽回归命令中，除通道 widget 的 12 个问题外，其余 381 个通过，覆盖 file navigator、pyqtgraph time-domain canvas、共轴双游标极值和 hotpath。

`git diff --check`：通过，无空白错误。

### 5.2 未完成的验证

- 没有宣称全仓 pytest 通过；本轮实际发现相关回归集仍有 12 个失败。
- 没有在本轮重新进行用户桌面 live-app 点击录屏；UI 结论来自离屏 Qt 渲染。
- 没有验证 20 个有效 DBC 历史候选的最坏耗时，但代码上限和单候选真实计时足以证明线性放大风险。
- 没有验证 Windows/Linux 下 QMessageBox 标题测试表现。

## 6. 建议收口顺序

### 阶段 A：先关闭发布阻断项

1. DBC 候选按集合去重、限制自动 probe 数量、strong 优先并允许提前停止；
2. 把 probe 移出 GUI 主线程，或至少提供取消；
3. 同步 `test_channel_widget.py` 的 View 附加契约，修复 QMessageBox 跨平台断言；
4. 补混合格式顺序、重复路径、最后一个 mismatch 文案、无 DBC progress 的失败用例。

### 阶段 B：修正真实性和边界逻辑

1. 为 raw BLF assemble 增加 progress callback；
2. 按候选数和帧数动态计算 DBC probe 工作量；
3. 保持用户输入文件顺序；
4. 修复 mismatch 剩余数量文案；
5. 明确配置管理器 `None` 与空选择的语义。

### 阶段 C：按主题拆分提交并复验

建议至少拆成：

1. `fix(blf): bound and dedupe dbc candidate probing`
2. `feat(ui): report truthful file and plot progress`
3. `fix(ui): align channel tree and channel config controls`
4. `perf(plot): cap high-variation envelope rendering`
5. `fix(plot): retain coaxis cursor extrema`

6. `test(ui): align channel widget tests with view attachments`

每个提交运行对应专项；最后再跑相关 UI 回归集，目标至少恢复到 `0 failed` 后才能标记完成。

## 7. 最终判断

本轮不是“没做完”，而是“主要功能已经实现，但验证闭环和最坏路径还没有收口”。

- **功能方向：到位。** 本次/下次 DBC 作用域、单文件帧复用、不匹配保护、UI 对齐和 CRC 渲染策略都符合目标。
- **性能闭环：部分到位。** CRC 选择卡顿已针对绘制几何优化，但 DBC 候选扫描仍是明显主线程瓶颈。
- **进度真实性：部分到位。** 绘图已有分阶段真实推进；raw BLF 与多候选 probe 仍会跳变或长时间挤在窄区间。
- **交付质量：未到位。** 当前工作树过宽且相关回归集有 12 个失败，不应直接一次性提交或宣称完成。

建议结论保持为 **NEEDS REVISION**，先做阶段 A，再进行一次小范围复审。

## 8. Implementation Addendum — CRC AA Root Cause Correction

后续用户前台复测证明，第 4.2 节只能说明 envelope 上限已落地，不能说明
CRC 卡顿已关闭。对同一真实 `EPS_CRC1` 隔离 AA 后，AA off repaint 约
2.23 ms，而 AA on + NoCache 约 1,044 ms，DeviceCoordinateCache 下平均仍约
302 ms、最坏约 1 s。主因是通用 idle-AA gate 只看 cap 后约 714 个点，错误
认为低于 12,000 点预算即可开启 AA。

实现已据此改为：raw `dense_discrete` profile 稳定分类；idle/export AA 对该
几何硬门禁；质量提示明确点名 high-raster-cost 通道；普通 smooth 低密度
曲线继续使用 idle AA。`setData()` debounce、25% buffer 和 10 Hz coarse
refresh 保留为次级防护，不再作为 AA 卡顿已经解决的替代证据。
