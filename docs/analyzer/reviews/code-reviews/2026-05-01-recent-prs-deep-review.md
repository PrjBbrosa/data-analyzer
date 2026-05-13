| ID | Severity P0/P1/P2 | PR | File:Line | One-line description |
|---|---|---|---|---|
| P7-L1 | P1 | PR #7 | mf4_analyzer/ui/inspector_sections.py:2132 | dB/Linear 切换只打开自动色阶但保留旧 Z 范围，用户再关自动会提交错误单位值。 |
| P8-L1 | P1 | PR #8 | mf4_analyzer/ui/drawers/batch/output_panel.py:128 | Batch OUTPUT 切换 Linear 后仍把旧 dB 手动范围传给图片导出。 |
| P10-L2 | P1 | PR #10 | mf4_analyzer/ui/dialogs.py:638 | ChartOptionsDialog 对数轴允许非正 limit，Matplotlib 会忽略用户输入。 |
| P7-D1 | P2 | PR #7 | mf4_analyzer/ui/main_window.py:81 | 旧 OrderWorker / _dispatch_order_worker 与 tests 仍维护废弃 compute_time_order_result 路径。 |
| P7-O1 | P2 | PR #7 | mf4_analyzer/ui/main_window.py:1501 | `_render_order_time` 注释仍描述已迁移的 dynamic 枚举。 |
| P7-T1 | P2 | PR #7 | tests/ui/test_inspector.py:1787 | FFTTimeContextual 缺少 unit-toggle 强制 z_auto 的对称测试。 |
| P8-O1 | P2 | PR #8 | mf4_analyzer/ui/style.qss:146 | compact spinbox stepper 样式使用全局 QSpinBox/QDoubleSpinBox 选择器。 |
| P10-L1 | P2 | PR #10 | mf4_analyzer/ui/widgets/searchable_combo.py:289 | 空模型已有过滤文本时添加首项会覆盖用户查询。 |

## PR #7 — COT Migration + Axis Settings UI Refactor

### 逻辑漏洞

**[P7-L1] mf4_analyzer/ui/inspector_sections.py:2132** — dB↔Linear 切换只打开自动色阶但保留旧 Z 数值
Problem: `OrderContextual._on_amp_unit_changed()` 只执行 `self.chk_z_auto.setChecked(True)` 和 `_sync_axis_enabled()`，没有重置、禁用语义外的值或按单位转换 `spin_z_floor/spin_z_ceiling`；`FFTTimeContextual._on_amp_unit_changed()` 在 `mf4_analyzer/ui/inspector_sections.py:2667` 也是同样实现。现有测试只断言 `chk_z_auto` 被打开，未覆盖用户切换单位后再关闭自动时旧 dB 范围会以 Linear 单位继续显示/提交。
Impact: 最小复现是把 Z 范围设为 `-70 → -20 dB`，切到 `Linear`，再关闭“自动”：界面会重新暴露 `-70 → -20` 这样的线性范围，传给 `plot_or_update_heatmap(..., amplitude_mode='amplitude', z_floor=-70, z_ceiling=-20)` 后可能得到不可读或全空的色阶。
Fix direction: 单位切换时为新单位写入合理默认 range，或清空/禁用手动 Z 值直到用户重新输入；同时补上 order 与 FFTTime 两个面板的 round-trip 测试。

**[P7-NC1] mf4_analyzer/batch_preset_io.py:22** — NOT CONFIRMED: `_migrate_axis_keys` 幂等性问题
Problem: `_migrate_axis_keys()` 明确在 `mf4_analyzer/batch_preset_io.py:27` 删除 `algorithm`，在 `mf4_analyzer/batch_preset_io.py:30` 只在缺少 `z_floor` 且存在 `dynamic` 时迁移旧动态范围，否则在 `mf4_analyzer/batch_preset_io.py:43` 移除残留 `dynamic`。运行覆盖 `30 dB`、`Auto`、malformed dynamic、以及已显式迁移 Z keys 的一次/两次调用对比，均得到相同 dict。
Impact: 未确认幂等性缺陷；当前风险是没有一个直接断言“一次迁移等于二次迁移”的单元测试，未来修改迁移逻辑时可能无意打破这个契约。
Fix direction: 不需要功能修复；建议把本次探针固化为 `_migrate_axis_keys` 的参数化单元测试。

### 死代码

**[P7-D1] mf4_analyzer/ui/main_window.py:81** — 旧 OrderWorker / _dispatch_order_worker 已脱离真实 COT UI 路径
Problem: `OrderWorker.run()` 仍调用已废弃的 `OrderAnalyzer.compute_time_order_result`，但 `do_order_time()` 现在在 `mf4_analyzer/ui/main_window.py:1378` 导入 `COTOrderAnalyzer` 并在 `mf4_analyzer/ui/main_window.py:1400` 同步计算；旧 `_dispatch_order_worker()` 只剩 `mf4_analyzer/ui/main_window.py:1428` 的定义和 `tests/ui/test_order_worker.py` 调用。保留下来的 `tests/ui/test_order_worker.py:10` 继续验证旧 worker 行为，容易把废弃异步路径误当成仍受支持的主流程。
Impact: 开发者会维护两套 order-time 计算路径，其中测试绿灯只能证明旧频域 worker 仍能跑，不能覆盖用户实际点击“时间-阶次谱”时走的 COT 分支；后续改动也可能错误复活 deprecated API。
Fix direction: 删除或明确隔离 `OrderWorker` / `_dispatch_order_worker` 旧路径及其 stale tests，若仍需要异步 COT，则新增 COT worker 并让 UI 与测试都覆盖同一条 COT 调用链。

### 乱引用

**[P7-NC2] mf4_analyzer/ui/canvases.py:1518** — NOT CONFIRMED: `_color_limits` 新签名调用错配
Problem: `_color_limits(self, z, amplitude_mode, z_auto, z_floor, z_ceiling)` 的生产调用只有 `mf4_analyzer/ui/canvases.py:1470`，该调用传入 `z, amplitude_mode` 并以关键字传入 `z_auto/z_floor/z_ceiling`。`rg "_color_limits\\(" mf4_analyzer tests` 只额外找到 `tests/ui/test_canvases_envelope.py:186` 和 `tests/ui/test_canvases_envelope.py:192`，两处也使用相同关键字名。
Impact: 未确认 argument count 或 keyword 名称错配；当前迁移面看不到残留 `dynamic` 参数直接调用 `_color_limits`。
Fix direction: 不需要功能修复；保留现有 signature 测试即可，若后续恢复公开调用面可增加 grep/AST check 防止 `dynamic=` 回流。

### 命名不一致

### 测试盲区

**[P7-T1] tests/ui/test_inspector.py:1787** — 缺少 FFTTimeContextual 的 unit-toggle 对称测试
Problem: 测试套件只在 `test_order_contextual_unit_toggle_forces_z_auto` 覆盖 `combo_amp_unit` 切换会强制 `chk_z_auto` 打开；`FFTTimeContextual._on_amp_unit_changed()` 在 `mf4_analyzer/ui/inspector_sections.py:2667` 拥有同样行为，但 `rg unit_toggle_forces_z_auto tests/ui/test_inspector.py` 没有 FFTTime 版本。现有 FFTTime 测试只覆盖轴控存在、axis keys、legacy dynamic 应用，未验证用户在 FFT-vs-Time 面板直接切换 dB/Linear 时的 guard。
Impact: 如果未来重构 `_make_axis_settings_group()`、signal wiring 或 FFTTimeContextual 方法名，order 面板测试仍会通过，但 FFT-vs-Time 面板可能保留旧 Z 范围并渲染错误单位。
Fix direction: 增加 `test_fft_time_contextual_unit_toggle_forces_z_auto`，构造 `FFTTimeContextual`、将 `chk_z_auto` 置 False、切换 `combo_amp_unit` 到另一单位，并断言 `chk_z_auto.isChecked()` 变 True。

### 其他

**[P7-O1] mf4_analyzer/ui/main_window.py:1501** — `_render_order_time` 注释仍描述已迁移的 dynamic 枚举
Problem: 注释写着 `OrderContextual` 暴露 `dynamic ∈ {'30 dB', '50 dB', '80 dB', 'Auto'}`，但当前 `OrderContextual.current_params()` 在 `mf4_analyzer/ui/inspector_sections.py:2298` 起返回显式 `x/y/z_auto` 与 `z_floor/z_ceiling`，不再返回 `dynamic`。紧随其后的实际渲染调用在 `mf4_analyzer/ui/main_window.py:1524` 读取 `z_auto/z_floor/z_ceiling`，与注释不一致。
Impact: 后续维护者可能按注释恢复旧 `dynamic` 字符串路径，或者误判 canvas 仍由旧枚举驱动，增加迁移期回归风险。
Fix direction: 将注释改为“从 `OrderContextual.current_params()` 读取 `amplitude_mode` 兼容键和显式 Z 范围键”，或删除关于 `dynamic` 枚举的旧说明。

## PR #8 — Batch Axes / FFT-Time Polish

### 逻辑漏洞

**[P8-L1] mf4_analyzer/ui/drawers/batch/output_panel.py:128** — Batch OUTPUT dB↔Linear 切换保留旧手动 Z 范围
Problem: `OutputPanel` 的 `combo_amp_unit.currentTextChanged` 只触发 `changed.emit()`，没有像 Inspector 那样强制 `chk_z_auto`、重置或转换 `spin_z_floor/spin_z_ceiling`；`axis_params()` 随后在 `mf4_analyzer/ui/drawers/batch/output_panel.py:205` 起把旧 `z_floor/z_ceiling` 和新的 `amplitude_mode` 一起写入 preset。`BatchRunner._write_image()` 在 `mf4_analyzer/batch.py:668` 起直接把手动 Z 范围作为 `vmin/vmax`，Linear 模式下仍会使用旧 dB 数值。
Impact: 最小复现是在 Batch OUTPUT 中关闭 Z 自动、设 `-40 → -5 dB`，切到 `Linear` 后运行导出；线性振幅通常为正数，却会用 `vmin=-40, vmax=-5` 渲染，图片色阶可能整体饱和，属于可见错误输出。
Fix direction: Batch OUTPUT 的单位切换应与 Inspector 统一：切换单位时打开 `chk_z_auto` 或写入该单位的合理默认范围，并补一条 `axis_params()` / `_write_image()` 的 Linear 手动范围回归测试。

### 死代码

### 乱引用

### 命名不一致

### 测试盲区

### 其他

**[P8-O1] mf4_analyzer/ui/style.qss:146** — compact spinbox 样式使用全局 QSpinBox/QDoubleSpinBox 选择器
Problem: 用于收回 padding 和隐藏 stepper 的规则写成全局 `QSpinBox, QDoubleSpinBox` 以及全局 `QSpinBox::up-button/down-button`，会作用到整个应用的所有 spinbox，而不只是不带按钮的 `CompactDoubleSpinBox` 或 Inspector 轴控。`tests/ui/test_inspector.py:2217` 只验证 Inspector 子树，无法发现 `ChartOptionsDialog`、batch drawer、ChannelEditor 等 sibling widgets 被同一全局规则影响。
Impact: 最小影响是任意未来新增的普通 `QSpinBox` 即使需要原生 stepper，也会被全局 QSS 隐藏按钮区域；当前 dialog/drawer 也隐式依赖这条全局规则，样式边界不清会让后续局部 UI 调整互相污染。
Fix direction: 给 `CompactDoubleSpinBox` 或需要无按钮的 spinbox 设置专用 property/objectName，并把 padding/subcontrol 规则收敛到该 selector 或具体容器；同时增加非 Inspector 的样式边界测试。

## PR #10 — Chart Options Dialog

### 逻辑漏洞

**[P10-L1] mf4_analyzer/ui/widgets/searchable_combo.py:289** — 空模型已有过滤文本时添加首项会覆盖用户查询
Problem: `SearchableComboBox.addItem()` 直接调用 `super().addItem()`；当 combo 为空且 `lineEdit().text()` 已是用户输入时，Qt 会把新插入的第一个 item 设为当前项并覆盖 line edit。最小序列“空 combo → `lineEdit().setText('abc')` → `addItem('AlphaBeta')`”后，line edit 从 `abc` 变成 `AlphaBeta`，`currentIndex()` 变为 0。
Impact: 如果通道列表在用户输入期间刷新或从空模型异步填充，用户的查询会被第一条候选吞掉，completer 也会按第一项而不是原查询过滤；现有 `tests/ui/test_searchable_combo.py` 只覆盖先加项再过滤、clear 后 addItems、单项 popup 展示，没有这个空模型先输入边界。
Fix direction: 在空模型 mutation 时保存 line-edit 查询和 current index，插入后恢复查询并重新设置 proxy filter；同时新增空模型先输入、单项添加、快速连续输入刷新候选项的回归测试。

**[P10-L2] mf4_analyzer/ui/dialogs.py:638** — 对数轴允许提交非正范围，Matplotlib 会静默忽略 limit
Problem: `_apply_axis()` 先 `set_yscale("log")`，随后在未校验 `vmin/vmax > 0` 的情况下调用 `set_ylim(float(vmin), float(vmax))`；X 轴在 `mf4_analyzer/ui/dialogs.py:631` / `mf4_analyzer/ui/dialogs.py:635` 也同理。最小复现是打开 dialog、把 Y 刻度切到“对数”、输入 `min=-1, max=10` 后应用，Matplotlib 只发出 `Attempt to set non-positive ylim on a log-scaled axis will be ignored` warning 并把下限改成自动正值。
Impact: 用户看到“应用”成功，但图表范围不是输入值，且 warning 不会在 UI 中呈现；这是 chart-options dialog 的可见编辑失败。
Fix direction: 对 log scale 的 X/Y 范围做前置校验，非正值时阻止应用并提示用户，或自动钳制到最小正数并在字段中回写实际值；补上 log scale 非正 limit 测试。

### 死代码

### 乱引用

### 命名不一致

### 测试盲区

### 其他

**[P10-NC1] mf4_analyzer/ui/chart_stack.py:231** — NOT CONFIRMED: ChartOptionsDialog 主窗口入口或 parent 断链
Problem: `MainWindow` 在 `mf4_analyzer/ui/main_window.py:201` 创建 `ChartStack(self)`，`_ChartCard` 在 `mf4_analyzer/ui/chart_stack.py:231` 创建 `chartOptionsButton` 并在 `mf4_analyzer/ui/chart_stack.py:238` 连接到 `open_chart_options()`，后者在 `mf4_analyzer/ui/chart_stack.py:381` 转调当前 canvas 的 `open_chart_options_dialog()`。canvas helper 在 `mf4_analyzer/ui/canvases.py:71` 选择 live axes，并在 `mf4_analyzer/ui/canvases.py:80` 调用 `edit_chart_options_dialog(canvas.parent(), ax)`，最终 `mf4_analyzer/ui/_axis_interaction.py:109` 以该 parent 构造 `ChartOptionsDialog`。
Impact: 未确认从主窗口不可达或 parent 为错误对象的问题；当前路径能从 toolbar 按钮和双击事件进入，parent 会落在承载 canvas 的 Qt 父组件上。
Fix direction: 不需要功能修复；建议补一个 MainWindow/ChartStack 级测试，monkeypatch `ChartOptionsDialog` 捕获 parent，断言它是当前 chart card 或其窗口层级子组件。

**[P10-NC2] mf4_analyzer/ui/widgets/searchable_combo.py:249** — NOT CONFIRMED: single-item / rapid-keystroke / focus-loss crash
Problem: `lineEdit().textChanged` 直接连接 `_proxy_model.setFilterText`，复核 single item 后过滤、快速设置 `a → al → alp → "" → tor`、以及输入后 `clearFocus()` 的序列，没有发现崩溃、异常或 proxy rowCount 不可用。已确认的问题限于 `mf4_analyzer/ui/widgets/searchable_combo.py:289` 的空模型先输入再添加首项会覆盖查询。
Impact: 未确认 single item、rapid keystroke 或 focus-loss race 会造成 crash；这些边界仍缺少测试，未来重构 proxy/completer 绑定时可能回归。
Fix direction: 将本次边界序列补进 `tests/ui/test_searchable_combo.py`，并把已确认的空模型查询覆盖问题作为失败用例。
