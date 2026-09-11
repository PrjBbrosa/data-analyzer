# TraceLab 自动范围与频谱显示正确性优化 Implementation Plan

> **执行更新（2026-09-11）：** 用户已明确授权按本计划安排 agent 执行。中立范围/Batch、FFT 画布、Pane 状态分别由 agent 实施；协调者负责热图接入、集成与验收。实施结果见 [验收记录](../verify/2026-09-11-analysis-auto-range-correctness.md)。

**Goal:** 自动坐标覆盖应显示的数据，缩放后保留频谱细节，主图、切片与 Batch 使用一致且可解释的范围规则。

**Architecture:** 在 `signal/` 增加无 GUI 依赖的显示范围计算；画布根据原始结果和当前可见范围生成绘图数据；分析 Pane 区分计算默认范围与用户缩放意图。沿用现有 DSP、结果缓存、Qt 画布及 Batch DTO，不在兼容 facade 扩展实现。

**Tech Stack:** NumPy、PyQt5、pyqtgraph、pytest/pytest-qt、现有 Batch Qt renderer；macOS Cocoa 实机用于最终显示与交互验收。

日期：2026-09-11。调查 HEAD：`a8d4b231`。状态：**T0–T6 已实施并完成 focused/边界及 Cocoa 合成数据、Batch 产物验收；Windows frozen 与客户原文件前台验收未执行**。集成 HEAD 为 `569fdc0c`，实施验收完成时尚未提交。

当前工作区已有“四项交互优化”的并行代码、测试及文档改动；尤其 `_analysis_mixin.py`、`analysis_section_page.py`、`hints.py`、`quickref.py` 存在共享路径。实施前重读这些文件，仅叠加本计划所需改动，不回退、覆盖或整文件暂存其他工作。

## 1. 调查依据与范围

以下是本次只读调查结果，不是未来实现的通过凭据。行号为调查定位，实施前按函数名定位。

| ID | 问题与证据 | 代码入口 | 任务 |
|---|---|---|---|
| R1 | Linear 切片使用 `hi - 200` 的 dB 过滤；Qt 探针将 `[0,100,200,900,1000] Pa` 自动显示为 `895..1005 Pa` | `qt_analysis_shared.py:_slice_amp_bounds`；`ui/pg_canvas/slice_panel.py:_apply_slice_amp_range`；`batch_render_qt/_builder.py:build_heatmap` | T1 |
| R2 | Batch 手动 X=0..200、自动 Y 时，范围外 0 dB 峰使可见的 -110..-90 dB 全部落在图外；Batch 场景得到 Y=-30..0 | `_builder.py:build_fft`、`_auto_db_line_limits` | T2 |
| R3 | 时频自动频段传入 `freq_range` 后被写成 `y_auto=False`；主图到 1000..2000 Hz 或 Home 到 12000 Hz，切片仍停在 0..200 | `heatmap_canvas.py:plot_result`；`slice_panel.py:_slice_axis_range` | T4 |
| R4 | GUI FFT、时频以 98% 能量频率乘 4 并取整裁频；24 kHz 合成数据含 10 kHz 弱峰仍得到自动上限 200 Hz；Batch 则取全频段 | `signal/adaptive.py:energy_band_fmax`；`main_window/window.py:_fft_auto_xlim`、`_fft_time_auto_freq_range` | T2/T4 |
| R5 | FFT 在完整频段上做 peak trace，再缩小 X；1188000 点、24 kHz、1000 像素探针：0..200 Hz 原有约 9900 bins，绘图只剩 17 点 | `line_canvas.py:_spectrum_plot_arrays`；`signal/envelope.py:build_peak_trace` | T3 |
| R6 | FFT GUI 与 Batch 自动 dB Y 使用 P99 下方 30 dB；真实低谷被裁；FFT Home 又使用另一套 Y 规则 | `line_canvas.py:_auto_db_y_range`；`_builder.py:_auto_db_line_limits` | T2 |
| R7 | FFT Home 用 `_last_xlim`，可能只是能量裁频范围；时频 Home 用完整 `_extents` | `line_canvas.py:reset_view_to_data_extents`；`heatmap_canvas.py:reset_view_to_data_extents` | T3/T5 |
| R8 | FFT/时频/阶次恢复旧视口只验证有限、非退化、存在交集；不区分自动捕获与用户缩放 | `_analysis_mixin.py:_capture_analysis_xy_viewports`、`_restore_analysis_pane_viewport` | T5 |

计划补充核对项：`_builder.py:_display_db_values` 在返回绘图数组前还执行 `max(EMPTY_DB_LEVEL, peak-200)` 截底。这是 R1/R6 的同类路径，T2 必须先用低幅值非零输入复现，再移除对真实有限 dB 值的截断；不得仅修 ViewBox 而保留已被修改的绘图值。

已检查的对照：时域 ChartOptions 自动 X 已从 raw X union 恢复；其 1 项回归和 FRF 范围/单位的 2 项回归在调查时通过。它们只证明各自测试场景，不代表全软件通过。

**不在本计划内：**

- 不改变采样率、导入器、时间重建、NFFT、窗函数、去均值、计权、PSD、FRF 估计或阶次计算。
- 用户所述 48 kHz 与截图 24 kHz 的差异尚未查明；需要原文件元数据另行调查，不能借本次坐标修复“校正”为 48 kHz。
- 不改热图自动色阶的 P99/30 dB 对比度规则、颜色映射、手动色阶的参考值平移规则。
- 不扩展四项交互优化、滑动按钮动效、全局工具栏改版。
- 不新增长期“能量聚焦”设置或预设字段。现有能量 helper 保持兼容；未来如需要聚焦操作，单独设计明确入口，不再隐含在默认“自动”内。

## 2. 产品与数值合同

### 2.1 自动范围

| 对象 | 本计划目标 |
|---|---|
| FFT 自动 X | 可见、已选择结果的有限非负频率并集；使用实际结果 bins，不凭文件卡片 Fs 推造上限 |
| 时频自动频率 Y | 当前结果完整有限频率范围；频率有效范围不由振幅或能量决定 |
| 阶次自动 Y | 保持当前结果实际 order extent；不套 Hz 或 Nyquist 规则 |
| FFT/切片自动幅值 Y | 当前可见 X 内原始结果的有效幅值并集，加上下留白；Linear 与 dB 规则显式区分 |
| Batch FFT/切片自动幅值 | 与交互 GUI 使用同一个中立 helper、同一个可见范围和有效值掩码；允许刻度美化，但最终范围必须包住 helper 范围 |
| 热图自动 Z | 继续为自动对比度，不承诺覆盖所有极值；仅改变色阶，不截断矩阵值 |

- 正常非退化 Y 范围上下各留 5%；常量 dB 用 ±1 dB，Linear 非零常量用 `abs(value)*0.05`，全零 Linear 用 ±1 当前轴单位。这些是显示回退，不是新增数据。
- 原始幅值为零/负值/非有限数时，dB 自动适配可排除这些不能表示有效对数幅值的点；必须来自线性原值掩码，不能按“比峰值低多少”猜测无效。
- Linear 中有限的零值、负值都保留；不得使用 200 数值单位阈值。dB 中非零真实深谷即使低于峰值 200 dB 也保留。
- 没有线性来源掩码的兼容调用，仅排除 NaN/Inf；不得将有效有限值当作人工底噪。全无效 dB 使用明确空数据路径，不继承上一条曲线的范围，不伪造 0 dB 信号。
- X/Y 必须同形、1D；掩码如存在必须同形。形状不匹配抛 `ValueError`，禁止 `min(len(x),len(y))` 静默截齐。空、单点、常量、NaN/Inf、float32/float64 均有针对性用例。
- 窗口无内部采样点但有穿越窗口的线段时，用真实相邻点计算边界交点供范围适配；绘图保留边界邻点，不能错误判成空图。跨 NaN 断点不得插值。

### 2.2 原始数据、绘图数据、用户意图区分

1. 原始 FFT bins/热图矩阵/来源时间序列不因缩放、Auto、Home 或图形尺寸改变。游标、标记、统计、导出数值读取原始结果。
2. peak trace 只决定每个像素桶画哪个现有频点，使用当前可见 X 和已实现的绘图区宽度；不能用它计算完整频率边界或真实 Y 最小值。
3. 时间预览仍使用现有所有已选来源，不能用处理后的频谱数据替代。
4. 自动策略与用户缩放是不同状态：勾选自动表示默认适配策略；用户缩放暂时覆盖该轴，界面显示“已缩放 · 自动范围暂停”。不能只亮着自动且无任何说明。
5. 只在用户实际改变范围时记录覆盖意图。重绘、程序投影、布局实现、自动范围捕获均不得产生用户覆盖。

### 2.3 视口与 Home 的优先级

| 触发 | 默认范围与缩放行为 |
|---|---|
| 用户初次计算/主动重新计算或改来源、时间段、分析参数后替换结果 | 清除该 Pane 临时缩放；按当前 Inspector 自动/手动设置得到范围 |
| 项目打开或缓存驱逐后，为恢复同一保存 View 而重建结果 | 属于恢复事务，不当作用户重新计算；恢复合法的 user/home/legacy 范围，自动来源重新适配 |
| 切换 View 后显示同一结果，或颜色、标题等外观重绘 | 恢复该 Pane 明确保存的用户缩放；自动捕获范围重新计算，不回写为手动意图 |
| 单位/参考值/坐标表示改变 | 保留合法 X 用户缩放，清除无法原样解释的幅值 Y 缩放；手动 Inspector 参数沿用既有显式换算合同 |
| 修改某轴 Inspector 范围或重新启用自动 | 清除此轴缩放覆盖；另一轴的明确覆盖独立保留 |
| Home / 查看全部 | FFT 使用完整频率及全结果有效幅值加留白；热图恢复完整时间、频率/阶次 extent，并同步切片；不改分析时间范围、DSP 或 Inspector 手动数值 |
| Home 后重新应用 Inspector 设置/重新计算 | 返回 Inspector 的自动或手动范围；旧 Home 范围不得反过来污染参数 |

Home 是当前视口命令：手动 Inspector 仍存在时，提示“查看全部 · 参数范围保留”；在下一次明确应用参数前保持该视口。热图 Home 后切片必须跟随主图，不能仍被旧手动切片范围锁住。FRF/时域既有 Home 不在本次扩展范围。

## 3. 文件与状态所有权

下列路径均相对仓库根目录 `/Users/donghang/Downloads/data analyzer`。

| 文件 | 责任 |
|---|---|
| 新建 `mf4_analyzer/signal/display_ranges.py` | 纯 NumPy：原始有效范围、可见样本/边界相交、Linear/dB 范围与 padding；不得导入 Qt/UI |
| `mf4_analyzer/qt_analysis_shared.py` | 保留既有公共 helper 兼容入口，明确幅值模式参数；色阶 helper 与线图范围分离 |
| `mf4_analyzer/ui/pg_canvas/line_canvas.py` | 完整原始 extent、可见 peak trace 刷新、Y 适配、Home、缩放信号 |
| `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`、`slice_panel.py` | 用户频率意图与有效范围分离；有效幅值 mask；主图/切片统一当前视口 |
| `mf4_analyzer/ui/main_window/window.py`、`_fft_mixin.py`、`_fft_time_mixin.py`、`_order_mixin.py` | 现有渲染入口传递结果与显示意图，不新增计算算法或跨 mixin 状态 |
| `mf4_analyzer/ui/analysis_view_state.py`、`main_window/_analysis_mixin.py` | Pane 的缩放来源和序列化、逐轴恢复事务；不由 canvas 维护另一份持久化意图 |
| `mf4_analyzer/ui/analysis_section_page.py` | 当前 Pane 范围覆盖提示及恢复入口，与已有布局、无障碍焦点保持一致 |
| `mf4_analyzer/ui/_axis_handle.py`、`ui/dialogs/chart_options.py` | 仅分析画布的设置读取/Apply 与 Pane 意图衔接；保留时域现有 raw-union 事务 |
| `mf4_analyzer/batch_render_qt/_builder.py` | 先解析 X，再按同一窗口适配 Y；保留真实绘图幅值；不改变 Batch DSP |
| `mf4_analyzer/ui/hints.py`、`quickref.py` | 自动、缩放暂停、Home、色阶说明同步更新 |

新增状态必须显式初始化并在 clear/full_reset/结果替换/teardown 对称清理：FFT 的原始 extent 与显示刷新缓存；热图的有效幅值 mask；Pane 的缩放来源。mask 不存进项目或预设，不以显示通道名作为缓存键。

## 4. 实施任务

### T0 — 固定当前范围与复现基线

**依赖：** 无。**Owner：** 同一执行者协调共享文件。

- [x] 记录当时 `git rev-parse HEAD`、`git status --short` 和本计划涉及文件的差异到 `.state/analysis-auto-range/`；保留其他任务修改。
- [x] 按 R1–R8 重读实际 owner，特别是正在变更的 `_analysis_mixin.py`；若函数位置变化，调整定位而非覆盖新版文件。
- [x] 将调查中三个新缺陷转为各 owner 的最小失败测试；测试断言原始值、有效窗口和真实画布范围，不只断言 checkbox 或 helper 被调用。
- [x] 记录失败原因。基线只运行对应失败用例及直接相关现有回归，不启动全量测试。

### T1 — 统一幅值范围，修 Linear 切片误判

**文件：** 新建 `signal/display_ranges.py`、`tests/signal/test_display_ranges.py`；修改 `qt_analysis_shared.py`、`heatmap_canvas.py`、`slice_panel.py`、`_order_mixin.py`、`_builder.py`；测试 `tests/ui/test_pg_heatmap_canvas.py`、`tests/test_batch_render_qt.py`。

- [x] 先写失败用例：Linear `[0,100,200,900,1000]` 全包；缩放到后两个值时适配 `895..1005`；整体缩放单位后范围同比变化；dB `[-300,-40,-20]` 的 -300 不被当作死值。
- [x] 建立中立 API，输入合同按 §2.1，禁止 GUI 依赖；签名及核心示例固定为：

```python
def line_amplitude_limits(values, *, amplitude_mode, valid_mask=None):
    """Return padded finite limits or None; validate 1D/equal shapes."""

def visible_line_values(x, y, xlim, *, valid_mask=None):
    """Return valid in-window values plus finite boundary intersections."""

# 新增 tests/signal/test_display_ranges.py 中的验收示例：
assert line_amplitude_limits(
    [0., 100., 200., 900., 1000.], amplitude_mode="amplitude"
) == (-50., 1050.)
assert line_amplitude_limits(
    [-300., -40., -20.], amplitude_mode="amplitude_db"
) == (-314., -6.)
```

- [x] 用线性来源形成 dB 有效 mask：`np.isfinite(raw) & (raw > 0)`；Linear 用 `np.isfinite(raw)`。GUI 时频在 `plot_result` 保存与显示矩阵同方向的 mask；Order 在转置原始幅值时同样转置 mask，并传入现有通用热图入口的新增可选参数 `amplitude_valid_mask`。
- [x] `plot_or_update_heatmap(..., amplitude_valid_mask=None)` 显式验证 mask 与矩阵同形；保存在画布拥有的 `_matrix_amp_valid`，清理/重绘对称更新。无 mask 兼容调用仅使用显示矩阵有限性。
- [x] 切片提取矩阵行/列时同步提取 mask，自动适配与右键 Y 适应都调用新 helper；Batch 在相同 slice picks 上提取原始矩阵 mask，不能仅 GUI 修复。
- [x] `_slice_amp_bounds` 保留可导入入口，迁移所有生产调用；不得继续让无模式参数的兼容签名隐式执行 200 dB 阈值。热图 `_auto_db_window` 不变。
- [x] 验证手动 Z、色条拖动、reference 平移不会改变矩阵和 mask；空、全零、全 NaN、常量、单点及跨 NaN 断点符合合同。

**Focused gate：** `tests/signal/test_display_ranges.py`；热图和 Batch 文件中新增的范围用例及既有 slice/manual-Z/reference 用例。新增用例失败→修改→通过必须分别记录。

### T2 — FFT GUI/Batch 的完整频段和自动 Y

**依赖：** T1。**文件：** `window.py`、`_fft_mixin.py`、`line_canvas.py`、`_builder.py`；测试 `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_analysis_multiview_integration.py`、`tests/test_batch_render_qt.py`。

- [x] 写 GUI/Batch 对照：频率 0..1000，0..200 中幅值 -110..-90 dB，外段 0 dB；手动 X=0..200、自动 Y 时，两条路径必须包住可见段且不受外段峰值控制。
- [x] 先复现 `_display_db_values` 对真实小幅值截底：reference=1、线性 `[1e-15,1]` 应对应 `[-300,0] dB`；本次代码不改变有效点转换值，也不把 NaN/Inf 伪装成正常平坦曲线。
- [x] `_fft_auto_xlim` 及两条 FFT 渲染入口改用实际有限频率 extent；多源取当前可见结果并集。`energy_band_fmax` 不删除、不改变 DSP 使用方或旧公共 API。
- [x] GUI 与 Batch 都先确定 X，再从原始结果提取可见有效幅值，使用 T1 helper 适配 Y；GUI 的 `amp_for_xlim` 可作为当前 raw linear 来源，必须验证长度匹配。
- [x] 替换 `_auto_db_y_range`/`_auto_db_line_limits` 的 P99-30 dB 线图规则；常量及空态采用 §2.1。手动 Y 按用户范围显示，不能被新 helper 强制放大。
- [x] 为 Linear 同样显式按当前可见原始数据适配，不依赖 pyqtgraph 默认是否启用了 `autoVisibleOnly`；Y 不从 peak trace 抽点数据推导。
- [x] 修改旧的“应裁掉低谷”测试预期，并增加原始曲线数组/统计数值未变的断言；保留热图色阶的原测试。

**Focused gate：** 上述三个测试文件中的 FFT auto/manual/overlay/reference 相关用例；新建的 GUI/Batch 对照必须实际构建画布与 Batch scene，不能仅让同一 helper 与自身比较。

### T3 — FFT 可见频段抽点与 Home

**依赖：** T2。**文件：** `line_canvas.py`、`signal/envelope.py`（仅在需要复用边界邻点选择时修改）；测试 `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_canvases_envelope.py`。

- [x] 复现 NFFT=1188000、Fs=24000、0..12000 Hz、1000 px，缩放 0..200 后绘图点仍只有约 17 个的问题。测试不要硬编码每次恰为 1000 个桶，而要证明窄窗按自己的像素宽度重建，且已知窗口内峰值保留。
- [x] `plot_spectra` 从完整 `_entries` 确定 raw extent；先确定目标 X，再调用 `_spectrum_plot_arrays(..., xlim=visible_xlim)`。保留 peak trace 每桶最大点，不改成 min/max 填充。
- [x] X 变化、滚轮、拖拽、框选、历史前进后退、Home、恢复视口、首次 show 和绘图区尺寸变化都进入同一显示刷新入口；范围未变、宽度未变、结果未变时复用缓存。
- [x] 连续交互使用已有节流/idle 生命周期合并刷新；离散绘图、Home、View 恢复在操作完成后可立即得到完整新窗口数据。刷新不提交 DSP，不重建曲线对象/图例，不产生新的用户缩放事件。
- [x] 新增窗口外紧邻的有效样本保留策略，使边缘线段连续；全数据 extent 从原始 `_entries` 读取，不从当前 PDI 反推。空窗不得保留旧曲线冒充新数据。
- [x] 更新频谱质量判定读取的实际 drawn point 数；保持 AA 最初关闭、离散 settle 独立 0 ms、交互 150 ms quiet timer 和校准阈值原值。
- [x] FFT Home 使用完整原始 frequency union，Y 使用完整有效幅值；底部时间预览沿用所有来源的完整时间范围。不得通过修改分析时间段实现 Home。

**Focused gate：** `test_pg_line_canvas.py` 的新增可见抽点、Home、resize、restore、AA settle 用例；若改变中立 envelope helper，再运行直接消费它的 `test_canvases_envelope.py` 相关用例。

### T4 — 时频自动意图与切片同步

**依赖：** T1/T3 的范围与 Home 合同。**文件：** `window.py:_fft_time_auto_freq_range`、`_fft_time_mixin.py:_render_fft_time_on`、`heatmap_canvas.py:plot_result`、`slice_panel.py`；测试 `test_pg_heatmap_canvas.py`、`test_analysis_multiview_integration.py`。

- [x] 添加经真实 `_render_fft_time_on` 入口的回归：Inspector 自动 Y，画布得到完整 0..12000；主图缩放 1000..2000，切片同步；Home 后两者均恢复完整频段。
- [x] 不仅测试直接 `plot_result(freq_range=None)`；当前已有此类裸画布测试通过，但它绕开了生产入口传入自动 `freq_range` 的缺陷。
- [x] `_fft_time_auto_freq_range` 返回实际结果频率范围；生产自动路径保留 `y_auto=True`，不以传入有效范围的方式把它改成 False。手动最小/最大只在用户关闭自动时形成手动约束。
- [x] 通用热图绘制保存用户意图与有效 viewport 分别对应的值；切片默认取主图当前可见频率/时间范围。用户输入手动范围时先应用主图，再同步切片；后续用户缩放或 Home 也必须同步。
- [x] Order 复用相同主图→切片同步规则，仍使用 order 坐标；手动幅值窗口与自动幅值按 T1 执行，不能因通用绘制入口重置 slice 状态而丢失。
- [x] 保护时间 coverage：主图使用 coverage_start/end，游标和切片索引仍使用 frame centers；不把此次频率修复扩展成时间轴重算。

**Focused gate：** 新增生产入口用例；既有 live-slice、manual-slice、Home、coverage、Order slice 用例。旧“手动面板范围始终忽略主图缩放”用例按本次统一可见视口合同改写。

### T5 — 逐轴保存真实缩放意图，明确自动暂停

**依赖：** T2–T4。**文件：** `analysis_view_state.py`、`_analysis_mixin.py`、`analysis_section_page.py`、`line_canvas.py`、`heatmap_canvas.py`、`ui/_axis_handle.py`、`ui/dialogs/chart_options.py`；测试 `tests/ui/test_analysis_view_state.py`、`tests/ui/test_analysis_multiview_integration.py`、`tests/test_project_io_analysis_views.py`、`tests/ui/test_dialogs.py`、`tests/ui/test_axis_handle.py`。

- [x] 先写三种失败场景：自动范围被旧程序捕获覆盖；只有 X 合法却因 Y 不合法整组无法恢复；新结果比旧结果宽但旧范围仅有交集就被误认为正确默认。
- [x] Pane 增加显式可序列化 `viewport_origin`，结构为 `{"x": "auto", "y": "auto"}`，允许值为 `auto/user/home/legacy`，由 `analysis_view_state.py` 初始化、拷贝、校验和 round-trip。现有 `xlim/ylim` 继续保存范围，不增加第二份范围数据。
- [x] canvas 只报告用户事件与受影响轴；新增独立 `viewport_action_committed` 信号携带 `(action, axes)`，保留现有无参数 `viewport_intent_committed` 兼容接口。MainWindow 使用新事件入口一次性捕获最终范围和更新 Pane 来源，禁止新旧信号重复提交。
- [x] `action` 只允许 `user/home`；ViewBox 手动事件、Home 和明确的图表设置 Apply 才发出；程序 setRange、布局和渲染不发出。由现有 mixin/coordinator 处理联动 Pane 的 X 来源，不新增 MainWindow 散落字段。
- [x] 分析画布的 ChartOptions 通过可选 handle 意图适配器读取/应用范围策略，不仅凭 ViewBox `autoRange` 位判断“自动”。对话框明确应用自动时更新该分析 View 对应轴的参数并清除覆盖；仅打开/取消不得改状态。适配器由分析协调层注入，公共 dialog/handle 不反向导入 MainWindow；未注入时保留时域/FRF 原行为。
- [x] 每轴独立执行 §2.3；`origin=auto` 不用已保存范围覆盖新计算结果。单轴失效只回退该轴。移除恢复失败时把自动 capture 再包装为用户意图的路径。
- [x] 同结果 View 切换及其恢复性重算可保留 `user/home/legacy`；用户主动产生新结果清除覆盖。来源/时间段改变依据现有结果身份和提交入口判定，恢复任务沿用现有项目/View 恢复事务标识，不能仅凭 result 对象变化判断；不用矩阵内容 hash 扫描大数组。
- [x] 旧项目没有 `viewport_origin`：有效 saved range 标为 `legacy` 并保留可恢复范围，UI 提示“已恢复保存范围”；不能声称它是自动结果。重新计算/重新应用自动后转为 `auto`，新保存写入明确来源。无效来源值记录诊断并按 `auto` 处理。
- [x] 当前 Pane 状态提示只显示实际覆盖轴，例如“X 已缩放 · 自动范围暂停”；单击“恢复参数范围”清除覆盖并按 Inspector 重绘。Home 若暂时覆盖手动参数，显示 §2.3 提示。焦点切换后提示来自当前 Pane，不能串到 FRF 或时域。
- [x] 不把 `viewport_origin` 存进分析预设/Batch recipe；它属于 View 用户浏览意图。嵌套 schema 版本按现有项目兼容约定升级并覆盖旧数据迁移；不修改产品版本号。

**Focused gate：** 上述文件的新增状态/恢复/迁移与分析 ChartOptions 用例；覆盖 FFT/时频/阶次、单 Pane、联动/不联动 split、来源关闭、项目打开触发重算、View 缓存驱逐、仅 X/仅 Y 覆盖。时域 ChartOptions 原范围事务为直接对照门。

### T6 — 帮助、边界与真实渲染验收

**依赖：** T1–T5。**文件：** `ui/hints.py`、`ui/quickref.py`；新建 `docs/analyzer/verify/2026-09-11-analysis-auto-range-correctness.md` 仅在实施验收时填写真实结果。

- [x] 帮助统一说明：自动频率显示完整结果；自动幅值适配当前窗口；缩放暂时覆盖自动；Home 查看全部；热图自动色阶是对比度策略。标注 None/Linear/dB 的实际作用，不增加模糊“智能优化”文案。
- [x] 完成变更 owner focused tests 后，协调者运行下述适用边界门；同一稳定快照不重复运行。
- [x] macOS Cocoa 用真实画布重现 §5 的可视场景，截图记录轴范围、切片、顶峰和低谷；对批量图片读取 scene ranges 并比较输出，不要求用户逐张判断。
- [x] 高频大 NFFT 场景记录首次显示、缩放刷新和 resize 的实际点数/耗时；对比修改前同机结果。不得只凭 offscreen 时间或“点数更少”宣称交互性能通过。
- [x] 文档登记 HEAD、相关 dirty scope、命令、结果、截图路径和平台。未执行 Windows frozen/macOS foreground 时明确记为未验证，不将源码测试代替平台验收。

## 5. 验收矩阵

| ID | 输入/动作 | 必须满足 |
|---|---|---|
| A1 | 实际 24 kHz / 48 kHz 结果，低频强峰和高频弱峰 | 自动全频分别到实际末 bin（典型约 12/24 kHz）；不能只到 200 Hz；无需更改采样率 |
| A2 | NFFT=1188000、24 kHz，缩放到 0..200 Hz | 重建可见 peak trace，已知窄峰保留；不再仅约 17 点铺满图；原始 bins 不变 |
| A3 | FFT dB 真实 -90..-15 含更深非零谷 | 顶峰、低谷均在自动 Y 内并有留白；不被固定 30 dB 或 200 dB 阈值裁掉 |
| A4 | Linear 切片 0,100,200,900,1000 | 自动范围 -50..1050；GUI 时频/Order 与 Batch 都包住全部；单位缩放保持等价 |
| A5 | Batch X=0..200，可见 -110..-90，外段 0 dB | 自动 Y 包住可见段；201 个点不会全部落在画外；GUI 与 Batch 使用同一数据窗口 |
| A6 | 时频主图缩放 1..2 kHz，再 Home | 切片先到 1..2 kHz，再恢复完整频段；生产入口而非裸画布必须通过 |
| A7 | 自动计算→用户缩放→切换 View→返回 | 缩放按 Pane 保留，显示暂停提示；重新自动或新计算后回到当前参数范围 |
| A8 | 旧项目 saved ranges、split 联动、仅单轴失效 | 旧范围可解释、逐轴处理、不串 View、不默默把旧范围当自动结果 |
| A9 | 空、常量、单点、NaN/Inf、零值、深谷、长度错误 | 满足 §2.1；明确空态/错误，无旧图残留，不静默截齐 |
| A10 | 手动 Z、自动色阶、reference 更改 | 色阶策略保持；矩阵/切片数值不被色阶裁断；Linear 不受 dB 过滤 |
| A11 | FFT Home、右键 Y 适应、图表设置、历史回退 | 原始 extent、当前显示、缓存抽点同步；不改变时间范围和 DSP |
| A12 | 时域/FRF 原有对照 | 时域自动 X raw-union 回归及 FRF Hz/log/coherence 范围回归不退化 |

## 6. 验证命令、交付与完成条件

所有运行测试使用项目运行时。每任务新增用例的命令形式：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/signal/test_display_ranges.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_render_qt.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_view_state.py tests/ui/test_analysis_multiview_integration.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_project_io_analysis_views.py -q
```

T0/T1–T5 先以新增 node ID/相关 `-k` 子集运行；上述 owner 文件完整命令仅作为该 owner 完成时的汇总门，不在每个子步骤重复执行。新失败才扩大相关范围。

适用边界门由 T6 协调者统一运行一次：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_signal_no_gui_import.py tests/test_batch_render_import_boundary.py tests/test_native_import_boundaries.py tests/test_packaging_imports.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_hints.py tests/ui/test_quickref.py tests/ui/test_dialogs.py::test_pg_chart_options_x_autorange_starts_from_full_data_extent tests/ui/test_frf_canvas.py::test_frf_canvas_log_xlim_and_cursor_keep_public_units_in_hz tests/ui/test_frf_canvas.py::test_frf_canvas_coherence_range_cursor_and_independent_y_ranges -q
git diff --check
```

- 若新增 QSS，另加 `tests/ui_kit/test_qss_border_shorthand.py`；无 QSS 修改不为凑检查运行。
- 默认不要求全量套件。本计划涉及多个显示 owner，但不做 DSP/架构大拆分；只有新跨边界失败、顺序污染、发布/合并门或用户明确要求才升级全量。升级时先检查现有 pytest 进程，记录稳定快照，主套件排除 acquisition_ui 后与其分开顺序运行。
- 修复过程如确认共享模式判错的复发教训，按项目 lessons 流程记录并晋升；计划编写本身不生成未经实施验证的新 lesson。
- 完成条件：R1–R8 均有任务落实，A1–A12 均填写证据/明确未通过项；focused/边界门通过；Cocoa 与批量产物验收有实际结果；不得以测试总数替代场景覆盖。
- 提交/推送仅在用户随后授权时执行；按命名路径审查和暂存，不吸收四项交互优化等无关修改。

**原计划编写阶段检查（历史）：** 当时只新增本 plan；检查引用路径、符号、任务覆盖及 `git diff --check`。未改变可执行行为，因此计划阶段不重跑 runtime suite；调查时的探针和 3 项回归仅列为历史调查证据。
