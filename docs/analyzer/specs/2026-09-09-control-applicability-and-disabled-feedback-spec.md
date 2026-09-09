# 控件适用条件与禁用反馈 Spec

日期：2026-09-09
状态：设计文档；产品实现未开始。本轮仅编写 Spec / Plan。
配套：[执行 Plan](../plans/2026-09-09-control-applicability-and-disabled-feedback-plan.md)

## 1. 目标与范围

批处理选择「每项单独」时，「叠加 / 分屏」实际不可操作，却仍显示正常选中高亮。解决此问题及横查确认的同类反馈缺口，使用户能区分当前选择、当前可操作性和设置的实际用途。

范围：共享 SegmentedChoice 的禁用呈现；Batch 图内布局、运行锁定、FFT 参数适用性、线性幅值下的 dB 参考，以及仅导出数据时的图片设置用途提示；主界面曲线绑定 X 轴作为共享控件消费者验收。

保持现有面板、按钮、配色体系和布局语言。不得扩大为界面重做，不新增通用依赖引擎，不修改 DSP、输出数值、分组算法、预设 schema、产品版本。此前的 Batch 首次打开宽度修复属于独立工作，必须保留。

## 2. 当前证据与边界

证据来自 2026-09-09 工作区，包含未提交修改；以下符号优先于可能漂移的行号。

| 位置 / 符号 | 已确认事实 |
| --- | --- |
| `mf4_analyzer/ui/drawers/batch/method_buttons.py:DynamicParamForm._sync_render_group_by` | none 分组已同时禁用隐藏 combo 与可见 SegmentedChoice，业务禁用没有遗漏 |
| `mf4_analyzer/ui_kit/style.qss` 的 segmentedChoice checked 规则 | 比通用 role=choice disabled 规则更具体，缺少同级禁用覆盖 |
| `mf4_analyzer/ui_kit/widgets/segmented_choice.py:_SelectionPill.paintEvent` | 动画底板固定绘制正常选中底色、边线，未按有效禁用状态分支 |
| `mf4_analyzer/ui/drawers/batch/sheet.py` 的运行锁定 / 解锁 | 通过父面板禁用子控件，必须覆盖祖先禁用，不仅覆盖控件自身 setEnabled |
| `mf4_analyzer/ui/inspector_sections/persistent_top.py:PersistentTop.set_curve_bound_xaxis_summary` | 曲线绑定 X 轴时禁用 choice_xaxis，共享选中白底问题同样存在 |
| `DynamicParamForm._sync_avg_mode`、`mf4_analyzer/batch_compute.py:resolve_fft_nfft / compute_fft_dataframe` | 单帧模式只禁用平均重叠；窗长及普通重叠率仍可编辑。单帧数值分支不消费这两项 |
| `mf4_analyzer/ui/drawers/batch/output_panel.py:OutputPanel._apply_method_axis_context / _on_amp_unit_changed` | dB 参考按方法显隐，没有按 Linear / dB 切换适用性 |
| `mf4_analyzer/batch_render_qt/_builder.py:build_fft / build_heatmap` | 线性值绘图不使用 dB 参考完成幅值换算 |
| `OutputPanel._sync_output_controls` | 当前为空实现；取消图片导出后，图片样式、坐标等仍可编辑 |

真实 Cocoa + Fusion 控件探针确认：图内布局及绑定 X 轴切换的 isEnabled 为 False，但选中按钮采样背景仍为白色；祖先锁定同样如此。单帧 FFT 对照计算改变窗长及普通重叠率后，数值数组完全相同。
这些证据不是整个主程序的前台逐项验收，也不是 Windows 冻结版本证据。临时探针位于 `.state/batch-control-audit/`，不作为版本化依赖。

## 3. 状态合同

控件状态由两个独立条件决定：业务是否适用，以及所属面板是否允许操作。最终可操作性必须同时满足两者。

- 当前选择保留：禁用不清空、不改选项、不触发业务参数改变。
- 禁用后撤掉正常白底、强调色文字和选中强调边线；保留低对比的选中区轮廓，允许识别先前所选值。
- 禁用状态使用已有 CONTROL_DISABLED_BG / CONTROL_DISABLED_LINE / CONTROL_TEXT_MUTED；不新增散落的颜色常量。
- 禁用 hover / pressed / focus 不得恢复正常高亮；不能经点击、键盘或滚轮改变选项。
- 重新启用恢复原选中项及正常外观；禁用切换不发 currentIndexChanged / paramsChanged。
- 正常动画及关闭动画两条绘制路径一致；动画中途禁用立即结束位移动画并呈现禁用状态。
- 业务原因由拥有控件语义的面板提供；共享 SegmentedChoice 不知道「每项单独」等业务词。
- 原因应出现在可见字段标签的 tooltip，必要时在设置区提供短说明；不只依赖禁用按钮接收 tooltip。
- 状态由现有参数推导，不持久化 enabled、提示文本、动画状态或另外一份当前选择。

## 4. 适用性矩阵

### 4.1 图内布局与锁定

| 条件 | 图内布局 | 提示与恢复 |
| --- | --- | --- |
| 时域，render_group_by=none | 保留选择，禁用并弱化 | 「每项单独输出时，图内布局不生效；合并图片后可设置。」 |
| 时域，按数据源 / 按信号 | 启用 | 恢复先前叠加 / 分屏选择 |
| Batch 运行中 | 所有原有锁定控件保持禁用 | 共享禁用样式生效；禁止因业务联动重新启用祖先锁定中的控件 |
| Batch 运行完成 / 失败 / 中断后 | 按业务条件重新投影 | none 分组仍禁用布局；不得一律点亮 |
| 主界面曲线绑定 X 轴 | choice_xaxis 保留现有业务禁用 | 复用现有绑定原因提示；解除绑定遵循现有状态恢复语义 |

本次不按当前文件数或信号数动态禁用分组卡片。只有一条曲线时提前配置后续分组仍是合理意图。

### 4.2 FFT 参数

只调整 Batch FFT 表单；其他分析方法沿用各自已有语义。

| FFT 条件 | NFFT 数值 | 窗长 t_win_s | 平均重叠 avg_overlap |
| --- | --- | --- | --- |
| 单帧 + Auto | 禁用 | 禁用 | 禁用 |
| 单帧 + Fixed | 启用 | 禁用 | 禁用 |
| 线性平均 / 峰值保持 + Auto | 禁用 | 启用 | 启用 |
| 线性平均 / 峰值保持 + Fixed | 启用 | 禁用 | 启用 |

FFT 的普通 overlap 字段从可见字段列表移除，避免与平均重叠同时出现；FFT 数值计算的分段重叠由 avg_overlap 决定。普通 overlap 在时频 / FRF 等适用方法中的可见性和行为保持。

禁用窗长的原因按条件显示：「单帧 FFT 不使用窗长设置」或「固定 NFFT 时，窗长由 NFFT 与采样率决定」。所有条件切换保留控件中已填值，不新增自动重置。

兼容约束：旧方案中的 overlap 可能进入 effective_facts 等元信息，不能因隐藏字段就清除、归一化改写或改变旧 payload 的行为。实现时需核对 get_params 对 visible_field_names 的依赖，保留既有序列化兼容路径；不能顺手改 DSP 或元信息语义。若发现必须改数值或历史字段解释才能实现，则暂停该扩展并修订 Spec。

### 4.3 线性幅值与 dB 参考

FFT / 时频 / 阶次使用 Linear 时，dB 参考整组禁用并弱化，包括模式选择、编辑器和相关动作入口；显示原因「线性幅值不使用 dB 参考」。返回 dB 后恢复原参考模式和值。

已有时域 / FRF 下隐藏参考行的规则保持。启用参考整组时，不得覆盖其内部 Auto / 手动模式所决定的子控件状态。不得因切换可用性触发重算、修改参考目录或重置参考值。

### 4.4 仅导出数据

取消 PNG 导出但保留 XLSX 时，图片设置仍可供预览使用，因此保留可编辑性。在输出设置区域显示一条紧凑、可换行说明：

> 当前仅导出数据；图片合并、图内布局、图片样式和显示范围仅用于预览，不改变 XLSX 数值。

说明也覆盖 FRF 图表组织、幅值显示等图片呈现设置，tooltip 可列出完整范围；不要每行重复新增标记。重新勾选图片后撤销该说明；两种导出都未选时沿用现有错误提示，不显示“仅导出数据”。

严格区分显示范围与用于计算的数据截取、滤波、目标信号、统计区间、切片输出：不得把会影响数据产物的控件一并标成“仅预览”。预览按钮的有效条件、运行条件、实际导出合同不变。

## 5. 所有权与兼容

- 共享外观：`ui_kit/widgets/segmented_choice.py` 和 `ui_kit/style.qss`；两者必须共同覆盖无动画与动画路径。
- 图内布局与 FFT 依赖：`DynamicParamForm`；复用现有 sync 方法，在构造、方法切换、用户操作、apply_params 后投影最终状态。
- 幅值单位、dB 参考、仅数据说明：`OutputPanel`；使用现有 changed / apply 方法，避免新的跨 MainWindow 状态。
- 运行锁定与解锁：`BatchSheet` 保持现有生命周期；仅在回归证明需要时修改相关同步，不扩大到 worker。
- 绑定 X 轴：`PersistentTop` 是共享消费者；已有业务逻辑不重复实现。
- 帮助文案：同步 `ui/hints.py` 与 `ui/quickref.py`，说明不可用原因与仅预览用途。
- 保留 combo 公共 API、选项身份、参数值和预设兼容；样式与适用性变化不得把方案变脏。

## 6. 验收标准

| ID | 验收 |
| --- | --- |
| A1 | none 分组下布局不能交互，选中区无正常高亮；切换分组恢复原值 |
| A2 | SegmentedChoice 自身禁用、祖先禁用、禁用期间 hover/focus、重新启用均正确；状态切换零参数信号 |
| A3 | 动画开 / 关及动画中禁用，底板、文字、边线一致，无残留正常选中底板 |
| A4 | Batch 运行锁定 / 解锁各出口后，分组限制仍生效；绑定 X 轴消费者同样正确 |
| A5 | FFT 四种模式组合符合矩阵；普通 overlap 不重复展示；旧参数往返及数值结果不改变 |
| A6 | Linear 禁用整组参考，返回 dB 原模式和值保留；时域 / FRF 隐藏规则保持 |
| A7 | XLSX-only 显示用途说明；PNG / 无输出时正确撤销；预览、数据截取和数据产物语义保持 |
| A8 | 方案导入、方法来回切换、首次打开、运行后恢复均无短暂错误状态；不引入宽度跳变或底部裁切 |
| A9 | hints / quickref 一致；真实 Cocoa + Fusion 像素与交互验证通过；Windows 冻结验证单独记录状态 |

## 7. 当前完成边界

本轮完成的是合同与执行步骤，不是修复。没有待用户选择的产品方案。实现前只需核对代码漂移、FFT 旧字段往返和共享控件动画测试接缝；发现与本合同冲突时先更新文档，不能把未知行为算成已验收。
